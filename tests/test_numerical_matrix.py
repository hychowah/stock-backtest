"""Bounded real compiled-output reuse without financial selection shortcuts."""
import unittest
from unittest.mock import patch

import numpy as np
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import backtest_control as backtest_control
from backtest.engines.numerical.matrix import CompiledMatrix


class Policy:
    input_names=('a','b')
    output_names=('sum','ratio')
    def python_source(self,name,outputs=None):
        return 'def '+name+'(row):\n    return row[0]+row[1],row[0]/row[1]\n'


class MatrixTests(unittest.TestCase):
    def make(self,**options):
        result=CompiledMatrix(Policy(),'fictional-identity',**options)
        self.addCleanup(result.close)
        return result

    def test_real_hit_exact_nan_input_keys_detached_outputs_and_unretained_oversize(self):
        value=self.make(cache_bytes=4096,chunk_rows=1)
        matrix=np.array([[1.,2.],[3.,0.]])
        first=value(matrix);first[0,0]=999.
        second=value(matrix)
        np.testing.assert_equal(second,[[3.,.5],[3.,np.inf]])
        self.assertEqual(value.stats['hits'],1)
        altered=matrix.copy();altered[0,0]=2.
        np.testing.assert_equal(value(altered)[0],[4.,1.])
        self.assertEqual(value.stats['misses'],2)
        self.assertLessEqual(value.stats['retained_bytes'],4096)
        tiny=self.make(cache_bytes=0)
        np.testing.assert_equal(tiny(matrix),second)
        self.assertEqual(tiny.stats['retained_bytes'],0)

    def test_eviction_and_workspace_rejection_before_native_work(self):
        value=self.make(cache_bytes=1100,workspace_bytes=8192)
        for i in range(10):value(np.array([[float(i),2.]]))
        self.assertGreater(value.stats['evictions'],0)
        self.assertLessEqual(value.stats['retained_bytes'],1100)
        before=value.stats['native_chunks']
        with self.assertRaisesRegex(ValueError,'workspace'):value(np.ones((100,2)))
        self.assertEqual(value.stats['native_chunks'],before)
        with self.assertRaisesRegex(ValueError,'signature'):value(np.ones((1,3)))

    def test_cancellation_between_bounded_chunks_does_not_retain_partial_output(self):
        value=self.make(chunk_rows=1)
        with backtest_control.cancel_when(lambda:value.stats['native_chunks']>=1):
            with self.assertRaises(backtest_control.Cancelled):value(np.ones((3,2)))
        self.assertEqual(value.stats['native_chunks'],1)
        self.assertEqual(value.stats['retained_bytes'],0)
        value.close()
        with self.assertRaisesRegex(ValueError,'closed'):value(np.ones((1,2)))


if __name__=='__main__':unittest.main()
