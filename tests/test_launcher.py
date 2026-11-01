"""Ownership lasts through request cleanup, including failed HTTP probes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import Mock, patch
from urllib.request import build_opener, ProxyHandler
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from website.server import launcher
class LauncherTests(unittest.TestCase):
    def test_transfer_stops_current_server_and_cleans_identity(self):
        old=dict(port=3000,token='old',lifetime_lock=True)
        server=Mock();server.server_address=('0.0.0.0',3000)
        with tempfile.TemporaryDirectory() as tmp,patch.object(launcher,'ROOT',Path(tmp)),patch.object(launcher,'active',return_value=old),patch.object(launcher,'request') as request:
            with launcher.Lifecycle(3000,'0.0.0.0') as lifecycle:
                lifecycle.attach(server)
                self.assertTrue(launcher.state_path(3000).exists())
                self.assertFalse(server.daemon_threads)
            request.assert_called_once_with(old,'/api/launcher','POST')
            server.server_close.assert_called_once()
            self.assertFalse(launcher.state_path(3000).exists())

    def test_listener_stopping_does_not_release_busy_request_ownership(self):
        entered=Event();release=Event();closing=Event();client_done=Event()
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                entered.set();release.wait(5)
                self.send_response(200);self.end_headers()
            def log_message(self,*args):pass
        class Server(ThreadingHTTPServer):
            def server_close(self):
                closing.set();super().server_close()
        with tempfile.TemporaryDirectory() as tmp,patch.object(launcher,'ROOT',Path(tmp)),patch.object(launcher,'active',return_value=None):
            lifecycle=launcher.Lifecycle(3000,'127.0.0.1');lifecycle.__enter__()
            server=Server(('127.0.0.1',0),Handler);lifecycle.attach(server)
            serving=Thread(target=server.serve_forever);serving.start()
            def fetch():
                try:
                    with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{server.server_address[1]}',timeout=5) as response:response.read()
                finally:client_done.set()
            client=Thread(target=fetch);client.start()
            cleanup=None
            try:
                self.assertTrue(entered.wait(3))
                server.shutdown();serving.join(3)
                cleanup=Thread(target=lambda:lifecycle.__exit__(None,None,None));cleanup.start()
                self.assertTrue(closing.wait(3))
                # HTTP is unavailable, but an old calculation still owns the cache.
                with self.assertRaisesRegex(RuntimeError,'still owns'):
                    with launcher.Lifecycle(3000,'127.0.0.1',timeout=.05):pass
                self.assertTrue(cleanup.is_alive())
            finally:
                release.set();client.join(5)
                if cleanup:cleanup.join(5)
                else:lifecycle.__exit__(None,None,None)
                server.shutdown();serving.join(3)
            self.assertTrue(client_done.is_set())
            with launcher.Lifecycle(3000,'127.0.0.1',timeout=.05):pass

    def test_failed_publication_closes_server_and_releases_locks(self):
        server=Mock();server.server_address=('127.0.0.1',3000)
        with tempfile.TemporaryDirectory() as tmp,patch.object(launcher,'ROOT',Path(tmp)),patch.object(launcher,'active',return_value=None):
            with self.assertRaises(OSError):
                with launcher.Lifecycle(3000,'127.0.0.1') as lifecycle:
                    with patch.object(Path,'replace',side_effect=OSError('publication failed')):lifecycle.attach(server)
            server.server_close.assert_called_once()
            with launcher.Lifecycle(3000,'127.0.0.1',timeout=.05):pass

    def test_rejects_identity_from_another_project(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(launcher,'ROOT',Path(tmp)),patch.object(launcher,'request',return_value=dict(token='token',project='another project')):
            (Path(tmp)/'data').mkdir()
            launcher.state_path(3000).write_text('{"port":3000,"token":"token"}')
            self.assertIsNone(launcher.active(3000))

    def test_legacy_transfer_waits_for_process_exit(self):
        old=dict(port=3000,token='old',pid=123)
        with tempfile.TemporaryDirectory() as tmp,patch.object(launcher,'ROOT',Path(tmp)),patch.object(launcher,'active',return_value=old),patch.object(launcher,'request'),patch.object(launcher,'wait_legacy_process') as wait:
            with launcher.Lifecycle(3000,'0.0.0.0'):pass
            wait.assert_called_once_with(123,30)


if __name__=='__main__':unittest.main()
