"""Replay frozen Phase 9 entry evidence; never regenerate expected results here."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from contextlib import closing
import hashlib
import json
import unittest

from backtest import screening
from backtest.inputs import financial_inputs as financial, research
import test_baseline
import test_selection_order

FIXTURES = Path(__file__).parent/'fixtures'/'phase09_legacy'


def replay():
    """Run actual entry owners on private synthetic assets and SQL fixtures."""
    fixture = test_baseline.BaselineTests('test_new_price_refreshes_both_engines_and_preserves_exact_previous_evidence')
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
        research.prepare(fixture.path)
        with closing(research.connect(fixture.path)) as db:
            baseline = research.verify_reference(db)
            financial_rows = [tuple(row) for row in db.execute('SELECT * FROM financial_inputs ORDER BY symbol,fiscal')]
            filters = [tuple(row) for row in db.execute('SELECT * FROM filter_values ORDER BY mode,pool,year,symbol,field')]
        report = (research.RESULTS/'summary-exits.txt').read_text()
    finally:
        fixture.doCleanups()
    selection = test_selection_order.SelectionOrderTests('test_filter_first_default_and_rank_first_does_not_refill')
    selection.setUp()
    try:
        selections = {}
        for mode, select in [('historical', screening.historical), ('latest', screening.latest)]:
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
        baseline=baseline, report=report, financial_rows=financial_rows, filters=filters, selections=selections), allow_nan=False))


class FrozenLegacyTests(unittest.TestCase):
    def test_entry_provenance_and_bytes(self):
        manifest = (FIXTURES/'manifest.json').read_bytes()
        self.assertEqual(hashlib.sha256(manifest).hexdigest(), 'f3936e75a5a4bf43de69ce86baa6e4f7a07eef5ef1caf68ddf821f1cd7a7bc46')
        receipt = json.loads(manifest)
        self.assertEqual(receipt['entry_commit'], '30ff79d1f93f3e802efdd0d9a01ff61d42766bb9')
        for name, digest in receipt['files'].items():
            self.assertEqual(hashlib.sha256((FIXTURES/name).read_bytes()).hexdigest(), digest)

    def test_legacy_projections_baseline_and_both_selection_orders(self):
        self.assertEqual(replay(), json.loads((FIXTURES/'expected.json').read_text()))


if __name__ == '__main__': unittest.main()
