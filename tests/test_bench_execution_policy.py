"""Owned source-only policy fixtures. No real capture, raw cache or requests."""
import json
import logging
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if '--runtime' in sys.argv:
    index = sys.argv.index('--runtime'); del sys.argv[index:index + 2]
sys.path.insert(0, str(ROOT / 'tools'))
import bench_execution_policy as policy
import bench_input_artifacts as artifacts
import test_bench_execution_inputs as workspace_tests

# CB-08 calendar adapters change the schedules.py whole-source identity.
# Financial expression/code digests below remain bound to the same calculations.
SIGNATURE = 'a81afa42775313a181ea49685492931852f99caaee8463f1c9e9ebcba3b94e98'


class PolicyTests(unittest.TestCase):
    setUp = workspace_tests.WorkspaceTests.setUp
    owner = workspace_tests.WorkspaceTests.owner
    write_manifest = workspace_tests.WorkspaceTests.write_manifest
    immutable_bytes = workspace_tests.WorkspaceTests.immutable_bytes

    def assert_reason(self, reason, invoke):
        with self.assertRaises(policy.ExecutionPolicyError) as caught:
            invoke()
        self.assertEqual(caught.exception.reason, reason)

    def rewrite_source(self, name, text):
        path = self.source / name
        path.write_text(text, encoding='utf-8')
        self.sources[name] = workspace_tests.sha(path)
        self.manifest['originals']['sources'] = self.sources
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(self.capture / 'research.sqlite')) as research, closing(sqlite3.connect(self.capture / 'schedules.sqlite')) as daily:
            self.identity = workspace_tests.semantic(research, daily, self.sources)
        self.manifest['financial_generation'] = self.identity
        self.write_manifest()

    def test_actual_program_exact_identity_private_paths_and_retained_evidence(self):
        original = self.immutable_bytes()
        with self.owner() as inputs:
            with policy.CapturedPolicy(inputs) as attached:
                binding = attached.binding
                self.assertEqual(binding['policy_signature'], SIGNATURE)
                self.assertEqual(attached._program_evidence, dict(signature=SIGNATURE,
                    expressions='e87697c7a3be20577458f42be862bc19205bb99f3c8c74ccb0a8a67900d78239',
                    python='8e5074d34ac0173866122f0cc4545f3298ea2e6249108d1eae92ddab36c98ec2',
                    decisions='596019cf3fcb9a65fe453b88e46e7a4998e5859e08189caafe72f80acc5be2ab',
                    statuses=['Scheduled exit', 'Marked to date', 'Last available price', 'Bankruptcy'],
                    sources={Path(name).name: sha for name, sha in binding['policy_sources'].items()},
                    constants=[100000000, 50000000, 250, 800], bankruptcy=[]))
                self.assertEqual(binding['financial_generation'], inputs.identity)
                self.assertEqual(binding['capture_id'], inputs.capture_id)
                self.assertEqual(set(binding['policy_sources']), {'scripts/' + n + '.py' for n in
                    ('books', 'metrics', 'research', 'revalue', 'run', 'schedules')})
                self.assertTrue(all(self.sources[name] == sha for name, sha in binding['policy_sources'].items()))
                with self.assertRaises(TypeError): binding['policy_signature'] = 'changed'
                with self.assertRaises(TypeError): binding['policy_sources']['scripts/books.py'] = 'changed'
                folder = attached._folder
                self.assertIsNone(attached._owned.process.poll())
                self.assertTrue(folder.is_relative_to(inputs._folder))
                self.assertFalse((inputs.source_snapshot / 'raw').exists())
                self.assertFalse((inputs.source_snapshot / 'data').exists())
            self.assertEqual(attached.exit_code, 0)
            self.assertFalse(attached._owned.reader.is_alive())
            self.assert_reason('inactive', lambda: attached.binding)
            record = json.loads((folder / 'attempt.json').read_bytes())
            self.assertEqual(record['status'], 'complete')
            self.assertEqual(record['exit_code'], 0)
            self.assertEqual(record['current_raw_freshness'], 'unavailable')
        self.assertEqual(original, self.immutable_bytes())
        self.output.rename(self.root / 'closed-output')
        self.capture.rename(self.root / 'closed-capture')

    def test_ambient_parent_state_and_attachment_environment_do_not_contaminate(self):
        logger = logging.getLogger('backtest')
        before = (list(sys.path), dict(sys.modules), logger.level, logger.propagate, list(logger.handlers))
        with patch.dict(sys.modules, schedules=object(), research=object()), patch.dict(os.environ,
             BACKTEST_BASELINE_RUNTIME=str(self.root / 'forbidden'), BACKTEST_BASELINE_TOOL_SHA256='bad',
             BACKTEST_BASELINE_TELEMETRY=str(self.root / 'forbidden'), PYTHONPATH=str(self.root / 'forbidden')):
            with self.owner() as inputs, policy.CapturedPolicy(inputs) as attached:
                self.assertEqual(attached.binding['policy_signature'], SIGNATURE)
        self.assertEqual(sys.path, before[0])
        self.assertEqual(logger.level, before[2]); self.assertEqual(logger.propagate, before[3])
        self.assertEqual(logger.handlers, before[4])
        self.assertEqual({k: sys.modules.get(k) for k in before[1]}, before[1])
        self.assertNotIn('numpy', sys.modules)
        self.assertFalse((self.root / 'forbidden').exists())

    def test_outer_workspace_closes_escaped_policy_before_ownership_release(self):
        with self.owner() as inputs:
            attached = policy.CapturedPolicy(inputs).__enter__()
            pid = attached._owned.process.pid
            folder = attached._folder
        self.assertEqual(attached.exit_code, 0)
        self.assertFalse(attached._owned.reader.is_alive())
        self.assertIsNotNone(attached._owned.process.poll())
        self.assert_reason('inactive', lambda: attached.binding)
        attached.__exit__(None, None, None)
        folder.rename(folder.with_name('closed-policy'))
        with self.owner(): pass
        self.assertGreater(pid, 0)

    def test_single_child_per_workspace_and_reuse_after_close(self):
        with self.owner() as inputs:
            with policy.CapturedPolicy(inputs):
                self.assert_reason('inactive', policy.CapturedPolicy(inputs).__enter__)
            with policy.CapturedPolicy(inputs) as again:
                self.assertEqual(again.binding['policy_signature'], SIGNATURE)
        self.assert_reason('inactive', policy.CapturedPolicy(inputs).__enter__)
        self.assert_reason('unsupported', lambda: policy.CapturedPolicy(object()))

    def test_caller_exception_identity_and_sanitized_failure_record(self):
        for error in (RuntimeError('private secret text'), FileNotFoundError('private path')):
            with self.owner() as inputs:
                attached = policy.CapturedPolicy(inputs)
                with self.assertRaises(type(error)) as caught:
                    with attached: raise error
                self.assertIs(caught.exception, error)
                record = (attached._folder / 'attempt.json').read_text()
                self.assertNotIn('private', record)
                self.assertEqual(json.loads(record)['reason'], 'unexpected')
                attached.close()
                self.assert_reason('inactive', attached.__enter__)

    def test_no_database_raw_network_or_descendant_effect_from_source(self):
        external = self.root / 'outside-source.txt'; external.write_text('owned fixture content')
        attempts = (f"from pathlib import Path\nPath({str(external)!r}).read_bytes()\n",
                    "import sqlite3\nsqlite3.connect(':memory:')\n",
                    "from pathlib import Path\n(Path(__file__).parents[1]/'raw'/'blocked').read_bytes()\n",
                    "import socket\nsocket.socket().connect(('127.0.0.1',1))\n",
                    "import subprocess\nsubprocess.Popen(['unavailable'])\n")
        original = (self.source / 'scripts/metrics.py').read_text()
        for attempt in attempts:
            self.rewrite_source('scripts/metrics.py', original + '\n' + attempt)
            with self.owner() as inputs:
                attached = policy.CapturedPolicy(inputs)
                self.assert_reason('unsupported', attached.__enter__)
                self.assertIsNotNone(attached._owned.process.poll())
                self.assertFalse(attached._owned.reader.is_alive())
                self.assertNotIn('blocked', (attached._folder / 'attempt.json').read_text())

    def test_changed_or_missing_snapshot_rejects_without_child(self):
        for change in ('changed', 'missing'):
            with self.owner() as inputs:
                path = inputs.source_snapshot / 'scripts/books.py'
                if change == 'changed': path.write_bytes(b'# changed')
                else: path.unlink()
                with patch.object(policy, 'OwnedProcess') as spawn:
                    self.assert_reason('mismatch' if change == 'changed' else 'incomplete', policy.CapturedPolicy(inputs).__enter__)
                    spawn.assert_not_called()

    def test_actual_source_mutation_changes_policy_not_metadata(self):
        original = (self.source / 'scripts/books.py').read_text()
        self.rewrite_source('scripts/books.py', original.replace('cap>0 and ev>0', 'cap>1 and ev>0'))
        with self.owner() as inputs, policy.CapturedPolicy(inputs) as attached:
            self.assertNotEqual(attached.binding['policy_signature'], SIGNATURE)
            self.assertEqual(attached.binding['financial_generation'], inputs.identity)
            self.assertEqual(inputs.captured_freshness, self.freshness)

    def test_cancelled_attachment_closes_owned_child(self):
        cancelled = [False]
        with self.owner(cancel=lambda: cancelled[0]) as inputs:
            attached = policy.CapturedPolicy(inputs)
            actual = policy.OwnedProcess
            def spawn(*args, **kwargs):
                owned = actual(*args, **kwargs)
                cancelled[0] = True
                return owned
            with patch.object(policy, 'OwnedProcess', spawn):
                self.assert_reason('cancelled', attached.__enter__)
            cancelled[0] = False
            self.assertIsNotNone(attached._owned.process.poll())
            self.assertFalse(attached._owned.reader.is_alive())
            self.assertEqual(json.loads((attached._folder / 'attempt.json').read_bytes())['reason'], 'cancelled')

    def test_timeout_closes_owned_child_and_preserves_evidence(self):
        with self.owner() as inputs:
            attached = policy.CapturedPolicy(inputs)
            with patch.object(policy, 'MAX_ATTACH_SECONDS', 0.):
                self.assert_reason('limit', attached.__enter__)
            self.assertIsNotNone(attached._owned.process.poll())
            self.assertFalse(attached._owned.reader.is_alive())
            self.assertEqual(json.loads((attached._folder / 'attempt.json').read_bytes())['reason'], 'limit')

    def test_memory_limit_and_child_exit_invalidate_binding(self):
        with self.owner() as inputs:
            attached = policy.CapturedPolicy(inputs)
            with patch.object(policy, '_memory', return_value=policy.MAX_CHILD_MEMORY + 1):
                self.assert_reason('limit', attached.__enter__)
            self.assertIsNotNone(attached._owned.process.poll())
            with policy.CapturedPolicy(inputs) as live:
                live._owned.terminate()
                self.assert_reason('child_failed', lambda: live.binding)
                # Exit failure is also reported by the owner; avoid a second exception here.
                live.close(RuntimeError('owned test termination'))

    def test_malformed_or_mismatched_binding_and_protocol_reject(self):
        with self.owner() as inputs:
            for event in ({'event': 'worker_log', 'text': 'private body'},
                {'event': 'failed', 'reason': 'not allowed'},
                {'event': 'failed', 'reason': 'unsupported'}, ['malformed']):
                attached = policy.CapturedPolicy(inputs)
                with patch.object(policy.CapturedPolicy, '_monitor', return_value=event):
                    self.assert_reason('protocol', attached.__enter__)
            with policy.CapturedPolicy(inputs) as good:
                binding = json.loads(artifacts.encoded({k: dict(v) if hasattr(v, 'items') else v for k, v in good.binding.items()}))
                request = good._request
                for key in ('capture_id', 'financial_generation', 'identity'):
                    changed = dict(binding, **{key: 'bad'})
                    self.assert_reason('mismatch', lambda: policy._validate_binding(changed, request))
                self.assert_reason('protocol', lambda: policy._validate_binding({}, request))

    def test_child_failure_is_sanitized_and_contained(self):
        original = (self.source / 'scripts/metrics.py').read_text()
        self.rewrite_source('scripts/metrics.py', original + "\nraise RuntimeError('private child exception')\n")
        with self.owner() as inputs:
            attached = policy.CapturedPolicy(inputs)
            self.assert_reason('child_failed', attached.__enter__)
            self.assertIsNotNone(attached._owned.process.poll())
            self.assertFalse(attached._owned.reader.is_alive())
            record = (attached._folder / 'attempt.json').read_text()
            self.assertNotIn('private', record)
            attached._folder.rename(attached._folder.with_name('closed-failed-policy'))

    def test_support_changes_reject_at_close_and_record_failure(self):
        with self.owner() as inputs:
            attached = policy.CapturedPolicy(inputs).__enter__()
            (attached._folder / 'tools/bench_policy_program.py').write_text('# changed')
            self.assert_reason('mismatch', attached.close)
            self.assertEqual(attached.exit_code, 0)
            self.assertFalse(attached._owned.reader.is_alive())
            self.assertEqual(json.loads((attached._folder / 'attempt.json').read_bytes())['reason'], 'mismatch')

    def assert_closed(self, attached):
        self.assertTrue(attached._closed)
        self.assertIsNotNone(attached._owned.process.poll())
        self.assertFalse(attached._owned.reader.is_alive())
        self.assertTrue(all(stream is None or stream.closed for stream in
            (attached._owned.process.stdin, attached._owned.process.stdout)))
        self.assertIsNone(attached._owned.job)
        self.assertNotIn('policy', attached._inputs._attachments)

    def test_stop_publication_failure_still_terminates_reaps_and_closes(self):
        failure = PermissionError('private stop path')
        with self.owner() as inputs:
            attached = policy.CapturedPolicy(inputs).__enter__()
            with patch.object(Path, 'touch', side_effect=failure), \
                 patch.object(attached._owned, 'terminate', wraps=attached._owned.terminate) as terminate:
                with self.assertRaises(PermissionError) as caught:
                    attached.close()
            self.assertIs(caught.exception, failure)
            terminate.assert_called_once()
            self.assert_closed(attached)
            record = (attached._folder / 'attempt.json').read_text()
            self.assertNotIn('private', record)
            self.assertEqual(json.loads(record)['status'], 'failed')
            with policy.CapturedPolicy(inputs): pass

    def test_evidence_publication_failure_occurs_after_confirmed_closure(self):
        failure = PermissionError('private evidence path')
        with self.owner() as inputs:
            attached = policy.CapturedPolicy(inputs).__enter__()
            write = Path.write_bytes
            def fail_evidence(path, data):
                if path == attached._folder / 'attempt.json':
                    self.assert_closed(attached)
                    raise failure
                return write(path, data)
            with patch.object(Path, 'write_bytes', fail_evidence):
                with self.assertRaises(PermissionError) as caught:
                    attached.close()
            self.assertIs(caught.exception, failure)
            self.assert_closed(attached)
            attached.close()
            with policy.CapturedPolicy(inputs): pass

    def test_intermediate_handle_cleanup_failure_retries_same_owner(self):
        failure = OSError('private handle failure')
        with self.owner() as inputs:
            attached = policy.CapturedPolicy(inputs).__enter__()
            close_handles = attached._owned._close_handles
            attempts = []
            def close_after_failure():
                attempts.append(None)
                if len(attempts) == 1:
                    self.assertIsNotNone(attached._owned.process.poll())
                    self.assertFalse(attached._owned.reader.is_alive())
                    raise failure
                close_handles()
            with patch.object(attached._owned, '_close_handles', close_after_failure):
                with self.assertRaises(OSError) as caught:
                    attached.close()
            self.assertIs(caught.exception, failure)
            self.assertEqual(len(attempts), 2)
            self.assert_closed(attached)

    def test_caller_exception_identity_survives_evidence_failure(self):
        caller = RuntimeError('private caller exception')
        with self.owner() as inputs:
            attached = policy.CapturedPolicy(inputs)
            write = Path.write_bytes
            def fail_closed_evidence(path, data):
                if attached._closed and path == attached._folder / 'attempt.json':
                    raise PermissionError('private evidence')
                return write(path, data)
            with patch.object(Path, 'write_bytes', fail_closed_evidence):
                with self.assertRaises(RuntimeError) as caught:
                    with attached: raise caller
            self.assertIs(caught.exception, caller)
            self.assert_closed(attached)

    def test_unconfirmed_policy_close_keeps_registration_until_retry(self):
        failure = OSError('private cleanup failure')
        with self.owner() as inputs:
            attached = policy.CapturedPolicy(inputs).__enter__()
            try:
                with patch.object(Path, 'touch', side_effect=failure), \
                     patch.object(attached._owned, 'terminate', side_effect=failure), \
                     patch.object(attached._owned, 'close', side_effect=failure):
                    with self.assertRaises(OSError) as caught:
                        attached.close()
                self.assertIs(caught.exception, failure)
                self.assertFalse(attached._closed)
                self.assertIn('policy', inputs._attachments)
                self.assertIsNone(attached._owned.process.poll())
                self.assertTrue(attached._owned.reader.is_alive())
                self.assert_reason('inactive', lambda: attached.binding)
                self.assert_reason('inactive', policy.CapturedPolicy(inputs).__enter__)
                self.assertEqual(json.loads((attached._folder / 'attempt.json').read_bytes())['status'],
                                 'closure_pending')
            finally:
                attached.close()
            self.assert_closed(attached)

    def test_outer_exit_retains_workspace_when_child_cleanup_is_unconfirmed(self):
        execution = workspace_tests.execution
        failure = OSError('private cleanup failure')
        inputs = self.owner().__enter__()
        attached = policy.CapturedPolicy(inputs).__enter__()
        try:
            with patch.object(Path, 'touch', side_effect=failure), \
                 patch.object(attached._owned, 'terminate', side_effect=failure), \
                 patch.object(attached._owned, 'close', side_effect=failure):
                with self.assertRaises(OSError) as caught:
                    inputs.__exit__(None, None, None)
            self.assertIs(caught.exception, failure)
            self.assertIs(execution._pending_closures[id(inputs)], inputs)
            self.assertTrue(inputs._thread_lock.locked())
            self.assertFalse(inputs._active)
            self.assertIn('policy', inputs._attachments)
            self.assertFalse(attached._closed)
            self.assertEqual(tuple(inputs.daily.execute('SELECT 1').fetchone()), (1,))
            with self.assertRaises(execution.ExecutionInputError) as busy:
                self.owner().__enter__()
            self.assertEqual(busy.exception.reason, 'busy')
        finally:
            inputs.__exit__(None, None, None)
        self.assert_closed(attached)
        self.assertNotIn(id(inputs), execution._pending_closures)

    def test_attachment_exception_keeps_registration_when_cleanup_fails(self):
        execution = workspace_tests.execution
        original = RuntimeError('private attachment failure')
        cleanup = OSError('private cleanup failure')
        inputs = self.owner()
        attached = policy.CapturedPolicy(inputs)
        try:
            with patch.object(policy.CapturedPolicy, '_monitor', side_effect=original), \
                 patch.object(Path, 'touch', side_effect=cleanup), \
                 patch.object(policy.OwnedProcess, 'terminate', side_effect=cleanup), \
                 patch.object(policy.OwnedProcess, 'close', side_effect=cleanup):
                with self.assertRaises(RuntimeError) as caught:
                    with inputs:
                        attached.__enter__()
            self.assertIs(caught.exception, original)
            self.assertFalse(attached._closed)
            self.assertIn('policy', inputs._attachments)
            self.assertIs(execution._pending_closures[id(inputs)], inputs)
            self.assertTrue(inputs._thread_lock.locked())
        finally:
            if inputs._thread_lock.locked():
                inputs.__exit__(None, None, None)
        self.assert_closed(attached)
        self.assertNotIn(id(inputs), execution._pending_closures)
        self.assertFalse(inputs._thread_lock.locked())
        with self.owner(): pass

    def test_caller_exception_identity_survives_unconfirmed_inner_and_outer_close(self):
        execution = workspace_tests.execution
        caller = RuntimeError('private caller exception')
        cleanup = OSError('private cleanup failure')
        inputs = self.owner()
        attached = policy.CapturedPolicy(inputs)
        try:
            with patch.object(Path, 'touch', side_effect=cleanup), \
                 patch.object(policy.OwnedProcess, 'terminate', side_effect=cleanup), \
                 patch.object(policy.OwnedProcess, 'close', side_effect=cleanup):
                with self.assertRaises(RuntimeError) as caught:
                    with inputs:
                        with attached: raise caller
            self.assertIs(caught.exception, caller)
            self.assertFalse(attached._closed)
            self.assertIn('policy', inputs._attachments)
            self.assertIs(execution._pending_closures[id(inputs)], inputs)
            self.assertTrue(inputs._thread_lock.locked())
            self.assertIsNone(attached._owned.process.poll())
            self.assertNotIn('private', (attached._folder / 'attempt.json').read_text())
        finally:
            if inputs._thread_lock.locked():
                inputs.__exit__(None, None, None)
        self.assert_closed(attached)
        self.assertNotIn(id(inputs), execution._pending_closures)

    def test_pending_workspace_survives_collection_for_explicit_retry(self):
        import gc
        import weakref
        execution = workspace_tests.execution
        inputs = self.owner().__enter__()
        attached = policy.CapturedPolicy(inputs).__enter__()
        inputs_ref, attached_ref = weakref.ref(inputs), weakref.ref(attached)
        try:
            failure = OSError('private cleanup failure')
            with patch.object(Path, 'touch', side_effect=failure), \
                 patch.object(attached._owned, 'terminate', side_effect=failure), \
                 patch.object(attached._owned, 'close', side_effect=failure):
                with self.assertRaises(OSError):
                    inputs.__exit__(None, None, None)
            del inputs, attached, failure
            gc.collect()
            self.assertIsNotNone(inputs_ref())
            self.assertIsNotNone(attached_ref())
            self.assertIs(execution._pending_closures[id(inputs_ref())], inputs_ref())
            self.assertTrue(inputs_ref()._thread_lock.locked())
        finally:
            if inputs_ref() is not None:
                inputs_ref().__exit__(None, None, None)
        self.assertFalse(execution._pending_closures)
        with self.owner(): pass

    def test_missing_ambiguous_and_escaped_dependencies_reuse_owner_rejection(self):
        # The source-content owner rejects these before source-only attachment.
        import bench_execution_inputs as execution
        for change in ('missing', 'ambiguous', 'escaped'):
            with self.subTest(change=change):
                if change == 'missing':
                    saved = self.manifest['originals']['sources'].pop('scripts/books.py')
                    self.write_manifest()
                elif change == 'ambiguous':
                    self.rewrite_source('website/books.py', '# ambiguous duplicate')
                else:
                    self.manifest['originals']['sources']['scripts/../escape.py'] = 'a' * 64
                    self.write_manifest()
                try:
                    with self.assertRaises(execution.ExecutionInputError):
                        with self.owner() as inputs:
                            policy.CapturedPolicy(inputs).__enter__()
                finally:
                    if change == 'missing': self.manifest['originals']['sources']['scripts/books.py'] = saved
                    elif change == 'ambiguous':
                        (self.source / 'website/books.py').unlink()
                        self.sources.pop('website/books.py')
                        self.manifest['originals']['sources'] = self.sources
                        from contextlib import closing
                        import sqlite3
                        with closing(sqlite3.connect(self.capture / 'research.sqlite')) as research, closing(sqlite3.connect(self.capture / 'schedules.sqlite')) as daily:
                            self.manifest['financial_generation'] = workspace_tests.semantic(research, daily, self.sources)
                    else:self.manifest['originals']['sources'].pop('scripts/../escape.py')
                    self.write_manifest()

    def test_closed_admission_unchanged(self):
        import bench_admission
        with self.owner() as inputs, policy.CapturedPolicy(inputs):
            with self.assertRaises(bench_admission.BenchmarkAdmissionError):
                bench_admission.require_execution()


