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

ROOT = Path(__file__).absolute().parents[1]
FRAME_BYTES = 16*1024
REQUEST_BYTES = 1024*1024


def _parent_monitor(kind, value, stopped, finished, seconds):
    """Observe an inherited pipe or actual process handle, never PID polling."""
    if kind == 'handle':
        import ctypes as c
        from ctypes import wintypes as w
        kernel = c.WinDLL('kernel32', use_last_error=True)
        kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        try:
            while not finished.is_set():
                state = kernel.WaitForSingleObject(w.HANDLE(value), 50)
                if state == 0: break
                if state != 258: break
            else: return
            stopped.set()
            if not finished.wait(seconds): os._exit(72)
        finally: kernel.CloseHandle(w.HANDLE(value))
    else:
        try:
            while not finished.is_set():
                readable, _, _ = select.select([value], [], [], .05)
                if readable and not os.read(value, 1): break
            else: return
            stopped.set()
            if not finished.wait(seconds): os._exit(72)
        finally: os.close(value)


def _read(path):
    with path.open('rb') as handle: payload = handle.read(REQUEST_BYTES+1)
    if len(payload) > REQUEST_BYTES: raise ValueError('Trial worker request exceeds its byte bound.')
    return json.loads(payload)


def _private_sample():
    from process_owner import process_metrics, windows_processes
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
    stopped, finished = Event(), Event()
    watcher = Thread(target=_parent_monitor, args=(sys.argv[2], int(sys.argv[3]), stopped, finished,
        configuration['close_seconds']), name='trial-parent-lifetime', daemon=True)
    watcher.start()
    sys.path[:0] = [str(ROOT/'website')]
    import runtime_access
    inputs = provider = portfolio = None
    began = time.perf_counter()
    with runtime_access.ownership(ROOT, timeout=0):
        try:
            emit(dict(event='stage', stage='source-owned'))
            sys.path[:0] = [str(ROOT/'scripts')]
            import run
            run.KEY_PATH = scratch/'nonexistent-key'
            import backtest_control
            import numerical_generation
            import numerical_random
            import numerical_trial
            import schedules
            import trial_checkpoints
            from numerical_numba import NumbaExecutor
            from numerical_portfolio import NumericalPortfolio
            from numerical_runtime_child import _stdin_lines
            cancelled = lambda: stopped.is_set() or (scratch/'cancel').exists()
            with backtest_control.cancel_when(cancelled):
                checkpoint = backtest_control.checkpoint
                source = trial_checkpoints.digest(trial_checkpoints.canonical(numerical_random.source_identity()))
                if source != configuration['source']: raise ValueError('Trial worker source identity differs.')
                attached = time.perf_counter()
                emit(dict(event='stage', stage='attaching'))
                inputs = numerical_generation.open_delegated(configuration['reference'], schedules, checkpoint=checkpoint)
                attachment_seconds = time.perf_counter()-attached
                emit(dict(event='stage', stage='initializing'))
                provider = NumbaExecutor(inputs, limits=configuration['provider_limits'])
                portfolio = NumericalPortfolio(inputs, provider)
                checkpoint()
                def measurements():
                    return dict(**_private_sample(), provider=provider.stats, matrix=provider._calculate.stats,
                        mappings=id(inputs), provider_instance=id(provider), sql_workspace=id(portfolio.db))
                emit(dict(event='ready', pid=os.getpid(), generation=inputs.signature, source=source,
                    backend='numba', compiler=provider.compiler['signature'], threads=provider.stats['threads'],
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
                    specification = _read(scratch/('slot-'+str(slot)+'.json'))
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
        except BaseException as error:
            # Never expose exception text, source lines, credentials or URLs.
            emit(dict(event='cancelled' if type(error).__name__ == 'Cancelled' else 'error',
                      error_type=type(error).__name__))
        finally:
            while True:
                try:
                    for value in (portfolio, provider, inputs):
                        if value is not None: value.close()
                except BaseException:
                    # Keep source and mappings owned until retry or terminal OS
                    # cleanup. Parent pool retains its failed-closure owner.
                    time.sleep(.05)
                else: break
            finished.set(); watcher.join(timeout=configuration['close_seconds'])
            emit(dict(event='closed'))
            protocol.close()
            # Source remains held through native-team and process termination.
            os._exit(0)


if __name__ == '__main__': main()
