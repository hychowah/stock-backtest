"""The tier runner selects files by tier, isolates each file and reports failures.

Each test copies tests/run.py into a private checkout with synthetic entries;
the copy resolves paths from its own file, so it never sees the real suite.
The copy gets a private home folder, so its run folders stay in scratch.
"""
import importlib.util
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

RUNNER = Path(__file__).resolve().with_name('run.py')

OK = '''import os, sys, tempfile
from pathlib import Path
run = Path(tempfile.gettempdir()).resolve().parent
sys.exit(0 if run.name.startswith('run-') and run.parent == Path(os.environ['EXPECTED_RUNS']) else 1)
'''
BROKEN = 'import sys\nfor n in range(100): print(f"line {n}")\nsys.exit(1)\n'
ORPHAN = '''import subprocess, sys, time
sleep = [sys.executable, '-c', 'import time; time.sleep(60)']
print(f'grouped {subprocess.Popen(sleep).pid}')
print(f'escaped {subprocess.Popen(sleep, start_new_session=True).pid}')
time.sleep(60)
'''


def gone(pid, seconds=5):
    deadline = time.monotonic() + seconds
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def kill(pid):
    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        pass


class TierRunnerTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve() / 'checkout'
        self.home = Path(scratch.name).resolve() / 'home'
        self.runs = self.home / '.cache' / 'ebitda-ev-spread-tests'
        self.tests = self.root / 'tests'
        self.tests.mkdir(parents=True)
        shutil.copy2(RUNNER, self.tests / 'run.py')
        spec = importlib.util.spec_from_file_location('tier_runner_copy', self.tests / 'run.py')
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        for name in self.runner.HEAVY:
            self.write(name, f'print("ran {name}")\n')
        for name in self.runner.NOT_ENTRIES:
            self.write(name, 'process.exit(1);\n' if name.endswith('.cjs') else 'raise SystemExit(1)\n')
        self.write('test_ok.py', OK)
        self.write('test_broken.py', BROKEN)
        self.write('check-ok.cjs', 'console.log("ok");\n')

    def write(self, name, text):
        (self.tests / name).write_text(text, encoding='utf-8')

    def run_tier(self, *arguments):
        environment = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                           EXPECTED_RUNS=str(self.runs))
        return subprocess.run([sys.executable, '-B', str(self.tests / 'run.py'), *arguments],
                              capture_output=True, text=True, timeout=120, env=environment)

    def test_fast_tier_runs_only_fast_entries_in_a_removed_private_folder(self):
        done = self.run_tier('--jobs', '2')
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertRegex(done.stdout, r'(?m)^PASS .*  test_ok\.py$')
        self.assertRegex(done.stdout, r'(?m)^PASS .*  check-ok\.cjs$')
        self.assertRegex(done.stdout, r'(?m)^FAIL .*  test_broken\.py$')
        self.assertRegex(done.stdout, r'(?m)^line 99$')
        self.assertNotRegex(done.stdout, r'(?m)^line 0$')
        for name in self.runner.HEAVY | self.runner.NOT_ENTRIES:
            self.assertNotIn(name, done.stdout)
        self.assertIn('2 passed, 1 failed', done.stdout)
        self.assertIn(f'Not run: {len(self.runner.HEAVY)} heavy files.', done.stdout)
        self.assertEqual(list(self.runs.iterdir()), [])

    def test_heavy_tier_runs_only_heavy_entries(self):
        done = self.run_tier('--tier', 'heavy')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(f'heavy tier: {len(self.runner.HEAVY)} files, 1 at a time', done.stdout)
        passed = set(re.findall(r'(?m)^PASS .*  (\S+)$', done.stdout))
        self.assertEqual(passed, set(self.runner.HEAVY))
        self.assertIn('Not run: 3 fast files.', done.stdout)

    def test_stale_table_name_stops_the_run_before_any_file(self):
        stale = sorted(self.runner.HEAVY)[0]
        (self.tests / stale).unlink()
        done = self.run_tier()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(f'not found: {stale}', done.stderr)
        self.assertNotIn('PASS', done.stdout)

    @unittest.skipUnless(os.name == 'posix', 'POSIX signals')
    def test_termination_kills_running_files_and_removes_the_run_folder(self):
        marker = self.root.parent / 'sleep.pid'
        self.write('test_sleep.py', 'import os, time\nfrom pathlib import Path\n'
                   'Path(os.environ["PID_FILE"]).write_text(str(os.getpid()))\ntime.sleep(60)\n')
        environment = dict(os.environ, HOME=str(self.home), PID_FILE=str(marker))
        runner = subprocess.Popen([sys.executable, '-B', str(self.tests / 'run.py')], env=environment,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(runner.kill)
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        runner.send_signal(signal.SIGTERM)
        output, errors = runner.communicate(timeout=30)
        self.assertEqual(runner.returncode, 130, output + errors)
        self.assertIn('Interrupted;', output)
        self.assertTrue(gone(int(marker.read_text())), 'the running file survived termination')
        self.assertEqual(list(self.runs.iterdir()), [])

    @unittest.skipUnless(Path('/proc/self/environ').exists(), 'Linux process groups and /proc')
    def test_timeout_kills_the_group_and_close_kills_escaped_descendants(self):
        self.write('test_orphan.py', ORPHAN)
        self.runner.RUNS = self.runs
        run = self.runner.Run()
        result = run.execute(self.runner.Entry(self.tests / 'test_orphan.py', 'fast'), 2)
        self.assertEqual(result.status, 'TIMEOUT')
        grouped = int(re.search(r'grouped (\d+)', result.tail).group(1))
        escaped = int(re.search(r'escaped (\d+)', result.tail).group(1))
        self.addCleanup(kill, escaped)
        self.assertTrue(gone(grouped), f'grandchild {grouped} survived the timeout')
        self.assertFalse(gone(escaped, 0.2), 'a new session leaves the group kill')
        self.assertIsNone(run.close())
        self.assertTrue(gone(escaped), f'escaped grandchild {escaped} survived close()')
        self.assertFalse(run.folder.exists())


if __name__ == '__main__':
    unittest.main()
