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

from backtest.runtime.process_owner import OwnedProcess, ProcessLimits, user_cpu_ticks


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
    def __init__(self, command, *, limits, env=None, hierarchy=None, role=None):
        self.unit = (hierarchy[role] if hierarchy else 'cb02-domain-' + uuid.uuid4().hex + '.service')
        self.domain_limits = limits
        self.hierarchy = hierarchy
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
        if hierarchy:
            properties['Slice'] = hierarchy['slice']
            if role == 'application':
                properties.update(BindsTo=hierarchy['helper'], After=hierarchy['helper'])
            else:
                properties.update(StartLimitIntervalSec='infinity', StartLimitBurst='1', Restart='no')
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
                if self.hierarchy and self.cgroup.parent.name != self.hierarchy['slice']:
                    raise OSError('Experimental ancestor membership mismatch.')
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


def start_controller(command, limits, *, env=None, hierarchy=None, role=None):
    """Start one known experimental controller; no financial admission is granted.

    Windows contains the controller in its pre-bootstrap job. Linux requires
    the private user-service backend. Unsupported platforms do not fall back.
    """
    if os.name == 'nt':
        return _WindowsController(command, env=env, limits=limits.process_limits())
    if os.sys.platform == 'linux':
        return _UserService(command, env=env, limits=limits, hierarchy=hierarchy, role=role)
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


@dataclass(frozen=True)
class LifetimeLimits:
    """Aggregate charged-memory/task/CPU allocation for a private WSL hierarchy."""
    memory_bytes: int
    tasks: int
    cpu_percent: int

    def __post_init__(self):
        if (any(type(v) is not int or v <= 0 for v in
                (self.memory_bytes, self.tasks, self.cpu_percent)) or self.cpu_percent > 100):
            raise ValueError('Unsupported lifetime limits.')


@dataclass(frozen=True)
class NativeLifetimeLimits:
    """Windows aggregate commit/process/rate/user-time; never WSL task limits."""
    committed_bytes: int
    processes: int
    cpu_percent: int
    user_cpu_seconds: float

    def __post_init__(self):
        if (type(self.committed_bytes) is not int or not 0 < self.committed_bytes < 2**63
                or type(self.processes) is not int or not 0 < self.processes < 2**32):
            raise ValueError('Unsupported native lifetime limits.')
        self.process_limits()

    def process_limits(self, *, output_bytes=1024*1024, close_seconds=5.):
        return ProcessLimits(self.committed_bytes, self.processes, self.cpu_percent,
            user_cpu_seconds=self.user_cpu_seconds, output_bytes=output_bytes,
            close_seconds=close_seconds)


def parse_lifetime(value):
    """Validate exact resource meanings without platform conversion or effects."""
    from tools.experiments.bench_comparison import ComparisonError
    try:
        if not isinstance(value, dict): raise ValueError()
        if set(value) == {'memory_bytes', 'tasks', 'cpu_percent'}:
            return LifetimeLimits(**value)
        if (set(value) == {'kind', 'committed_bytes', 'processes', 'cpu_percent', 'user_cpu_seconds'}
                and value['kind'] == 'windows-job'):
            return NativeLifetimeLimits(**{k:v for k,v in value.items() if k != 'kind'})
    except (ValueError, TypeError, OverflowError):
        pass
    raise ComparisonError('unsupported')


