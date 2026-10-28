"""Private synthetic proof of immutable numerical publication and attachment."""
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tools')]
import test_bench_methods as shared
import numerical_generation as ng
from bench_candidates import NumericInputs, PythonExecutor
import numpy as np


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = shared.SharedMethodsTests('test_empty_trials_remain_visible_and_excluded_from_distributions')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.s, self.db = shared.s, self.fixture.db
        self.root = self.fixture.root
        self.report = self.root / 'summary-exits.txt'
        self.report.write_text('Through 2016-12-30\nSynthetic unchanged report\n')
        self.binding = dict(temporal_version=ng.TEMPORAL_VERSION, factor_version=ng.FACTOR_VERSION,
                            field_schema=ng.PolicyProgram(self.s).field_schema, daily={}, prices={}, report=ng._sha(self.report),
                            policy=ng.PolicyProgram(self.s).signature, sources={})
        self.owner = ng.cache_access.WorkspaceAccess(self.root / 'cache.lock')
        self.store = ng.GenerationStore(self.s, self.root / 'numerical', self.owner)
        self.binding_patch = self.enterContext(patch.object(self.store, '_binding', side_effect=lambda: (self.binding.copy(), ng.PolicyProgram(self.s))))
        def connect():
            db = ng.sqlite3.connect(self.fixture.path.as_uri() + '?mode=ro', uri=True)
            db.row_factory = ng.sqlite3.Row
            return db
        self.enterContext(patch.object(self.s, 'connect', side_effect=connect))

    def prepare(self): return self.store.prepare()
    def attach(self):
        value = self.store.open_current()
        self.addCleanup(value.close)
        return value

    def advance(self):
        self.db.execute("UPDATE prices SET price=price+1,adjusted=adjusted+1 WHERE symbol='A'")
        self.db.commit()
        self.binding['prices'] = dict(revision=self.binding.get('prices', {}).get('revision', 0) + 1)
        return self.prepare()

    def test_export_values_order_missingness_and_mutable_books_reuse(self):
        before = self.fixture.base_inputs()
        first = self.prepare()
        attached = self.attach()
        old = NumericInputs(self.fixture.reader, self.s)
        self.addCleanup(old.close)
        for name in ng.ARRAYS:
            if name == 'symbol_sort':
                self.assertEqual([attached.symbols[i] for i in attached.symbol_sort], sorted(old.symbols))
            elif name.startswith(('cached_', 'legacy_')) and name != 'cached_mask':
                pool, field = name.split('_', 1)
                np.testing.assert_array_equal(getattr(attached, 'pool_' + field)[pool], getattr(old, 'pool_' + field)[pool])
            else:
                np.testing.assert_array_equal(getattr(attached, name), getattr(old, name))
        self.assertEqual(attached.symbols, old.symbols)
        self.assertEqual(attached.companies, old.companies)
        self.assertEqual(attached.sessions, old.sessions)
        self.assertEqual(attached.treasury_days, old.treasury_days)
        self.assertEqual(attached.treasury_values, old.treasury_values)
        self.assertEqual(list(attached.report_rows), list(old.report_rows))
        self.assertEqual(dict(attached.histories), old.histories)
        self.assertEqual(dict(attached.financials), old.financials)
        self.assertFalse(attached.raw_values.flags.writeable)
        with self.assertRaises(ng.sqlite3.OperationalError): attached._db.execute('DELETE FROM reports')
        self.assertEqual(before, self.fixture.base_inputs())
        report_sha = ng._sha(self.report)
        for pool in ('legacy', 'cached'):
            books = [('2015-01-02', '2016-01-04', pool)]
            result = self.s.compute_period(self.db, date(2015,1,2), date(2016,1,4),
                                           self.s.histories(self.db), self.s.cached_symbols(self.db), pool)
            self.s.store_period(self.db, result)
        self.assertTrue(self.prepare()['reused'])
        self.assertEqual(self.store._pointer()['current'], first['identity'])
        self.assertEqual(ng._sha(self.report), report_sha)

    def test_preparation_source_books_and_factors_do_not_translate_compiled_guards(self):
        from numerical_numba import NumbaExecutor
        from numerical_factors import FactorEvaluator
        with patch('numerical_decisions.CandidateDecisionProgram',
                   side_effect=AssertionError('Optional guard translator invoked')) as translator:
            self.prepare()
            inputs = self.attach()
            inputs.validate()
            fields = dict(filters=[dict(field=field,op='gt',value=-999999.)
                                   for field in self.s.metrics.FILTERS])
            with closing(NumbaExecutor(inputs, limits=dict(threads=2))) as executor:
                for pool in ('legacy', 'cached'):
                    book = ('2015-01-02', '2016-01-04', pool)
                    actual = executor.evaluate([book],fields)[0]
                    expected = self.s.compute_period(self.db, date(2015,1,2), date(2016,1,4),
                        self.s.histories(self.db), self.s.cached_symbols(self.db), pool)
                    self.assertTrue(shared.baseline.compare(expected, actual)['exact'])
                self.assertNotIn('candidate_decisions', executor.compiler['fields'])
            with closing(FactorEvaluator(inputs)) as factors:
                self.assertTrue(factors.evaluate([date(2015,1,2).toordinal()]))
            self.assertNotIn('decisions', vars(inputs.policy))
            translator.assert_not_called()

    def test_python_and_numba_books_all_filters_pools_sql_and_aggregation(self):
        from bench_candidates_numba import NumbaExecutor
        self.prepare()
        inputs = self.attach()
        fields = [dict(field=field,op='gt',value=-999999) for field in self.s.metrics.FILTERS]
        maximum_absolute=maximum_relative=0.
        for factory in (PythonExecutor, NumbaExecutor):
            executor = factory(inputs, limits=dict(threads=2, request_plan=True))
            try:
                for pool in ('legacy', 'cached'):
                    batch = [('2015-01-02','2016-01-04',pool), ('2016-02-29','2016-12-30',pool)]
                    for filters in ([], fields, [dict(field='pe',op='lt',value=20), dict(field='return_3y',op='gt',value=0)]):
                        options = dict(shared.baseline.options(pool,'F0'), filters=filters, min_cap=0., min_ev=0.)
                        executor.begin(dict(options=options))
                        actual = executor.evaluate(batch)
                        for book, value in zip(batch, actual):
                            a,b,pool = book
                            expected = self.s.compute_period(self.db,date.fromisoformat(a),date.fromisoformat(b),
                                self.s.histories(self.db),self.s.cached_symbols(self.db),pool)
                            # Source computes every filter; evaluator projects only requested fields.
                            needed = {f['field'] for f in filters}
                            expected['filters'] = [r for r in expected['filters'] if r[1] in needed]
                            agreement=shared.baseline.compare(expected,value)
                            self.assertTrue(agreement['exact'])
                            maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
                            maximum_relative=max(maximum_relative,agreement['maximum_relative'])
                            # Separate result stores ensure the source reference
                            # cannot accidentally fill a missing candidate book.
                            with closing(ng.sqlite3.connect(':memory:')) as left, closing(ng.sqlite3.connect(':memory:')) as right:
                                for db, book_value in ((left, expected), (right, value)):
                                    db.row_factory = ng.sqlite3.Row
                                    db.executescript(self.s.SCHEMA)
                                    db.executemany('INSERT INTO companies VALUES(?,?,?,?)',inputs.companies)
                                    self.s.store_period(db,book_value)
                                for metric in self.s.metrics.METRICS:
                                    options['metric'] = metric
                                    for extra in ({}, dict(rank_from=100,rank_to=110)):
                                        settings = dict(options,**extra)
                                        left_result = self.s.backtest_periods(left, [(date.fromisoformat(a),date.fromisoformat(b))],months=12,**settings)
                                        right_result = self.s.backtest_periods(right, [(date.fromisoformat(a),date.fromisoformat(b))],months=12,**settings)
                                        left_result.pop('seconds'); right_result.pop('seconds')
                                        agreement=shared.baseline.compare(left_result,right_result)
                                        self.assertTrue(agreement['exact'])
                                        maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
                                        maximum_relative=max(maximum_relative,agreement['maximum_relative'])
            finally: executor.close()
        print(json.dumps(dict(check='numerical-books-and-selection',maximum_absolute=maximum_absolute,
            maximum_relative=maximum_relative,tolerance=1e-12)),flush=True)

    def test_live_reader_survives_publication_retirement_and_move(self):
        first = self.prepare()['identity']
        old = self.attach()
        old.validate()
        sample = old.raw_values.copy()
        self.advance(); self.advance()
        with self.assertRaisesRegex(ValueError,'stale'): old.validate()
        self.assertIn(first,self.store.retire_unused()['retained'])
        np.testing.assert_array_equal(old.raw_values,sample)
        old.close()
        with self.assertRaisesRegex(ValueError,'closed'): old.validate()
        self.assertIn(first,self.store.retire_unused()['removed'])
        current = self.store._pointer()['current']
        relocated = self.root / 'moved'
        shutil.move(self.store.path, relocated)
        self.store.path = relocated
        self.assertEqual(self.attach().signature,current)

    def test_corrupt_buffer_truncation_and_manifest_are_rejected(self):
        identity = self.prepare()['identity']
        target = self.store.path / identity / 'raw_values.npy'
        saved = target.read_bytes()
        for content in (saved[:-1], saved[:-1] + bytes([saved[-1] ^ 1])):
            target.write_bytes(content)
            with self.assertRaisesRegex(ValueError,'Corrupt numerical buffer'): self.attach()
        target.write_bytes(saved)
        manifest = self.store.path / identity / 'manifest.json'
        value = json.loads(manifest.read_bytes()); value['format'] = 999
        manifest.write_bytes(ng._json(value))
        with self.assertRaisesRegex(ValueError,'manifest'): self.attach()

    def test_stale_policy_and_publication_binding_reject_before_attach(self):
        self.prepare()
        self.binding['report'] = 'changed'
        with self.assertRaisesRegex(ValueError,'stale'): self.attach()
        self.binding['report'] = ng._sha(self.report)
        original = self.store._pointer()
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            self.store.prepare(lambda: (_ for _ in ()).throw(RuntimeError('cancelled')))
        self.assertEqual(self.store._pointer(),original)

    def test_interrupted_pointer_publication_recovers_and_preserves_prior(self):
        first = self.prepare()['identity']
        original = ng.cache_assets.write_json
        def write(path,value):
            if path.name == 'current.json': raise PermissionError('synthetic failure')
            return original(path,value)
        with patch.object(ng.cache_assets,'write_json',side_effect=write):
            with self.assertRaises(PermissionError): self.advance()
        self.assertEqual(self.store._pointer()['current'],first)
        self.assertTrue((self.store.path/'publication.json').exists())
        new = self.attach()
        self.assertNotEqual(new.signature,first)
        self.assertEqual(self.store._pointer()['previous'],first)
        self.assertFalse((self.store.path/'publication.json').exists())

    def test_invalid_pending_candidate_recovers_prior_without_stale_fallback(self):
        first = self.prepare()['identity']
        ng.cache_assets.write_json(self.store.path/'publication.json',dict(candidate='a'*64, prior=self.store._pointer()))
        self.assertEqual(self.attach().signature,first)
        self.binding['policy'] = 'changed'
        with self.assertRaisesRegex(ValueError,'stale'): self.attach()

    def test_transient_windows_publication_retries_are_bounded(self):
        path = self.root/'atomic.json'
        original = Path.replace
        calls=[]
        def replace(source,target):
            if source.name == 'atomic.json.download':
                calls.append(1)
                if len(calls) < 3:
                    error=PermissionError(); error.winerror=32; raise error
            return original(source,target)
        with patch.object(Path,'replace',replace), patch.object(ng.cache_assets.time,'sleep') as sleep:
            ng.cache_assets.write_json(path,dict(ok=True))
        self.assertEqual(len(calls),3)
        self.assertEqual(sleep.call_count,2)

    def test_readiness_checks_full_price_inventory_report_and_pending_journals(self):
        self.db.execute('INSERT INTO metadata VALUES(?,?)',('daily_inputs','{}')); self.db.commit()
        with patch.object(self.s.r,'ROOT',self.root), patch.object(self.s.r,'RESULTS',self.root), \
             patch.object(self.s.r,'connect',return_value=self.fixture.reader) as ready, \
             patch.object(self.s.r,'price_sources',return_value={'A.json':[12,34]}):
            # Use a fresh reader because readiness owns and closes its handle.
            ready.side_effect=lambda **kwargs: ng.sqlite3.connect(self.fixture.path)
            actual,_ = ng.GenerationStore._binding(self.store)
            ready.assert_called_once_with(full_prices=True)
            self.assertEqual(actual['prices'],{'A.json':[12,34]})
            self.assertEqual(actual['report'],ng._sha(self.report))
            (self.root/'data').mkdir(exist_ok=True)
            for name in ('deployment.pending.json','research.sqlite.publication.json'):
                marker=self.root/'data'/name; marker.write_text('{}')
                with self.assertRaisesRegex(ValueError,'Unfinished publication'):
                    ng.GenerationStore._binding(self.store)
                marker.unlink()

    def test_interleaved_report_order_and_ties_preserve_buffer_order(self):
        self.db.execute('DELETE FROM statements')
        for fiscal in ('2013-06-30','2012-06-30','2014-06-30'):
            for symbol in ('STOP','C','B','A','SMALL'):
                self.db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',
                    (symbol,fiscal,str(date.fromisoformat(fiscal)+shared.timedelta(days=90)),150e6,180e6,60e6,1/3))
        self.db.commit()
        self.prepare(); attached=self.attach()
        old=NumericInputs(self.fixture.reader,self.s); self.addCleanup(old.close)
        self.assertEqual(attached.symbols,('STOP','C','B','A','SMALL'))
        self.assertEqual(list(attached.report_rows),list(old.report_rows))
        executor=PythonExecutor(attached)
        expected=PythonExecutor(old)
        try:
            self.assertTrue(shared.baseline.compare(
                executor.evaluate([('2015-01-02','2016-01-04','legacy')]),
                expected.evaluate([('2015-01-02','2016-01-04','legacy')]))['exact'])
        finally: executor.close(); expected.close()

    def test_export_cursor_batches_and_per_symbol_history_limit(self):
        class Cursor:
            def __init__(self,cursor): self.cursor=cursor
            def __iter__(self): return iter(self.cursor)
            def fetchone(self): return self.cursor.fetchone()
            def fetchmany(self,size):
                self_test.assertLessEqual(size,ng.CHUNK)
                return self.cursor.fetchmany(size)
            def close(self): return self.cursor.close()
            def fetchall(self): raise AssertionError('Unbounded fetchall')
        class Source:
            def execute(self,*args): return Cursor(self_db.execute(*args))
        self_test,self_db=self,self.db
        folder=self.root/'bounded'; folder.mkdir()
        ng._export(Source(),self.s,ng.PolicyProgram(self.s),folder,lambda:None)
        shutil.rmtree(folder); folder.mkdir()
        with patch.object(ng,'MAX_HISTORY',2):
            with self.assertRaisesRegex(ValueError,'per-symbol bound'):
                ng._export(Source(),self.s,ng.PolicyProgram(self.s),folder,lambda:None)

    def test_owned_abandoned_staging_and_first_publication_recovery(self):
        self.store.path.mkdir()
        abandoned=self.store.path/('building-'+'a'*32); abandoned.mkdir()
        ng.cache_assets.write_json(abandoned/'owner.json',dict(format=ng.FORMAT,owner='numerical-generation'))
        unrelated=self.store.path/'building-user'; unrelated.mkdir()
        ng.cache_assets.write_json(self.store.path/'publication.json',dict(candidate='b'*64,prior=None))
        self.prepare()
        self.assertFalse(abandoned.exists()); self.assertTrue(unrelated.is_dir())
        self.assertFalse((self.store.path/'publication.json').exists())

    def test_explicit_previous_recovery_rejects_stale_attachment(self):
        first=self.prepare()['identity']; self.advance()
        self.assertEqual(self.store.recover_previous()['current'],first)
        with self.assertRaisesRegex(ValueError,'stale'): self.attach()
        self.prepare(); self.attach()

    def test_close_failure_retains_lease_and_owner_for_retry(self):
        first=self.prepare()['identity']; inputs=self.attach()
        self.advance(); self.advance()
        original=inputs._db
        class FailedClose:
            def close(self): raise OSError('synthetic close failure')
        inputs._db=FailedClose()
        with self.assertRaises(OSError): inputs.close()
        self.assertIs(ng._attachments[id(inputs)],inputs)
        self.assertIn(first,self.store.retire_unused()['retained'])
        inputs._db=original; inputs.close()
        self.assertNotIn(id(inputs),ng._attachments)
        self.assertIn(first,self.store.retire_unused()['removed'])

    def test_crashed_cross_process_reader_lease_is_reclaimed(self):
        first=self.prepare()['identity']; self.advance(); self.advance()
        folder=self.store.path/'leases'/first; folder.mkdir(parents=True)
        lease=folder/'child.lease'; ready=self.root/'reader-ready'
        script='''import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import cache_access
handle=Path(sys.argv[2]).open('x+b',buffering=0); handle.write(b'0')
cache_access._file_lock(handle,True)
Path(sys.argv[3]).write_text('ready')
time.sleep(30)
'''
        process=subprocess.Popen([sys.executable,'-I','-B','-c',script,str(ROOT/'scripts'),str(lease),str(ready)])
        try:
            deadline=ng.time.monotonic()+10
            while not ready.exists():
                if process.poll() is not None or ng.time.monotonic()>deadline: self.fail('Reader did not start')
                ng.time.sleep(.02)
            self.assertIn(first,self.store.retire_unused()['retained'])
        finally:
            process.kill(); process.wait(timeout=10)
        self.assertIn(first,self.store.retire_unused()['removed'])

    def test_interruption_after_directory_and_after_pointer_replacement(self):
        first=self.prepare()['identity']
        original=ng._replace
        def replace(source,target,checkpoint=lambda:None):
            original(source,target,checkpoint)
            if source.name.startswith('building-'): raise RuntimeError('after directory rename')
        with patch.object(ng,'_replace',side_effect=replace):
            with self.assertRaisesRegex(RuntimeError,'after directory'): self.advance()
        self.assertEqual(self.store._pointer()['current'],first)
        second=self.prepare()['identity']
        self.assertNotEqual(second,first)
        unlink=Path.unlink
        def fail_unlink(path,*args,**kwargs):
            if path.name=='publication.json': raise PermissionError('after pointer replacement')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail_unlink):
            with self.assertRaises(PermissionError): self.advance()
        third=self.store._pointer()['current']
        self.assertNotEqual(third,second)
        self.assertEqual(self.attach().signature,third)
        self.assertFalse((self.store.path/'publication.json').exists())

    def test_damaged_current_rebuild_preserves_original_and_pointer_validation(self):
        identity=self.prepare()['identity']
        target=self.store.path/identity/'raw_values.npy'
        target.write_bytes(target.read_bytes()[:-1])
        self.assertEqual(self.prepare()['identity'],identity)
        self.attach()
        self.assertEqual(len(list(self.store.path.glob('damaged-*'))),1)
        ng.cache_assets.write_json(self.store.path/'current.json',dict(current='../escape',previous=None))
        with self.assertRaisesRegex(ValueError,'pointer'): self.attach()

    def test_rehashed_inconsistent_report_and_shape_fail_structural_checks(self):
        identity=self.prepare()['identity']
        folder=self.store.path/identity
        def reseal():
            value=json.loads((folder/'manifest.json').read_bytes())
            for name in value['files']:
                path=folder/name
                value['files'][name]=dict(bytes=path.stat().st_size,sha256=ng._sha(path))
            core={k:value[k] for k in ('format','binding','arrays','files')}
            value['identity']=ng.hashlib.sha256(ng._json(core)).hexdigest()
            (folder/'manifest.json').write_bytes(ng._json(value))
            return value['identity']
        array=np.load(folder/'report_symbol.npy',mmap_mode='r+')
        array[0]=999; array.flush(); array._mmap.close()
        changed=reseal()
        with self.assertRaisesRegex(ValueError,'record and buffer'):
            self.store._verify(changed,folder=folder)

    def test_empty_prepared_pools_keep_empty_arrays_and_zero_offsets(self):
        self.db.execute('DELETE FROM statements'); self.db.execute('DELETE FROM prices'); self.db.commit()
        self.prepare(); inputs=self.attach()
        self.assertEqual(inputs.symbols,())
        self.assertEqual(len(inputs.report_rows),0)
        self.assertEqual(inputs.raw_values.shape,(0,))
        for offsets in (inputs.raw_offsets,*inputs.pool_offsets.values()):
            np.testing.assert_array_equal(offsets,np.array([0]))

    def test_value_error_cancellation_is_not_reclassified_as_corruption(self):
        self.prepare(); before=self.store._pointer()
        error=ValueError('caller cancellation')
        def cancel(): raise error
        with self.assertRaises(ValueError) as caught: self.store.prepare(cancel)
        self.assertIs(caught.exception,error)
        self.assertEqual(before,self.store._pointer())

    def test_unmanifested_files_prevent_retirement(self):
        first=self.prepare()['identity']; self.advance(); self.advance()
        unrelated=self.store.path/first/'user-file.txt'; unrelated.write_text('preserve')
        with self.assertRaisesRegex(ValueError,'Unmanifested'): self.store.retire_unused()
        self.assertEqual(unrelated.read_text(),'preserve')

    def test_malformed_manifest_current_rebuild_and_pending_fallback(self):
        identity=self.prepare()['identity']; path=self.store.path/identity/'manifest.json'
        valid=json.loads(path.read_bytes())
        malformed=({}, [], dict(valid,arrays=[]),dict(valid,files=[]))
        for value in malformed:
            with self.subTest(manifest=value if isinstance(value,list) else list(value)):
                path.write_bytes(ng._json(value))
                self.assertEqual(self.prepare()['identity'],identity)
                self.attach().close()
        original=ng.cache_assets.write_json
        def write(path,value):
            if path.name=='current.json': raise PermissionError('synthetic pointer failure')
            return original(path,value)
        with patch.object(ng.cache_assets,'write_json',side_effect=write):
            with self.assertRaises(PermissionError): self.advance()
        journal=ng._read(self.store.path/'publication.json')
        candidate=journal['candidate']
        (self.store.path/candidate/'manifest.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'stale'): self.attach()
        self.assertEqual(self.store._pointer()['current'],identity)
        self.assertFalse((self.store.path/'publication.json').exists())
        self.assertEqual(self.prepare()['identity'],candidate)
        self.attach()


if __name__ == '__main__': unittest.main()
