"""Prepared scope membership, owner lanes from stored books and the dated owner policy."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from contextlib import closing
from datetime import date
import json
import sqlite3
import unittest
from unittest.mock import Mock, patch
from backtest import measure_observations as bridge
from backtest.financial import books, metrics, rules
from backtest.inputs import book_store, daily, facts, research
from prepared_inputs_fixture import PreparedInputs
import test_annual_observations as annual
from test_annual_observations import field, formulas, values, root


class PreparedMeasureTests(unittest.TestCase):
    def test_prepared_scope_membership(self):
        root = dict(mode='latest', pool='cached')
        self.assertTrue(bridge.prepared_scope(root, dict(id='a', root='a', date='2020-01-02')))
        self.assertFalse(bridge.prepared_scope(root, dict(id='b', root='a', date='2020-01-02')))
        # A historical root has no stored owner book, on any date.
        self.assertFalse(bridge.prepared_scope(dict(mode='historical', pool='cached'), dict(id='a', root='a', date='2020-01-02')))
        dated = dict(root, owner_scope=dict(kind='dated'))
        # A prepared owner scope names its stored book by id.
        prepared = dict(root, owner_scope=dict(kind='prepared', book=7))
        self.assertFalse(bridge.prepared_scope(dated, dict(id='a', root='a', date='2020-01-02')))
        self.assertTrue(bridge.prepared_scope(prepared, dict(id='a', root='a', date='2020-01-02')))
        self.assertFalse(bridge.prepared_scope(prepared, dict(id='b', root='a', date='2020-01-02')))

    def test_stored_components_and_missing_lanes(self):
        context = dict(reason=None, evidence=dict(snapshot=dict(market_cap=500.),
            metrics=dict(ev_ebitda=[3.0, .33333333333333337]),
            filters=dict(profit_margin=12.5)))
        self.assertEqual(bridge.lane(context, 'ev_ebitda')['value'], 3.)
        self.assertEqual(bridge.lane(context, 'ebitda_yield')['value'], .33333333333333337)
        margin = bridge.lane(context, 'profit_margin')
        self.assertEqual(margin['value'], .125)
        self.assertEqual(margin['evidence'], dict(source='filters', key='profit_margin', stored=12.5,
                                                  conversion='percent-divided-by-100'))
        self.assertEqual(bridge.lane(context, 'roe')['reason'], 'LEGACY_MEASURE_UNAVAILABLE')
        self.assertEqual(bridge.lane(dict(reason='PREPARED_MEASURE_CONTEXT_UNAVAILABLE', evidence=None), 'pe')['reason'],
                         'PREPARED_MEASURE_CONTEXT_UNAVAILABLE')


class OwnerExtractionTests(unittest.TestCase):
    def test_entry_and_exit_rules_preserve_predecessor_and_lookup_order(self):
        def predecessor(statement, entry_day, exit_day, lookup, bankruptcy):
            # One dividend-adjusted series: the entry valuation price is the buy price.
            fiscal_px, start = lookup(statement['fiscal'], False, 7), lookup(entry_day, True, 4)
            if fiscal_px is None or start is None: return None
            cap = statement['market_cap'] * (start[1] / fiscal_px[1])
            ev = cap + (statement['enterprise'] - statement['market_cap'])
            if ev <= 0 or cap <= 0: return None
            ebitda = statement['yield'] * statement['enterprise']
            if start[0] >= exit_day: return None
            end = lookup(exit_day, False, 10)
            status = 'Scheduled exit'  # A book records only how a holding exited.
            if end is None:
                end = lookup(exit_day, False, 100000)
                status = 'Last available price'
            if end is None or end[0] < start[0]: return None
            ret = -1. if bankruptcy else end[1] / start[1] - 1
            if bankruptcy: status = 'Bankruptcy'
            return [str(statement['fiscal']), str(start[0]), str(end[0]), cap, ev,
                    ebitda, ebitda / ev, ev / ebitda, ret, status]
        def current(statement, entry_day, exit_day, lookup, bankruptcy):
            # books.Screen.decide's order: the entry valuation, then the exit.
            reason, valuation = books.admit(statement, entry_day, lookup, books.ENTRY_SLACK)
            if reason is not None: return None
            _, start, cap, ev, ebitda = valuation
            reason, ending = books.close(start, exit_day, lookup, bankruptcy)
            if reason is not None: return None
            end, ret, status = ending
            return [str(statement['fiscal']), str(start[0]), str(end[0]), cap, ev, ebitda,
                    *books.ebitda_yield_and_multiple(ebitda, ev), ret, status]
        fiscal, entry = date(2018, 12, 31), date(2020, 1, 2)
        statement = dict(fiscal=fiscal, known=fiscal + rules.LAG, market_cap=101., enterprise=153., yield_=.1)
        statement['yield'] = statement.pop('yield_')
        for label, exit_day, missing, bankrupt, zero in (
                ('scheduled', date(2021, 1, 2), None, False, False),
                ('same year', date(2020, 12, 2), None, False, False),
                ('stopped', date(2021, 1, 2), 10, False, False),
                ('bankrupt', date(2021, 1, 2), None, True, False),
                ('no exit', date(2021, 1, 2), 'all_exit', False, True),
                ('zero', date(2021, 1, 2), None, False, True),
                ('no fiscal price', date(2021, 1, 2), 'fiscal', False, False),
                ('no entry price', date(2021, 1, 2), 'entry', False, False),
                ('entry at exit', entry, None, False, False)):
            with self.subTest(label=label):
                report = dict(statement, **{'yield': 0. if zero else .1})
                results, histories = [], []
                for fn in (predecessor, current):
                    calls = []
                    def lookup(day, forward, slack):
                        calls.append((day, forward, slack))
                        if missing == 'fiscal' and slack == 7: return None
                        if missing == 'entry' and forward: return None
                        if missing == 'all_exit' and not forward and slack != 7: return None
                        if missing == 10 and not forward and slack == 10: return None
                        return day, 10. if day <= entry else 12.
                    try: results.append(('value', fn(report, entry, exit_day, lookup, bankrupt)))
                    except ArithmeticError as exc: results.append(('error', type(exc)))
                    histories.append(calls)
                self.assertEqual(results[0], results[1])
                self.assertEqual(histories[0], histories[1])
        pair = books.ebitda_yield_and_multiple(1., 49.)
        self.assertEqual(pair, (1. / 49., 49. / 1.))
        self.assertNotEqual(pair[1], 1. / pair[0])

    def test_dated_owner_parity_with_no_future_lookups(self):
        day = date(2020, 1, 2)
        anchor = dict(fiscal=date(2018, 12, 31), known=date(2019, 3, 31), market_cap=100., enterprise=150., ebitda=30., **{'yield': .2})
        reports = [dict(fiscal=date(year, 12, 31), known=date(year, 12, 31) + rules.LAG, ebitda=value)
                   for year, value in ((2016, 10.), (2017, 20.), (2018, 30.))]
        financials = {f'{year}-12-31': dict(revenue=100., operatingIncome=20., netIncome=10., totalStockholdersEquity=50., freeCashFlow=5., totalCurrentAssets=30., totalCurrentLiabilities=10., ebit=12., interestExpense=3., totalDebt=25., epsDiluted=eps)
                      for year, eps in ((2015, 1.), (2016, 2.), (2017, 3.), (2018, 4.))}
        port = Port(reports, financials, lambda when: (when, 10. if when < day else 20.))
        root, context = dict(symbol='A'), dict(date=str(day))
        with patch.object(books, 'ebitda_yield_and_multiple', wraps=books.ebitda_yield_and_multiple) as helper:
            owner = bridge.dated(Mock(facts=port), root, context, anchor, lambda: None)
        # The entry valuation rescales the report to the entry price: cap 200, EV 250.
        helper.assert_called_once_with(30., 250.)
        obs = dict(fiscal='2018-12-31', market_cap=200., enterprise_value=250., ebitda_yield=30./250., ev_ebitda=250./30.)
        history = [dict(row, fiscal=str(row['fiscal']), known=str(row['known'])) for row in reports]
        pairs = metrics.evaluate(obs, history)
        expected = metrics.filter_values(obs, pairs, day, lambda when, forward, slack: (when, 10. if when < day else 20.), financials, 2.)
        self.assertEqual(owner['evidence']['metrics'], {key:list(value) for key,value in pairs.items()})
        self.assertEqual(owner['evidence']['filters'], expected)
        self.assertEqual(bridge.lane(owner, 'pe')['value'], 20.)
        self.assertEqual(bridge.lane(owner, 'profit_margin')['value'], .1)
        self.assertEqual(bridge.lane(owner, 'return_1y')['value'], 1.)
        self.assertEqual(port.years, [day])
        self.assertTrue(all(when <= day for when, forward, slack in port.calls if not forward))
        missing = bridge.dated(Mock(facts=port), root, context, dict(anchor, **{'yield': 0.}), lambda: None)
        self.assertEqual(missing['reason'], 'LEGACY_MEASURE_UNAVAILABLE')

    def test_entry_valuation_needs_no_holding_or_exit_prices(self):
        statement=dict(fiscal=date(2014,6,30),market_cap=100e6,enterprise=150e6,**{'yield':.2})
        calls=[]
        def lookup(day,forward,slack):
            calls.append((day,forward,slack))
            return day,10. if day==statement['fiscal'] else 20.
        reason,(fiscal,entry,cap,ev,ebitda)=books.admit(statement,date(2015,1,2),lookup,books.ENTRY_SLACK)
        self.assertIsNone(reason)
        self.assertEqual((cap,ev,ebitda),(200e6,250e6,30e6))
        self.assertEqual(calls,[(statement['fiscal'],False,7),(date(2015,1,2),True,4)])
        self.assertEqual((fiscal,entry),((statement['fiscal'],10.),(date(2015,1,2),20.)))

    def test_leap_day_trailing_and_ten_year_asof(self):
        day = date(2020,2,29)
        anchor = dict(fiscal=date(2018,12,31),known=date(2019,3,31),market_cap=100.,enterprise=150.,**{'yield':.2})
        port = Port([dict(fiscal=date(2018,12,31),known=date(2019,3,31),ebitda=30.)], {}, lambda when:(when,10.))
        owner = bridge.dated(Mock(facts=port),dict(symbol='A'),dict(date=str(day)),anchor,lambda:None)
        self.assertIsNone(owner['reason'])
        # The fiscal and entry prices, then the trailing-return endpoints; 29 February clamps.
        self.assertEqual([str(when) for when, forward, slack in port.calls],
                         ['2018-12-31','2020-02-29','2020-02-29','2019-02-28','2017-02-28'])
        self.assertEqual(port.years,[day])
        self.assertEqual(bridge.detached(float('inf')),'Infinity')
        self.assertEqual(bridge.detached(-float('inf')),'-Infinity')
        self.assertEqual(bridge.detached(float('nan')),'NaN')
        self.assertEqual(bridge.detached(1.5),1.5)


class Port:
    """A facts port (facts.BookFacts) of company A: reports, legacy annual values, prices and a 2% 10-year yield."""
    def __init__(self, reports, financials, price):
        self.rows, self.financials, self.quote, self.calls, self.years = reports, financials, price, [], []

    def reports(self):
        return dict(A=self.rows), {}

    def legacy_annual(self, symbol):
        return self.financials

    def price(self, symbol, day, forward=False, slack=None):
        self.calls.append((day, forward, slack))
        return self.quote(day)

    def ten_year(self, day):
        self.years.append(day)
        return 2.


class DatedOwnerTests(unittest.TestCase):
    def setUp(self):
        self.company = annual.Company()
        self.addCleanup(self.company.close)
        self.company.financials = {f'{year}-06-30': dict(revenue=100., operatingIncome=20., netIncome=10.,
                                   totalStockholdersEquity=50., epsDiluted=year-2010.) for year in (2012, 2013, 2014)}
        self.company.treasury10 = [('2014-12-31', 2.)]

    def test_memoized_dated_context_and_fixed_boundary_validations(self):
        view = self.company.view()
        program = formulas(*[field(name) for name in ('owner.pe', 'owner.pb', 'owner.return_1y')])
        with patch.object(bridge, 'dated', wraps=bridge.dated) as owner, \
                patch.object(view, 'validate', wraps=view.validate) as validate:
            [[pe, pb, trailing]] = values(program, view, [root(owner_scope=dict(kind='dated'))])
        owner.assert_called_once()
        self.assertEqual((pe, pb), ((15e6, None), (3e6, None)))
        # No saved price a year before the root: the lane is unavailable, not recalculated.
        self.assertEqual(trailing, (None, 'LEGACY_MEASURE_UNAVAILABLE'))
        # Admission entry and exit only.
        self.assertEqual(validate.call_count, 2)

class PreparedTransportTests(unittest.TestCase):
    def prepared(self, configure=None):
        inputs = PreparedInputs(configure=configure)
        self.addCleanup(inputs.close)
        return inputs

    def test_prepared_owner_lanes_are_the_stored_book_rows(self):
        with self.prepared().view() as view:
            for mode, day in (('latest', '2015-10-20'),):
                for pool in ('legacy', 'cached'):
                    with closing(daily.connect()) as cache:
                        key = (book_store.open_book(cache), pool, 'TEST')
                        pairs = {row[0]: [row[1], row[2]] for row in cache.execute(
                            'SELECT metric,multiple,yield_value FROM book_metrics WHERE book=? AND pool=? AND symbol=?', key)}
                        stored = {row[0]: row[1] for row in cache.execute(
                            'SELECT field,value FROM book_filters WHERE book=? AND pool=? AND symbol=?', key)}
                        cap = cache.execute('SELECT market_cap FROM book_rows WHERE book=? AND pool=? AND symbol=?', key).fetchone()
                    self.assertTrue(pairs and stored)
                    roots = [root('TEST', pool, mode, day)]
                    [decision] = view.admit(roots)
                    owner = view.prepared(decision)
                    self.assertEqual(owner, dict(reason=None, evidence=dict(snapshot=dict(market_cap=cap[0]),
                                                                           metrics=pairs, filters=stored)))
                    with patch.object(bridge, 'dated', side_effect=AssertionError('recalculated')):
                        lanes = values(formulas(field('owner.ev_ebitda'), field('owner.ebitda_yield'),
                                                field('owner.market_cap')), view, roots)
                    self.assertEqual(lanes, [[(pairs['ev_ebitda'][0], None), (pairs['ev_ebitda'][1], None), (cap[0], None)]])

    def test_real_prepared_view_missing_book_row_and_lane_never_fall_back(self):
        inputs = self.prepared()
        program = formulas(field('owner.pe'))
        roots = [root('TEST', 'cached', 'latest', '2015-10-20')]
        # A real admitted company has a stored row but no PE lane in the saved fixture.
        with inputs.view() as view, patch.object(bridge, 'dated', side_effect=AssertionError('fallback')):
            self.assertEqual(values(program, view, roots), [[(None, 'LEGACY_MEASURE_UNAVAILABLE')]])
        with closing(sqlite3.connect(inputs.path)) as db:
            db.execute("DELETE FROM book_rows WHERE pool='cached' AND symbol='TEST'")
            db.commit()
        # The prepared scope lacks this company's book row.
        with inputs.view() as view, patch.object(bridge, 'dated', side_effect=AssertionError('fallback')):
            self.assertEqual(view.admit(roots)[0]['admitted'], True)
            self.assertEqual(values(program, view, roots), [[(None, 'PREPARED_MEASURE_CONTEXT_UNAVAILABLE')]])

    def test_delayed_stock_entry_and_selected_treasury_dates(self):
        def configure(inputs):
            price = research.RAW/'px'/'TEST.json'
            payload = json.loads(price.read_text())
            payload['div'][1]['date'] = '2015-01-05'
            price.write_text(json.dumps(payload))
            (research.RAW/'treasury.json').write_text(json.dumps([
                dict(date='2014-12-31', month3=2, year10=3),
                dict(date='2015-01-03', month3=2, year10=9),
                dict(date='2015-10-20', month3=2, year10=4)]))
        day = date(2015, 1, 2)
        with self.prepared(configure).view() as view:
            [decision] = view.admit([root('TEST', 'cached', owner_scope=dict(kind='dated'))])
            reports = [dict(row, fiscal=date.fromisoformat(row['fiscal']), known=date.fromisoformat(row['known']))
                       for row in view.reports('TEST', 'cached')]
            with patch.object(view.facts, 'price', wraps=view.facts.price) as price, \
                    patch.object(view.facts, 'ten_year', wraps=view.facts.ten_year) as ten_year:
                owner = bridge.dated(view, decision, dict(date=str(day)), rules.latest_statement(reports, day), lambda: None)
                # The dated owner reads the context date, never the later 9% day.
                self.assertEqual(ten_year.call_args_list, [((day,),)])
            self.assertEqual(view.facts.ten_year(day), 3.)
        self.assertIsNone(owner['reason'])
        calls = [call.args[1:3] for call in price.call_args_list]
        # The fiscal price, then the entry price up to four days later (2015-01-05).
        self.assertEqual(calls[:2], [(date(2014, 6, 30), False), (day, True)])
        self.assertTrue(all(when <= day for when, forward in calls if not forward))


if __name__ == '__main__':
    unittest.main()
