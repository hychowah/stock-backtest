"""Annual resolution evidence and the typed prepared facts that research publishes."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from contextlib import ExitStack, closing
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backtest.inputs import financial_inputs as financial, facts
from backtest.inputs import daily, research
import test_research as research_fixtures


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.raw = Path(self.folder.name)
        self.ledger = {}

    def publish(self, rows):
        financial.publish(self.raw, 'A', 'income-statement', rows, self.ledger, self.raw/'coverage.json')
        return financial.asset_path(self.raw, 'A', 'income-statement')

    def test_equal_variants_nulls_signed_values_and_empty_dates_preserve_values(self):
        common = dict(date='2023-12-31', reportedCurrency='USD', revenue=100, operatingIncome=-10)
        path = self.publish([common, dict(common, operatingIncome=None), dict(common),
                             dict(common, reportedCurrency='EUR', revenue=999),
                             dict(date='2024-12-31', reportedCurrency='USD', revenue=None)])
        before = path.read_bytes()
        resolved = financial.resolve_history(self.raw, 'A')
        self.assertEqual(resolved['values'], {'2023-12-31': dict(revenue=100, operatingIncome=-10)})
        self.assertEqual(financial.history(self.raw, 'A'), resolved['values'])
        self.assertEqual(resolved['annual']['income-statement']['2024-12-31']['revenue']['reason'], 'MISSING_INPUT')
        field = resolved['annual']['income-statement']['2023-12-31']['operatingIncome']
        self.assertTrue(field['valid']); self.assertEqual(field['value'], -10)
        self.assertEqual(len(field['rows']), 4)
        self.assertEqual(resolved['sources']['income-statement']['sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(path.read_bytes(), before)

    def test_independent_conflicts_and_non_usd_reasons(self):
        common = dict(date='2023-12-31', reportedCurrency='USD', revenue=100)
        self.publish([dict(common, operatingIncome=10), dict(common, operatingIncome=11),
                      dict(date='2022-12-31', reportedCurrency='EUR', revenue=20, operatingIncome=2),
                      dict(date='2021-12-31', revenue=20, operatingIncome=2)])
        resolved = financial.resolve_history(self.raw, 'A')
        self.assertEqual(resolved['values'], {'2023-12-31': dict(revenue=100)})
        rows = resolved['annual']['income-statement']
        self.assertEqual(rows['2023-12-31']['operatingIncome']['reason'], 'CONFLICTING_INPUT')
        self.assertEqual(rows['2022-12-31']['revenue']['reason'], 'NON_USD_INPUT')
        self.assertEqual(rows['2021-12-31']['revenue']['reason'], 'MISSING_INPUT')
        self.assertEqual(resolved['sources']['balance-sheet-statement']['disposition'], 'missing')

    def test_salvage_hash_identifies_bytes_without_proving_completion(self):
        good = dict(date='2023-12-31', reportedCurrency='USD', revenue=100, operatingIncome=10)
        path = self.publish([good])
        payload = json.loads(path.read_bytes()); payload['rows'].insert(0, 'damaged')
        path.write_text(json.dumps(payload)); before = path.read_bytes()
        resolved = financial.resolve_history(self.raw, 'A')
        self.assertEqual(financial.read(self.raw, 'A', 'income-statement'), ([good], None))
        self.assertFalse(financial.completed(self.raw, 'A', 'income-statement', self.ledger))
        self.assertEqual(resolved['sources']['income-statement'], dict(endpoint='income-statement',
            disposition='salvaged', sha256=hashlib.sha256(before).hexdigest()))
        self.assertEqual(resolved['annual']['income-statement']['2023-12-31']['revenue']['rows'][0]['index'], 1)
        self.assertEqual(path.read_bytes(), before)

    def test_unreadable_and_absent_assets_remain_distinct(self):
        missing = financial.resolve_history(self.raw, 'A')
        self.assertEqual(missing['values'], {})
        path = self.publish([]); path.write_bytes(b'{invalid')
        resolved = financial.resolve_history(self.raw, 'A')
        self.assertEqual(resolved['values'], {})
        self.assertEqual(resolved['sources']['income-statement']['disposition'], 'unreadable')
        self.assertEqual(resolved['sources']['income-statement']['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.real_signature = research.signature
        self.fixture = research_fixtures.PreparationTests('test_success_publishes_database_without_january_books')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = self.fixture.path
        self.path = self.source.with_name('daily.sqlite')
        financial.publish(research.RAW, 'TEST', 'income-statement', [
            dict(date=f'{year}-06-30', reportedCurrency='USD', revenue=100e6, operatingIncome=value)
            for year, value in ((2012, 10e6), (2013, -5e6), (2014, None))], {}, research.RAW/'coverage.json')

    def prepare(self):
        daily.prepare(self.path, self.source)

    def test_complete_chain_preserves_evidence_dates_and_latest_valuation(self):
        self.prepare()
        with closing(research.connect(self.source)) as original, closing(sqlite3.connect(self.path)) as copied:
            first = facts.require(original)
            self.assertEqual(first['latest_date'], '2015-10-20')
            self.assertEqual(json.loads(copied.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])['facts'], first)
            # The daily cache binds the facts; it holds no copy of them.
            names = {row[0] for row in copied.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertFalse(names & {'stock_days', 'market_days', 'annual_facts', 'fact_sources',
                                       'latest_admission', 'fact_metadata'})
            self.assertFalse([name for name in names if name.startswith('observation_')])
            row = original.execute("SELECT operating_income,operating_income_reason,revenue FROM annual_facts "
                                   "WHERE symbol='TEST' AND fiscal='2014-06-30'").fetchone()
            self.assertEqual(tuple(row), (None, 'MISSING_INPUT', 100e6))
            latest = original.execute("SELECT admitted,reason,fiscal,market_cap,enterprise_value FROM latest_admission "
                                      "WHERE symbol='TEST' AND pool='legacy'").fetchone()
            self.assertEqual(tuple(latest)[:3], (1, None, '2014-06-30'))
            self.assertEqual(latest['enterprise_value'], 270e6)
            source = original.execute("SELECT sha256,disposition FROM fact_sources WHERE symbol='TEST' AND endpoint=?",
                                      (facts.STOCK,)).fetchone()
            self.assertEqual(source[0], hashlib.sha256((research.RAW/'px/TEST.json').read_bytes()).hexdigest())

    def test_latest_denials_keep_exact_session_and_listing_policy(self):
        for listed, exact, reason in ((False, True, 'NOT_LISTED'), (True, False, 'MISSING_PRICE')):
            with self.subTest(listed=listed, exact=exact):
                universe = json.loads((research.RAW/'universe.json').read_text())
                universe[0]['listed'] = listed
                (research.RAW/'universe.json').write_text(json.dumps(universe))
                path = research.RAW/'px/TEST.json'; prices = json.loads(path.read_text())
                prices['div'][-1]['date'] = '2015-10-20' if exact else '2015-10-19'
                path.write_text(json.dumps(prices))
                research.prepare(self.source, force=True)
                with closing(research.connect(self.source)) as db:
                    rows = db.execute('SELECT admitted,reason FROM latest_admission').fetchall()
                    self.assertTrue(rows)
                    self.assertEqual({tuple(row) for row in rows}, {(0, reason)})
                    self.assertEqual(db.execute('SELECT count(*) FROM latest_snapshots').fetchone()[0], 0)

    def test_projection_source_change_and_missing_metadata_fail_closed(self):
        self.prepare()
        with closing(sqlite3.connect(self.source)) as db:
            expected = facts.require(db)
            with patch.object(facts, 'policy_binding', return_value={'changed': 'source'}):
                with self.assertRaisesRegex(ValueError, 'stale'): facts.require(db)
            db.execute('DELETE FROM fact_metadata')
            with self.assertRaisesRegex(ValueError, 'missing'): facts.require(db, expected=expected)

    def test_policy_change_rebuilds_research_before_downstream_preparation(self):
        from backtest import measure_observations
        with ExitStack() as context:
            for module in (research, research.metrics, research.books, research.rules, research.cache_assets,
                           research.market, financial, financial.parameters, measure_observations, facts):
                path = research.ROOT / Path(module.__file__).name
                path.write_bytes(Path(module.__file__).read_bytes())
                context.enter_context(patch.object(module, '__file__', str(path)))
            context.enter_context(patch.object(research, 'signature', side_effect=self.real_signature))
            self.prepare()
            previous = research.prepared_bindings(self.source)[1]
            signature = research.signature()
            policy = research.ROOT/'facts.py'
            policy.write_bytes(policy.read_bytes() + b'\n# Changed private policy fixture.\n')
            # The binding is hashed once per process; deployment restarts it.
            self.addCleanup(facts._policy_binding.cache_clear)
            facts._policy_binding.cache_clear()
            self.assertNotEqual(research.signature(), signature)
            with closing(sqlite3.connect(self.source)) as db:
                with self.assertRaisesRegex(ValueError, 'stale'): facts.require(db)
            # Ordinary preparation must repair the rejected policy without force.
            research.prepare(self.source)
            current = research.prepared_bindings(self.source)[1]
            self.assertNotEqual(current['policy']['facts.py'], previous['policy']['facts.py'])
            self.prepare()
            with closing(daily.connect(self.path, self.source)) as db:
                saved = json.loads(db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])
                self.assertEqual(saved['facts'], current)

    def test_daily_cancellation_preserves_previous_database(self):
        self.prepare(); before = self.path.read_bytes()
        def cancelled(): raise RuntimeError('fixture cancellation')
        with patch.object(daily, 'fingerprint', return_value={'stale inputs': True}), \
             patch.object(daily.backtest_control, 'checkpoint', side_effect=cancelled):
            with self.assertRaisesRegex(RuntimeError, 'fixture cancellation'):
                daily.prepare(self.path, self.source)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.path.with_name(self.path.name+'.building').exists())


if __name__ == '__main__':
    unittest.main()
