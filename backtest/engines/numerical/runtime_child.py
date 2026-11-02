"""Source-before-import bootstrap for the explicit numerical capability.

No application calculation import occurs until shared source ownership exists.
The parent contains native redirectors before resume. EOF cancels idle/active work.
"""
from contextlib import ExitStack
import importlib
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
import signal
import sys
from threading import Event, Thread
import time

ROOT = Path(__file__).absolute().parents[3]
import importlib.util as _bootstrap_imports
_bootstrap_spec = _bootstrap_imports.spec_from_file_location('_backtest_source_owner', ROOT/'website'/'runtime_access.py')
runtime_access = _bootstrap_imports.module_from_spec(_bootstrap_spec)
sys.modules[_bootstrap_spec.name] = runtime_access
_bootstrap_spec.loader.exec_module(runtime_access)


_INPUT_FRAME_BYTES = 16*1024


def _framed_lines(receive, *, frame_bytes=_INPUT_FRAME_BYTES, pause=None):
    """Decode bounded UTF-8 frames without discarding read-ahead after GO.

    receive(maximum) returns available bytes, None while idle, or b'' at EOF.
    One generator moves from the main handshake to the control reader, so a
    coalesced GO/cancel write keeps its later commands. CRLF is normalized.
    """
    if pause is None: pause = lambda: time.sleep(.01)
    pending = bytearray()
    while True:
        newline = pending.find(b'\n')
        if newline >= 0:
            if newline+1 > frame_bytes: raise ValueError('Numerical input frame exceeds its byte bound.')
            line = bytes(pending[:newline+1]); del pending[:newline+1]
            if line.endswith(b'\r\n'): line = line[:-2]+b'\n'
            yield line.decode('utf-8')
            continue
        if len(pending) >= frame_bytes:
            raise ValueError('Numerical input frame exceeds its byte bound.')
        part = receive(min(4096,frame_bytes-len(pending)))
        if part is None:
            pause(); continue
        if not part:
            if pending: raise ValueError('Numerical input ended inside a frame.')
            return
        pending.extend(part)


def _windows_stdin_reader():
    """Poll an anonymous pipe without a blocked Windows CRT descriptor read.

    A blocking text/CRT stdin reader can hold CRT state while native extension
    DLLs load on the main thread. PeekNamedPipe waits for no bytes. os.read is
    called in binary mode only for bytes already reported available.
    """
    import ctypes
    from ctypes import wintypes as w
    import msvcrt
    descriptor = sys.stdin.fileno()
    msvcrt.setmode(descriptor,os.O_BINARY)
    handle = w.HANDLE(msvcrt.get_osfhandle(descriptor))
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.PeekNamedPipe.argtypes = [w.HANDLE,ctypes.c_void_p,w.DWORD,ctypes.c_void_p,
                                    ctypes.POINTER(w.DWORD),ctypes.c_void_p]
    kernel.PeekNamedPipe.restype = w.BOOL
    def receive(maximum):
        available = w.DWORD()
        if not kernel.PeekNamedPipe(handle,None,0,None,ctypes.byref(available),None):
            code = ctypes.get_last_error()
            if code in (109,232): return b''  # broken pipe / no writer
            raise ctypes.WinError(code)
        if not available.value: return None
        return os.read(descriptor,min(maximum,available.value))
    return receive


def _stdin_lines():
    if os.name == 'nt':
        yield from _framed_lines(_windows_stdin_reader())
    else:
        # Keep the ordinary POSIX reader. It does not have the Windows CRT/DLL
        # import interaction. The same generator retains handshake read-ahead.
        while True:
            line = sys.stdin.readline(_INPUT_FRAME_BYTES+1)
            if not line: return
            if len(line.encode('utf-8')) > _INPUT_FRAME_BYTES:
                raise ValueError('Numerical input frame exceeds its byte bound.')
            yield line