class LifetimeDomain:
    """Own supervisor and application resources through collection and closure.

    Effective ancestor controls cover their shared lifetime. Application exit
    does not release the boundary. Unknown creation or closure retains ownership
    for explicit recovery. The caller registers this object before prepare().
    WSL changes only generated transient units. Windows reuses the existing
    native job owner. No persistent unit or runtime registration is installed.
    """
    def __new__(cls, limits, application_limits):
        if cls is LifetimeDomain and isinstance(limits, NativeLifetimeLimits):
            if os.name != 'nt':
                from tools.experiments.bench_comparison import ComparisonError
                raise ComparisonError('unsupported')
            return object.__new__(_WindowsLifetimeDomain)
        return object.__new__(cls)

    def __init__(self, limits, application_limits):
        if os.sys.platform != 'linux':
            from tools.experiments.bench_comparison import ComparisonError
            raise ComparisonError('unsupported')
        token = uuid.uuid4().hex
        self.names = dict(slice='cb02life' + token + '.slice',
                          helper='cb02-helper-' + token + '.service',
                          application='cb02-application-' + token + '.service')
        self.limits, self.application_limits = limits, application_limits
        self.owned = None
        self.created = self.closed = False
        self.requested = False
        self.go = False
        self.application_settled = False
        self.configuration = self.cgroup = None
        self.final_memory_events = None
        self.final_task_events = None

    def _control(self, *args):
        return subprocess.run(['systemctl', '--user', *args], capture_output=True,
            text=True, timeout=self.application_limits.close_seconds)

    def _state(self, unit):
        r = self._control('show', unit, '--no-pager',
            '--property=LoadState,ActiveState,ControlGroup,Job,Transient')
        rows = dict(line.split('=', 1) for line in r.stdout.splitlines() if '=' in line)
        if 'LoadState' not in rows: raise OSError('Lifetime state unavailable.')
        return rows

    def prepare(self):
        # Same local user bus as the existing service backend, before creation.
        runtime = os.environ.get('XDG_RUNTIME_DIR', '/run/user/' + str(os.getuid()))
        if os.environ.get('DBUS_SESSION_BUS_ADDRESS', 'unix:path=' + runtime + '/bus') != 'unix:path=' + runtime + '/bus':
            raise OSError('Lifetime bus binding unsupported.')
        r = self._control('show', '--property=Version')
        if r.returncode or not r.stdout.startswith('Version='):
            raise OSError('Lifetime manager unavailable.')
        p = self.limits
        args = ['busctl', '--user', 'call', 'org.freedesktop.systemd1',
            '/org/freedesktop/systemd1', 'org.freedesktop.systemd1.Manager',
            'StartTransientUnit', 'ssa(sv)a(sa(sv))', self.names['slice'], 'fail', '5',
            'MemoryMax', 't', str(p.memory_bytes), 'MemorySwapMax', 't', '0',
            'TasksMax', 't', str(p.tasks), 'CPUQuotaPerSecUSec', 't',
            str(p.cpu_percent * (os.cpu_count() or 1) * 10000),
            'CollectMode', 's', 'inactive-or-failed', '0']
        self.requested = True
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=self.application_limits.close_seconds)
        deadline = time.monotonic() + self.application_limits.close_seconds
        while True:
            state = self._state(self.names['slice'])
            if state.get('ControlGroup'):
                group = Path('/sys/fs/cgroup') / state['ControlGroup'].lstrip('/')
                if group.name != self.names['slice'] or '..' in group.parts:
                    raise OSError('Lifetime group changed.')
                self.cgroup = group
                try:
                    config = {n: (group/n).read_text().strip() for n in
                              ('memory.max','memory.swap.max','pids.max','cpu.max')}
                except FileNotFoundError: config = None
                if config:
                    quota, period = map(int, config['cpu.max'].split())
                    if (int(config['memory.max']) != p.memory_bytes or config['memory.swap.max'] != '0'
                            or int(config['pids.max']) != p.tasks
                            or quota/period > p.cpu_percent*(os.cpu_count() or 1)/100+.001):
                        raise OSError('Lifetime controls not applied.')
                    self.configuration = config; self.created = True
                    return
            if result.returncode or time.monotonic() > deadline:
                raise OSError('Lifetime creation unconfirmed.')
            time.sleep(.01)

    def start(self, command):
        if not self.created: raise OSError('Lifetime is not configured.')
        p, a = self.limits, self.application_limits
        # Manager deadline includes a finite mechanical close interval. The
        # caller still rejects whole-operation overruns at the original bound.
        limits = DomainLimits(p.memory_bytes, p.tasks, p.cpu_percent,
            a.wall_seconds + a.close_seconds, a.user_cpu_seconds,
            processes=a.processes, output_bytes=a.output_bytes, close_seconds=a.close_seconds)
        try:
            self.owned = start_controller(command, limits, hierarchy=self.names, role='helper')
        except BaseException as error:
            self.owned = getattr(error, 'owned_process', None)
            raise
        self.verify_member(self.owned.cgroup)
        return self.owned

    def verify_member(self, group):
        group = Path(group)
        if group.parent != self.cgroup or group.name not in (self.names['helper'], self.names['application']):
            raise OSError('Lifetime membership mismatch.')

    def observe_application(self):
        state = self._state(self.names['application'])
        if state.get('ControlGroup'):
            self.verify_member(Path('/sys/fs/cgroup') / state['ControlGroup'].lstrip('/'))
            self.application_settled = True
        return state

    def application_created(self):
        self.observe_application()
        self.application_settled = True

    def resource_failure(self):
        if self.cgroup is not None:
            for name, attribute in (('memory.events', 'final_memory_events'), ('pids.events', 'final_task_events')):
                try: setattr(self, attribute, dict(line.split() for line in (self.cgroup/name).read_text().splitlines()))
                except FileNotFoundError: pass
        return (int((self.final_memory_events or {}).get('oom_kill', 0)) > 0
                or int((self.final_task_events or {}).get('max', 0)) > 0)

    def application_closed(self):
        # Called only on the verified helper's closed-application event. This
        # settles a completed creation or proves no request was made at all.
        self.application_settled = True

    def capability(self):
        p = self.limits
        return dict(status='hard', scope='supervisor_application_clients_readers_pinned_storage_collection',
            mechanism='private transient ancestor cgroup', names=dict(self.names),
            configuration=self.configuration, charged_memory_bytes=p.memory_bytes,
            tasks=p.tasks, cpu_percent=p.cpu_percent,
            memory_events=self.final_memory_events, task_events=self.final_task_events,
            control_file_payload_bytes=2*1024**2+8192,
            residual='caller_transport_initial_submission_and_closure_outside; no_total_residency_IO_or_cumulative_CPU')

    def close(self):
        if self.closed: return
        # Stop helper first, preventing any further requests by its processes.
        if self.owned is not None: self.owned.close()
        if not self.go: self.application_settled = True
        state = self.observe_application() if self.requested else {}
        if state.get('LoadState') != 'not-found' and state:
            stopped = self._control('stop', self.names['application'])
            if stopped.returncode:
                if not self.application_settled or self.observe_application()['LoadState'] != 'not-found':
                    raise OSError('Application stop unconfirmed.')
            self.application_settled = True
        if self.requested and not self.application_settled:
            raise TimeoutError('Application creation remains unresolved.')
        self.resource_failure()
        if self.cgroup is not None:
            try:
                self.final_memory_events = dict(line.split() for line in
                                                (self.cgroup/'memory.events').read_text().splitlines())
            except FileNotFoundError: pass
        if self.requested:
            state = self._state(self.names['slice'])
            if not self.created and state.get('Transient') != 'yes':
                # Slice names can synthesize a loaded inactive unit even when
                # no transient creation has ever been observed. It is absence,
                # not settlement of the registered manager request.
                raise TimeoutError('Lifetime creation remains unresolved.')
            if state.get('ControlGroup') and self.cgroup is None:
                group = Path('/sys/fs/cgroup') / state['ControlGroup'].lstrip('/')
                if group.name != self.names['slice'] or '..' in group.parts:
                    raise OSError('Lifetime group changed.')
                self.cgroup = group
            if state['LoadState'] != 'not-found':
                result = self._control('stop', self.names['slice'])
                if result.returncode and (not self.created or self._state(self.names['slice'])['LoadState'] != 'not-found'):
                    raise OSError('Lifetime stop unconfirmed.')
                self.created = True
            elif not self.created:
                raise TimeoutError('Lifetime creation remains unresolved.')
            deadline = time.monotonic() + self.application_limits.close_seconds
            while True:
                state = self._state(self.names['slice'])
                empty = self.cgroup is None or not self.cgroup.exists()
                if not empty:
                    try: empty = 'populated 0' in (self.cgroup/'cgroup.events').read_text().splitlines()
                    except FileNotFoundError: empty = True
                if state.get('Job','0') in ('0','') and state.get('ActiveState') in ('inactive','failed') and empty: break
                if state['LoadState'] == 'not-found' and empty: break
                if time.monotonic() > deadline: raise TimeoutError('Lifetime closure unconfirmed.')
                time.sleep(.01)
        self.closed = True


