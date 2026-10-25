"""Synthetic admission checks; never attach the installed runtime or live cache."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
# Common synthetic-suite launchers supply a source fixture. These checks create
# their own source-only roots and must not attach the supplied runtime on import.
if '--runtime' in sys.argv:
    index = sys.argv.index('--runtime')
    del sys.argv[index:index + 2]
sys.path.insert(0, str(ROOT / 'tools'))
import bench_admission as admission
import bench_baseline as baseline
import bench_methods as methods
import bench_candidates_run as candidates
import bench_candidates_process as process
import bench_backtest as historical


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def test_policy_has_no_runtime_environment_or_marker_override(self):
        (self.root / 'data').mkdir()
        (self.root / 'data/deployment.json').write_text(json.dumps(dict(commit='a' * 40)))
        (self.root / 'bound-inputs.json').write_text(json.dumps(dict(sha256='b' * 64)))
        with patch.dict(os.environ, BACKTEST_BASELINE_RUNTIME=str(self.root),
                        BACKTEST_BASELINE_TOOL_SHA256=baseline._loaded_tool_sha256):
            with self.assertRaisesRegex(admission.BenchmarkAdmissionError, 'bound input ownership'):
                admission.require_execution()

    def test_direct_execution_boundaries_reject_before_effects(self):
        args = SimpleNamespace(runtime=self.root, workdir=self.root / 'output')
        boundaries = {
            'baseline runner': lambda: baseline.runner(args),
            'baseline request': lambda: baseline.request(None, None, None, None),
            'methods CLI': methods.main,
            'methods request': lambda: methods.run_request(None, None, None, None),
            'candidate parent': lambda: candidates.parent(args),
            'candidate worker': lambda: candidates.worker(args),
            'candidate child launch': lambda: candidates.run_isolated(None, None, None, None),
            'candidate request': lambda: candidates.run_candidate(
                None, None, None, None, None, freshness=None, budget_seconds=1.),
            'historical CLI': historical.main,
            'historical worker': lambda: historical.worker(args),
        }
        with ExitStack() as stack:
            # A missing guard must fail this test before it can touch any cache,
            # produce output, start work, or wait for a worker handshake.
            blocked = Mock(side_effect=AssertionError('Execution crossed admission.'))
            for module, name in ((baseline, 'bootstrap'), (baseline, 'publish'),
                                 (baseline, 'Resources'), (baseline, 'Delivery'),
                                 (methods, 'Model'), (candidates, 'BatchModel'),
                                 (candidates, 'emit'), (process, 'OwnedProcess')):
                stack.enter_context(patch.object(module, name, blocked))
            stack.enter_context(patch.object(baseline, 'coordinator', SimpleNamespace(access=blocked)))
            stack.enter_context(patch.object(baseline, 's', SimpleNamespace(
                connect=blocked, prepare=blocked,
                r=SimpleNamespace(connect=blocked, prepare=blocked))))
            stack.enter_context(patch.object(baseline.sqlite3, 'connect', blocked))
            stack.enter_context(patch.object(baseline.subprocess, 'Popen', blocked))
            stack.enter_context(patch.object(candidates.sys, 'stdin', SimpleNamespace(readline=blocked)))
            stack.enter_context(patch.object(Path, 'mkdir', blocked))
            stack.enter_context(patch.object(Path, 'open', blocked))
            for label, invoke in boundaries.items():
                with self.subTest(boundary=label):
                    argv = ['bench_methods.py', '--runtime', str(self.root),
                            '--workdir', str(self.root / 'output')]
                    if label == 'historical CLI':
                        argv = ['bench_backtest.py']
                    with patch.object(sys, 'argv', argv), self.assertRaises(admission.BenchmarkAdmissionError):
                        invoke()
            blocked.assert_not_called()
        self.assertFalse((self.root / 'output').exists())

    def test_unpatched_clis_reject_without_creating_work_or_worker_ready_event(self):
        workdir = self.root / 'output'
        runtime = self.root / 'not-an-installed-runtime'
        common = ['--runtime', str(runtime), '--workdir', str(workdir)]
        commands = [('bench_baseline.py', [command, *common, '--manifest', str(self.root / 'manifest.json')])
                    for command in ('freeze', 'run', 'verify')]
        commands += [('bench_methods.py', common), ('bench_candidates_run.py', common),
                     ('bench_candidates_run.py', [*common, '--worker', 'python']),
                     ('bench_backtest.py', ['--workdir', str(workdir)]),
                     ('bench_backtest.py', ['--worker', '--workdir', str(workdir)])]
        environment = dict(os.environ)
        for key in ('BACKTEST_BASELINE_RUNTIME', 'BACKTEST_BASELINE_TOOL_SHA256'):
            environment.pop(key, None)
        for tool, arguments in commands:
            with self.subTest(tool=tool, arguments=arguments):
                result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools' / tool), *arguments],
                                        input='', text=True, capture_output=True, env=environment,
                                        timeout=20, cwd=self.root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('BenchmarkAdmissionError', result.stderr)
                self.assertIn('resource/availability admission', result.stderr)
                self.assertNotIn('worker_ready', result.stdout)
                self.assertEqual(result.stdout, '')
                self.assertFalse(workdir.exists())
                self.assertFalse(runtime.exists())

    def test_source_only_attachment_and_spawn_import_do_not_admit_execution(self):
        fixture = self.root / 'source-only'
        (fixture / 'scripts').mkdir(parents=True)
        (fixture / 'website').mkdir()
        for source in (ROOT / 'scripts').glob('*.py'):
            shutil.copy2(source, fixture / 'scripts' / source.name)
        shutil.copy2(ROOT / 'website/runtime_access.py', fixture / 'website/runtime_access.py')
        environment = dict(os.environ)
        for key in ('BACKTEST_BASELINE_RUNTIME', 'BACKTEST_BASELINE_TOOL_SHA256'):
            environment.pop(key, None)
        code = '''import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import bench_baseline as baseline
baseline.bootstrap(pathlib.Path(sys.argv[2]))
import bench_methods
assert baseline.s is not None
assert not (pathlib.Path(sys.argv[2]) / 'data/website-data-0.lock').exists()
try:
    baseline.request(None, None, None, None)
except baseline.admission.BenchmarkAdmissionError:
    pass
else:
    raise AssertionError('Source attachment admitted execution.')
print(json.dumps(dict(attached=True, execution_admitted=False)))
'''
        for spawned_import in (False, True):
            with self.subTest(spawned_import=spawned_import):
                if spawned_import:
                    environment['BACKTEST_BASELINE_RUNTIME'] = str(fixture)
                    environment['BACKTEST_BASELINE_TOOL_SHA256'] = baseline._loaded_tool_sha256
                result = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT / 'tools'), str(fixture)],
                                        text=True, capture_output=True, env=environment,
                                        timeout=20, cwd=self.root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), dict(attached=True, execution_admitted=False))
        self.assertTrue((fixture / 'data/website-source.lock').exists())
        self.assertFalse((fixture / 'data/website-data-0.lock').exists())
        self.assertFalse((fixture / 'raw').exists())


if __name__ == '__main__':
    unittest.main()
