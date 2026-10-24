"""Committed source publication, recovery and actual cross-process ownership."""
import hashlib
from contextlib import closing
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'website'), str(ROOT / 'scripts')]
import deploy
import runtime_access


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'runtime'
        self.root.mkdir()
        self.stage = self.root / '.deployment' / 'stage-test'
        self.payload = self.stage / 'payload'
        self.payload.mkdir(parents=True)

    def manifest(self, files, commit='a' * 40):
        hashes = {}
        for name, content in files.items():
            path = self.payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            hashes[name] = deploy.digest(path)
        return dict(version=1, commit=commit, files=hashes, source='/home/test/project', distro='Ubuntu')

    def test_preserves_runtime_assets_and_source_mtime(self):
        files = {'scripts/engine.py': 'one', 'README.md': 'source'}
        manifest = self.manifest(files)
        for name in ('raw/prices.json', 'data/research.sqlite', deploy.REPORT,
                     'website/local/index.html', 'website/.openai/hosting.json'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'Windows-owned')
        deploy.publish(self.root, self.payload, manifest)
        before = (self.root / 'scripts/engine.py').stat().st_mtime_ns
        deploy.publish(self.root, self.payload, manifest)
        self.assertEqual((self.root / 'scripts/engine.py').stat().st_mtime_ns, before)
        self.assertEqual((self.root / deploy.REPORT).read_bytes(), b'Windows-owned')
        self.assertEqual((self.root / 'data/research.sqlite').read_bytes(), b'Windows-owned')
        self.assertEqual(deploy.read_json(self.root / deploy.MANIFEST)['commit'], 'a' * 40)
        self.assertFalse((self.root / deploy.PENDING).exists())

    def test_collision_preflight_and_outside_edits(self):
        manifest = self.manifest({'scripts/engine.py': 'one', 'README.md': 'source'})
        (self.root / 'README.md').write_text('unowned user file')
        with self.assertRaisesRegex(ValueError, 'unowned'):
            deploy.publish(self.root, self.payload, manifest)
        self.assertFalse((self.root / 'scripts/engine.py').exists())
        self.assertFalse((self.root / deploy.PENDING).exists())
        (self.root / 'README.md').unlink()
        deploy.publish(self.root, self.payload, manifest)
        (self.root / 'scripts/engine.py').write_text('runtime edit')
        with self.assertRaisesRegex(ValueError, 'outside Git'):
            deploy.publish(self.root, self.payload, manifest)

    def test_missing_established_report_is_not_reseeded(self):
        manifest = self.manifest({'README.md': 'source'})
        (self.payload / 'results').mkdir()
        (self.payload / deploy.REPORT).write_text('reviewed initial report')
        deploy.publish(self.root, self.payload, manifest)
        self.assertEqual((self.root / deploy.REPORT).read_text(), 'reviewed initial report')
        (self.root / deploy.REPORT).unlink()
        deploy.publish(self.root, self.payload, manifest)
        self.assertFalse((self.root / deploy.REPORT).exists())

    def test_existing_database_prevents_first_deploy_report_seed(self):
        manifest = self.manifest({'README.md': 'source'})
        (self.payload / 'results').mkdir()
        (self.payload / deploy.REPORT).write_text('old Git report')
        (self.root / 'data').mkdir()
        (self.root / 'data/research.sqlite').write_bytes(b'existing database')
        deploy.publish(self.root, self.payload, manifest)
        self.assertFalse((self.root / deploy.REPORT).exists())

    def test_removes_only_manifest_owned_source(self):
        first = self.manifest({'scripts/removed.py': 'old', 'README.md': 'source'})
        deploy.publish(self.root, self.payload, first)
        (self.root / 'scripts/user.txt').write_text('keep')
        second = self.manifest({'README.md': 'source'}, 'b' * 40)
        deploy.publish(self.root, self.payload, second)
        self.assertFalse((self.root / 'scripts/removed.py').exists())
        self.assertEqual((self.root / 'scripts/user.txt').read_text(), 'keep')

    def test_interruption_blocks_startup_and_retry_finishes(self):
        first = self.manifest({'scripts/engine.py': 'one', 'README.md': 'source'})
        deploy.publish(self.root, self.payload, first)
        second = self.manifest({'scripts/engine.py': 'two', 'README.md': 'new source'}, 'b' * 40)
        install = deploy.install_file
        calls = 0
        def interrupted(source, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('simulated interruption')
            return install(source, target)
        with patch.object(deploy, 'install_file', side_effect=interrupted), self.assertRaises(OSError):
            deploy.publish(self.root, self.payload, second)
        self.assertTrue((self.root / deploy.PENDING).exists())
        with self.assertRaisesRegex(RuntimeError, 'unfinished'):
            with runtime_access.ownership(self.root):
                pass
        deploy.publish(self.root, self.payload, second)
        self.assertEqual((self.root / 'scripts/engine.py').read_text(), 'two')
        self.assertEqual((self.root / 'README.md').read_text(), 'new source')
        self.assertFalse((self.root / deploy.PENDING).exists())

    def test_recovery_rejects_tampered_staging(self):
        manifest = self.manifest({'README.md': 'source'})
        with patch.object(deploy, 'install_file', side_effect=OSError()), self.assertRaises(OSError):
            deploy.publish(self.root, self.payload, manifest)
        (self.payload / 'README.md').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'verification'):
            deploy.apply_pending(self.root)
        self.assertTrue((self.root / deploy.PENDING).exists())

    def test_manifest_cannot_own_data_or_repository(self):
        for name in ('../escape', '/absolute', 'folder\\file', 'file:stream', './file'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                deploy.source_path(name)
        for name in ('raw/a.json', 'data/research.sqlite', deploy.REPORT, '.git/config',
                     '.git-local/HEAD', '.venv/file', '.env', 'website/local/index.html',
                     'Raw/a.json', 'DATA/deployment.json', 'RESULTS/SUMMARY-EXITS.TXT'):
            with self.subTest(name=name):
                self.assertFalse(deploy.managed(name))
        manifest = self.manifest({'README.md': 'source'})
        (self.root / '.git').write_text('gitdir: somewhere')
        with self.assertRaisesRegex(ValueError, 'repository'):
            deploy.publish(self.root, self.payload, manifest)

    def test_case_only_rename_fails_before_publication(self):
        first = self.manifest({'scripts/Module.py': 'one'})
        deploy.publish(self.root, self.payload, first)
        second = self.manifest({'scripts/module.py': 'two'}, 'b' * 40)
        with self.assertRaisesRegex(ValueError, 'case-only'):
            deploy.publish(self.root, self.payload, second)
        self.assertFalse((self.root / deploy.PENDING).exists())
        self.assertEqual((self.root / 'scripts/Module.py').read_text(), 'one')

    def test_authentication_stops_all_owned_alternate_ports(self):
        (self.root / 'data').mkdir()
        states = []
        for port in (3000, 8765):
            state = dict(port=port, pid=port + 100, token='test-token', project=str(self.root))
            states.append(state)
            deploy.write_json(self.root / 'data' / f'website-server-{port}.json', state)
        import launcher
        def request(state, path, method='GET'):
            return state if method == 'GET' else dict(stopping=True)
        with patch.object(launcher, 'request', side_effect=request) as calls, patch.object(launcher, 'wait_legacy_process') as wait:
            deploy.stop_servers(self.root)
        self.assertEqual(sum(call.args[-1:] == ('POST',) for call in calls.call_args_list), 2)
        self.assertEqual([call.args[0] for call in wait.call_args_list], [3100, 8865])
        with patch.object(launcher, 'request', return_value=dict(project='unrelated', token='wrong', pid=3100)) as calls:
            with self.assertRaisesRegex(ValueError, 'authenticated'):
                deploy.stop_servers(self.root)
        self.assertEqual(calls.call_count, 1)

    def test_archive_ignores_windows_assets_and_rejects_links(self):
        def archive(entries):
            with tarfile.open(self.stage / 'source.tar', 'w') as output:
                for name, content, link in entries:
                    item = tarfile.TarInfo(name)
                    if link:
                        item.type = tarfile.SYMTYPE
                        item.linkname = content
                        output.addfile(item)
                    else:
                        content = content.encode()
                        item.size = len(content)
                        output.addfile(item, io.BytesIO(content))
            deploy.write_json(self.stage / 'request.json', dict(commit='a' * 40,
                              archive_sha256=deploy.digest(self.stage / 'source.tar'), source='source', distro='Ubuntu'))
        archive([('README.md', 'source', False), ('raw/secret.json', 'omit', False),
                 (deploy.REPORT, 'initial report', False)])
        payload, manifest = deploy.unpack(self.stage)
        self.assertEqual(list(manifest['files']), ['README.md'])
        self.assertFalse((payload / 'raw/secret.json').exists())
        self.assertTrue((payload / deploy.REPORT).exists())
        archive([('scripts/link.py', '/outside', True)])
        with self.assertRaisesRegex(ValueError, 'plain Git files'):
            deploy.unpack(self.stage)

    def test_publication_cli_installs_verified_archive(self):
        names = ('tools/deploy.py', 'website/runtime_access.py', 'website/launcher.py',
                 'scripts/cache_access.py', 'scripts/paths.py')
        with tarfile.open(self.stage / 'source.tar', 'w') as output:
            for name in names:
                output.add(ROOT / name, arcname=name, recursive=False)
        deploy.write_json(self.stage / 'request.json', dict(commit='c' * 40,
                          archive_sha256=deploy.digest(self.stage / 'source.tar'), source='/home/test/source', distro='Ubuntu'))
        bootstrap = self.stage / 'bootstrap.py'
        shutil.copy2(ROOT / 'tools/deploy.py', bootstrap)
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(bootstrap),
                                 '--native-publish', str(self.stage), str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(deploy.read_json(self.root / deploy.MANIFEST)['commit'], 'c' * 40)
        self.assertEqual((self.root / 'website/runtime_access.py').read_bytes(),
                         (ROOT / 'website/runtime_access.py').read_bytes())

    def test_report_export_requires_database_binding(self):
        content = b'Through 2026-10-21\n'
        (self.root / 'results').mkdir()
        (self.root / deploy.REPORT).write_bytes(content)
        (self.root / 'data').mkdir()
        with closing(sqlite3.connect(self.root / 'data/research.sqlite')) as db:
            with db:
                db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
                db.executemany('INSERT INTO metadata VALUES(?,?)', [
                    ('baseline_report_sha', json.dumps(hashlib.sha256(content).hexdigest())),
                    ('baseline_result', json.dumps(dict(through='2026-10-21', years=[])))])
        bundle = self.stage / 'report'
        deploy.export_runtime_report(self.root, bundle)
        self.assertEqual((bundle / 'summary-exits.txt').read_bytes(), content)
        (self.root / deploy.REPORT).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            deploy.export_runtime_report(self.root, bundle)

    def test_report_export_owns_source_before_financial_imports(self):
        scripts = self.root / 'scripts'
        scripts.mkdir()
        marker = self.root / 'financial-import'
        (scripts / 'baseline.py').write_text('from pathlib import Path\n'
                'Path(__file__).resolve().parents[1].joinpath("financial-import").write_text("yes")\n'
                'raise RuntimeError("import probe finished")\n')
        code = ('import sys;sys.path[:0]=[sys.argv[1],sys.argv[2]];import deploy;'
                'deploy.export_runtime_report(sys.argv[3],sys.argv[4])')
        child = None
        try:
            with runtime_access.ownership(self.root, exclusive=True):
                child = subprocess.Popen([sys.executable, '-B', '-c', code, str(ROOT / 'tools'),
                                          str(ROOT / 'website'), str(self.root), str(self.stage / 'report')],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                import time
                time.sleep(.2)
                self.assertFalse(marker.exists())
                self.assertIsNone(child.poll())
            child.communicate(timeout=10)
            self.assertNotEqual(child.returncode, 0)
            self.assertTrue(marker.exists())
        finally:
            if child and child.poll() is None:
                child.kill()
                child.communicate()

    def test_shared_readers_exclude_writer_and_release_on_process_exit(self):
        code = ('import sys;sys.path.insert(0,sys.argv[1]);import runtime_access;'
                'owner=runtime_access.ownership(sys.argv[2]);owner.__enter__();'
                'print("ready",flush=True);sys.stdin.readline();owner.__exit__(None,None,None)')
        children = []
        try:
            for unused in range(2):
                child = subprocess.Popen([sys.executable, '-B', '-c', code, str(ROOT / 'website'), str(self.root)],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                children.append(child)
                self.assertEqual(child.stdout.readline().strip(), 'ready')
            with self.assertRaises(RuntimeError):
                with runtime_access.ownership(self.root, exclusive=True, timeout=.1):
                    pass
            children[0].communicate('\n', timeout=10)
            with self.assertRaises(RuntimeError):
                with runtime_access.ownership(self.root, exclusive=True, timeout=.1):
                    pass
            children[1].terminate()
            children[1].communicate(timeout=10)
            with runtime_access.ownership(self.root, exclusive=True, timeout=1):
                pass
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate()

    def test_entry_point_owns_source_before_application_import(self):
        website = self.root / 'website'
        website.mkdir()
        for name in ('serve.py', 'runtime_access.py'):
            shutil.copy2(ROOT / 'website' / name, website / name)
        marker = self.root / 'imported'
        (website / 'serve_app.py').write_text('from pathlib import Path\n'
                'Path(__file__).resolve().parents[1].joinpath("imported").write_text("yes")\n'
                'def main(): pass\n')
        child = None
        try:
            with runtime_access.ownership(self.root, exclusive=True):
                child = subprocess.Popen([sys.executable, '-B', str(website / 'serve.py')],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                import time
                time.sleep(.2)
                self.assertFalse(marker.exists())
                self.assertIsNone(child.poll())
            output, error = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, error)
            self.assertTrue(marker.exists())
            marker.unlink()
            deploy.write_json(self.root / deploy.PENDING, {'unfinished': True})
            result = subprocess.run([sys.executable, '-B', str(website / 'serve.py')], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())
        finally:
            if child and child.poll() is None:
                child.kill()
                child.communicate()

    def test_native_launcher_delegates_one_way_to_wsl(self):
        config = dict(source='/home/test/source', distro='Ubuntu')
        deploy.write_json(self.root / deploy.CONFIG, config)
        with patch.object(deploy, 'ROOT', self.root), patch.object(deploy.subprocess, 'call', return_value=0) as call:
            self.assertEqual(deploy.native_launch(['--no-browser']), 0)
        self.assertEqual(call.call_args.args[0], ['wsl.exe', '-d', 'Ubuntu', '--cd', '/home/test/source',
                                                '--exec', 'python3', 'tools/deploy.py', '--start', '--no-browser'])

    def test_spawned_entry_keeps_source_ownership_after_bootstrap(self):
        website = self.root / 'website'
        website.mkdir()
        for name in ('serve.py', 'runtime_access.py'):
            shutil.copy2(ROOT / 'website' / name, website / name)
        (website / 'serve_app.py').write_text('def main(): raise RuntimeError("worker must not run main")\n')
        code = ('import runpy,sys;runpy.run_path(sys.argv[1],run_name="__mp_main__");'
                'print("ready",flush=True);sys.stdin.readline()')
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(website / 'serve.py')],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 env=dict(__import__('os').environ, PYTHONPATH=str(website)))
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            with self.assertRaises(RuntimeError):
                with runtime_access.ownership(self.root, exclusive=True, timeout=.1):
                    pass
            child.communicate('\n', timeout=10)
            self.assertEqual(child.returncode, 0)
            with runtime_access.ownership(self.root, exclusive=True, timeout=1):
                pass
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()


if __name__ == '__main__':
    unittest.main()
