"""Execution provenance and accounting; synthetic observations are explicit."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import numerical_execution as execution


OBSERVATIONS = dict(logical_cpus=16, affinity_cpus=12, cpu_quota_lanes=6.5,
    available_bytes=4*1024**3, commit_headroom_bytes=None, container_headroom_bytes=None)


class ExecutionTests(unittest.TestCase):
    def test_effective_resources_attribution_and_higher_layout(self):
        policy = execution.ExecutionPolicy(observations=OBSERVATIONS)
        self.assertEqual(policy.workers, 1)
        self.assertEqual(policy.provider_limits['threads'], 4)
        self.assertEqual(policy.identity['numerical_lane_budget'], 6)
        self.assertIn('comparison', policy.provenance['threads'])
        larger = execution.ExecutionPolicy(dict(workers=2, threads_per_worker=3), observations=OBSERVATIONS)
        self.assertEqual(larger.identity['workers']*larger.identity['threads_per_worker'], 6)
        self.assertEqual(larger.identity['workspace_total_bytes'], 3*64*1024**2)
        self.assertEqual(larger.provider_limits['workspace_bytes'], 64*1024**2)
        explicit = execution.ExecutionPolicy(dict(workers=8, threads_per_worker=2, lane_budget=16),
                                              observations=OBSERVATIONS)
        self.assertEqual(explicit.workers, 8)
        with self.assertRaisesRegex(ValueError, 'lane budget'):
            execution.ExecutionPolicy(dict(workers=3, threads_per_worker=3), observations=OBSERVATIONS)
        self.assertEqual(execution.effective_lanes(dict(logical_cpus=None)), 1)

    def test_total_provider_and_artifact_accounting(self):
        policy = execution.ExecutionPolicy(dict(workers=2, threads_per_worker=1,
            workspace_bytes=120, matrix_cache_bytes=30, pending_slots=3,
            artifact_bytes=2000, artifact_total_bytes=6000, piece_bytes=100), observations=OBSERVATIONS)
        self.assertEqual(policy.identity['live_providers'], 3)
        self.assertEqual(policy.provider_limits['workspace_bytes'], 40)
        self.assertEqual(policy.provider_limits['matrix_cache_bytes'], 10)
        for settings in (dict(threads_per_worker=True), dict(workers=0), dict(pending_slots=0),
                         dict(workspace_bytes=1), dict(artifact_bytes=10),
                         dict(artifact_total_bytes=1), dict(start_seconds=float('nan')),
                         dict(close_seconds=0), dict(unknown=1)):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                execution.ExecutionPolicy(settings, observations=OBSERVATIONS)

    def test_observations_admission_and_timeouts_do_not_change_identity(self):
        settings = dict(workers=2, threads_per_worker=1)
        first = execution.ExecutionPolicy(settings, observations=OBSERVATIONS)
        changed = dict(OBSERVATIONS, observed_at=1, available_bytes=123, physical_bytes=456)
        second = execution.ExecutionPolicy(dict(settings, private_memory_budget_bytes=2000,
                                                close_seconds=99, start_seconds=999), observations=changed)
        self.assertEqual(first.identity, second.identity)
        detached = first.identity; detached['workers'] = 999
        self.assertEqual(first.identity['workers'], 2)
        with patch.object(execution, 'observe_resources', return_value=OBSERVATIONS):
            self.assertEqual(first.admit_cold_worker(dict(sampled_private_bytes=1000))['duplication_bytes'], 1000)
            with self.assertRaisesRegex(ValueError, 'measured cold'):
                first.admit_cold_worker({})
            with self.assertRaisesRegex(ValueError, 'allowance'):
                second.admit_cold_worker(dict(sampled_private_bytes=1001))
        with patch.object(execution, 'observe_resources', return_value=dict(available_bytes=999)):
            with self.assertRaisesRegex(ValueError, 'available memory'):
                first.admit_cold_worker(dict(sampled_private_bytes=1000))

    def test_actual_probe_records_uncertainty_and_numba_never_silently_clamps(self):
        actual = execution.observe_resources()
        self.assertGreater(execution.effective_lanes(actual), 0)
        self.assertIn('unknown', actual)
        self.assertEqual(execution.numba_threads(5, 8), 5)
        for count in (0, True, -1, 9):
            with self.assertRaises(ValueError): execution.numba_threads(count, 8)
        print('Actual numerical resource observations:', actual, flush=True)


if __name__ == '__main__': unittest.main()
