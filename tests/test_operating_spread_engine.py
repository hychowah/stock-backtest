"""Source-derived operating spread over private annual and dated inputs."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import daily, research
from backtest.financial import metrics
from copy import deepcopy
from datetime import date
import inspect
import json
import math
import unittest
from unittest.mock import patch

import numpy as np
import test_numerical_generation as generations
import numerical_fixture
import numerical_inputs_fixture
from backtest.engines.numerical.generation import DatedYields
from numerical_factor_oracle import FactorEvaluator
from backtest.engines.numerical.policy import PolicyProgram
from backtest.engines.numerical.numba import NumbaExecutor
from backtest.engines.numerical.portfolio import NumericalPortfolio, compare_results
from backtest.engines.original import robustness as robustness
from backtest.engines.numerical import random as numerical_random


FIELD = 'operating_yield_spread_3y'
FILTERS = [dict(field=FIELD, op='gt', value=0.),
           dict(field='pb', op='lt', value=1.5),
           dict(field='fcf_yield', op='gt', value=3.)]


def financial_inputs(db):
    """Nonempty requested-filter coverage, plus signed and missing histories."""
    for symbol, fiscal, raw in list(db.execute('SELECT * FROM financial_inputs')):
        values = json.loads(raw)
        values.update(revenue=100e6, operatingIncome=-10e6 if symbol == 'STOP' else 20e6,
                      totalStockholdersEquity=300e6, freeCashFlow=20e6)
        db.execute('UPDATE financial_inputs SET values_json=? WHERE symbol=? AND fiscal=?',
                   (json.dumps(values), symbol, fiscal))
    db.executemany('INSERT OR REPLACE INTO treasury10 VALUES(?,?)',
                   [('2014-12-31', 2.), ('2015-07-01', 3.), ('2016-07-01', 0.)])
    db.commit()


class SpreadTests(unittest.TestCase):
    setUp = generations.GenerationTests.setUp
    prepare = generations.GenerationTests.prepare
    attach = generations.GenerationTests.attach

    def evaluator(self, assembly='source', planned=True):
        financial_inputs(self.db)
        self.prepare()
        inputs = self.attach()
        provider = NumbaExecutor(inputs, limits=dict(threads=2, request_plan=planned,
                                                    candidate_assembly=assembly))
        self.addCleanup(provider.close)
        portfolio = NumericalPortfolio(inputs, provider)
        self.addCleanup(portfolio.close)
        return inputs, provider, portfolio

    def test_saved_yields_keep_exact_preceding_missing_zero_and_negative(self):
        rows = [('2015-01-02', 2.), ('2015-01-05', 0.), ('2015-01-06', -1.)]
        series = DatedYields(rows)
        self.db.executemany('INSERT INTO treasury10 VALUES(?,?)', rows)
        for day in ('2015-01-01', '2015-01-02', '2015-01-04', '2015-01-05', '2015-01-06', '2026-01-01'):
            self.assertEqual(series(day), research.ten_year_yield(self.db, day))
        self.assertIsNone(DatedYields([])(date(2015, 1, 2)))

    def test_specialization_executes_source_history_guards_and_arithmetic(self):
        policy = PolicyProgram()
        reports = {f'{year}-06-30': dict(revenue=100e6, operatingIncome=amount)
                   for year, amount in ((2012, -10e6), (2013, 30e6), (2014, 40e6))}
        # Same-year variants and newer reports exercise the source fiscal cutoff.
        reports['2013-09-30'] = dict(revenue=90e6, operatingIncome=15e6)
        reports['2015-06-30'] = dict(revenue=1., operatingIncome=1e20)
        variants = [reports]
        for fiscal, key, value in [('2013-09-30', 'revenue', 0.),
                                   ('2014-06-30', 'revenue', -1.),
                                   ('2012-06-30', 'operatingIncome', None)]:
            changed = deepcopy(reports)
            changed[fiscal][key] = value
            variants.append(changed)
        missing = deepcopy(reports)
        del missing['2012-06-30']
        variants.append(missing)
        for annual in variants:
            for treasury in (None, 0., -1., 2.):
                matrix = np.ones((1, len(policy.input_names)), dtype=np.float64)
                matrix[0, -len(policy.parameter_names):] = policy.specialize_financial('2014-06-30', annual)
                matrix[0, policy.input_index['treasury10']] = np.nan if treasury is None else treasury
                output = policy.evaluate(matrix)[0]
                ev = output[policy.output_index['ev']]
                expected = metrics.operating_yield_spread(
                    dict(fiscal='2014-06-30', enterprise_value=ev), annual, treasury)
                actual = output[policy.output_index['filter_' + FIELD]]
                if expected is None:
                    self.assertTrue(np.isnan(actual))
                else:
                    self.assertEqual(actual, expected)
        self.assertIn(FIELD, policy.filter_order)

    def test_source_formula_mutations_change_policy_and_unsupported_shapes_fail(self):
        original = metrics.operating_yield_spread
        base = PolicyProgram()
        text = inspect.getsource(original)
        for index, replacement in enumerate(('value=sales*statistics.mean(margins)/ev*200-treasury10',
                                              'value=sales*statistics.mean(margins)/(ev+sales)*100-treasury10')):
            source = text.replace('value=sales*statistics.mean(margins)/ev*100-treasury10', replacement)
            path = self.root / f'spread-{index}.py'
            path.write_text(source)
            namespace = dict(original.__globals__)
            exec(compile(source, str(path), 'exec'), namespace)
            with patch.object(metrics, 'operating_yield_spread', namespace[original.__name__]):
                changed = PolicyProgram()
                self.assertNotEqual(changed.signature, base.signature)
        source = text.replace('ev<=0', 'ev<=100')
        path = self.root / 'spread-guard.py'
        path.write_text(source)
        namespace = dict(original.__globals__)
        exec(compile(source, str(path), 'exec'), namespace)
        with patch.object(metrics, 'operating_yield_spread', namespace[original.__name__]):
            with self.assertRaisesRegex(ValueError, 'Unsupported symbolic'):
                PolicyProgram()

    def test_complete_books_both_matrix_and_assembly_paths_match(self):
        from backtest.engines.numerical.books import PythonExecutor
        financial_inputs(self.db)
        self.prepare()
        inputs = self.attach()
        for factory, assembly in ((PythonExecutor, 'source'), (NumbaExecutor, 'source'),
                                  (NumbaExecutor, 'compiled')):
            provider = factory(inputs, limits=dict(threads=2, candidate_assembly=assembly))
            try:
                books = [('2015-01-05', '2016-01-04', pool) for pool in ('cached', 'legacy')]
                for planned in (False, True):
                    provider.limits['request_plan'] = planned
                    provider.begin(dict(options=dict(filters=[dict(field=field, op='gt', value=-1e99)
                        for field in inputs.policy.fields['thresholds']])))
                    actual = provider.evaluate(books)
                    for book, observed in zip(books, actual, strict=True):
                        entry, exit_day, pool = book
                        expected = self.s.compute_period(self.db, date.fromisoformat(entry),
                            date.fromisoformat(exit_day), daily.histories(self.db),
                            daily.cached_symbols(self.db), pool)
                        self.assertTrue(numerical_fixture.compare(expected, observed)['exact'])
                        self.assertTrue(any(field == FIELD for _, field, _ in observed['filters']))
            finally:
                provider.close()

    def test_requested_filters_fixed_and_recorded_random_both_orders_and_pools(self):
        _, _, portfolio = self.evaluator()
        for pool in ('cached', 'legacy'):
            for order in ('filter_first', 'rank_first'):
                request = dict(start='2015-01-05', end='2016-12-30', months=12,
                    rank_from=1, rank_to=30, pool=pool, selection_order=order,
                    min_cap=100e6, min_ev=50e6, min_yield=0., filters=FILTERS)
                expected = self.s.backtest(self.db, **request)
                actual = portfolio.backtest(**request)['result']
                self.assertTrue(compare_results(expected, actual)['exact'])
                self.assertTrue(all(p['names'] > 0 for p in actual['periods']))
                self.assertNotIn('STOP', [h['symbol'] for p in actual['periods'] for h in p['holdings']])
                plan = robustness.plan(self.db, **request, trials=2, seed=2607948532)
                before = deepcopy(plan)
                self.assertEqual(numerical_random.validate_configuration(portfolio, plan), plan)
                for dates in plan['samples']:
                    replay = dict(request, dates=dates)
                    self.assertTrue(compare_results(self.s.backtest_dates(self.db, **replay),
                        portfolio.backtest_dates(**replay)['result'])['exact'])
                self.assertEqual(plan, before)

    def test_strict_thresholds_use_the_same_representable_values(self):
        inputs, _, portfolio = self.evaluator()
        request = dict(start='2015-01-05', end='2016-12-30', months=12, pool='cached', rank_to=30)
        book = self.s.backtest(self.db, **request)['periods'][0]
        holding = next(h for h in book['holdings'] if h['symbol'] == 'A')
        expected = metrics.operating_yield_spread(holding, inputs.financials['A'],
            inputs.ten_year_yield(book['entry']))
        for value in (math.nextafter(expected, -math.inf), expected, math.nextafter(expected, math.inf)):
            for op in ('lt', 'gt'):
                options = dict(request, filters=[dict(field=FIELD, op=op, value=value)])
                source = self.s.backtest(self.db, **options)
                result = portfolio.backtest(**options)['result']
                self.assertTrue(compare_results(source, result)['exact'])

    def test_treasury_only_publication_changes_generation_and_rejects_old_attachment(self):
        financial_inputs(self.db)
        self.prepare()
        inputs = self.attach()
        prior = inputs.signature
        before = numerical_inputs_fixture.NumericInputs(self.fixture.reader, self.s)
        self.addCleanup(before.close)
        self.db.execute("UPDATE treasury10 SET yield_percent=4 WHERE day='2014-12-31'")
        self.db.commit()
        after = numerical_inputs_fixture.NumericInputs(self.fixture.reader, self.s)
        self.addCleanup(after.close)
        self.assertNotEqual(before.signature, after.signature)
        # This fixture injects accepted metadata; production derives it from raw
        # inventory. Bind that acceptance before testing immutable publication.
        self.binding['daily'] = dict(treasury10_revision=1)
        with self.assertRaisesRegex(ValueError, 'stale'):
            inputs.validate()
        self.prepare()
        fresh = self.attach()
        self.assertNotEqual(fresh.signature, prior)
        self.assertEqual(inputs.ten_year_yield('2015-01-05'), 2.)
        self.assertEqual(fresh.ten_year_yield('2015-01-05'), 4.)

    def test_missing_treasury_excludes_only_the_requested_filter(self):
        inputs, _, portfolio = self.evaluator()
        factors = FactorEvaluator(inputs)
        self.addCleanup(factors.close)
        date_value = date(2015, 1, 5).toordinal()
        self.assertTrue(factors.evaluate([date_value], threshold_fields=[FIELD])[0].threshold_valid[FIELD].any())
        # Build a new generation with a future-only observation.
        factors.close()
        self.db.execute('DELETE FROM treasury10')
        self.db.execute("INSERT INTO treasury10 VALUES('2016-12-31',9.)")
        self.db.commit()
        self.binding['daily'] = dict(treasury10_revision=2)
        self.prepare()
        fresh = self.attach()
        missing = FactorEvaluator(fresh)
        self.addCleanup(missing.close)
        batch = missing.evaluate([date_value], threshold_fields=[FIELD, 'pb'])[0]
        self.assertFalse(batch.threshold_valid[FIELD].any())
        self.assertTrue(batch.threshold_valid['pb'].any())
        self.assertTrue(batch.pair_valid['ev_ebitda'].any())


if __name__ == '__main__':
    unittest.main()
