"""One launcher resolves dependencies and opens the browser without manual steps."""
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys
import errno
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'website')]
import serve
import build_state
import research


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.context.enter_context(patch.object(serve.cache_access,'access',side_effect=lambda:nullcontext()))
        self.context.enter_context(patch.object(serve.data_manager,'source_problem',return_value=False))

    def test_prepare_then_build_when_stale(self):
        calls=[]
        with patch.object(serve.schedules,'prepare',side_effect=lambda:calls.append('prepare')),patch.object(serve,'current_build',side_effect=lambda:calls.append('check_build') or False),patch.object(serve.subprocess,'run',side_effect=lambda *args,**kwargs:calls.append('build')) as run:
            serve.ensure_ready()
        self.assertEqual(calls,['prepare','check_build','build'])
        self.assertEqual(run.call_args.args[0],[sys.executable,'-X','utf8',str(serve.ROOT/'build.py')])
        self.assertTrue(run.call_args.kwargs['check'])

    def test_unchanged_caches_do_not_rebuild_page(self):
        with patch.object(serve.schedules,'prepare'),patch.object(serve,'current_build',return_value=True),patch.object(serve.subprocess,'run') as run:
            serve.ensure_ready()
        run.assert_not_called()

    def test_main_opens_browser_after_successful_bind(self):
        calls=[];server=Mock();server.server_address=('127.0.0.1',8765)
        server.serve_forever.side_effect=lambda:calls.append('serve')
        with patch.object(sys,'argv',['serve.py']),patch.object(serve,'ensure_ready',side_effect=lambda:calls.append('prepare')),patch.object(serve,'ThreadingHTTPServer',side_effect=lambda *args:calls.append('bind') or server),patch.object(serve.webbrowser,'open',side_effect=lambda url:calls.append('browser')):
            serve.main()
        self.assertEqual(calls,['prepare','bind','browser','serve'])
        server.server_close.assert_called_once()

    def test_missing_sources_open_recovery_panel_without_preparation(self):
        server=Mock();server.server_address=('127.0.0.1',3000)
        with patch.object(sys,'argv',['serve.py','--no-browser']),patch.object(serve.data_manager,'source_problem',return_value=True),patch.object(serve,'ensure_ready') as prepare,patch.object(serve,'ThreadingHTTPServer',return_value=server):
            serve.main()
        prepare.assert_not_called();self.assertTrue(server.data_recovery)
        server.serve_forever.assert_called_once()

    def test_ctrl_c_closes_terminal_owned_server(self):
        server=Mock();server.server_address=('0.0.0.0',3000)
        server.serve_forever.side_effect=KeyboardInterrupt
        with patch.object(sys,'argv',['serve.py','--no-browser']),patch.object(serve,'ensure_ready'),patch.object(serve,'ThreadingHTTPServer',return_value=server):
            serve.main()
        server.server_close.assert_called_once()

    def test_failure_never_opens_browser(self):
        with patch.object(sys,'argv',['serve.py']),patch.object(serve,'ensure_ready',side_effect=ValueError('bad cache')),patch.object(serve,'ThreadingHTTPServer') as server,patch.object(serve.webbrowser,'open') as browser:
            with self.assertRaises(SystemExit):serve.main()
        server.assert_not_called();browser.assert_not_called()

    def test_bind_failure_does_not_open_browser(self):
        with patch.object(sys,'argv',['serve.py']),patch.object(serve,'ensure_ready'),patch.object(serve,'ThreadingHTTPServer',side_effect=OSError('port unavailable')),patch.object(serve.webbrowser,'open') as browser:
            with self.assertRaises(SystemExit):serve.main()
        browser.assert_not_called()

    def test_no_browser_flag(self):
        server=Mock();server.server_address=('127.0.0.1',8765)
        with patch.object(sys,'argv',['serve.py','--no-browser']),patch.object(serve,'ensure_ready'),patch.object(serve,'ThreadingHTTPServer',return_value=server),patch.object(serve.webbrowser,'open') as browser:
            serve.main()
        browser.assert_not_called();server.serve_forever.assert_called_once()

    def test_occupied_port_opens_new_instance_instead_of_stale_server(self):
        server=Mock();server.server_address=('127.0.0.1',49123)
        with patch.object(sys,'argv',['serve.py']),patch.object(serve,'ensure_ready'),patch.object(serve,'ThreadingHTTPServer',side_effect=[OSError(errno.EADDRINUSE,'in use'),server]) as bind,patch.object(serve.webbrowser,'open') as browser:
            serve.main()
        self.assertEqual(bind.call_args_list[1].args[0],('0.0.0.0',0))
        browser.assert_called_once_with('http://127.0.0.1:49123')
        server.server_close.assert_called_once()


class BuildStateTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.website=root/'website';(self.website/'dist').mkdir(parents=True)
        (root/'data').mkdir();(root/'data'/'research.sqlite').write_bytes(b'database')
        self.source=self.website/'range.js';self.source.write_bytes(b'const n=1;\r\n')
        for name in ('index.html','returns.csv','holdings.csv','valuations.json','latest-picks.csv','data.html'):
            (self.website/'dist'/name).write_text('output')
        self.context.enter_context(patch.object(build_state,'ROOT',self.website))
        self.context.enter_context(patch.object(build_state,'STAMP',self.website/'dist'/'.build-state.json'))

    def test_source_changes_invalidate_but_newlines_do_not(self):
        self.assertFalse(build_state.current_build())
        build_state.record_build();self.assertTrue(build_state.current_build())
        self.source.write_bytes(b'const n=1;\n');self.assertTrue(build_state.current_build())
        self.source.write_text('const n=2;');self.assertFalse(build_state.current_build())

    def test_missing_artifacts_and_malformed_stamp(self):
        build_state.record_build();(self.website/'dist'/'holdings.csv').unlink()
        self.assertFalse(build_state.current_build())
        (self.website/'dist'/'holdings.csv').write_text('output')
        build_state.STAMP.write_text('bad JSON');self.assertFalse(build_state.current_build())


class PortableFingerprintTests(unittest.TestCase):
    def test_directory_size_is_not_a_cache_dependency(self):
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as context:
            root=Path(tmp);raw=root/'raw';raw.mkdir();(raw/'px').mkdir()
            results=root/'results';results.mkdir()
            for name in ('universe.json','metrics.jsonl','spy-div.json','treasury.json'):(raw/name).write_text('[]')
            (results/'summary-exits.txt').write_text('fixture')
            context.enter_context(patch.object(research,'ROOT',root));context.enter_context(patch.object(research,'RAW',raw));context.enter_context(patch.object(research,'RESULTS',results))
            for module,name in [(research,'research.py'),(research.metrics,'metrics.py'),(research.books,'books.py'),(research.cache_assets,'cache_assets.py'),(research.run,'run.py'),(research.revalue,'revalue.py')]:
                file=root/name;file.write_text('source');context.enter_context(patch.object(module,'__file__',str(file)))
            expected=research.signature();original=Path.stat;directory=raw/'px'
            stamp=directory.stat().st_mtime_ns
            def stat(path,*args,**kwargs):
                result=original(path,*args,**kwargs)
                if path==directory:return SimpleNamespace(st_size=999999,st_mtime_ns=stamp,st_mode=result.st_mode)
                return result
            with patch.object(Path,'stat',stat):self.assertEqual(research.signature(),expected)
            self.assertEqual(expected['raw/px'][0],'directory')
            self.assertTrue(all('\\' not in key for key in expected))


if __name__=='__main__':unittest.main()
