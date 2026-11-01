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
        self.assertEqual(policy.backend,'numba_compiled')
        self.assertEqual(policy.workers, 2)
        self.assertEqual(policy.provider_limits['threads'], 2)
        self.assertEqual(policy.identity['numerical_lane_budget'], 6)
        self.assertIn('measured', policy.provenance['threads'])
        self.assertIn('256 MiB',policy.provenance['memory'])
        for backend in ('rust','numba'):
            with self.assertRaisesRegex(ValueError,'historical'):
                execution.ExecutionPolicy({'backend':backend},observations=OBSERVATIONS)
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

    def test_default_capacity_resolves_before_identity_and_unknown_memory_is_single(self):
        for lanes,workers,threads in ((1,1,1),(2,1,2),(3,1,2),(4,2,2),(16,2,2)):
            observed=dict(OBSERVATIONS,logical_cpus=lanes,affinity_cpus=lanes,cpu_quota_lanes=None)
            value=execution.ExecutionPolicy(observations=observed)
            self.assertEqual((value.workers,value.provider_limits['threads']),(workers,threads))
            changed=dict(observed,available_bytes=1)
            resolved=execution.ExecutionPolicy(value.settings,observations=changed)
            self.assertEqual(value.identity,resolved.identity)
        for available in (None,1):
            observed=dict(OBSERVATIONS,available_bytes=available)
            self.assertEqual(execution.ExecutionPolicy(observations=observed).workers,1)
        explicit=execution.ExecutionPolicy(dict(workers=4,threads_per_worker=2,lane_budget=8),observations=OBSERVATIONS)
        self.assertEqual(explicit.workers,4)

    def test_job_headroom_limits_both_default_and_actual_cold_admission(self):
        restricted=dict(OBSERVATIONS,job_headroom_bytes=1000)
        self.assertEqual(execution.ExecutionPolicy(observations=restricted).workers,1)
        missing=dict(OBSERVATIONS,restricted_memory_unobserved=True)
        self.assertEqual(execution.ExecutionPolicy(observations=missing).workers,1)
        policy=execution.ExecutionPolicy(dict(workers=2,threads_per_worker=1),observations=OBSERVATIONS)
        with patch.object(execution,'observe_resources',return_value=restricted):
            with self.assertRaisesRegex(ValueError,'available memory'):policy.admit_cold_worker({'sampled_private_bytes':1001})
        with patch.object(execution,'observe_resources',return_value=missing):
            with self.assertRaisesRegex(ValueError,'memory observation'):policy.admit_cold_worker({'sampled_private_bytes':1})
        explicit=execution.ExecutionPolicy(dict(workers=2,threads_per_worker=1,private_memory_budget_bytes=1000),observations=missing)
        with patch.object(execution,'observe_resources',return_value=missing):
            self.assertEqual(explicit.admit_cold_worker({'sampled_private_bytes':100})['duplication_bytes'],100)

    def test_runtime_and_session_normalization_preserve_legacy_per_provider_bounds_and_origin(self):
        from numerical_runtime import NumericalRuntime
        with patch.object(execution,'observe_resources',return_value=OBSERVATIONS):
            value=NumericalRuntime(source_root=ROOT,scratch=ROOT/'tmp/not-started-policy-test',session_options={'matrix_cache_bytes':32768})
        settings=value.configuration['session_options']['execution']
        self.assertEqual(settings['matrix_cache_bytes'],32768*(settings['workers']+1))
        configured=dict(value.configuration,**value.configuration['session_options'])
        session=execution.ExecutionPolicy.from_configuration(configured)
        self.assertEqual(session.provider_limits['matrix_cache_bytes'],32768)
        self.assertIn('measured',session.provenance['layout'])
        self.assertEqual(session.observations,OBSERVATIONS)

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
