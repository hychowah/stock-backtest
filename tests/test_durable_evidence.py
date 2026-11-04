"""Durable v3 exact copies; all roots and values are private fictional fixtures."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, ExitStack
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'tests')]
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import backtest_control as backtest_control
from backtest.application import jobs as backtest_jobs
from backtest.application import queue as queue
from backtest.application import durable_evidence as durable
from backtest import result_evidence as result_evidence
from backtest.application import library as saved
import test_result_evidence as codec
from test_saved_backtests import snapshot as legacy_snapshot

LIMIT=4*1024**2


def source(kind='custom',*,large=False,seed=42):
    stream=io.BytesIO();options=dict(start='2019-12-30',end='2020-04-02',months=1,rank_to=53)
    plan=None
    if kind=='random':
        options.update(trials=2,seed=seed)
        plan=dict(seed=seed,requested=2,start=options['start'],end=options['end'],months=1,
            options=dict(rank_to=53),samples=[['2020-01-02','2020-02-03','2020-03-02']]*2,
            window_start='2020-01-02',window_end='2020-04-02')
    writer=result_evidence.Writer(stream,trials=2 if plan else 1,
        metadata=dict(mode=kind,options=options,configuration=plan,generation='fictional-generation',source={'fixture':'original'}),
        max_bytes=LIMIT,piece_bytes=127,record_bytes=1024**2)
    originals=[]
    for n in range(1,3 if plan else 2):
        writer.start_trial(n);pairs,select=codec.fixture()
        if large:
            original_select=select
            def select(*args):
                value=original_select(*args)
                for h in value['holdings']:h['large_extension']='測試'*12000
                return value
        result=codec.portfolio_results.evaluate(pairs,select,common_start=codec.date(2019,12,30))
        result.update(options=deepcopy(options),months=1,seconds=n/10,diagnostic={'original':None,'signed':-0.0})
        for period in result['periods']:writer.period(period)
        writer.end_trial({k:v for k,v in result.items() if k!='periods'});originals.append(result)
    summary={k:v for k,v in originals[0].items() if k!='periods'} if not plan else dict(
        completed=2,trials=[{'trial':n,'periods':3} for n in (1,2)],configuration=plan,
        distributions={'cagr':{'mean':None}},seconds=.3,extension={'keep':[None,-0.0,'測試']})
    writer.finish(summary)
    reader=result_evidence.Reader(stream,max_bytes=LIMIT)
    metadata=dict(version=3,kind=kind,settings=dict(mode=kind,**options),result=summary,
        catalog={'metrics':{'original':'Original 測試 label'},'filters':{}},presentation={'periodLabel':'Original label'},
        captured_at='2026-10-29T00:00:00Z',extension={'all':[None,False,1.,-0.0]})
    return reader,metadata,originals


def submission(metadata):
    return dict(id=uuid.uuid4().hex,name='Fictional',mode=metadata['kind'],
        options={k:v for k,v in metadata['settings'].items() if k!='mode'},
        catalog=metadata['catalog'],presentation=metadata['presentation'])


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);self.budget=durable.Budget(96*1024**2)
        self.library=saved.Store(self.root/'library.sqlite',evidence_budget=self.budget)
        self.queue=queue.Store(self.root/'queue.sqlite',evidence_budget=self.budget)
        self.addCleanup(self.clean)

    def clean(self):
        self.budget.collect()
        self.assertEqual(self.budget.measurements()['reserved_bytes'],0)
        self.assertFalse(list(self.root.glob('.evidence-reader-*')))

    def publish(self,kind='custom',**kwargs):
        reader,meta,expected=source(kind,**kwargs)
        record=self.library.save_evidence('Original',meta,reader)
        return record,reader,meta,expected

    def completed_queue(self,reader,meta):
        req=submission(meta);self.queue.enqueue(req);self.queue.claim()
        plan=reader.metadata['configuration']
        if plan:self.queue.progress(req['id'],'configuration',plan)
        self.queue.finish_evidence(req['id'],meta,reader)
        return req

    def sql(self,path,statement,args=()):
        with closing(sqlite3.connect(path)) as db,db:return db.execute(statement,args).fetchall()

    def test_exact_eager_agreement_original_bytes_extensions_and_large_period(self):
        for kind in ('custom','random'):
            record,reader,meta,expected=self.publish(kind,large=True)
            req=self.completed_queue(reader,meta)
            original=reader.stream.getvalue()
            self.assertGreater(len(original),durable.CHUNK_BYTES)
            with self.library.open_evidence(record['id']) as opened,self.queue.open_evidence(req['id']) as queued:
                self.assertEqual(opened.metadata,meta);self.assertEqual(queued.metadata,meta)
                self.assertEqual(codec.collect(opened.reader),expected)
                self.assertEqual(codec.collect(queued.reader),expected)
                self.assertEqual(opened.stream.seek(0),0)
                self.assertEqual(opened.stream.read(),original)
                self.assertEqual(json.dumps(codec.collect(queued.reader),sort_keys=True),json.dumps(expected,sort_keys=True))
            for store,identifier in ((self.library,record['id']),(self.queue,req['id'])):
                with self.assertRaises(durable.RequiresReader):store.get(identifier)

    def test_legacy_v1_v2_read_without_rewriting_or_evidence_references(self):
        saved_rows=[]
        for version in (1,2):
            snap=legacy_snapshot('random');snap['version']=version
            if version==2:snap['presentation']={}
            record=self.library.save('legacy',snap)
            saved_rows.append((record['id'],self.sql(self.library.path,'SELECT snapshot FROM records WHERE id=?',(record['id'],))[0][0]))
            self.assertEqual(self.library.get(record['id'])['snapshot'],snap)
        self.publish()
        for identifier,packed in saved_rows:
            self.assertEqual(self.sql(self.library.path,'SELECT snapshot FROM records WHERE id=?',(identifier,))[0][0],packed)
            with self.assertRaises(durable.RequiresReader):
                with self.library.open_evidence(identifier):pass
        req=submission(source()[1]);self.queue.enqueue(req);self.queue.claim()
        snap=legacy_snapshot('custom');self.queue.finish(req['id'],'complete',snapshot=snap)
        original=self.sql(self.queue.path,'SELECT snapshot FROM jobs WHERE id=?',(req['id'],))[0][0]
        self.completed_queue(*source()[:2]);self.assertEqual(self.queue.get(req['id'])['snapshot'],snap)
        self.assertEqual(self.sql(self.queue.path,'SELECT snapshot FROM jobs WHERE id=?',(req['id'],))[0][0],original)

    def test_reopen_and_complete_traversal_after_inputs_and_checkpoints_removed_no_calculation(self):
        record,reader,meta,expected=self.publish('random');req=self.completed_queue(reader,meta)
        reader.stream.close()
        # These unrelated disposable files represent evicted/replaced producer inputs.
        for name in ('checkpoints.sqlite','financial-generation'):
            path=self.root/name;path.write_bytes(b'old');path.unlink();path.write_bytes(b'new')
        with patch.object(backtest_jobs.Original,'calculate',side_effect=AssertionError('Calculation forbidden')),patch('backtest.runtime.cache_access.access',side_effect=AssertionError('Financial ownership forbidden')):
            for store,identifier in ((saved.Store(self.library.path),record['id']),(queue.Store(self.queue.path),req['id'])):
                with store.open_evidence(identifier) as opened:
                    self.assertEqual(codec.collect(opened.reader),expected)
                    self.assertEqual(opened.metadata,meta)
                    self.assertEqual(sum(1 for r in opened.reader.records() if r['type']=='holding'),12)

    def test_publication_invisible_until_atomic_commit_and_failure_preserves_source(self):
        reader,meta,_=source(large=True);before=reader.stream.getvalue();counts=[]
        self.publish()
        old=durable.ChunkStream
        def check(*args):
            with closing(sqlite3.connect(self.library.path)) as other:
                counts.append(other.execute('SELECT COUNT(*) FROM records').fetchone()[0])
                self.assertEqual(other.execute('SELECT COUNT(DISTINCT record_id) FROM evidence_chunks').fetchone()[0],1)
            return old(*args)
        with patch.object(durable,'ChunkStream',side_effect=check):self.library.save_evidence('new',meta,reader)
        self.assertEqual(counts,[1]);self.assertEqual(len(self.library.list()),2)
        self.sql(self.library.path,"CREATE TRIGGER fail_publish BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'full'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.library.save_evidence('failed',meta,reader)
        self.assertEqual(len(self.library.list()),2);self.assertEqual(reader.stream.getvalue(),before)
        self.assertEqual(self.sql(self.library.path,'SELECT COUNT(DISTINCT record_id) FROM evidence_chunks')[0][0],2)

    def test_cancel_disk_full_capacity_and_partial_copy_rollback(self):
        record,reader,meta,_=self.publish(large=True);before=reader.stream.getvalue()
        actual=self.budget.max_bytes
        for failure in ('budget','disk','write','cancel'):
            with ExitStack() as stack:
                if failure=='budget':self.budget.max_bytes=1
                elif failure=='disk':stack.enter_context(patch.object(durable.shutil,'disk_usage',return_value=type('Usage',(),{'free':0})()))
                elif failure=='write':
                    self.sql(self.library.path,"CREATE TRIGGER fail_chunk BEFORE INSERT ON evidence_chunks WHEN NEW.ordinal=1 BEGIN SELECT RAISE(ABORT,'disk full'); END")
                else:
                    calls=0
                    def check():
                        nonlocal calls
                        calls+=1
                        if calls==4:raise backtest_control.Cancelled()
                    stack.enter_context(patch.object(backtest_control,'checkpoint',side_effect=check))
                with self.assertRaises((durable.CapacityError,sqlite3.IntegrityError,backtest_control.Cancelled)):
                    self.library.save_evidence('failure',meta,reader)
            self.budget.max_bytes=actual
            if failure=='write':self.sql(self.library.path,'DROP TRIGGER fail_chunk')
            self.assertEqual(len(self.library.list()),1)
            self.assertEqual(self.sql(self.library.path,'SELECT COUNT(DISTINCT record_id) FROM evidence_chunks')[0][0],1)
            self.assertEqual(reader.stream.getvalue(),before)
        with self.library.open_evidence(record['id']) as opened:self.assertEqual(opened.metadata,meta)

    def test_metadata_plan_settings_summary_and_content_binding(self):
        record,reader,meta,_=self.publish('random')
        for change in ('kind','settings','summary','presentation'):
            bad=deepcopy(meta)
            if change=='kind':bad['kind']='custom'
            elif change=='settings':bad['settings']['rank_to']=54
            elif change=='summary':bad['result']['seconds']=1.
            else:bad['presentation']=None
            with self.assertRaises(ValueError):self.library.save_evidence('bad',bad,reader)
        # Omitted seed and generated seed remain distinct original evidence.
        unseeded=deepcopy(meta);unseeded['settings']['seed']=None
        self.library.save_evidence('generated seed',unseeded,reader)
        packed=self.sql(self.library.path,'SELECT snapshot FROM records WHERE id=?',(record['id'],))[0][0]
        envelope=json.loads(packed[len(durable.MAGIC):]);envelope['snapshot']=envelope['snapshot'].replace('Original label','Changed label')
        self.sql(self.library.path,'UPDATE records SET snapshot=? WHERE id=?',(durable.MAGIC+json.dumps(envelope).encode(),record['id']))
        with self.assertRaises(ValueError):
            with self.library.open_evidence(record['id']):pass
        self.assertEqual(len(self.library.list()),2)

    def test_corrupt_missing_duplicate_reordered_and_truncated_chunks_never_open(self):
        mutations=("DELETE FROM evidence_chunks WHERE ordinal=1", "UPDATE evidence_chunks SET payload=x'00' WHERE ordinal=1",
            'UPDATE evidence_chunks SET ordinal=ordinal+1000',
            "INSERT INTO evidence_chunks SELECT record_id,99999,payload FROM evidence_chunks WHERE ordinal=0")
        for statement in mutations:
            record,_,_,_=self.publish(large=True)
            with closing(sqlite3.connect(self.library.path)) as db:
                db.execute('BEGIN');db.execute(statement)
                # A second connection never sees uncommitted corruption.
                with self.library.open_evidence(record['id']):pass
                db.commit()
            with self.assertRaises(ValueError):
                with self.library.open_evidence(record['id']):pass
            self.library.delete(record['id'])
        record,_,_,_=self.publish(large=True)
        rows=self.sql(self.library.path,'SELECT payload FROM evidence_chunks WHERE record_id=? AND ordinal IN (0,1) ORDER BY ordinal',(record['id'],))
        self.sql(self.library.path,'UPDATE evidence_chunks SET payload=CASE ordinal WHEN 0 THEN ? WHEN 1 THEN ? ELSE payload END WHERE record_id=?',(rows[1][0],rows[0][0],record['id']))
        with self.assertRaises(ValueError):
            with self.library.open_evidence(record['id']):pass

    def test_source_change_after_reader_validation_fails_destination_before_publication(self):
        reader,meta,_=source();data=bytearray(reader.stream.getvalue());data[12]^=1
        reader.stream.seek(0);reader.stream.write(data)
        with self.assertRaises(ValueError):self.library.save_evidence('bad',meta,reader)
        self.assertEqual(self.library.list(),[])
        self.assertEqual(self.sql(self.library.path,'SELECT COUNT(*) FROM evidence_chunks')[0][0],0)

    def test_delete_active_readers_and_same_database_copy_no_database_pin(self):
        record,_,meta,expected=self.publish('random');deleted=False
        with self.library.open_evidence(record['id']) as first,self.library.open_evidence(record['id']) as second:
            self.assertEqual(self.budget.measurements()['reservations'],2)
            self.library.delete(record['id']);deleted=True
            self.assertEqual(self.library.list(),[])
            replacement=self.library.save_evidence('independent',first.metadata,first.reader)
            self.assertEqual(codec.collect(second.reader),expected)
            with self.assertRaises(saved.Missing):
                with self.library.open_evidence(record['id']):pass
        self.assertTrue(deleted)
        with self.library.open_evidence(replacement['id']) as opened:self.assertEqual(opened.metadata,meta)
        req=self.completed_queue(*source('random')[:2])
        with self.queue.open_evidence(req['id']) as opened:
            item=self.queue.listing()['records'][0]
            self.queue.change(req['id'],'delete',dict(revision=item['revision']))
            self.assertTrue(list(opened.reader.records()))
            with self.assertRaises(queue.Conflict):self.queue.enqueue(req)
        self.assertEqual(self.sql(self.queue.path,'SELECT COUNT(*) FROM evidence_chunks')[0][0],0)

    def test_cleanup_failure_keeps_charge_until_retry(self):
        record,_,_,_=self.publish();original=Path.unlink
        def unlink(path,*args,**kw):
            if path.name.startswith('.evidence-reader-'):raise PermissionError('fictional sharing lock')
            return original(path,*args,**kw)
        with patch.object(Path,'unlink',unlink),self.assertRaises(PermissionError):
            with self.library.open_evidence(record['id']):pass
        self.assertEqual(self.budget.measurements()['pending_cleanup'],1)
        self.assertGreater(self.budget.measurements()['reserved_bytes'],0)
        self.budget.collect();self.assertEqual(self.budget.measurements()['reserved_bytes'],0)

    def test_library_cap_atomic_across_store_instances_no_eviction(self):
        for _ in range(98):self.library.save('legacy',legacy_snapshot())
        def save(n):
            reader,meta,_=source()
            try:return saved.Store(self.library.path,evidence_budget=self.budget).save_evidence(str(n),meta,reader)
            except saved.Full:return None
        with ThreadPoolExecutor(max_workers=4) as pool:records=list(pool.map(save,range(5)))
        self.assertEqual(sum(r is not None for r in records),2);self.assertEqual(len(self.library.list()),100)
        chosen=next(r for r in records if r)
        self.library.delete(chosen['id']);self.assertEqual(len(self.library.list()),99)
        reader,meta,_=source();self.library.save_evidence('replacement',meta,reader)
        self.assertEqual(len(self.library.list()),100)

    def test_queue_exact_retry_state_stop_plan_and_mutation_contracts(self):
        reader,meta,_=source('random');req=submission(meta);self.queue.enqueue(req);self.queue.claim()
        self.queue.progress(req['id'],'configuration',reader.metadata['configuration'])
        before=self.queue.listing()['records'][0]
        bad=deepcopy(meta);bad['presentation']={'changed':True}
        with self.assertRaises(queue.Conflict):self.queue.finish_evidence(req['id'],bad,reader)
        self.queue.finish_evidence(req['id'],meta,reader);first=self.queue.listing()['records'][0]
        self.queue.finish_evidence(req['id'],meta,reader)
        self.assertEqual(self.queue.listing()['records'][0],first)
        with self.assertRaises(queue.Conflict):self.queue.finish_evidence(req['id'],bad,reader)
        reader2,meta2,_=source();req2=submission(meta2);self.queue.enqueue(req2);self.queue.claim()
        running=next(r for r in self.queue.listing()['records'] if r['id']==req2['id'])
        self.queue.change(req2['id'],'stop',dict(revision=running['revision']))
        self.assertEqual(self.queue.finish_evidence(req2['id'],meta2,reader2)['state'],'cancelled')
        self.assertEqual(self.sql(self.queue.path,'SELECT COUNT(*) FROM evidence_chunks WHERE record_id=?',(req2['id'],))[0][0],0)
        self.assertGreater(first['revision'],before['revision'])

    def test_jobs_pin_expiry_copy_and_shutdown_drain(self):
        source_reader,meta,expected=source()
        class Calculation:
            def calculate_into(self,mode,options,destination,*args,**kw):
                data=source_reader.stream.getvalue();destination.write(data)
                return dict(manifest=source_reader.manifest,transfer=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        jobs=backtest_jobs.Jobs(Calculation(),evidence_root=self.root/'jobs',evidence_bytes=4*LIMIT)
        jobs.start_evidence('a'*32,'custom',meta['settings'],max_bytes=LIMIT)
        jobs.runs['a'*32]['thread'].join(10);self.assertEqual(jobs.snapshot('a'*32)['state'],'complete')
        with jobs.open_evidence('a'*32) as reader:
            jobs.runs['a'*32]['finished']=time.time()-86401
            with self.assertRaises(backtest_jobs.Missing):jobs.snapshot('a'*32)
            record=self.library.save_evidence('expired pinned job',meta,reader)
            self.assertGreater(jobs.evidence.measurements()['retained_bytes'],0)
            closed=Event();thread=Thread(target=lambda:(jobs.close(),closed.set()));thread.start()
            self.assertFalse(closed.wait(.02))
        thread.join(3);self.assertTrue(closed.is_set());self.assertEqual(jobs.evidence.measurements()['reserved_bytes'],0)
        with self.library.open_evidence(record['id']) as opened:self.assertEqual(codec.collect(opened.reader),expected)

    def test_delete_during_read_acquisition_and_failed_open_release_locks(self):
        record,_,_,expected=self.publish(large=True);entered=Event();release=Event();deleted=Event();errors=[]
        old=durable.ChunkStream.read;context=[]
        def read(stream,size=-1):
            if not entered.is_set():entered.set();self.assertTrue(release.wait(5))
            return old(stream,size)
        def opening():
            try:
                with self.library.open_evidence(record['id']) as opened:
                    context.append(opened);self.assertEqual(codec.collect(opened.reader),expected)
            except BaseException as error:errors.append(error)
        with patch.object(durable.ChunkStream,'read',read):
            thread=Thread(target=opening);thread.start();self.assertTrue(entered.wait(5))
            deleter=Thread(target=lambda:(self.library.delete(record['id']),deleted.set()));deleter.start()
            self.assertFalse(deleted.wait(.03));release.set();thread.join(10);deleter.join(10)
        self.assertEqual(errors,[]);self.assertTrue(deleted.is_set());self.assertTrue(context[0].closed)

    def test_sqlite_full_rolls_back_without_replacing_previous_record(self):
        record,reader,meta,_=self.publish(large=True)
        connect=self.library.connect
        def limited():
            db=connect();pages=db.execute('PRAGMA page_count').fetchone()[0]
            db.execute('PRAGMA max_page_count='+str(pages+1));return db
        with patch.object(self.library,'connect',side_effect=limited):
            with self.assertRaisesRegex(sqlite3.OperationalError,'full'):
                self.library.save_evidence('too much',meta,reader)
        self.assertEqual(len(self.library.list()),1)
        with self.library.open_evidence(record['id']) as opened:self.assertEqual(opened.metadata,meta)
        self.assertEqual(self.sql(self.library.path,'PRAGMA integrity_check'),[('ok',)])

    def test_failed_open_releases_read_transaction_and_temporary_charge(self):
        record,_,_,_=self.publish()
        with patch.object(durable,'_reader',side_effect=OSError('fictional reader write failure')):
            with self.assertRaises(OSError):
                with self.library.open_evidence(record['id']):pass
        self.assertEqual(self.budget.measurements()['reserved_bytes'],0)
        self.library.delete(record['id']);self.assertEqual(self.library.list(),[])

    def test_queue_copy_failure_keeps_running_state_exact_plan_and_old_evidence(self):
        reader,meta,_=source('random');req=submission(meta)
        self.queue.enqueue(req);self.queue.claim();self.queue.progress(req['id'],'configuration',reader.metadata['configuration'])
        before=self.queue.listing()['records'][0]
        self.sql(self.queue.path,"CREATE TRIGGER block_completion BEFORE UPDATE OF snapshot ON jobs BEGIN SELECT RAISE(ABORT,'full'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.queue.finish_evidence(req['id'],meta,reader)
        self.assertEqual(self.queue.listing()['records'][0],before)
        self.assertEqual(self.sql(self.queue.path,'SELECT COUNT(*) FROM evidence_chunks')[0][0],0)
        self.sql(self.queue.path,'DROP TRIGGER block_completion')
        self.queue.finish_evidence(req['id'],meta,reader)
        with self.queue.open_evidence(req['id']) as opened:self.assertEqual(opened.metadata,meta)

    def test_real_fictional_input_generation_replacement_and_checkpoint_eviction(self):
        import test_numerical_trials as trials
        from numerical_inputs_fixture import NumericInputs
        from backtest.engines.numerical.numba import NumbaExecutor
        from backtest.engines.numerical.portfolio import NumericalPortfolio
        from backtest.engines.numerical.portfolio import compare_results
        fixture=trials.NumericalTrialsTests('test_full_month_pool_metric_filter_rank_matrix_and_exact_recovery')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        inputs,provider,portfolio,checkpoints=fixture.evaluator('source')
        config=fixture.config(months=12,rank_to=3);binding=trials.diagnostic.checkpoint_binding(portfolio,config)
        experiment=checkpoints.open(binding);details=[]
        result=trials.diagnostic.run(portfolio,config,experiment,capture=lambda n,r:details.append(r))['result']
        options=dict(start=config['start'],end=config['end'],months=config['months'],trials=config['requested'],seed=config['seed'],**config['options'])
        stream=io.BytesIO();writer=result_evidence.Writer(stream,trials=config['requested'],
            metadata=dict(mode='random',options=options,configuration=config,generation=inputs.signature,source=binding['implementation']),max_bytes=LIMIT)
        for n,trial in enumerate(details,1):
            writer.start_trial(n)
            for period in trial['periods']:writer.period(period)
            writer.end_trial({k:v for k,v in trial.items() if k!='periods'})
        writer.finish(result);reader=result_evidence.Reader(stream,max_bytes=LIMIT)
        meta=dict(version=3,kind='random',settings=dict(mode='random',**options),result=result,
            catalog={'metrics':{},'filters':{}},presentation={'original':'saved labels'})
        record=self.library.save_evidence('generation bound original',meta,reader);req=self.completed_queue(reader,meta)
        with fixture.db:fixture.db.execute("UPDATE prices SET adjusted=adjusted*1.1 WHERE day>='2016-01-04'")
        replacement=NumericInputs(fixture.reader,trials.s);self.addCleanup(replacement.close)
        self.assertNotEqual(replacement.signature,inputs.signature)
        new_provider=NumbaExecutor(replacement,limits=deepcopy(provider.limits));self.addCleanup(new_provider.close)
        new_portfolio=NumericalPortfolio(replacement,new_provider);self.addCleanup(new_portfolio.close)
        new_binding=trials.diagnostic.checkpoint_binding(new_portfolio,config);checkpoints.max_experiments=1
        changed=trials.diagnostic.run(new_portfolio,config,checkpoints.open(new_binding))['result']
        self.assertNotEqual(result['distributions'],changed['distributions']);self.assertEqual(experiment.read(),[])
        with ExitStack() as guards:
            for owner,name in ((trials.diagnostic,'run'),(trials.diagnostic,'run_into'),(trials.s,'backtest'),
                    (trials.s,'backtest_dates'),(backtest_jobs.Original,'calculate'),(trials.trial_checkpoints.Experiment,'load'),
                    (trials.trial_checkpoints.Store,'open')):
                guards.enter_context(patch.object(owner,name,side_effect=AssertionError('Stored evidence must not calculate')))
            for store,identifier in ((saved.Store(self.library.path),record['id']),(queue.Store(self.queue.path),req['id'])):
                with store.open_evidence(identifier) as opened:
                    actual=codec.collect(opened.reader)
                    self.assertEqual(actual,details)
                    for original,copy in zip(details,actual,strict=True):
                        self.assertTrue(compare_results(original,copy)['exact'])
                    self.assertEqual(opened.metadata,meta)
                    self.assertEqual(opened.reader.metadata['generation'],inputs.signature)

    def test_independent_process_copies_respect_atomic_cap_without_eviction(self):
        for _ in range(98):self.library.save('legacy',legacy_snapshot())
        reader,meta,_=source();path=self.root/'source';path.write_bytes(reader.stream.getvalue())
        metadata=self.root/'metadata';metadata.write_text(json.dumps(meta))
        code="""import sys,json
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/website',sys.argv[1]+'/scripts']
from backtest.application import library as saved_backtests
from backtest import result_evidence
assert sys.stdin.readline()=='GO\\n'
with open(sys.argv[3],'rb') as stream:
 reader=result_evidence.Reader(stream,max_bytes=4*1024**2)
 try:saved_backtests.Store(sys.argv[2]).save_evidence('process',json.loads(Path(sys.argv[4]).read_text()),reader)
 except saved_backtests.Full:raise SystemExit(11)
