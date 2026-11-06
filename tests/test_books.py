"""The one book function (books.book) over research facts equals the stored books.

Research writes the latest book twice: latest_snapshots and its year-0 metric
and filter rows, and the book_* tables from books.book over facts.BookFacts.
Dated books still come from schedules.compute_period over the daily cache.
These tests compare the new path with both, value for value, on a fictional
cache with a light series and duplicate price and Treasury days.
"""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))

from contextlib import closing
from datetime import date
import json
import sqlite3
import unittest

from backtest.engines.original import schedules
from backtest.financial import books
from backtest.inputs import daily, facts, research
from prepared_inputs_fixture import PreparedInputs, history


def exact(rows):
    """Rows with every float spelled exactly, so -0.0 and 0.0 differ."""
    return [repr(tuple(row)) for row in rows]


def predecessor_price_rows(payload):
    """The daily price rule before facts.book_prices (fd043e3 daily._price_rows), as an oracle."""
    def bars(rows, key):
        result = []
        for row in rows:
            value = research.rules.num(row.get(key))
            try:
                day = date.fromisoformat(str(row.get('date', ''))[:10])
            except ValueError:
                continue
            if value is not None and value > 0:
                result.append((day, value))
        return sorted(result)
    adjusted = dict(bars(payload.get('div') or [], 'adjClose'))
    light = {}
    for row in payload.get('light') or []:
        value = row.get('price') if row.get('price') is not None else row.get('close')
        light.update(bars([dict(date=row.get('date'), value=value)], 'value'))
    valuation = light or adjusted
    return [(str(day), valuation.get(day), adjusted.get(day)) for day in sorted(valuation.keys() | adjusted.keys())]


