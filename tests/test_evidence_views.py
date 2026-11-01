"""Additive browser-reader ownership and complete exports on fictional evidence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Event, Thread, local
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'website'),str(ROOT/'scripts'),str(ROOT/'tests')]
from backtest.application import jobs as backtest_jobs
from backtest.application import queue as backtest_queue
from backtest.application import durable_evidence as durable_evidence
from backtest.application import evidence_views as evidence_views
from backtest.application import temporary_evidence as job_evidence
from backtest.application import result_exports as result_exports
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest import result_evidence as result_evidence
from backtest.application import library as saved_backtests
import serve_app
from backtest.application.result_access import ResultAccess
from test_durable_evidence import source,submission
from test_saved_backtests import snapshot as legacy


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.budget=durable_evidence.Budget(96*1024**2)
        self.store=saved_backtests.Store(self.root/'library.sqlite',evidence_budget=self.budget)
        self.jobs=backtest_jobs.Jobs();self.addCleanup(self.jobs.close)
        self.access=ResultAccess(self.jobs,self.store,None);self.addCleanup(self.access.close)

    def stored(self,kind='random',**kw):
        reader,metadata,original=source(kind,**kw)
        record=self.store.save_evidence('Original',metadata,reader)
        return record,metadata,original

    def acquire(self,identifier='a'*32,record=None):
        record=record or self.stored()[0]
        return self.access.acquire(identifier,dict(source=dict(kind='saved',id=record['id'])))

    def test_all_trials_periods_holdings_and_original_extensions(self):
        record,metadata,original=self.stored();artifact=self.acquire(record=record)
        self.assertEqual({k:v for k,v in artifact.items() if k!='evidence'},metadata)
        with self.access.read('a'*32) as (meta,reader):
            self.assertEqual(meta,metadata)
            for number,expected in enumerate(original,1):
                info=evidence_views.trial(reader,number)
                self.assertEqual(info['summary'],{k:v for k,v in expected.items() if k!='periods'})
                periods=evidence_views.read(reader,dict(operation='periods',trial=number))
                for row,period in zip(periods['rows'],expected['periods'],strict=True):
                    self.assertEqual(row['value'],{k:v for k,v in period.items() if k!='holdings'})
                    page=evidence_views.read(reader,dict(operation='holdings',trial=number,period=row['number']))
                    self.assertEqual(page['rows'],period['holdings']);self.assertEqual(page['next'],None)
            for selection in (dict(operation='periods',trial=3),dict(operation='holdings',trial=1,period=9),dict(operation='periods',trial=1,cursor=-1)):
                with self.assertRaises(ValueError):evidence_views.read(reader,selection)

    def test_pages_preserve_every_row_and_allow_a_large_valid_record(self):
        original=[dict(rank=n,extension='x'*(300000 if n==80 else 8000)) for n in range(180)]
        cursor=0;observed=[]
        while cursor is not None:
            page=evidence_views.page(iter(original),cursor);self.assertLessEqual(len(page['rows']),64)
            self.assertEqual(page['total'],180);observed.extend(page['rows']);cursor=page['next']
        self.assertEqual(observed,original)
        with self.assertRaises(ValueError):evidence_views.page(iter(original),181)

    def test_acquisition_retry_capacity_and_source_deletion(self):
        record,metadata,_=self.stored();artifact=self.acquire(record=record)
        self.assertEqual(self.acquire(record=record),artifact)
        self.assertEqual(self.budget.measurements()['reservations'],1)
        with self.assertRaises(ValueError):self.access._acquire('a'*32,{'different':True},lambda:None)
        self.access.limit=1
        with self.assertRaisesRegex(ValueError,'capacity'):self.acquire('b'*32,record)
        self.store.delete(record['id'])
        with self.access.read('a'*32) as (meta,reader):self.assertEqual(meta,metadata);self.assertEqual(reader.manifest['trials'],2)
        self.access.release('a'*32);self.access.release('a'*32)
        self.assertEqual(self.budget.measurements()['reserved_bytes'],0)
        with self.assertRaises(ValueError):
            with self.access.read('a'*32):pass

    def test_concurrent_readers_have_independent_seek_positions(self):
        record,_,_=self.stored();self.acquire(record=record)
        def inspect(number):
            with self.access.read('a'*32) as (_,reader):
                return evidence_views.trial(reader,number),list(evidence_views.holdings(reader,number,1))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first,second=list(pool.map(inspect,(1,2)))
        self.assertEqual(first[1],second[1]);self.assertNotEqual(first[0]['summary']['seconds'],second[0]['summary']['seconds'])

    def test_request_rebinding_rejects_corruption_outside_requested_prefix(self):
        record,_,_=self.stored();self.acquire(record=record)
        opened=self.access.entries['a'*32]['opened']
        # The display was valid. A later change to its final byte must reject
        # even a first-period request, before any selected rows are exposed.
        with opened.path.open('r+b') as stream:
            stream.seek(-1,2);value=stream.read(1);stream.seek(-1,2)
            stream.write(bytes([value[0]^1]))
        with self.assertRaisesRegex(ValueError,'changed'):
            with self.access.read('a'*32):self.fail('Corrupt reader escaped')
        self.assertEqual(self.access.measurements()['requests'],0)
        self.access.release('a'*32)
        self.assertEqual(self.budget.measurements()['reserved_bytes'],0)

    def test_release_and_shutdown_drain_request_pins(self):
        record,_,_=self.stored();self.acquire(record=record)
        with self.access.read('a'*32) as (_,reader):
            self.store.delete(record['id']);self.access.release('a'*32)
            self.assertGreater(self.budget.measurements()['reserved_bytes'],0)
            done=Event();thread=Thread(target=lambda:(self.access.close(),done.set()));thread.start()
            self.assertFalse(done.wait(.05))
            chunks=result_exports.csv(reader,'holdings',1);self.assertTrue(next(chunks));chunks.close()
        thread.join(5);self.assertTrue(done.is_set());self.assertEqual(self.budget.measurements()['reserved_bytes'],0)

    def test_open_failure_and_cleanup_failure_keep_retryable_ownership(self):
        def broken():raise OSError('fictional opener failure')
        with self.assertRaises(OSError):self.access._acquire('b'*32,{},broken)
        self.assertEqual(self.access.measurements()['acquiring'],0)
        record,_,_=self.stored();self.acquire(record=record)
        original=Path.unlink
        def fail(path,*args,**kw):
            if path.name.startswith('.evidence-reader-'):raise PermissionError('fictional sharing lock')
            return original(path,*args,**kw)
        with patch.object(Path,'unlink',fail):
            with self.assertRaises(PermissionError):self.access.release('a'*32)
            self.assertEqual(self.access.measurements()['readers'],1)
            self.assertGreater(self.budget.measurements()['reserved_bytes'],0)
        self.access.release('a'*32);self.budget.collect()
        self.assertEqual(self.access.measurements()['readers'],0)
        self.assertEqual(self.budget.measurements()['reserved_bytes'],0)

    def test_fresh_reader_survives_jobs_expiry_and_saves_original_metadata(self):
        original_reader,metadata,_=source('custom')
        class Owner:
            def calculate_into(owner,mode,options,destination,*callbacks,**kw):
                data=original_reader.stream.getvalue();destination.write(data)
                import hashlib
                return dict(transfer=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest()),manifest=original_reader.manifest)
        self.jobs.calculations=Owner()
        self.jobs.start_evidence('c'*32,'custom',{k:v for k,v in metadata['settings'].items() if k!='mode'},max_bytes=4*1024**2)
        self.jobs.runs['c'*32]['thread'].join(5);self.assertEqual(self.jobs.snapshot('c'*32)['state'],'complete')
        display={k:metadata[k] for k in ('catalog','presentation','captured_at')}
        artifact=self.access._acquire('a'*32,{'kind':'run','id':'c'*32},lambda:self.jobs.display_evidence('c'*32,display))
        self.jobs.runs['c'*32]['finished']=time.time()-86401
        with self.assertRaises(backtest_jobs.Missing):self.jobs.snapshot('c'*32)
        with self.access.read('a'*32) as (meta,reader):
            row=self.store.save_evidence('From expired job',meta,reader)
            self.assertEqual(meta['result'],metadata['result'])
        self.access.release('a'*32)
        self.assertEqual(self.jobs.evidence.measurements()['reserved_bytes'],0)
        with self.store.open_evidence(row['id']) as opened:self.assertEqual(opened.metadata['settings'],artifact['settings'])

    def test_csv_quoting_unicode_number_spelling_crlf_and_complete_order(self):
        reader,_,original=source('custom')
        expected_rows=[result_exports.HOLDINGS]
        for period in original[0]['periods']:
            for holding in period['holdings']:
                value=dict(holding,period_start=period['entry'],period_end=period['exit'],metric='ev_ebitda')
                expected_rows.append([value.get(k) for k in result_exports.HOLDINGS])
        text=lambda rows:'\r\n'.join(','.join('"'+result_exports.string(v).replace('"','""')+'"' for v in row) for row in rows)
        chunks=list(result_exports.csv(reader,'holdings',1))
        self.assertTrue(all(0<len(c)<=65536 for c in chunks));self.assertEqual(b''.join(chunks).decode(),text(expected_rows))
        self.assertFalse(b''.join(chunks).endswith(b'\r\n'))
        values=[-0.,1.,1e-7,1e-6,1e20,1e21,1.2345678901234567,1.0000000000000001e18]
        self.assertEqual([result_exports.number(v) for v in values],['0','1','1e-7','0.000001','100000000000000000000','1e+21','1.2345678901234567','1000000000000000100'])
        self.assertEqual(result_exports.filename(reader,'holdings',1),'scheduled-holdings-2019-12-30-2020-04-02.csv')

    def test_prepared_attachment_resolves_selection_once_and_matches_legacy_bytes(self):
        for mode in ('custom','random'):
            reader,_,originals=source(mode)
            if mode=='random':
                # The durable fixture's abbreviated summary is not an export
                # fixture. Supply its original explicit dates before sealing.
                summary=reader.manifest['summary'];metadata=reader.metadata
                for row,dates in zip(summary['trials'],metadata['configuration']['samples'],strict=True):row['dates']=dates
                stream=io.BytesIO();writer=result_evidence.Writer(stream,trials=2,metadata=metadata,max_bytes=4*1024**2)
                for n,original in enumerate(originals,1):
                    writer.start_trial(n)
                    for period in original['periods']:writer.period(period)
                    writer.end_trial({k:v for k,v in original.items() if k!='periods'})
                writer.finish(summary);reader=result_evidence.Reader(stream,max_bytes=4*1024**2)
            for kind in ('holdings','returns','random') if mode=='random' else ('holdings','returns'):
                expected=b''.join(result_exports.csv(reader,kind))
                name=result_exports.filename(reader,kind)
                with patch.object(evidence_views,'records',wraps=evidence_views.records) as scans:
                    export=result_exports.prepare(reader,kind)
                    self.assertEqual(export.filename,name)
                    self.assertEqual(export.content_length,len(expected))
                    chunks=list(export.chunks())
                    self.assertEqual(b''.join(chunks),expected)
                    self.assertTrue(all(0<len(chunk)<=65536 for chunk in chunks))
                    self.assertEqual(scans.call_count,0 if kind=='random' else 3)
                # The request object stores selection scalars and the borrowed
                # reader, not row collections or an encoded attachment.
                self.assertEqual(set(vars(export)),{'reader','kind','trial','filename','metric','content_length'})
                self.assertIs(export.reader,reader)
        reader,_,_=source('custom')
        with patch.object(result_exports,'_csv',side_effect=AssertionError('Unexpected formatting')):
            self.assertTrue(result_exports.filename(reader,'returns'))
        invalid=result_exports.csv(reader,'unknown')  # Existing lazy error timing.
        with self.assertRaises(ValueError):next(invalid)
        for kind,trial in (('unknown',1),('holdings',99),('returns',0)):
            with self.assertRaises(ValueError):result_exports.prepare(reader,kind,trial)
        reader.stream.seek(-1,2);value=reader.stream.read(1);reader.stream.seek(-1,2)
        reader.stream.write(bytes([value[0]^1]))
        with self.assertRaisesRegex(ValueError,'changed'):result_exports.prepare(reader,'returns')

    def test_csv_number_and_complete_bytes_against_javascript(self):
        node=shutil.which('node')
        if not node and Path('C:/Program Files/nodejs/node.exe').exists():node='C:/Program Files/nodejs/node.exe'
        if not node:self.skipTest('Node unavailable; actual native browser checks retain CSV byte parity.')
        import random,struct,math
        randomizer=random.Random(20261030)
        values=[None,False,True,'Unicode 測試 🐈, "quote"\r\nline',-0.,1e-7,1e-6,1e20,1e21]
        for _ in range(10000):
            value=struct.unpack('>d',randomizer.randbytes(8))[0]
            if math.isfinite(value):values.append(value)
        code="let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(v=>String(v??'')))));"
        result=subprocess.run([node,'-e',code],input=json.dumps(values),text=True,capture_output=True,check=True)
        self.assertEqual([result_exports.string(v) for v in values],json.loads(result.stdout))

    def test_complete_csv_bytes_use_the_actual_eager_browser_exporter(self):
        node=shutil.which('node')
        if not node and Path('C:/Program Files/nodejs/node.exe').exists():node='C:/Program Files/nodejs/node.exe'
        if not node:self.skipTest('Node unavailable')
        reader,_,originals=source('custom');original=originals[0]
        for period in original['periods']:
            for index,holding in enumerate(period['holdings']):
                holding['name']=None if index==0 else ('Unicode 測試 🐈, "quote"\r\nline'*3000)
        stream=io.BytesIO();writer=result_evidence.Writer(stream,trials=1,metadata=reader.metadata,max_bytes=4*1024**2)
        writer.start_trial(1)
        for period in original['periods']:writer.period(period)
        summary={k:v for k,v in original.items() if k!='periods'};writer.end_trial(summary);writer.finish(summary)
        reader=result_evidence.Reader(stream,max_bytes=4*1024**2)
        # Invoke schedule.js itself, with only DOM/download transport replaced.
        code=r"""const fs=require('fs'),vm=require('vm');let input='';
