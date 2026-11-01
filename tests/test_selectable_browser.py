"""Normal app selector against fictional saved inputs; actual native browser."""
import csv
import io
import json
import os
from http.client import HTTPConnection
import time
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from candidate_browser_fixture import FictionalWorkspace,CandidateService
from test_candidate_browser import WorkflowBrowser
from bench_native_browser import BrowserStorage
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.engines.numerical.portfolio import compare_results


@unittest.skipUnless(os.name=='nt','Actual native Chrome requires Windows.')
class SelectableBrowserTests(unittest.TestCase):
    def test_normal_selector_complete_workflow(self):
        with FictionalWorkspace() as workspace:
            service=CandidateService(workspace,'selectable-workflow').start()
            # Normal startup must not create numerical artifacts. Prepare explicitly
            # before starting Chrome so its share cannot delay setup admission.
            self.assertFalse((workspace.source/'data/numerical/current.json').exists())
            def api(path,payload=None):
                client=HTTPConnection('127.0.0.1',service.port,timeout=10)
                try:
                    client.request('POST' if payload is not None else 'GET',path,json.dumps(payload) if payload is not None else None)
                    response=client.getresponse();value=json.loads(response.read())
                    self.assertLess(response.status,400,value);return value
                finally:client.close()
            api('/api/data/prepare',dict(scope='symbols',symbols='ZZ000',start='2015-01-01',end='2016-12-30',datasets=['prices']))
            deadline=time.monotonic()+120;last=None;timeouts=0
            while True:
                try:last=api('/api/data/status')
                except TimeoutError:
                    timeouts+=1
                    if time.monotonic()>deadline:self.fail('Optional preparation status timed out: '+json.dumps(dict(last=last,timeouts=timeouts)))
                    continue
                print(json.dumps(dict(check='optional preparation status',message=last['job']['message'],running=last['job']['running'],candidate=last.get('candidate'),timeouts=timeouts)),flush=True)
                if last['job'].get('error'):self.fail(last['job']['error'])
                if not last['job']['running']:
                    self.assertEqual(last['candidate']['state'],'current',last);break
                if time.monotonic()>deadline:self.fail('Optional preparation did not finish: '+json.dumps(last))
                time.sleep(.25)
            storage=workspace.own(BrowserStorage());browser=workspace.own(WorkflowBrowser(storage,service,renderer_processes=1))
            exports={};snapshots=[];receipts=[]
            try:
                browser.start();browser.viewport(1440,1000)
                browser.navigate('http://127.0.0.1:'+str(service.port)+'/')
                browser.wait("!!ResultArtifacts.forView('latest')")
                self.assertEqual(browser.evaluate("document.querySelector('#backtest-engine').value"),'original')
                browser.click('#auto-run');browser.click('#mode-backtest');browser.fill('#schedule-kind','custom')
                for selector,value in [('#trade-start','2015-01-02'),('#trade-end','2015-03-31'),('#rank-to','3'),('#rebalance-months','12')]:browser.fill(selector,value)
                job_samples=[]
                def sample_job():
                    import ctypes
                    from ctypes import wintypes as w
                    class Accounting(ctypes.Structure):
                        _fields_=[(k,ctypes.c_int64) for k in ('user','kernel','period_user','period_kernel')]+[(k,w.DWORD) for k in ('faults','total','active','terminated')]
                    account=Accounting();limits=service.owner._extended_limits_type()
                    kernel=service.owner.kernel
                    available=bool(kernel.QueryInformationJobObject(None,1,ctypes.byref(account),ctypes.sizeof(account),None)
                        and kernel.QueryInformationJobObject(None,9,ctypes.byref(limits),ctypes.sizeof(limits),None))
                    row=(dict(scope='immediate caller Job, possibly a venv redirector Job',active=account.active,total=account.total,terminated=account.terminated,
                              process_limit=limits.basic.active_limit,flags=limits.basic.flags)
                         if available else dict(available=False,winerror=ctypes.get_last_error()))
                    job_samples.append(row)
                    (storage.root/'evidence/native-job-samples.json').write_text(json.dumps(job_samples),encoding='utf8')
                def run():
                    sample_job()
                    previous=browser.evaluate("ResultArtifacts.forView('custom')?.captured_at??null")
                    browser.click('#run-screen')
                    browser.wait("!document.querySelector('#run-screen').disabled&&(document.querySelector('#screen-error').textContent||ResultArtifacts.forView('custom')?.captured_at!=="+json.dumps(previous)+")")
                    self.assertEqual(browser.evaluate("document.querySelector('#screen-error').textContent"),'')
                    return browser.evaluate("ResultArtifacts.forView('custom')")
                def download(snapshot):
                    contents=[]
                    def take(selector,count):
                        receipt,body=browser.download(selector);receipts.append(receipt)
                        rows=list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))));self.assertEqual(len(rows),count)
                        self.assertTrue(all(row['engine']==snapshot['result']['producer']['engine'] for row in rows))
                        contents.append(body)
                    result=snapshot['result']
                    if snapshot['kind']=='random':take('#robustness-download',len(result['trials']));trials=result['trial_results']
                    else:trials=[result]
                    for i,trial in enumerate(trials):
                        if snapshot['kind']=='random':browser.fill('#robustness-trial',str(i));browser.click('#robustness-inspect')
                        take('#schedule-download-returns',len(trial['periods']))
                        take('#schedule-download-holdings',sum(len(p['holdings']) for p in trial['periods']))
                    return contents
                browser.click('#calendar-custom');browser.fill('#calendar-unit','week');browser.fill('#calendar-count','2')
                original=run();snapshots.append(original);exports[0]=download(original)
                self.assertEqual(original['settings']['calendar']['interval'],dict(unit='week',count=2))
                browser.fill('#backtest-engine','experimental');experimental=run();snapshots.append(experimental);exports[1]=download(experimental)
                a=dict(original['result']);b=dict(experimental['result']);a.pop('producer');b.pop('producer')
                self.assertTrue(compare_results(a,b)['exact'])
                browser.click('.random-advanced summary')
                for engine in ('original','experimental'):
                    browser.fill('#backtest-engine',engine);browser.fill('#date-testing','random');browser.fill('#random-trials','2')
                    if not browser.evaluate("document.querySelector('#repeat-random').checked"):browser.click('#repeat-random')
                    browser.fill('#random-seed','42');snapshot=run();snapshots.append(snapshot);exports[len(snapshots)-1]=download(snapshot)
                self.assertEqual(snapshots[2]['result']['configuration'],snapshots[3]['result']['configuration'])
                self.assertEqual(snapshots[2]['result']['distributions'],snapshots[3]['result']['distributions'])
                for a,b in zip(snapshots[2]['result']['trial_results'],snapshots[3]['result']['trial_results']):self.assertTrue(compare_results(a,b)['exact'])
                ids=[]
                for i,snapshot in enumerate(snapshots):
                    value=browser.evaluate("(async()=>{const r=await fetch('/api/backtests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify("+json.dumps(dict(name='Selector '+str(i),snapshot=snapshot))+")});if(!r.ok)throw Error('Save failed');return r.json()})()")
                    ids.append(value['id'])
                browser.click('details:has(#saved-list) summary');browser.click('#refresh-backtests')
                for i,identifier in enumerate(ids):
                    browser.wait("!!document.querySelector('#saved-list [data-open=\""+identifier+"\"]')")
                    browser.click('#saved-list [data-open="'+identifier+'"]')
                    browser.wait("ResultArtifacts.forView('custom')?.captured_at==="+json.dumps(snapshots[i]['captured_at']))
                    self.assertEqual(browser.evaluate("document.querySelector('#backtest-engine').value"),snapshots[i]['settings']['engine'])
                    self.assertEqual(download(snapshots[i]),exports[i])
                # Replay retains experimental even if the live form is Original.
                browser.fill('#backtest-engine','original');browser.click('#robustness-replay')
                browser.wait("!document.querySelector('#run-screen').disabled&&ResultArtifacts.forView('custom').captured_at!=="+json.dumps(snapshots[3]['captured_at']))
                self.assertEqual(browser.evaluate("ResultArtifacts.forView('custom').result.producer.engine"),'experimental')
                # A submitted job survives page reconnection with its own choice.
                browser.fill('#backtest-engine','experimental');browser.click('#run-screen')
                browser.navigate('http://127.0.0.1:'+str(service.port)+'/')
                browser.wait("ResultArtifacts.forView('custom')?.result.producer.engine==='experimental'&&!document.querySelector('#run-screen').disabled")
                browser.click('#run-screen');browser.wait("!document.querySelector('#stop-backtest').hidden");browser.click('#stop-backtest')
                browser.wait("!document.querySelector('#run-screen').disabled")
                self.assertIn('stopped',browser.evaluate("document.querySelector('#schedule-message').textContent"))
                browser.fill('#backtest-engine','original');browser.fill('#date-testing','single');returned=run()
                self.assertEqual(returned['result']['producer']['engine'],'original')
                browser.viewport(390,844)
                self.assertFalse(browser.evaluate('document.documentElement.scrollWidth>innerWidth'))
                self.assertEqual(browser.errors,[])
                (storage.root/'evidence/selector-snapshots.json').write_text(json.dumps(snapshots,allow_nan=False),encoding='utf-8')
                print(json.dumps(dict(check='CB-18 both-engine weekly selector',snapshots=4,seed=42,trials=2,financial_differences=0,downloads=receipts,records=ids,reconnected=True,stop=True,returned='original')),flush=True)
            except BaseException:
                # Preserve the existing redacted development log before the
                # fictional workspace closes, so native failures stay diagnosable.
                logs=storage.root/'evidence'
                for log in (workspace.source/'data/logs').glob('*.log'):
                    (logs/('server-'+log.name)).write_bytes(log.read_bytes())
                for record in (workspace.source/'data').glob('_fixture-transport-*.json'):
                    (logs/record.name).write_bytes(record.read_bytes())
                try:
                    state=browser.evaluate("({error:document.querySelector('#screen-error')?.textContent,message:document.querySelector('#schedule-message')?.textContent,progress:document.querySelector('#schedule-progress-detail')?.textContent,engine:document.querySelector('#backtest-engine')?.value,producer:ResultArtifacts.forView('custom')?.result.producer})")
                    print(json.dumps(dict(check='selector failure state',state=state)),flush=True)
                    (storage.root/'evidence/failure-state.json').write_text(json.dumps(state),encoding='utf-8')
                except Exception:pass
                raise
            finally:
                browser.close();service.close()
                print(json.dumps(dict(check='CB-18 selector closure',browser_artifacts=storage.preserve(),service=service.owner.closure(),browser=browser.owned.closure() if browser.owned else None)),flush=True)


if __name__=='__main__':unittest.main()