class _WindowsLifetimeDomain(LifetimeDomain):
    """Own supervisor, application and finalization until confirmed closure.

    Application exit does not release the ancestor job. Resource meanings are
    explicit in the declaration. Unknown closure retains ownership for retry.
    The invoking caller and its bounded reader remain outside this job.
    """
    def __init__(self, limits, application_limits):
        self.limits, self.application_limits = limits, application_limits
        self.owned = None
        self.names = None
        self.created = self.closed = self.go = False

    def prepare(self):
        # No handle or process exists before the registered start operation.
        pass

    def start(self, command):
        try:
            self.owned = _WindowsController(command, limits=self.limits.process_limits(
                output_bytes=self.application_limits.output_bytes,
                close_seconds=self.application_limits.close_seconds))
        except BaseException as error:
            self.owned = getattr(error, 'owned_process', None)
            raise
        self.created = True
        return self.owned

    def observe_application(self):
        # Native inheritance and final job emptiness establish containment.
        # No caller assertion settles an asynchronous manager request here.
        return None

    def application_created(self):
        pass

    def application_closed(self):
        pass

    def resource_failure(self):
        return self.owned is not None and bool(self.owned.resource_failure())

    def capability(self):
        resources = self.owned.capabilities() if self.owned is not None else {}
        for item in resources.values():
            item['scope'] = 'helper_application_nested_descendants_and_finalization'
        return dict(status='native_job', mechanism='suspended-start ancestor Job Object',
            scope='helper_application_nested_descendants_and_finalization', resources=resources,
            closure=self.owned.closure() if self.owned is not None else None,
            control_file_payload_bytes=2*1024**2+8192,
            residual='caller_reader_and_final_ownership_outside; no_residency_threads_disk_IO_or_total_CPU')

    def close(self):
        if self.closed: return
        if self.owned is not None:
            self.owned.close()
            if not self.owned.closed: raise TimeoutError('Native lifetime closure unconfirmed.')
        self.closed = True
