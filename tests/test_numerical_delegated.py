"""Synthetic exact-generation attachment, pin races and worker lifetime."""
from contextlib import closing
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_numerical_generation as fixtures
import numerical_generation as ng
import numpy as np


class DelegatedTests(unittest.TestCase):
    setUp = fixtures.GenerationTests.setUp
    prepare = fixtures.GenerationTests.prepare
    attach = fixtures.GenerationTests.attach
    advance = fixtures.GenerationTests.advance

    def reference(self):
        self.prepare()
        parent = self.attach()
        with self.owner.hold(): reference = parent.worker_reference()
        return parent, reference

    def delegated(self, reference, checkpoint=lambda: None):
        inputs = ng.open_delegated(reference, self.s, checkpoint=checkpoint)
        self.addCleanup(inputs.close)
        return inputs

    def unpinned(self, identity):
        with self.store._gate(identity, exclusive=True): pass

    def wait_for(self, path, process=None):
        deadline = time.monotonic() + 40
        while not path.exists():
            if process is not None and process.poll() is not None:
                self.fail('Reader exited before its barrier: ' + str(process.returncode))
            if time.monotonic() > deadline: self.fail('Reader barrier timed out: ' + path.name)
            time.sleep(.02)

    def spawn(self, reference, mode='reader'):
        ref = self.root / 'reference.json'; ref.write_text(json.dumps(reference))
        ready, stop, done = (self.root / name for name in ('ready', 'stop', 'done'))
        process = subprocess.Popen([sys.executable, '-B', str(fixtures.ROOT / 'tests' /
            'numerical_delegated_fixture.py'), mode, str(ref), str(ready), str(stop), str(done)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cleanup():
            stop.touch()
            try: process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate(timeout=10)
        self.addCleanup(cleanup)
        self.wait_for(ready, process)
        return process, ready, stop, done

    def test_exact_readonly_interface_without_financial_or_current_input_work(self):
        parent, reference = self.reference()
        forbidden = AssertionError('Worker acquired coordinator or inspected current inputs')
        with self.owner.hold(), patch.object(ng.cache_access.WorkspaceAccess, 'hold', side_effect=forbidden), \
             patch.object(ng.GenerationStore, '_binding', side_effect=forbidden), \
             patch.object(ng.GenerationStore, '_recover', side_effect=forbidden):
            worker = self.delegated(reference)
            worker.validate()
        for name in ng.ARRAYS:
            np.testing.assert_array_equal(getattr(worker, name), getattr(parent, name))
            self.assertFalse(getattr(worker, name).flags.writeable)
        for name in ('symbols', 'companies', 'sessions', 'cached', 'treasury_days', 'treasury_values'):
            self.assertEqual(getattr(worker, name), getattr(parent, name))
        self.assertEqual(dict(worker.histories), dict(parent.histories))
        self.assertEqual(dict(worker.financials), dict(parent.financials))
        self.assertEqual(list(worker.report_rows), list(parent.report_rows))
        self.assertEqual(worker.policy.signature, parent.policy.signature)
        self.assertEqual(worker.field_schema, parent.field_schema)
        self.assertEqual(worker.ten_year_yield.rows, parent.ten_year_yield.rows)
        with self.assertRaises(ValueError): worker.raw_values[0] = 0
        with self.assertRaises(ng.sqlite3.OperationalError): worker._db.execute('DELETE FROM reports')
        with self.assertRaisesRegex(ValueError, 'coordinator'): worker.worker_reference()
        print(json.dumps(dict(check='delegated-attachment', scope='synthetic',
            attachment_seconds=worker.stats['attachment_seconds'], maximum_absolute=0., maximum_relative=0.)), flush=True)

    def test_exact_reference_ignores_pointer_and_coordinator_close(self):
        parent, reference = self.reference()
        expected = parent.raw_values.copy()
        self.advance(); self.advance()
        parent.close()
        first = self.delegated(reference)
        second = self.delegated(reference)
        first.validate()
        np.testing.assert_array_equal(first.raw_values, expected)
        self.assertIn(reference['identity'], self.store.retire_unused()['retained'])
        first.close()
        self.assertIn(reference['identity'], self.store.retire_unused()['retained'])
        second.close()
        self.assertIn(reference['identity'], self.store.retire_unused()['removed'])
        self.assertTrue((self.store.path / 'gates' / (reference['identity'] + '.lock')).exists())
        with self.assertRaisesRegex(ValueError, 'closed'): second.validate()

    def test_only_current_open_coordinator_can_issue_reference(self):
        parent, reference = self.reference()
        self.advance()
        with self.assertRaisesRegex(ValueError, 'stale'): parent.worker_reference()
        parent.close()
        with self.assertRaisesRegex(ValueError, 'closed'): parent.worker_reference()

    def test_reference_validation_missing_gate_corruption_and_source_mismatch_release(self):
        parent, reference = self.reference()
        for fields in (dict(version=True), dict(version=99), dict(store='relative'),
                       dict(identity='../escape'), dict(extra=1), dict(store=str(self.store.path / '..'))):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError): self.delegated(dict(reference, **fields))
                self.unpinned(parent.signature)
        with self.assertRaises(ValueError): self.delegated({})
        with self.assertRaises(ValueError): ng.open_delegated(reference, self.s, checkpoint=None)
        gate = self.store.path / 'gates' / (parent.signature + '.lock')
        gate.unlink()
        with self.assertRaises(FileNotFoundError): self.delegated(reference)
        self.store._ensure_gate(parent.signature)
        # Native Windows does not permit truncating an ordinary mapped file.
        # Close that reader before injecting malformed saved content.
        parent.close()
        target = self.store.path / parent.signature / 'raw_values.npy'
        saved = target.read_bytes(); target.write_bytes(saved[:-1])
        with self.assertRaisesRegex(ValueError, 'Corrupt numerical buffer'): self.delegated(reference)
        self.unpinned(parent.signature)
        target.write_bytes(saved)
        with patch.object(ng, '_source_binding', return_value={}):
            with self.assertRaisesRegex(ValueError, 'source policy'): self.delegated(reference)
        self.unpinned(parent.signature)
        original = ng.PolicyProgram
        def changed(*args, **kwargs):
            policy = original(*args, **kwargs); policy.signature = 'f' * 64
            return policy
        with patch.object(ng, 'PolicyProgram', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'source policy'): self.delegated(reference)
        self.unpinned(parent.signature)
        for field, value in (('field_schema', 'e' * 64), ('parameter_names', ('wrong',))):
            def changed_schema(*args, **kwargs):
                policy = original(*args, **kwargs); setattr(policy, field, value)
                return policy
            with self.subTest(field=field), patch.object(ng, 'PolicyProgram', side_effect=changed_schema):
                with self.assertRaisesRegex(ValueError, 'source policy'): self.delegated(reference)
            self.unpinned(parent.signature)

    def test_cancellation_during_verification_and_mapping_cleanup_and_later_validation(self):
        parent, reference = self.reference()
        error = ValueError('ownership ended')
        count = 0
        def checkpoint():
            nonlocal count
            count += 1
            if count == 12: raise error
        before = set(ng._attachments)
        with self.assertRaises(ValueError) as caught: self.delegated(reference, checkpoint)
        self.assertIs(caught.exception, error)
        self.assertEqual(set(ng._attachments), before)
        self.unpinned(parent.signature)
        original = ng.np.load
        mapped = []
        def load(*args, **kwargs):
            result = original(*args, **kwargs); mapped.append(result); return result
        def mapping_checkpoint():
            if len(mapped) > len(ng.ARRAYS) + 2: raise error
        with patch.object(ng.np, 'load', side_effect=load):
            with self.assertRaises(ValueError) as caught: self.delegated(reference, mapping_checkpoint)
        self.assertIs(caught.exception, error)
        self.assertTrue(all(a._mmap.closed for a in mapped))
        self.assertEqual(set(ng._attachments), before)
        self.unpinned(parent.signature)
        active = True
        def live():
            if not active: raise error
        worker = self.delegated(reference, live)
        worker.validate(); active = False
        with self.assertRaises(ValueError) as caught: worker.validate()
        self.assertIs(caught.exception, error)

    def test_close_failure_retains_pin_and_strong_owner_until_retry(self):
        parent, reference = self.reference()
        worker = self.delegated(reference)
        parent.close(); self.advance(); self.advance()
        original = worker._db
        class FailedClose:
            def close(self): raise OSError('synthetic close failure')
        worker._db = FailedClose()
        with self.assertRaises(OSError): worker.close()
        self.assertIs(ng._attachments[id(worker)], worker)
        self.assertIn(worker.signature, self.store.retire_unused()['retained'])
        worker._db = original; worker.close()
        self.assertNotIn(id(worker), ng._attachments)
        self.assertIn(worker.signature, self.store.retire_unused()['removed'])

    def test_verifier_mapping_close_failure_retains_handles_and_pin_until_retry(self):
        parent, reference = self.reference()
        original = ng.np.load
        broken = None
        class FailedMap:
            def __init__(self, mapping): self.mapping, self.fail = mapping, True
            def close(self):
                if self.fail: raise OSError('synthetic verifier close failure')
                self.mapping.close()
        def load(*args, **kwargs):
            nonlocal broken
            array = original(*args, **kwargs)
            if broken is None:
                broken = FailedMap(array._mmap); array._mmap = broken
            return array
        with patch.object(ng.np, 'load', side_effect=load):
            with self.assertRaisesRegex(OSError, 'verifier close') as caught: self.delegated(reference)
        owner = caught.exception.numerical_inputs
        self.addCleanup(owner.close)
        self.assertIs(ng._attachments[id(owner)], owner)
        self.assertFalse(broken.mapping.closed)
        parent.close(); self.advance(); self.advance()
        self.assertIn(parent.signature, self.store.retire_unused()['retained'])
        broken.fail = False; owner.close()
        self.assertTrue(broken.mapping.closed)
        self.assertNotIn(id(owner), ng._attachments)
        self.assertIn(parent.signature, self.store.retire_unused()['removed'])

    def test_retirement_exclusive_gate_wins_before_attachment_and_gate_stays_stable(self):
        parent, reference = self.reference()
        parent.close(); self.advance(); self.advance()
        original = ng.shutil.rmtree
        attempts = []
        gate = self.store.path / 'gates' / (parent.signature + '.lock')
        stat = gate.stat()
        def remove(path, *args, **kwargs):
            if Path(path).name == parent.signature:
                with self.assertRaises(BlockingIOError): self.delegated(reference)
                attempts.append(True)
            return original(path, *args, **kwargs)
        with patch.object(ng.shutil, 'rmtree', side_effect=remove):
            self.assertIn(parent.signature, self.store.retire_unused()['removed'])
        self.assertEqual(attempts, [True])
        self.assertEqual(gate.stat().st_ino, stat.st_ino)
        with self.assertRaises(FileNotFoundError): self.delegated(reference)
        self.unpinned(parent.signature)

    def test_damaged_replacement_requires_exclusive_pin_and_preserves_gate(self):
        parent, reference = self.reference()
        worker = self.delegated(reference); parent.close()
        manifest = self.store.path / parent.signature / 'manifest.json'
        manifest.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'busy or unowned'): self.prepare()
        self.assertFalse(list(self.store.path.glob('damaged-*')))
        worker.close()
        self.assertEqual(self.prepare()['identity'], parent.signature)
        self.assertEqual(len(list(self.store.path.glob('damaged-*'))), 1)
        with closing(self.delegated(reference)) as rebuilt: rebuilt.validate()

    def test_spawned_reader_shares_gate_without_financial_ownership_then_abrupt_exit_releases(self):
        parent, reference = self.reference()
        with self.owner.hold():
            process, ready, stop, done = self.spawn(reference)
            value = json.loads(ready.read_text())
            self.assertEqual(value['identity'], parent.signature)
            self.assertEqual(value['sample'], parent.raw_values.tolist())
        parent.close(); self.advance(); self.advance()
        worker = self.delegated(reference)
        self.assertIn(parent.signature, self.store.retire_unused()['retained'])
        worker.close()
        self.assertIn(parent.signature, self.store.retire_unused()['retained'])
        process.kill(); process.communicate(timeout=10)
        self.assertFalse(done.exists())
        self.assertIn(parent.signature, self.store.retire_unused()['removed'])
        self.unpinned(parent.signature)

    def test_reader_keeps_own_pin_after_spawning_parent_dies_and_releases_all_files(self):
        parent, reference = self.reference()
        process, ready, stop, done = self.spawn(reference, 'parent')
        process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0)
        pid = json.loads(ready.read_text())['pid']
        def cleanup_orphan():
            stop.touch()
            if not done.exists():
                try: os.kill(pid, signal.SIGTERM)
                except ProcessLookupError: pass
        self.addCleanup(cleanup_orphan)
        parent.close(); self.advance(); self.advance()
        self.assertIn(parent.signature, self.store.retire_unused()['retained'])
        stop.touch(); self.wait_for(done)
        self.unpinned(parent.signature)
        folder = self.store.path / parent.signature
        renamed = folder.with_name('closed-reader')
        folder.rename(renamed)
        ng.shutil.rmtree(renamed)
        self.assertFalse(renamed.exists())


if __name__ == '__main__': unittest.main()
