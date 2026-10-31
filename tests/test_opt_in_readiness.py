"""Supported experimental selection and rejection on owned fictional inputs."""
from collections import OrderedDict
from copy import deepcopy
from datetime import date
from io import BytesIO
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).absolute().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'scripts'), str(ROOT/'tools')]
import test_numerical_portfolios as portfolios
import numerical_random
from numerical_policy import PolicyProgram, UNSUPPORTED_THRESHOLDS
from numerical_session import Session
import robustness


class ReadinessTests(unittest.TestCase):
    s = portfolios.s
    setUp = portfolios.NumericalPortfolioTests.setUp
    evaluator = portfolios.NumericalPortfolioTests.evaluator

    def test_both_selection_orders_complete_fixed_and_recorded_random_agree(self):
        inputs, provider, portfolio = self.evaluator(candidate_assembly='source')
        differences = []
        for pool in ('cached', 'legacy'):
            for metric in self.s.metrics.METRICS:
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

    def test_capability_catalog_and_every_reuse_boundary_reject_spread(self):
        inputs, provider, portfolio = self.evaluator(candidate_assembly='source')
        self.assertEqual(set(inputs.policy.fields['thresholds']),
                         set(self.s.metrics.FILTERS)-UNSUPPORTED_THRESHOLDS)
        options = dict(pool='cached', filters=[dict(field='operating_yield_spread_3y', op='gt', value=5.)])
        request = dict(start='2015-01-05', end='2016-12-30', months=12, **options)
        before = deepcopy(request)
        config = robustness.plan(self.db, **request, trials=2, seed=42)
        session = Session.__new__(Session)
        session.portfolio = portfolio
        session.validate = Mock()
        session.inputs = inputs
        session.results = OrderedDict()
        session.checkpoints = Mock()
        session.checkpoints.open.side_effect = AssertionError('No checkpoint access')
        with patch.object(provider, 'begin', side_effect=AssertionError('No provider work')):
            for call in (
                lambda: portfolio.backtest(**request),
                lambda: session.plan(dict(request, trials=2, seed=42)),
                lambda: session.plan(dict(calendar=dict(version=1,start=request['start'],end=request['end'],
                    interval=dict(unit='week',count=1)), trials=2, seed=42, **options)),
                lambda: numerical_random.validate_configuration(portfolio, config),
                lambda: numerical_random.checkpoint_binding(portfolio, config),
                lambda: session.calculate('custom', request, None, None),
                lambda: session.calculate('random', dict(request,trials=2,seed=42), None, None, planned=config),
                lambda: session.calculate_into('random', request, BytesIO(), None, None, planned=config,
                    max_bytes=1024**2,piece_bytes=1024,record_bytes=1024),
            ):
                with self.assertRaisesRegex(ValueError, 'experimental does not support filter operating_yield_spread_3y'):
                    call()
        session.checkpoints.open.assert_not_called()
        self.assertEqual(request, before)
        with self.assertRaisesRegex(ValueError, 'experimental does not support'):
            provider.evaluate([('2015-01-05','2016-12-30','cached')],options)
        # Catalog additions still fail preparation instead of silently disappearing.
        with patch.dict(self.s.metrics.FILTERS, {'unknown_future_field':dict(available=True)}):
            with self.assertRaisesRegex(ValueError,'Unsupported threshold catalog'):
                PolicyProgram(self.s)


if __name__ == '__main__': unittest.main()
