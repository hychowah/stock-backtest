"""One launcher resolves dependencies and opens the browser without manual steps."""
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.inputs import daily
from contextlib import ExitStack, closing, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import io
import sys
import errno
import sqlite3
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
from website.server import app as serve
from website.rendering import state as build_state
from website import build
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import research as research


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.context.enter_context(patch.object(serve.cache_access,'access',side_effect=lambda:nullcontext()))
        self.context.enter_context(patch.object(serve.diagnostics,'configure',return_value=None))
        self.context.enter_context(patch.object(serve.diagnostics,'close'))
        self.context.enter_context(patch.object(serve.cache_assets,'source_problem',return_value=False))
        # main() stamps the process streams; these private ones keep that inside each test.
        self.stdout=io.StringIO()
        self.context.enter_context(patch.object(sys,'stdout',self.stdout))
        self.context.enter_context(patch.object(sys,'stderr',io.StringIO()))

    def test_prepare_then_build_when_stale(self):
        calls=[]
        with patch.object(daily,'prepare',side_effect=lambda:calls.append('prepare')),patch.object(serve,'current_build',side_effect=lambda:calls.append('check_build') or False),patch.object(serve.subprocess,'run',side_effect=lambda *args,**kwargs:calls.append('build')) as run:
            serve.ensure_ready()
        self.assertEqual(calls,['prepare','check_build','build'])
        self.assertEqual(run.call_args.args[0],[sys.executable,'-X','utf8',str(serve.ROOT/'build.py'),'--cache-owned'])
        self.assertTrue(run.call_args.kwargs['check'])

    def test_unchanged_caches_do_not_rebuild_page(self):
        with patch.object(daily,'prepare'),patch.object(serve,'current_build',return_value=True),patch.object(serve.subprocess,'run') as run:
            serve.ensure_ready()
        run.assert_not_called()

    def test_main_opens_browser_after_successful_bind(self):
        calls=[];server=Mock();server.server_address=('127.0.0.1',8765)
        server.serve_forever.side_effect=lambda:calls.append('serve')
        with patch.object(sys,'argv',['serve.py']),patch.object(serve,'ensure_ready',side_effect=lambda:calls.append('prepare')),patch.object(serve,'Server',side_effect=lambda *args:calls.append('bind') or server),patch.object(serve.webbrowser,'open',side_effect=lambda url:calls.append('browser')):
            serve.main()
        self.assertEqual(calls,['prepare','bind','browser','serve'])
        server.server_close.assert_called_once()
        lines=self.stdout.getvalue().splitlines()
        self.assertTrue(lines)
        for line in lines:self.assertRegex(line,r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \S')

    def test_missing_sources_open_recovery_panel_without_preparation(self):
        server=Mock();server.server_address=('127.0.0.1',3000)
        with patch.object(sys,'argv',['serve.py','--no-browser']),patch.object(serve.cache_assets,'source_problem',return_value=True),patch.object(serve,'ensure_ready') as prepare,patch.object(serve,'Server',return_value=server):
            serve.main()
        prepare.assert_not_called();self.assertTrue(server.data_recovery)
        server.serve_forever.assert_called_once()

    def test_ctrl_c_closes_terminal_owned_server(self):
        server=Mock();server.server_address=('0.0.0.0',3000)
        server.serve_forever.side_effect=KeyboardInterrupt
        with patch.object(sys,'argv',['serve.py','--no-browser']),patch.object(serve,'ensure_ready'),patch.object(serve,'Server',return_value=server):
            serve.main()
        server.server_close.assert_called_once()

    def test_failure_never_opens_browser(self):
        with patch.object(sys,'argv',['serve.py']),patch.object(serve,'ensure_ready',side_effect=ValueError('bad cache')),patch.object(serve,'Server') as server,patch.object(serve.webbrowser,'open') as browser:
            with self.assertRaises(SystemExit):serve.main()
        server.assert_not_called();browser.assert_not_called()

    def test_bind_failure_does_not_open_browser(self):
        with patch.object(sys,'argv',['serve.py']),patch.object(serve,'ensure_ready'),patch.object(serve,'Server',side_effect=OSError('port unavailable')),patch.object(serve.webbrowser,'open') as browser:
            with self.assertRaises(SystemExit):serve.main()
        browser.assert_not_called()

    def test_no_browser_flag(self):
        server=Mock();server.server_address=('127.0.0.1',8765)
        with patch.object(sys,'argv',['serve.py','--no-browser']),patch.object(serve,'ensure_ready'),patch.object(serve,'Server',return_value=server),patch.object(serve.webbrowser,'open') as browser:
            serve.main()
        browser.assert_not_called();server.serve_forever.assert_called_once()

    def test_occupied_port_opens_new_instance_instead_of_stale_server(self):
        server=Mock();server.server_address=('127.0.0.1',49123)
        with patch.object(sys,'argv',['serve.py']),patch.object(serve,'ensure_ready'),patch.object(serve,'Server',side_effect=[OSError(errno.EADDRINUSE,'in use'),server]) as bind,patch.object(serve.webbrowser,'open') as browser:
            serve.main()
        self.assertEqual(bind.call_args_list[1].args[0],('0.0.0.0',0))
        browser.assert_called_once_with('http://127.0.0.1:49123')
        server.server_close.assert_called_once()


class BuildStateTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.website=root/'website';(self.website/'local').mkdir(parents=True)
        (root/'data').mkdir();self.daily=root/'data'/'schedules.sqlite'
        with closing(sqlite3.connect(self.daily)) as db:
            db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute("INSERT INTO metadata VALUES('daily_inputs','{\"generation\":1}')");db.commit()
        (self.website/'browser').mkdir()
        self.source=self.website/'browser/range.js';self.source.write_bytes(b'const n=1;\r\n')
        for name in ('index.html','latest-picks.csv','data.html'):
            (self.website/'local'/name).write_text('output')
        self.context.enter_context(patch.object(build_state,'ROOT',self.website))
        self.context.enter_context(patch.object(build_state,'LOCAL_OUTPUT',self.website/'local'))
        self.context.enter_context(patch.object(build_state,'STAMP',self.website/'local'/'.build-state.json'))

    def test_application_source_moves_retain_freshness_and_normalized_keys(self):
        application=self.website.parent/'backtest/application';application.mkdir(parents=True)
        owner=application/'jobs.py';owner.write_bytes(b'value=1;\r\n')
        sources=build_state.inputs()['sources']
        self.assertIn('backtest/application/jobs.py',sources)
        build_state.record_build();self.assertTrue(build_state.current_build())
        owner.write_bytes(b'value=1;\n');self.assertTrue(build_state.current_build())
        owner.write_bytes(b'value=2;\n');self.assertFalse(build_state.current_build())
        generated=application/'__pycache__';generated.mkdir();(generated/'jobs.py').write_text('ignored')
        self.assertNotIn('backtest/application/__pycache__/jobs.py',build_state.inputs()['sources'])

    def test_nested_owners_invalidate_and_generated_directories_do_not(self):
        for directory in ('browser','rendering','server'):
            folder=self.website/directory
            folder.mkdir(exist_ok=True)
            nested=folder/'nested';nested.mkdir()
            source=nested/'owner.py';source.write_text('value=1\n')
            build_state.record_build()
            self.assertIn('website/'+directory+'/nested/owner.py',build_state.inputs()['sources'])
            source.write_text('value=2\n')
            self.assertFalse(build_state.current_build())
        build_state.record_build()
        for directory in ('local','dist','.openai','node_modules','server/__pycache__'):
            folder=self.website/directory;folder.mkdir(parents=True,exist_ok=True)
            (folder/'generated.py').write_text('ignored')
        self.assertTrue(build_state.current_build())

    def test_latest_book_generation_not_the_cache_stamp_binds_the_build(self):
        build_state.record_build();self.assertTrue(build_state.current_build())
        # Saving a dated book rewrites the cache; the latest book is unchanged.
        with closing(sqlite3.connect(self.daily)) as db:
            db.execute("INSERT INTO metadata VALUES('saved','book')");db.commit()
        self.assertTrue(build_state.current_build())
        with closing(sqlite3.connect(self.daily)) as db:
            db.execute("UPDATE metadata SET value='{\"generation\":2}' WHERE key='daily_inputs'");db.commit()
        self.assertFalse(build_state.current_build())
        self.daily.unlink();self.assertFalse(build_state.current_build())

    def test_portable_snapshot_does_not_satisfy_local_build(self):
        snapshot=self.website/'dist';snapshot.mkdir()
        for path in (self.website/'local').iterdir():
            (snapshot/path.name).write_bytes(path.read_bytes())
            path.unlink()
        build_state.record_build()
        self.assertFalse(build_state.current_build())

    def test_source_changes_invalidate_but_newlines_do_not(self):
        self.assertFalse(build_state.current_build())
        build_state.record_build();self.assertTrue(build_state.current_build())
        self.source.write_bytes(b'const n=1;\n');self.assertTrue(build_state.current_build())
        self.source.write_text('const n=2;');self.assertFalse(build_state.current_build())

    def test_missing_artifacts_and_malformed_stamp(self):
        build_state.record_build();(self.website/'local'/'latest-picks.csv').unlink()
        self.assertFalse(build_state.current_build())
        (self.website/'local'/'latest-picks.csv').write_text('output')
        build_state.STAMP.write_text('bad JSON');self.assertFalse(build_state.current_build())


class BuildDestinationTests(unittest.TestCase):
    def test_cli_defaults_to_local_and_snapshot_requires_flag(self):
        for options,destination in [([],build.LOCAL_OUTPUT),(['--snapshot'],build.SNAPSHOT_OUTPUT)]:
            with patch.object(sys,'argv',['build.py',*options]),patch.object(build.cache_access,'access',return_value=nullcontext()),patch.object(build,'build') as main:
                build.cli()
            main.assert_called_once_with(destination)

    def test_handler_serves_local_output(self):
        with patch('http.server.SimpleHTTPRequestHandler.__init__') as initialize:
            serve.Handler(None,None,None)
        self.assertEqual(initialize.call_args.kwargs['directory'],str(build_state.LOCAL_OUTPUT))


class PortableFingerprintTests(unittest.TestCase):
    def test_directory_size_is_not_a_cache_dependency(self):
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as context:
            root=Path(tmp);raw=root/'raw';raw.mkdir();(raw/'px').mkdir()
            for name in ('universe.json','metrics.jsonl','spy-div.json','treasury.json'):(raw/name).write_text('[]')
            context.enter_context(patch.object(research,'ROOT',root));context.enter_context(patch.object(research,'RAW',raw))
            for module,name in [(research,'research.py'),(research.metrics,'metrics.py'),(research.books,'books.py'),(research.rules,'rules.py'),(research.cache_assets,'cache_assets.py'),(research.financial_inputs,'financial_inputs.py'),(research.market,'market.py'),(research.financial_inputs.parameters,'parameters.py'),(research.facts,'facts.py')]:
                file=root/name;file.write_text('source');context.enter_context(patch.object(module,'__file__',str(file)))
            for name in ('fmp_download.py','daily.py'):(root/name).write_text('source')
            expected=research.signature();original=Path.stat;directory=raw/'px'
            stamp=directory.stat().st_mtime_ns
            def stat(path,*args,**kwargs):
                result=original(path,*args,**kwargs)
                if path==directory:return SimpleNamespace(st_size=999999,st_mtime_ns=stamp,st_mode=result.st_mode)
                return result
            with patch.object(Path,'stat',stat):self.assertEqual(research.signature(),expected)
            self.assertEqual(expected['raw/px'][0],'directory')
            self.assertTrue(all('\\' not in key for key in expected))
            policy_source=Path(research.books.__file__)
            policy_source.write_text('changed book policy source')
            changed=research.signature()
            self.assertNotEqual(changed['books.py'],expected['books.py'])
            self.assertEqual({key:value for key,value in changed.items() if key!='books.py'},
                             {key:value for key,value in expected.items() if key!='books.py'})


if __name__=='__main__':unittest.main()
