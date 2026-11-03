"""Private predecessor-oracle checks for exact observation content identity."""
import hashlib
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest.inputs import observation_inputs as source


ORDER = [('observation_sources','symbol,endpoint'),
         ('observation_annual','symbol,endpoint,fiscal'),
         ('observation_latest','symbol,pool'),
         ('observation_dated','symbol,endpoint,day'),
         ('observation_sessions','day'),
         ('observation_measure_contexts','mode,pool,context_date,symbol')]


def predecessor(db, scopes=None):
    digest = hashlib.sha256()
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    digest.update(('scopes\n' + encode([] if scopes is None else scopes) + '\n').encode())
    for table, order in ORDER:
        digest.update((table + '\n').encode())
        for row in db.execute('SELECT * FROM ' + table + ' ORDER BY ' + order):
            digest.update((encode(tuple(row)) + '\n').encode())
    return digest.hexdigest()


class IdentityEncodingTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript(source.SCHEMA)

    def same(self, scopes=None):
        self.assertEqual(source.content_identity(self.db, scopes=scopes), predecessor(self.db, scopes))

    def test_builtin_sqlite_json_uses_exact_fast_path(self):
        self.db.execute("INSERT INTO observation_sources VALUES('a','b','{}')")
        statements = []
        self.db.set_trace_callback(statements.append)
        self.addCleanup(self.db.set_trace_callback, None)
        self.same()
        self.assertTrue(any(sql.startswith('SELECT CASE WHEN') for sql in statements))

    def test_all_ascii_unicode_literals_all_tables_and_scopes(self):
        values = [chr(n) for n in range(128)] + ['é', '雪', 'literal \\u007f', '"\\\n']
        self.db.executemany('INSERT INTO observation_sources VALUES(?,?,?)',
            [(f's{i:03d}', 'endpoint', value) for i, value in enumerate(values)])
        self.db.execute('INSERT INTO observation_annual VALUES(?,?,?,?)', ('a','income','2015', '{bad'))
        self.db.execute('INSERT INTO observation_latest VALUES(?,?,?,?)', ('a','cached',1, '{bad'))
        self.db.execute('INSERT INTO observation_dated VALUES(?,?,?,?)', ('a','stock','2015','null'))
        self.db.execute('INSERT INTO observation_sessions VALUES(?,?)', ('2015','{}'))
        self.db.execute('INSERT INTO observation_measure_contexts VALUES(?,?,?,?,?)', ('historical','cached','2015','a','[]'))
        self.same([])
        self.same([dict(mode='historical', pool='cached', context_date='2015', book=2015)])

    def test_integer_real_null_and_exceptional_values(self):
        for i, value in enumerate((0, 1, -1, 2**62, 1.25, None)):
            if value is None:
                continue  # The production schema makes admitted NOT NULL.
            self.db.execute('INSERT INTO observation_latest VALUES(?,?,?,?)', (str(i),'cached',value,'{}'))
        self.same()
        self.db.execute('INSERT INTO observation_sources VALUES(?,?,?)', ('blob','x',sqlite3.Binary(b'bad')))
        with self.assertRaises(TypeError): predecessor(self.db)
        with self.assertRaises(TypeError): source.content_identity(self.db)

    def test_nonfinite_real_propagates_predecessor_error(self):
        self.db.execute('INSERT INTO observation_latest VALUES(?,?,?,?)', ('a','cached',float('inf'),'{}'))
        with self.assertRaises(ValueError): predecessor(self.db)
        with self.assertRaises(ValueError): source.content_identity(self.db)

    def test_nullable_unusual_schema_and_negative_zero(self):
        self.db.execute('DROP TABLE observation_latest')
        self.db.execute('CREATE TABLE observation_latest(symbol TEXT,pool TEXT,admitted,evidence_json TEXT)')
        self.db.executemany('INSERT INTO observation_latest VALUES(?,?,?,?)', [
            ('a', None, None, 'null'), ('b', 'cached', -0.0, '{}'),
            ('c', 'cached', 1.5, '{}')])
        self.same()

    def test_extra_and_generated_columns_use_complete_row(self):
        self.db.execute("ALTER TABLE observation_sources ADD COLUMN extra TEXT DEFAULT 'new'")
        self.db.execute("INSERT INTO observation_sources(symbol,endpoint,evidence_json) VALUES('a','b','{}')")
        self.same()
        self.db.execute("ALTER TABLE observation_sources ADD COLUMN generated TEXT GENERATED ALWAYS AS (symbol || endpoint) VIRTUAL")
        self.same()

    def test_views_use_complete_row(self):
        self.db.execute('ALTER TABLE observation_sources RENAME TO stored_sources')
        self.db.execute('CREATE VIEW observation_sources AS SELECT *, 7 AS extra FROM stored_sources')
        self.db.execute("INSERT INTO stored_sources VALUES('a','b','{}')")
        self.same()

    def test_temporary_view_shadow_uses_ordinary_path(self):
        self.db.execute("INSERT INTO observation_sources VALUES('a','b','{}')")
        self.db.execute('CREATE TEMP VIEW observation_sources AS SELECT * FROM main.observation_sources')
        statements = []
        self.db.set_trace_callback(statements.append)
        self.addCleanup(self.db.set_trace_callback, None)
        actual = source.content_identity(self.db)
        self.assertTrue(any(sql.startswith('SELECT * FROM observation_sources ') for sql in statements))
        self.assertEqual(actual, predecessor(self.db))

    def test_missing_json_and_real_errors_are_distinct(self):
        self.db.execute("INSERT INTO observation_sources VALUES('a','b','{}')")
        class NoJSON:
            def __init__(self, db, message): self.db, self.message = db, message
            def execute(self, sql, *args):
                if sql == "SELECT json_array('probe')": raise sqlite3.OperationalError(self.message)
                return self.db.execute(sql, *args)
        self.assertEqual(source.content_identity(NoJSON(self.db, 'no such function: json_array')), predecessor(self.db))
        with self.assertRaisesRegex(sqlite3.OperationalError, 'database is corrupt'):
            source.content_identity(NoJSON(self.db, 'database is corrupt'))
        class BrokenQuery:
            def execute(self, sql, *args):
                if sql.startswith('SELECT CASE WHEN'):
                    raise sqlite3.OperationalError('disk I/O error')
                return self_db.execute(sql, *args)
        self_db = self.db
        with self.assertRaisesRegex(sqlite3.OperationalError, 'disk I/O error'):
            source.content_identity(BrokenQuery())

    def test_overridden_json_function_uses_ordinary_encoder(self):
        self.db.execute("INSERT INTO observation_sources VALUES('a','b','{}')")
        expected = predecessor(self.db)
        self.db.create_function('json_array', -1,
            lambda *values: '["probe"]' if values == ('probe',) else '["wrong"]')
        self.assertEqual(source.content_identity(self.db), expected)
        self.db.create_function('json_array', -1, lambda *values: '["wrong"]')
        self.assertEqual(source.content_identity(self.db), expected)

    def test_each_table_mutation_and_cancellation(self):
        inserts = ["INSERT INTO observation_sources VALUES('a','b','{}')",
                   "INSERT INTO observation_annual VALUES('a','b','c','{}')",
                   "INSERT INTO observation_latest VALUES('a','b',1,'{}')",
                   "INSERT INTO observation_dated VALUES('a','b','c','{}')",
                   "INSERT INTO observation_sessions VALUES('a','{}')",
                   "INSERT INTO observation_measure_contexts VALUES('a','b','c','d','{}')"]
        for (table, _), insert in zip(ORDER, inserts):
            before = source.content_identity(self.db)
            self.db.execute(insert); self.same()
            self.assertNotEqual(before, source.content_identity(self.db))
            self.db.execute('UPDATE ' + table + " SET evidence_json='changed'"); self.same()
            self.db.execute('DELETE FROM ' + table); self.assertEqual(before, source.content_identity(self.db))
        self.db.execute(inserts[0]); calls = []
        def cancel():
            calls.append(1)
            raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError, 'cancelled'): source.content_identity(self.db, cancel)
        self.assertEqual(len(calls), 1)
        self.same()

    def test_copy_scopes_and_metadata_tampering(self):
        self.db.execute("INSERT INTO observation_sources VALUES('a','b','{}')")
        metadata = source.finish(self.db, '2015-01-02', scopes=[])
        other = sqlite3.connect(':memory:')
        self.addCleanup(other.close)
        other.executescript(source.SCHEMA)
        source.copy(self.db, other)
        self.assertEqual(source.require(other, expected=metadata, verify_content=True), metadata)
        self.assertEqual(source.content_identity(other, scopes=metadata['scopes']), predecessor(self.db, metadata['scopes']))
        other.execute("UPDATE observation_metadata SET value='\"bad\"' WHERE key='content'")
        with self.assertRaises(ValueError): source.require(other, verify_content=True)
        changed = list(metadata['scopes']) + [dict(mode='historical',pool='cached',context_date='2014-01-02',book=2014)]
        self.assertNotEqual(source.content_identity(self.db, scopes=changed), metadata['content'])

    def test_content_change_between_validation_boundaries_is_rejected(self):
        self.db.execute("INSERT INTO observation_sources VALUES('a','b','{}')")
        metadata = source.finish(self.db, '2015-01-02')
        self.assertEqual(source.require(self.db, expected=metadata, verify_content=True), metadata)
        self.db.execute("UPDATE observation_sources SET evidence_json='changed'")
        with self.assertRaises(ValueError):
            source.require(self.db, expected=metadata, verify_content=True)


if __name__ == '__main__':
    unittest.main()