def configure(inputs):
    """Twenty companies 2013-2016, a light series, duplicate days and more annual endpoints."""
    history(20, 2013, 2016)(inputs)
    raw = research.RAW
    path = raw / 'px' / 'Q0001.json'
    payload = json.loads(path.read_text())
    # A light series on another scale, with a duplicate day whose last value differs.
    payload['light'] = [dict(date=row['date'], price=row['adjClose'] * 3) for row in payload['div']]
    payload['light'].append(dict(date='2015-01-02', close=70.))
    path.write_text(json.dumps(payload))
    path = raw / 'px' / 'Q0002.json'
    payload = json.loads(path.read_text())
    payload['div'].insert(0, dict(date='2015-01-05', adjClose=99.))
    path.write_text(json.dumps(payload))
    treasury = json.loads((raw / 'treasury.json').read_text())
    treasury.append(dict(date='2015-01-02', month3=5., year10=-0.0))
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

    def test_book_prices_keep_the_daily_rule_on_duplicate_days(self):
        for symbol in ('Q0001', 'Q0002', 'Q0005'):
            payload = json.loads((research.RAW / 'px' / f'{symbol}.json').read_text())
            self.assertEqual(daily._price_rows(payload), predecessor_price_rows(payload))
        rows = dict((row[0], row[1:]) for row in self.research.execute(
            "SELECT day,book_price,book_adjusted FROM stock_days WHERE symbol='Q0001'"))
        self.assertEqual(rows['2015-01-02'][0], 70.)
        self.assertEqual(self.research.execute(
            "SELECT book_adjusted FROM stock_days WHERE symbol='Q0002' AND day='2015-01-05'").fetchone()[0], 99.)

    def test_book_columns_equal_the_daily_cache_tables(self):
        stock = self.research.execute('SELECT symbol,day,book_price,book_adjusted FROM stock_days '
                                      'WHERE book_price IS NOT NULL OR book_adjusted IS NOT NULL ORDER BY symbol,day')
        self.assertEqual(exact(stock), exact(self.daily.execute('SELECT * FROM prices ORDER BY symbol,day')))
        self.assertEqual(exact(self.research.execute('SELECT day,book_spy FROM market_days WHERE book_spy IS NOT NULL ORDER BY day')),
                         exact(self.daily.execute('SELECT * FROM sessions ORDER BY day')))
        self.assertEqual(exact(self.research.execute('SELECT day,book_month3/100 FROM market_days WHERE book_month3 IS NOT NULL ORDER BY day')),
                         exact(self.daily.execute('SELECT * FROM treasuries ORDER BY day')))
        treasury10 = [tuple(row) for row in self.daily.execute('SELECT day,yield_percent FROM treasury10 ORDER BY day')]
        self.assertIn(('2015-01-02', -0.0), treasury10)
        self.assertEqual(exact(self.research.execute('SELECT day,book_year10 FROM market_days WHERE book_year10 IS NOT NULL ORDER BY day')),
                         exact(treasury10))
        for day in ('2013-01-01', '2015-01-02', '2015-01-03', '2016-10-20'):
            row = facts.ten_year(self.research, day)
            self.assertEqual(repr(None if row is None else row[1]), repr(research.ten_year_yield(self.research, date.fromisoformat(day))))

    def test_legacy_annual_values_equal_the_saved_json_bit_for_bit(self):
        saved = {}
        for symbol, fiscal, values in self.daily.execute('SELECT symbol,fiscal,values_json FROM financial_inputs ORDER BY symbol,fiscal'):
            saved.setdefault(symbol, {})[fiscal] = json.loads(values)
        self.assertEqual(json.dumps(saved['Q0003']['2015-06-30']), json.dumps(
            {'revenue': saved['Q0003']['2015-06-30']['revenue'], 'operatingIncome': saved['Q0003']['2015-06-30']['operatingIncome'],
             'totalStockholdersEquity': 80e6, 'totalDebt': -0.0, 'freeCashFlow': 9e6}))
        for symbol, values in saved.items():
            self.assertEqual(json.dumps(facts.legacy_annual(self.research, symbol)), json.dumps(values), symbol)

    def test_latest_book_equals_the_latest_snapshot_tables(self):
        (book, entry, exit_day, spy, legacy, cached), = self.research.execute(
            'SELECT book,entry,exit,spy,legacy_candidates,cached_candidates FROM books')
        latest = json.loads(self.research.execute("SELECT value FROM metadata WHERE key='latest'").fetchone()[0])
        self.assertEqual((entry, exit_day, spy, legacy, cached),
                         (latest['asof'], None, None, latest['legacy_candidates'], latest['eligible_financials']))
        self.assertEqual(exact(self.research.execute('SELECT pool FROM book_pools ORDER BY pool')), exact([('cached',), ('legacy',)]))
        new = self.research.execute('''SELECT pool,symbol,candidate_rank,fiscal,known,entry,price,market_cap,enterprise_value,
            ebitda_yield,ev_ebitda,spread,ebitda,exit,return_value,status FROM book_rows WHERE book=? ORDER BY pool,symbol''', (book,))
        old = self.research.execute('''SELECT s.pool,s.symbol,s.candidate_rank,s.fiscal,s.known,s.price_date,s.price,s.market_cap,
            s.enterprise_value,s.ebitda_yield,s.ev_ebitda,s.spread,a.ebitda,NULL,NULL,NULL FROM latest_snapshots s
            JOIN latest_admission a ON a.symbol=s.symbol AND a.pool=s.pool ORDER BY s.pool,s.symbol''')
        old = old.fetchall()
        self.assertGreater(len(old), 20)
        self.assertEqual(exact(new), exact(old))
        for table, columns in (('screening_metrics', 'metric,multiple,yield_value'), ('filter_values', 'field,value')):
            target = 'book_metrics' if table == 'screening_metrics' else 'book_filters'
            self.assertEqual(
                exact(self.research.execute(f'SELECT pool,symbol,{columns} FROM {target} WHERE book=? ORDER BY 1,2,3', (book,))),
                exact(self.research.execute(f"SELECT pool,symbol,{columns} FROM {table} WHERE mode='latest' AND year=0 ORDER BY 1,2,3")))

    def test_dated_books_equal_the_daily_cache_calculation(self):
        sessions = [date.fromisoformat(row[0]) for row in self.daily.execute('SELECT day FROM sessions ORDER BY day')]
        reports, cached = daily.histories(self.daily), daily.cached_symbols(self.daily)
        book_facts = facts.BookFacts(self.research)
        pairs = [(sessions[i], sessions[min(i + 63, len(sessions) - 1)]) for i in range(0, len(sessions) - 1, 120)]
        pairs.append((date(2015, 1, 2), date(2015, 1, 5)))
        self.assertGreater(len(pairs), 6)
        compared = 0
        for entry, exit_day in pairs:
            for pool in ('legacy', 'cached'):
                with self.subTest(entry=entry, exit=exit_day, pool=pool):
                    old = schedules.compute_period(self.daily, entry, exit_day, reports, cached, pool)
                    new = books.book(daily.histories(self.research), entry, exit_day, pool, cached, book_facts)
                    self.assertEqual(exact([new['book']]), exact([old['period']]))
                    self.assertEqual(exact([row[:3] + row[4:5] + row[6:] for row in new['rows']]), exact(old['snapshots']))
                    self.assertEqual(exact(new['metrics']), exact(old['metrics']))
                    self.assertEqual(exact(new['filters']), exact(old['filters']))
                    compared += len(new['rows'])
        self.assertGreater(compared, 100)

    def test_one_writer_shares_a_book_id_between_pools(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript(research.BOOK_SCHEMA)
            entry, exit_day = date(2015, 1, 2), date(2015, 7, 1)
            reports, cached = daily.histories(self.research), daily.cached_symbols(self.daily)
            ids = [research.store_book(db, books.book(reports, entry, exit_day, pool, cached, facts.BookFacts(self.research)))
                   for pool in ('legacy', 'cached')]
            self.assertEqual(ids[0], ids[1])
            self.assertEqual(db.execute('SELECT entry,exit FROM books').fetchall(), [('2015-01-02', '2015-07-01')])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM book_pools').fetchone()[0], 2)
            self.assertGreater(db.execute("SELECT COUNT(*) FROM book_rows WHERE status='Scheduled exit'").fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
