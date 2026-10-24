"""Run the same source differential candidate contract against Polars."""
import unittest

import test_bench_candidates_duckdb as analytical_tests


class PolarsCandidateTests(analytical_tests.DuckDBCandidateTests):
    backend_name = 'polars'


if __name__ == '__main__':
    unittest.main()
