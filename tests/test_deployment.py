"""Committed source publication, recovery and actual cross-process ownership."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
import hashlib
from contextlib import closing, ExitStack
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tools.ops.deploy as deploy
from website import runtime_access
@unittest.skipUnless(sys.platform=='win32','Windows batch entry checks require native Windows.')
class BatchEntryTests(unittest.TestCase):
    def command(self,launcher,*arguments,cwd):
        return subprocess.run([os.environ.get('COMSPEC','cmd.exe'),'/d','/c','call',str(launcher),*arguments],
                              cwd=cwd,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=20)

    def test_batch_entry_uses_its_own_script_from_an_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'launcher with spaces';(root/'tools').mkdir(parents=True)
            elsewhere=Path(folder)/'elsewhere';elsewhere.mkdir()
            for name in ('backtest-web.cmd','start.cmd'):shutil.copy2(ROOT/name,root/name)
            (root/'tools/deploy.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            result=self.command(root/'backtest-web.cmd','--no-browser','--port','4312',cwd=elsewhere)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout.splitlines()[-1]),['--native-launch','--no-browser','--port','4312'])

    def test_batch_entry_from_the_unc_source_path(self):
        if not str(ROOT).startswith('\\\\'):self.skipTest('Run from the WSL source UNC path to check this entry.')
        with tempfile.TemporaryDirectory() as elsewhere:
            # Help exercises real batch/Python resolution without publishing
            # source, starting a server or touching runtime financial data.
            result=self.command(ROOT/'backtest-web.cmd','--help',cwd=elsewhere)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('usage: deploy.py',result.stdout)


class DeploymentRevisionTests(unittest.TestCase):
    """Resolve intent against disposable evidence before any publication action."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'runtime'
        self.root.mkdir()
        self.source = Path(temporary.name) / 'source'
        self.config = dict(source=str(self.source), distro='Ubuntu', runtime=str(self.root), python='fixture-python')
        self.installed = self.manifest('a' * 40)
        self.pending = self.manifest('b' * 40)
        self.head = 'c' * 40
        self.addCleanup(patch.stopall)
        patch.object(deploy, 'ROOT', self.source).start()
        patch.object(deploy, 'linux_path', side_effect=Path).start()
        self.git = patch.object(deploy, 'git', side_effect=self.git_result).start()

    def manifest(self, commit):
        return dict(version=1, commit=commit, files={'README.md': 'd' * 64},
                    source=str(self.source), distro='Ubuntu')

    def git_result(self, *arguments):
        if arguments[0] == 'rev-parse':
            self.assertEqual(arguments[:3], ('rev-parse', '--verify', '--end-of-options'))
            revision = arguments[3].removesuffix('^{commit}')
            if revision == 'HEAD':
                return self.head.encode()
            if revision in ('a' * 40, 'b' * 40, 'c' * 40):
                return revision.encode()
            raise subprocess.CalledProcessError(128, ['fixture-git', 'rev-parse'])
        self.assertEqual(arguments[0], 'show')
        return b'committed bootstrap fixture'

    def evidence(self, installed=True, previous=True):
        if installed:
            deploy.write_json(self.root / deploy.MANIFEST, self.installed)
        journal = dict(manifest=self.pending, previous=self.installed if previous else None,
                       payload='.deployment/stage-retained/payload')
        deploy.write_json(self.root / deploy.PENDING, journal)
        return journal

    def assert_rejected(self, requested=None, error=ValueError):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with ExitStack() as stack:
            guards = [stack.enter_context(patch.object(owner, name)) for owner, name in (
                (Path, 'mkdir'), (deploy, 'native'), (deploy.subprocess, 'run'),
                (deploy, 'stop_servers'), (deploy, 'cache_ownership'),
                (runtime_access, 'ownership'), (deploy, 'install_file'), (deploy, 'windows_path'))]
            with self.assertRaises(error):
                deploy.deploy(self.config, requested)
            for guard in guards:
                guard.assert_not_called()
        self.assertFalse((self.root / '.deployment').exists())
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(after, before)
        self.assertFalse(any(call.args[0] == 'show' for call in self.git.call_args_list))

    def test_default_retains_installed_commit_while_head_differs(self):
        deploy.write_json(self.root / deploy.MANIFEST, self.installed)
        self.assertEqual(deploy.deployment_revision(self.config), 'a' * 40)
        self.git.assert_called_once_with('rev-parse', '--verify', '--end-of-options', 'a' * 40 + '^{commit}')

    def test_fresh_runtime_requires_explicit_revision(self):
        self.assert_rejected()
        self.git.assert_not_called()
        self.assertEqual(deploy.deployment_revision(self.config, 'HEAD'), self.head)

    def test_explicit_selection_can_change_installed_commit(self):
        deploy.write_json(self.root / deploy.MANIFEST, self.installed)
        self.assertEqual(deploy.deployment_revision(self.config, 'HEAD'), self.head)

    def test_pending_owns_default_with_old_new_or_absent_installed_manifest(self):
        for current in (self.installed, self.pending, None):
            with self.subTest(current=current):
                self.evidence(installed=False)
                path = self.root / deploy.MANIFEST
                if current is None:
                    path.unlink(missing_ok=True)
                else:
                    deploy.write_json(path, current)
                self.assertEqual(deploy.deployment_revision(self.config), self.pending['commit'])
                self.assertTrue((self.root / deploy.PENDING).exists())
        self.evidence(installed=False, previous=False)
        self.assertEqual(deploy.deployment_revision(self.config), self.pending['commit'])

    def test_pending_allows_only_its_exact_commit(self):
        self.evidence()
        self.assertEqual(deploy.deployment_revision(self.config, self.pending['commit']), self.pending['commit'])
        self.assert_rejected('HEAD')
        self.assert_rejected(self.installed['commit'])

    def test_invalid_installed_evidence_fails_even_for_explicit_selection(self):
        invalid = [None, {}, [], dict(self.installed, version=True), dict(self.installed, commit=None),
                   dict(self.installed, commit='HEAD'), dict(self.installed, files=[]),
                   dict(self.installed, files={'README.md': None}),
                   dict(self.installed, files={'raw/prices.json': 'd' * 64}),
                   dict(self.installed, files={'README.md': 'd' * 64, 'readme.md': 'd' * 64}),
                   dict(self.installed, source='/different/source'), dict(self.installed, distro='Other')]
        for value in invalid:
            with self.subTest(value=value):
                deploy.write_json(self.root / deploy.MANIFEST, value)
                self.assert_rejected('HEAD')
        for content in ('', '{'):
            with self.subTest(content=content):
                (self.root / deploy.MANIFEST).write_text(content)
                self.assert_rejected('HEAD')

    def test_malformed_pending_never_behaves_as_missing(self):
        valid = self.evidence()
        invalid = [None, {}, [], False]
        invalid += [{key: value for key, value in valid.items() if key != missing}
                    for missing in valid]
        invalid += [dict(valid, manifest=value) for value in (None, {}, [], dict(self.pending, commit=42))]
        invalid += [dict(valid, previous=value) for value in ({}, [], False, dict(self.installed, source='wrong'))]
        invalid += [dict(valid, payload=value) for value in (None, '', '../outside', 'elsewhere/payload', '.deployment')]
        for value in invalid:
            with self.subTest(value=value):
                deploy.write_json(self.root / deploy.PENDING, value)
                self.assert_rejected('HEAD')
        for content in ('', '{'):
            with self.subTest(content=content):
                (self.root / deploy.PENDING).write_text(content)
                self.assert_rejected()

    def test_pending_rejects_unrelated_or_malformed_current_evidence(self):
        self.evidence()
        for value in (self.manifest('c' * 40), None, {}, dict(self.installed, files={})):
            with self.subTest(value=value):
                deploy.write_json(self.root / deploy.MANIFEST, value)
                self.assert_rejected()

    def test_invalid_registration_rejects_before_publication(self):
        deploy.write_json(self.root / deploy.MANIFEST, self.installed)
        original = self.config.copy()
        for field, value in (('source', '/other/source'), ('distro', None), ('distro', ''),
                             ('distro', 'Other'), ('runtime', None), ('runtime', '')):
            with self.subTest(field=field, value=value):
                self.config = dict(original, **{field: value})
                self.assert_rejected('HEAD')

    def test_missing_history_never_falls_back_to_head(self):
        deploy.write_json(self.root / deploy.MANIFEST, dict(self.installed, commit='e' * 40))
        self.assert_rejected(error=subprocess.CalledProcessError)
        self.git.assert_called_once_with('rev-parse', '--verify', '--end-of-options', 'e' * 40 + '^{commit}')
        self.evidence()
        journal = deploy.read_json(self.root / deploy.PENDING)
        journal['manifest']['commit'] = 'e' * 40
        deploy.write_json(self.root / deploy.PENDING, journal)
        self.assert_rejected(error=subprocess.CalledProcessError)

    def test_export_uses_one_resolved_commit_for_bootstrap_and_archive(self):
        deploy.write_json(self.root / deploy.MANIFEST, self.installed)
        for requested, expected in ((None, 'a' * 40), ('HEAD', 'c' * 40)):
            with self.subTest(requested=requested):
                self.git.reset_mock()
                self.head = 'c' * 40
                def archive(command, stdout, check):
                    self.assertEqual(command, ['/usr/bin/git', '--git-dir=' + str(self.source / '.git-local'),
                                     '--work-tree=' + str(self.source), 'archive', '--format=tar', expected])
                    self.head = 'b' * 40  # A moving name cannot affect the extracted generation.
                    stdout.write(b'fixture archive')
                def publish(config, bootstrap, operation, stage, runtime):
                    self.assertEqual(operation, '--native-publish')
                    self.assertEqual(Path(bootstrap).read_bytes(), b'committed bootstrap fixture')
                    request = deploy.read_json(Path(stage) / 'request.json')
                    self.assertEqual(request['commit'], expected)
                    self.assertEqual(request['archive_sha256'], deploy.digest(Path(stage) / 'source.tar'))
                with patch.object(deploy.subprocess, 'run', side_effect=archive) as run, \
                        patch.object(deploy, 'windows_path', side_effect=str), \
                        patch.object(deploy, 'native', side_effect=publish) as native:
                    deploy.deploy(self.config, requested)
                self.assertEqual(self.git.call_count, 2)
                self.assertEqual(self.git.call_args.args, ('show', expected + ':tools/deploy.py'))
                run.assert_called_once()
                native.assert_called_once()
                self.assertEqual(list((self.root / '.deployment').iterdir()), [])

    def test_parser_default_and_explicit_revision_reach_deploy(self):
        for selection, expected in (([], None), (['--revision', 'HEAD'], 'HEAD')):
            with self.subTest(selection=selection), patch.object(sys, 'argv', ['deploy.py', *selection]), \
                    patch.object(deploy.os, 'name', 'posix'), \
                    patch.object(deploy, 'configuration', return_value=self.config), \
                    patch.object(deploy, 'deploy') as publish:
                deploy.main()
                publish.assert_called_once_with(self.config, expected)

    def test_archive_failure_does_not_request_server_shutdown(self):
        deploy.write_json(self.root / deploy.MANIFEST, self.installed)
        with patch.object(deploy.subprocess,'run',side_effect=OSError('fixture archive failure')),patch.object(deploy,'windows_path',side_effect=str),patch.object(deploy,'native') as publish:
            stop=Mock()
            with self.assertRaises(OSError):deploy.deploy(self.config,self.installed['commit'],before_publish=stop)
        stop.assert_not_called();publish.assert_not_called()

    def test_native_parser_forwards_explicit_revision_and_default_has_no_head(self):
        deploy.write_json(self.root / deploy.CONFIG, self.config)
        for selection, expected in (([], []), (['--revision', 'HEAD'], ['--revision', 'HEAD'])):
            with self.subTest(selection=selection), patch.object(deploy, 'ROOT', self.root), \
                    patch.object(sys, 'argv', ['deploy.py', '--native-launch', *selection, '--no-browser']), \
                    patch.object(deploy.subprocess, 'call', return_value=0) as call, self.assertRaises(SystemExit) as result:
                deploy.main()
            self.assertEqual(result.exception.code, 0)
            self.assertEqual(call.call_args.args[0], ['wsl.exe', '-d', 'Ubuntu', '--cd', str(self.source),
                             '--exec', 'python3', 'tools/deploy.py', '--start', *expected, '--no-browser'])

    def test_unregistered_native_launcher_rejects_explicit_selection(self):
        with patch.object(deploy, 'ROOT', self.root), patch.object(deploy.subprocess, 'call') as call:
            with self.assertRaisesRegex(ValueError, 'registered'):
                deploy.native_launch(['--no-browser'], 'HEAD')
        call.assert_not_called()


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
        for name in ('raw/prices.json', 'data/research.sqlite', 'data/backtest-queue.sqlite', deploy.REPORT,
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
        self.assertEqual((self.root / 'data/backtest-queue.sqlite').read_bytes(), b'Windows-owned')
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
        for name in ('raw/a.json', 'data/research.sqlite', 'data/backtest-queue.sqlite', deploy.REPORT, '.git/config',
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
        from website.server import launcher
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
        names = ('tools/deploy.py', 'tools/ops/deploy.py', 'tools/__init__.py', 'tools/ops/__init__.py',
                 'website/__init__.py', 'website/server/__init__.py', 'website/runtime_access.py', 'website/server/launcher.py',
                 'backtest/runtime/cache_access.py', 'backtest/runtime/__init__.py', 'backtest/__init__.py', 'backtest/paths.py')
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

    def test_genuine_old_controller_publishes_selected_new_layout(self):
        """bdd75d9 really extracts the selected stable entry as one file."""
        import importlib.util
        historical = ROOT/'tests/fixtures/deployment-old-controller/deploy.py'
        self.assertEqual(hashlib.sha256(historical.read_bytes()).hexdigest(),'5a9fd344a2c64287ca24ba430ddd480201b7cf48b11516511cea627d5250db50')
        spec = importlib.util.spec_from_file_location('frozen_old_controller',historical)
        old = importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'source';source.mkdir()
            names=('tools/deploy.py','tools/ops/deploy.py','tools/__init__.py','tools/ops/__init__.py',
                'website/__init__.py','website/server/__init__.py','website/runtime_access.py',
                'website/server/launcher.py','backtest/__init__.py','backtest/paths.py',
                'backtest/runtime/__init__.py','backtest/runtime/cache_access.py')
            for name in names:
                destination=source/name;destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(ROOT/name,destination)
            git=shutil.which('git')
            if git is None:self.skipTest('Git is required for the genuine old-controller archive fixture.')
            subprocess.run([git,'init','-q','--separate-git-dir',str(source/'.git-local'),str(source)],check=True)
            def command(*args):return [git,'--git-dir='+str(source/'.git-local'),'--work-tree='+str(source),*args]
            for key,value in (('user.name','Fixture'),('user.email','fixture@example.invalid'),('core.autocrlf','false')):
                subprocess.run(command('config',key,value),check=True)
            subprocess.run(command('add','tools','website','backtest'),check=True)
            subprocess.run(command('commit','-qm','Private new-layout fixture'),check=True)
            commit=subprocess.check_output(command('rev-parse','HEAD')).decode().strip()
            config=dict(source=str(source),runtime=str(self.root),distro='Fixture',python=sys.executable)
            def native(config,*arguments):
                subprocess.run([sys.executable,'-B',*map(str,arguments)],check=True,capture_output=True)
            with patch.object(old,'ROOT',source),patch.object(old,'linux_path',side_effect=Path), \
                    patch.object(old,'windows_path',side_effect=str),patch.object(old,'git_command',side_effect=command), \
                    patch.object(old,'native',side_effect=native):
                old.deploy(config,commit)
            self.assertEqual(deploy.read_json(self.root/deploy.MANIFEST)['commit'],commit)
            self.assertEqual((self.root/'tools/ops/deploy.py').read_bytes(),(ROOT/'tools/ops/deploy.py').read_bytes())
            self.assertFalse((self.root/deploy.PENDING).exists())

    def test_stable_bootstrap_rejects_unbound_or_nonregular_helper(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('stable_deployment_entry',ROOT/'tools/deploy.py')
        entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
        content=b'raise AssertionError("unverified helper executed")\n'
        for kind in ('hash','missing','link','duplicate','oversize'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temporary:
                stage=Path(temporary)
                with tarfile.open(stage/'source.tar','w') as archive:
                    if kind!='missing':
                        member=tarfile.TarInfo(entry.HELPER_MEMBER)
                        member.size=len(content)
                        if kind=='link':member.type=tarfile.SYMTYPE;member.linkname='/outside'
                        if kind=='oversize':member.size=entry.MAX_HELPER_BYTES+1
                        payload=content if kind!='oversize' else b'x'*member.size
                        archive.addfile(member,io.BytesIO(payload) if member.isfile() else None)
                        if kind=='duplicate':archive.addfile(member,io.BytesIO(content))
                sha=deploy.digest(stage/'source.tar') if kind!='hash' else '0'*64
                deploy.write_json(stage/'request.json',dict(archive_sha256=sha))
                with self.assertRaises(ValueError):entry.native_bootstrap(['--native-publish',str(stage),str(self.root)])
                self.assertFalse((stage/'operations-helper.py').exists())

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
        with patch.object(deploy, 'support'):
            deploy.export_runtime_report(self.root, bundle)
        self.assertEqual((bundle / 'summary-exits.txt').read_bytes(), content)
        (self.root / deploy.REPORT).write_bytes(b'changed')
        with self.assertRaises(ValueError), patch.object(deploy, 'support'):
            deploy.export_runtime_report(self.root, bundle)

    def test_report_export_owns_source_before_financial_imports(self):
        scripts = self.root / 'backtest'/'inputs'
        scripts.mkdir(parents=True)
        (self.root/'backtest/__init__.py').write_text('')
        (scripts/'__init__.py').write_text('')
        website = self.root/'website'; website.mkdir()
        (website/'__init__.py').write_text('')
        shutil.copy2(ROOT/'website/runtime_access.py', website/'runtime_access.py')
        marker = self.root / 'financial-import'
        (scripts / 'baseline.py').write_text('from pathlib import Path\n'
                'Path(__file__).resolve().parents[2].joinpath("financial-import").write_text("yes")\n'
                'raise RuntimeError("import probe finished")\n')
        code = ('import sys;sys.path.insert(0,sys.argv[1]);from tools.ops import deploy;'
                'deploy.export_runtime_report(sys.argv[3],sys.argv[4])')
        child = None
        try:
            with runtime_access.ownership(self.root, exclusive=True):
                child = subprocess.Popen([sys.executable, '-B', '-c', code, str(ROOT),
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
        website.mkdir(); (website/'server').mkdir(); (website/'__init__.py').write_text(''); (website/'server/__init__.py').write_text('')
        for name in ('serve.py', 'runtime_access.py'):
            shutil.copy2(ROOT / 'website' / name, website / name)
        marker = self.root / 'imported'
        (website / 'server/app.py').write_text('from pathlib import Path\n'
                'Path(__file__).resolve().parents[2].joinpath("imported").write_text("yes")\n'
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
        website.mkdir(); (website/'server').mkdir(); (website/'__init__.py').write_text(''); (website/'server/__init__.py').write_text('')
        for name in ('serve.py', 'runtime_access.py'):
            shutil.copy2(ROOT / 'website' / name, website / name)
        (website / 'server/app.py').write_text('def main(): raise RuntimeError("worker must not run main")\n')
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
