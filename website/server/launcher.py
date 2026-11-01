"""Own managed server identity, startup transfer, and lifetime cleanup."""
from contextlib import ExitStack, contextmanager
import errno
import json
import os
from pathlib import Path
import secrets
from threading import Thread
import time
from urllib.request import Request, build_opener, ProxyHandler

ROOT=Path(__file__).resolve().parents[2]


def state_path(port):
    return ROOT/'data'/f'website-server-{port}.json'


def request(state,path,method='GET'):
    req=Request(f"http://127.0.0.1:{state['port']}{path}",method=method,headers={'X-Launcher-Token':state['token']})
    # Launcher traffic stays on loopback, independent of Windows proxy settings.
    with build_opener(ProxyHandler({})).open(req,timeout=2) as response:return json.load(response)


def active(port):
    try:
        state=json.loads(state_path(port).read_text())
        health=request(state,'/api/launcher')
        return state if health.get('token')==state['token'] and health.get('project')==str(ROOT) else None
    except (OSError,ValueError,KeyError):return None


@contextmanager
def file_lock(port,kind,timeout=30):
    """Hold a process lock; a failed health probe never bypasses ownership."""
    path=ROOT/'data'/f'website-{kind}-{port}.lock';path.parent.mkdir(exist_ok=True)
    handle=path.open('a+b')
    deadline=time.monotonic()+timeout
    try:
        # Windows byte-range locking needs an existing byte. Never truncate locks.
        if not path.stat().st_size:handle.write(b'0');handle.flush()
        while True:
            try:
                handle.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES,errno.EAGAIN,errno.EDEADLK):raise
                if time.monotonic()>=deadline:
                    raise RuntimeError('The previous website still owns the server. Let its active request finish or stop its terminal, then run backtest-web.cmd again.') from error
                time.sleep(.1)
        try:yield
        finally:
            if os.name=='nt':
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle,fcntl.LOCK_UN)
    finally:handle.close()


def wait_legacy_process(pid,timeout=30):
    """Older managed servers have no lifetime lock; wait for their process exit."""
    if not isinstance(pid,int) or pid<=0:raise RuntimeError('Stop the older website process before relaunching.')
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x100000,False,pid)
        if not handle:
            if ctypes.get_last_error()==87:return
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if kernel.WaitForSingleObject(handle,int(timeout*1000))!=0:
                raise RuntimeError('The older website is still stopping. Wait for its request to finish, then retry.')
        finally:kernel.CloseHandle(handle)
    else:
        deadline=time.monotonic()+timeout
        while True:
            try:os.kill(pid,0)
            except ProcessLookupError:return
            if time.monotonic()>=deadline:raise RuntimeError('The older website is still stopping. Wait for its request to finish, then retry.')
            time.sleep(.1)


class Lifecycle:
    """One terminal owns preparation, the bound server, and all request cleanup.

    Enter before preparation. Attach the bound server before serving. Exit closes
    the listener and joins request threads before releasing lifetime ownership.
    Startup serialization ends at attach; the lifetime lock ends only at exit.
    """
    def __init__(self,port,host,timeout=30):
        self.port=port;self.host=host;self.timeout=timeout
        self.startup=ExitStack();self.lifetime=ExitStack();self.server=None
        self.state=None

    def __enter__(self):
        try:
            self.startup.enter_context(file_lock(self.port,'launch',self.timeout))
            previous=active(self.port)
            if previous:
                print('Stopping the previous website so this terminal owns the server…',flush=True)
                request(previous,'/api/launcher','POST')
                if not previous.get('lifetime_lock'):
                    wait_legacy_process(previous.get('pid'),self.timeout)
            # Always acquire ownership, even when HTTP is down or unresponsive.
            self.lifetime.enter_context(file_lock(self.port,'owner',self.timeout))
            return self
        except BaseException:
            self.lifetime.close();self.startup.close();raise

    def attach(self,server):
        self.server=server
        # Request threads can still write to SQLite after the listener stops.
        server.daemon_threads=False
        server.block_on_close=True
        server.lifecycle=self
        self.state=dict(port=server.server_address[1],host=self.host,
                        token=secrets.token_hex(24),project=str(ROOT),
                        pid=os.getpid(),lifetime_lock=True)
        path=state_path(self.port);temporary=path.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(self.state),encoding='utf-8')
            temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)
        self.startup.close()

    def control(self,handler):
        """Handle authenticated launcher requests without exposing the record format."""
        if handler.path!='/api/launcher':return False
        if not self.state or handler.headers.get('X-Launcher-Token')!=self.state['token'] or handler.headers.get('Origin'):
            handler.reply(403,dict(error='Invalid launcher request.'));return True
        if handler.command=='GET':handler.reply(200,self.state)
        else:
            handler.reply(200,dict(stopping=True))
            Thread(target=self.server.shutdown,daemon=True).start()
        return True

    def __exit__(self,*error):
        try:
            if self.server:self.server.server_close()
        finally:
            try:
                if self.state:
                    path=state_path(self.port)
                    try:
                        if json.loads(path.read_text(encoding='utf-8')).get('token')==self.state['token']:path.unlink()
                    except (FileNotFoundError,ValueError):pass
            finally:
                self.lifetime.close();self.startup.close()
