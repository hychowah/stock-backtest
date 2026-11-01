"""Equivalent legacy selection defaults retain exact dated-plan recovery."""
from copy import deepcopy
import io
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).absolute().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'scripts'),str(ROOT)]
import test_numerical_runtime as fixtures
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.engines.numerical.portfolio import compare_results
from backtest.engines.numerical.session import _validate_submitted
from backtest import result_evidence as result_evidence
from backtest.engines.original import robustness as robustness
from test_result_evidence import collect


class ReplayTests(unittest.TestCase):
    setUp=fixtures.RuntimeTests.setUp
    make=fixtures.RuntimeTests.make
    options=fixtures.RuntimeTests.options
    assert_closed=fixtures.RuntimeTests.assert_closed

    def test_eager_and_bounded_replay_accept_only_equivalent_order_defaults(self):
        options=self.options(trials=2,seed=42)
        plan=robustness.plan(self.fixture.db,**options)
        self.assertNotIn('selection_order',plan['options'])
        before=deepcopy(plan)
        for bounded in (False,True):
            value=self.make()
            request=dict(options,selection_order='filter_first')
            if bounded:
                stream=io.BytesIO()
                completion=value.calculate_into('random',request,stream,planned=plan,max_bytes=4*1024**2)
                actual=collect(result_evidence.Reader(stream,max_bytes=4*1024**2))
                summary=completion['manifest']['summary']
            else:
                summary=value.calculate('random',request,planned=plan)
                actual=summary['trial_results']
            self.assertEqual(summary['configuration'],plan)
            for dates,trial in zip(plan['samples'],actual,strict=True):
                reference=self.fixture.s.backtest_dates(self.fixture.db,dates=dates,
                    **{k:v for k,v in options.items() if k not in ('trials','seed')})
                self.assertTrue(compare_results(reference,trial)['exact'])
            self.assertEqual(plan,before)
            value.close();self.assert_closed(value)
        self.assertEqual(summary['execution']['recovered_trials'],2)
        self.assertEqual(summary['execution']['calculated_trials'],0)
        # Both transport paths reject a real change before returning recovered
        # evidence. The original plan and its samples remain unchanged.
        for bounded in (False,True):
            for changed in (dict(options,selection_order='rank_first'),dict(options,rank_to=2)):
                value=self.make()
                with self.assertRaisesRegex(ValueError,'Submitted settings differ'):
                    if bounded:value.calculate_into('random',changed,io.BytesIO(),planned=plan,max_bytes=4*1024**2)
                    else:value.calculate('random',changed,planned=plan)
                self.assert_closed(value)
        _validate_submitted(options,dict(plan,options=dict(plan['options'],selection_order='filter_first')))
        with self.assertRaisesRegex(ValueError,'Submitted settings differ'):
            _validate_submitted(options,dict(plan,options=dict(plan['options'],selection_order='rank_first')))
        self.assertEqual(plan,before)


if __name__=='__main__':unittest.main()
