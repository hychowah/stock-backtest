"""The shared cache contract gives waiting live threads priority too."""
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cache_access


class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='cb02-priority-')
        self.addCleanup(self.folder.cleanup)
        self.access = cache_access.WorkspaceAccess(Path(self.folder.name) / 'cache.lock')

    def test_waiting_thread_announces_intent_before_local_lock_and_observer_yields(self):
        ready, release = Event(), Event()
        failures = []
        def live():
            try:
                with self.access.hold(timeout=5): ready.set(); release.wait(5)
            except BaseException as error: failures.append(error)
        with self.assertRaises(ValueError), self.access.observe() as checkpoint:
            worker = Thread(target=live); worker.start()
            try:
                deadline = time.monotonic() + 3
                while not self.access.live_pending() and time.monotonic() < deadline: time.sleep(.001)
                self.assertTrue(self.access.live_pending())
                self.assertFalse(ready.is_set())
                with self.assertRaises(ValueError): checkpoint()
            finally:
                # observe's final checkpoint also rejects the conflict.
                release.set()
                self.addCleanup(worker.join, 6)
                self.assertEqual(failures, [])

    def test_nested_live_ownership_reuses_one_lease_and_error_releases_it(self):
        with self.assertRaises(RuntimeError):
            with self.access.hold():
                self.assertEqual(len(list(self.access.intents.iterdir())), 1)
                with self.access.hold():
                    self.assertEqual(len(list(self.access.intents.iterdir())), 1)
                    raise RuntimeError('fixture')
        self.assertFalse(self.access.live_pending())
        with self.access.observe(): pass

    def test_live_operation_cannot_nest_in_observation_and_ambiguous_lease_defers(self):
        with self.access.observe():
            with self.assertRaises(ValueError):
                with self.access.hold(): pass
        self.access.intents.mkdir(exist_ok=True)
        (self.access.intents / 'unknown').mkdir()
        self.assertTrue(self.access.live_pending())
        with self.assertRaises(ValueError):
            with self.access.observe(): pass

    def test_lease_publication_failure_never_acquires_financial_lock(self):
        with patch.object(self.access, '_intent', side_effect=OSError('fixture')), patch.object(self.access, '_hold') as held:
            with self.assertRaises(OSError):
                with self.access.hold(): pass
            held.assert_not_called()


if __name__ == '__main__': unittest.main()
