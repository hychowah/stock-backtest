"""Supervise comparison control without importing or opening financial inputs.

Only bounded control transport and the controller's private terminal evidence
cross this boundary. Application calculations, cloning and observation stay in
the domain. An optional WSL ancestor also contains this supervision and collection work.
The invoking caller remains outside that boundary. This is no hostile-code sandbox.
"""
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

import bench_admission as admission
from bench_comparison import ComparisonError, encoded
from bench_execution_domain import DomainLimits, LifetimeLimits, LifetimeDomain, start_controller
from bench_execution_storage import ExperimentalStorage, PRIVATE_ROOT, CONTROL_BYTES, validate_limits, storage_io, failure_reason

_pending_supervisors = {}


class _ApplicationSupervisor:
    """A single-use comparison lifetime, including external domain closure.

    No result is accepted before the entire controller domain closes. Failed
    closure retains this owner and its control files for explicit close retry.
    The existing comparison protocol owns allocations and identity; this is not
    another admission or qualification declaration.
    """
    def __init__(self, specification, *, cancel=None, hierarchy=None, report=None):
        self.hierarchy = hierarchy
        self.report = report or (lambda **value: None)
        self.application_requested = False
        self.specification = specification
        self.cancel = cancel or (lambda: False)
        self.owned = None
        self.control = None
        self.used = False
        self.closed = False
        self.terminal_error = None
        self._result = None
        self.evidence = None
        self.storage = None
        self._domain_closed = False
        self._finalization_started = None

    def _command(self, request):
        return [sys.executable, '-I', '-B', '-c',
            'import runpy,sys;sys.path.insert(0,sys.argv[1]);'
            'runpy.run_module("bench_execution_controller",run_name="__main__")',
            str(Path(__file__).parent), str(request)]

    def run(self):
        # No path reads, temp files, manager queries or process creation before
        # admission. Shipped admission has no admitted state.
        admission.require_execution()
        if self.used: raise ComparisonError('inactive')
        self.used = True
        self.started = self.specification.get('supervision_started', time.monotonic())
        spec = json.loads(encoded(self.specification))
        e = spec['envelope']
        limits = DomainLimits(e['sampled_memory_bytes'], e['sampled_tree_threads'],
            e['cpu_percent'], e['wall_seconds'], e['user_cpu_seconds'], processes=e['processes'],
            output_bytes=e['log_bytes'], close_seconds=e['close_seconds'])
        self.limit = limits
        spec['supervision_started'] = self.started
        validate_limits(e.get('storage_bytes'), e.get('evidence_bytes'))
        if e.get('storage_bytes') is not None:
            self.storage = ExperimentalStorage(e['storage_bytes'], e['evidence_bytes'],
                                               spec['output'], e['close_seconds'],
                protected=(spec['capture'], spec['source'], spec['observation_root']))
        raw = encoded(spec)
        if len(raw) > CONTROL_BYTES: raise ComparisonError('limit')
        self.control = Path(tempfile.mkdtemp(prefix='cb02-supervision-'))
        _pending_supervisors[id(self)] = self
        request = self.control / 'request.json'
        try:
            if self.storage is not None:
                self.storage.prepare()
                spec['output'] = PRIVATE_ROOT + '/output'
                spec['read_only_observation'] = True
                raw = encoded(spec)
                if len(raw) > CONTROL_BYTES: raise ComparisonError('limit')
            with storage_io(): request.write_bytes(raw)
            command = self._command(request)
            if self.storage is not None:
                command = self.storage.command(command,
                    [spec['capture'], spec['source'], spec['observation_root'], self.control])
            try:
                self.application_requested = True
                self.owned = start_controller(command, limits, **(
                    dict(hierarchy=self.hierarchy, role='application') if self.hierarchy else {}))
                self.report(event='application_created')
            except BaseException as error:
                self.owned = getattr(error, 'owned_process', None)
                raise
            if self.storage is not None:
                self.storage.attach(self.owned, self._checkpoint)
            self.owned.start()
            terminal = None
            while True:
                if self.cancel(): raise ComparisonError('cancelled')
                if time.monotonic() - self.started > limits.wall_seconds:
                    raise ComparisonError('limit')
                event = self.owned.event(timeout=.02)
                if event:
                    if event.get('event') == 'failed':
                        self.remote_error_type = event.get('error_type')
                        raise ComparisonError(event.get('reason', 'child_failed'))
                    if event.get('event') == 'complete' and terminal is None:
                        terminal = event
                    else:
                        raise ComparisonError('protocol')
                if self.owned.process.poll() is not None and event is None:
                    if self.owned.resource_failure():
                        raise ComparisonError(self.owned.failure)
                    if self.owned.process.returncode or terminal is None:
                        raise ComparisonError('child_failed')
                    break
            self._close_domain()
            # A queued terminal message and a zero leader exit are provisional.
            # Final accounting includes descendants that ran during closure.
            if self.owned.resource_failure():
                raise ComparisonError(self.owned.failure)
            # Charge launch/import/dispatch before attachment and final domain
            # closure after controller finalization. They are inside whole time.
            result = terminal['result']
            if (result['protocol'] != spec['protocol_sha256']
                    or result['status'] != 'fixture_pair_complete' or not result['closed']):
                raise ComparisonError('mismatch')
            # One continuous boundary includes controller terminal publication,
            # transport, domain closure and then this supervisor's receipt.
            self._finalization_started = terminal['finalization_started']
            result['costs']['finalization'] = time.monotonic() - self._finalization_started
            elapsed = time.monotonic() - self.started
            if (elapsed > limits.wall_seconds or any(result['costs'][key] > bound
                    for key, bound in spec['protocol']['costs'].items())):
                raise ComparisonError('limit')
            self.evidence = dict(status='domain_closed', execution_admission='unavailable',
                protocol=spec['protocol_sha256'], elapsed_seconds=elapsed,
                capabilities=self.owned.capabilities(), closure=self.owned.closure(),
                supervisor_scope='outside_application_domain; bounded_control_transport_only',
                receipt_timing=('costs_before_storage_collection; collection_publication_and_release_checked_before_return'
                                if self.storage else 'costs_through_domain_closure; receipt_write_checked_before_return'),
                result=result)
            workspace = Path(terminal['workspace'])
            output = Path(spec['output']).resolve() if self.storage is None else Path(spec['output'])
            parent = workspace.parent.resolve() if self.storage is None else workspace.parent
            if (parent != output or not workspace.name.startswith('workspace-')
                    or any(c not in '0123456789abcdef' for c in workspace.name[len('workspace-'):])
                    or (self.storage is None and workspace.is_symlink())):
                raise ComparisonError('mismatch')
            if self.storage is not None:
                workspace = self.storage.root / 'output' / workspace.name
                if workspace.is_symlink() or not workspace.is_dir(): raise ComparisonError('mismatch')
                self.evidence['storage'] = self.storage.capability()
                self.evidence['capabilities']['disk'] = self.storage.capability()
            target = workspace / 'domain.json'
            temporary = workspace / 'domain.building'
            with storage_io():
                temporary.write_bytes(encoded(self.evidence))
                temporary.replace(target)
            # Collection/publication/handle release remain continuously charged.
            self.close()
            publication = time.monotonic() - self.started - elapsed
            result['costs']['finalization'] += publication
            if (time.monotonic() - self.started > limits.wall_seconds or
                    result['costs']['finalization'] > spec['protocol']['costs']['finalization']):
                if self.storage is None: target.unlink()
                raise ComparisonError('limit')
            self._result = json.loads(encoded(result))
            return self
        except BaseException as error:
            self.terminal_error = error
            self._result = None
            try: self.close()
            except BaseException:
                error.comparison_supervisor = self
            raise

    @property
    def result(self):
        if self._result is None or not self.closed or self.terminal_error is not None:
            raise ComparisonError('incomplete')
        return json.loads(encoded(self._result))

    def _checkpoint(self):
        if self.cancel(): raise ComparisonError('cancelled')
        now = time.monotonic()
        if now - self.started > self.limit.wall_seconds: raise ComparisonError('limit')
        if (self._finalization_started is not None and
                now - self._finalization_started > self.specification['protocol']['costs']['finalization']):
            raise ComparisonError('limit')

    def _close_domain(self):
        if self._domain_closed: return
        if self.owned is not None:
            if self.owned.process.poll() is None: self.owned.terminate()
            self.owned.close()
            if not self.owned.closed: raise ComparisonError('closure_pending')
        self._domain_closed = True
        self.report(event='application_closed')

    def close(self):
        if self.closed: return
        self._close_domain()
        if self.storage is not None:
            # Error recovery has a fresh bounded mechanical cleanup interval.
            # It never replenishes the failed comparison's ledger or CPU time.
            check = self._checkpoint if self.terminal_error is None else (lambda: None)
            self.report(event='collection')
            self.storage.finish(domain_closed=self._domain_closed,
                reason=failure_reason(self.terminal_error, 'unexpected') if self.terminal_error else None,
                checkpoint=check)
        if self.control is not None: shutil.rmtree(self.control)
        self.closed = True
        _pending_supervisors.pop(id(self), None)



