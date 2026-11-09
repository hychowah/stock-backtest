"""Market-bound formulas use prepared local dates and one USD basis per context."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from datetime import date
import json
import math
import unittest

from backtest.inputs import book_store, fact_view, facts
from backtest.variables import columns, definitions as d, parameters
import book_store_fixture as store
from test_variable_definitions import binary, bundle, definition, entry


DISPLAY = {'scalar': 'number', 'USD': 'usd', 'USD/share': 'usd_per_share', 'share': 'shares'}


def program(expression, unit='USD', catalog=parameters.V4):
    value = dict(definition(expression, unit, DISPLAY[unit]), version=3, parameter_catalog=catalog,
                 temporal_policy=d.MARKET_TEMPORAL_POLICY if catalog == parameters.V4 else d.TEMPORAL_POLICY)
    return d.require_program(d.validate(bundle(entry(value))))


def parameter(identity):
    return dict(op='parameter', id=identity)


class MarketFormulas(unittest.TestCase):
    def setUp(self):
        self.db = store.connection()
        self.addCleanup(self.db.close)
        db = self.db.research
        store.record(db, self.db, '2015-01-05')
        identity = json.loads(db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0])
        identity['latest_dates'] = dict(us='2015-01-05', hk='2015-01-05')
        db.execute("UPDATE metadata SET value=? WHERE key='identity'", (json.dumps(identity),))
        self.symbol = '0001.HK'
        store.company(self.db, self.symbol, exchange='HKSE')
        db.execute('INSERT INTO company_markets VALUES(?,?,?)', (self.symbol, 'hk', 'HKD'))
        for day in ('2012-06-29', '2013-06-28', '2014-06-30', '2014-10-01', '2014-10-30', '2014-10-31',
                    '2015-01-02', '2015-01-05'):
            db.execute('INSERT INTO local_sessions VALUES(?,?)', ('hk', day))
            store.price(self.db, self.symbol, day, 10.)
        # A foreign close needs the previous completed US observation.
        store.session(self.db, '2015-01-02', 100., month3=2., year10=3.)
        store.session(self.db, '2015-01-05', 200., month3=4., year10=5.)
        for day, cny, jpy, hkd in [('2014-09-30', .4, .03, .15), ('2014-10-29', .5, .04, .15),
                                    ('2014-10-30', .5, .04, .15), ('2015-01-01', .3, .02, .1),
                                    ('2015-01-04', .2, .01, .2)]:
            db.executemany('INSERT INTO fx_days VALUES(?,?,?,?)',
                           [(currency, day, rate, None) for currency, rate in [('CNY', cny), ('JPY', jpy), ('HKD', hkd)]])
        annual, metadata = {}, {}
        for year, currency, revenue in [(2012, 'CNY', 100.), (2013, 'JPY', 200.), (2014, 'USD', 300.)]:
            fiscal, known = f'{year}-06-30', f'{year}-10-30'
            annual[fiscal] = {name: store.state(value) for name, value in dict(
                revenue=revenue, operatingIncome=-0., weightedAverageShsOut=10., eps=2.).items()}
            metadata[fiscal] = dict(currency=currency, known=known, basis='fiscal-plus-months')
            db.execute('INSERT INTO foreign_reports VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (self.symbol, fiscal, known, currency, 1e8, 100e6, 10e6, 5e6,
                        'fiscal-plus-months', 1e9))
        facts.store_annual(db, self.symbol, dict(annual={'income-statement': annual},
            sources={'income-statement': store.source('income-statement')},
            metadata={'income-statement': metadata}))
        self.root = dict(symbol=self.symbol, pool='cached', mode='historical', date='2015-01-05')

    def evaluate(self, expression, unit='USD', root=None):
        roots = [root or self.root]
        with fact_view.View(self.db, lambda: None, lambda: None, market='hk') as view:
            formulas = columns.Formulas(program(expression, unit))
            formulas.require_contexts(roots)
            decisions = view.admit(roots)
            self.assertTrue(decisions[0]['admitted'], decisions[0]['reason'])
            values = formulas.evaluate(roots, view, lambda: None, decisions=decisions)
            explained = formulas.explain(roots, view, lambda: None, decisions=decisions)
            result, = explained['results']
            self.assertEqual(values[0][result['variable_id'], result['revision']],
                             (result['value'], result['valid'], result['reason']))
            return result, explained

    def test_annual_history_uses_each_report_currency_at_one_context_date(self):
        result, block = self.evaluate(dict(op='annual', stat='mean', count=3, parameter='annual.revenue'))
        self.assertEqual(result['value'], (20. + 2. + 300.) / 3)
        members = block['observations']['results'][0]['members']
        self.assertEqual([item['evidence']['fields']['revenue']['source_currency'] for item in members],
                         ['CNY', 'JPY', 'USD'])
        self.assertEqual([item['evidence']['fields']['revenue']['fx_date'] for item in members],
                         ['2015-01-04', '2015-01-04', '2015-01-05'])
        self.assertEqual(members[-1]['evidence']['availability_model'], 'fiscal-plus-months')
        growth, _ = self.evaluate(dict(op='annual', stat='growth', count=3, parameter='annual.revenue'), 'scalar')
        self.assertEqual(growth['value'], 14.)

    def test_market_availability_and_derived_contexts_use_their_own_date(self):
        expression = parameter('annual.revenue')
        for day, expected in [('2014-10-01', 6.), ('2014-10-30', 8.), ('2014-10-31', 300.)]:
            with self.subTest(day=day):
                result, _ = self.evaluate(dict(op='at', date=day, arg=expression))
                self.assertEqual(result['value'], expected)
        shifted, _ = self.evaluate(dict(op='lookback', months=3, arg=expression))
        self.assertEqual(shifted['value'], 6.)

    def test_shares_eps_and_signed_zero_keep_their_units(self):
        shares, _ = self.evaluate(parameter('annual.weighted_average_basic_shares'), 'share')
        self.assertEqual(shares['value'], 10.)
        eps, _ = self.evaluate(dict(op='at', date='2014-10-01', arg=parameter('annual.basic_eps')), 'USD/share')
        self.assertEqual(eps['value'], .06)
        zero, _ = self.evaluate(parameter('annual.operating_income'))
        self.assertEqual(math.copysign(1., zero['value']), -1.)

    def test_local_stock_observation_uses_actual_day_fx_and_prior_us_yield(self):
        price, block = self.evaluate(dict(op='at', date='2015-01-04', arg=parameter('market.adjusted_price')), 'USD/share')
        self.assertEqual(price['value'], 1.)
        evidence = block['observations']['results'][0]['members'][0]['evidence']
        self.assertEqual((evidence['session']['day'], evidence['state']['fx_date']), ('2015-01-02', '2015-01-01'))
        yield_value, _ = self.evaluate(parameter('treasury.us_3m'), 'scalar')
        self.assertEqual(yield_value['value'], .02)

    def test_missing_endpoint_fx_is_unavailable_without_affecting_other_fields(self):
        fiscal = '2014-06-30'
        facts.store_annual(self.db.research, self.symbol, dict(annual={'balance-sheet-statement': {fiscal: dict(totalStockholdersEquity=store.state(20.))}},
            sources={'balance-sheet-statement': store.source('balance-sheet-statement')}, metadata={'balance-sheet-statement': {fiscal:
                dict(currency='EUR', known='2014-10-30', basis='fiscal-plus-months')}}))
        result, _ = self.evaluate(parameter('annual.equity'))
        self.assertEqual((result['valid'], result['reason']), (False, 'MISSING_FX'))
        available, _ = self.evaluate(parameter('annual.revenue'))
        self.assertEqual(available['value'], 300.)

    def test_history_never_reads_a_prior_report_published_after_the_context(self):
        self.db.research.execute("UPDATE foreign_reports SET known='2015-02-01' WHERE fiscal='2013-06-30'")
        self.db.research.execute("UPDATE annual_metadata SET known='2015-02-01' WHERE fiscal='2013-06-30'")
        for identity in ('annual.report_ebitda', 'annual.revenue'):
            with self.subTest(parameter=identity):
                result, _ = self.evaluate(dict(op='annual', stat='mean', count=2, parameter=identity))
                self.assertEqual((result['valid'], result['reason']), (False, 'MISSING_FISCAL_YEAR'))

    def test_equal_date_derived_owner_context_keeps_dated_policy(self):
        rows = [(self.symbol, 1, '2014-06-30', '2014-10-30', '2015-01-05', 10., 999e6, 999e6, 1e8, .1, 10., .08)]
        book_store.store(self.db, dict(market='hk', entry='2015-01-05', latest=True, pool='cached', candidates=1,
                                      rows=rows, metrics=[], filters=[]))
        expression = binary('sub', parameter('owner.market_cap'),
                            dict(op='at', date='2015-01-05', arg=parameter('owner.market_cap')))
        result, _ = self.evaluate(expression, root=dict(self.root, mode='latest'))
        self.assertEqual(result['value'], 799e6)

    def test_policy_namespace_pair_is_explicit(self):
        for catalog, policy in [(parameters.V4, d.TEMPORAL_POLICY), (parameters.V3, d.MARKET_TEMPORAL_POLICY)]:
            with self.subTest(catalog=catalog):
                value = dict(definition(), version=3, parameter_catalog=catalog, temporal_policy=policy)
                with self.assertRaises(d.FormulaError) as caught:
                    d.revision(value)
                self.assertEqual(caught.exception.code, 'UNKNOWN_VERSION')


if __name__ == '__main__':
    unittest.main()