"""
        processes=[subprocess.Popen([sys.executable,'-I','-B','-c',code,str(ROOT),str(self.library.path),str(path),str(metadata)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(3)]
        def finish(proc):
            out,err=proc.communicate('GO\n',timeout=30)
            self.assertIn(proc.returncode,(0,11),out+err);return proc.returncode
        try:
            with ThreadPoolExecutor(max_workers=3) as pool:codes=list(pool.map(finish,processes))
        finally:
            for proc in processes:
                if proc.poll() is None:proc.kill();proc.communicate(timeout=10)
        self.assertEqual(sorted(codes),[0,0,11]);self.assertEqual(len(self.library.list()),100)
        self.assertEqual(self.sql(self.library.path,'SELECT COUNT(DISTINCT record_id) FROM evidence_chunks')[0][0],2)

    def test_oversized_metadata_rejected_without_whole_json_encoding(self):
        reader,meta,_=source();meta['extension']=['x'*1024]*9000
        with patch.object(durable.json,'dumps',side_effect=AssertionError('Whole metadata encoding forbidden')):
            with self.assertRaises(durable.CapacityError):self.library.save_evidence('oversized metadata',meta,reader)
        self.assertEqual(self.library.list(),[])
        self.assertEqual(self.sql(self.library.path,'SELECT COUNT(*) FROM evidence_chunks')[0][0],0)

    def test_private_writer_process_exit_before_and_after_commit(self):
        reader,meta,_=source(large=True);input_path=self.root/'input';input_path.write_bytes(reader.stream.getvalue())
        metadata=self.root/'metadata';metadata.write_text(json.dumps(meta))
        self.publish()
        code='''import sys,os,json,sqlite3
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/website',sys.argv[1]+'/scripts']
from backtest.application import library as saved_backtests, durable_evidence
from backtest import result_evidence
with open(sys.argv[3],'rb') as stream:
 reader=result_evidence.Reader(stream,max_bytes=4*1024**2)
 store=saved_backtests.Store(sys.argv[2]);metadata=json.loads(Path(sys.argv[4]).read_text())
 if sys.argv[5]=='before':
  old=durable_evidence.ChunkStream
  def stop(*a):os._exit(37)
  durable_evidence.ChunkStream=stop
 store.save_evidence('child',metadata,reader)
 os._exit(38)
'''
        for when,exit_code,count in (('before',37,1),('after',38,2)):
            proc=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT),str(self.library.path),str(input_path),str(metadata),when],timeout=30)
            self.assertEqual(proc.returncode,exit_code);self.assertEqual(len(self.library.list()),count)
            self.assertEqual(self.sql(self.library.path,'PRAGMA integrity_check'),[('ok',)])
            self.assertEqual(self.sql(self.library.path,'SELECT COUNT(DISTINCT record_id) FROM evidence_chunks')[0][0],count)


if __name__=='__main__':unittest.main()
