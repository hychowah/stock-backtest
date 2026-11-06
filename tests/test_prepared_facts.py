"""Annual resolution evidence and the typed prepared facts that research publishes."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from contextlib import ExitStack, closing
from datetime import date
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backtest import calendar as schedule_calendar, portfolio_results, screening
from backtest.application import scalar_execution
from backtest.engines.original import book_batch, schedules
from backtest.financial import books, metrics, rules
from backtest.inputs import financial_inputs as financial, facts
from backtest.inputs import book_store, daily, fact_view, research
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

    def latest_decisions(self):
        """View.admit of both latest TEST roots (books.Screen.decide) after a fresh daily build."""
        self.path.unlink(missing_ok=True)
        self.prepare()
        with closing(daily.connect(self.path, self.source)) as db, fact_view.View(db, lambda: None, lambda: None) as view:
            day = view.bounds['latest_date']
            return view.admit([dict(symbol='TEST', pool=pool, mode='latest', date=day) for pool in ('legacy', 'cached')]), \
                db.execute('SELECT COUNT(*) FROM book_rows').fetchone()[0]

    def test_complete_chain_preserves_evidence_dates_and_latest_valuation(self):
        self.prepare()
        with closing(research.connect(self.source)) as original, closing(sqlite3.connect(self.path)) as copied:
            first = research.identity(original)
            self.assertEqual(set(first), {'version', 'latest_date', 'code', 'content'})
            self.assertEqual((first['latest_date'], first['code']), ('2015-10-20', research.code_identity('facts')))
            # The daily binding names the research content identity and the book code.
            self.assertEqual(json.loads(daily.binding(copied)), dict(version=daily.VERSION, research=first['content'],
                                                                     books=research.code_identity('books')))
            # The daily cache binds the facts and attaches them; it holds no copy of them.
            names = {row[0] for row in copied.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertFalse(names & {'stock_days', 'market_days', 'annual_facts', 'fact_sources', 'companies',
                                       'statements', 'financial_inputs', 'fact_metadata'})
            self.assertFalse([name for name in names if name.startswith('observation_')])
            row = original.execute("SELECT operating_income,operating_income_reason,revenue FROM annual_facts "
                                   "WHERE symbol='TEST' AND fiscal='2014-06-30'").fetchone()
            self.assertEqual(tuple(row), (None, 'MISSING_INPUT', 100e6))
            latest = copied.execute("SELECT fiscal,enterprise_value FROM book_rows WHERE pool='legacy' AND symbol='TEST' "
                                    "AND book=(SELECT book FROM books WHERE exit IS NULL)").fetchone()
            self.assertEqual(tuple(latest), ('2014-06-30', 270e6))
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
                decisions, rows = self.latest_decisions()
                self.assertEqual({(decision['admitted'], decision['reason']) for decision in decisions}, {(False, reason)})
                self.assertEqual(rows, 0)

    def test_changed_code_and_missing_record_fail_closed(self):
        self.prepare()
        with closing(sqlite3.connect(self.source)) as db:
            research.identity(db)
            with patch.object(research, 'code_identity', return_value='0' * 64):
                with self.assertRaisesRegex(ValueError, 'changed'): research.identity(db)
            db.execute("DELETE FROM metadata WHERE key='identity'"); db.commit()
            with self.assertRaisesRegex(ValueError, 'changed'): research.identity(db)
        with self.assertRaisesRegex(ValueError, 'changed'): daily.connect(self.path, self.source)

    def dated(self):
        """Save one dated book of each pool; return the stored dated pools."""
        with closing(daily.connect(self.path, self.source)) as db, db:
            book_facts = facts.BookFacts(db)
            for pool in ('legacy', 'cached'):
                schedules.prepare_period(db, date(2015, 1, 2), date(2015, 10, 20), pool, book_facts)
        return self.saved()

    def saved(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT COUNT(*) FROM book_pools JOIN books USING(book) WHERE exit IS NOT NULL').fetchone()[0]

    def copies(self, context, modules):
        """Point each module's source file at a private copy under the fixture root; return the copies."""
        copies = []
        for module in modules:
            path = research.ROOT / ('copy-' + Path(module.__file__).name)
            path.write_bytes(Path(module.__file__).read_bytes())
            context.enter_context(patch.object(module, '__file__', str(path)))
            copies.append(path)
        return copies

    def edit(self, path):
        path.write_bytes(path.read_bytes() + b'\n# Changed private source fixture.\n')

    def published(self):
        return self.source.stat().st_mtime_ns, self.path.stat().st_mtime_ns

    def test_reader_edit_neither_rebuilds_research_nor_drops_books(self):
        readers = (fact_view, daily, schedules, book_batch, screening, scalar_execution, schedule_calendar, portfolio_results)
        with ExitStack() as context:
            copies = self.copies(context, readers)
            self.prepare()
            self.assertEqual(self.dated(), 2)
            before = self.published()
            for path in copies:
                with self.subTest(reader=path.name):
                    self.edit(path)
                    daily.connect(self.path, self.source).close()
                    self.prepare()
                    self.assertEqual(self.published(), before)
                    self.assertEqual(self.saved(), 2)

    def test_book_code_edit_drops_every_book(self):
        modules = (books, metrics, rules, facts, book_store)
        with ExitStack() as context:
            copies = self.copies(context, modules)
            # Every book code file is a private copy here.
            self.assertEqual(research.code_sources('books'), copies)
            self.prepare()
            for module, path in zip(modules, copies):
                with self.subTest(book_code=module.__name__):
                    self.assertEqual(self.dated(), 2)
                    rebuilds = path in research.code_sources('facts')
                    research_stamp = self.source.stat().st_mtime_ns
                    self.edit(path)
                    with self.assertRaisesRegex(ValueError, 'changed'): daily.connect(self.path, self.source)
                    self.prepare()
                    self.assertEqual(self.saved(), 0)
                    # Only fact-row code also rebuilds research.
                    self.assertEqual(self.source.stat().st_mtime_ns != research_stamp, rebuilds)

    def test_equal_bytes_rewrites_keep_both_identities(self):
        with ExitStack() as context:
            copies = self.copies(context, (books, book_store))
            context.enter_context(patch.object(research, 'signature', side_effect=self.real_signature))
            self.prepare()
            self.assertEqual(self.dated(), 2)
            identity = json.loads(daily.binding(sqlite3.connect(self.path)))
            daily_stamp = self.path.stat().st_mtime_ns
            # Equal code bytes with new stamps change nothing.
            for path in copies:
                path.write_bytes(path.read_bytes())
            daily.connect(self.path, self.source).close()
            # Equal raw bytes with a new stamp rebuild research to the same content identity.
            price = research.RAW / 'px/TEST.json'
            price.write_bytes(price.read_bytes()); os.utime(price, ns=(1, 1))
            research_stamp = self.source.stat().st_mtime_ns
            self.prepare()
            self.assertNotEqual(self.source.stat().st_mtime_ns, research_stamp)
            self.assertEqual(json.loads(daily.binding(sqlite3.connect(self.path))), identity)
            self.assertEqual((self.path.stat().st_mtime_ns, self.saved()), (daily_stamp, 2))

    def test_daily_cancellation_after_a_full_drop_leaves_an_empty_valid_cache(self):
        self.prepare()
        def cancelled(): raise RuntimeError('fixture cancellation')
        stale = dict(version=daily.VERSION, research='0' * 64, books='0' * 64)
        with patch.object(daily, 'current', return_value=stale), \
             patch.object(daily.backtest_control, 'checkpoint', side_effect=cancelled):
            with self.assertRaisesRegex(RuntimeError, 'fixture cancellation'):
                daily.prepare(self.path, self.source)
        # The research diff has no base, so no book stays: the empty cache replaced the file
        # before the transaction (an in-place rollback is KeptBookTests' interrupted update).
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual((daily.binding(db), book_store.stored(db)), (None, []))
        self.prepare()
        daily.connect(self.path, self.source).close()



if __name__ == '__main__':
    unittest.main()
