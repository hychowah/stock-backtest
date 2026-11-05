"""Persistent local diagnostics without exception messages, source or locals.

Callers supply controlled operational context: names, enums and numbers, never
credentials, provider URLs, response bodies, formulas or run identifiers, which
are capabilities. Error chains retain types, OS codes and stack locations.
Each server process owns its rotating files, including when ports run together.
operation() records the duration, outcome, stages and counts of one operation.
An operation that runs longer than PROGRESS_SECONDS also reports progress.
"""

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import itertools
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import sys
from pathlib import Path
from threading import Event, Lock, Thread
import time
import uuid

from backtest.paths import ROOT
from backtest.runtime import backtest_control

MAX_BYTES=5*1024*1024
BACKUPS=2
RETENTION_DAYS=14
TOTAL_BYTES=100*1024*1024
MAX_FILES=50
DIRECTORY=ROOT/'data'/'logs'
LOG_NAME=re.compile(r'website-(?:([0-9a-f]{32})-)?([1-9][0-9]*)\.log(?:\.[1-9][0-9]*)?')
LOGGER=logging.getLogger('backtest')
LOGGER.setLevel(logging.INFO)
LOGGER.propagate=False
LOGGER.addHandler(logging.NullHandler())
PROGRESS_SECONDS=60
REPEAT_SECONDS=300
_handler=None
_operation=ContextVar('diagnostics_operation',default=None)
_open={};_open_lock=Lock();_wake=Event();_watcher=None;_numbers=itertools.count(1)


def _process_namespace():
    """Identify the host PID namespace; logs of unknown ownership age out only.

    Linux boot identity prevents reuse of a PID namespace inode across boots.
    Windows PIDs belong to the machine, not to an individual login session.
    """
    try:
        if os.name=='nt':
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Cryptography',
                                0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
                identity=winreg.QueryValueEx(key,'MachineGuid')[0]
            identity='windows:'+identity
        elif sys.platform.startswith('linux'):
            boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            identity='linux:'+boot+':'+os.readlink('/proc/self/ns/pid')
        else:return None
    except (OSError,ValueError):return None
    return hashlib.sha256(identity.encode()).hexdigest()[:32]


def _process_running(pid):
    """Treat inaccessible or uncertain process state as running."""
    if pid==os.getpid() or pid>0x7fffffff:return True
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.WaitForSingleObject.restype=wintypes.DWORD
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        kernel.CloseHandle.restype=wintypes.BOOL
        handle=kernel.OpenProcess(0x00100000,False,pid) # SYNCHRONIZE
        if not handle:return ctypes.get_last_error()!=87 # ERROR_INVALID_PARAMETER: no process
        try:return kernel.WaitForSingleObject(handle,0)!=0
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0)
    except ProcessLookupError:return False
    except OSError:return True
    return True


def cleanup(directory):
    """Prune logs by age, then oldest first by total size and file count.

    A stopped process's log in the current namespace is pruned by any rule.
    The size and count targets cover only these logs. Legacy, foreign-namespace
    and unknown-namespace logs have no checkable PID: only age prunes them,
    after RETENTION_DAYS without a write. A Linux reboot starts a new
    namespace. Active and inaccessible files can leave the current namespace
    above its targets. Cleanup failures must not block startup.
    """
    try:paths=list(Path(directory).iterdir())
    except OSError:return
    namespace=_process_namespace()
    entries=[];total=count=0
    for path in paths:
        match=LOG_NAME.fullmatch(path.name)
        if not match:continue
        try:
            if path.is_symlink() or not path.is_file():continue
            stat=path.stat()
        except OSError:continue
        local=namespace is not None and match[1]==namespace
        if local:total+=stat.st_size;count+=1
        entries.append((stat.st_mtime,path,stat.st_size,int(match[2]),local))
    cutoff=time.time()-RETENTION_DAYS*86400
    for modified,path,size,pid,local in sorted(entries):
        if not local:
            if modified>=cutoff:continue
        elif (modified>=cutoff and total<=TOTAL_BYTES and count<=MAX_FILES) or _process_running(pid):continue
        try:path.unlink()
        except OSError:continue
        if local:total-=size;count-=1


def relative_path(path):
    if '://' in str(path) or '?' in str(path):return '<external path>'
    path=Path(path)
    try:return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:return path.name


