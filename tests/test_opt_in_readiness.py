"""Supported experimental selection and catalog validation on owned fictional inputs."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.financial import metrics
from copy import deepcopy
from datetime import date
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).absolute().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'scripts'), str(ROOT/'tools')]
import test_numerical_portfolios as portfolios
from backtest.engines.numerical import random as numerical_random
from backtest.engines.numerical.policy import PolicyProgram
from backtest.engines.original import robustness as robustness


class ReadinessTests(unittest.TestCase):
    s = portfolios.s
    setUp = portfolios.NumericalPortfolioTests.setUp
    evaluator = portfolios.NumericalPortfolioTests.evaluator

    def test_both_selection_orders_complete_fixed_and_recorded_random_agree(self):
        inputs, provider, portfolio = self.evaluator(candidate_assembly='source')
        differences = []
        for pool in ('cached', 'legacy'):
            for metric in metrics.METRICS:
                for order in ('filter_first', 'rank_first'):
                    options = dict(pool=pool, metric=metric, selection_order=order,
                        rank_to=5, min_cap=0., min_ev=0.,
                        filters=[dict(field='market_cap', op='gt', value=180.)])
                    request = dict(start='2015-01-05', end='2016-12-30', months=12, **options)
                    expected = self.s.backtest(self.db, **request)
                    actual = portfolio.backtest(**request)['result']
                    self.assertTrue(portfolios.compare_results(expected, actual)['exact'])
                    self.assertTrue(all(p['names'] for p in actual['periods']))
                    if metric == 'ev_ebitda':
                        ranks = [h['rank'] for h in actual['periods'][0]['holdings']]
                        self.assertEqual(ranks, [4 if pool == 'cached' else 3] if order == 'rank_first' else [1])
                    config = robustness.plan(self.db, **request, trials=2, seed=42)
                    before = deepcopy(config)
                    self.assertEqual(numerical_random.validate_configuration(portfolio, config), config)
                    for dates in config['samples']:
                        replay = dict(dates=dates, **request)
                        agreement = portfolios.compare_results(self.s.backtest_dates(self.db, **replay),
                            portfolio.backtest_dates(**replay)['result'])
                        self.assertTrue(agreement['exact'], agreement)
                        differences.append(agreement['maximum_absolute'])
                    self.assertEqual(config, before)
        self.assertEqual(max(differences), 0.)

    def test_full_capability_catalog_and_unknown_future_fields_fail(self):
        inputs, provider, portfolio = self.evaluator(candidate_assembly='source')
        self.assertEqual(set(inputs.policy.fields['thresholds']), set(metrics.FILTERS))
        with patch.dict(metrics.FILTERS, {'unknown_future_field':dict(available=True)}):
            with self.assertRaisesRegex(ValueError,'Unsupported threshold catalog'):
                PolicyProgram()


if __name__ == '__main__': unittest.main()
