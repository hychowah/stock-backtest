"""Own an application controller and descendants, independently of its checks.

Limits apply before application effects. Controller results remain provisional
until transport, descendant and native-resource closure are confirmed. Unsupported
guarantees never become qualified through samples or caller declarations.

Windows reuses OwnedProcess's suspended-start job. Linux requires a private
transient user service; it never falls back to session-only containment. These
are known-source resource domains, not hostile-code or filesystem sandboxes.
The outside supervisor and its service-manager client are explicitly outside
the application domain. No financial assets or modules are accessed here.
"""
from dataclasses import dataclass
import math
import os
from pathlib import Path
import subprocess
import time
import uuid

from bench_candidates_process import OwnedProcess, ProcessLimits, user_cpu_ticks


@dataclass(frozen=True)
class DomainLimits:
    memory_bytes: int
    tasks: int
    cpu_percent: int
    wall_seconds: float
    user_cpu_seconds: float
    processes: int = 8
    output_bytes: int = 1024 * 1024
    close_seconds: float = 5.

    def __post_init__(self):
        user_cpu_ticks(self.user_cpu_seconds)
        self.process_limits()
        if (type(self.tasks) is not int or self.tasks <= 0
                or type(self.wall_seconds) not in (int, float)
                or not math.isfinite(self.wall_seconds) or self.wall_seconds <= 0):
            raise ValueError('Unsupported domain limits.')

    def process_limits(self):
        return ProcessLimits(self.memory_bytes, self.processes, self.cpu_percent,
                             output_bytes=self.output_bytes, close_seconds=self.close_seconds,
                             user_cpu_seconds=self.user_cpu_seconds)


