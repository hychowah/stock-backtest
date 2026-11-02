"""Fixed fresh-process entry. Only stdlib/bootstrap imports precede source.

The caller's runtime owns financial coordination and process containment.
This worker owns a source guard, delegated mappings and private provider/SQL.
No factory, executable pickle, checkpoint writer or application store is loaded.
"""
import json
import os
from pathlib import Path
import select
import sys
from threading import Event, Thread
import time

ROOT = Path(__file__).absolute().parents[3]
FRAME_BYTES = 16*1024
REQUEST_BYTES = 1024*1024


class _Control:
    """Translate private control I/O into terminal memory state for checkpoints."""
    def __init__(self, marker):
        self.marker = marker
        self.stopped, self.finished, self.ready = Event(), Event(), Event()
        self.error = None

    def fail(self, error):
        if self.error is None: self.error = error
        self.stopped.set()

    def cancelled(self):
        if not self.stopped.is_set(): return False
        if self.error is not None: raise self.error
        return True

    def _observe_marker(self):
        if self.stopped.is_set(): return
        try: self.marker.stat()
        except FileNotFoundError: pass
        except BaseException as error: self.fail(error)
        else: self.stopped.set()

    def observe(self, parent_departed, seconds):
        self._observe_marker()
        self.ready.set()
        while not self.finished.is_set():
            if parent_departed():
                self.stopped.set()
                if not self.finished.wait(seconds): os._exit(72)
                return
            # Marker cancellation is terminal, but never removes parent-loss
            # protection while calculation or owned-resource cleanup continues.
            self._observe_marker()


def _parent_monitor(kind, value, control, seconds):
    """Own inherited parent lifetime and the existing 50 ms control cadence."""
    close = None
    try:
        if kind == 'handle':
            import ctypes as c
            from ctypes import wintypes as w
            kernel = c.WinDLL('kernel32', use_last_error=True)
            kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
            kernel.CloseHandle.argtypes = [w.HANDLE]
            close = lambda: kernel.CloseHandle(w.HANDLE(value))
            def departed():
                state = kernel.WaitForSingleObject(w.HANDLE(value), 50)
                if state == 0: return True
                if state != 258: raise c.WinError(c.get_last_error())
                return False
        else:
            close = lambda: os.close(value)
            def departed():
                readable, _, _ = select.select([value], [], [], .05)
                return bool(readable and not os.read(value, 1))
        control.observe(departed, seconds)
    except BaseException as error:
        control.fail(error)
        control.ready.set()
        # An unobservable parent must retain the existing terminal safeguard.
        if not control.finished.wait(seconds): os._exit(72)
    finally:
        if close is not None:
            try: close()
            except BaseException as error: control.fail(error)


def _read(path):
    with path.open('rb') as handle: payload = handle.read(REQUEST_BYTES+1)
    if len(payload) > REQUEST_BYTES: raise ValueError('Trial worker request exceeds its byte bound.')
    return json.loads(payload)


def _private_sample():
    from backtest.runtime.process_owner import process_metrics, windows_processes
    result = process_metrics()
    if os.name == 'nt':
        row = windows_processes(include_pids=[os.getpid()]).get(str(os.getpid()), {})
        result['sampled_private_bytes'] = row.get('private_bytes')
    else:
        try:
            rows = dict(line.split(':', 1) for line in Path('/proc/self/smaps_rollup').read_text().splitlines()
                        if ':' in line)
            result['sampled_private_bytes'] = sum(int(rows.get(name, '0 kB').split()[0])*1024
                for name in ('Private_Clean', 'Private_Dirty', 'Private_Hugetlb'))
        except (OSError, ValueError): result['sampled_private_bytes'] = None
    return result


