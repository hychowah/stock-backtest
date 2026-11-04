"""Private fictional browser qualification; no launcher, profiles or real inputs.

Own one new native browser and its private state against one already-owned
fictional service. Publish no session before containment and endpoint validation
succeed. Return evidence from actual controls, ordinary requests and completed
downloads. Keep roots until browser and service closure are confirmed.
"""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
import base64
from collections import deque
from functools import wraps
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backtest.runtime.process_owner import OwnedProcess, ProcessLimits

MIB = 1024**2
LIMITS = dict(committed_bytes=1024**3, processes=16, cpu_percent=25,
    user_cpu_seconds=120, startup_seconds=45, operation_seconds=60,
    session_seconds=450, close_seconds=15, profile_cache_bytes=128*MIB,
    root_bytes=192*MIB, downloads_bytes=16*MIB, evidence_bytes=16*MIB,
    bootstrap_output_bytes=MIB, cdp_message_bytes=16*MIB,
    pending_events=128, pending_event_bytes=4*MIB, received_bytes=64*MIB)
EXECUTABLE = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
_retained = {}


class BrowserFailure(RuntimeError):
    pass


class BrowserLimit(BrowserFailure):
    pass


def _bounded(method):
    """One public operation budget includes every nested CDP/DOM step."""
    @wraps(method)
    def run(self, *args, **kwargs):
        previous = self.operation_deadline
        self.operation_deadline = self.deadline()
        try: return method(self, *args, **kwargs)
        finally: self.operation_deadline = previous
    return run


