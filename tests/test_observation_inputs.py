"""Private source-evidence, prepared-copy and borrowed-attachment contracts."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from contextlib import ExitStack, closing
from datetime import date
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backtest.inputs import financial_inputs as financial, observation_inputs as observed
from backtest.inputs import daily, research
from backtest.engines.numerical import generation
import test_research as research_fixtures
import test_numerical_generation as generation_fixtures


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
        self.fixture = research_fixtures.PreparationTests('test_success_publishes_verified_database')
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
            first = observed.require(original, verify_content=True)
            self.assertEqual(observed.require(copied, verify_content=True), first)
            self.assertEqual(first['latest_date'], '2015-10-20')
            for table in observed.TABLES:
                self.assertEqual([tuple(row) for row in original.execute('SELECT * FROM '+table)], copied.execute('SELECT * FROM '+table).fetchall())
            evidence = json.loads(copied.execute("SELECT evidence_json FROM observation_annual WHERE fiscal='2014-06-30'").fetchone()[0])
            self.assertIsNone(evidence['operatingIncome']['value'])
            latest = json.loads(copied.execute("SELECT evidence_json FROM observation_latest WHERE pool='legacy'").fetchone()[0])
            self.assertTrue(latest['admitted'])
            self.assertEqual(latest['fiscal_price'], ['2014-06-30', 10])
            self.assertEqual(latest['valuation_price'], ['2015-10-20', 22])
            self.assertEqual(latest['valuation']['enterprise_value'], 270e6)

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
                    for admitted, text in db.execute('SELECT admitted,evidence_json FROM observation_latest'):
                        evidence = json.loads(text)
                        self.assertFalse(admitted); self.assertEqual(evidence['reason'], reason)
                    self.assertEqual(db.execute('SELECT count(*) FROM latest_snapshots').fetchone()[0], 0)

    def test_real_preparation_through_immutable_generation_and_pending_guard(self):
        self.prepare()
        ordinary_connect = daily.connect
        ordinary_research_connect = research.connect
        store = generation.GenerationStore(self.source.parent/'numerical',
            generation.cache_access.WorkspaceAccess(self.source.parent/'fixture.lock'))
        with patch.object(daily, 'connect', side_effect=lambda: ordinary_connect(self.path, self.source)), \
             patch.object(research, 'connect', side_effect=lambda path=self.source, **kw: ordinary_research_connect(path, **kw)):
            receipt = store.prepare()
            with store.open_current() as attached:
                with attached.observations() as view:
                    self.assertEqual(view.identity, receipt['identity'])
                    facts = view.company('TEST', 'legacy')
                    self.assertTrue(facts['latest']['admitted'])
                    self.assertEqual(facts['annual']['income-statement']['2013-06-30']['operatingIncome']['value'], -5e6)
                    self.assertEqual(view.lookup('TEST', date(2015, 10, 20), 'adjusted', False, 0),
                                     (date(2015, 10, 20), 22))
            marker = self.source.parent/'research.sqlite.publication.json'
            marker.write_text('{}')
            try:
                with self.assertRaisesRegex(ValueError, 'Unfinished publication'):
                    store.open_current()
            finally:
                marker.unlink()

    def test_projection_source_and_content_tampering_fail_closed(self):
        self.prepare()
        with closing(sqlite3.connect(self.path)) as db:
            expected = observed.require(db)
            with patch.object(observed, 'policy_binding', return_value={'changed': 'source'}):
                with self.assertRaisesRegex(ValueError, 'stale'): observed.require(db)
            db.execute("UPDATE observation_annual SET evidence_json='{}'")
            with self.assertRaisesRegex(ValueError, 'stale'): observed.require(db, verify_content=True)
            db.execute('DELETE FROM observation_metadata')
            with self.assertRaisesRegex(ValueError, 'missing'): observed.require(db, expected=expected)

    def test_daily_policy_change_rebuilds_research_before_downstream_preparation(self):
        source_folder = Path(research.__file__).parent
        with ExitStack() as context:
            for module in (research, research.baseline, research.metrics, research.books,
                           research.rules, research.screening, research.selection, research.cache_assets,
                           research.market, research.legacy, research.revalue, financial, observed, financial.parameters, research.dated_observation_inputs, observed.measure_observations):
                path = research.ROOT / Path(module.__file__).name
                path.write_bytes(Path(module.__file__).read_bytes())
                context.enter_context(patch.object(module, '__file__', str(path)))
            for name in ('legacy_downloads.py', 'fmp_download.py', 'daily.py'):
                (research.ROOT/name).write_bytes((source_folder/name).read_bytes())
            context.enter_context(patch.object(research, 'signature', side_effect=self.real_signature))
            self.prepare()
            previous = research.prepared_observation_binding(self.source)
            signature = research.signature()
            policy = research.ROOT/'daily.py'
            policy.write_bytes(policy.read_bytes() + b'\n# Changed private daily policy fixture.\n')
            self.assertNotEqual(research.signature(), signature)
            with closing(sqlite3.connect(self.source)) as db:
                with self.assertRaisesRegex(ValueError, 'stale'): observed.require(db)
            # Ordinary preparation must repair the rejected policy without force.
            research.prepare(self.source)
            current = research.prepared_observation_binding(self.source)
            self.assertNotEqual(current['policy']['daily.py'], previous['policy']['daily.py'])
            self.prepare()
            with closing(daily.connect(self.path, self.source)) as db:
                self.assertEqual(observed.require(db, verify_content=True), current)

    def test_daily_cancellation_preserves_previous_database(self):
        self.prepare(); before = self.path.read_bytes()
        def cancelled(): raise RuntimeError('fixture cancellation')
        with patch.object(daily, 'connect', side_effect=ValueError('force rebuild')), \
             patch.object(daily.backtest_control, 'checkpoint', side_effect=cancelled):
            with self.assertRaisesRegex(RuntimeError, 'fixture cancellation'):
                daily.prepare(self.path, self.source)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.path.with_name(self.path.name+'.building').exists())

    def test_legacy_daily_upgrade_cannot_invent_observation_projection(self):
        self.prepare()
        with closing(sqlite3.connect(self.path)) as db:
            current = json.loads(db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])
            old = dict(current, version=2); old.pop('observations'); old.pop('observation_version')
            db.execute("UPDATE metadata SET value=? WHERE key='daily_inputs'", (json.dumps(old),)); db.commit()
        before = self.path.read_bytes()
        self.assertFalse(daily.upgrade_daily_cache(self.path, current))
        self.assertEqual(self.path.read_bytes(), before)


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = generation_fixtures.GenerationTests('test_export_values_order_missingness_and_mutable_books_reuse')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.db, self.binding = self.fixture.db, self.fixture.binding
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder)
            financial.publish(raw, 'A', 'income-statement', [
                dict(date='2014-06-30', reportedCurrency='USD', revenue=100, operatingIncome=-5),
                dict(date='2013-06-30', reportedCurrency='USD', revenue=None)], {}, raw/'coverage.json')
            observed.store_annual(self.db, 'A', financial.resolve_history(raw, 'A'))
        for pool in ('legacy', 'cached'):
            observed.store_latest(self.db, 'A', pool, dict(admitted=True, root_date='2016-12-30'))
        self.binding['observations'] = observed.finish(self.db, '2016-12-30')
        self.db.commit()

    def test_generation_copy_borrowed_view_detachment_prices_and_closure(self):
        self.fixture.prepare()
        attached = self.fixture.attach()
        view = attached.observations()
        self.addCleanup(view.close)
        company = view.company('A', 'legacy')
        self.assertEqual(company['annual']['income-statement']['2014-06-30']['operatingIncome']['value'], -5)
        self.assertIn('2013-06-30', company['annual']['income-statement'])
        for table in observed.TABLES:
            self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM '+table)],
                             [tuple(row) for row in attached._db.execute('SELECT * FROM '+table)])
        # Price lookup uses the identical stored series, date and tolerance.
        for column in ('price', 'adjusted'):
            for forward in (False, True):
                for day in (date(2015, 1, 1), date(2015, 1, 2), date(2015, 1, 5)):
                    self.assertEqual(view.lookup('A', day, column, forward, 4),
                                     daily.price(self.db, 'A', day, column, forward, 4))
        detached = observed.encoded(company)
        view.close(); attached.close()
        self.assertEqual(observed.encoded(company), detached)
        with self.assertRaisesRegex(ValueError, 'closed'): view.validate()
        with self.assertRaisesRegex(ValueError, 'closed'): view.company('A', 'legacy')

    def test_missing_projection_stale_generation_and_closed_attachment_reject(self):
        self.fixture.prepare(); attached = self.fixture.attach()
        view = attached.observations(); self.addCleanup(view.close)
        self.binding['prices'] = {'changed': True}
        with self.assertRaisesRegex(ValueError, 'stale'): view.validate()
        attached.close()
        with self.assertRaisesRegex(ValueError, 'closed'): attached.observations()
        self.db.execute('DELETE FROM observation_metadata'); self.db.commit()
        self.binding.pop('observations'); self.fixture.prepare()
        missing = self.fixture.attach()
        with self.assertRaisesRegex(ValueError, 'no admitted'): missing.observations()

    def test_export_cancellation_preserves_current_generation(self):
        first = self.fixture.prepare()
        self.binding['prices'] = {'changed': True}
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls > 5: raise RuntimeError('fixture cancellation')
        with self.assertRaisesRegex(RuntimeError, 'fixture cancellation'):
            self.fixture.store.prepare(checkpoint=cancel)
        self.assertEqual(self.fixture.store._pointer()['current'], first['identity'])

    def test_observation_record_byte_boundary_rejects_before_publication(self):
        row = self.db.execute("SELECT * FROM observation_annual WHERE fiscal='2014-06-30'").fetchone()
        size = sum(len(value.encode('utf-8')) for value in row)
        # Valid JSON whitespace changes only its byte size, not its source facts.
        boundary = row[-1] + ' ' * (generation.MAX_MANIFEST - size)
        def replace(text):
            self.db.execute("UPDATE observation_annual SET evidence_json=? WHERE fiscal='2014-06-30'", (text,))
            self.db.execute('DELETE FROM observation_metadata')
            self.binding['observations'] = observed.finish(self.db, '2016-12-30')
            self.db.commit()
        replace(boundary)
        first = self.fixture.prepare()
        with self.fixture.store.open_current() as attached:
            with attached.observations() as view:
                self.assertEqual(view.company('A', 'legacy')['annual']['income-statement']['2014-06-30'], json.loads(row[-1]))
        pointer = self.fixture.store._pointer()
        replace(boundary + ' ')
        with self.assertRaisesRegex(ValueError, 'observation record exceeds its byte bound'):
            self.fixture.prepare()
        self.assertEqual(self.fixture.store._pointer(), pointer)
        self.assertEqual(pointer['current'], first['identity'])
        self.assertEqual(list(self.fixture.store.path.glob('building-*')), [])
        self.assertFalse((self.fixture.store.path/'publication.json').exists())


if __name__ == '__main__':
    unittest.main()