def main():
    # Preserve only a dedicated bounded protocol descriptor. Native stdout and
    # stderr, including compiler output, cannot enter the runtime's JSON stream.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), 'wb', buffering=0)
    with open(os.devnull, 'wb') as null:
        os.dup2(null.fileno(), 1); os.dup2(null.fileno(), 2)
    def emit(event):
        payload = json.dumps(event, allow_nan=False, separators=(',', ':')).encode('utf-8')+b'\n'
        if len(payload) > FRAME_BYTES: raise ValueError('Trial worker response exceeds its frame bound.')
        protocol.write(payload)
    configuration = _read(Path(sys.argv[1]))
    if Path(configuration['source_root']).absolute() != ROOT:
        raise ValueError('Trial worker source root differs.')
    scratch = Path(configuration['scratch'])
    control = _Control(scratch/'cancel')
    watcher = Thread(target=_parent_monitor, args=(sys.argv[2], int(sys.argv[3]), control,
        configuration['close_seconds']), name='trial-parent-lifetime', daemon=True)
    watcher.start()
    control.ready.wait()
    import importlib.util as _bootstrap_imports
    _bootstrap_spec = _bootstrap_imports.spec_from_file_location('_backtest_source_owner', ROOT/'website'/'runtime_access.py')
    runtime_access = _bootstrap_imports.module_from_spec(_bootstrap_spec)
    sys.modules[_bootstrap_spec.name] = runtime_access
    _bootstrap_spec.loader.exec_module(runtime_access)
    inputs = provider = portfolio = scalar_resources = None
    active_slot=None
    began = time.perf_counter()
    with runtime_access.ownership(ROOT, timeout=0):
        try:
            emit(dict(event='stage', stage='source-owned'))
            sys.path.insert(0,str(ROOT))
            from backtest.runtime import backtest_control as backtest_control
            with backtest_control.cancel_when(control.cancelled):
                from backtest.financial import rules
                from backtest.inputs import market, fmp_download, cache_assets
                from backtest.engines.reference import legacy
                fmp_download.KEY_PATH = scratch/'nonexistent-key'
                from backtest.engines.numerical import generation as numerical_generation
                from backtest.engines.numerical import random as numerical_random
                from backtest.engines.numerical import trial as numerical_trial
                from backtest.engines.numerical import checkpoints as trial_checkpoints
                from backtest.engines.numerical.numba import NumbaExecutor
                from backtest.engines.numerical import matrix as numerical_matrix
                from backtest.engines.numerical.portfolio import NumericalPortfolio
                from backtest.engines.numerical.runtime_child import _stdin_lines
                checkpoint = backtest_control.checkpoint
                source = trial_checkpoints.digest(trial_checkpoints.canonical(numerical_random.source_identity()))
                if source != configuration['source']: raise ValueError('Trial worker source identity differs.')
                attached = time.perf_counter()
                emit(dict(event='stage', stage='attaching'))
                inputs = numerical_generation.open_delegated(configuration['reference'], checkpoint=checkpoint)
                attachment_seconds = time.perf_counter()-attached
                emit(dict(event='stage', stage='initializing'))
                provider_constructions=1
                if configuration.get('workload','legacy')=='scalar':
                    from backtest.engines.numerical import scalar
                    scalar_resources=scalar.Resources.__new__(scalar.Resources)
                    scalar.Resources.__init__(scalar_resources,inputs,configuration['provider_limits'],checkpoint=checkpoint,warm=True)
                    portfolio=scalar_resources.books();provider=scalar_resources.provider
                else:
                    provider = NumbaExecutor(inputs,limits=configuration['provider_limits'])
                    portfolio = NumericalPortfolio(inputs, provider)
                checkpoint()
                def measurements():
                    return dict(**_private_sample(), provider=provider.stats, matrix=provider._calculate.stats,
                        provider_constructions=provider_constructions,
                        factor_kernel_compilation_requests=numerical_matrix.compilation_requests(),
                        mappings=id(inputs), provider_instance=id(provider), sql_workspace=id(portfolio.db),
                        **({'formula':dict(scalar_resources.evaluator.stats)} if scalar_resources is not None else {}))
                emit(dict(event='ready', pid=os.getpid(), generation=inputs.signature, source=source,
                    backend=provider.stats['backend'], compiler=provider.compiler['signature'], threads=provider.stats['threads'],
                    initialization_seconds=time.perf_counter()-began, attachment_seconds=attachment_seconds,
                    measurements=measurements()))
                for line in _stdin_lines():
                    checkpoint()
                    command = json.loads(line)
                    if command == {'command': 'close'}: break
                    if set(command) != {'command', 'slot'} or command['command'] != 'trial':
                        raise ValueError('Invalid trial worker command.')
                    slot = command['slot']
                    if type(slot) is not int or not 0 <= slot < configuration['slots']:
                        raise ValueError('Invalid trial worker task slot.')
                    active_slot=slot
                    specification = _read(scratch/('slot-'+str(slot)+'.json'))
                    if scalar_resources is not None:
                        task=scalar.TrialEvaluator(scalar_resources,calculation_identity=specification['calculation_identity'])
                    else:
                        if specification.get('version')!=1:raise ValueError('Trial kind differs from worker workload.')
                        task = numerical_trial.TrialEvaluator(portfolio,
                            calculation_identity=specification['calculation_identity'])
                    emit(dict(event='stage', stage='calculating'))
                    started = time.perf_counter()
                    with (scratch/('slot-'+str(slot)+'.evidence')).open('x+b') as stream:
                        descriptor = task.produce(specification, stream, limits=configuration['artifact_limits'])
                        sealed = time.perf_counter()
                        stream.flush()
                    checkpoint()
                    emit(dict(event='completed', slot=slot, descriptor=descriptor,
                        work_and_seal_seconds=sealed-started, flush_seconds=time.perf_counter()-sealed,
                        measurements=measurements()))
                    active_slot=None
        except BaseException as error:
            # Never expose exception text, source lines, credentials or URLs.
            extra={}
            if active_slot is not None:
                from backtest.application.strategy_requests import failure_details
                details=failure_details(error)
                if details is not None:
                    from backtest.engines.numerical.runtime import write_payload
                    write_payload(scratch/('slot-'+str(active_slot)+'.failure.json'),details,REQUEST_BYTES)
                    extra=dict(scalar_failure=True,slot=active_slot)
            emit(dict(event='cancelled' if type(error).__name__ == 'Cancelled' else 'error',
                      error_type=type(error).__name__,**extra))
        finally:
            while True:
                try:
                    for value in (scalar_resources, portfolio, provider, inputs):
                        if value is not None: value.close()
                except BaseException:
                    # Keep source and mappings owned until retry or terminal OS
                    # cleanup. Parent pool retains its failed-closure owner.
                    time.sleep(.05)
                else: break
            control.finished.set()
            while watcher.is_alive():
                watcher.join(timeout=configuration['close_seconds'])
            emit(dict(event='closed'))
            protocol.close()
            # Source remains held through native-team and process termination.
            os._exit(0)


if __name__ == '__main__': main()