class BrowserStorage:
    """Register before start. Delete only after all dependent owners close."""
    def __init__(self):
        self.root = None
        self.owners = []
        self.closed = False

    def start(self):
        if self.root is not None or self.closed:
            raise BrowserFailure('Browser storage was already started.')
        _retained[id(self)] = self
        self.root = Path(tempfile.mkdtemp(prefix='cb02-native-browser-'))
        for name in ('profile', 'cache', 'downloads', 'evidence', 'temp'):
            (self.root/name).mkdir()
        return self

    def inventory(self):
        """Fresh complete recursive sample; no inventory survives between calls.

        Keep all category ceilings, reject links and propagate unexpected file
        errors. An entry that disappears during observation can be absent.
        """
        totals = dict(root=0, profile_cache=0, downloads=0, evidence=0)
        pending = [(str(self.root), None)]
        while pending:
            directory, category = pending.pop()
            try: entries = os.scandir(directory)
            except FileNotFoundError: continue
            with entries as children:
                for entry in children:
                    try:
                        if entry.is_symlink():
                            raise BrowserFailure('Unexpected browser storage link.')
                        group = category if category is not None else entry.name
                        if entry.is_dir(follow_symlinks=False):
                            pending.append((entry.path, group))
                        elif entry.is_file(follow_symlinks=False):
                            size = entry.stat(follow_symlinks=False).st_size
                            totals['root'] += size
                            if group in ('profile', 'cache'): totals['profile_cache'] += size
                            # Match the original Path.is_relative_to semantics
                            # for attachments on case-insensitive Windows paths.
                            attachment = group.lower() if os.name == 'nt' else group
                            if attachment in ('downloads', 'evidence'): totals[attachment] += size
                    except FileNotFoundError:
                        # Chrome can rename a completed .crdownload between
                        # observations. This sample is not a filesystem quota.
                        continue
        for name, value in totals.items():
            if value > LIMITS[name+'_bytes']:
                raise BrowserLimit('Browser logical storage bound: '+name)
        return totals

    def close(self):
        if self.closed: return
        if any(not owner.closed for owner in self.owners):
            _retained[id(self)] = self
            raise BrowserFailure('Browser storage dependencies remain open.')
        if self.root is not None:
            until = time.monotonic()+3.
            while True:
                try:
                    shutil.rmtree(self.root)
                    break
                except PermissionError:
                    if time.monotonic() >= until: raise
                    time.sleep(.05)
        self.closed = True
        _retained.pop(id(self), None)

    def preserve(self):
        """Keep bounded actual download/screenshot files after dependency closure.

        The explicit test source export owns this artifact directory. Browser
        state is still removed separately by close; profiles are not archived.
        """
        if self.closed or any(not owner.closed for owner in self.owners):
            raise BrowserFailure('Close browser and service before preserving evidence.')
        self.inventory()
        output = ROOT/'tmp'/'native-browser-evidence'/uuid.uuid4().hex
        output.mkdir(parents=True)
        manifest = {}
        for folder in ('downloads','evidence'):
            (output/folder).mkdir()
            for path in (self.root/folder).iterdir():
                if not path.is_file() or path.is_symlink(): raise BrowserFailure('Invalid browser evidence asset.')
                target = output/folder/path.name
                shutil.copyfile(path,target)
                manifest[target.relative_to(output).as_posix()] = dict(bytes=target.stat().st_size,
                    sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        (output/'manifest.json').write_text(json.dumps(manifest,sort_keys=True),encoding='utf-8')
        return dict(root=str(output),files=manifest)


class _WebSocket:
    """Serialized bounded RFC6455 subset for the owned Chromium endpoint."""
    def __init__(self, port, path, deadline, checkpoint):
        self.socket = None
        self.received = 0
        self.checkpoint = checkpoint
        try:
            self.socket = socket.create_connection(('127.0.0.1', port), timeout=max(.01, deadline-time.monotonic()))
            key = base64.b64encode(os.urandom(16)).decode('ascii')
            self._send_raw(('GET '+path+' HTTP/1.1\r\nHost: 127.0.0.1:'+str(port)+
                '\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: '+key+
                '\r\nSec-WebSocket-Version: 13\r\n\r\n').encode('ascii'), deadline)
            header = bytearray()
            while not header.endswith(b'\r\n\r\n'):
                if len(header) >= 8192: raise BrowserLimit('WebSocket upgrade header bound.')
                header.extend(self._read(1, deadline))
            lines = header.decode('ascii').split('\r\n')
            if lines[0] != 'HTTP/1.1 101 WebSocket Protocol Handshake' and not lines[0].startswith('HTTP/1.1 101 '):
                raise BrowserFailure('WebSocket upgrade rejected.')
            fields = {}
            for line in lines[1:-2]:
                name, value = line.split(':', 1)
                name = name.lower()
                if name in fields: raise BrowserFailure('Duplicate WebSocket upgrade header.')
                fields[name] = value.strip()
            expected = base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')).digest()).decode('ascii')
            if (fields.get('upgrade', '').lower() != 'websocket' or
                'upgrade' not in fields.get('connection', '').lower().split(', ') or
                fields.get('sec-websocket-accept') != expected or
                'sec-websocket-extensions' in fields or 'sec-websocket-protocol' in fields):
                raise BrowserFailure('Invalid WebSocket upgrade identity.')
        except BaseException:
            self.close()
            raise

    def _remaining(self, deadline):
        self.checkpoint()
        remaining = deadline-time.monotonic()
        if remaining <= 0: raise TimeoutError('Browser operation deadline expired.')
        self.socket.settimeout(min(.25, remaining))

    def _read(self, count, deadline):
        data = bytearray()
        while len(data) < count:
            self._remaining(deadline)
            try: part = self.socket.recv(min(65536, count-len(data)))
            except socket.timeout: continue
            if not part: raise BrowserFailure('Browser debugger closed its transport.')
            self.received += len(part)
            if self.received > LIMITS['received_bytes']: raise BrowserLimit('Browser received-byte bound.')
            data.extend(part)
        return bytes(data)

    def _send_raw(self, data, deadline):
        view = memoryview(data)
        while view:
            self._remaining(deadline)
            try: sent = self.socket.send(view)
            except socket.timeout: continue
            if not sent: raise BrowserFailure('Browser debugger send failed.')
            view = view[sent:]

    def send(self, data, deadline, opcode=1):
        if len(data) > LIMITS['cdp_message_bytes']: raise BrowserLimit('Browser message bound.')
        if opcode >= 8 and len(data) > 125: raise BrowserFailure('Invalid control frame.')
        length = len(data)
        header = bytes((0x80|opcode, 0x80|length)) if length < 126 else (
            bytes((0x80|opcode, 0x80|126))+struct.pack('!H', length) if length < 65536 else
            bytes((0x80|opcode, 0x80|127))+struct.pack('!Q', length))
        mask = os.urandom(4)
        self._send_raw(header+mask+bytes(v^mask[i%4] for i,v in enumerate(data)), deadline)

    def receive(self, deadline):
        message = bytearray()
        started = False
        while True:
            first, second = self._read(2, deadline)
            final, opcode = bool(first&128), first&15
            if first&112 or second&128 or opcode not in (0, 1, 8, 9, 10):
                raise BrowserFailure('Unsupported WebSocket frame.')
            length = second&127
            if length == 126:
                length = struct.unpack('!H', self._read(2, deadline))[0]
                if length < 126: raise BrowserFailure('Nonminimal WebSocket length.')
            elif length == 127:
                length = struct.unpack('!Q', self._read(8, deadline))[0]
                if length < 65536 or length >= 2**63: raise BrowserFailure('Invalid WebSocket length.')
            if opcode >= 8:
                if not final or length > 125: raise BrowserFailure('Invalid WebSocket control frame.')
                data = self._read(length, deadline)
                if opcode == 8:
                    if length == 1: raise BrowserFailure('Invalid WebSocket close frame.')
                    raise BrowserFailure('Browser debugger sent close.')
                if opcode == 9: self.send(data, deadline, opcode=10)
                continue
            if (opcode == 1 and started) or (opcode == 0 and not started):
                raise BrowserFailure('Invalid WebSocket fragmentation.')
            started = True
            if len(message)+length > LIMITS['cdp_message_bytes']:
                raise BrowserLimit('Browser fragmented-message bound.')
            message.extend(self._read(length, deadline))
            if final:
                try: value = json.loads(message.decode('utf-8'))
                except (UnicodeError, ValueError): raise BrowserFailure('Invalid CDP JSON.') from None
                if not isinstance(value, dict): raise BrowserFailure('Invalid CDP object.')
                return value

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None


class NativeBrowser:
    """One owned session. Storage and service are registered before effects."""
    def __init__(self, storage, service=None, *, renderer_processes=None):
        if renderer_processes is not None and (type(renderer_processes) is not int or not 1<=renderer_processes<=8):
            raise ValueError('Choose between 1 and 8 private renderer processes.')
        self.renderer_processes=renderer_processes
        self.storage, self.service = storage, service
        self.owned = self.ws = None
        self.closed = False
        self.sequence = 0
        self.events = deque()
        self.event_bytes = 0
        self.errors = []
        self.error_bytes = 0
        self.session = None
        self.started = None
        self.last_inventory = 0.
        self.operation_deadline = float('inf')
        storage.owners.append(self)
        if service is not None: storage.owners.append(service)

    def checkpoint(self):
        if time.monotonic() >= self.started+LIMITS['session_seconds']-LIMITS['close_seconds']:
            raise BrowserLimit('Browser session active-work deadline.')
        if self.owned is not None:
            if self.owned.resource_failure(): raise BrowserLimit('Browser Job or bootstrap output bound.')
            if self.owned.process.poll() is not None: raise BrowserFailure('Browser bootstrap exited.')
            while not self.owned.events.empty():
                value = self.owned.events.get_nowait()
                if value.get('event') == 'failed': raise BrowserLimit('Browser bootstrap declared a limit.')
                # Startup consumes its own browser_started handshake.
                if value.get('event') == 'browser_started':
                    self.bootstrap_ready = value
        if time.monotonic()-self.last_inventory >= .25:
            self.storage.inventory()
            self.last_inventory = time.monotonic()

    def deadline(self, seconds=None):
        self.checkpoint()
        return min(time.monotonic()+(LIMITS['operation_seconds'] if seconds is None else seconds),
                   self.started+LIMITS['session_seconds']-LIMITS['close_seconds'],self.operation_deadline)

    def start(self):
        if os.name != 'nt': raise BrowserFailure('Native browser requires Windows.')
        if self.started is not None or self.closed: raise BrowserFailure('Browser already started.')
        if not EXECUTABLE.is_file(): raise BrowserFailure('Fixed native browser executable unavailable.')
        if self.service is not None and (not self.service.ready or self.service.closed or self.service.port in (0,3000)):
            raise BrowserFailure('Invalid owned fictional service.')
        self.started = time.monotonic()
        startup_deadline = self.started+LIMITS['startup_seconds']
        _retained[id(self)] = self
        try:
            if self.storage.root is None: self.storage.start()
            command = [sys.executable, '-X', 'utf8', '-I', '-B', '-c',
                'import sys;sys.path.insert(0,sys.argv[1]);from native_browser_fixture import bootstrap;bootstrap(sys.argv[2],renderer_processes=int(sys.argv[3]) if len(sys.argv)>3 else None)',
                str(ROOT/'tests'), str(self.storage.root)]
            if self.renderer_processes is not None:command.append(str(self.renderer_processes))
            env = dict(os.environ, TEMP=str(self.storage.root/'temp'), TMP=str(self.storage.root/'temp'))
            self.owned = OwnedProcess(command, env=env, limits=ProcessLimits(
                LIMITS['committed_bytes'], LIMITS['processes'], LIMITS['cpu_percent'],
                user_cpu_seconds=LIMITS['user_cpu_seconds'], close_seconds=3.))
            self.owned.start()
            until = min(startup_deadline,self.deadline(LIMITS['startup_seconds']))
            while True:
                self.checkpoint()
                event = getattr(self, 'bootstrap_ready', None)
                if event and event.get('event') == 'browser_started':
                    self.browser_pid = event['pid']
                    if not self._member(self.browser_pid): raise BrowserFailure('Browser did not inherit its owned Job.')
                    break
                if time.monotonic() >= until: raise TimeoutError('Browser process startup expired.')
                time.sleep(.02)
            active = self.storage.root/'profile/DevToolsActivePort'
            while not active.is_file():
                self.checkpoint()
                if time.monotonic() >= until: raise TimeoutError('Owned debugger discovery expired.')
                time.sleep(.02)
            raw = active.read_bytes()
            if len(raw) > 4096: raise BrowserLimit('Debugger discovery bound.')
            lines = raw.decode('ascii').splitlines()
            if len(lines) != 2 or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]+', lines[1]):
                raise BrowserFailure('Invalid owned debugger discovery.')
            port = int(lines[0])
            if not 0 < port < 65536 or port == 3000: raise BrowserFailure('Invalid owned debugger port.')
            client = http.client.HTTPConnection('127.0.0.1', port, timeout=max(.01,until-time.monotonic()))
            try:
                client.request('GET', '/json/version')
                response = client.getresponse()
                body = response.read(8193)
                if response.status != 200 or len(body)>8192: raise BrowserFailure('Invalid debugger identity response.')
                version = json.loads(body)
                if version.get('webSocketDebuggerUrl') != 'ws://127.0.0.1:'+str(port)+lines[1]:
                    raise BrowserFailure('Debugger identity does not match owned profile.')
                if not version.get('Browser', '').startswith('Chrome/'):
                    raise BrowserFailure('Unexpected browser identity.')
                self.identity = dict(browser=version['Browser'], protocol=version['Protocol-Version'],
                                     pid=self.browser_pid, inherited_job=True)
            finally: client.close()
            self.ws = _WebSocket(port, lines[1], until, self.checkpoint)
            self.command('Browser.setDownloadBehavior', dict(behavior='allowAndName',
                downloadPath=str(self.storage.root/'downloads'), eventsEnabled=True), deadline=until)
            target = self.command('Target.createTarget', dict(url='about:blank'), deadline=until)['targetId']
            self.session = self.command('Target.attachToTarget', dict(targetId=target, flatten=True), deadline=until)['sessionId']
            for method in ('Page.enable', 'Runtime.enable', 'Network.enable'):
                self.command(method, page=True, deadline=until)
            self.command('Page.setLifecycleEventsEnabled',dict(enabled=True),page=True,deadline=until)
            return self
        except BaseException as error:
            self.owned = self.owned or getattr(error, 'owned_process', None)
            try: self.close()
            except BaseException: error.native_browser = self
            raise

    def _member(self, pid):
        import ctypes
        from ctypes import wintypes as w
        kernel = self.owned.kernel
        kernel.OpenProcess.argtypes = [w.DWORD,w.BOOL,w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.IsProcessInJob.argtypes = [w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)]
        handle = kernel.OpenProcess(0x1000,False,pid)
        if not handle: raise ctypes.WinError(ctypes.get_last_error())
        try:
            result = w.BOOL()
            if not kernel.IsProcessInJob(handle,self.owned.job,ctypes.byref(result)):
                raise ctypes.WinError(ctypes.get_last_error())
            return bool(result.value)
        finally: kernel.CloseHandle(handle)

    def _event(self, value):
        method = value.get('method', '')
        if method == 'Runtime.exceptionThrown':
            size = len(json.dumps(value).encode('utf-8'))
            if (len(self.errors)+len(self.events)+1 > LIMITS['pending_events'] or
                self.error_bytes+self.event_bytes+size > LIMITS['pending_event_bytes']):
                raise BrowserLimit('Page error bound.')
            self.errors.append(value['params'])
            self.error_bytes += size
        if (method.startswith('Browser.download') or
            method == 'Page.lifecycleEvent' and value['params']['name']=='load' or
            method in ('Network.requestWillBeSent', 'Network.responseReceived', 'Network.loadingFinished', 'Network.loadingFailed')):
            if method in ('Network.requestWillBeSent','Network.responseReceived'):
                url = value['params'].get('request',value['params'].get('response',{})).get('url','')
                if not urlsplit(url).path.startswith('/api/'): return
            size = len(json.dumps(value).encode('utf-8'))
            if len(self.events)+len(self.errors)+1 > LIMITS['pending_events'] or self.event_bytes+self.error_bytes+size > LIMITS['pending_event_bytes']:
                raise BrowserLimit('Pending browser event bound.')
            self.events.append((value,size)); self.event_bytes += size

    @_bounded
    def command(self, method, params=None, *, page=False, deadline=None):
        deadline = self.deadline() if deadline is None else deadline
        deadline = min(deadline,self.operation_deadline)
        self.sequence += 1
        number = self.sequence
        request = dict(id=number, method=method, params=params or {})
        if page: request['sessionId'] = self.session
        self.ws.send(json.dumps(request).encode('utf-8'), deadline)
        while True:
            value = self.ws.receive(deadline)
            if 'id' in value:
                if value['id'] != number: raise BrowserFailure('Unexpected CDP response identity.')
                if 'error' in value: raise BrowserFailure('CDP command rejected: '+method)
                return value.get('result',{})
            self._event(value)

    @_bounded
    def event(self, method, predicate=lambda p: True, *, deadline=None):
        deadline = self.deadline() if deadline is None else deadline
        deadline = min(deadline,self.operation_deadline)
        while True:
            for item in list(self.events):
                value,size = item
                if value.get('method') == method and predicate(value['params']):
                    self.events.remove(item); self.event_bytes -= size
                    return value['params']
            value = self.ws.receive(deadline)
            if 'id' in value: raise BrowserFailure('Unsolicited CDP response.')
            self._event(value)

    def clear_events(self):
        self.events.clear(); self.event_bytes = 0

    @_bounded
    def evaluate(self, expression):
        result = self.command('Runtime.evaluate', dict(expression=expression, returnByValue=True, awaitPromise=True), page=True)
        if 'exceptionDetails' in result: raise BrowserFailure('Browser evaluation failed.')
        return result.get('result',{}).get('value')

    @_bounded
    def wait(self, expression):
        until = self.deadline()
        while True:
            if self.evaluate(expression): return
            if time.monotonic() >= until: raise TimeoutError('Browser DOM condition expired.')
            time.sleep(.02)

    @_bounded
    def navigate(self, url):
        parsed = urlsplit(url)
        if not (parsed.scheme == 'http' and parsed.hostname == '127.0.0.1' and
                self.service is not None and parsed.port == self.service.port):
            raise BrowserFailure('Navigation requires the owned fictional service.')
        navigation = self.command('Page.navigate', dict(url=url), page=True)
        if 'errorText' in navigation: raise BrowserFailure('Owned service navigation failed.')
        self.event('Page.lifecycleEvent',lambda p:p.get('loaderId')==navigation['loaderId'] and p['name']=='load')

    @_bounded
    def click(self, selector):
        query = json.dumps(selector)
        self.wait('(()=>{const e=document.querySelector('+query+');return e&&!e.disabled&&e.getClientRects().length>0;})()')
        point = self.evaluate('(()=>{const e=document.querySelector('+query+');if(!e||e.disabled)throw Error("Unavailable control");e.scrollIntoView({block:"center"});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()')
        for kind in ('mousePressed','mouseReleased'):
            self.command('Input.dispatchMouseEvent', dict(type=kind, button='left',clickCount=1,**point), page=True)

    @_bounded
    def fill(self, selector, value):
        self.wait('(()=>{const e=document.querySelector('+json.dumps(selector)+');return e&&!e.disabled;})()')
        self.evaluate('(()=>{const e=document.querySelector('+json.dumps(selector)+');if(!e||e.disabled)throw Error("Unavailable control");e.focus();e.value='+json.dumps(str(value))+';if(e.value!=='+json.dumps(str(value))+')throw Error("Control rejected value");e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));})()')

    @_bounded
    def viewport(self, width, height):
        self.command('Emulation.setDeviceMetricsOverride', dict(width=width,height=height,deviceScaleFactor=1,mobile=False), page=True)

    @_bounded
    def download(self, selector):
        until = self.deadline()
        self.click(selector)
        begin = self.event('Browser.downloadWillBegin', deadline=until)
        guid = begin['guid']
        if not re.fullmatch('[A-Za-z0-9-]{1,128}', guid): raise BrowserFailure('Invalid download identity.')
        while True:
            progress = self.event('Browser.downloadProgress', lambda p:p['guid']==guid, deadline=until)
            if progress['state'] == 'canceled': raise BrowserFailure('Browser download canceled.')
            if progress['state'] == 'completed': break
        path = self.storage.root/'downloads'/guid
        if not path.is_file() or path.is_symlink() or path.with_name(guid+'.crdownload').exists():
            raise BrowserFailure('Completed download file unavailable.')
        self.storage.inventory()
        data = path.read_bytes()
        if len(data) != progress['receivedBytes']: raise BrowserFailure('Download byte evidence differs.')
        return dict(guid=guid,name=begin['suggestedFilename'],bytes=len(data),sha256=hashlib.sha256(data).hexdigest()), data

    @_bounded
    def screenshot(self, name):
        if not re.fullmatch('[a-z-]+',name): raise ValueError('Invalid screenshot name.')
        result = self.command('Page.captureScreenshot', dict(format='png'), page=True)
        data = base64.b64decode(result['data'],validate=True)
        if len(data) > LIMITS['evidence_bytes']: raise BrowserLimit('Screenshot bound.')
        (self.storage.root/'evidence'/(name+'.png')).write_bytes(data)
        self.storage.inventory()

    def close(self):
        if self.closed: return
        until = time.monotonic()+LIMITS['close_seconds']
        if self.ws is not None:
            self.ws.close(); self.ws = None
        if self.storage.root is not None: (self.storage.root/'stop').touch()
        if self.owned is not None:
            # Terminate the owned Job rather than wait on a remote CDP close.
            # EOF, leader exit and Job emptiness remain independent evidence.
            self.owned.terminate()
            self.owned.close()
            if not self.owned.closed: raise BrowserFailure('Browser closure remains unknown.')
        if time.monotonic() > until: raise TimeoutError('Browser closure exceeded its declaration.')
        self.closed = True
        _retained.pop(id(self),None)
        if self.owned is not None and self.owned.resource_failure():
            raise BrowserLimit('Browser resource exhaustion retained at closure.')


