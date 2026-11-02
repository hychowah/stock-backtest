"""Private native real-entry containment gate through public scalar admission."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import json
import os
import subprocess
import unittest
from unittest.mock import patch

from guarded_numerical_entries import install, translated

ROOT = Path(__file__).resolve().parents[1]


class CommandTests(unittest.TestCase):
    def test_only_exact_entries_are_translated_and_arguments_preserved(self):
        for name in ('runtime_child.py', 'trial_worker.py'):
            entry = ROOT/'backtest/engines/numerical'/name
            original = [sys.executable, '-I', '-B', str(entry), 'private-launch.json', 'handle', '123']
            result = translated(original, ROOT)
            self.assertEqual(result[:4], [sys.executable, '-I', '-B', '-c'])
            self.assertEqual(result[5:], original[4:])
            self.assertIn("run_name='__main__'", result[4])
            self.assertIn('sys.argv[0]=', result[4])
            self.assertNotIn('sys.path.insert', result[4])
            self.assertIn("['install']", result[4])
            self.assertNotIn('backtest.', result[4])
        command = [sys.executable, '-I', '-c', 'pass']
        self.assertEqual(translated(command, ROOT), command)

    def test_unrecognized_scripts_and_flags_are_rejected_without_execution(self):
        for command in ([sys.executable, '-I', '-B', str(ROOT/'tests/test_queue.py'), 'x'],
                        [sys.executable, '-B', str(ROOT/'backtest/engines/numerical/runtime_child.py'), 'x'],
                        ['other-python', '-c', 'pass']):
            with self.assertRaises(ValueError):
                translated(command, ROOT)


class NativeEntryGate(unittest.TestCase):
    def setUp(self):
        self.assertEqual(sys.platform, 'win32', 'Select this gate only in the guarded native procedure.')
        self.original = subprocess.Popen
        original_null = os.devnull
        install(ROOT)
        self.addCleanup(setattr, subprocess, 'Popen', self.original)
        self.addCleanup(setattr, os, 'devnull', original_null)

    def test_real_runtime_scalar_worker_and_retirement_keep_guard_and_containment(self):
        import test_numerical_scalar_process as process
        from backtest.engines.numerical.runtime import RuntimeProcess
        fixture = process.ScalarCandidateTests('test_actual_candidate_child_transfers_codec2_all_modes_and_closes_before_result')
        fixture.setUp()
        output = []
        created = []
        ordinary_created = RuntimeProcess._created
        class ObservedOutput:
            def __init__(self, stream): self.stream = stream
            def __getattr__(self, name): return getattr(self.stream, name)
            def readline(self, size):
                try:
                    value = self.stream.readline(size)
                except BaseException as error:
                    output.append(dict(read_error=type(error).__name__, errno=getattr(error,'errno',None)))
                    raise
                # Exact private synthetic startup only. Bound the test receipt.
                if len(output)<24: output.append(dict(line=value[:2048]))
                return value
        def observed_created(owner):
            ordinary_created(owner)
            owner.process.stdout = ObservedOutput(owner.process.stdout)
        try:
            owner, created = fixture.candidate()
            import io
            from backtest import result_evidence
            with patch.object(RuntimeProcess, '_created', observed_created):
                stream = io.BytesIO()
                owner.calculate_into('random', fixture.options(trials=2, seed=42), stream, None,
                    lambda value: None, **process.LIMITS)
            reader = result_evidence.open_reader(stream, **process.LIMITS)
            self.assertEqual(reader.format_version, 2)
            self.assertGreater(reader.manifest['holdings'], 0)
            self.assertIsNone(owner.runtime)
            closure = created[-1].closure()
            self.assertEqual(closure['state'], 'closed')
            self.assertTrue(closure['process']['closed'])
            for field in ('eof', 'reader_stopped', 'streams_closed', 'descendants_empty', 'native_handles_released'):
                self.assertTrue(closure['process'][field], field)
            self.assertEqual(closure['process']['descendant_scope'], 'job')
            stages = [row['stage'] for row in created[-1].diagnostics]
            self.assertLess(stages.index('source-owned'), stages.index('financial-owned'))
            self.assertLess(stages.index('financial-owned'), stages.index('session-import'))
            private = ROOT.parent
            children = [json.loads(line) for line in (private/'logs/children.jsonl').read_text().splitlines()]
            relevant = [row for row in children if any('private_numerical_entries' in item for item in row['command'])]
            self.assertGreaterEqual(len(relevant), 2)
            for row in relevant:
                code = row['command'][row['command'].index('-c')+1]
                self.assertTrue(code.startswith('import runpy; runpy.run_path('))
                self.assertIn("run_name='_private_native_guard'", code)
            self.assertFalse((private/'logs/denials.jsonl').exists())
            sinks = list((private/'logs').glob('native-discard-*.bin'))
            self.assertTrue(sinks)
            self.assertLess(sum(path.stat().st_size for path in sinks), 65536)
        finally:
            (ROOT.parent/'logs/native-entry-gate-runtime.json').write_text(json.dumps(dict(
                raw_output=output, runtimes=[dict(state=value.state, diagnostics=value.diagnostics,
                closure=value.closure(), last_stats=value.last_stats) for value in created]),indent=2))
            self.assertTrue(fixture.doCleanups())


if __name__ == '__main__':
    unittest.main()
