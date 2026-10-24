"""Source-derived Rust expression lowering and native candidate parity."""
from datetime import date
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import test_bench_methods as shared
import numpy as np
from bench_candidates import NumericInputs, PythonExecutor
import bench_candidates_rust as backend


class RustSourceTests(unittest.TestCase):
    def test_expression_tree_preserves_source_order_and_conditional_branches(self):
        policy = SimpleNamespace(input_names=('a','b','bankruptcy'),
            expressions=(('cap',('mul',('input','a'),('div',('input','b'),('const',3.)))),
                         ('ret',('if',('input','bankruptcy'),('const',-1.),
                                 ('sub',('var','cap'),('const',1.))))),
            output_names=('cap','ret'))
        result = backend.rust_expressions(policy)
        self.assertIn('(input[0]*(input[1]/3.0_f64))',result)
        self.assertIn('if input[2] != 0.0_f64 {-1.0_f64} else {(v0-1.0_f64)}',result)
        self.assertIn('output[0] = v0',result)
        self.assertIn('output[1] = v1',result)
        source = backend.rust_source(policy)
        self.assertIn('ninputs != 3 || noutputs != 2',source)
        self.assertNotIn('__FACTORS__',source)

    def test_unsupported_policy_fails_instead_of_using_scalar_fallback(self):
        policy = SimpleNamespace(input_names=('a',),expressions=(('bad',('call','unknown')),),output_names=('bad',))
        with self.assertRaisesRegex(ValueError,'Unsupported shared policy'):
            backend.rust_expressions(policy)
        policy.expressions = (('bad',('var','not_defined')),)
        with self.assertRaisesRegex(ValueError,'unordered derived'):
            backend.rust_expressions(policy)


@unittest.skipUnless(os.name == 'nt' or shutil.which('rustc'), 'Native Rust compiler is absent on this platform.')
class RustNativeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = shared.SharedMethodsTests('test_empty_trials_remain_visible_and_excluded_from_distributions')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.inputs = NumericInputs(self.fixture.reader,shared.s)
        self.addCleanup(self.inputs.close)
        self.executor = backend.attach(self.inputs,limits=dict(workdir=self.fixture.root/'rust',capture=True,
                                                             threads=4,setup_seconds=60.))
        self.addCleanup(self.executor.close)
        self.ordinary = PythonExecutor(self.inputs,limits=dict(capture=True))
        self.addCleanup(self.ordinary.close)

    def test_native_primitives_preserve_report_boundaries_and_sparse_prices(self):
        entries = np.array([date(2011,9,28).toordinal(),date(2011,9,29).toordinal(),
                            date(2015,1,2).toordinal(),date(2020,1,1).toordinal()],dtype=np.int32)
        for actual,expected in zip(self.executor.select_reports(entries),self.ordinary.select_reports(entries),strict=True):
            np.testing.assert_array_equal(actual,expected)
        symbols = np.array([-1,0,0,0,-1],dtype=np.int32)
        days = np.array([date(2015,1,2).toordinal()]*5,dtype=np.int32)
        columns = np.array([0,0,1,1,0],dtype=np.uint8)
        forwards = np.array([0,0,1,0,1],dtype=np.uint8)
        actual = self.executor.resolve(symbols,days,columns,forwards)
        expected = self.ordinary.resolve(symbols,days,columns,forwards)
        np.testing.assert_array_equal(actual[0],expected[0])
        np.testing.assert_allclose(actual[1],expected[1],rtol=0,atol=0,equal_nan=True)

    def test_all_numeric_outputs_and_full_candidate_books_match_source_adapter(self):
        for pool in ('legacy','cached'):
            for profile in ('F0','F1','F2'):
                options = dict(shared.baseline.options(pool,profile),min_cap=0.,min_ev=0.)
                request = dict(options=options)
                self.ordinary.begin(request)
                self.executor.begin(request)
                books = [('2015-01-02','2016-01-04',pool),('2016-01-04','2016-12-30',pool)]
                expected = self.ordinary.evaluate(books,options=options)
                actual = self.executor.evaluate(books,options=options)
                self.assertTrue(shared.baseline.compare(expected,actual)['exact'])
                for key,value in self.ordinary.trace.items():
                    np.testing.assert_allclose(self.executor.trace[key],value,rtol=1e-12,atol=1e-12,
                                               equal_nan=True,err_msg=key)
        # Exceed the native parallel threshold and exercise IEEE missing/error
        # values before the shared source guards reject unavailable candidates.
        matrix = np.tile(self.ordinary.trace['numeric_inputs'],(40,1))
        matrix[0,self.inputs.policy.input_index['fiscal_raw']] = 0.
        matrix[1,self.inputs.policy.input_index['average_3y']] = np.nan
        with np.errstate(all='ignore'):
            expected = self.inputs.policy.evaluate(matrix)
            actual = self.executor.calculate(matrix)
        np.testing.assert_allclose(actual,expected,rtol=1e-12,atol=1e-12,equal_nan=True)
        np.testing.assert_array_equal(np.isfinite(actual),np.isfinite(expected))
        self.assertEqual(self.executor.stats['abi'],1)
        self.assertFalse(self.executor.stats['compiler_cache'])

    def test_close_is_idempotent_and_native_calls_cannot_outlive_library(self):
        self.executor.close()
        self.executor.close()
        with self.assertRaisesRegex(RuntimeError,'closed'):
            self.executor.kernel.calculate(np.empty((0,len(self.inputs.policy.input_names))))


if __name__ == '__main__':
    unittest.main()