def main():
    lines = _stdin_lines()
    if next(lines,None) != 'GO\n': raise ValueError('Numerical startup handshake failed.')
    with Path(sys.argv[1]).open('rb') as handle: payload = handle.read(1024*1024+1)
    if len(payload)>1024*1024: raise ValueError('Numerical startup request exceeds its byte bound.')
    configuration = json.loads(payload)
    if Path(configuration['source_root']).absolute() != ROOT: raise ValueError('Numerical source root differs.')
    scratch = Path(configuration['scratch'])
    with runtime_access.ownership(ROOT,timeout=0):
        print(json.dumps(dict(event='diagnostic',stage='source-owned')),flush=True)
        sys.path.insert(0,str(ROOT))
        # Credential access is disabled for this offline calculation capability.
        from backtest.financial import rules
        from backtest.inputs import market, fmp_download, cache_assets
        from backtest.engines.reference import legacy
        fmp_download.KEY_PATH = scratch/'nonexistent-key'
        from backtest.engines.numerical.runtime import FRAME_BYTES, MAX_REQUEST_BYTES, MAX_PAYLOAD_BYTES, read_payload, write_payload
        from backtest.runtime import backtest_control as backtest_control
        from backtest.runtime import cache_access as cache_access
        from backtest.engines.numerical import transfer as numerical_transfer
        from backtest.runtime.process_owner import close_own_session
        stop,shutdown,ack,exited = Event(),Event(),Event(),Event()
        commands = Queue(maxsize=1)
        acknowledgements = numerical_transfer.Acknowledgements()
        def emit(event):
            line = json.dumps(event,allow_nan=False,separators=(',',':'))
            if len(line.encode('utf-8')) > FRAME_BYTES: raise ValueError('Numerical event exceeds its frame bound.')
            print(line,flush=True)
        def controls():
            try:
                for line in lines:
                    value = json.loads(line)
                    command = value.get('command')
                    if command == 'ack': ack.set()
                    elif command == 'transfer_ack':
                        if not acknowledgements.accept(value):break
                    elif command == 'cancel': stop.set(); ack.set()
                    elif command == 'close':
                        shutdown.set(); stop.set(); ack.set()
                        try: commands.put_nowait('close')
                        except Full: pass
                    elif command == 'calculate' and not shutdown.is_set(): commands.put_nowait('calculate')
                    else: break
            except (OSError,ValueError,Full): pass
            # Parent death/EOF must close a runtime which is idle as well.
            shutdown.set(); stop.set(); ack.set()
            try: commands.put_nowait('close')
            except Full: pass
            # A stuck native import/compiler cannot retain ownership forever
            # after its only owner disappeared. OS exit closes all handles.
            if not exited.wait(configuration['close_seconds']):
                try: close_own_session(timeout=.1)
                finally: os._exit(72)
        Thread(target=controls,name='numerical-control',daemon=True).start()
        def stopping(*unused): shutdown.set(); stop.set(); ack.set()
        signal.signal(signal.SIGINT,stopping)
        signal.signal(signal.SIGTERM,stopping)
        coordinator = cache_access.WorkspaceAccess(Path(configuration['cache_lock']))
        cache_access.workspace = coordinator
        factory_module,factory_name = configuration['session_factory'].split(':',1)
        if factory_module != 'backtest.engines.numerical.session': sys.path.insert(0,str(ROOT/'tests'))
        session = None
        with ExitStack() as financial:
            try: financial.enter_context(coordinator.hold(timeout=0))
            except cache_access.Contention:
                emit(dict(event='error',category='contention'))
                return
            try:
                emit(dict(event='diagnostic',stage='financial-owned',pid=os.getpid()))
                with backtest_control.cancel_when(stop.is_set):
                    options = dict(configuration)
                    extras = configuration['session_options']
                    if set(extras) & {'threads','source_root','scratch','generation_path','checkpoint_path','cache_lock'}:
                        raise ValueError('Session options cannot override runtime ownership.')
                    options.update(extras)
                    emit(dict(event='diagnostic',stage='session-import'))
                    factory = getattr(importlib.import_module(factory_module),factory_name)
                    emit(dict(event='diagnostic',stage='session-construct-prewarm'))
                    session = factory(options)
                def stats(required=True):
                    try:
                        write_payload(scratch/'stats.json',session.measurements(),MAX_REQUEST_BYTES)
                        return True
                    except BaseException as error:
                        details=getattr(error,'numerical_publication',None)
                        if details:emit(dict(event='diagnostic',stage='publication-failed',**details))
                        if required:raise
                        return False
                emit(dict(event='ready',stats=stats(),pid=os.getpid()))
                while not shutdown.is_set():
                    try: command = commands.get(timeout=.05)
                    except Empty: continue
                    if command == 'close': break
                    stop.clear()
                    def callback(kind,value,number=None):
                        backtest_control.checkpoint()
                        ack.clear()
                        write_payload(scratch/'payload.json',value,MAX_PAYLOAD_BYTES)
                        event = dict(event=kind)
                        if number is not None: event['number'] = number
                        emit(event)
                        while not ack.wait(.05): backtest_control.checkpoint()
                        backtest_control.checkpoint()
                    def exchange(event,operation,sequence):
                        backtest_control.checkpoint()
                        acknowledgements.arm(operation,sequence)
                        emit(event)
                        while not acknowledgements.wait(.05):backtest_control.checkpoint()
                        backtest_control.checkpoint()
                    try:
                        with backtest_control.cancel_when(stop.is_set):
                            request = read_payload(scratch/'request.json',MAX_REQUEST_BYTES)
                            emit(dict(event='diagnostic',stage='validate-calculate'))
                            status = None
                            if configuration.get('preparation_status'):
                                from backtest.application.preparation import Preparation, DEFAULT_PROFILE
                                status = Preparation(ROOT,profile=configuration.get('preparation_profile') or DEFAULT_PROFILE).status()
                            if request['mode'] == '__inspect__':
                                result = status
                            elif request['mode'] == '__prepare__':
                                result = session.verify_provider()
                            elif status is not None and status.get('state') != 'current':
                                emit(dict(event='error',category='unavailable'))
                                shutdown.set()
                                continue
                            else:
                                if request.get('operation')=='evidence':
                                    planned=(numerical_transfer.read_plan(scratch,request['plan_reference'],backtest_control.checkpoint)
                                        if request['plan_reference'] is not None else None)
                                    with (scratch/'produced.evidence').open('x+b') as stream:
                                        session.calculate_into(request['mode'],request['options'],stream,
                                            lambda value:callback('progress',value),lambda value:callback('configuration',value),
                                            planned=planned,**request['limits'])
                                        stream.flush()
                                        numerical_transfer.send(stream,scratch,exchange,max_bytes=request['limits']['max_bytes'],
                                            checkpoint=backtest_control.checkpoint)
                                        acknowledgements.check()
                                    numerical_transfer.cleanup(scratch)
                                    result=None
                                else:
                                    if 'plan_reference' in request:raise ValueError('Staged plans require the evidence operation.')
                                    result = session.calculate(request['mode'],request['options'],
                                    lambda value:callback('progress',value),lambda value:callback('configuration',value),
                                    planned=request['planned'],capture=(lambda number,value:callback('capture',value,number))
                                    if request['capture'] else None)
                            backtest_control.checkpoint()
                            write_payload(scratch/'payload.json',result,MAX_PAYLOAD_BYTES)
                            emit(dict(event='result',stats=stats()))
                    except backtest_control.Cancelled:
                        emit(dict(event='cancelled',stats=stats(required=False)))
                        shutdown.set()
                    except BaseException as error:
                        details=getattr(error,'numerical_publication',None)
                        if details:emit(dict(event='diagnostic',stage='publication-failed',**details))
                        # Error text may contain provider paths or URLs. Stable
                        # source-owned validation messages are safe; other types
                        # are reported by category without exception text.
                        message = str(error) if isinstance(error,ValueError) else 'Numerical calculation failed: '+type(error).__name__
                        from backtest.application.strategy_requests import failure_details
                        scalar_failure=failure_details(error)
                        if scalar_failure is not None:
                            write_payload(scratch/'scalar-failure.json',scalar_failure,MAX_REQUEST_BYTES)
                            emit(dict(event='error',scalar_failure=True))
                        else:emit(dict(event='error',message=message))
                        shutdown.set()
            except BaseException as error:
                session = session or getattr(error,'numerical_session',None)
                emit(dict(event='error',message='Numerical initialization failed: '+type(error).__name__))
            finally:
                while True:
                    try:
                        if session is not None:
                            session.close(); session = None
                        close_own_session(timeout=configuration['close_seconds'])
                    except BaseException:
                        # Keep financial/source ownership through retry. Parent
                        # may establish terminal release by confirmed OS exit.
                        emit(dict(event='diagnostic',stage='failed-closure'))
                        time.sleep(.05)
                    else: break
                emit(dict(event='diagnostic',stage='resources-closed'))
                # Keep BOTH OS lock handles live through terminal process exit.
                # Native teams/compiler state end with this process; Python
                # context unwinding must not release ownership before then.
                exited.set()
                os._exit(0)
    # Only process exit establishes compiler/native-team release.


if __name__ == '__main__': main()