class _UserService(OwnedProcess):
    """A unique fixture unit; only its own unit can be stopped or queried.

    The service manager applies limits before exec. A process changing session
    remains in this cgroup. Arbitrary same-user cgroup migration is outside this
    known-source contract. No existing unit or shared scope is configured.
    """
    def __init__(self, command, *, limits, env=None):
        self.unit = 'cb02-domain-' + uuid.uuid4().hex + '.service'
        self.domain_limits = limits
        self.cgroup = None
        self.invocation = None
        self.configuration = None
        self._stop_confirmed = False
        self._creation_settled = False
        # A missing manager can be rejected before any creation request exists.
        # After launch, client exit alone can never supply this proof.
        runtime = os.environ.get('XDG_RUNTIME_DIR', '/run/user/' + str(os.getuid()))
        address = 'unix:path=' + runtime + '/bus'
        # systemctl's local-user route and systemd-run's environment route must
        # name the same bus. Arbitrary alternate buses are unsupported here.
        for configuration in (os.environ, env or os.environ):
            if (configuration.get('DBUS_SESSION_BUS_ADDRESS', address) != address
                    or configuration.get('XDG_RUNTIME_DIR', runtime) != runtime):
                raise OSError('Experimental user-service bus binding is unsupported.')
        probe = subprocess.run(['systemctl', '--user', 'show', '--property=Version'],
            capture_output=True, text=True, timeout=limits.close_seconds)
        if probe.returncode or not probe.stdout.startswith('Version='):
            raise OSError('Experimental user-service manager is unavailable.')
        properties = dict(MemoryMax=str(limits.memory_bytes), MemorySwapMax='0',
            TasksMax=str(limits.tasks), CPUQuota=str(limits.cpu_percent * (os.cpu_count() or 1)) + '%',
            RuntimeMaxSec=str(limits.wall_seconds), TimeoutStopSec=str(limits.close_seconds),
            KillMode='control-group', SendSIGKILL='yes', OOMPolicy='kill', NoNewPrivileges='yes')
        prefix = ['systemd-run', '--user', '--quiet', '--pipe', '--wait', '--collect', '--unit=' + self.unit]
        for name, value in properties.items(): prefix += ['--property=' + name + '=' + value]
        # systemd-run --pipe passes descriptors to the service. Only explicit
        # non-secret execution settings are forwarded, not the user's full env.
        if env is not None:
            for name, value in env.items():
                if name in ('TMPDIR', 'TEMP', 'TMP', 'PYTHONDONTWRITEBYTECODE', 'NUMBA_CACHE_DIR',
                            'MPLCONFIGDIR', 'NUMBA_NUM_THREADS', 'OMP_NUM_THREADS',
                            'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
                    prefix += ['--setenv=' + name + '=' + value]
        super().__init__(prefix + ['--', *map(str, command)], env=env, limits=limits.process_limits())

    def _control(self, *arguments):
        # Bounded control calls cannot hard-preempt a blocked kernel/manager.
        return subprocess.run(['systemctl', '--user', *arguments], capture_output=True,
                              text=True, timeout=self._close_seconds)

    def _state(self):
        result = self._control('show', self.unit, '--no-pager',
            '--property=LoadState,ActiveState,SubState,ControlGroup,InvocationID,Job,Result')
        rows = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if 'LoadState' not in rows:
            raise OSError('Experimental service state is unavailable.')
        invocation = rows.get('InvocationID')
        if self.invocation and invocation and invocation != self.invocation:
            raise OSError('Experimental service identity changed.')
        if invocation: self.invocation = invocation
        group = rows.get('ControlGroup')
        if group:
            path = Path('/sys/fs/cgroup') / group.lstrip('/')
            if (not path.is_relative_to('/sys/fs/cgroup') or '..' in path.parts
                    or path.name != self.unit or (self.cgroup and path != self.cgroup)):
                raise OSError('Experimental service group changed.')
            self.cgroup = path
        return rows

    def _created(self):
        deadline = time.monotonic() + self._close_seconds
        while True:
            state = self._state()
            if self.cgroup and self.invocation and (self.cgroup / 'cgroup.procs').exists():
                # Read effective kernel controls; source declarations alone
                # never establish that delegation applied the requested limits.
                self.configuration = {name: (self.cgroup / name).read_text().strip() for name in
                    ('memory.max', 'memory.swap.max', 'pids.max', 'cpu.max')}
                expected = self.domain_limits
                quota, period = self.configuration['cpu.max'].split()
                if (int(self.configuration['memory.max']) != expected.memory_bytes
                        or self.configuration['memory.swap.max'] != '0'
                        or int(self.configuration['pids.max']) != expected.tasks
                        or quota == 'max' or int(quota) / int(period) >
                        expected.cpu_percent * (os.cpu_count() or 1) / 100 + .001):
                    raise OSError('Experimental service limits were not applied.')
                self._creation_settled = True
                return
            if self.process.poll() is not None or time.monotonic() >= deadline:
                raise OSError('Experimental user-service containment is unavailable.')
            time.sleep(.01)

    def _stop_tree(self, code):
        # A loaded unit can outlive systemd-run and its output pipes. Stop the
        # unit independently. A failed stop retains the complete process owner.
        state = self._state()
        if state['LoadState'] != 'not-found':
            result = self._control('stop', self.unit)
            if result.returncode:
                # A --collect unit can disappear between show and stop. Only
                # previously verified creation can accept this race. A dead
                # client and repeated absence still cannot settle creation.
                if not self._creation_settled or self._state()['LoadState'] != 'not-found':
                    raise OSError('Experimental service stop is unconfirmed.')
            # A successful manager-bound stop settles the registered creation,
            # even if cancellation preceded the cgroup's first process.
            self._creation_settled = True
            self._stop_confirmed = True
        elif not self._creation_settled:
            # A queued StartTransientUnit request can survive its client.
            # Repeated absence, including after client exit, cannot settle it.
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=self._close_seconds)
            raise TimeoutError('Experimental service creation closure is unconfirmed.')
        else:
            self._stop_confirmed = True

    def wait_empty(self):
        deadline = time.monotonic() + self._close_seconds
        while True:
            state = self._state()
            absent = state['LoadState'] == 'not-found'
            inactive = state.get('ActiveState') in ('inactive', 'failed') and state.get('Job', '0') == '0'
            populated = None
            if self.cgroup:
                try:
                    populated = dict(line.split() for line in
                                     (self.cgroup / 'cgroup.events').read_text().splitlines())['populated']
                except FileNotFoundError: populated = '0'
            if (self._creation_settled and self._stop_confirmed and (absent or inactive)
                    and populated in (None, '0') and self.process.poll() is not None):
                self.descendants_empty = True
                return
            if time.monotonic() >= deadline:
                raise TimeoutError('Experimental service closure is unconfirmed.')
            time.sleep(.01)

    def _session_members(self):
        if not self.cgroup: return []
        # Cgroup membership survives setsid and leader exit. No process-session
        # scan is promoted into domain containment.
        members = set()
        try:
            for path in self.cgroup.rglob('cgroup.procs'):
                try: members.update(map(int, path.read_text().split()))
                except FileNotFoundError: continue
        except FileNotFoundError: pass
        return sorted(members)

    def capabilities(self):
        def item(bound, status, mechanism):
            return dict(bound=bound, status=status, mechanism=mechanism,
                        scope='application_controller_and_known_source_descendants_including_compiler')
        p = self.domain_limits
        return dict(containment=item(None, 'hard', 'private systemd user-service cgroup; setsid stays contained'),
            charged_memory=item(p.memory_bytes, 'hard', 'cgroup memory.max including charged file cache; swap disabled'),
            resident_memory=item(None, 'unsupported', 'shared mapped pages can be charged outside this cgroup'),
            committed_memory=item(None, 'unsupported', 'memory.max is not a virtual commit bound'),
            threads=item(p.tasks, 'hard', 'pids.max counts threads and processes together'),
            processes=item(p.tasks, 'hard', 'shared task budget; not an independent process budget'),
            cpu_rate=item(p.cpu_percent, 'hard', 'cpu.max quota; percent of discovered logical CPU count'),
            cpu_time=item(None, 'unsupported', 'allocation is not a cumulative CPU-time limit'),
            user_cpu_time=item(p.user_cpu_seconds, 'unsupported',
                              'no cumulative user-time enforcement; cpu.max limits allocation only'),
            disk=item(None, 'unsupported', 'no aggregate filesystem quota'),
            wall=item(p.wall_seconds, 'hard', 'service RuntimeMaxSec plus TimeoutStopSec; not blocked-kernel preemption'),
            transport=item(p.output_bytes, 'hard', 'bounded frames, total bytes and pending event queue'))

    def closure(self):
        value = super().closure()
        value.update(descendant_scope='private_user_service_cgroup', unit=self.unit,
                     invocation=self.invocation, service_stop_confirmed=self._stop_confirmed,
                     creation_settled=self._creation_settled,
                     kernel_configuration=self.configuration)
        return value


def start_controller(command, limits, *, env=None):
    """Start one known experimental controller; no financial admission is granted.

    Windows contains the controller in its pre-bootstrap job. Linux requires
    the private user-service backend. Unsupported platforms do not fall back.
    """
    if os.name == 'nt':
        return _WindowsController(command, env=env, limits=limits.process_limits())
    if os.sys.platform == 'linux':
        return _UserService(command, env=env, limits=limits)
    raise OSError('Experimental controller containment is unsupported.')


class _WindowsController(OwnedProcess):
    def capabilities(self):
        value = super().capabilities()
        for resource in value.values():
            resource['scope'] = 'application_controller_and_descendants_including_compiler'
        value['cpu_time'] = dict(bound=None, status='unsupported',
            mechanism='user-time threshold excludes kernel CPU time', scope='application_domain')
        value['wall'] = dict(bound=None, status='cooperative',
            mechanism='external supervisor deadline; not blocked-kernel preemption', scope='application_domain')
        return value
