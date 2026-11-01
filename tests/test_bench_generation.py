"""Disposable freshness, publication and reattachment checks for the pilot."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import FunctionType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import test_bench_methods as shared
import bench_generation as generation


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        for name in ('raw/px', 'raw/financial-inputs/income-statement',
                     'scripts', 'results', 'data'):
            (self.root / name).mkdir(parents=True)
        for name in ('universe.json', 'metrics.jsonl', 'spy-div.json', 'treasury.json'):
            (self.root / 'raw' / name).write_text('[]')
        modules = {}
        for name in ('baseline', 'research', 'metrics', 'books', 'cache_assets',
                     'run', 'revalue', 'financial_inputs', 'schedules', 'book_batch', 'schedule_calendar', 'portfolio_results', 'rules', 'screening'):
            relative = {'metrics':'backtest/financial/metrics.py','books':'backtest/financial/books.py','rules':'backtest/financial/rules.py','screening':'backtest/screening.py','schedule_calendar':'backtest/calendar.py','portfolio_results':'backtest/portfolio_results.py'}.get(name,'scripts/'+name+'.py')
            path = self.root / relative
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('# fixture ' + name)
            modules[name] = SimpleNamespace(__file__=str(path))
        self.report = self.root / 'results/summary-exits.txt'
        self.report.write_text('Through 2026-10-21\nOriginal evidence\n')
        self.asset = self.root / 'raw/financial-inputs/income-statement/A.json'
        self.asset.write_text('[]')
        self.r = SimpleNamespace(**{name: modules[name] for name in
            ('baseline', 'metrics', 'books', 'cache_assets', 'run', 'revalue', 'financial_inputs', 'rules', 'screening')},
            ROOT=self.root, RAW=self.root / 'raw', RESULTS=self.root / 'results',
            DATABASE=self.root / 'data/research.sqlite',
            SCHEMA_VERSION=shared.s.r.SCHEMA_VERSION, __file__=modules['research'].__file__)
        self.r.baseline.cutoff = shared.s.r.baseline.cutoff
        namespace = dict(shared.s.r.signature.__globals__, **vars(self.r))
        self.r.signature = FunctionType(shared.s.r.signature.__code__, namespace)
        self.s = SimpleNamespace(r=self.r, VERSION=shared.s.VERSION,
            DATABASE=self.root / 'data/schedules.sqlite', __file__=modules['schedules'].__file__, schedule_calendar=modules['schedule_calendar'], portfolio_results=modules['portfolio_results'])
        self.sources = [Path(self.r.metrics.__file__)]
        self.prepare()

    def write_metadata(self, path, values):
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            with db:
                db.execute('DELETE FROM metadata')
                db.executemany('INSERT INTO metadata VALUES(?,?)',
                               ((key, json.dumps(value)) for key, value in values.items()))

    def prepare(self):
        signature = self.r.signature()
        prices={path.name:[path.stat().st_size,path.stat().st_mtime_ns]
                for path in (self.root/'raw/px').glob('*.json')}
        engine = {path.relative_to(self.root).as_posix(): [path.stat().st_size, path.stat().st_mtime_ns] for path in
            (Path(self.s.__file__), Path(self.s.__file__).with_name('book_batch.py'),
             Path(self.s.schedule_calendar.__file__),
             Path(self.s.portfolio_results.__file__))}
        self.write_metadata(self.s.DATABASE, dict(daily_inputs=dict(version=self.s.VERSION,
                            inputs=signature,prices=generation.digest(prices), engine=engine)))
        self.write_metadata(self.r.DATABASE, dict(version=self.r.SCHEMA_VERSION,
            inputs=signature,prices=prices, baseline_report_sha=generation.file_hash(self.report)))
        self.inputs = SimpleNamespace(signature=generation.digest(signature),
            generation=json.dumps(generation.metadata(self.s.DATABASE)['daily_inputs']),
            policy=SimpleNamespace(signature='policy-fixture', source_paths=tuple(self.sources),
                source_hashes={path.as_posix(): generation.file_hash(path) for path in self.sources}))

    def attach(self):
        return generation.PreparedGeneration(self.inputs, self.s, sources=self.sources)

    def test_inventory_exact_with_matching_directories_hidden_files_and_missing_root(self):
        (self.asset.parent / 'directory.json').mkdir()
        (self.asset.parent / '.hidden.json').write_text('{}')
        (self.asset.parent / 'ignored.json.pending').write_text('{}')
        (self.asset.parent / 'upper.JSON').write_text('{}')
        (self.root / 'raw/financial-inputs/not-an-endpoint').write_text('{}')
        self.assertEqual(generation.signature(self.r), self.r.signature())
        self.prepare()
        self.assertEqual(self.attach().validate(), self.attach().identity)
        self.asset.unlink()
        for path in self.asset.parent.iterdir():
            if path.is_dir(): path.rmdir()
            else: path.unlink()
        self.asset.parent.rmdir()
        (self.root / 'raw/financial-inputs/not-an-endpoint').unlink()
        (self.root / 'raw/financial-inputs').rmdir()
        self.assertEqual(generation.signature(self.r), self.r.signature())

    def test_edits_additions_removals_replacements_reject_before_reprepare(self):
        for operation in ('edit', 'add', 'remove', 'replace'):
            with self.subTest(operation=operation):
                old = self.attach()
                added = self.asset.with_name('B.json')
                if operation == 'edit': self.asset.write_text('[1,2,3]')
                elif operation == 'add': added.write_text('[]')
                elif operation == 'remove': self.asset.unlink()
                else:
                    pending = self.asset.with_suffix('.pending')
                    pending.write_text('[4,5]')
                    os.replace(pending, self.asset)
                self.assertEqual(generation.signature(self.r), self.r.signature())
                for _ in range(2):
                    with self.assertRaises(ValueError): old.validate()
                self.prepare()
                self.attach().validate()
                if added.exists(): added.unlink()
                self.asset.write_text('[]')
                self.prepare()

    def test_calendar_dependency_changes_require_daily_preparation(self):
        old=self.attach()
        path=self.root/'backtest/calendar.py'
        path.write_text('# changed private calendar fixture')
        with self.assertRaises(ValueError): old.validate()
        with self.assertRaises(ValueError): self.attach()
        self.prepare()
        self.attach().validate()

    def test_portfolio_dependency_changes_require_daily_preparation(self):
        old=self.attach()
        path=self.root/'backtest/portfolio_results.py'
        path.write_text('# changed private portfolio fixture')
        with self.assertRaises(ValueError): old.validate()
        with self.assertRaises(ValueError): self.attach()
        self.prepare()
        self.attach().validate()

    def test_symlink_files_and_endpoint_directories_follow_current_policy(self):
        target = self.root / 'target.json'; target.write_text('{}')
        try:
            self.asset.with_name('link.json').symlink_to(target)
            (self.asset.parent.parent / 'linked-endpoint').symlink_to(self.asset.parent, target_is_directory=True)
        except OSError as error:
            self.skipTest('Symlink creation unavailable: ' + type(error).__name__)
        self.assertEqual(generation.signature(self.r), self.r.signature())
        self.prepare(); self.attach().validate()

    def test_unfinished_publications_reject_then_recover_without_stale_acceptance(self):
        current = self.attach()
        for name in ('deployment.pending.json', 'research.sqlite.publication.json'):
            journal = self.root / 'data' / name
            journal.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Unfinished publication'): current.validate()
            with self.assertRaisesRegex(ValueError, 'Unfinished publication'): self.attach()
            journal.unlink()
            current.validate()

    def test_report_same_cutoff_content_change_requires_new_binding(self):
        old = self.attach()
        self.report.write_text('Through 2026-10-21\nRevised evidence\n')
        self.assertEqual(generation.signature(self.r), old.inventory)
        with self.assertRaisesRegex(ValueError, 'Report content'): old.validate()
        self.prepare()
        with self.assertRaises(ValueError): old.validate()
        current = self.attach(); current.validate()
        self.assertNotEqual(old.identity, current.identity)

    def test_source_and_policy_changes_invalidate_the_attachment(self):
        old = self.attach()
        source = self.sources[0]; info = source.stat()
        content = source.read_bytes()
        source.write_bytes(b'X' * len(content))
        os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.assertEqual(generation.signature(self.r), old.inventory)
        with self.assertRaisesRegex(ValueError, 'source dependencies'): old.validate()
        source.write_bytes(content); os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
        old.validate()
        self.inputs.policy.signature = 'new-policy'
        with self.assertRaisesRegex(ValueError, 'policy identity'): old.validate()
        self.attach().validate()
        self.inputs.signature = 'new-numeric'
        with self.assertRaisesRegex(ValueError, 'numerical or policy'): old.validate()

    def test_fresh_path_metadata_detects_replacement_and_closes_handles(self):
        old = self.attach()
        replacement = self.root / 'data/replacement.sqlite'
        metadata = generation.metadata(self.r.DATABASE)
        metadata['fixture_generation'] = 'replacement'
        self.write_metadata(replacement, metadata)
        os.replace(replacement, self.r.DATABASE)
        with self.assertRaisesRegex(ValueError, 'stale'): old.validate()
        self.attach().validate()
        replacement.write_bytes(b'truncated SQLite')
        os.replace(replacement, self.r.DATABASE)
        with self.assertRaises(sqlite3.DatabaseError): old.validate()
        self.r.DATABASE.unlink()
        self.prepare(); self.attach().validate()

    def test_partial_asset_write_keeps_previous_generation_until_publication(self):
        old = self.attach()
        pending = self.asset.with_suffix('.json.pending')
        pending.write_text('[new interrupted asset')
        old.validate()
        pending.write_text('[8,9]')
        os.replace(pending, self.asset)
        with self.assertRaises(ValueError): old.validate()
        self.prepare(); self.attach().validate()

    def test_changed_daily_metadata_rejects_and_valid_reprepare_recovers(self):
        old = self.attach()
        metadata = generation.metadata(self.s.DATABASE)
        metadata['daily_inputs']['version'] += 1
        self.write_metadata(self.s.DATABASE, metadata)
        with self.assertRaisesRegex(ValueError, 'different prepared generation'): old.validate()
        self.prepare(); old.validate()

    def test_current_daily_price_binding_rejects_missing_or_mismatched_evidence(self):
        self.attach().validate()
        for changed in (None,'changed'):
            daily=generation.metadata(self.s.DATABASE)
            if changed is None:daily['daily_inputs'].pop('prices')
            else:daily['daily_inputs']['prices']=changed
            self.write_metadata(self.s.DATABASE,daily)
            self.inputs.generation=json.dumps(daily['daily_inputs'])
            with self.assertRaisesRegex(ValueError,'Daily prepared generation'):self.attach()
            self.prepare()
        research=generation.metadata(self.r.DATABASE);research['prices']={'A.json':[1,2]}
        self.write_metadata(self.r.DATABASE,research)
        with self.assertRaisesRegex(ValueError,'Daily prepared generation'):self.attach()
        self.prepare()
        research=generation.metadata(self.r.DATABASE);research.pop('prices')
        self.write_metadata(self.r.DATABASE,research)
        with self.assertRaisesRegex(ValueError,'price inventory'):self.attach()

    def test_old_numeric_inputs_cannot_attach_after_valid_reprepare(self):
        old_inputs = self.inputs
        self.asset.write_text('[new valid raw generation]')
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'different prepared generation'):
            generation.PreparedGeneration(old_inputs, self.s, sources=self.sources)
        self.attach().validate()

    def test_old_policy_cannot_attach_after_dependency_change(self):
        old_inputs = self.inputs
        self.sources[0].write_text('# changed source dependency')
        self.prepare()
        # Even with refreshed metadata, the original expression provenance is
        # incompatible with the changed source. New expressions must be built.
        old_inputs.generation = self.inputs.generation
        with self.assertRaisesRegex(ValueError, 'policy source dependencies'):
            generation.PreparedGeneration(old_inputs, self.s, sources=self.sources)
        self.attach().validate()

    def test_scanner_disagreement_never_enables_optimized_validation(self):
        with patch.object(self.r, 'signature', return_value={'unexpected': True}):
            with self.assertRaisesRegex(ValueError, 'authoritative scan'): self.attach()


if __name__ == '__main__':
    unittest.main()
