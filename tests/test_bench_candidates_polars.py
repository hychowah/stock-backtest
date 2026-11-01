"""Run the same source differential candidate contract against Polars."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
import unittest

import test_bench_candidates_duckdb as analytical_tests


class PolarsCandidateTests(analytical_tests.DuckDBCandidateTests):
    backend_name = 'polars'


if __name__ == '__main__':
    unittest.main()
