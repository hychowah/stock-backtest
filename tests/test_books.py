"""The one admission rule (books.Screen.decide) and book function (books.book) over research facts.

The daily cache writes the latest book into the book store from books.book
over facts.BookFacts, and dated books come from the same function through the
research schema that a daily connection attaches. Formula roots are admitted
by the same rule (fact_view.View.admit). The fictional cache has every latest
denial, a conflicting price day, a conflicting Treasury day, a signed-zero
yield and more annual endpoints.
"""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))

from collections import Counter
from contextlib import closing
from datetime import date
import json
import math
import sqlite3
import unittest
from unittest.mock import patch

from backtest.financial import books, rules
from backtest.inputs import book_store, daily, facts, research
from prepared_inputs_fixture import PreparedInputs, history


def exact(rows):
    """Rows with every float spelled exactly, so -0.0 and 0.0 differ."""
    return [repr(tuple(row)) for row in rows]


def companies(db):
    """The saved companies with annual reports, in symbol order."""
    return [row[0] for row in db.execute('SELECT DISTINCT symbol FROM statements ORDER BY symbol')]


def configure(inputs):
    """Twenty companies 2013-2016 with every latest denial, bad rows and more annual endpoints."""
    history(20, 2013, 2016)(inputs)
    raw = research.RAW

    def rewrite(symbol, change):
        path = raw / 'px' / f'{symbol}.json'
        payload = json.loads(path.read_text())
        change(payload['div'])
        path.write_text(json.dumps(payload))
    # Two different closes on one day: the day has no price.
    rewrite('Q0002', lambda rows: rows.insert(0, dict(date='2015-01-05', adjClose=99.)))
    # A stopped stock has no price at the latest session.
    rewrite('Q0005', lambda rows: rows.__setitem__(slice(None), [row for row in rows if row['date'] <= '2016-06-30']))
    # Half the fiscal-date price after the 2016 report: below the legacy floor at the latest session.
    rewrite('Q0007', lambda rows: [row.update(adjClose=row['adjClose'] / 2) for row in rows if row['date'] > '2016-06-30'])
    (raw / 'px' / 'Q0008.json').unlink()
    universe = json.loads((raw / 'universe.json').read_text())
    universe[6]['listed'] = False
    (raw / 'universe.json').write_text(json.dumps(universe))
    treasury = json.loads((raw / 'treasury.json').read_text())
    # Weekend rows: a signed-zero 10-year yield, then a conflicting 3-month yield.
    treasury += [dict(date='2015-01-03', month3=2., year10=-0.0), dict(date='2015-01-04', month3=4.),
                 dict(date='2015-01-04', month3=6.)]
    (raw / 'treasury.json').write_text(json.dumps(treasury))
    for symbol in ('Q0003', 'Q0004'):
        for endpoint, fields in (('balance-sheet-statement', dict(totalStockholdersEquity=80e6, totalDebt=-0.0)),
                                 ('cash-flow-statement', dict(freeCashFlow=9e6))):
            research.financial_inputs.publish(raw, symbol, endpoint, [
                dict(date=f'{year}-06-30', reportedCurrency='USD', **fields) for year in range(2008, 2017)],
                {}, raw / 'coverage.json')


class BookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A twelve-name legacy buffer leaves the lowest report yields outside it.
        cls.buffer = patch.object(rules, 'BUFFER', 12)
        cls.buffer.start()
        cls.inputs = PreparedInputs(configure=configure)
        cls.research = sqlite3.connect(cls.inputs.source)
        cls.research.row_factory = sqlite3.Row
        # The facts readers read the research schema that a daily connection attaches.
        cls.attached = sqlite3.connect(':memory:', uri=True)
        daily.attach(cls.attached, cls.inputs.source)
        cls.daily = sqlite3.connect(cls.inputs.path)
        cls.daily.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        cls.research.close()
        cls.attached.close()
        cls.daily.close()
        cls.inputs.close()
        cls.buffer.stop()

    def test_one_value_rule_for_prices_and_yields(self):
        # A conflicting price day has no value in the facts.
        row = self.research.execute("SELECT adjusted,adjusted_reason FROM stock_days WHERE symbol='Q0002' AND day='2015-01-05'").fetchone()
        self.assertEqual(tuple(row), (None, 'CONFLICTING_INPUT'))
        book_facts = facts.BookFacts(self.attached)
        self.assertEqual(book_facts.price('Q0002', date(2015, 1, 5), True, 4)[0], date(2015, 1, 6))
        # The conflicting weekend 3-month yield is skipped; the signed zero keeps its sign.
        self.assertEqual(book_facts.treasury(date(2015, 1, 4)), .02)
        self.assertEqual(facts.ten_year(self.attached, '2015-01-04'), ('2015-01-03', -0.0))
        self.assertEqual(math.copysign(1, facts.ten_year(self.attached, '2015-01-04')[1]), -1)
        # The 10-year yield on or before a day is the saved file's latest year10 value then.
        saved = sorted((row['date'], row['year10']) for row in json.loads((research.RAW / 'treasury.json').read_text())
                       if row.get('year10') is not None)
        for day in ('2013-01-01', '2015-01-02', '2015-01-04', '2016-10-20'):
            row = facts.ten_year(self.attached, day)
            expected = [value for when, value in saved if when <= day]
            self.assertEqual(exact([(None if row is None else row[1],)]), exact([(expected[-1] if expected else None,)]))

    def test_listing_and_cached_prices_are_company_facts(self):
        book_facts = facts.BookFacts(self.attached)
        companies = book_facts.companies()
        self.assertEqual(len(companies), 20)
        self.assertEqual({symbol for symbol, listed in companies.items() if not listed}, {'Q0006'})
        self.assertEqual(book_facts.cached(), {f'Q{i:04d}' for i in range(20)} - {'Q0008'})
        self.assertEqual(book_facts.cached(), {path.stem for path in (research.RAW / 'px').glob('*.json')})
        # Listing is a column of the one companies table, beside the names.
        self.assertEqual(tuple(self.research.execute("SELECT * FROM companies WHERE symbol='Q0006'").fetchone())[4], 0)

    def test_legacy_annual_values_equal_the_values_only_projection_bit_for_bit(self):
        saved = {symbol: research.financial_inputs.history(research.RAW, symbol) for symbol in companies(self.research)}
        self.assertEqual(json.dumps(saved['Q0003']['2015-06-30']), json.dumps(
            {'revenue': saved['Q0003']['2015-06-30']['revenue'], 'operatingIncome': saved['Q0003']['2015-06-30']['operatingIncome'],
             'totalStockholdersEquity': 80e6, 'totalDebt': -0.0, 'freeCashFlow': 9e6}))
        for symbol, values in saved.items():
            self.assertEqual(json.dumps(facts.legacy_annual(self.attached, symbol)), json.dumps(values), symbol)
        # A bounded leaf read: a longer history fails instead of reading on.
        rows, = self.attached.execute('SELECT count(*) FROM research.annual_facts WHERE symbol=? AND endpoint IN (?,?,?)',
                                      ('Q0003', *(endpoint for endpoint, _ in facts.LEGACY))).fetchone()
        with patch.object(facts, 'MAX_HISTORY', (rows - 1) // len(facts.LEGACY)), self.assertRaises(ValueError):
            facts.legacy_annual(self.attached, 'Q0003')

    def test_latest_book_is_the_open_book_of_the_latest_date(self):
        latest = date.fromisoformat(research.identity(self.research)['latest_date'])
        screen = books.Screen(latest, facts.BookFacts(self.attached), open_book=True)
        (book, entry, exit_day, spy, candidates), = self.daily.execute('SELECT book,entry,exit,spy,candidates FROM books')
        self.assertEqual((entry, exit_day, spy, candidates), (str(latest), None, None, len(screen.statements['cached'])))
        self.assertEqual(exact(self.daily.execute('SELECT pool FROM book_pools ORDER BY pool')), exact([('cached',), ('legacy',)]))
        stored = {(pool, symbol): (fiscal, known, day, price, cap, ev, ebitda) for pool, symbol, fiscal, known, day, price, cap, ev, ebitda
                  in self.daily.execute('SELECT pool,symbol,fiscal,known,entry,price,market_cap,enterprise_value,ebitda FROM book_rows WHERE book=?', (book,))}
        self.assertEqual(len(stored), 26)
        for pool in ('legacy', 'cached'):
            for symbol, statement in screen.statements[pool].items():
                held, _ = screen.decide(symbol, pool)
                self.assertEqual(stored.get((pool, symbol)), None if held is None else (
                    str(statement['fiscal']), str(statement['known']), str(held['entry'][0]), held['entry'][1],
                    held['market_cap'], held['enterprise_value'], held['ebitda']))

    def test_view_admits_latest_roots_with_the_one_vocabulary(self):
        with self.inputs.view() as view:
            day = view.bounds['latest_date']
            symbols = sorted(facts.BookFacts(self.attached).companies()) + ['NONE']
            roots = [dict(symbol=symbol, pool=pool, mode='latest', date=day) for symbol in symbols for pool in ('legacy', 'cached')]
            decisions = view.admit(roots)
        reasons = Counter((decision['pool'], decision['reason']) for decision in decisions)
        self.assertEqual(reasons, Counter({
            ('cached', None): 17, ('legacy', None): 9, ('cached', 'NOT_LISTED'): 1, ('legacy', 'NOT_LISTED'): 1,
            ('cached', 'MISSING_PRICE'): 1, ('legacy', 'MISSING_PRICE'): 1,
            ('cached', 'MISSING_CACHED_PRICES'): 1, ('legacy', 'MISSING_CACHED_PRICES'): 1,
            ('legacy', 'OUTSIDE_LEGACY_BUFFER'): 7, ('legacy', 'INELIGIBLE_VALUATION'): 1,
            ('cached', 'UNKNOWN_COMPANY'): 1, ('legacy', 'UNKNOWN_COMPANY'): 1}))
        # An admitted latest root keeps its stored shape: report dates and the entry valuation, no lookups.
        admitted = next(decision for decision in decisions if decision['admitted'])
        self.assertEqual(set(admitted['statement']), {'fiscal', 'known'})
        self.assertEqual(set(admitted['valuation']), {'market_cap', 'enterprise_value', 'ebitda'})
        self.assertNotIn('admission_evidence', admitted)

    def test_dated_books_are_deterministic_across_connections(self):
        with closing(daily.connect()) as db:
            sessions = facts.sessions(db)
            attached, direct = facts.BookFacts(db), facts.BookFacts(self.attached)
            pairs = [(sessions[i], sessions[min(i + 63, len(sessions) - 1)]) for i in range(0, len(sessions) - 1, 120)]
            pairs += [(date(2015, 1, 2), date(2015, 1, 5)), (date(2016, 6, 1), date(2016, 10, 20))]
            self.assertGreater(len(pairs), 6)
            compared = Counter()
            for entry, exit_day in pairs:
                for pool in ('legacy', 'cached'):
                    with self.subTest(entry=entry, exit=exit_day, pool=pool):
                        new = books.book(entry, exit_day, pool, attached)
                        old = books.book(entry, exit_day, pool, direct)
                        for key in ('rows', 'metrics', 'filters'):
                            self.assertEqual(exact(new[key]), exact(old[key]))
                        self.assertEqual({key: new[key] for key in ('entry', 'exit', 'spy', 'candidates')},
                                         {key: old[key] for key in ('entry', 'exit', 'spy', 'candidates')})
                        compared.update(row[-1] for row in new['rows'])
        self.assertGreater(compared['Scheduled exit'], 100)
        self.assertGreater(compared['Last available price'], 0)

    def test_one_writer_shares_a_book_id_between_pools(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript(book_store.SCHEMA)
            entry, exit_day = date(2015, 1, 2), date(2015, 7, 1)
            ids = [book_store.store(db, books.book(entry, exit_day, pool, facts.BookFacts(self.attached)))
                   for pool in ('legacy', 'cached')]
            self.assertEqual(ids[0], ids[1])
            self.assertEqual(db.execute('SELECT entry,exit FROM books').fetchall(), [('2015-01-02', '2015-07-01')])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM book_pools').fetchone()[0], 2)
            self.assertGreater(db.execute("SELECT COUNT(*) FROM book_rows WHERE status='Scheduled exit'").fetchone()[0], 0)


class Facts:
    """An in-memory facts port: reports, listing, saved price files and adjusted closes."""
    def __init__(self, statements, companies, prices, sessions):
        self.statements, self.listing, self.prices, self.sessions = statements, companies, prices, sessions

    def reports(self):
        return books.pools(self.statements)

    def cached(self):
        return set(self.prices)

    def companies(self):
        return self.listing

    def spy(self, day):
        return 100. if day in self.sessions else None

    def price(self, symbol, day, forward=False, slack=None):
        days = sorted(d for d in self.prices[symbol] if (d >= day if forward else d <= day))
        if not days:
            return None
        found = days[0] if forward else days[-1]
        return (found, self.prices[symbol][found]) if slack is None or abs((found - day).days) <= slack else None


class DecisionTests(unittest.TestCase):
    """Every denial reason of Screen.decide, in gate order, through its public interface."""
    FISCAL, ENTRY, EXIT = date(2014, 6, 30), date(2015, 1, 2), date(2015, 7, 1)

    def report(self, cap=150e6, ev=180e6, multiple=5.):
        return dict(fiscal=self.FISCAL, known=self.FISCAL + rules.LAG, market_cap=cap, enterprise=ev,
                    ebitda=ev / multiple, **{'yield': 1 / multiple})

    def screen(self, open_book=False, **changes):
        statements = dict(A=[self.report()], LOW=[self.report(multiple=50.)], FILE=[self.report()],
                          GAP=[self.report()], NEG=[self.report(ev=60e6)], HUGE=[self.report(cap=1e308, ev=1e308)],
                          SMALL=[self.report()], STOP=[self.report()], SMALLCAP=[self.report(cap=50e6, ev=60e6)])
        steady = {self.FISCAL: 10., self.ENTRY: 10., self.EXIT: 11.}
        prices = dict(A=steady, LOW=steady, GAP={self.ENTRY: 10.}, NEG={self.FISCAL: 10., self.ENTRY: 1.},
                      HUGE={self.FISCAL: 10., self.ENTRY: 100.}, SMALL={self.FISCAL: 10., self.ENTRY: 5.},
                      STOP={self.FISCAL: 10., self.ENTRY: 10.},
                      SMALLCAP=steady, UNLISTED=steady)
        companies = {symbol: True for symbol in statements} | dict(UNLISTED=False, NOREPORT=True)
        statements['UNLISTED'] = [self.report()]
        facts_port = Facts(statements, companies, prices, {self.ENTRY, self.EXIT})
        for name, value in changes.items():
            setattr(facts_port, name, value)
        # Eight legacy names: LOW, the lowest report yield, is outside; SMALLCAP has no legacy report.
        with patch.object(rules, 'BUFFER', 8):
            return books.Screen(self.ENTRY, facts_port, open_book=open_book)

    def test_every_reason_in_gate_order(self):
        screen = self.screen()
        decide = lambda symbol, pool='legacy', exit_day=self.EXIT: screen.decide(symbol, pool, exit_day)[1]
        self.assertEqual(decide('A'), None)
        self.assertEqual(decide('NOPE'), 'UNKNOWN_COMPANY')
        self.assertEqual(decide('NOREPORT'), 'NO_ELIGIBLE_REPORT')
        self.assertEqual(decide('SMALLCAP'), 'NO_ELIGIBLE_REPORT')
        self.assertEqual(decide('SMALLCAP', 'cached'), None)
        self.assertEqual(decide('LOW'), 'OUTSIDE_LEGACY_BUFFER')
        self.assertEqual(decide('LOW', 'cached'), None)
        self.assertEqual(decide('FILE'), 'MISSING_CACHED_PRICES')
        self.assertEqual(decide('GAP'), 'MISSING_PRICE')
        self.assertEqual(decide('NEG'), 'NONPOSITIVE_VALUATION')
        self.assertEqual(decide('HUGE', 'cached'), 'NONFINITE_RESULT')
        self.assertEqual(decide('SMALL'), 'INELIGIBLE_VALUATION')
        self.assertEqual(decide('SMALL', 'cached'), None)
        self.assertEqual(decide('A', 'legacy', self.ENTRY), 'ENTRY_NOT_BEFORE_EXIT')
        # A dated screen ignores the listing; the open book denies it first.
        self.assertEqual(decide('UNLISTED'), None)
        self.assertEqual(self.screen(open_book=True).decide('UNLISTED', 'legacy'), (None, 'NOT_LISTED'))
        self.assertEqual(set(books.REASONS), {'UNKNOWN_COMPANY', 'NOT_LISTED', 'NO_ELIGIBLE_REPORT', 'OUTSIDE_LEGACY_BUFFER',
            'MISSING_CACHED_PRICES', 'MISSING_PRICE', 'NONPOSITIVE_VALUATION', 'NONFINITE_RESULT', 'INELIGIBLE_VALUATION',
            'ENTRY_NOT_BEFORE_EXIT', 'MISSING_EXIT_PRICE'})

    def test_exit_and_admission_alone(self):
        screen = self.screen()
        held, reason = screen.decide('A', 'legacy', self.EXIT)
        self.assertIsNone(reason)
        self.assertEqual((held['entry'], held['exit'], held['status']), ((self.ENTRY, 10.), (self.EXIT, 11.), 'Scheduled exit'))
        self.assertAlmostEqual(held['return_value'], .1)
        self.assertEqual(held['rank'], 1)
        stopped, _ = screen.decide('STOP', 'legacy', self.EXIT)
        self.assertEqual((stopped['exit'], stopped['return_value'], stopped['status']), ((self.ENTRY, 10.), 0., 'Last available price'))
        alone, _ = screen.decide('A', 'legacy')
        self.assertEqual((alone['exit'], alone['return_value'], alone['status']), (None, None, None))
        self.assertEqual((alone['market_cap'], alone['enterprise_value'], alone['fiscal_price']), (150e6, 180e6, (self.FISCAL, 10.)))
        no_exit = self.screen(price=lambda symbol, day, forward=False, slack=None:
                              None if day == self.EXIT else Facts.price(screen.facts, symbol, day, forward, slack))
        self.assertEqual(no_exit.decide('A', 'legacy', self.EXIT), (None, 'MISSING_EXIT_PRICE'))

    def test_the_date_rule(self):
        facts_port = Facts({}, {}, {}, {self.ENTRY, date(1995, 12, 29)})
        for day in (date(1995, 12, 29), date(2015, 1, 3)):
            with self.subTest(day=day), self.assertRaisesRegex(ValueError, 'saved SPY session from 1996-01-01'):
                books.Screen(day, facts_port)
        self.assertEqual(books.Screen(self.ENTRY, facts_port).statements, dict(cached={}, legacy={}))


if __name__ == '__main__':
    unittest.main()
