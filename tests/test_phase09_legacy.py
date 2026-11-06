"""Replay frozen Phase 9 entry evidence; never regenerate expected results here.

P2b removed the January books, their baseline and the report. The replay
compares every part that still exists with the frozen values: financial
projections and completion, financial rows, latest filter rows, and both
selection orders over latest and dated book rows. P3b moved the latest book into
the daily cache's book store: its filter rows keep the frozen
(mode, pool, year 0, symbol, field, value) form, and a dated row no longer
carries the private period id (year). P3c2 deleted the research financial_inputs
table: the financial rows are the typed annual facts' values-only projection.
"""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from contextlib import closing
import hashlib
import json
import unittest

from backtest import screening
from backtest.inputs import book_store, daily, facts, financial_inputs as financial, research
import test_research
import test_selection_order

FIXTURES = Path(__file__).parent/'fixtures'/'phase09_legacy'


def replay():
    """Run actual entry owners on private synthetic assets and SQL fixtures."""
    fixture = test_research.PreparationTests('test_success_publishes_database_without_january_books')
    fixture.setUp()
    try:
        inputs = json.loads((FIXTURES/'inputs.json').read_text())
        ledger = {}
        for symbol, endpoints in inputs.items():
            for endpoint, rows in endpoints.items():
                financial.publish(research.RAW, symbol, endpoint, rows, ledger, research.RAW/'coverage.json')
        projections = {symbol: financial.history(research.RAW, symbol) for symbol in inputs}
        completion = {symbol: {endpoint: financial.completed(research.RAW, symbol, endpoint, ledger)
                              for endpoint in financial.ENDPOINTS} for symbol in inputs}
        daily.prepare(fixture.daily, fixture.path)
        with closing(daily.connect(fixture.daily, fixture.path)) as db:
            # The legacy values-only rows (symbol, fiscal, JSON), now read from the typed annual facts.
            financial_rows = [(symbol, fiscal, json.dumps(values))
                              for symbol, in db.execute('SELECT DISTINCT symbol FROM research.annual_facts ORDER BY symbol')
                              for fiscal, values in sorted(facts.legacy_annual(db, symbol).items())]
            book = book_store.open_book(db)
            filters = sorted(('latest', pool, 0, symbol, field, value) for pool in ('legacy', 'cached')
                             for symbol, found in book_store.lanes(db, book, pool)[1].items() for field, value in found.items())
    finally:
        fixture.doCleanups()
    selection = test_selection_order.SelectionOrderTests('test_filter_first_default_and_rank_first_does_not_refill')
    selection.setUp()
    try:
        selections = {}
        for mode, select in [('historical', test_selection_order.dated), ('latest', screening.latest)]:
            for pool in ('legacy', 'cached'):
                for order in ('filter_first', 'rank_first'):
                    for filtered in (False, True):
                        options = dict(pool=pool, selection_order=order, rank_to=2)
                        if mode == 'historical': options.update(first=2015, last=2015)
                        if filtered: options.update(min_cap=150e6)
                        selections[f'{mode}/{pool}/{order}/{filtered}'] = select(selection.db, **options)
    finally:
        selection.doCleanups()
    return json.loads(json.dumps(dict(projections=projections, completion=completion,
        financial_rows=financial_rows, filters=filters, selections=selections), allow_nan=False))


class FrozenLegacyTests(unittest.TestCase):
    def test_entry_provenance_and_bytes(self):
        manifest = (FIXTURES/'manifest.json').read_bytes()
        self.assertEqual(hashlib.sha256(manifest).hexdigest(), 'f3936e75a5a4bf43de69ce86baa6e4f7a07eef5ef1caf68ddf821f1cd7a7bc46')
        receipt = json.loads(manifest)
        self.assertEqual(receipt['entry_commit'], '30ff79d1f93f3e802efdd0d9a01ff61d42766bb9')
        for name, digest in receipt['files'].items():
            self.assertEqual(hashlib.sha256((FIXTURES/name).read_bytes()).hexdigest(), digest)

    def test_legacy_projections_and_both_selection_orders(self):
        expected = json.loads((FIXTURES/'expected.json').read_text())
        for removed in ('baseline', 'report'):
            del expected[removed]
        expected['filters'] = [row for row in expected['filters'] if row[0] == 'latest']
        for name, rows in expected['selections'].items():
            for row in rows:
                row.pop('year', None)
        self.assertEqual(replay(), expected)


if __name__ == '__main__': unittest.main()