def configure(directory=None):
    """Open a process-owned log; unavailable logging must not stop the server."""
    global _handler
    close()
    directory=Path(directory) if directory is not None else DIRECTORY
    try:
        directory.mkdir(parents=True,exist_ok=True)
        cleanup(directory)
        namespace=_process_namespace() or uuid.uuid4().hex
        handler=RotatingFileHandler(directory/f'website-{namespace}-{os.getpid()}.log',maxBytes=MAX_BYTES,backupCount=BACKUPS,encoding='utf-8')
    except OSError:return None
    formatter=logging.Formatter('%(asctime)sZ %(levelname)s %(message)s',datefmt='%Y-%m-%dT%H:%M:%S')
    formatter.converter=time.gmtime
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler);_handler=handler
    _start_watcher()
    return Path(handler.baseFilename)


def close():
    global _handler
    if _handler is not None:
        LOGGER.removeHandler(_handler);_handler.close();_handler=None


def log_path():
    return Path(_handler.baseFilename) if _handler is not None else None


def event(name,**context):
    LOGGER.info(json.dumps(dict(event=name,pid=os.getpid(),**context),ensure_ascii=True))


@contextmanager
def operation(name):
    """Write one event when the operation ends, also as a function decorator.

    The event has the outcome, wall seconds, this thread's CPU seconds, stage
    seconds and counts. op numbers the operation within this process, so
    readers can match its progress lines. An exception records only its type. The body can note
    its own outcome. stage(), lap(), note() and count() add to the innermost
    open operation of the calling thread; outside one they do nothing. Stages
    are measured regions. They can overlap and need not add up to seconds.
    """
    state=dict(name=name,op=next(_numbers),parent=_operation.get(),fields={},stages={},counts={},started=time.perf_counter(),
               cpu=time.thread_time(),process=time.process_time(),last_step=None,stage=None,reported=None)
    state['lap']=state['started']
    token=_operation.set(state);outcome=None;error=None
    with _open_lock:_open[id(state)]=state
    _wake.set()
    try:yield
    except backtest_control.Cancelled:
        outcome='cancelled';raise
    except Exception as caught:
        outcome='failed';error=type(caught).__name__;raise
    except BaseException:
        outcome='interrupted';raise
    finally:
        _operation.reset(token)
        with _open_lock:del _open[id(state)]
        parent=state['parent']
        if parent is not None:
            parent['inner_ended']=True
            # A reported inner operation hands its progress trail to the outer one.
            if state['reported'] is not None:parent['reported']=None
        fields=state['fields'];noted=fields.pop('outcome','completed')
        record=dict(event=name,pid=os.getpid(),op=state['op'],outcome=outcome or noted)
        if error:record['error']=error
        record.update(fields)
        record.update(seconds=round(time.perf_counter()-state['started'],3),
            cpu_seconds=round(time.thread_time()-state['cpu'],3),
            stages={key:round(value,3) for key,value in state['stages'].items()},counts=state['counts'])
        try:LOGGER.log(logging.WARNING if record['outcome']=='failed' else logging.INFO,json.dumps(record,ensure_ascii=True))
        except (TypeError,ValueError):warning('diagnostics.unserializable',operation=name)
        _wake.set()


@contextmanager
def stage(name):
    """Add the seconds spent in this block to the current operation's stage."""
    state=_operation.get()
    if state is None:
        yield;return
    started=time.perf_counter();outer=state['stage'];state['stage']=name
    try:yield
    finally:
        state['stage']=outer
        state['stages'][name]=state['stages'].get(name,0.)+time.perf_counter()-started


def lap(name):
    """Add the seconds since the operation start or previous lap to a stage.

    A step of PROGRESS_SECONDS or more is also logged when it ends, unless an
    inner operation ended in it: that operation's end line already shows it.
    """
    state=_operation.get()
    if state is None:return
    now=time.perf_counter();seconds=now-state['lap'];repeated=state.pop('inner_ended',False)
    state['stages'][name]=state['stages'].get(name,0.)+seconds;state['lap']=now;state['last_step']=name
    if seconds>=PROGRESS_SECONDS and not repeated:
        event(state['name'],op=state['op'],state='step',step=name,step_seconds=round(seconds,1),seconds=round(now-state['started'],1))


