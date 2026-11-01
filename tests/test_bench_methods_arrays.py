"""Synthetic conformance checks for the benchmark-only arrays resolver."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
from datetime import date
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.experiments.bench_methods_arrays import open_prices


def ordinal(day):
    return date.fromisoformat(day).toordinal()


class ArrayPricesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'saved prices.sqlite'
        db = sqlite3.connect(self.path)
        db.execute('CREATE TABLE prices(symbol TEXT, day TEXT, price REAL, '
                   'adjusted REAL, PRIMARY KEY(symbol,day)) WITHOUT ROWID')
        db.executemany('INSERT INTO prices VALUES(?,?,?,?)', [
            ('A', '2020-01-02', 10, None),
            ('A', '2020-01-03', None, 20),
            ('A', '2020-01-06', 12, 22),
            ('A', '2020-01-07', None, None),
            ('B', '2020-01-03', 30, None),
            ('EMPTY', '2020-01-03', None, None),
            # Deliberately far from A: no tolerance belongs in this backend.
            ('STOP', '1999-12-31', 1, 2),
        ])
        db.commit()
        db.close()
        self.db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        self.addCleanup(self.db.close)
        self.resolver = open_prices(self.db)
        self.addCleanup(self.resolver.close)

    def query(self, symbol, day, column='price', forward=False):
        return symbol, ordinal(day), column, forward

    def test_exact_day_both_directions_and_actual_saved_date(self):
        queries = [self.query('A', '2020-01-06', column, forward)
                   for column in ('price', 'adjusted') for forward in (False, True)]
        self.assertEqual(self.resolver.resolve(queries), [
            (ordinal('2020-01-06'), 12.0),
            (ordinal('2020-01-06'), 12.0),
            (ordinal('2020-01-06'), 22.0),
            (ordinal('2020-01-06'), 22.0),
        ])
        self.assertEqual(self.resolver.resolve([
            self.query('A', '2020-01-04'),
            self.query('A', '2020-01-04', forward=True),
        ]), [(ordinal('2020-01-02'), 10.0), (ordinal('2020-01-06'), 12.0)])

    def test_mixed_order_nulls_columns_and_two_waves(self):
        first = self.resolver.resolve([
            self.query('B', '2020-01-03', 'adjusted'),
            self.query('A', '2020-01-02', 'adjusted', True),
            self.query('A', '2020-01-03'),
            self.query('MISSING', '2020-01-03', forward=True),
            self.query('A', '2020-01-07', 'adjusted'),
            self.query('EMPTY', '2020-01-03'),
        ])
        self.assertEqual(first, [None, (ordinal('2020-01-03'), 20.0),
                                 (ordinal('2020-01-02'), 10.0), None,
                                 (ordinal('2020-01-06'), 22.0), None])
        # Raw entry can precede adjusted entry. Feed the actual raw date back.
        self.assertEqual(self.resolver.resolve([
            ('A', first[2][0], 'adjusted', True),
        ]), [(ordinal('2020-01-03'), 20.0)])

    def test_boundaries_no_slack_and_empty_batch(self):
        self.assertEqual(self.resolver.resolve([
            self.query('A', '2019-12-31'),
            self.query('A', '2020-01-08', forward=True),
            self.query('A', '2019-12-31', forward=True),
            self.query('A', '2020-01-08'),
            self.query('STOP', '2026-10-21', 'adjusted'),
        ]), [None, None, (ordinal('2020-01-02'), 10.0),
             (ordinal('2020-01-06'), 12.0), (ordinal('1999-12-31'), 2.0)])
        self.assertEqual(self.resolver.resolve([]), [])

    def test_invalid_queries_fail_instead_of_guessing(self):
        valid = self.query('A', '2020-01-03')
        malformed = [None, 'A', valid[:3], valid + (None,),
                     ('', valid[1], 'price', False),
                     (None, valid[1], 'price', False),
                     ('A', True, 'price', False),
                     ('A', float(valid[1]), 'price', False),
                     ('A', '2020-01-03', 'price', False),
                     ('A', 0, 'price', False),
                     ('A', date.max.toordinal() + 1, 'price', False),
                     ('A', valid[1], 'close', False),
                     ('A', valid[1], 'price', 1)]
        for query in malformed:
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.resolver.resolve([query])

    def test_statistics_and_close_preserve_caller_owned_connection(self):
        stats = self.resolver.stats
        self.assertEqual(stats['rows'], 7)
        self.assertEqual(stats['symbols'], 4)
        self.assertEqual(stats['raw_points'], 4)
        self.assertEqual(stats['adjusted_points'], 3)
        self.assertEqual(stats['payload_bytes'], 7 * (4 + 8))
        self.assertGreaterEqual(stats['allocated_bytes'], stats['payload_bytes'])
        self.assertGreaterEqual(stats['load_seconds'], 0)
        self.resolver.resolve([self.query('A', '2020-01-02')])
        self.assertEqual(stats['resolve_calls'], 1)
        self.assertEqual(stats['queries'], 1)
        self.resolver.close()
        self.resolver.close()
        with self.assertRaises(RuntimeError):
            self.resolver.resolve([])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM prices').fetchone()[0], 7)
        with self.assertRaises(sqlite3.OperationalError):
            self.db.execute('DELETE FROM prices')

    def test_physical_missing_column_and_empty_database(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE prices(symbol TEXT, day TEXT, price REAL)')
        empty = open_prices(db)
        self.addCleanup(empty.close)
        self.assertEqual(empty.stats['rows'], 0)
        self.assertEqual(empty.resolve([self.query('A', '2020-01-03')]), [None])
        db.execute("INSERT INTO prices VALUES('A','2020-01-03',10)")
        partial = open_prices(db)
        self.addCleanup(partial.close)
        self.assertEqual(partial.resolve([
            self.query('A', '2020-01-03', 'adjusted'),
            self.query('A', '2020-01-03'),
        ]), [None, (ordinal('2020-01-03'), 10.0)])

    def test_nonfinite_saved_prices_are_rejected(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE prices(symbol TEXT, day TEXT, price REAL, adjusted REAL)')
        db.execute("INSERT INTO prices VALUES('A','2020-01-03',?,1)", (float('inf'),))
        with self.assertRaises(ValueError):
            open_prices(db)

    def test_all_fixture_lookups_match_ordered_sql(self):
        queries = []
        expected = []
        for symbol in ('A', 'B', 'EMPTY', 'STOP', 'MISSING'):
            for day in range(ordinal('2020-01-01'), ordinal('2020-01-10')):
                for column in ('price', 'adjusted'):
                    for forward in (False, True):
                        queries.append((symbol, day, column, forward))
                        relation, order = ('>=', 'ASC') if forward else ('<=', 'DESC')
                        result = self.db.execute(
                            f'SELECT day,{column} FROM prices WHERE symbol=? '
                            f'AND day{relation}? AND {column} IS NOT NULL '
                            f'ORDER BY day {order} LIMIT 1',
                            (symbol, str(date.fromordinal(day)))).fetchone()
                        expected.append(None if result is None
                                        else (ordinal(result[0]), float(result[1])))
        self.assertEqual(self.resolver.resolve(queries), expected)

    def test_import_and_absolute_database_path_from_another_folder(self):
        script = (
            'from pathlib import Path; import sqlite3, sys; '
            f'sys.path.insert(0, {str(ROOT)!r}); '
            'from tools.experiments.bench_methods_arrays import open_prices; '
            'db=sqlite3.connect(Path(sys.argv[1]).as_uri()+"?mode=ro", uri=True); '
            'r=open_prices(db); '
            f'assert r.resolve([("A", {ordinal("2020-01-04")}, "price", True)])'
            f'==[({ordinal("2020-01-06")}, 12.0)]; '
            'r.close(); db.close()'
        )
        completed = subprocess.run([sys.executable, '-c', script, str(self.path)],
                                   cwd=self.folder.name, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__':
    unittest.main()