def bootstrap(root, *, renderer_processes=None):
    """Native GO-gated bootstrap; stdout stays the existing small JSON protocol."""
    if input() != 'GO': raise BrowserFailure('Browser bootstrap handshake rejected.')
    if os.name != 'nt': raise BrowserFailure('Native browser requires Windows.')
    root = Path(root).resolve()
    command = [str(EXECUTABLE), '--headless', '--no-first-run', '--no-default-browser-check',
        '--disable-background-networking', '--disable-component-update', '--disable-sync',
        '--disable-crash-reporter', '--disable-extensions', '--disable-default-apps',
        '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
        '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
        '--user-data-dir='+str(root/'profile'), '--disk-cache-dir='+str(root/'cache'),
        '--disk-cache-size=33554432', 'about:blank']
    if renderer_processes is not None:
        if type(renderer_processes) is not int or not 1<=renderer_processes<=8:
            raise BrowserFailure('Invalid private renderer process count.')
        command.insert(-1,'--renderer-process-limit='+str(renderer_processes))
    browser = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    exhausted = threading.Event()
    output_lock = threading.Lock()
    output_bytes = 0
    def count(size):
        nonlocal output_bytes
        with output_lock:
            output_bytes += size
            if output_bytes > LIMITS['bootstrap_output_bytes']: exhausted.set()
    def emit(value):
        line = json.dumps(value)
        count(len((line+'\n').encode('utf-8')))
        print(line,flush=True)
    emit(dict(event='browser_started',pid=browser.pid))
    def drain():
        while True:
            part = browser.stdout.read(4096)
            if not part: break
            count(len(part))
    reader = threading.Thread(target=drain,daemon=True); reader.start()
    until = time.monotonic()+LIMITS['session_seconds']-LIMITS['close_seconds']
    while browser.poll() is None:
        if exhausted.is_set() or time.monotonic()>until:
            emit(dict(event='failed',reason='limit'))
            break
        if (root/'stop').exists(): break
        time.sleep(.05)
    # The parent closes the entire existing Job, including this bootstrap.
    emit(dict(event='browser_stopped',exit=browser.poll()))