def note(**fields):
    """Set controlled fields, including outcome, on the current operation."""
    state=_operation.get()
    if state is not None:state['fields'].update(fields)


def count(name,amount=1):
    state=_operation.get()
    if state is not None:state['counts'][name]=state['counts'].get(name,0)+amount


def _start_watcher():
    global _watcher
    if _watcher is None:
        _watcher=Thread(target=_watch,name='diagnostics-progress',daemon=True);_watcher.start()


def _watch():
    """Report open operations after PROGRESS_SECONDS, then every REPEAT_SECONDS.

    A report also counts for the operations around the reporter, which it
    names. An operation with an open inner operation waits PROGRESS_SECONDS
    more, so a long inner operation reports for it; one made of short inner
    operations then reports for itself. Operations wake the thread when they
    start and end; it sleeps while no operation is open.
    """
    while True:
        _wake.clear();now=time.perf_counter();wait=None
        with _open_lock:states=list(_open.values())
        outer={id(state['parent']) for state in states if state['parent'] is not None}
        for state in states:
            due=state['started']+PROGRESS_SECONDS if state['reported'] is None else state['reported']+REPEAT_SECONDS
            if id(state) in outer:due+=PROGRESS_SECONDS
            if due<=now:
                # An ending operation leaves _open under this lock before its end line.
                with _open_lock:
                    if _open.get(id(state)) is state:_progress(state,now)
                due=now+REPEAT_SECONDS
            wait=due-now if wait is None else min(wait,due-now)
        _wake.wait(wait)


def _progress(state,now):
    within=[];parent=state['parent']
    while parent is not None:within.insert(0,parent['name']);parent['reported']=now;parent=parent['parent']
    state['reported']=now
    record=dict(op=state['op'],state='running',seconds=round(now-state['started'],1),
                process_cpu_seconds=round(time.process_time()-state['process'],1))
    if within:record['within']=within
    if state['last_step']:record.update(last_step=state['last_step'],since_step_seconds=round(now-state['lap'],1))
    if state['stage']:record['stage']=state['stage']
    record['counts']=dict(state['counts'])
    event(state['name'],**record)


def warning(name,**context):
    LOGGER.warning(json.dumps(dict(event=name,pid=os.getpid(),**context),ensure_ascii=True))


def records(directory=None):
    """Yield the saved events of every log in directory, oldest file first.

    Each event gains its line's UTC time and level. Unreadable files and lines
    that are not events are skipped. Reading never changes a log.
    """
    directory=Path(directory) if directory is not None else DIRECTORY
    try:paths=list(directory.iterdir())
    except OSError:return
    saved=[]
    for path in paths:
        try:
            if LOG_NAME.fullmatch(path.name) and path.is_file():saved.append((path.stat().st_mtime,path))
        except OSError:continue
    for _,path in sorted(saved):
        try:lines=path.read_text(encoding='utf-8',errors='replace').splitlines()
        except OSError:continue
        for line in lines:
            stamp,level,text=(line.split(' ',2)+['',''])[:3]
            try:record=json.loads(text)
            except ValueError:continue
            if isinstance(record,dict) and isinstance(record.get('event'),str):
                yield dict(record,time=stamp,level=level)


def failure(name,error,**context):
    """Keep safe tracebacks, omitting arbitrary exception text and source lines."""
    errors=[];seen=set()
    while error is not None and id(error) not in seen:
        seen.add(id(error));frames=[];tb=error.__traceback__
        while tb is not None:
            code=tb.tb_frame.f_code
            frames.append(dict(file=relative_path(code.co_filename),line=tb.tb_lineno,function=code.co_name))
            tb=tb.tb_next
        detail=dict(type=type(error).__name__,frames=frames)
        for key in ('errno','winerror','sqlite_errorcode','returncode'):
            value=getattr(error,key,None)
            if isinstance(value,int):detail[key]=value
        if isinstance(error,OSError):
            for key in ('filename','filename2'):
                value=getattr(error,key,None)
                if value:detail[key]=relative_path(value)
        errors.append(detail)
        error=error.__cause__ or (error.__context__ if not error.__suppress_context__ else None)
    LOGGER.error(json.dumps(dict(event=name,pid=os.getpid(),errors=errors,**context),ensure_ascii=True))
