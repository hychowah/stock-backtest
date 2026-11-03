"""Private, in-memory capability probe for bounded SQLite JSON projection."""
import json
import sqlite3
import unittest
from contextlib import closing


class SQLiteProjectionProbe(unittest.TestCase):
    def test_json_projection_preserves_selected_state_without_other_fields(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE facts (states TEXT NOT NULL)')
            db.execute('INSERT INTO facts VALUES (?)', (json.dumps({
                'revenue': {'state': 'value', 'value': 12},
                'irrelevant': {'state': 'value', 'value': 'x' * 20000},
            }),))
            selected, absent = db.execute(
                "SELECT json_extract(states, '$.revenue'), "
                "json_extract(states, '$.missing') FROM facts").fetchone()
            self.assertEqual(json.loads(selected), {'state': 'value', 'value': 12})
            self.assertIsNone(absent)


if __name__ == '__main__':
    unittest.main()
