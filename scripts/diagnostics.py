"""Persistent local diagnostics without exception messages, source or locals.

Callers supply controlled operational context, never credentials, provider URLs
or response bodies. Error chains retain types, OS codes and stack locations.
Each server process owns its rotating files, including when ports run together.
"""
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import sys
from pathlib import Path
import time
import uuid

from paths import ROOT

MAX_BYTES=5*1024*1024
BACKUPS=2
RETENTION_DAYS=14
TOTAL_BYTES=100*1024*1024
LOGGER=logging.getLogger('backtest')
LOGGER.setLevel(logging.INFO)
LOGGER.propagate=False
LOGGER.addHandler(logging.NullHandler())
_handler=None


def _process_namespace():
    """Identify the host PID namespace; unknown ownership is never pruned.

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
    """Prune stopped-process logs by age, then oldest first by total size.

    Active and inaccessible files can leave the directory above the size target.
    Only logs from the current process namespace are eligible. Legacy and
    foreign-namespace logs are preserved and count toward total size. Cleanup failures must not block startup.
    """
    try:paths=list(Path(directory).iterdir())
    except OSError:return
    namespace=_process_namespace()
    entries=[];total=0
    for path in paths:
        match=re.fullmatch(r'website-(?:([0-9a-f]{32})-)?([1-9][0-9]*)\.log(?:\.[1-9][0-9]*)?',path.name)
        if not match:continue
        try:
            if path.is_symlink() or not path.is_file():continue
            stat=path.stat()
        except OSError:continue
        total+=stat.st_size
        entries.append((stat.st_mtime,path,stat.st_size,int(match[2]),match[1]))
    cutoff=time.time()-RETENTION_DAYS*86400
    for modified,path,size,pid,owner in sorted(entries):
        if namespace is None or owner!=namespace:continue
        if modified>=cutoff and total<=TOTAL_BYTES:continue
        if _process_running(pid):continue
        try:path.unlink()
        except OSError:continue
        total-=size


def relative_path(path):
    if '://' in str(path) or '?' in str(path):return '<external path>'
    path=Path(path)
    try:return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:return path.name


def configure(directory=None):
    """Open a process-owned log; unavailable logging must not stop the server."""
    global _handler
    close()
    directory=Path(directory) if directory is not None else ROOT/'data'/'logs'
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
    return Path(handler.baseFilename)


def close():
    global _handler
    if _handler is not None:
        LOGGER.removeHandler(_handler);_handler.close();_handler=None


def log_path():
    return Path(_handler.baseFilename) if _handler is not None else None


def event(name,**context):
    LOGGER.info(json.dumps(dict(event=name,pid=os.getpid(),**context),ensure_ascii=True))


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
