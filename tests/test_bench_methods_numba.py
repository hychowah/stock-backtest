"""Synthetic SQL-oracle checks for the benchmark-only compiled price resolver."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
from datetime import date, timedelta
from pathlib import Path
import random
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import tools.experiments.bench_methods_numba as method
except ModuleNotFoundError as error:
    if error.name not in ('numpy', 'numba', 'llvmlite'):
        raise
    method = None


@unittest.skipIf(method is None, 'The benchmark-only NumPy/Numba environment is not installed.')
class NumbaPricesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = sqlite3.connect(':memory:')
        cls.db.execute('CREATE TABLE prices(symbol TEXT,day TEXT,price REAL,adjusted REAL,PRIMARY KEY(symbol,day)) WITHOUT ROWID')
        cls.db.executemany('INSERT INTO prices VALUES(?,?,?,?)', [
            ('A', '2024-02-28', 10., None),
            ('A', '2024-02-29', None, 12.),
            ('A', '2024-03-04', 14., 13.),
            ('B', '2024-01-01', None, None),
            ('C', '2024-01-02', None, 30.),
            ('D', '2024-01-03', 40., None),
        ])
        cls.db.commit()
        cls.db.execute('PRAGMA query_only=ON')
        cls.resolver = method.open_prices(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.resolver.close()
        cls.db.close()

    def oracle(self, query):
        symbol, ordinal, column, forward = query
        comparator, ordering = ('>=', 'ASC') if forward else ('<=', 'DESC')
        row = self.db.execute(
            f'SELECT day,{column} FROM prices WHERE symbol=? AND day{comparator}? '
            f'AND {column} IS NOT NULL ORDER BY day {ordering} LIMIT 1',
            (symbol, date.fromordinal(ordinal).isoformat())).fetchone()
        return (date.fromisoformat(row[0]).toordinal(), float(row[1])) if row else None

    def test_sparse_columns_boundaries_and_mixed_directions(self):
        queries = [(symbol, date.fromisoformat(day).toordinal(), column, forward)
                   for symbol in ('A', 'B', 'C', 'D', 'UNKNOWN')
                   for day in ('2023-12-31', '2024-01-02', '2024-02-28', '2024-02-29',
                               '2024-03-01', '2024-03-04', '2024-03-05')
                   for column in ('price', 'adjusted') for forward in (False, True)]
        random.Random(42).shuffle(queries)
        self.assertEqual(self.resolver.resolve(queries), [self.oracle(query) for query in queries])

    def test_random_queries_and_duplicates_keep_order(self):
        generator = random.Random(1729)
        first = date(2023, 12, 1)
        queries = [(generator.choice(('A', 'B', 'C', 'D', 'MISSING')),
                    (first + timedelta(days=generator.randrange(140))).toordinal(),
                    generator.choice(('price', 'adjusted')), bool(generator.randrange(2)))
                   for unused in range(1000)]
        queries.extend(queries[:50])
        self.assertEqual(self.resolver.resolve(queries), [self.oracle(query) for query in queries])

    def test_empty_database_empty_batch_and_closure(self):
        db = sqlite3.connect(':memory:')
        try:
            db.execute('CREATE TABLE prices(symbol TEXT,day TEXT,price REAL,adjusted REAL)')
            resolver = method.open_prices(db)
            self.assertEqual(resolver.resolve([]), [])
            self.assertEqual(resolver.resolve([('A', 1, 'price', True)]), [None])
            resolver.close()
            resolver.close()
            with self.assertRaisesRegex(RuntimeError, 'closed'):
                resolver.resolve([])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM prices').fetchone()[0], 0)
        finally:
            db.close()

    def test_stats_account_for_sparse_numeric_payload(self):
        stats = self.resolver.stats
        self.assertEqual(stats['rows'], 6)
        self.assertEqual(stats['symbols'], 4)
        self.assertEqual(stats['raw_rows'], 3)
        self.assertEqual(stats['adjusted_rows'], 3)
        self.assertEqual(stats['payload_bytes'], 6 * 12 + 2 * 5 * 8)
        self.assertGreaterEqual(stats['load_seconds'], 0)
        self.assertGreaterEqual(stats['compile_seconds'], 0)
        self.assertTrue(1 <= stats['threads'] <= 4)
        self.assertFalse(stats['compiler_cache'])
        self.assertEqual(set(stats['versions']), {'numpy', 'numba', 'llvmlite'})

    def test_invalid_queries_fail_instead_of_changing_policy(self):
        for query in [('A', 0, 'price', True), ('A', 1, 'volume', True),
                      ('A', 1, 'price', 1), (None, 1, 'price', True),
                      ('A', True, 'price', False), ('A', 1, 'price')]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.resolver.resolve([query])

    def test_nonfinite_saved_prices_fail_before_use(self):
        db = sqlite3.connect(':memory:')
        try:
            db.execute('CREATE TABLE prices(symbol TEXT,day TEXT,price REAL,adjusted REAL)')
            db.execute("INSERT INTO prices VALUES('A','2024-01-01',?,NULL)", (float('inf'),))
            with self.assertRaisesRegex(ValueError, 'finite'):
                method.open_prices(db)
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
