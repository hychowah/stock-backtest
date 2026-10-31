"""Bounded protocol and owner failures plus an explicitly private native smoke."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import sys
import threading
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import quote

sys.path.insert(0,str(Path(__file__).resolve().parent))
from bench_native_browser import (BrowserFailure, BrowserLimit, BrowserStorage,
    LIMITS, NativeBrowser, ROOT, _WebSocket, _retained)


class ProtocolTests(unittest.TestCase):
    def connection(self, data):
        left,right = socket.socketpair()
        self.addCleanup(left.close); self.addCleanup(right.close)
        ws = _WebSocket.__new__(_WebSocket)
        ws.socket, ws.received, ws.checkpoint = left,0,lambda:None
        right.sendall(data)
        return ws,right

    def test_fragmented_message_with_ping_gets_masked_pong(self):
        ws,peer = self.connection(b'\x01\x06{"id":'+b'\x89\x01x'+b'\x80\x021}')
        self.assertEqual(ws.receive(time.monotonic()+2),dict(id=1))
        peer.settimeout(2)
        reply = peer.recv(128)
        self.assertEqual(reply[:2],b'\x8a\x81')
        self.assertEqual(bytes(v^reply[2+i%4] for i,v in enumerate(reply[6:])),b'x')

    def test_reject_malformed_and_oversized_frames_before_body(self):
        frames = [b'\xc1\x00', b'\x81\x80', b'\x82\x00', b'\x80\x00',
            b'\x09\x00', b'\x88\x01x', b'\x81\x7e\x00\x01',
            b'\x81\x7f'+struct.pack('!Q',2**63)]
        for frame in frames:
            with self.subTest(frame=frame):
                ws,_ = self.connection(frame)
                with self.assertRaises(BrowserFailure): ws.receive(time.monotonic()+2)
        ws,_ = self.connection(b'\x81\x7f'+struct.pack('!Q',LIMITS['cdp_message_bytes']+1))
        with self.assertRaises(BrowserLimit): ws.receive(time.monotonic()+2)

    def test_fragment_bound_and_invalid_json_or_encoding(self):
        for data in (b'\x81\x01[', b'\x81\x01\xff', b'\x81\x02[]', b'\x01\x01{\x81\x01}'):
            ws,_ = self.connection(data)
            with self.assertRaises(BrowserFailure): ws.receive(time.monotonic()+2)
        ws,_ = self.connection(b'\x01\x02{}\x80\x04null')
        with patch.dict(LIMITS,cdp_message_bytes=5):
            with self.assertRaises(BrowserLimit): ws.receive(time.monotonic()+2)

    def test_received_bound_and_deadline(self):
        ws,_ = self.connection(b'\x81\x02{}')
        with patch.dict(LIMITS,received_bytes=3):
            with self.assertRaises(BrowserLimit): ws.receive(time.monotonic()+2)
        ws,_ = self.connection(b'')
        with self.assertRaises(TimeoutError): ws.receive(time.monotonic()+.03)

    def test_upgrade_validates_exact_accept_and_rejects_extensions(self):
        for invalid in ('accept','extension',None):
            with self.subTest(invalid=invalid):
                listener = socket.socket(); listener.bind(('127.0.0.1',0)); listener.listen(1)
                def server():
                    with listener:
                        peer,_ = listener.accept()
                        with peer:
                            data = b''
                            while not data.endswith(b'\r\n\r\n'): data += peer.recv(1)
                            key = data.split(b'Sec-WebSocket-Key: ')[1].split(b'\r\n')[0]
                            accept = base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                            if invalid == 'accept': accept = b'wrong'
                            header = b'HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Accept: '+accept+b'\r\n'
                            if invalid == 'extension': header += b'Sec-WebSocket-Extensions: permessage-deflate\r\n'
                            peer.sendall(header+b'\r\n')
                thread = threading.Thread(target=server); thread.start()
                try:
                    if invalid:
                        with self.assertRaises(BrowserFailure): _WebSocket(listener.getsockname()[1],'/owned',time.monotonic()+2,lambda:None)
                    else:
                        ws = _WebSocket(listener.getsockname()[1],'/owned',time.monotonic()+2,lambda:None)
                        ws.close()
                finally: thread.join(2)
                self.assertFalse(thread.is_alive())


class OwnershipTests(unittest.TestCase):
    def storage(self):
        storage = BrowserStorage().start()
        self.addCleanup(storage.close)
        return storage

    def test_unknown_closure_retains_storage_and_strong_owner_for_retry(self):
        storage = self.storage(); browser = NativeBrowser(storage)
        class Pending:
            closed = False
            def terminate(self): raise TimeoutError('injected')
        browser.owned = Pending()
        _retained[id(browser)] = browser
        with self.assertRaises(TimeoutError): browser.close()
        with self.assertRaises(BrowserFailure): storage.close()
        self.assertTrue(storage.root.exists())
        self.assertIs(_retained[id(browser)],browser)
        browser.owned = None; browser.close(); storage.close()
        self.assertNotIn(id(browser),_retained)
        self.assertFalse(storage.root.exists())

    def test_root_lives_until_browser_then_service_closes(self):
        storage = self.storage()
        class Service: closed=False
        service = Service(); browser = NativeBrowser(storage,service)
        browser.close()
        with self.assertRaises(BrowserFailure): storage.close()
        service.closed=True; storage.close()

    def test_inventory_handles_download_rename_but_keeps_other_errors(self):
        storage=self.storage();path=storage.root/'downloads'/'inflight.crdownload';path.write_bytes(b'partial')
        original_scan=os.scandir;opened=[];closed=[]
        class Entry:
            def __init__(self,entry,action):self.entry,self.action=entry,action
            def __getattr__(self,key):return getattr(self.entry,key)
            def stat(self,**kwargs):
                if Path(self.entry.path)==path:self.action()
                return self.entry.stat(**kwargs)
        @contextmanager
        def scan(directory,action):
            opened.append(str(directory))
            try:
                with original_scan(directory) as entries:
                    yield (Entry(entry,action) for entry in entries)
            finally:closed.append(str(directory))
        def renamed():
            path.unlink()
            raise FileNotFoundError('Renamed before metadata acquisition')
        with patch('bench_native_browser.os.scandir',side_effect=lambda directory:scan(directory,renamed)):
            self.assertEqual(storage.inventory()['downloads'],0)
        self.assertFalse(path.exists());self.assertTrue(closed);self.assertCountEqual(opened,closed);path.write_bytes(b'partial')
        def inaccessible():raise PermissionError('Unexpected access failure')
        with patch('bench_native_browser.os.scandir',side_effect=lambda directory:scan(directory,inaccessible)):
            before=len(closed)
            with self.assertRaises(PermissionError):storage.inventory()
            self.assertGreater(len(closed),before)
            self.assertCountEqual(opened,closed)

    def test_inventory_rejects_link_before_classification_on_every_platform(self):
        storage=self.storage();original=os.scandir
        class Link:
            def is_symlink(self):return True
            def is_dir(self,**kwargs):raise AssertionError('Link was followed')
        @contextmanager
        def scan(directory):
            with original(directory):yield iter([Link()])
        with patch('bench_native_browser.os.scandir',side_effect=scan):
            with self.assertRaises(BrowserFailure):storage.inventory()

    def test_inventory_counts_nested_and_unknown_files_and_each_exact_ceiling(self):
        storage=self.storage()
        sizes={'profile/sub/a':3,'cache/b':5,'downloads/sub/c':7,'evidence/sub/d':11,
               'temp/e':13,'unknown/downloads/f':17,'root-file':19,'empty-file':0}
        for name,size in sizes.items():
            path=storage.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x'*size)
        (storage.root/'empty-directory').mkdir()
        expected=dict(root=75,profile_cache=8,downloads=7,evidence=11)
        self.assertEqual(storage.inventory(),expected)
        for category,total in expected.items():
            with self.subTest(category=category),patch.dict(LIMITS,{category+'_bytes':total}):
                self.assertEqual(storage.inventory(),expected)
                with patch.dict(LIMITS,{category+'_bytes':total-1}):
                    with self.assertRaisesRegex(BrowserLimit,category):storage.inventory()

    def test_inventory_rejects_file_directory_broken_and_loop_links(self):
        storage=self.storage();target=storage.root/'temp/target';target.mkdir()
        (target/'value').write_bytes(b'owned')
        for name,destination,directory in (('file',target/'value',False),('directory',target,True),
                                            ('broken',target/'missing',False),('loop',storage.root,True)):
            with self.subTest(link=name):
                link=storage.root/'temp'/('link-'+name)
                try:
                    try:link.symlink_to(destination,target_is_directory=directory)
                    except OSError as error:self.skipTest('Native link creation unavailable: '+type(error).__name__)
                    with self.assertRaises(BrowserFailure):storage.inventory()
                finally:link.unlink(missing_ok=True)

    def test_attachment_category_preserves_platform_path_case_rules(self):
        storage=self.storage()
        for name in ('downloads','evidence'):
            directory=storage.root/name;upper=storage.root/name.upper()
            if os.name=='nt':directory.rename(upper)
            else:upper.mkdir()
            try:
                (upper/'value').write_bytes(b'owned')
                self.assertEqual(storage.inventory()[name],5 if os.name=='nt' else 0)
            finally:
                (upper/'value').unlink()
                if os.name=='nt':upper.rename(directory)
                else:upper.rmdir()

    def test_inventory_tolerates_disappearing_directory_but_not_other_scan_errors(self):
        storage=self.storage();folder=storage.root/'downloads/disappearing';folder.mkdir()
        original=os.scandir
        def disappearing(directory):
            if Path(directory)==folder:folder.rmdir()
            return original(directory)
        with patch('bench_native_browser.os.scandir',side_effect=disappearing):
            self.assertEqual(storage.inventory()['downloads'],0)
        for error in (PermissionError('denied'),OSError('unexpected')):
            with patch('bench_native_browser.os.scandir',side_effect=error):
                with self.assertRaises(type(error)):storage.inventory()

    def test_checkpoint_retains_quarter_second_inventory_cadence(self):
        storage=self.storage();browser=NativeBrowser(storage);self.addCleanup(browser.close)
        browser.started=0;browser.last_inventory=0
        with patch('bench_native_browser.time.monotonic',return_value=.249),patch.object(storage,'inventory') as inventory:
            browser.checkpoint();inventory.assert_not_called()
        with patch('bench_native_browser.time.monotonic',return_value=.25),patch.object(storage,'inventory') as inventory:
            browser.checkpoint();inventory.assert_called_once_with()
        self.assertEqual(browser.last_inventory,.25)

    def test_pending_events_and_storage_have_separate_frozen_bounds(self):
        storage = self.storage(); browser = NativeBrowser(storage)
        self.addCleanup(browser.close)
        with patch.dict(LIMITS,pending_events=1):
            browser._event(dict(method='Browser.downloadWillBegin',params=dict(guid='a')))
            with self.assertRaises(BrowserLimit): browser._event(dict(method='Browser.downloadWillBegin',params=dict(guid='b')))
        with patch.dict(LIMITS,downloads_bytes=2):
            (storage.root/'downloads/x').write_bytes(b'abc')
            with self.assertRaises(BrowserLimit): storage.inventory()

    def test_canceled_download_cannot_supply_file_evidence(self):
        storage = self.storage(); browser = NativeBrowser(storage)
        self.addCleanup(browser.close)
        with patch.object(browser,'deadline',return_value=time.monotonic()+2), patch.object(browser,'click'), patch.object(browser,'event',side_effect=[dict(guid='a'),dict(guid='a',state='canceled')]):
            with self.assertRaises(BrowserFailure): browser.download('#download')

    def test_nested_operations_share_one_deadline(self):
        storage = self.storage(); browser = NativeBrowser(storage)
        self.addCleanup(browser.close)
        browser.started = time.monotonic()
        browser.operation_deadline = time.monotonic()+.01
        with patch.object(browser,'evaluate',return_value=False):
            with self.assertRaises(TimeoutError): browser.wait('false')

    def test_initialization_failure_adopts_unclosed_process_and_preserves_error(self):
        storage = self.storage(); browser = NativeBrowser(storage)
        self.addCleanup(browser.close)
        class Pending:
            closed = False
            def terminate(self): raise TimeoutError('injected close')
        pending = Pending()
        original = OSError('injected creation')
        original.owned_process = pending
        with patch('bench_native_browser.os.name','nt'),patch.object(Path,'is_file',return_value=True),patch('bench_native_browser.OwnedProcess',side_effect=original):
            with self.assertRaises(OSError) as caught: browser.start()
        self.assertIs(caught.exception,original)
        self.assertIs(original.native_browser,browser)
        self.assertIs(browser.owned,pending)
        self.assertIs(_retained[id(browser)],browser)
        with self.assertRaises(BrowserFailure): storage.close()
        browser.owned = None

    def test_final_resource_failure_rejects_success_after_confirmed_closure(self):
        storage = self.storage(); browser = NativeBrowser(storage)
        self.addCleanup(browser.close)
        class Exhausted:
            closed = True
            def terminate(self): pass
            def close(self): pass
            def resource_failure(self): return 'limit'
        browser.owned = Exhausted()
        with self.assertRaises(BrowserLimit): browser.close()
        self.assertTrue(browser.closed)
        storage.close()

    def test_declaration_is_unchanged_and_preservation_requires_closure(self):
        record = json.loads((ROOT/'docs/plans/compiled-backtest/phases/CB-02/execution/native-browser-capability.json').read_bytes())
        self.assertEqual(LIMITS,record['declaration']['limits'])
        storage = self.storage(); browser = NativeBrowser(storage)
        self.addCleanup(browser.close)
        (storage.root/'downloads/test.csv').write_bytes(b'symbol\nZZ000\n')
        (storage.root/'profile/private').write_bytes(b'profile must not be copied')
        with self.assertRaises(BrowserFailure): storage.preserve()
        browser.close()
        artifact = storage.preserve()
        self.addCleanup(shutil.rmtree,artifact['root'])
        self.assertEqual(set(artifact['files']),{'downloads/test.csv'})
        self.assertEqual((Path(artifact['root'])/'downloads/test.csv').read_bytes(),b'symbol\nZZ000\n')


@unittest.skipUnless(os.name=='nt','Native browser requires Windows.')
class NativeSmokeTests(unittest.TestCase):
    def test_post_containment_attach_failure_closes_browser_before_storage(self):
        storage = BrowserStorage(); browser = NativeBrowser(storage)
        try:
            original = BrowserFailure('injected debugger attach')
            with patch('bench_native_browser._WebSocket',side_effect=original):
                with self.assertRaises(BrowserFailure) as caught: browser.start()
            self.assertIs(caught.exception,original)
            self.assertTrue(browser.closed)
            self.assertTrue(browser.owned.closure()['descendants_empty'])
            print(json.dumps(dict(check='native-browser-attach-failure',closure=browser.owned.closure())),flush=True)
        finally:
            browser.close(); storage.close()

    def test_active_download_closure_keeps_storage_until_service_closes(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        released = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                if self.path=='/':
                    data=b'<!doctype html><a id="download" href="/slow">Download</a>'
                    self.send_response(200); self.send_header('Content-Length',str(len(data)))
                    self.end_headers(); self.wfile.write(data)
                elif self.path=='/slow':
                    self.send_response(200)
                    self.send_header('Content-Type','text/csv')
                    self.send_header('Content-Disposition','attachment; filename="active.csv"')
                    self.send_header('Content-Length','4096'); self.end_headers()
                    self.wfile.write(b'symbol\nZZ000\n'); self.wfile.flush()
                    released.wait(30)
                else:
                    self.send_error(404)
        class Service:
            ready=False
            closed=False
            def __init__(self):
                self.server=self.listener=None
            def start(self):
                self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
                self.port=self.server.server_address[1]
                self.listener=threading.Thread(target=self.server.serve_forever,kwargs=dict(poll_interval=.02))
                self.listener.start()
                self.ready=True
            def close(self):
                if self.closed:return
                released.set()
                if self.listener is not None and self.listener.is_alive():self.server.shutdown()
                if self.server is not None:self.server.server_close()
                if self.listener is not None and self.listener.ident is not None:self.listener.join(2)
                if self.listener is not None and self.listener.is_alive():raise TimeoutError('Smoke listener closure unknown.')
                self.closed=True
        storage=BrowserStorage().start()
        service=Service()
        browser=NativeBrowser(storage,service)
        try:
            service.start()
            browser.start()
            browser.navigate('http://127.0.0.1:'+str(service.port)+'/')
            browser.click('#download')
            begin=browser.event('Browser.downloadWillBegin')
            progress=browser.event('Browser.downloadProgress',lambda p:p['guid']==begin['guid'])
            self.assertEqual(progress['state'],'inProgress')
            browser.close()
            self.assertTrue(browser.owned.closure()['descendants_empty'])
            with self.assertRaises(BrowserFailure):storage.close()
            self.assertTrue(storage.root.exists())
            print(json.dumps(dict(check='native-browser-active-download-close',
                completed=False,storage_retained_until_service_close=True,closure=browser.owned.closure())),flush=True)
        finally:
            browser.close();service.close();storage.close()

    def test_private_rendered_control_real_blob_job_and_confirmed_closure(self):
        storage = BrowserStorage()
        browser = NativeBrowser(storage)
        failed = False
        try:
            browser.start()
            print(json.dumps(dict(check='native-browser-started',root=str(storage.root),identity=browser.identity)),flush=True)
            browser.viewport(800,600)
            html = '''<!doctype html><meta charset="utf-8"><button id="test" onclick="this.textContent='clicked'">ready</button>
                <button id="download" onclick="const a=document.createElement('a');a.href=window.URL.createObjectURL(new Blob(['symbol,value\\nZZ000,1\\n'],{type:'text/csv'}));a.download='smoke.csv';a.click()">Download</button>'''
            browser.command('Page.navigate',dict(url='data:text/html,'+quote(html)),page=True)
            browser.wait('document.querySelector("#test") !== null')
            browser.click('#test')
            browser.wait('document.querySelector("#test").textContent === "clicked"')
            browser.screenshot('before-download')
            receipt,data = browser.download('#download')
            self.assertEqual(data,b'symbol,value\nZZ000,1\n')
            self.assertEqual(receipt['name'],'smoke.csv')
            processes = browser.command('SystemInfo.getProcessInfo')['processInfo']
            self.assertTrue(any(p['type']=='renderer' for p in processes))
            self.assertTrue(all(browser._member(p['id']) for p in processes))
            browser.screenshot('smoke')
            self.assertEqual(browser.errors,[])
            print(json.dumps(dict(check='native-browser-smoke',identity=browser.identity,
                rendered_control=True,download=receipt,all_browser_processes_in_job=True,
                inventory=storage.inventory(),limits=LIMITS)),flush=True)
        except BaseException:
            failed = True
            print(json.dumps(dict(check='native-browser-smoke-failed',root=str(storage.root),
                errors=browser.errors,events=[v for v,n in browser.events])),flush=True)
            raise
        finally:
            try:
                browser.close()
                print(json.dumps(dict(check='native-browser-closure',closure=browser.owned.closure() if browser.owned else None)),flush=True)
                if not failed: print(json.dumps(dict(check='native-browser-artifacts',**storage.preserve())),flush=True)
                if browser.closed: storage.close()
            except BaseException:
                if not failed: raise
                import traceback
                traceback.print_exc()
        self.assertTrue(browser.owned.closed)


if __name__=='__main__': unittest.main()
