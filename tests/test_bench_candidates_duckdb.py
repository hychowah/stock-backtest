from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
from backtest.inputs import daily, research
from backtest.financial import rules, books as financial_books, metrics


from backtest import screening
"""Differential candidate, temporal and source-expression checks for DuckDB."""
from contextlib import closing
from datetime import date, timedelta
import importlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_bench_methods as fixtures

try:
    import numpy as np
    import tools.experiments.bench_candidates as core
except ModuleNotFoundError as error:
    if error.name != 'numpy':
        raise
    np = core = None

s, baseline = fixtures.s, fixtures.baseline


def canonical(book, fields):
    result = dict(book)
    result['period'] = list(result['period'])
    result['snapshots'] = [list(row) for row in result['snapshots']]
    result['metrics'] = [list(row) for row in sorted(tuple(row) for row in result['metrics'])]
    result['filters'] = [list(row) for row in sorted(tuple(row) for row in result['filters'] if row[1] in fields)]
    return result


class DuckDBCandidateTests(unittest.TestCase):
    backend_name = 'duckdb'

    def setUp(self):
        if core is None or importlib.util.find_spec(self.backend_name) is None:
            self.skipTest('Optional analytical benchmark dependencies are absent.')
        self.fixture = fixtures.SharedMethodsTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        # Populate every annual-ratio family. Keep B absent and C's selected
        # report hole, so missing fields still exercise their source guards.
        for symbol, fiscal, body in self.fixture.db.execute(
                'SELECT symbol,fiscal,values_json FROM financial_inputs').fetchall():
            values = json.loads(body)
            values.update(revenue=200e6, operatingIncome=70e6, totalCurrentAssets=110e6,
                          totalCurrentLiabilities=50e6, ebit=70e6,
                          interestExpense=5e6, totalDebt=40e6)
            self.fixture.db.execute('UPDATE financial_inputs SET values_json=? WHERE symbol=? AND fiscal=?',
                                    (json.dumps(values), symbol, fiscal))
        self.fixture.db.executemany('INSERT OR IGNORE INTO treasury10 VALUES(?,?)',
            [('2014-12-31',2.),('2015-07-01',3.),('2016-07-01',0.)])
        self.fixture.db.commit()
        self.inputs = core.NumericInputs(self.fixture.reader, s)
        self.addCleanup(self.inputs.close)
        self.module = importlib.import_module('tools.experiments.bench_candidates_' + self.backend_name)
        self.executor = self.module.attach(self.inputs, limits=dict(capture=True, threads=4))
        self.addCleanup(self.executor.close)

    def source_books(self, jobs):
        return [s.compute_period(self.fixture.reader, date.fromisoformat(entry),
                    date.fromisoformat(exit_day), self.inputs.books, self.inputs.cached, pool)
                for entry, exit_day, pool in jobs]

    def selected(self, book, options):
        with closing(sqlite3.connect(':memory:')) as db:
            db.row_factory = sqlite3.Row
            db.executescript(daily.SCHEMA)
            db.executemany('INSERT INTO companies VALUES(?,?,?,?)', self.inputs.companies)
            period = daily.store_period(db, book)
            rows = screening.select(db, period=(period, period), **options)
            for row in rows:
                row.pop('year')
            return rows

    def assert_books(self, jobs, options):
        source = self.source_books(jobs)
        self.executor.begin(dict(options=options))
        actual = self.executor.evaluate(jobs)
        fields = {condition['field'] for condition in options.get('filters', [])}
        baseline.compare([canonical(book, fields) for book in source],
                         [canonical(book, fields) for book in actual])
        for expected, got in zip(source, actual, strict=True):
            # The final selector consumes complete backend-produced values.
            # A threshold at an exact source value must preserve membership.
            baseline.compare(self.selected(expected, options), self.selected(got, options))
        trace = self.executor.trace
        expected_numeric = self.inputs.policy.evaluate(trace['numeric_inputs'])
        np.testing.assert_allclose(trace['numeric_outputs'], expected_numeric,
                                   rtol=1e-12, atol=1e-12, equal_nan=True)
        return source, actual

    def test_complete_candidate_books_profiles_metrics_and_sql_membership(self):
        profiles = list(baseline.PROFILES.values()) + [
            baseline.PROFILES['F1'] + baseline.PROFILES['F2'],
            [dict(field=field, op='gt', value=-1e100) for field in metrics.FILTERS],
        ]
        for pool in ('legacy', 'cached'):
            jobs = [('2015-01-02', '2016-01-04', pool),
                    ('2015-07-01', '2016-06-30', pool),
                    ('2016-07-01', '2016-12-30', pool)]
            for metric in metrics.METRICS:
                for conditions in profiles:
                    with self.subTest(pool=pool, metric=metric, fields=[c['field'] for c in conditions]):
                        options = dict(baseline.options(pool, 'F0'), min_cap=0., min_ev=0.,
                                       metric=metric, filters=conditions, rank_from=1, rank_to=100)
                        self.assert_books(jobs, options)
        self.assertGreaterEqual(self.executor.stats['max_report_batch_days'], 3)

    def test_report_availability_age_boundaries_and_complete_pool_identity(self):
        days = set()
        for row in self.inputs.report_rows:
            for anchor in (row['known'], row['fiscal'] + rules.MAX_AGE):
                days.update(anchor + timedelta(days=offset) for offset in (-1, 0, 1))
        ordered = sorted(days)
        actual = self.executor.select_reports(np.array([day.toordinal() for day in ordered], dtype=np.int32))
        for number, day in enumerate(ordered):
            expected, unused = financial_books.candidates(self.inputs.books, day)
            for output, pool in zip(actual, ('cached', 'legacy'), strict=True):
                for sid, symbol in enumerate(self.inputs.symbols):
                    report_id = int(output[number, sid])
                    if symbol not in expected[pool]:
                        self.assertEqual(report_id, -1)
                    else:
                        self.assertGreaterEqual(report_id, 0)
                        self.assertEqual(self.inputs.report_rows[report_id], expected[pool][symbol])

    def test_sparse_price_queries_and_exact_order_match_sqlite(self):
        queries = [(sid, date.fromisoformat(day).toordinal(), column, forward)
                   for sid in range(len(self.inputs.symbols))
                   for day in ('2010-12-31', '2015-01-02', '2015-01-03', '2016-06-30', '2017-01-02')
                   for column in (0, 1) for forward in (False, True)]
        queries += [(-1, date(2015, 1, 2).toordinal(), 0, False)]
        symbols, days, columns, forwards = zip(*reversed(queries), strict=True)
        actual_days, actual_prices = self.executor.resolve(
            np.array(symbols, dtype=np.int32), np.array(days, dtype=np.int32),
            np.array(columns, dtype=np.int8), np.array(forwards, dtype=np.bool_))
        for index, (symbol, day, column, forward) in enumerate(reversed(queries)):
            expected = None if symbol < 0 else daily.price(self.fixture.reader,
                self.inputs.symbols[symbol], date.fromordinal(day),
                'price' if column == 0 else 'adjusted', forward=forward)
            if expected is None:
                self.assertEqual(actual_days[index], 0)
                self.assertTrue(np.isnan(actual_prices[index]))
            else:
                self.assertEqual(actual_days[index], expected[0].toordinal())
                self.assertEqual(actual_prices[index], expected[1])

    def test_equal_availability_ties_keep_last_source_report(self):
        source_id = 0
        duplicate_id = len(self.inputs.report_rows)
        copied = SimpleNamespace(**vars(self.inputs))
        copied.report_rows = self.inputs.report_rows + (dict(self.inputs.report_rows[source_id]),)
        for name in ('report_symbol', 'report_known', 'report_fiscal', 'report_cap',
                     'report_enterprise', 'report_yield', 'average_3y'):
            old = getattr(self.inputs, name)
            setattr(copied, name, np.append(old, old[source_id]).astype(old.dtype))
        copied.financial_parameters = np.vstack((self.inputs.financial_parameters,
                                                 self.inputs.financial_parameters[source_id]))
        copied.pool_offsets, copied.pool_report_ids = {}, {}
        copied.pool_known, copied.pool_fiscal = {}, {}
        sid = int(self.inputs.report_symbol[source_id])
        for pool in ('cached', 'legacy'):
            old = self.inputs.pool_report_ids[pool]
            position = int(np.flatnonzero(old == source_id)[0])
            identities = np.insert(old, position+1, duplicate_id)
            offsets = self.inputs.pool_offsets[pool].copy()
            offsets[sid+1:] += 1
            copied.pool_report_ids[pool] = identities
            copied.pool_offsets[pool] = offsets
            copied.pool_known[pool] = copied.report_known[identities]
            copied.pool_fiscal[pool] = copied.report_fiscal[identities]
        executor = self.module.attach(copied, limits=dict(threads=4))
        try:
            known = int(self.inputs.report_known[source_id])
            outputs = executor.select_reports(np.array([known, known+1], dtype=np.int32))
            for selected in outputs:
                self.assertEqual(selected[0, sid], -1)
                self.assertEqual(selected[1, sid], duplicate_id)
        finally:
            executor.close()

    def test_numeric_batch_and_single_row_preserve_source_operation_order(self):
        self.executor.evaluate([('2015-01-02', '2016-01-04', 'cached')], dict(filters=[]))
        sample = self.executor.trace['numeric_inputs']
        matrix = np.tile(sample, (2048, 1))
        ii = self.inputs.policy.input_index
        matrix[:, ii['report_cap']] *= 1 + np.arange(len(matrix))*1e-6
        matrix[:, ii['bankruptcy']] = np.arange(len(matrix)) % 2
        matrix[::13, ii['average_3y']] = np.nan
        expected = self.inputs.policy.evaluate(matrix)
        actual = self.executor.calculate(matrix)
        # Exact array equality also detects row reordering under native threads.
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(self.executor.calculate(matrix[:1]), expected[:1])

    def test_each_strict_threshold_at_its_source_value(self):
        jobs = [('2015-07-01', '2016-06-30', 'cached')]
        book = self.source_books(jobs)[0]
        values = {field: value for symbol, field, value in book['filters'] if symbol == 'A'}
        self.assertEqual(set(values), set(metrics.FILTERS))
        for field, value in values.items():
            for operator in ('lt', 'gt'):
                with self.subTest(field=field, operator=operator):
                    options = dict(baseline.options('cached', 'F0'), min_cap=0., min_ev=0.,
                        filters=[dict(field=field, op=operator, value=value)], rank_from=2, rank_to=100)
                    self.assert_books(jobs, options)

    def test_short_adjusted_entry_and_bankruptcy_keep_source_eligibility(self):
        jobs = [('2015-01-02', '2015-01-05', 'cached'),
                ('2016-02-29', '2016-03-07', 'legacy')]
        options = dict(baseline.options('cached', 'F2'), min_cap=0., min_ev=0.)
        # Pool is a property of each prepared book; selection uses its pool.
        for job in jobs:
            selected_options = dict(options, pool=job[2])
            self.assert_books([job], selected_options)
        with patch.object(rules,'BANKRUPT', {(2015, 'A')}):
            # Bankruptcy overrides belong to the immutable input identity.
            # Attach a new generation instead of mutating an attached one.
            previous_inputs, previous_executor = self.inputs, self.executor
            self.inputs = core.NumericInputs(self.fixture.reader, s)
            self.executor = self.module.attach(self.inputs, limits=dict(capture=True, threads=4))
            try:
                source, actual = self.assert_books([('2015-07-01', '2016-06-30', 'cached')],
                    dict(baseline.options('cached', 'F0'), min_cap=0., min_ev=0.))
            finally:
                self.executor.close()
                self.inputs.close()
                self.inputs, self.executor = previous_inputs, previous_executor
        holding = next(row for row in actual[0]['snapshots'] if row[0] == 'A')
        self.assertEqual(holding[-2:], (-1., 'Bankruptcy'))

    def test_empty_batches_errors_and_request_counters(self):
        self.executor.begin(dict(options=baseline.options('legacy', 'F0')))
        self.assertEqual(self.executor.evaluate([]), [])
        for matrices in (self.executor.select_reports(np.empty(0, dtype=np.int32)),):
            self.assertEqual(matrices[0].shape, (0, len(self.inputs.symbols)))
        days, values = self.executor.resolve(np.empty(0, dtype=np.int32), np.empty(0, dtype=np.int32),
                                            np.empty(0, dtype=np.int8), np.empty(0, dtype=np.bool_))
        self.assertEqual((len(days), len(values)), (0, 0))
        with self.assertRaises(ValueError):
            self.executor.calculate(np.ones((1, 1)))
        with self.assertRaises(ValueError):
            self.executor.resolve(np.array([0]), np.array([1]), np.array([2]), np.array([False]))
        limited = self.module.attach(self.inputs, limits=dict(max_query_rows=1, threads=4))
        try:
            with self.assertRaisesRegex(ValueError, 'row limit'):
                limited.select_reports(np.array([date(2015, 1, 2).toordinal()], dtype=np.int32))
            with self.assertRaisesRegex(ValueError, 'row limit'):
                limited.resolve(np.array([0, 0], dtype=np.int32), np.array([1, 2], dtype=np.int32),
                                np.array([0, 1], dtype=np.int8), np.array([False, True]))
        finally:
            limited.close()
        self.executor.begin(dict(options=baseline.options('legacy', 'F0')))
        self.assertEqual(self.executor.stats['price_queries'], 0)
        self.executor.deadline = time.perf_counter()-1
        with self.assertRaises(TimeoutError):
            self.executor.select_reports(np.array([date(2015, 1, 2).toordinal()], dtype=np.int32))

    def test_close_releases_only_owned_resources(self):
        before = self.inputs.raw_values[:10].copy()
        directory = self.executor.stats.get('temporary_directory')
        self.executor.close()
        self.executor.close()
        np.testing.assert_array_equal(self.inputs.raw_values[:10], before)
        if directory:
            self.assertFalse(Path(directory).exists())
        with self.assertRaises(RuntimeError):
            self.executor.select_reports(np.array([date(2015, 1, 2).toordinal()], dtype=np.int32))


if __name__ == '__main__':
    unittest.main()
