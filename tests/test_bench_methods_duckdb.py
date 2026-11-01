"""Synthetic SQLite-oracle conformance for batched DuckDB ASOF price lookup."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
from datetime import date
import importlib.util
import os
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tools.experiments.bench_methods_duckdb as method
AVAILABLE = importlib.util.find_spec('duckdb') is not None and importlib.util.find_spec('numpy') is not None


def ordinal(day):
    return date.fromisoformat(day).toordinal()


class BoundedCursor:
    def __init__(self, cursor, observed):
        self.cursor, self.observed = cursor, observed
    def fetchmany(self, size):
        self.observed['chunk_sizes'].append(size)
        return self.cursor.fetchmany(size)
    def fetchall(self):
        raise AssertionError('Loading all saved price rows is forbidden.')
    def close(self):
        self.cursor.close()


class BoundedSource:
    """Require one streaming SELECT while preserving an actual SQLite oracle."""
    def __init__(self, db):
        self.db = db
        self.observed = dict(price_reads=0, chunk_sizes=[])
    def execute(self, sql, *args):
        cursor = self.db.execute(sql, *args)
        if sql.startswith('SELECT symbol,day,'):
            self.observed['price_reads'] += 1
            return BoundedCursor(cursor, self.observed)
        return cursor


@unittest.skipUnless(AVAILABLE, 'DuckDB and NumPy are optional benchmark dependencies.')
class DuckDBPricesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.workdir = self.root / 'duckdb-spill'
        self.environment = patch.dict(os.environ, BACKTEST_METHODS_DUCKDB_WORKDIR=str(self.workdir))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.path = self.root / 'saved prices.sqlite'
        db = sqlite3.connect(self.path)
        db.execute('CREATE TABLE prices(symbol TEXT,day TEXT,price REAL,adjusted REAL, '
                   'PRIMARY KEY(symbol,day)) WITHOUT ROWID')
        db.executemany('INSERT INTO prices VALUES(?,?,?,?)', [
            ('A', '2020-01-02', 10, None),
            ('A', '2020-01-03', None, 20),
            ('A', '2020-01-06', 12, 22),
            ('A', '2020-01-07', None, None),
            ('a', '2020-01-03', 99, 101),
            ('B', '2020-01-03', 30, None),
            ('EMPTY', '2020-01-03', None, None),
            ('STOP', '1999-12-31', 1, 2),
        ])
        db.commit();db.close()
        self.db = sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)
        self.addCleanup(self.db.close)
        self.source = BoundedSource(self.db)
        with patch.object(method, 'CHUNK_ROWS', 3):
            self.resolver = method.open_prices(self.source)
        self.addCleanup(self.resolver.close)

    def q(self, symbol, day, column='price', forward=False):
        return symbol, ordinal(day), column, forward

    def oracle(self, queries):
        answers = []
        for symbol, day, column, forward in queries:
            operator, order = ('>=', 'ASC') if forward else ('<=', 'DESC')
            row = self.db.execute(f'SELECT day,{column} FROM prices WHERE symbol=? '
                                  f'AND day{operator}? AND {column} IS NOT NULL ORDER BY day {order} LIMIT 1',
                                  (symbol, str(date.fromordinal(day)))).fetchone()
            answers.append(None if row is None else (ordinal(row[0]), row[1]))
        return answers

    def test_all_directions_dates_nulls_and_case_match_sqlite_exactly(self):
        queries = [self.q(symbol, day, column, forward)
                   for symbol in ('A', 'a', 'B', 'EMPTY', 'MISSING', 'STOP')
                   for day in ('1999-12-30', '1999-12-31', '2020-01-01', '2020-01-02',
                               '2020-01-03', '2020-01-04', '2020-01-06', '2020-01-07', '2026-10-21')
                   for column in ('price', 'adjusted') for forward in (False, True)]
        random.Random(42).shuffle(queries)
        # Repeat inputs deliberately: order and multiplicity must be preserved.
        queries += queries[:29]
        self.assertEqual(self.resolver.resolve(queries), self.oracle(queries))
        self.assertEqual(self.resolver.resolve(queries[:7]), self.oracle(queries[:7]))

    def test_two_waves_use_actual_raw_entry_date_and_no_date_slack(self):
        raw = self.resolver.resolve([self.q('A', '2020-01-01', forward=True)])[0]
        self.assertEqual(raw, (ordinal('2020-01-02'), 10.))
        self.assertEqual(self.resolver.resolve([('A', raw[0], 'adjusted', True)]),
                         [(ordinal('2020-01-03'), 20.)])
        self.assertEqual(self.resolver.resolve([self.q('STOP', '2026-10-21', 'adjusted')]),
                         [(ordinal('1999-12-31'), 2.)])
        self.assertEqual(self.resolver.resolve([]), [])

    def test_loader_streams_once_with_bounded_chunks_and_stats(self):
        stats = self.resolver.stats
        self.assertEqual(self.source.observed['price_reads'], 1)
        self.assertTrue(self.source.observed['chunk_sizes'])
        self.assertEqual(set(self.source.observed['chunk_sizes']), {3})
        self.assertEqual(stats['rows'], 8)
        self.assertEqual(stats['symbols'], 5)
        self.assertEqual(stats['raw_points'], 5)
        self.assertEqual(stats['adjusted_points'], 4)
        self.assertEqual(stats['payload_bytes'], 9*16)
        self.assertLessEqual(stats['peak_numpy_chunk_bytes'], 3*2*16)
        self.assertEqual(stats['threads'], 4)
        self.assertEqual(stats['memory_limit'], '1GB')
        self.assertGreater(stats['disk_bytes'], 0)
        self.assertIn('duckdb', stats['versions'])
        self.assertIn('numpy', stats['versions'])
        self.resolver.resolve([self.q('A', '2020-01-03')])
        self.assertEqual(stats['resolve_calls'], 1)
        self.assertEqual(stats['queries'], 1)
        # The resolver never returns to SQLite after its bulk import.
        self.assertEqual(self.source.observed['price_reads'], 1)

    def test_invalid_queries_fail_before_any_join(self):
        day = ordinal('2020-01-03')
        malformed = [None, 'A', ('A', day, 'price'), ('A', day, 'price', False, 1),
                     ('', day, 'price', False), (None, day, 'price', False),
                     ('A', True, 'price', False), ('A', float(day), 'price', False),
                     ('A', 0, 'price', False), ('A', date.max.toordinal()+1, 'price', False),
                     ('A', day, 'close', False), ('A', day, 'price', 0)]
        for query in malformed:
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.resolver.resolve([query])
        self.assertEqual(self.resolver.stats['resolve_calls'], 0)

    def test_close_releases_owned_files_without_closing_or_writing_sqlite(self):
        owned = self.resolver._directory
        self.assertTrue(owned.is_relative_to(self.workdir))
        self.assertTrue(owned.is_dir())
        self.resolver.close();self.resolver.close()
        self.assertFalse(owned.exists())
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM prices').fetchone()[0], 8)
        with self.assertRaises(sqlite3.OperationalError):
            self.db.execute('DELETE FROM prices')
        with self.assertRaises(RuntimeError):
            self.resolver.resolve([])

    def test_missing_physical_column_and_empty_prices(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE prices(symbol TEXT,day TEXT,price REAL)')
        empty = method.open_prices(db)
        self.addCleanup(empty.close)
        self.assertEqual(empty.stats['rows'], 0)
        self.assertEqual(empty.resolve([self.q('A', '2020-01-03')]), [None])
        db.execute("INSERT INTO prices VALUES('A','2020-01-03',10)")
        partial = method.open_prices(db)
        self.addCleanup(partial.close)
        self.assertEqual(partial.resolve([self.q('A', '2020-01-03', 'adjusted'), self.q('A', '2020-01-03')]),
                         [None, (ordinal('2020-01-03'), 10.)])

    def test_nonfinite_or_duplicate_saved_values_fail_and_remove_partial_db(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE prices(symbol TEXT,day TEXT,price REAL,adjusted REAL)')
        for value in (float('inf'), float('-inf')):
            db.execute('DELETE FROM prices')
            db.execute("INSERT INTO prices VALUES('A','2020-01-03',?,1)", (value,))
            before = set(self.workdir.iterdir())
            with self.assertRaisesRegex(ValueError, 'finite'):
                method.open_prices(db)
            self.assertEqual(set(self.workdir.iterdir()), before)
        db.execute('DELETE FROM prices')
        db.executemany('INSERT INTO prices VALUES(?,?,?,?)', [('A', '2020-01-03', 1, 1)]*2)
        with self.assertRaisesRegex(ValueError, 'unique'):
            method.open_prices(db)

    def test_finite_zero_and_negative_values_are_not_reinterpreted(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE prices(symbol TEXT,day TEXT,price REAL,adjusted REAL)')
        db.execute("INSERT INTO prices VALUES('A','2020-01-03',0,-2)")
        resolver = method.open_prices(db)
        self.addCleanup(resolver.close)
        self.assertEqual(resolver.resolve([self.q('A', '2020-01-03'), self.q('A', '2020-01-03', 'adjusted')]),
                         [(ordinal('2020-01-03'), 0.), (ordinal('2020-01-03'), -2.)])


if __name__ == '__main__':
    unittest.main()
