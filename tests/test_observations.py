"""Private fixtures for admitted roots, temporal observations and bounded work."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from datetime import date, timedelta
import json
import math
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from backtest import observations as obs
from backtest.financial import books, rules
from backtest.inputs import financial_inputs as financial, observation_inputs as source, daily, sqlite_observations
from numerical_fixture import SyntheticDailyFixture
from prepared_inputs_fixture import PreparedInputs


def statement(fiscal, *, earnings_yield=.3):
    day = date.fromisoformat(fiscal)
    return dict(fiscal=day, known=day+rules.LAG, market_cap=150e6, enterprise=180e6,
                enterprise_value=180e6, ebitda=180e6*earnings_yield,
                ebitda_yield=earnings_yield, **{'yield': earnings_yield})


def state(value, reason=None):
    return dict(value=value, valid=reason is None, reason=reason, rows=[dict(index=0, sha256='a'*64)])


def annual(revenue=100., income=10.):
    return dict(revenue=state(revenue), operatingIncome=state(income))


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript(source.SCHEMA + 'CREATE TABLE companies(symbol TEXT PRIMARY KEY);')
        self.db.execute("INSERT INTO companies VALUES('A')")
        self.reports = [statement(f'{year}-06-30') for year in (2012, 2013, 2014)]
        self.annual = {f'{year}-06-30': annual(100., income) for year, income in ((2012, -10.), (2013, 0.), (2014, 20.))}
        self.root_date = '2015-01-02'
        self.latest_date = '2015-01-05'
        self.lookup = Mock(side_effect=lambda symbol, day, column, forward, slack: (day, 10.))
        self.stale = False

    def view(self, *, admitted=True, latest=None):
        self.db.execute('DELETE FROM observation_annual')
        self.db.execute('DELETE FROM observation_sources')
        self.db.execute('DELETE FROM observation_latest')
        self.db.execute('DELETE FROM observation_metadata')
        self.db.execute('INSERT INTO observation_sources VALUES(?,?,?)',
            ('A', 'income-statement', source.encoded(dict(disposition='valid', sha256='b'*64))))
        self.db.executemany('INSERT INTO observation_annual VALUES(?,?,?,?)',
            [('A', 'income-statement', fiscal, source.encoded(row)) for fiscal, row in self.annual.items()])
        latest = latest or dict(root_date=self.latest_date, admitted=admitted,
            reason=None if admitted else 'NOT_LISTED', candidate_rank=1,
            statement=source.ReadView._statement(self.reports[-1]),
            valuation=dict(market_cap=160e6, enterprise_value=190e6, ebitda=54e6),
            adjusted_price=[self.latest_date, 11.], fiscal_price=['2014-06-30', 10.],
            valuation_price=[self.latest_date, 11.])
        source.store_latest(self.db, 'A', 'legacy', latest)
        source.store_latest(self.db, 'A', 'cached', latest)
        metadata = source.finish(self.db, self.latest_date)
        def validate():
            if self.stale:
                raise ValueError('Fixture attachment is stale.')
        def reports(symbol, pool):
            return [source.ReadView._statement(row) for row in self.reports] if symbol == 'A' else []
        view = source.ReadView('generation-fixture', self.db, validate, reports, self.lookup,
            expected=metadata, max_history=16384, max_record_bytes=4*1024*1024,
            bounds=dict(historical_through=self.root_date, latest_date=self.latest_date,
                        population=1, report_rows=len(self.reports), max_reports=len(self.reports),
                        max_annual=len(self.annual)),
            populations=lambda checkpoint: books.pools({'A': self.reports}),
            cached=lambda symbol: symbol == 'A', session=lambda day: str(day) == self.root_date)
        self.addCleanup(view.close)
        return view

    def contexts(self, **overrides):
        return [dict(id='root', kind='root', symbol='A', pool='legacy', mode='historical',
                     date=self.root_date, **overrides)]

    def request(self, parameter='annual.revenue', count=1, context='root', identity='value'):
        return dict(id=identity, parameter=parameter, context=context, count=count)

    def result(self, view=None, *, parameter='annual.revenue', count=1, contexts=None, context='root'):
        plan = obs.plan([self.request(parameter, count, context)], contexts or self.contexts())
        return obs.observe(plan, view or self.view()).to_dict()['results'][0]

    def test_catalog_and_example_return_ingredients_without_formula_arithmetic(self):
        self.assertEqual({item['id'] for item in obs.catalog()}, set(obs._CATALOG))
        view = self.view()
        block = obs.example(view, symbol='A', pool='legacy', mode='historical', screen_date=self.root_date)
        values = block.to_dict()
        self.assertEqual(values['format'], 'parameter-observations')
        self.assertEqual([m['value'] for m in values['results'][1]['members']], [-.1, 0., .2])
        self.assertEqual(values['results'][0]['members'][0]['value'], 100.)
        self.assertEqual(values['results'][2]['members'][0]['value'], 180e6)
        self.assertEqual(values['results'][2]['unit'], 'USD')
        self.assertTrue(all(call.args[2] == 'price' for call in self.lookup.call_args_list))

    def test_explicit_owner_scope_is_checked_and_preserved(self):
        view = self.view()
        contexts = [dict(id='root', kind='root', symbol='A', pool='cached',
                         mode='latest', date=self.latest_date,
                         owner_scope=dict(kind='prepared', book=0))]
        result = obs.observe(obs.plan([self.request()], contexts), view).to_dict()
        self.assertEqual(result['roots'][0]['owner_scope'], contexts[0]['owner_scope'])
        self.assertEqual(result['contexts'][0]['owner_scope'], contexts[0]['owner_scope'])
        contexts[0]['owner_scope'] = dict(kind='prepared', book=1)
        with self.assertRaises(obs.ObservationError):
            obs.observe(obs.plan([self.request()], contexts), view)
        contexts[0]['owner_scope'] = dict(kind='prepared', book=True)
        with self.assertRaises(obs.ObservationError):
            obs.plan([self.request()], contexts)

    def test_plan_strict_shape_types_parameters_dates_and_immutable_snapshot(self):
        requests, contexts = [self.request()], self.contexts()
        plan = obs.plan(requests, contexts)
        requests[0]['parameter'] = 'unknown'
        contexts[0]['symbol'] = 'changed'
        self.assertEqual(plan.to_dict()['requests'][0]['parameter'], 'annual.revenue')
        with self.assertRaises(AttributeError): plan.document = '{}'
        cases = [([dict(self.request(), count=True)], self.contexts(), 'INVALID_SHAPE'),
                 ([dict(self.request(), extra=1)], self.contexts(), 'INVALID_SHAPE'),
                 ([dict(self.request(), parameter=[])], self.contexts(), 'UNKNOWN_PARAMETER'),
                 ([dict(self.request(), context=[])], self.contexts(), 'INVALID_SHAPE'),
                 ([dict(self.request(), parameter='market.enterprise_value', count=2)], self.contexts(), 'INVALID_SHAPE'),
                 ([self.request()], [dict(self.contexts()[0], date='20150102')], 'INVALID_DATE'),
                 ([self.request()], [dict(self.contexts()[0], kind='calendar')], 'UNSUPPORTED_OPERATION')]
        for requests, contexts, code in cases:
            with self.subTest(code=code), self.assertRaises(obs.ObservationError) as caught:
                obs.plan(requests, contexts)
            self.assertEqual(caught.exception.code, code)

    def test_context_graph_rejects_duplicates_missing_parents_cycles_and_future_dates(self):
        for contexts, code in ((self.contexts()*2, 'INVALID_SHAPE'),
                ([dict(id='at', kind='at', parent='absent', date='2014-01-01')], 'MISSING_REFERENCE'),
                ([dict(id='at', kind='at', parent='back', date='2014-01-01'),
                  dict(id='back', kind='at', parent='at', date='2014-01-01')], 'DEPENDENCY_CYCLE'),
                (self.contexts()+[dict(id='at', kind='at', parent='root', date='2015-01-03')], 'FUTURE_DATE')):
            with self.subTest(code=code), self.assertRaises(obs.ObservationError) as caught:
                obs.plan([], contexts)
            self.assertEqual(caught.exception.code, code)
        contexts = self.contexts()
        for index in range(32):
            contexts.append(dict(id=f'c{index}', kind='lookback', parent='root' if index == 0 else f'c{index-1}', months=1))
        with self.assertRaises(obs.ObservationError) as caught: obs.plan([], contexts)
        self.assertEqual(caught.exception.code, 'WORK_LIMIT')

    def test_forged_or_malformed_plan_fails_before_input_access(self):
        inputs = Mock()
        for plan in ({}, obs.ObservationPlan('{}'), obs.ObservationPlan('invalid')):
            with self.assertRaises(obs.ObservationError): obs.observe(plan, inputs)
        inputs.validate.assert_not_called()

    def test_month_end_and_leap_day_contexts_resolve_without_reranking_root(self):
        self.root_date = '2024-05-31'
        contexts = self.contexts()+[dict(id='back', kind='lookback', parent='root', months=3),
                                   dict(id='year', kind='lookback', parent='back', months=12)]
        view = self.view()
        plan = obs.plan([self.request(context='year')], contexts)
        block = obs.observe(plan, view).to_dict()
        self.assertEqual([c['date'] for c in block['contexts']], ['2024-05-31', '2024-02-29', '2023-02-28'])
        self.assertEqual(block['results'][0]['candidate_rank'], block['roots'][0]['candidate_rank'])
        self.assertEqual(len(block['roots']), 1)

    def test_strict_ninety_day_availability_reselects_at_earlier_context(self):
        self.root_date = '2024-04-02'
        self.reports = [statement('2023-12-31')]
        self.annual = {'2023-12-31': annual()}
        contexts = self.contexts()+[dict(id='equal', kind='at', parent='root', date='2024-03-30'),
                                   dict(id='next', kind='at', parent='root', date='2024-03-31')]
        view = self.view()
        requests = [self.request(context=context, identity=context) for context in ('equal', 'next')]
        results = obs.observe(obs.plan(requests, contexts), view).to_dict()['results']
        self.assertEqual(results[0]['reason'], 'NO_ELIGIBLE_REPORT')
        self.assertEqual(results[0]['members'], [])
        self.assertTrue(results[1]['valid'])
        self.assertEqual(results[1]['anchor'], '2023-12-31')

    def test_anchor_ages_800_and_801_are_distinct_from_old_history_members(self):
        fiscal = date(2019, 6, 30)
        for age in (800, 801):
            with self.subTest(age=age):
                self.root_date = str(fiscal + timedelta(days=age))
                self.reports = [statement(str(fiscal))]
                self.annual = {f'{year}-06-30': annual() for year in range(2010, 2020)}
                result = self.result(count=10)
                if age == 800:
                    self.assertTrue(result['valid'])
                    self.assertEqual(len(result['members']), 10)
                else:
                    self.assertEqual(result['reason'], 'ROOT_NOT_ADMITTED')
        self.root_date = '2022-01-03'
        self.reports.append(statement('2021-06-30'))
        contexts = self.contexts()+[dict(id='old', kind='at', parent='root', date=str(fiscal+timedelta(days=801)))]
        self.assertEqual(self.result(contexts=contexts, context='old')['reason'], 'STALE_REPORT')

    def test_missing_middle_year_preserves_every_bucket_and_rejects_partial_history(self):
        del self.annual['2013-06-30']
        result = self.result(parameter='annual.operating_margin', count=3)
        self.assertFalse(result['valid'])
        self.assertEqual([member['fiscal_year'] for member in result['members']], [2012, 2013, 2014])
        self.assertEqual(result['members'][1]['reason'], 'MISSING_FISCAL_YEAR')
        self.assertIsNone(result['members'][1]['fiscal_date'])

    def test_exact_anchor_missing_field_cannot_use_a_different_report(self):
        self.annual['2014-01-01'] = annual(999, 999)
        self.annual['2014-06-30']['revenue'] = state(None, 'CONFLICTING_INPUT')
        result = self.result()
        self.assertEqual(result['anchor'], '2014-06-30')
        self.assertEqual(result['reason'], 'CONFLICTING_INPUT')
        self.assertIsNone(result['members'][0]['value'])

    def test_newer_incomplete_prior_year_does_not_fall_back_to_complete_member(self):
        self.annual['2013-12-31'] = dict(revenue=state(None, 'MISSING_INPUT'), operatingIncome=state(99))
        result = self.result(parameter='annual.operating_margin', count=3)
        self.assertEqual(result['members'][1]['fiscal_date'], '2013-12-31')
        self.assertEqual(result['members'][1]['reason'], 'MISSING_INPUT')

    def test_shifted_fiscal_ends_follow_calendar_year_buckets_not_spacing(self):
        self.annual.pop('2013-06-30')
        self.annual['2013-03-31'] = annual(100, 7)
        result = self.result(parameter='annual.operating_margin', count=3)
        self.assertEqual([m['value'] for m in result['members']], [-.1, .07, .2])

    def test_signed_zero_denominator_and_nonfinite_results(self):
        for revenue, income, expected, reason in ((-100., -5., -100., None), (0., 0., 0., None),
                (100., 0., 100., None)):
            self.annual['2014-06-30'] = annual(revenue, income)
            self.assertEqual(self.result()['members'][0]['value'], expected)
            margin = self.result(parameter='annual.operating_margin')
            self.assertEqual(margin['reason'], 'NONPOSITIVE_DENOMINATOR' if revenue <= 0 else None)
            if revenue > 0: self.assertEqual(margin['members'][0]['value'], 0.)
        self.annual['2014-06-30'] = annual(1e-300, 1e300)
        result = self.result(parameter='annual.operating_margin')
        self.assertEqual(result['reason'], 'NONFINITE_RESULT')
        self.assertIsNone(result['members'][0]['value'])

    def test_latest_root_uses_exact_prepared_ev_and_earlier_context_reconstructs(self):
        contexts = [dict(self.contexts()[0], mode='latest', date=self.latest_date),
                    dict(id='before', kind='at', parent='root', date=self.root_date)]
        requests = [self.request('market.enterprise_value', context=context, identity=context)
                    for context in ('root', 'before')]
        block = obs.observe(obs.plan(requests, contexts), self.view()).to_dict()
        self.assertEqual([item['members'][0]['value'] for item in block['results']], [190e6, 180e6])
        self.assertEqual(block['results'][1]['candidate_rank'], 1)
        self.assertEqual(block['results'][1]['members'][0]['evidence']['lookup_policy'], 'existing-entry-valuation')

    def test_latest_denial_reads_no_annual_fields_and_retains_detailed_reason(self):
        view = self.view(admitted=False)
        contexts = [dict(self.contexts()[0], mode='latest', date=self.latest_date)]
        with patch.object(view, 'company', side_effect=AssertionError('Annual evidence read')):
            block = obs.observe(obs.plan([self.request()], contexts), view).to_dict()
        self.assertEqual(block['results'][0]['reason'], 'ROOT_NOT_ADMITTED')
        self.assertEqual(block['roots'][0]['reason'], 'NOT_LISTED')

    def test_cutoffs_exact_sessions_latest_root_and_missing_projection_fail_operation(self):
        for changed in (dict(date='2015-01-03'), dict(date='1995-01-02'), dict(mode='latest', date=self.root_date)):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                obs.observe(obs.plan([self.request()], [dict(self.contexts()[0], **changed)]), self.view())
        view = self.view()
        self.db.execute("DELETE FROM observation_latest WHERE symbol='A'")
        # Projection is incompatible even if a caller attempts to repair only its digest.
        self.db.execute('DELETE FROM observation_metadata')
        with self.assertRaisesRegex(ValueError, 'missing|stale'):
            obs.observe(obs.plan([self.request()], self.contexts()), view)

    def test_missing_price_denies_root_without_inventing_a_value(self):
        self.lookup.side_effect = lambda *args: None
        block = obs.observe(obs.plan([self.request('market.enterprise_value')], self.contexts()), self.view()).to_dict()
        self.assertEqual(block['roots'][0]['reason'], 'MISSING_PRICE')
        self.assertEqual(block['results'][0]['reason'], 'ROOT_NOT_ADMITTED')

    def test_ev_preserves_helper_arithmetic_actual_dates_and_missing_earlier_prices(self):
        fiscal = self.reports[-1]['fiscal']
        self.lookup.side_effect = lambda symbol, day, column, forward, slack: (
            (day+timedelta(days=3), 7.) if forward else (day-timedelta(days=2), 3.))
        expected = books.entry_valuation(self.reports[-1], date.fromisoformat(self.root_date),
            lambda day, column, forward, slack: self.lookup('A', day, column, forward, slack))
        result = self.result(parameter='market.enterprise_value')
        self.assertEqual(result['members'][0]['value'], expected[3])
        lookups = result['members'][0]['evidence']['lookups']
        self.assertEqual(lookups[0]['observation'], [str(fiscal-timedelta(days=2)), 3.])
        self.assertEqual(lookups[1]['observation'], ['2015-01-05', 7.])
        self.assertEqual([item['slack'] for item in lookups], [7, 4])
        self.lookup.side_effect = lambda symbol, day, column, forward, slack: None if day == date(2014, 10, 2) else (day, 10.)
        contexts = self.contexts()+[dict(id='earlier', kind='at', parent='root', date='2014-10-02')]
        result = self.result(parameter='market.enterprise_value', contexts=contexts, context='earlier')
        self.assertEqual(result['reason'], 'MISSING_PRICE')
        self.assertEqual(result['candidate_rank'], 1)

    def test_latest_can_advance_beyond_historical_cutoff(self):
        view = self.view()
        view._bounds['historical_through'] = '2014-12-31'
        with self.assertRaisesRegex(ValueError, 'outside saved'):
            self.result(view)
        contexts = [dict(self.contexts()[0], mode='latest', date=self.latest_date)]
        self.assertTrue(self.result(view, contexts=contexts)['valid'])

    def test_work_and_output_limits_reject_without_truncation(self):
        view = self.view()
        plan = obs.plan([self.request()], self.contexts(), dict(rows=1))
        with patch.object(view, 'admit', side_effect=AssertionError('Admission read')):
            with self.assertRaises(obs.ObservationError) as caught: obs.observe(plan, view)
        self.assertEqual(caught.exception.code, 'WORK_LIMIT')
        request = self.request('market.enterprise_value')
        ordinary = obs.observe(obs.plan([request], self.contexts()), view)
        exact = len(ordinary.to_json().encode('utf-8'))
        self.assertEqual(len(obs.observe(obs.plan([request], self.contexts(), dict(bytes=exact)), view).to_json().encode('utf-8')), exact)
        with self.assertRaises((ValueError, obs.ObservationError)):
            obs.observe(obs.plan([request], self.contexts(), dict(bytes=exact-1)), view)
        for key in obs.CEILINGS:
            with self.assertRaises(obs.ObservationError): obs.plan([], [], {key: obs.CEILINGS[key]+1})

    def test_structural_limits_and_complete_population_work_are_paid_before_reads(self):
        with self.assertRaises(obs.ObservationError):
            obs.plan([self.request(identity='one'), self.request(identity='two')], self.contexts(), dict(requests=1))
        with self.assertRaises(obs.ObservationError):
            obs.plan([self.request(count=3)], self.contexts(), dict(members=2))
        with self.assertRaises(obs.ObservationError):
            obs.plan([], self.contexts()+[dict(id='back', kind='lookback', parent='root', months=1)], dict(contexts=1))
        view = self.view()
        bounds = view.bounds
        exact = (2 * (bounds['report_rows'] + bounds['population']) + 1
                 + bounds['max_reports'] + 2 * bounds['max_annual'] + 9
                 + bounds['max_reports'] + bounds['max_annual'] + 1)
        self.assertTrue(obs.observe(obs.plan([self.request()], self.contexts(), dict(rows=exact)), view).to_dict()['results'][0]['valid'])
        with patch.object(view, 'admit', side_effect=AssertionError('Complete population read')):
            with self.assertRaises(obs.ObservationError):
                obs.observe(obs.plan([self.request()], self.contexts(), dict(rows=exact-1)), view)

    def test_heavy_unrequested_evidence_is_rejected_before_json_decode(self):
        self.annual['2012-06-30']['revenue']['rows'] = [dict(index=index, sha256='c'*64) for index in range(10000)]
        view = self.view()
        with patch.object(view, '_json', wraps=view._json) as decode:
            with self.assertRaisesRegex(ValueError, 'company facts exceed'):
                obs.observe(obs.plan([self.request()], self.contexts(), dict(bytes=10000)), view)
            decode.assert_not_called()

    def test_source_edit_during_observation_rejects_the_complete_block(self):
        view = self.view()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'observations.py'
            original = Path(obs.__file__).read_bytes()
            path.write_bytes(original)
            calls = 0
            def changed():
                nonlocal calls
                calls += 1
                if calls == 5:
                    path.write_bytes(original+b'\n# changed private policy\n')
            with patch.object(obs, '__file__', str(path)):
                with self.assertRaises(obs.ObservationError) as caught:
                    obs.observe(obs.plan([self.request()], self.contexts()), view, changed)
                self.assertEqual(caught.exception.code, 'STALE_INPUT_GENERATION')

    def test_cancellation_staleness_source_change_and_detachment(self):
        view = self.view()
        plan = obs.plan([self.request()], self.contexts())
        with self.assertRaisesRegex(RuntimeError, 'cancel'):
            obs.observe(plan, view, lambda: (_ for _ in ()).throw(RuntimeError('cancel')))
        count = 0
        def stale_at_end():
            nonlocal count
            count += 1
            if count > 4: self.stale = True
        with self.assertRaisesRegex(ValueError, 'stale'): obs.observe(plan, view, stale_at_end)
        self.stale = False
        with patch.object(obs, '_LOADED_POLICY', 'changed'):
            with self.assertRaises(obs.ObservationError): obs.observe(plan, view)
        block = obs.observe(plan, view)
        before = block.to_json()
        view.close()
        self.assertEqual(block.to_json(), before)
        self.assertEqual(json.dumps(block.to_dict(), allow_nan=False, sort_keys=True),
                         json.dumps(json.loads(before), allow_nan=False, sort_keys=True))
        with self.assertRaisesRegex(ValueError, 'closed'): obs.observe(plan, view)


class PopulationAdmissionTests(unittest.TestCase):
    """The daily SQLite view admits a complete population with the legacy buffer.

    Callers add companies to `db` before they borrow `view()`.
    """
    def setUp(self):
        self.daily = SyntheticDailyFixture()
        self.daily.setUp()
        self.addCleanup(self.daily.doCleanups)
        self.db = self.daily.db
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder)
            financial.publish(raw, 'A', 'income-statement', [
                dict(date='2014-06-30', reportedCurrency='USD', revenue=100, operatingIncome=-5),
                dict(date='2013-06-30', reportedCurrency='USD', revenue=None)], {}, raw/'coverage.json')
            source.store_annual(self.db, 'A', financial.resolve_history(raw, 'A'))
        for pool in ('legacy', 'cached'):
            source.store_latest(self.db, 'A', pool, dict(admitted=True, root_date='2016-12-30'))
        source.finish(self.db, '2016-12-30')
        self.db.execute('INSERT INTO metadata VALUES(?,?)',
                        ('daily_inputs', json.dumps(dict(inputs=dict(historical_through='2016-12-30')))))
        self.db.commit()

    def view(self):
        view = sqlite_observations.prepared_view(self.db, lambda: None)
        self.addCleanup(view.close)
        return view

    def add_population(self):
        """Add 260 companies; Z000-Z009 have no cached prices."""
        for index in range(260):
            symbol = f'Z{index:03d}'
            self.db.execute('INSERT INTO companies VALUES(?,?,?,?)', (symbol, symbol, 'NYSE', 'Energy'))
            self.db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',
                (symbol, '2014-06-30', '2014-09-28', 150e6, 180e6, 162e6, .9))
            if index >= 10:
                self.db.executemany('INSERT INTO prices VALUES(?,?,?,?)',
                    [(symbol, day, 10., 10.) for day in ('2014-06-30', '2015-01-02')])
        self.db.commit()

    def test_complete_population_buffer_order_and_uncached_names(self):
        self.add_population()
        expected_books = daily.histories(self.db)
        expected_selected, expected_ranks = books.candidates(expected_books, date(2015, 1, 2))
        view = self.view()
        roots = [dict(id=symbol+pool, kind='root', symbol=symbol, pool=pool, mode='historical', date='2015-01-02')
                 for symbol, pool in (('Z249', 'legacy'), ('Z250', 'legacy'), ('Z005', 'legacy'), ('Z250', 'cached'))]
        requests = [dict(id=root['id'], parameter='market.enterprise_value', context=root['id'], count=1) for root in roots]
        block = obs.observe(obs.plan(requests, roots), view).to_dict()
        decisions = block['roots']
        self.assertEqual([item['admitted'] for item in decisions], [True, False, False, True])
        self.assertEqual(decisions[0]['candidate_rank'], expected_ranks['Z249'])
        self.assertEqual(decisions[0]['candidate_rank'], 250)
        self.assertEqual(decisions[1]['reason'], 'OUTSIDE_LEGACY_BUFFER')
        self.assertEqual(decisions[2]['reason'], 'MISSING_CACHED_PRICES')
        valuation = books.entry_valuation(expected_selected['legacy']['Z249'], date(2015, 1, 2),
            lambda day, column, forward, slack: daily.price(self.db, 'Z249', day, column, forward, slack))
        self.assertEqual(decisions[0]['valuation']['enterprise_value'], valuation[3])
        # A request containing only the low-ranked cached name cannot promote it.
        alone = obs.observe(obs.plan([requests[1]], [roots[1]]), view).to_dict()
        self.assertFalse(alone['roots'][0]['admitted'])


class CompleteChainTests(unittest.TestCase):
    def test_real_preparation_to_provider_example_detaches_without_future_returns(self):
        with PreparedInputs() as inputs, inputs.view() as view:
            block = obs.example(view, symbol='TEST', pool='legacy', mode='latest', screen_date='2015-10-20')
            values = block.to_dict()
            self.assertEqual(values['results'][2]['members'][0]['value'], 270e6)
            self.assertEqual(values['results'][1]['reason'], 'MISSING_INPUT')
            historical = obs.example(view, symbol='TEST', pool='legacy', mode='historical', screen_date='2015-01-02')
            self.assertTrue(historical.to_dict()['roots'][0]['admitted'])
        text = block.to_json()
        self.assertEqual(block.to_dict(), json.loads(text))
        self.assertNotIn('return', text)


if __name__ == '__main__':
    unittest.main()