class ComparisonSupervisor(_ApplicationSupervisor):
    """Return only after application, storage and outer closure are confirmed.

    Terminal messages and persistent receipts are provisional. Cleanup never
    changes the original failure into success. Without an explicit lifetime
    declaration this retains the older outside-supervisor fixture scope.
    """
    def __init__(self, specification, *, cancel=None):
        super().__init__(specification, cancel=cancel)
        self.lifetime = None
        self._remote = False
        self._sequence = 0
        self._helper_pending = False
        self.progress = None

    def _helper_command(self, request):
        return [sys.executable, '-I', '-B', '-c',
            'import runpy,sys;sys.path.insert(0,sys.argv[1]);'
            'runpy.run_module("bench_execution_supervisor_worker",run_name="__main__")',
            str(Path(__file__).parent), str(request)]

    def run(self):
        admission.require_execution()
        if self.specification['envelope'].get('lifetime') is None:
            return super().run()
        if self.used: raise ComparisonError('inactive')
        self.used = True
        self._remote = True
        self.started = time.monotonic()
        spec = json.loads(encoded(self.specification))
        e = spec['envelope']
        limits = DomainLimits(e['sampled_memory_bytes'], e['sampled_tree_threads'],
            e['cpu_percent'], e['wall_seconds'], e['user_cpu_seconds'], processes=e['processes'],
            output_bytes=e['log_bytes'], close_seconds=e['close_seconds'])
        self.limit = limits
        validate_limits(e.get('storage_bytes'), e.get('evidence_bytes'))
        if e.get('storage_bytes') is not None and sys.platform != 'linux':
            raise ComparisonError('unsupported')
        # Validation precedes control files and manager effects, including the
        # persistent destination previously protected by storage audit F1.
        if e.get('storage_bytes') is not None:
            ExperimentalStorage(e['storage_bytes'], e['evidence_bytes'], spec['output'],
                e['close_seconds'], protected=(spec['capture'], spec['source'], spec['observation_root']))
        self.lifetime = LifetimeDomain(LifetimeLimits(**e['lifetime']), limits)
        spec.update(supervision_started=self.started, hierarchy=self.lifetime.names)
        raw = encoded(spec)
        if len(raw) > CONTROL_BYTES: raise ComparisonError('limit')
        _pending_supervisors[id(self)] = self
        try:
            self.control = Path(tempfile.mkdtemp(prefix='cb02-lifetime-'))
            request = self.control/'request.json'
            with storage_io(): request.write_bytes(raw)
            self.lifetime.prepare()
            self.owned = self.lifetime.start(self._helper_command(request))
            self.lifetime.go = True  # Adopt possible effects before writing GO.
            self.owned.start()
            terminal = None
            while True:
                self._checkpoint()
                if self.lifetime.resource_failure(): raise ComparisonError('limit')
                event = self.owned.event(.02)
                if event:
                    kind = event.get('event')
                    if kind == 'application_created': self.lifetime.application_created()
                    elif kind == 'application_closed': self.lifetime.application_closed()
                    elif kind == 'collection': self.progress = event
                    elif kind == 'failed':
                        self.remote_error_type = event.get('error_type')
                        self._helper_pending = bool(event.get('pending'))
                        if event.get('application_not_requested'): self.lifetime.application_closed()
                        raise ComparisonError('limit' if self.lifetime.resource_failure() else event.get('reason','child_failed'))
                    elif kind == 'complete' and terminal is None:
                        terminal = event
                        self.evidence = event['evidence']
                        self._finalization_started = event['finalization_started']
                        self.lifetime.application_closed()
                    else: raise ComparisonError('protocol')
                if self.owned.process.poll() is not None and event is None:
                    if self.owned.process.returncode or terminal is None:
                        raise ComparisonError('limit' if self.lifetime.resource_failure() else 'child_failed')
                    break
            self.close()
            self._checkpoint()
            if self.lifetime.resource_failure(): raise ComparisonError('limit')
            result = terminal['result']
            if (result['protocol'] != spec['protocol_sha256'] or not result['closed']
                    or result['status'] != 'fixture_pair_complete'):
                raise ComparisonError('mismatch')
            result['costs']['finalization'] = time.monotonic()-self._finalization_started
            self.evidence.update(lifetime=self.lifetime.capability(),
                lifetime_closure=dict(closed=self.lifetime.closed, helper=self.owned.closure()),
                supervisor_scope='inside_private_lifetime_ancestor; caller_relay_outside',
                receipt_timing='application_receipt_predates_collection; returned_result_includes_outer_closure',
                result=result)
            self._result = json.loads(encoded(result))
            return self
        except BaseException as error:
            self.terminal_error = error
            self._result = None
            try: self.close()
            except BaseException: error.comparison_supervisor = self
            raise

    def _action(self, action):
        self._sequence += 1
        with storage_io():
            path = self.control/'action.building'
            raw = encoded(dict(sequence=self._sequence, action=action))
            if len(raw)>4096: raise ComparisonError('limit')
            path.write_bytes(raw)
            path.replace(self.control/'action.json')

    def close(self):
        if not self._remote: return super().close()
        if self.closed: return
        if self.lifetime is None:
            # A rejected declaration has created no domain or control owner.
            self.closed = True
            _pending_supervisors.pop(id(self), None)
            return
        if self.owned is not None and self.owned.process.poll() is None:
            self._action('close' if self._helper_pending else 'cancel')
            deadline = time.monotonic()+self.limit.close_seconds
            while self.owned.process.poll() is None and time.monotonic()<deadline:
                event = self.owned.event(.02)
                if event:
                    kind = event.get('event')
                    if kind == 'application_closed': self.lifetime.application_closed()
                    elif kind == 'application_created': self.lifetime.application_created()
                    elif kind == 'pending':
                        self._helper_pending = True
                        raise ComparisonError('closure_pending')
                    elif kind == 'closed':
                        self._helper_pending = False
                        self.lifetime.application_closed()
                    elif kind == 'failed':
                        self._helper_pending = bool(event.get('pending'))
                        if event.get('application_not_requested'): self.lifetime.application_closed()
                if self.owned.failure: break
            if self.owned.process.poll() is None:
                # A blocked helper cannot retain its Python objects after this
                # escalation. Verified records survive; uncollected bytes may not.
                self.lifetime.observe_application()
                self.owned.terminate()
        self.lifetime.close()
        if self.control is not None: shutil.rmtree(self.control)
        self.closed = True
        _pending_supervisors.pop(id(self), None)


def specification(owner):
    """Serialize explicit bindings; do not resolve or inspect input paths."""
    return dict(capture=str(owner.capture), source=str(owner.source), output=str(owner.output),
        protocol=owner.protocol.value, protocol_sha256=owner.protocol.identity,
        envelope=asdict(owner.envelope), observation_mode=owner.observation_mode,
        observation_root=str(owner.observation_root))
