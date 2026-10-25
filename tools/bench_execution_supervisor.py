"""Supervise comparison control without importing or opening financial inputs.

Only bounded control transport and the controller's private terminal evidence
cross this boundary. Application calculations, cloning and observation stay in
the domain. This outside supervisor is not a fully resource-limited sandbox.
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
from bench_execution_domain import DomainLimits, start_controller

_pending_supervisors = {}


class ComparisonSupervisor:
    """A single-use comparison lifetime, including external domain closure.

    No result is accepted before the entire controller domain closes. Failed
    closure retains this owner and its control files for explicit close retry.
    The existing comparison protocol owns allocations and identity; this is not
    another admission or qualification declaration.
    """
    def __init__(self, specification, *, cancel=None):
        self.specification = specification
        self.cancel = cancel or (lambda: False)
        self.owned = None
        self.control = None
        self.used = False
        self.closed = False
        self.terminal_error = None
        self._result = None
        self.evidence = None

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
        self.started = time.monotonic()
        spec = json.loads(encoded(self.specification))
        e = spec['envelope']
        limits = DomainLimits(e['sampled_memory_bytes'], e['sampled_tree_threads'],
            e['cpu_percent'], e['wall_seconds'], processes=e['processes'],
            output_bytes=e['log_bytes'], close_seconds=e['close_seconds'])
        self.limit = limits
        spec['supervision_started'] = self.started
        raw = encoded(spec)
        if len(raw) > 1024 * 1024: raise ComparisonError('limit')
        self.control = Path(tempfile.mkdtemp(prefix='cb02-supervision-'))
        _pending_supervisors[id(self)] = self
        request = self.control / 'request.json'
        try:
            request.write_bytes(raw)
            try:
                self.owned = start_controller(self._command(request), limits)
            except BaseException as error:
                self.owned = getattr(error, 'owned_process', None)
                raise
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
                    if self.owned.process.returncode or terminal is None:
                        raise ComparisonError('child_failed')
                    break
            self.close()
            # Charge launch/import/dispatch before attachment and final domain
            # closure after controller finalization. They are inside whole time.
            result = terminal['result']
            if (result['protocol'] != spec['protocol_sha256']
                    or result['status'] != 'fixture_pair_complete' or not result['closed']):
                raise ComparisonError('mismatch')
            # One continuous boundary includes controller terminal publication,
            # transport, domain closure and then this supervisor's receipt.
            result['costs']['finalization'] = time.monotonic() - terminal['finalization_started']
            elapsed = time.monotonic() - self.started
            if (elapsed > limits.wall_seconds or any(result['costs'][key] > bound
                    for key, bound in spec['protocol']['costs'].items())):
                raise ComparisonError('limit')
            self.evidence = dict(status='domain_closed', execution_admission='unavailable',
                protocol=spec['protocol_sha256'], elapsed_seconds=elapsed,
                capabilities=self.owned.capabilities(), closure=self.owned.closure(),
                supervisor_scope='outside_application_domain; bounded_control_transport_only',
                receipt_timing='costs_through_domain_closure; receipt_write_checked_before_return',
                result=result)
            workspace = Path(terminal['workspace'])
            output = Path(spec['output']).resolve()
            if (workspace.parent.resolve() != output or not workspace.name.startswith('workspace-')
                    or workspace.is_symlink()):
                raise ComparisonError('mismatch')
            target = workspace / 'domain.json'
            temporary = workspace / 'domain.building'
            temporary.write_bytes(encoded(self.evidence))
            temporary.replace(target)
            # Publication itself is still part of finalization and whole time.
            publication = time.monotonic() - self.started - elapsed
            result['costs']['finalization'] += publication
            if (time.monotonic() - self.started > limits.wall_seconds or
                    result['costs']['finalization'] > spec['protocol']['costs']['finalization']):
                target.unlink()
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

    def close(self):
        if self.closed: return
        if self.owned is not None:
            if self.owned.process.poll() is None: self.owned.terminate()
            self.owned.close()
            if not self.owned.closed: raise ComparisonError('closure_pending')
        if self.control is not None: shutil.rmtree(self.control)
        self.closed = True
        _pending_supervisors.pop(id(self), None)


def specification(owner):
    """Serialize explicit bindings; do not resolve or inspect input paths."""
    return dict(capture=str(owner.capture), source=str(owner.source), output=str(owner.output),
        protocol=owner.protocol.value, protocol_sha256=owner.protocol.identity,
        envelope=asdict(owner.envelope), observation_mode=owner.observation_mode,
        observation_root=str(owner.observation_root))