process.stdin.on('data',d=>input+=d);process.stdin.on('end',()=>{
const result=JSON.parse(input),nodes=new Map(),out=[];let csv='';
const node=id=>{if(!nodes.has(id))nodes.set(id,{handlers:{},addEventListener(k,f){this.handlers[k]=f;}});return nodes.get(id);};
const context=vm.createContext({ResultArtifacts:{forView:()=>({version:2,kind:'custom',result})},CalendarSettings:{init(){}},EngineControls:{init(){}},RobustnessView:{init(){}},document:{getElementById:node,createElement:()=>({click(){out.push({name:this.download,csv});}})},Blob:class{constructor(parts){this.parts=parts;}},URL:{createObjectURL(blob){csv=blob.parts.join('');return 'blob:test';},revokeObjectURL(){}}});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';ScheduleView.init()',context);
for(const kind of ['holdings','returns'])node('schedule-download-'+kind).handlers.click();
process.stdout.write(JSON.stringify(out));});"""
        expected=json.loads(subprocess.run([node,'-e',code,str(ROOT/'website/schedule.js')],input=json.dumps(original),encoding='utf-8',capture_output=True,check=True).stdout)
        for kind,golden in zip(('holdings','returns'),expected,strict=True):
            chunks=list(result_exports.csv(reader,kind))
            self.assertTrue(all(0<len(chunk)<=65536 for chunk in chunks))
            self.assertEqual(b''.join(chunks),golden['csv'].encode('utf-8'))
            self.assertEqual(result_exports.filename(reader,kind),golden['name'])

    def test_ordinary_http_open_export_save_delete_without_readiness_or_calculation(self):
        record,metadata,_=self.stored('custom')
        class Handler(serve_app.Handler):
            def log_message(self,*args):pass
            def calculation_ready(self):raise AssertionError('Reading must not check readiness')
        server=serve_app.Server(('127.0.0.1',0),Handler)
        server.backtest_jobs=self.jobs;server.result_access=self.access
        server.backtest_queue=backtest_queue.Queue(backtest_queue.Store(self.root/'queue.sqlite',evidence_budget=self.budget),library=backtest_queue.saved_backtests.Store((backtest_queue.Store(self.root/'queue.sqlite',evidence_budget=self.budget)).path.with_name('saved-library.sqlite')))
        thread=Thread(target=server.serve_forever);thread.start()
        def close():server.shutdown();thread.join(5);server.server_close()
        self.addCleanup(close)
        self.context.enter_context(patch.object(serve_app,'SAVED_BACKTESTS',self.store))
        self.context.enter_context(patch.object(backtest_jobs.Original,'calculate',side_effect=AssertionError('Calculation forbidden')))
        def request(method,path,payload=None):
            client=HTTPConnection(*server.server_address,timeout=10)
            try:
                client.request(method,path,json.dumps(payload) if payload is not None else None,headers={'Content-Type':'application/json'})
                response=client.getresponse();body=response.read()
                return response.status,dict(response.getheaders()),body
            finally:client.close()
        status,_,body=request('GET','/api/backtests/'+record['id'])
        self.assertEqual(status,409);self.assertTrue(json.loads(body)['requires_reader'])
        base='/api/backtest-runs/'+'a'*32+'/reader'
        status,_,body=request('POST',base,dict(source=dict(kind='saved',id=record['id'])))
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['settings'],metadata['settings'])
        status,_,body=request('GET',base+'/page/periods/1/0')
        self.assertEqual(status,200);self.assertEqual(len(json.loads(body)['rows']),3)
        status,headers,body=request('GET',base+'/export/holdings/1')
        self.assertEqual(status,200);self.assertEqual(int(headers['Content-Length']),len(body))
        with self.store.open_evidence(record['id']) as opened:
            self.assertEqual(body,b''.join(result_exports.csv(opened.reader,'holdings',1)))
        self.assertEqual(headers['Content-Disposition'],'attachment; filename="scheduled-holdings-2019-12-30-2020-04-02.csv"')
        status,_,body=request('POST','/api/backtests',dict(name='Copy from reader',reader='a'*32))
        self.assertEqual(status,201);copy=json.loads(body)
        request('DELETE','/api/backtests/'+record['id'])
        self.assertEqual(request('GET',base+'/export/holdings/1')[0],200)
        self.assertEqual(request('DELETE',base)[0],200)
        self.assertEqual(request('GET',base+'/page/trial/1/0')[0],400)
        with self.store.open_evidence(copy['id']) as opened:self.assertEqual(opened.metadata,metadata)
        # Both old versions retain eager opening and are never rewritten.
        for version in (1,2):
            snapshot=legacy();snapshot['version']=version
            if version==2:
                snapshot['presentation']=dict(coverage='Original coverage',periodLabel='Original dates')
            row=self.store.save('Legacy',snapshot)
            self.assertEqual(json.loads(request('GET','/api/backtests/'+row['id'])[2])['snapshot'],snapshot)

    def test_queue_reader_acquires_without_a_consumer_or_current_inputs(self):
        reader,metadata,_=source('random');store=backtest_queue.Store(self.root/'queue.sqlite',evidence_budget=self.budget)
        request=submission(metadata);store.enqueue(request);store.claim()
        store.progress(request['id'],'configuration',reader.metadata['configuration']);store.finish_evidence(request['id'],metadata,reader)
        with patch.object(backtest_jobs.Original,'calculate',side_effect=AssertionError('Calculation forbidden')):
            artifact=self.access._acquire('a'*32,dict(kind='queue',id=request['id']),lambda:store.open_evidence(request['id']))
            store.change(request['id'],'delete',dict(revision=store.listing()['records'][0]['revision']))
            with self.access.read('a'*32) as (meta,opened):
                self.assertEqual(meta,metadata);self.assertEqual(opened.metadata['configuration'],reader.metadata['configuration'])
                self.assertEqual(artifact['evidence']['trials'],2)

    def test_acquisition_shutdown_and_request_capacity(self):
        record,_,_=self.stored();entered=Event();resume=Event();errors=[]
        @contextmanager
        def paused():
            entered.set();resume.wait(5)
            with self.store.open_evidence(record['id']) as opened:yield opened
        def acquire():
            try:self.access._acquire('a'*32,{},paused)
            except ValueError as error:errors.append(error)
        worker=Thread(target=acquire);worker.start();self.assertTrue(entered.wait(2))
        closed=Event();closer=Thread(target=lambda:(self.access.close(),closed.set()));closer.start()
        self.assertFalse(closed.wait(.02));resume.set();worker.join(5);closer.join(5)
        self.assertTrue(closed.is_set());self.assertEqual(len(errors),1);self.assertEqual(self.budget.measurements()['reserved_bytes'],0)

    def test_http_attachment_pin_survives_release_deletion_and_disconnect(self):
        class Handler(serve_app.Handler):
            def log_message(self,*args):pass
            def calculation_ready(self):raise AssertionError('Readiness forbidden')
        server=serve_app.Server(('127.0.0.1',0),Handler);server.backtest_jobs=self.jobs;server.result_access=self.access
        worker=Thread(target=server.serve_forever);worker.start()
        def close():server.shutdown();worker.join(5);server.server_close()
        self.addCleanup(close)
        original=result_exports.Prepared.chunks;state=local();entered=Event();resume=Event()
        self.addCleanup(resume.set)
        def slow(*args):
            state.calls=getattr(state,'calls',0)+1
            for chunk in original(*args):
                if state.calls!=2:yield chunk;continue
                yield chunk[:32]
                entered.set()
                if not resume.wait(5):raise TimeoutError('Fixture export pause expired')
                yield chunk[32:]
        with patch.object(result_exports.Prepared,'chunks',slow),patch.object(backtest_jobs.Original,'calculate',side_effect=AssertionError('Calculation forbidden')):
            for index,disconnect in enumerate((False,True)):
                with self.subTest(disconnect=disconnect):
                    entered.clear();resume.clear()
                    record,_,_=self.stored('custom');identifier=('a' if index==0 else 'b')*32
                    self.acquire(identifier,record)
                    with self.access.read(identifier) as (_,reader):expected=b''.join(result_exports.csv(reader,'holdings',1))
                    client=HTTPConnection(*server.server_address,timeout=10)
                    try:
                        client.request('GET','/api/backtest-runs/'+identifier+'/reader/export/holdings/1')
                        response=client.getresponse();self.assertEqual(response.status,200)
                        self.assertTrue(entered.wait(2))
                        self.store.delete(record['id']);self.access.release(identifier)
                        self.assertEqual(self.access.measurements()['requests'],1)
                        self.assertGreater(self.budget.measurements()['reserved_bytes'],0)
                        if disconnect:response.close();client.close()
                        resume.set()
                        if not disconnect:self.assertEqual(response.read(),expected)
                    finally:resume.set();client.close()
                    until=time.monotonic()+5
                    while self.access.measurements()['readers'] and time.monotonic()<until:time.sleep(.01)
                    self.assertEqual(self.access.measurements()['readers'],0)
                    self.assertEqual(self.budget.measurements()['reserved_bytes'],0)

    def test_near_limit_utf8_codec_record_survives_actual_http_paging(self):
        reader,metadata,originals=source('custom');original=originals[0]
        extension=original['periods'][0]['holdings'][0]['extension']
        extension.update(large_utf8='\u0080'*3900000,lone='\ud800')
        row=original['periods'][0]['holdings'][0]
        self.assertGreater(len(json.dumps(row,ensure_ascii=True).encode()),16*1024**2)
        # Writer intentionally emits ASCII. Build the documented alternative
        # UTF-8 framing independently, then require the real Reader to validate it.
        import hashlib,struct
        records=list(reader.records());next(r for r in records if r['type']=='holding')['value']=row
        stream=io.BytesIO();digest=hashlib.sha256()
        for record in records:
            if record['type']=='complete':record=dict(record,sha256=digest.hexdigest())
            data=json.dumps(record,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8',errors='backslashreplace')
            self.assertLessEqual(len(data),result_evidence.MAX_RECORD_BYTES)
            if record['type']!='complete':digest.update(hashlib.sha256(data).digest())
            for offset in range(0,len(data),result_evidence.MAX_PIECE_BYTES):
                piece=data[offset:offset+result_evidence.MAX_PIECE_BYTES]
                last=int(offset+len(piece)==len(data));stream.write(struct.pack('!IB',len(piece),last))
                stream.write(piece);stream.write(hashlib.sha256(bytes([last])+piece).digest())
        # Real codec validation and durable publication precede HTTP inspection.
        reader=result_evidence.Reader(stream,max_bytes=16*1024**2)
        saved=self.store.save_evidence('Near-limit UTF8',metadata,reader)
        self.acquire(record=saved);self.store.delete(saved['id'])
        class Handler(serve_app.Handler):
            def log_message(self,*args):pass
            def calculation_ready(self):raise AssertionError('Readiness forbidden')
        server=serve_app.Server(('127.0.0.1',0),Handler);server.backtest_jobs=self.jobs;server.result_access=self.access
        worker=Thread(target=server.serve_forever);worker.start()
        def close():server.shutdown();worker.join(5);server.server_close()
        self.addCleanup(close)
        cursor=0;rows=[]
        while cursor is not None:
            client=HTTPConnection(*server.server_address,timeout=10)
            try:
                client.request('GET','/api/backtest-runs/'+'a'*32+'/reader/page/holdings/1/1/'+str(cursor))
                response=client.getresponse();body=response.read()
                self.assertEqual(response.status,200)
                self.assertEqual(len(body),int(response.getheader('Content-Length')))
                self.assertLessEqual(len(body),evidence_views.RESPONSE_BYTES)
                page=json.loads(body)
                self.assertEqual(body,evidence_views.encode(page))
                if cursor==0:
                    self.assertEqual(page['next'],1);self.assertEqual(len(page['rows']),1)
                    self.assertIn(b'\\ud800',body)
                rows.extend(page['rows']);cursor=page['next']
            finally:client.close()
        self.assertEqual(rows,original['periods'][0]['holdings'])
        self.assertEqual(rows[0]['extension']['lone'],'\ud800')

    def test_simultaneous_retry_opens_once_and_request_admission_is_finite(self):
        record,_,_=self.stored();entered=Event();resume=Event();calls=[]
        self.addCleanup(resume.set)
        @contextmanager
        def opener():
            calls.append(True);entered.set()
            if not resume.wait(5):raise TimeoutError('Fixture acquisition pause expired')
            with self.store.open_evidence(record['id']) as opened:yield opened
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.access._acquire,'a'*32,{},opener);self.assertTrue(entered.wait(2))
            second=pool.submit(self.access._acquire,'a'*32,{},opener);resume.set()
            self.assertEqual(first.result(),second.result())
        self.assertEqual(len(calls),1)
        self.access.request_limit=1
        with self.access.read('a'*32):
            with self.assertRaisesRegex(ValueError,'request capacity'):
                with self.access.read('a'*32):pass

    def test_request_validation_and_captured_display_identity(self):
        record,metadata,_=self.stored()
        with patch.object(self.store,'open_evidence',side_effect=AssertionError('Invalid request opened a source')):
            for request in (None,[],{},dict(source=[]),dict(source=dict(kind='saved',id=[])),
                            dict(source=dict(kind='saved',id=record['id']),display=[])):
                with self.assertRaises(ValueError):self.access.acquire('a'*32,request)
        request=dict(source=dict(kind='saved',id=record['id']),display=dict(catalog={'old':'caller'}))
        acquired=self.access.acquire('a'*32,request)
        self.assertEqual(acquired['catalog'],metadata['catalog'])
        self.assertEqual(self.access.acquire('a'*32,deepcopy(request)),acquired)
        request['display']['catalog']['old']='changed'
        with self.assertRaisesRegex(ValueError,'different source'):self.access.acquire('a'*32,request)
        with self.assertRaises(ValueError):self.access.release([])
        self.store.delete(record['id'])
        saved=self.access.save_reader('Original after deletion','a'*32)
        with self.store.open_evidence(saved['id']) as opened:self.assertEqual(opened.metadata,metadata)

    def test_http_crossing_release_before_registration_and_during_detachment(self):
        class Handler(serve_app.Handler):
            def log_message(self,*args):pass
            def calculation_ready(self):raise AssertionError('Readiness forbidden')
        server=serve_app.Server(('127.0.0.1',0),Handler)
        server.result_access=self.access
        worker=Thread(target=server.serve_forever);worker.start()
        def close():server.shutdown();worker.join(5);server.server_close()
        self.addCleanup(close)
        entered=Event();resume=Event();self.addCleanup(resume.set)
        def request(method,identifier,body=None):
            client=HTTPConnection(*server.server_address,timeout=10)
            try:
                data=json.dumps(body) if body is not None else None
                client.request(method,'/api/backtest-runs/'+identifier+'/reader',data,
                               {'Content-Type':'application/json'} if data else {})
                response=client.getresponse();return response.status,json.loads(response.read())
            finally:client.close()
        record,_,_=self.stored()
        captured=dict(source=dict(kind='saved',id=record['id']))
        original_acquire=self.access.acquire
        def delayed(identifier,body):
            entered.set()
            if not resume.wait(5):raise TimeoutError('Fixture delayed POST expired')
            return original_acquire(identifier,body)
        with patch.object(self.access,'acquire',delayed),ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(request,'POST','a'*32,captured);self.assertTrue(entered.wait(2))
            self.assertEqual(request('DELETE','a'*32)[0],200)
            resume.set();self.assertEqual(pending.result()[0],400)
        self.assertEqual(self.access.measurements()['readers'],0)
        entered.clear();resume.clear();original_open=self.store.open_evidence
        @contextmanager
        def detaching(identifier):
            with original_open(identifier) as opened:
                entered.set()
                if not resume.wait(5):raise TimeoutError('Fixture detach pause expired')
                yield opened
        with patch.object(self.store,'open_evidence',detaching),ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(request,'POST','b'*32,captured);self.assertTrue(entered.wait(2))
            self.assertEqual(request('DELETE','b'*32)[0],200)
            self.assertGreater(self.budget.measurements()['reserved_bytes'],0)
            resume.set();self.assertEqual(pending.result()[0],400)
        self.assertEqual(self.access.measurements()['readers'],0)
        self.assertEqual(self.budget.measurements()['reserved_bytes'],0)

    def test_server_shutdown_orders_result_drain_before_job_workspace(self):
        record,_,_=self.stored();self.acquire(record=record)
        entered=Event()
        class Owner:
            ready=lambda:True
            def calculate(owner,*args,**kwargs):
                entered.set()
                while True:
                    from backtest.runtime import backtest_control
                    backtest_control.checkpoint();time.sleep(.005)
            def close(owner):pass
        server=serve_app.Server(('127.0.0.1',0),serve_app.Handler)
        server.backtest_jobs=self.jobs;server.result_access=self.access
        server.calculations=Owner();self.jobs.calculations=server.calculations
        self.jobs.start('c'*32,'custom',{})
        self.assertTrue(entered.wait(2))
        closed=Event();errors=[]
        def shutdown():
            try:server.server_close();closed.set()
            except BaseException as error:errors.append(error)
        with self.access.read('a'*32) as (_,reader):
            thread=Thread(target=shutdown);thread.start()
            self.assertFalse(closed.wait(.05))
            self.assertTrue(self.jobs.closing);self.assertTrue(self.access.closing)
            self.assertFalse(self.jobs.evidence.closed)
            self.assertTrue(next(result_exports.csv(reader,'holdings',1)))
        thread.join(5);self.assertFalse(thread.is_alive());self.assertFalse(errors)
        self.assertTrue(closed.is_set());self.assertTrue(self.jobs.evidence.closed)
        self.assertEqual(self.jobs.snapshot('c'*32)['state'],'cancelled')


if __name__=='__main__':unittest.main()
