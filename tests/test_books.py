"""The one admission rule (books.Screen.decide) and book function (books.book) over research facts.

The daily cache writes the latest book into the book store from books.book
over facts.BookFacts; research still writes the old latest tables
(latest_snapshots, latest_admission and its year-0 metric and filter rows),
and dated books still come from schedules.compute_period over the daily cache.
These tests compare the new path with both, value for value and reason for
reason, on a fictional cache with latest denials, a conflicting price day, a
conflicting Treasury day, a signed-zero yield and more annual endpoints.
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

from backtest.engines.original import schedules
from backtest.financial import books, rules
from backtest.inputs import book_store, daily, facts, research
from prepared_inputs_fixture import PreparedInputs, history


def exact(rows):
    """Rows with every float spelled exactly, so -0.0 and 0.0 differ."""
    return [repr(tuple(row)) for row in rows]


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
        cls.daily = sqlite3.connect(cls.inputs.path)
        cls.daily.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        cls.research.close()
        cls.daily.close()
        cls.inputs.close()
        cls.buffer.stop()

    def test_one_value_rule_for_prices_and_yields(self):
        # A conflicting price day has no value in the facts and in the daily prices.
        row = self.research.execute("SELECT adjusted,adjusted_reason FROM stock_days WHERE symbol='Q0002' AND day='2015-01-05'").fetchone()
        self.assertEqual(tuple(row), (None, 'CONFLICTING_INPUT'))
        self.assertIsNone(self.daily.execute("SELECT 1 FROM prices WHERE symbol='Q0002' AND day='2015-01-05'").fetchone())
        book_facts = facts.BookFacts(self.research)
        self.assertEqual(book_facts.price('Q0002', date(2015, 1, 5), True, 4)[0], date(2015, 1, 6))
        valid = self.research.execute('SELECT symbol,day,adjusted FROM stock_days WHERE adjusted IS NOT NULL ORDER BY symbol,day')
        self.assertEqual(exact(valid), exact(self.daily.execute('SELECT * FROM prices ORDER BY symbol,day')))
        # The conflicting weekend 3-month yield is skipped; the signed zero keeps its sign.
        self.assertEqual(book_facts.treasury(date(2015, 1, 4)), .02)
        self.assertEqual(facts.ten_year(self.research, '2015-01-04'), ('2015-01-03', -0.0))
        self.assertEqual(math.copysign(1, facts.ten_year(self.research, '2015-01-04')[1]), -1)
        for day in ('2013-01-01', '2015-01-02', '2015-01-04', '2016-10-20'):
            row = facts.ten_year(self.research, day)
            self.assertEqual(None if row is None else row[1], research.ten_year_yield(self.research, date.fromisoformat(day)))
        sessions = self.research.execute('SELECT day,spy FROM market_days WHERE spy IS NOT NULL ORDER BY day')
        self.assertEqual(exact(sessions), exact(self.daily.execute('SELECT * FROM sessions ORDER BY day')))

    def test_listing_and_cached_prices_are_company_facts(self):
        book_facts = facts.BookFacts(self.research)
        companies = book_facts.companies()
        self.assertEqual(len(companies), 20)
        self.assertEqual({symbol for symbol, listed in companies.items() if not listed}, {'Q0006'})
        self.assertEqual(book_facts.cached(), {f'Q{i:04d}' for i in range(20)} - {'Q0008'})
        self.assertEqual(book_facts.cached(), daily.cached_symbols(self.daily))

    def test_legacy_annual_values_equal_the_saved_json_bit_for_bit(self):
        saved = {}
        for symbol, fiscal, values in self.daily.execute('SELECT symbol,fiscal,values_json FROM financial_inputs ORDER BY symbol,fiscal'):
            saved.setdefault(symbol, {})[fiscal] = json.loads(values)
        self.assertEqual(json.dumps(saved['Q0003']['2015-06-30']), json.dumps(
            {'revenue': saved['Q0003']['2015-06-30']['revenue'], 'operatingIncome': saved['Q0003']['2015-06-30']['operatingIncome'],
             'totalStockholdersEquity': 80e6, 'totalDebt': -0.0, 'freeCashFlow': 9e6}))
        for symbol, values in saved.items():
            self.assertEqual(json.dumps(facts.legacy_annual(self.research, symbol)), json.dumps(values), symbol)

    def test_latest_book_equals_the_old_latest_tables(self):
        latest = json.loads(self.research.execute("SELECT value FROM metadata WHERE key='latest'").fetchone()[0])
        (book, entry, exit_day, spy, candidates), = self.daily.execute('SELECT book,entry,exit,spy,candidates FROM books')
        self.assertEqual((entry, exit_day, spy, candidates), (latest['asof'], None, None, latest['eligible_financials']))
        self.assertEqual(exact(self.daily.execute('SELECT pool FROM book_pools ORDER BY pool')), exact([('cached',), ('legacy',)]))
        new = self.daily.execute('''SELECT pool,symbol,candidate_rank,fiscal,known,entry,price,market_cap,enterprise_value,
            ebitda_yield,ev_ebitda,spread,ebitda,exit,return_value,status FROM book_rows WHERE book=? ORDER BY pool,symbol''', (book,))
        old = self.research.execute('''SELECT s.pool,s.symbol,s.candidate_rank,s.fiscal,s.known,s.price_date,s.price,s.market_cap,
            s.enterprise_value,s.ebitda_yield,s.ev_ebitda,s.spread,a.ebitda,NULL,NULL,NULL FROM latest_snapshots s
            JOIN latest_admission a ON a.symbol=s.symbol AND a.pool=s.pool ORDER BY s.pool,s.symbol''').fetchall()
        self.assertEqual(len(old), 26)
        self.assertEqual(exact(new), exact(old))
        for table, columns in (('screening_metrics', 'metric,multiple,yield_value'), ('filter_values', 'field,value')):
            target = 'book_metrics' if table == 'screening_metrics' else 'book_filters'
            self.assertEqual(
                exact(self.daily.execute(f'SELECT pool,symbol,{columns} FROM {target} WHERE book=? ORDER BY 1,2,3', (book,))),
                exact(self.research.execute(f"SELECT pool,symbol,{columns} FROM {table} WHERE mode='latest' AND year=0 ORDER BY 1,2,3")))

    def test_latest_reasons_map_from_the_old_vocabulary(self):
        latest = date.fromisoformat(facts.require(self.research)['latest_date'])
        screen = books.Screen(latest, facts.BookFacts(self.research), open_book=True)
        pairs = Counter()
        for symbol, pool, admitted, reason in self.research.execute('SELECT symbol,pool,admitted,reason FROM latest_admission'):
            held, new = screen.decide(symbol, pool)
            self.assertEqual(held is not None, bool(admitted))
            pairs[pool, reason, new] += 1
        self.assertEqual(pairs, Counter({
            ('cached', None, None): 17, ('legacy', None, None): 9,
            ('cached', 'NOT_LISTED', 'NOT_LISTED'): 1, ('legacy', 'NOT_LISTED', 'NOT_LISTED'): 1,
            ('cached', 'MISSING_PRICE', 'MISSING_PRICE'): 1, ('legacy', 'MISSING_PRICE', 'MISSING_PRICE'): 1,
            ('cached', 'MISSING_PRICE', 'MISSING_CACHED_PRICES'): 1, ('legacy', 'MISSING_PRICE', 'MISSING_CACHED_PRICES'): 1,
            ('legacy', 'MISSING_PRICE', 'OUTSIDE_LEGACY_BUFFER'): 7, ('legacy', 'POOL_INELIGIBLE', 'INELIGIBLE_VALUATION'): 1}))
        self.assertEqual(screen.decide('NONE', 'cached'), (None, 'UNKNOWN_COMPANY'))

    def test_dated_books_equal_the_daily_cache_calculation(self):
        sessions = [date.fromisoformat(row[0]) for row in self.daily.execute('SELECT day FROM sessions ORDER BY day')]
        reports, cached = daily.histories(self.daily), daily.cached_symbols(self.daily)
        book_facts = facts.BookFacts(self.research)
        pairs = [(sessions[i], sessions[min(i + 63, len(sessions) - 1)]) for i in range(0, len(sessions) - 1, 120)]
        pairs += [(date(2015, 1, 2), date(2015, 1, 5)), (date(2016, 6, 1), date(2016, 10, 20))]
        self.assertGreater(len(pairs), 6)
        compared = Counter()
        for entry, exit_day in pairs:
            for pool in ('legacy', 'cached'):
                with self.subTest(entry=entry, exit=exit_day, pool=pool):
                    old = schedules.compute_period(self.daily, entry, exit_day, reports, cached, pool)
                    new = books.book(entry, exit_day, pool, book_facts)
                    self.assertEqual(exact([(new['entry'], new['exit'], new['spy'], new['candidates'])]),
                                     exact([old['period'][:3] + old['period'][-1:]]))
                    self.assertEqual(exact([row[:3] + row[4:5] + row[6:] for row in new['rows']]), exact(old['snapshots']))
                    self.assertEqual(exact(new['metrics']), exact(old['metrics']))
                    self.assertEqual(exact(new['filters']), exact(old['filters']))
                    compared.update(row[-1] for row in new['rows'])
        self.assertGreater(compared['Scheduled exit'], 100)
        self.assertGreater(compared['Last available price'], 0)

    def test_one_writer_shares_a_book_id_between_pools(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript(book_store.SCHEMA)
            entry, exit_day = date(2015, 1, 2), date(2015, 7, 1)
            ids = [book_store.store(db, books.book(entry, exit_day, pool, facts.BookFacts(self.research)))
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