class MonitorTests(unittest.TestCase):
    def owner(self, polls, events):
        value = object.__new__(policy.CapturedPolicy)
        value._check = lambda: None
        value.exit_code = None
        process = Mock(pid=1)
        process.poll.side_effect = polls
        value._owned = Mock(process=process)
        value._owned.event.side_effect = events
        return value

    def test_eof_before_exit_does_not_lose_exit_code_or_wait_forever(self):
        attached = self.owner([None, None, 0], [None, {}, {}])
        with patch.object(policy, '_memory', return_value=1):
            with self.assertRaises(policy.ExecutionPolicyError) as caught:
                attached._monitor()
        self.assertEqual(caught.exception.reason, 'child_failed')
        self.assertEqual(attached.exit_code, 0)
        self.assertEqual(attached._owned.process.poll.call_count, 3)

    def test_exit_before_eof_drains_queue_and_retains_exit_code(self):
        attached = self.owner([7, 7], [{}, None])
        with self.assertRaises(policy.ExecutionPolicyError) as caught:
            attached._monitor()
        self.assertEqual(caught.exception.reason, 'child_failed')
        self.assertEqual(attached.exit_code, 7)
        self.assertEqual(attached._owned.process.poll.call_count, 2)


if __name__ == '__main__':
    unittest.main()
