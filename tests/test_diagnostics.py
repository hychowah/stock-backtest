"""Persistent, bounded development logs with safe exception traces."""
import errno
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'website')]
import diagnostics as d
import serve


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
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
