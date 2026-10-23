"""Persistent, bounded development logs with safe exception traces."""
import errno
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'website')]
import diagnostics as d
import serve
namespace_implementation=d._process_namespace


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.namespace='a'*32
        namespace_patch=patch.object(d,'_process_namespace',return_value=self.namespace)
        namespace_patch.start();self.addCleanup(namespace_patch.stop)
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.addCleanup(d.close)
        self.path=d.configure(Path(self.folder.name))

    def test_file_preserves_error_chains_codes_and_frames_without_secrets(self):
        private='PRIVATE-CREDENTIAL-CANARY'
        url='https://provider.invalid/prices?apikey='+private
        try:
            try:raise OSError(errno.EACCES,private,url)
            except OSError as cause:
                cause.winerror=5
                raise RuntimeError(url) from cause
        except RuntimeError as error:
            d.failure('download.publish_failed',error,asset='px/ACR.json',start='2005-01-01',end='2014-12-31')
        content=self.path.read_text()
        self.assertIn('download.publish_failed',content)
        self.assertIn('px/ACR.json',content)
        self.assertIn('test_diagnostics.py',content)
        self.assertIn('"type": "RuntimeError"',content)
        self.assertIn('"type": "PermissionError"',content)
        self.assertIn('"winerror": 5',content)
        self.assertNotIn(private,content);self.assertNotIn('https:',content)
        self.assertNotIn('raise RuntimeError',content)

    def test_logs_rotate_and_do_not_grow_without_a_bound(self):
        with patch.object(d,'MAX_BYTES',350):
            d.configure(Path(self.folder.name))
        for count in range(30):d.event('download.saved',asset='px/ACR.json',count=count)
        files=list(Path(self.folder.name).glob('*.log*'))
        self.assertEqual(len(files),3)
        self.assertIn('"count": 29',self.path.read_text())

    def test_unavailable_log_directory_does_not_raise(self):
        file=Path(self.folder.name)/'file';file.write_text('occupied')
        self.assertIsNone(d.configure(file))
        d.event('server.starting',port=3000)
        self.assertIsNone(d.log_path())

    def saved_log(self,name,age=0,size=10):
        if name.startswith('website-'):name=name.replace('website-',f'website-{self.namespace}-',1)
        path=Path(self.folder.name)/name
        path.write_bytes(b'x'*size)
        stamp=time.time()-age*86400
        os.utime(path,(stamp,stamp))
        return path

    def test_cleanup_removes_expired_logs_and_backups_only(self):
        old=self.saved_log('website-123456.log',15)
        backup=self.saved_log('website-123456.log.2',15)
        recent=self.saved_log('website-123457.log',1)
        unrelated=self.saved_log('other.log',30)
        with patch.object(d,'_process_running',return_value=False):d.cleanup(self.folder.name)
        self.assertFalse(old.exists());self.assertFalse(backup.exists())
        self.assertTrue(recent.exists());self.assertTrue(unrelated.exists())

    def test_cleanup_size_target_removes_oldest_and_preserves_running_logs(self):
        active=self.saved_log('website-123450.log',30,20)
        oldest=self.saved_log('website-123451.log',3,20)
        newest=self.saved_log('website-123452.log',1,20)
        with patch.object(d,'TOTAL_BYTES',40),patch.object(d,'_process_running',side_effect=lambda pid:pid==123450):
            d.cleanup(self.folder.name)
        self.assertTrue(active.exists());self.assertFalse(oldest.exists());self.assertTrue(newest.exists())

    def test_cleanup_locked_file_does_not_block_other_cleanup_or_startup(self):
        locked=self.saved_log('website-123456.log',30)
        other=self.saved_log('website-123457.log',30)
        unlink=Path.unlink
        def remove(path,*args,**kwargs):
            if path==locked:raise PermissionError('locked')
            return unlink(path,*args,**kwargs)
        with patch.object(d,'_process_running',return_value=False),patch.object(Path,'unlink',remove):
            self.assertIsNotNone(d.configure(self.folder.name))
        self.assertTrue(locked.exists());self.assertFalse(other.exists())

    def test_foreign_and_legacy_logs_are_preserved_without_pid_checks(self):
        for name in ('website-123456.log','website-'+('b'*32)+'-123456.log.1'):
            path=Path(self.folder.name)/name
            path.write_bytes(b'old')
            os.utime(path,(0,0))
        with patch.object(d,'TOTAL_BYTES',0),patch.object(d,'_process_running') as running:
            d.cleanup(self.folder.name)
            self.assertTrue(all(call.args==(os.getpid(),) for call in running.call_args_list))
        self.assertEqual(len(list(Path(self.folder.name).glob('*.log*'))),3)

    def test_unknown_namespace_preserves_all_logs(self):
        old=self.saved_log('website-123456.log',30)
        with patch.object(d,'_process_namespace',return_value=None),patch.object(d,'_process_running') as running:
            d.cleanup(self.folder.name)
            running.assert_not_called()
        self.assertTrue(old.exists())

    def test_native_namespace_is_stable(self):
        # Exercise the real OS implementation despite the retention fixture.
        with patch.object(d,'_process_namespace',namespace_implementation):
            first=d._process_namespace()
            self.assertEqual(first,d._process_namespace())
            if os.name=='nt' or sys.platform.startswith('linux'):
                self.assertRegex(first,r'^[0-9a-f]{32}$')

    def test_live_and_exited_child_process(self):
        child=subprocess.Popen([sys.executable,'-c','import sys; sys.stdin.read()'],stdin=subprocess.PIPE)
        try:
            self.assertTrue(d._process_running(child.pid))
            child.communicate(timeout=10)
            self.assertFalse(d._process_running(child.pid))
        finally:
            if child.poll() is None:
                child.kill();child.communicate(timeout=10)

    @unittest.skipUnless(os.name=='nt','Windows process API')
    def test_windows_inaccessible_and_uncertain_process_is_protected(self):
        import ctypes
        from unittest.mock import MagicMock
        kernel=MagicMock()
        with patch.object(ctypes,'WinDLL',return_value=kernel),patch.object(ctypes,'get_last_error',return_value=5):
            kernel.OpenProcess.return_value=0
            self.assertTrue(d._process_running(123456))
            kernel.OpenProcess.return_value=42
            kernel.WaitForSingleObject.return_value=0xffffffff
            self.assertTrue(d._process_running(123456))
            kernel.CloseHandle.assert_called_once_with(42)

    def test_current_process_is_protected_and_unknown_state_is_conservative(self):
        self.assertTrue(d._process_running(os.getpid()))
        if os.name!='nt':
            with patch.object(d.os,'kill',side_effect=PermissionError):self.assertTrue(d._process_running(123456))
            with patch.object(d.os,'kill',side_effect=ProcessLookupError):self.assertFalse(d._process_running(123456))

    def test_http_failure_supports_python310_without_sys_exception(self):
        server=object.__new__(serve.Server)
        legacy_sys=SimpleNamespace(exc_info=sys.exc_info,stderr=io.StringIO())
        with patch.object(serve,'sys',legacy_sys):
            self.assertFalse(hasattr(serve.sys,'exception'))
            try:raise RuntimeError('PRIVATE-REQUEST-CANARY')
            except RuntimeError:server.handle_error(None,None)
        content=self.path.read_text()
        self.assertIn('http.failed',content)
        self.assertNotIn('PRIVATE-REQUEST-CANARY',content)


if __name__=='__main__':unittest.main()
