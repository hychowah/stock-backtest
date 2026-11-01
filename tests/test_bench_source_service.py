"""Actual preparation/build/freshness and HTTP on fictional private roots only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.client import RemoteDisconnected
import json
import os
from pathlib import Path
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'tools'),str(ROOT/'scripts'),str(ROOT/'website')]
from bench_source_service_fixture import FictionalWorkspace,SourceService,sha,write,MIB
from bench_comparison import ComparisonError
from bench_methods import clean
from bench_execution_observation import CurrentObservation
import bench_execution_observation as observation
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import cache_access as cache_access
import runtime_access
from backtest.engines.original import schedules as schedules


class SourceServiceTests(unittest.TestCase):
    def setUp(self):
        self.workspace=FictionalWorkspace()
        self.addCleanup(self.workspace.close)

    def test_current_schema8_capture_rejects_without_mutation(self):
        # Ordinary current preparation remains schema8. The retained capture
        # adapter admits only its historical protocol7 and cannot relabel it.
        service=self.service()
        self.assertEqual(self.expected(service)['metadata']['version'],8)
        service.close()
        def unchanged_inputs():
            paths=[p for p in (self.workspace.source/'raw').rglob('*') if p.is_file()]
            paths+=list((self.workspace.source/'data').glob('*.sqlite'))
            paths+=[self.workspace.source/'results/summary-exits.txt']
            paths+=[self.workspace.source/name for name in self.workspace.sources]
            return {p.relative_to(self.workspace.source).as_posix():sha(p) for p in paths}
        before=unchanged_inputs()
        from bench_capture_offline import OfflineCaptureError
        with self.assertRaises(OfflineCaptureError) as error:
            self.workspace.capture_prepared()
        self.assertEqual(error.exception.reason,'unsupported')
        self.assertEqual(unchanged_inputs(),before)
        self.assertFalse((self.workspace.source/'tmp/combined-capture').exists())
        self.workspace.inventory()

    def service(self,**scenario):
        service=SourceService(self.workspace,**scenario)
        self.addCleanup(service.close)
        return service.start()

    def expected(self,service):return json.loads((service.control/'expected.json').read_bytes())

    def options(self):return dict(start='2015-01-01',end='2016-12-30',months=12,pool='cached',rank_to=4)

    def provider(self,service):
        x=self.expected(service);w=self.workspace
        request=dict(observation_root=str(w.source),observation_mode='coordinated',sources=w.sources,
            captured_freshness=dict(inputs=x['signature'],daily_inputs=x['daily_metadata']['daily_inputs']),
            captured_metadata=dict(research=x['metadata'],daily=x['daily_metadata']),read_only_observation=True)
        return CurrentObservation(request,schedules,seconds=15.)

    def report(self,check,**data):
        print(json.dumps(dict(check=check,platform=sys.platform,**data)),flush=True)

    def test_cold_preparation_unchanged_reuse_and_complete_http_financial_workflows(self):
        w=self.workspace
        started=time.monotonic();s=self.service(oracle=True)
        x=self.expected(s);baseline=x['baseline'];oracle=json.loads((s.control/'oracle.json').read_bytes())
        self.assertEqual([y['year'] for y in baseline['years']],list(range(1996,2027)))
        self.assertEqual({len(y['holdings']) for y in baseline['years']},{50})
        self.assertEqual(x['metadata']['baseline_result'],baseline)
        self.assertEqual(x['metadata']['baseline_report_sha'],sha(w.source/'results/summary-exits.txt'))
        history=list((w.source/'results/baseline-history').iterdir());self.assertEqual(len(history),1)
        self.assertEqual((history[0]/'previous-report.txt').read_text(),'Fictional bootstrap only.\nThrough 2026-10-21\n')
        page=s.request('GET','/');panel=s.request('GET','/data.html')
        self.assertIn(b'Fictional Company',page);self.assertIn(b'id="screening-data"',page)
        self.assertNotIn(b'__DATA_SCRIPT__',panel)
        fixed=s.request('POST','/api/schedule',self.options())
        self.assertEqual(clean(fixed),clean(oracle['fixed']))
        result=s.request('POST','/api/robustness',dict(self.options(),trials=5,seed=42))[-1]['result']
        self.assertEqual(clean(result),clean(oracle['random']))
        self.assertGreater(result['execution']['missing_books'],0)
        repeated=s.request('POST','/api/robustness',dict(self.options(),trials=5,seed=42))[-1]['result']
        self.assertEqual(clean(result),clean(repeated));self.assertEqual(repeated['execution']['missing_books'],0)
        inspected=s.request('POST','/api/schedule',dict(self.options(),dates=result['configuration']['samples'][2]))
        self.assertEqual(clean(inspected),clean(oracle['inspected']))
        report=s.job('check',dict(scope='cached',start='2015-01-01',end='2016-12-30'))['report']
        self.assertFalse(report['api_key_present']);self.assertFalse(report['issues'])
        self.assertTrue(all(not names for names in report['missing_ratio_inputs'].values()))
        self.assertEqual({d['state'] for d in report['derived']},{'current','saved'})
        before={str(p.relative_to(w.source)):sha(p) for p in (w.source/'data/research.sqlite',
            w.source/'data/schedules.sqlite',w.source/'website/local/.build-state.json',w.source/'results/summary-exits.txt')}
        s.close();s=s.restart();self.addCleanup(s.close)
        self.assertEqual(before,{name:sha(w.source/name) for name in before})
        self.assertEqual(w.inputs,w.input_inventory())
        s.close()
        self.report('source_preparation_http',seconds=time.monotonic()-started,years=31,holdings=1550,
            inventory=w.inventory(),trials=5,cached_books=repeated['execution']['reused_books'],
            complete_page_bytes=len(page),complete_panel_bytes=len(panel),financial_agreement='exact',
            maximum_absolute=0.,maximum_relative=0.,closure=s.owned.closure())

    def test_actual_input_edit_rejects_then_panel_rebuild_preserves_report_history(self):
        s=self.service();w=self.workspace;provider=self.provider(s)
        self.assertEqual(provider.current(),self.expected(s)['signature'])
        old_report=(w.source/'results/summary-exits.txt').read_bytes()
        old_baseline=self.expected(s)['baseline']
        metrics=w.source/'raw/metrics.jsonl'
        rows=[json.loads(line) for line in metrics.read_text().splitlines()]
        rows[0]['rows'][-1]['marketCap']+=10e6
        metrics.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
        with self.assertRaisesRegex(ComparisonError,'stale'):provider.current()
        failed=s.request('POST','/api/schedule',self.options(),status=400)
        self.assertIn('changed',failed['error'].lower())
        self.assertIn(b'<html',s.request('GET','/data.html').lower())
        self.assertIn(b'Fictional Company',s.request('GET','/'))
        report=s.job('rebuild',dict(scope='symbols',symbols='ZZ000',start='2015-01-01',end='2016-12-30'))['report']
        self.assertEqual(report['baseline']['summary']['through'],'2026-10-21')
        revision=w.source/'results'/report['baseline']['summary']['audit']
        self.assertEqual((revision.parent/'previous-report.txt').read_bytes(),old_report)
        self.assertEqual(json.loads((revision.parent/'previous-snapshot.json').read_bytes()),old_baseline)
        self.assertTrue(s.request('POST','/api/schedule',self.options())['periods'])
        s.close();s=s.restart();self.addCleanup(s.close)
        self.assertEqual(self.provider(s).current(),self.expected(s)['signature'])
        s.close();self.report('source_edit_rebuild',history_preserved=True,inventory=w.inventory())

    def test_latest_only_price_advance_keeps_full_historical_baseline(self):
        s=self.service();w=self.workspace;before=self.expected(s)['baseline']
        report=(w.source/'results/summary-exits.txt').read_bytes()
        history={p.name for p in (w.source/'results/baseline-history').iterdir()}
        for path in [w.source/'raw/spy-div.json',*(w.source/'raw/px').glob('*.json')]:
            payload=json.loads(path.read_bytes());rows=payload if isinstance(payload,list) else payload['div']
            rows.append(dict(date='2026-10-22',adjClose=rows[-1]['adjClose']*1.01));write(path,payload)
        s.job('rebuild',dict(scope='symbols',symbols='ZZ000',start='2015-01-01',end='2016-12-30'))
        s.close();s=s.restart();self.addCleanup(s.close)
        after=self.expected(s)
        self.assertEqual(after['baseline'],before)
        self.assertEqual((w.source/'results/summary-exits.txt').read_bytes(),report)
        self.assertEqual({p.name for p in (w.source/'results/baseline-history').iterdir()},history)
        self.assertEqual({row['price_date'] for row in after['latest']},{'2026-10-22'})
        s.close();self.report('source_latest_advance',historical_unchanged=True,latest='2026-10-22',inventory=w.inventory())

    def test_rebuild_serves_page_panel_and_queues_financial_work_until_cache_release(self):
        s=self.service(hold_rebuild=True)
        s.request('POST','/api/data/rebuild',{},status=202);s.wait('rebuild_held')
        with ThreadPoolExecutor(max_workers=1) as clients:
            pending=clients.submit(s.request,'POST','/api/schedule',self.options())
            self.assertIn(b'Fictional Company',s.request('GET','/'))
            self.assertIn(b'<html',s.request('GET','/data.html').lower())
            self.assertTrue(s.request('GET','/api/data/status')['job']['running'])
            time.sleep(.05);self.assertFalse(pending.done())
            (s.control/'rebuild_held.release').touch()
            self.assertTrue(pending.result(timeout=60)['periods'])
        deadline=time.monotonic()+60
        while s.request('GET','/api/data/status')['job']['running']:
            self.assertLess(time.monotonic(),deadline);time.sleep(.01)
        s.close();self.report('source_rebuild_availability',static_available=True,financial_waited=True,closure=s.owned.closure())

    def test_current_observation_yields_to_real_service_within_two_seconds_and_shutdown_waits(self):
        s=self.service(hold_request=True);provider=self.provider(s)
        access=cache_access.WorkspaceAccess(self.workspace.source/'data/website-data-0.lock',read_only=True)
        original=observation.signature;arrivals=[]
        with ThreadPoolExecutor(max_workers=2) as clients:
            def scanning(research,checkpoint):
                def interrupt():
                    if not arrivals:
                        arrivals.append(clients.submit(s.request,'POST','/api/schedule',self.options()))
                        deadline=time.monotonic()+5
                        while not access.live_pending():
                            self.assertLess(time.monotonic(),deadline);time.sleep(.005)
                        arrivals.append(time.monotonic())
                    checkpoint()
                return original(research,interrupt)
            with patch.object(observation,'signature',side_effect=scanning):
                with self.assertRaisesRegex(ComparisonError,'busy'):provider.current()
            acquired=s.wait('acquired');handoff=acquired['at']-arrivals[1]
            self.assertGreaterEqual(handoff,0.);self.assertLess(handoff,2.)
            s.wait('request_held')
            closing_service=clients.submit(s.close)
            s.wait('admission_closed');self.assertFalse(closing_service.done())
            with self.assertRaises(RuntimeError):
                with runtime_access.ownership(self.workspace.source,exclusive=True,timeout=0):pass
            (s.control/'request_held.release').touch()
            with self.assertRaises(RemoteDisconnected):arrivals[0].result(timeout=60)
            closing_service.result(timeout=15)
        self.assertTrue(s.closed)
        with runtime_access.ownership(self.workspace.source,exclusive=True,timeout=0):pass
        self.report('source_priority_shutdown',handoff_seconds=handoff,bound=2.,closure=s.owned.closure())

    def test_committed_stream_disconnect_and_fresh_interpreter_retry(self):
        s=self.service(disconnect=True)
        request=dict(self.options(),trials=5,seed=42)
        with s.connection() as client:
            client.request('POST','/api/robustness',json.dumps(request),{'Content-Type':'application/json'})
            response=client.getresponse();self.assertEqual(response.status,200)
            self.assertEqual(json.loads(response.readline())['type'],'configuration')
            s.wait('trial_committed')
            try:
                transport=response.fp.raw._sock
                transport.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,struct.pack('ii',1,0) if os.name!='nt' else struct.pack('hh',1,0))
                transport.close();response.close()
            finally:
                (s.control/'trial_committed.release').touch()
        s.wait('released')
        with closing(sqlite3.connect(self.workspace.source/'data/schedules.sqlite')) as db:
            saved=db.execute('SELECT count(*) FROM period_pools').fetchone()[0]
        self.assertEqual(saved,2)
        s.close();s=s.restart();self.addCleanup(s.close)
        result=s.request('POST','/api/robustness',request)[-1]['result']
        self.assertEqual(result['completed'],5);self.assertEqual(result['execution']['reused_books'],saved)
        self.assertGreater(result['execution']['missing_books'],0)
        s.close();self.report('source_stream_retry',saved_pools=saved,completed=5,closure=s.owned.closure())

    def test_pending_source_startup_failure_and_close_retry_keep_ownership(self):
        w=self.workspace;journal=w.source/'data/deployment.pending.json';journal.write_text('{}')
        s=SourceService(w);self.addCleanup(s.close)
        with self.assertRaises(AssertionError):s.start()
        self.assertTrue(s.closed);self.assertFalse((w.source/'data/research.sqlite').exists())
        journal.unlink()
        failed=SourceService(w,fail_start=True);self.addCleanup(failed.close)
        with self.assertRaises(AssertionError):failed.start()
        self.assertTrue(failed.closed)
        s=self.service()
        with patch.object(s.owned,'close',side_effect=OSError('fixture handle-close failure')):
            with self.assertRaises(OSError):s.close()
        self.assertFalse(s.closed)
        s.close();self.assertTrue(s.closed)
        self.report('source_failures_retry',pending_rejected=True,start_failure_closed=True,closure=s.owned.closure())

    def test_full_source_fixture_does_not_silently_expand_original_capture_envelope(self):
        s=self.service();w=self.workspace;s.close()
        capture=w.root/'oversize-capture';capture.mkdir()
        import shutil
        for name in ('research.sqlite','schedules.sqlite'):
            shutil.copy2(w.source/'data'/name,capture/name)
        shutil.copy2(w.source/'results/summary-exits.txt',capture/'report.txt')
        (capture/'capture.json').write_text('{}')
        import bench_execution_inputs as inputs
        owner=inputs.CapturedWorkspace(capture,w.source,w.root/'capture-rejection')
        total=sum((capture/name).stat().st_size for name in ('research.sqlite','schedules.sqlite'))
        self.assertGreater(total,inputs.MAX_DATABASE_BYTES)
        with self.assertRaises(inputs.ExecutionInputError) as caught:
            with owner:pass
        self.assertEqual(caught.exception.reason,'limit')
        self.assertEqual(inputs.MAX_DATABASE_BYTES,32*MIB)
        self.report('source_capture_bound',database_bytes=total,original_limit=32*MIB,
            result='limit',combined_measured_attachment='unqualified')


class DependencyGuardTests(unittest.TestCase):
    def test_owned_SQLite_and_memory_succeed_external_paths_and_URIs_reject(self):
        self.check_guard(inherited=False)

    def test_build_child_inherits_the_same_SQLite_guard_from_sitecustomize(self):
        self.check_guard(inherited=True)

    def check_guard(self,*,inherited):
        from bench_source_service_fixture import guarded_environment
        with tempfile.TemporaryDirectory(prefix='cb02-guard-owned-') as owned, \
                tempfile.TemporaryDirectory(prefix='cb02-guard-external-') as external:
            source=Path(owned)/'application';source.mkdir()
            database=Path(external)/'external.sqlite'
            with closing(sqlite3.connect(database)) as db:db.execute('CREATE TABLE sentinel(value)')
            before=sha(database)
            code='''import sys,json,sqlite3
from pathlib import Path
source=Path(sys.argv[1]);external=Path(sys.argv[2])
if sys.argv[3]=='direct':
 from bench_source_service_fixture import dependency_guard
 dependency_guard(source)
for value,uri in [(str(source/'owned.sqlite'),False),(':memory:',False),((source/'owned.sqlite').as_uri()+'?mode=ro',True)]:
 db=sqlite3.connect(value,uri=uri);db.close()
rejected=[]
for value,uri in [(str(external),False),(external.as_uri()+'?mode=ro',True),('file://foreign/unknown.sqlite',True),('file:'+str(source/'owned.sqlite')+'?vfs=unknown',True),('',False)]:
 try:sqlite3.connect(value,uri=uri)
 except AssertionError:rejected.append(value)
 else:raise AssertionError('Unexpected SQLite access')
print(json.dumps(dict(owned=True,memory=True,rejected=len(rejected),mode=sys.argv[3])))
'''
            env=guarded_environment(source) if inherited else dict(os.environ,
                PYTHONPATH=os.pathsep.join([str(ROOT/'tests'),str(ROOT/'tools')]))
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',code,
                str(source),str(database),'inherited' if inherited else 'direct'],env=env,
                capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout)['rejected'],5)
            self.assertEqual(before,sha(database))
            self.assertTrue((source/'owned.sqlite').is_file())


if __name__=='__main__':unittest.main()
