"""Offline actual Original/jobs/queue scalar execution and replay ownership."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from contextlib import contextmanager, closing
from copy import deepcopy
from datetime import date
import io
import json
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from backtest import result_evidence, calendar_requests
from backtest.application import original_calculations, jobs, queue, library as saved, strategy_requests as s, evidence_views
from backtest.inputs import daily, facts, research
from backtest.variables import definitions
from backtest.runtime import backtest_control
from test_scalar_execution import Fixture
import test_strategy_requests as requests


def formula_failure():
    return definitions.FormulaError(errors=[
        dict(code='UNIT_MISMATCH',path='/expression/left',message='Use matching units.'),
        dict(code='FUTURE_DATE',path='/expression/right/date',message='Use an earlier context.')])


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'daily.sqlite'
        fixture=Fixture(12)
        source=Path(self.folder.name)/'research.sqlite'
        with closing(sqlite3.connect(self.path)) as db:fixture.db.backup(db)
        with closing(sqlite3.connect(source)) as db:fixture.db.research.backup(db)
        fixture.close()
        self.capture=fixture.capture()
        self.opened=[];self.financial=False
        owner=self
        class Connection(sqlite3.Connection):
            def close(connection):
                super().close();owner.opened.remove(connection)
        def connect(path,*,attach):
            db=sqlite3.connect(path,factory=Connection,uri=True);db.row_factory=sqlite3.Row;self.opened.append(db)
            # The daily connection attaches research, as daily.connect does.
            if attach:daily.attach(db,source)
            return db
        @contextmanager
        def financial(*args,**kwargs):
            self.financial=True
            try:yield
            finally:self.financial=False
        self.addCleanup(patch.stopall)
        patch.object(daily,'connect',side_effect=lambda *args,**kwargs:connect(self.path,attach=True)).start()
        patch.object(research,'connect',side_effect=lambda *args,**kwargs:connect(source,attach=False)).start()
        patch.object(research,'DATABASE',source).start()
        patch.object(original_calculations.Original,'_financial',side_effect=financial).start()
        self.calc=original_calculations.Original()
    def options(self,**changes):return dict(strategy=self.capture.to_dict(),start='2015-01-02',end='2015-01-05',months=12,**changes)
    def test_coverage_owns_and_closes_both_private_connections(self):
        listing=self.calc.coverage()
        self.assertFalse(self.financial);self.assertFalse(self.opened)
        scope=next(item for item in listing['scopes'] if item['mode']=='latest' and item['pool']=='cached')
        value=self.calc.coverage(self.capture.to_dict(),dict(scope,generation=listing['generation']))
        self.assertEqual(value['population'],12)
        self.assertFalse(self.financial);self.assertFalse(self.opened)
        with self.assertRaises(ValueError):self.calc.coverage(self.capture.to_dict(),dict(scope,generation='0'*64))
        self.assertFalse(self.financial);self.assertFalse(self.opened)
    def test_coverage_mid_evaluation_cancellation_closes_resources(self):
        from backtest.application import variable_coverage
        listing=self.calc.coverage();scope=next(x for x in listing['scopes'] if x['mode']=='latest' and x['pool']=='cached')
        real=variable_coverage.columns.Formulas.evaluate;calls=[]
        def interrupt(formulas,roots,view,checkpoint,**keywords):
            def check():
                calls.append(1)
                if len(calls)==10:raise backtest_control.Cancelled()
                checkpoint()
            return real(formulas,roots,view,check,**keywords)
        with patch.object(variable_coverage.columns.Formulas,'evaluate',interrupt):
            with self.assertRaises(backtest_control.Cancelled):
                self.calc.coverage(self.capture.to_dict(),dict(scope,generation=listing['generation']))
        self.assertEqual(len(calls),10);self.assertFalse(self.opened);self.assertFalse(self.financial)
    def run_result(self,mode='custom',options=None,planned=None):
        stream=io.BytesIO();config=[]
        completion=self.calc.calculate_into(mode,options or self.options(),stream,None,config.append,planned=planned)
        self.assertFalse(self.financial);self.assertFalse(self.opened)
        self.assertEqual(completion['transfer']['bytes'],len(stream.getvalue()))
        return result_evidence.open_reader(stream,max_bytes=256*1024**2),config
    def test_actual_original_fixed_stream_closes_financial_handles_before_completion(self):
        reader,_=self.run_result()
        self.assertEqual(reader.manifest['trials'],1)
        self.assertEqual(len(list(evidence_views.holdings(reader,1,1))),5)
    def test_actual_latest_evidence(self):
        reader,_=self.run_result('latest',dict(strategy=self.capture.to_dict()))
        self.assertEqual(reader.metadata['mode'],'latest')
        self.assertEqual(reader.manifest['trials'],0)
    def test_actual_random_seed_plan_and_recorded_replay_are_identical(self):
        intent=requests.intent(requests.builtin(),rank_from=1,rank_to=5)
        intent.update(pool='cached',bounds=dict(min_yield=0.,max_multiple=3.))
        self.capture=s.capture_strategy(intent)
        options=self.options(trials=2,seed=0)
        reader,configs=self.run_result('random',options)
        self.assertEqual(len(configs),1)
        plan=configs[0];stored=deepcopy(plan)
        repeated,_=self.run_result('random',options,planned=plan)
        self.assertEqual(plan,stored)
        self.assertEqual(reader.manifest['summary']['trials'],[{**row,'seconds':reader.manifest['summary']['trials'][i]['seconds']} for i,row in enumerate(repeated.manifest['summary']['trials'])])
        self.assertEqual(reader.manifest['trials'],2)
        legacy=calendar_requests.plan([date(2015,1,2),date(2015,1,5)],dict(
            start='2015-01-02',end='2015-01-05',months=12,trials=2,seed=0,
            pool='cached',rank_from=1,rank_to=5,max_multiple=3.))
        original=deepcopy(legacy);converted=deepcopy(legacy)
        converted['options']=dict(strategy=self.capture.to_dict())
        with patch.object(calendar_requests,'plan',side_effect=AssertionError('Replay must not resample')):
            replayed,configs=self.run_result('random',options,planned=converted)
        self.assertEqual(legacy,original)
        self.assertEqual({key:value for key,value in configs[0].items() if key!='options'},
                         {key:value for key,value in legacy.items() if key!='options'})
        self.assertEqual(reader.manifest['summary']['trials'],[{**row,'seconds':reader.manifest['summary']['trials'][i]['seconds']} for i,row in enumerate(replayed.manifest['summary']['trials'])])
    def test_presentation_only_capture_edit_replays_old_plan_without_rewriting(self):
        options=self.options(trials=1,seed=0)
        reader,configs=self.run_result('random',options);plan=configs[0];before=deepcopy(plan)
        edited=self.capture.to_dict();edited['variables']['presentation'][0]['name']='New submitted name'
        options['strategy']=edited
        self.assertTrue(s.options_calculation_equal(self.options(trials=1,seed=0),options))
        repeated,_=self.run_result('random',options,planned=plan)
        self.assertEqual(plan,before)
        self.assertEqual(repeated.metadata['options']['strategy'],edited)
        changed=deepcopy(options);changed['strategy']['selection']['ranking']['direction']='lowest'
        with self.assertRaises(ValueError):self.run_result('random',changed,planned=plan)
    def test_jobs_auto_bounded_scalar_and_exact_retry(self):
        manager=jobs.Jobs(self.calc,evidence_root=Path(self.folder.name)/'jobs')
        self.addCleanup(manager.close)
        manager.start('a'*32,'custom',self.options())
        manager.runs['a'*32]['thread'].join(10)
        run=manager.snapshot('a'*32);self.assertEqual(run['state'],'complete',run)
        self.assertEqual(run['evidence']['format_version'],2)
        self.assertIsNone(run['result'])
        with patch.object(s,'builtin_catalog',side_effect=AssertionError('Retry must not re-admit')):
            self.assertEqual(manager.start('a'*32,'custom',self.options())['state'],'complete')
        altered=self.options();altered['strategy']=deepcopy(altered['strategy']);altered['strategy']['selection']['rank_to']=3
        with self.assertRaises(ValueError):manager.start('a'*32,'custom',altered)
        with manager.display_evidence('a'*32,{}) as opened:
            self.assertEqual(opened.metadata['version'],4)
            self.assertEqual(opened.metadata['settings']['strategy'],self.capture.to_dict())
    def test_jobs_latest_uses_same_acquired_boundary(self):
        manager=jobs.Jobs(self.calc,evidence_root=Path(self.folder.name)/'latest-jobs');self.addCleanup(manager.close)
        manager.start('b'*32,'latest',dict(strategy=self.capture.to_dict()))
        manager.runs['b'*32]['thread'].join(10)
        self.assertEqual(manager.snapshot('b'*32)['state'],'complete')
        with manager.display_evidence('b'*32,{}) as opened:self.assertEqual(opened.metadata['kind'],'latest')
    def test_job_failure_retains_ordered_formula_and_provider_diagnostics(self):
        manager=jobs.Jobs(self.calc,evidence_root=Path(self.folder.name)/'failed-jobs');self.addCleanup(manager.close)
        errors=[formula_failure(),definitions.FormulaError('STALE_INPUT_GENERATION','/inputs','Inputs changed.')]
        for index,error in enumerate(errors):
            identifier=str(index)*32
            with patch.object(self.calc,'calculate_into',side_effect=error):
                manager.start(identifier,'custom',self.options())
                manager.runs[identifier]['thread'].join(10)
            run=manager.snapshot(identifier,include_result=False)
            self.assertEqual(run['state'],'failed')
            self.assertEqual(run['error'],str(error))
            self.assertEqual((run['code'],run['path']),(error.code,error.path))
            expected=error.to_dict()['errors'] if isinstance(error,definitions.FormulaError) else [dict(code=error.code,path=error.path,message=str(error))]
            self.assertEqual(run['errors'],expected)
            self.assertEqual(manager.start(identifier,'custom',self.options())['errors'],expected)
        self.assertEqual(manager.evidence.measurements()['reserved_bytes'],0)
    def test_queue_failure_diagnostics_survive_store_reopening(self):
        store=queue.Store(Path(self.folder.name)/'failed-queue.sqlite')
        consumer=queue.Queue(store,calculations=self.calc,library=saved.Store(Path(self.folder.name)/'failed-saved.sqlite'));self.addCleanup(consumer.close)
        request=dict(id='a'*32,name='Scalar',mode='custom',options=self.options(),catalog=dict(metrics={},filters={}),presentation={})
        store.enqueue(request);error=formula_failure()
        with patch.object(self.calc,'calculate_into',side_effect=error):consumer._run(store.claim())
        row=queue.Store(store.path).get(request['id'])
        self.assertEqual(row['state'],'failed')
        self.assertEqual(row['error'],str(error))
        self.assertEqual((row['code'],row['path']),(error.code,error.path))
        self.assertEqual(row['errors'],error.to_dict()['errors'])
        self.assertEqual(row['options'],request['options'])
        self.assertEqual(consumer.evidence.measurements()['reserved_bytes'],0)
    def test_legacy_failures_keep_text_only_job_and_queue_status(self):
        options=dict(start='2015-01-02',end='2015-01-05',months=12)
        manager=jobs.Jobs(self.calc,evidence_root=Path(self.folder.name)/'legacy-failure');self.addCleanup(manager.close)
        with patch.object(self.calc,'calculate',side_effect=ValueError('Original failure.')):
            manager.start('a'*32,'custom',options);manager.runs['a'*32]['thread'].join(10)
        run=manager.snapshot('a'*32)
        self.assertEqual(run['error'],'Original failure.')
        store=queue.Store(Path(self.folder.name)/'legacy-queue.sqlite')
        consumer=queue.Queue(store,calculations=self.calc,library=saved.Store(Path(self.folder.name)/'legacy-saved.sqlite'));self.addCleanup(consumer.close)
        request=dict(id='b'*32,name='Legacy',mode='custom',options=options,catalog=dict(metrics={},filters={}),presentation={})
        store.enqueue(request)
        with patch.object(self.calc,'calculate',side_effect=ValueError('Original failure.')):consumer._run(store.claim())
        row=queue.Store(store.path).get(request['id'])
        self.assertEqual(row['error'],'Original failure.')
        for value in (run,row):
            for key in ('code','path','errors'):self.assertNotIn(key,value)
        with closing(sqlite3.connect(store.path)) as db:
            self.assertEqual(db.execute('SELECT error FROM jobs WHERE id=?',(request['id'],)).fetchone()[0],'Original failure.')
    def test_queue_actual_completion_and_transfer_are_detached(self):
        store=queue.Store(Path(self.folder.name)/'queue.sqlite')
        library=saved.Store(Path(self.folder.name)/'saved.sqlite')
        consumer=queue.Queue(store,calculations=self.calc,library=library);self.addCleanup(consumer.close)
        request=dict(id='c'*32,name='Scalar',mode='custom',options=self.options(),catalog=dict(metrics={},filters={}),presentation={})
        store.enqueue(request);job=store.claim();consumer._run(job)
        row=store.listing()['records'][0];self.assertEqual(row['state'],'complete',row)
        with store.open_evidence('c'*32) as opened:self.assertEqual(opened.metadata['version'],4)
        consumer.reconcile_completed()
        self.assertEqual(len(library.list()),1)
        record=library.list()[0]
        with library.open_evidence(record['id']) as opened:
            with opened.open_reader() as reader:self.assertEqual(reader.metadata['options']['strategy'],self.capture.to_dict())
        self.assertEqual(consumer.evidence.measurements()['reserved_bytes'],0)
    def test_queue_due_stop_poll_during_publication_preserves_completion_stop_and_shutdown(self):
        for scenario,expected in [('complete','complete'),('spill','complete'),('stop','cancelled'),('shutdown','queued')]:
            with self.subTest(scenario=scenario):
                store=queue.Store(Path(self.folder.name)/(scenario+'-publication.sqlite'))
                consumer=queue.Queue(store,calculations=self.calc,library=saved.Store(Path(self.folder.name)/(scenario+'-saved.sqlite')))
                self.addCleanup(consumer.close)
                request=dict(id='a'*32,name='Scalar',mode='custom',options=self.options(),catalog=dict(metrics={},filters={}),presentation={})
                store.enqueue(request);job=store.claim()
                publication=queue.durable_evidence.publication;stopped=store.stopped;finish=store.finish_evidence
                connect=sqlite3.connect;connections=[];failures=[]
                state=dict(publishing=False,polls=0,ordinary_polls=0,ticks=0,checks=0,spilled=False)
                checkpoint=backtest_control.checkpoint
                class Connection(sqlite3.Connection):
                    def close(connection):
                        super().close();connections.remove(connection)
                def short_connection(*args,**kwargs):
                    kwargs['timeout']=.05
                    tracked='factory' not in kwargs
                    if tracked:kwargs['factory']=Connection
                    db=connect(*args,**kwargs)
                    if tracked:connections.append(db)
                    return db
                def tick():
                    if state['publishing']:state['ticks']+=1
                    return 1.+state['ticks']
                def poll(identifier):
                    if state['publishing']:
                        state['polls']+=1
                    else:state['ordinary_polls']+=1
                    return stopped(identifier)
                def check():
                    if state['publishing']:
                        state['checks']+=1
                        if scenario=='shutdown' and state['checks']==2:consumer.stopping.set()
                    return checkpoint()
                @contextmanager
                def publishing(db,*args,**kwargs):
                    self.assertTrue(db.in_transaction)
                    state['publishing']=True
                    try:
                        if scenario in ('spill','shutdown'):
                            # Exceed the default rollback-journal page cache. Its
                            # exclusive lock persists after these rows are deleted.
                            for ordinal in range(16):
                                db.execute('INSERT INTO evidence_chunks VALUES(?,?,?)',('spill-probe',ordinal,b'x'*1024**2))
                            db.execute("DELETE FROM evidence_chunks WHERE record_id='spill-probe'")
                            state['spilled']=True
                        with publication(db,*args,**kwargs) as packed:yield packed
                    finally:state['publishing']=False
                def finishing(identifier,*args,**kwargs):
                    if scenario=='stop':
                        row=store.get(identifier)
                        store.change(identifier,'stop',dict(revision=row['revision']))
                    return finish(identifier,*args,**kwargs)
                with patch.object(queue,'time',wraps=time) as clock, \
                        patch.object(sqlite3,'connect',side_effect=short_connection), \
                        patch.object(store,'stopped',side_effect=poll), \
                        patch.object(store,'finish_evidence',side_effect=finishing), \
                        patch.object(queue.durable_evidence,'publication',side_effect=publishing), \
                        patch.object(backtest_control,'checkpoint',side_effect=check), \
                        patch.object(queue.diagnostics.LOGGER,'error',side_effect=lambda value:failures.append(json.loads(value))):
                    clock.monotonic.side_effect=tick
                    consumer._run(job)
                row=store.listing()['records'][0]
                self.assertEqual(row['state'],expected,dict(state=row['state'],diagnostics=failures))
                self.assertFalse(failures)
                self.assertEqual(state['polls'],0)
                self.assertEqual(state['ordinary_polls'],1)
                if scenario in ('spill','shutdown'):self.assertTrue(state['spilled'])
                if scenario=='shutdown':self.assertEqual(state['checks'],2)
                self.assertEqual(row['options']['strategy'],self.capture.to_dict())
                self.assertFalse(connections);self.assertFalse(self.opened);self.assertFalse(self.financial)
                self.assertEqual(consumer.evidence.measurements()['reserved_bytes'],0)
                with closing(sqlite3.connect(store.path)) as db:
                    chunks=db.execute('SELECT count(*) FROM evidence_chunks').fetchone()[0]
                self.assertEqual(chunks>0,expected=='complete')
        with patch.object(sqlite3,'connect',side_effect=short_connection):
            with self.assertRaises(queue.Missing):store.stopped('b'*32)
        self.assertFalse(connections)
        missing=queue.Store(Path(self.folder.name)/'absent-queue.sqlite')
        with self.assertRaises(queue.Missing):missing.stopped('a'*32)
        self.assertFalse(missing.path.exists())
        with patch.object(sqlite3,'connect',side_effect=sqlite3.OperationalError):
            with self.assertRaises(sqlite3.OperationalError):store.stopped('a'*32)
    def test_queue_held_name_edit_retains_plan_and_changed_direction_drops_it(self):
        store=queue.Store(Path(self.folder.name)/'held.sqlite')
        request=dict(id='d'*32,name='Scalar',mode='random',options=self.options(trials=1,seed=0),catalog=dict(metrics={},filters={}),presentation={})
        store.enqueue(request);claimed=store.claim()
        sessions=[date(2015,1,2),date(2015,1,5)]
        plan=calendar_requests.plan(sessions,request['options'])
        store.progress('d'*32,'configuration',plan);store.finish('d'*32,'queued')
        row=store.get('d'*32);held=store.change('d'*32,'hold',dict(revision=row['revision']))
        edited=deepcopy(request);edited['name']='Renamed';edited['revision']=held['revision']
        edited['options']['strategy']['variables']['presentation'][0]['name']='New label'
        store.change('d'*32,'update',edited)
        claimed=store.claim()
        self.assertEqual(json.loads(claimed['plan']),plan)
        store.finish('d'*32,'queued')
        row=store.get('d'*32);held=store.change('d'*32,'hold',dict(revision=row['revision']))
        edited['revision']=held['revision'];edited['options']['strategy']['selection']['ranking']['direction']='lowest'
        store.change('d'*32,'update',edited)
        self.assertIsNone(store.claim()['plan'])
    def test_queue_recovery_and_explicit_stop_keep_existing_semantics(self):
        store=queue.Store(Path(self.folder.name)/'recover.sqlite')
        request=dict(id='e'*32,name='Scalar',mode='custom',options=self.options(),catalog=dict(metrics={},filters={}),presentation={})
        store.enqueue(request);job=store.claim()
        recovered=queue.Store(store.path);recovered.recover()
        self.assertEqual(recovered.listing()['records'][0]['state'],'queued')
        job=recovered.claim();recovered.change(job['id'],'stop',dict(revision=job['revision']))
        consumer=queue.Queue(recovered,calculations=self.calc,library=saved.Store(Path(self.folder.name)/'saved.sqlite'));self.addCleanup(consumer.close)
        consumer._run(job)
        self.assertEqual(recovered.listing()['records'][0]['state'],'cancelled')
    def test_shutdown_cancellation_requeues_without_losing_captured_request(self):
        store=queue.Store(Path(self.folder.name)/'shutdown.sqlite')
        request=dict(id='f'*32,name='Scalar',mode='custom',options=self.options(),catalog=dict(metrics={},filters={}),presentation={})
        store.enqueue(request);job=store.claim()
        consumer=queue.Queue(store,calculations=self.calc,library=saved.Store(Path(self.folder.name)/'shutdown-saved.sqlite'));self.addCleanup(consumer.close)
        consumer.stopping.set()
        consumer._run(job)
        row=store.listing()['records'][0]
        self.assertEqual(row['state'],'queued')
        self.assertEqual(row['options']['strategy'],self.capture.to_dict())
    def test_final_sealing_cancellation_has_closed_handles_and_no_completion(self):
        stream=io.BytesIO()
        def check():
            if not self.financial:raise backtest_control.Cancelled()
        with patch.object(self.calc,'_checkpoint',side_effect=check):
            with self.assertRaises(backtest_control.Cancelled):self.calc.calculate_into('custom',self.options(),stream,None,None)
        self.assertFalse(self.opened);self.assertFalse(self.financial)
        with self.assertRaises(ValueError):result_evidence.open_reader(stream,max_bytes=256*1024**2)

    def test_preview_future_context_is_rejected_before_financial_ownership(self):
        import test_variable_definitions as language
        local=language.entry(language.definition(dict(op='at',date='2020-01-01',arg=language.constant('1'))),'draft:future')
        capture=s.capture_strategy(requests.intent(requests.formula(local)),submitted=[local])
        with patch.object(self.calc,'_financial',side_effect=AssertionError('No financial access')):
            with self.assertRaises(ValueError) as caught:
                self.calc.preview(capture.to_dict(),[dict(symbol='A0000',pool='cached',mode='historical',date='2015-01-02')])
        self.assertEqual(caught.exception.code,'FUTURE_DATE')
    def test_unknown_options_are_rejected_before_financial_ownership(self):
        with patch.object(self.calc,'_financial',side_effect=AssertionError('No financial access')):
            with self.assertRaises(ValueError):self.calc.calculate_into('custom',self.options(unknown=True),io.BytesIO(),None,None)
            with self.assertRaises(ValueError):self.calc.calculate_into('latest',self.options(),io.BytesIO(),None,None)

    def test_experimental_rejection_precedes_any_financial_access(self):
        with self.assertRaises(ValueError) as caught:
            self.run_result(options=self.options(engine='experimental'))
        self.assertEqual(caught.exception.code,'UNSUPPORTED_CAPABILITY')
        self.assertFalse(self.opened);self.assertFalse(self.financial)
    def test_cancellation_and_exhaustion_close_all_financial_resources(self):
        for kwargs in [dict(max_bytes=100),dict(record_bytes=100)]:
            with self.assertRaises(ValueError):self.calc.calculate_into('custom',self.options(),io.BytesIO(),None,None,**kwargs)
            self.assertFalse(self.opened);self.assertFalse(self.financial)
        with self.assertRaises(backtest_control.Cancelled):
            with backtest_control.cancel_when(lambda:True):self.calc.calculate_into('custom',self.options(),io.BytesIO(),None,None)
        self.assertFalse(self.opened);self.assertFalse(self.financial)


if __name__=='__main__':unittest.main()
