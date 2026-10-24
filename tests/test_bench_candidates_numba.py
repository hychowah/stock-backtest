"""Differential source-policy proof with compiled reports, prices and factors."""
import unittest

import test_bench_candidates as source_tests
from bench_candidates_numba import NumbaExecutor


class NumbaCandidateTests(source_tests.CandidateTests):
    factory = NumbaExecutor

    def test_real_nopython_kernels_and_strict_arithmetic(self):
        inputs,executor = self.make()
        self.assertFalse(executor.stats['fastmath'])
        self.assertFalse(executor.stats['compiler_cache'])
        self.assertLessEqual(executor.stats['threads'],4)
        for name in ('reports','prices','factors'):
            self.assertTrue(executor.stats['nopython_signatures'][name])


if __name__=='__main__':
    unittest.main()
