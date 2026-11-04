"""Actual native version-3 controls and CSVs on eight fictional companies."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_browser_fixture import BrowserStorage
from source_service_fixture import SPEC
from candidate_browser_fixture import CandidateService,FictionalWorkspace,WorkflowBrowser


@unittest.skipUnless(os.name=='nt','Actual native Chrome requires Windows.')
class EvidenceBrowserTests(unittest.TestCase):
    def test_complete_original_evidence_after_generation_replacement(self):
        with patch.dict(SPEC,companies=8),FictionalWorkspace() as workspace:
            service=CandidateService(workspace,'evidence').start()
            storage=workspace.own(BrowserStorage());browser=workspace.own(WorkflowBrowser(storage,service))
            downloads=[];timings=[];samples=[];exports={};service_closures=[];read_timings=[]
            def sample(stage):
                browser.clear_events()
                samples.append(dict(stage=stage,application=service.owner.tree_usage(),browser=browser.owned.tree_usage(),
                                    files=workspace.inventory(),browser_files=storage.inventory()))
            def navigate():
                browser.navigate('http://127.0.0.1:'+str(service.port)+'/')
                browser.wait("!!ResultArtifacts.forView('latest')")
                # Measure through JSON decoding. Retain only aggregate timings
                # per operation; attachment timing uses real completed files.
                browser.evaluate("""globalThis.readerStageTimings={};globalThis.stageFetch=fetch;fetch=async(...args)=>{
                  const began=performance.now(),path=String(args[0]),method=args[1]?.method||'GET';
                  const r=await stageFetch(...args),parse=r.json.bind(r);
                  const kind=method==='POST'&&path.endsWith('/reader')?'acquire':method==='POST'&&path==='/api/backtests'?'save':path.includes('/reader/page/')?'page-'+path.split('/')[6]:null;
                  if(kind)r.json=async()=>{const value=await parse(),seconds=(performance.now()-began)/1000,s=readerStageTimings[kind]||{count:0,total:0,min:Infinity,max:0};s.count++;s.total+=seconds;s.min=Math.min(s.min,seconds);s.max=Math.max(s.max,seconds);readerStageTimings[kind]=s;return value;};
                  return r;
                };""")
                if browser.evaluate("document.querySelector('#auto-run').checked"):browser.click('#auto-run')
                browser.click('details:has(#saved-list) summary')
            def open_saved(identifier,version):
                previous=browser.evaluate("ResultArtifacts.forView('custom')?.evidence?.id??null")
                began=time.perf_counter();browser.click('#saved-list [data-open="'+identifier+'"]')
                browser.wait("ResultArtifacts.forView('custom')?.version==="+str(version)+"&&ResultArtifacts.forView('custom')?.evidence?.id!=="+json.dumps(previous) if version==3 else "ResultArtifacts.forView('custom')?.version===2")
                browser.wait("document.querySelector('#saved-message').textContent.startsWith('Opened')")
                timings.append(dict(stage='library-open',version=version,seconds=time.perf_counter()-began))
            def take(selector):
                browser.clear_events();began=time.perf_counter();receipt,data=browser.download(selector)
                timings.append(dict(stage='complete-attachment',seconds=time.perf_counter()-began,bytes=len(data)))
                downloads.append(receipt);return receipt['name'],data
            def all_exports(record):
                files=[]
                if record['kind']=='random':files.append(take('#robustness-download'))
                for index in range(4 if record['kind']=='random' else 1):
                    if record['kind']=='random':
                        browser.fill('#robustness-trial',str(index));browser.click('#robustness-inspect')
                    browser.wait("document.querySelectorAll('#schedule-stock-body tr').length===5&&!document.querySelector('#schedule-attribution').textContent.includes('Reading')")
                    periods=browser.evaluate("[...document.querySelector('#schedule-period').options].map(o=>o.value)")
                    for period in periods:
                        browser.fill('#schedule-period',period)
                        browser.wait("document.querySelector('#schedule-attribution').textContent.includes('all 5 selected stocks')||document.querySelector('#schedule-attribution').textContent.includes('Top 5 stocks')")
                        self.assertEqual(browser.evaluate("document.querySelectorAll('#schedule-stock-body tr').length"),5)
                    files.extend([take('#schedule-download-returns'),take('#schedule-download-holdings')])
                return files
            def pinned_download(record,delete_source=False,cancel=False):
                pause=workspace.source/'data/evidence-export-pause';pause.touch()
                browser.clear_events();began=time.perf_counter()
                try:
                    browser.click('#schedule-download-holdings')
                    begin=browser.event('Browser.downloadWillBegin');guid=begin['guid']
                    sample('paused-attachment')
                    if cancel:
                        browser.command('Browser.cancelDownload',dict(guid=guid))
                        browser.event('Browser.downloadProgress',lambda p:p['guid']==guid and p['state']=='canceled')
                    open_saved(record['eager']['id'],2)
                    if delete_source:
                        browser.click('#saved-list [data-delete="'+record['saved']['id']+'"]')
                        browser.click('#saved-list [data-confirm="'+record['saved']['id']+'"]')
                        browser.wait("!document.querySelector('#saved-list [data-open=\""+record['saved']['id']+"\"]')")
                finally:pause.unlink(missing_ok=True)
                if not cancel:
                    progress=browser.event('Browser.downloadProgress',lambda p:p['guid']==guid and p['state'] in ('completed','canceled'))
                    self.assertEqual(progress['state'],'completed')
                    data=(storage.root/'downloads'/guid).read_bytes()
                    golden=record['golden']['holdings4' if record['kind']=='random' else 'holdings1']
                    observed=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),filename=begin['suggestedFilename'])
                    self.assertEqual(observed,golden)
                    downloads.append(dict(guid=guid,name=observed['filename'],bytes=observed['bytes'],sha256=observed['sha256']))
                timings.append(dict(stage='cancelled-attachment' if cancel else 'attachment-through-replacement-and-deletion',seconds=time.perf_counter()-began))
            try:
                browser.start();browser.viewport(1440,1000);navigate()
                fixture=json.loads((workspace.source/'data/evidence-fixture.json').read_text(encoding='utf-8'))
                original_inputs=workspace.input_inventory()
                pointer=workspace.source/'data/numerical/current.json'
                original_generation=json.loads(pointer.read_text())['current']
                for record in fixture:
                    # Recover the explicitly produced fresh Jobs result through the
                    # normal recovery owner. No calculation submission is changed.
                    run=dict(id=record['id'],mode=record['kind'],options=record['options'],phase='accepted',submitted=int(time.time()*1000),stop=False)
                    browser.evaluate('localStorage.clear();localStorage.setItem('+json.dumps('backtest-server-run:'+record['id'])+','+json.dumps(json.dumps(run))+');ScheduleView.resume()')
                    browser.wait("!ScheduleView.isRunning()&&ResultArtifacts.forView('custom')?.version===3&&ResultArtifacts.forView('custom').kind==="+json.dumps(record['kind']))
                    self.assertEqual(browser.evaluate("document.querySelector('#screen-error').textContent"),'')
                    self.assertEqual(browser.evaluate("ResultArtifacts.forView('custom').settings"),dict(mode=record['kind'],**record['options']))
                    fresh=all_exports(record)
                    # Keep an already received page response pending across an
                    # actual view replacement, even when its signal is aborted.
                    browser.evaluate("globalThis.evidenceFetch=fetch;globalThis.lateEvidence=[];fetch=async(...args)=>{const r=await evidenceFetch(...args);if(String(args[0]).includes('/reader/page/')){const text=await r.text();return new Promise(resolve=>lateEvidence.push(()=>resolve(new Response(text,{status:r.status,headers:r.headers}))));}return r;};document.querySelector('#schedule-period').dispatchEvent(new Event('change'))")
                    browser.wait('lateEvidence.length>0')
                    open_saved(record['eager']['id'],2);eager=all_exports(record)
                    browser.evaluate('fetch=evidenceFetch;lateEvidence.splice(0).forEach(resolve=>resolve())')
                    self.assertEqual(browser.evaluate("document.querySelector('#screen-error').textContent"),'')
                    self.assertEqual(fresh,eager)
                    open_saved(record['saved']['id'],3);exports[record['kind']]=all_exports(record)
                    self.assertEqual(exports[record['kind']],eager)
                    # A held StrategyDraft refuses restoration and releases the
                    # newly acquired reader without changing the displayed result.
                    current=browser.evaluate("ResultArtifacts.forView('custom').evidence.id")
                    browser.evaluate("globalThis.heldEvidenceDraft=StrategyDraft.beginQueuedEdit('fictional-held-draft')")
                    browser.click('#saved-list [data-open="'+record['saved']['id']+'"]')
                    browser.wait("document.querySelector('#saved-message').textContent.includes('Save or cancel')")
                    self.assertEqual(browser.evaluate("ResultArtifacts.forView('custom').evidence.id"),current)
                    browser.evaluate('heldEvidenceDraft.end()')
                    # Save from the acquired capability, then delete its original
                    # source while this display and complete exports stay usable.
                    browser.fill('#saved-name',record['kind']+' reader copy');browser.click('#save-backtest')
                    browser.wait("document.querySelector('#saved-message').textContent.startsWith('Saved')")
                    pinned_download(record,delete_source=True)
                    listing=browser.evaluate("fetch('/api/backtests').then(r=>r.json())")
                    copy=next(row for row in listing['records'] if row['name']==record['kind']+' reader copy')
                    open_saved(copy['id'],3)
                    self.assertEqual(all_exports(record),eager)
                    pinned_download(record,cancel=True)
                    open_saved(copy['id'],3)
                    sample(record['kind']+'-source-deleted')
                # Open the durable queue through its ordinary UI owner.
                browser.click('#queue-list [data-action="open"][data-id="'+ 'c'*32+'"]')
                browser.wait("document.querySelector('#queue-status').textContent.startsWith('Opened')")
                self.assertEqual(browser.evaluate("ResultArtifacts.forView('custom').version"),3)
                self.assertEqual(all_exports(fixture[0]),exports['random'])
                sample('queue-open')
                read_timings.append(dict(service='candidate',operations=browser.evaluate('readerStageTimings')))
                service.close();service_closures.append(service.owner.closure())
                for path in (workspace.source/'raw/px').glob('*.json'):
                    value=json.loads(path.read_text())
                    for row in value['div']:
                        if row['date']>='2015-02-01':row['adjClose']*=1.2
                    path.write_text(json.dumps(value),encoding='utf-8')
                replacement_inputs=workspace.input_inventory();self.assertNotEqual(original_inputs,replacement_inputs)
                # Real candidate preparation publishes a different numerical
                # generation. Its saved evidence remains unchanged.
                service=CandidateService(workspace,'workflow').start();service.close();service_closures.append(service.owner.closure())
                replacement_generation=json.loads(pointer.read_text())['current']
                self.assertNotEqual(original_generation,replacement_generation)
                service=CandidateService(workspace,'ordinary-evidence').start();browser.service=service;storage.owners.append(service)
                navigate()
                listing=browser.evaluate("fetch('/api/backtests').then(r=>r.json())")
                for record in fixture:
                    saved=next(row for row in listing['records'] if row['name']==record['kind']+' reader copy')
                    open_saved(saved['id'],3)
                    self.assertEqual(all_exports(record),exports[record['kind']])
                    self.assertEqual(browser.evaluate("ResultArtifacts.forView('custom').settings"),record['metadata']['settings'])
                    sample(record['kind']+'-ordinary-after-replacement')
                self.assertEqual(browser.errors,[])
                read_timings.append(dict(service='ordinary',operations=browser.evaluate('readerStageTimings')))
                for width,height,name in [(1440,1000,'evidence-desktop'),(390,844,'evidence-mobile')]:
                    browser.viewport(width,height);browser.evaluate("document.querySelector('#schedule-results').scrollIntoView({block:'start',behavior:'instant'})")
                    self.assertTrue(browser.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    browser.screenshot(name)
                from importlib.metadata import version
                import sqlite3
                receipt=dict(check='native-evidence-browser',fixture=fixture,original_inputs=original_inputs,replacement_inputs=replacement_inputs,
                             original_generation=original_generation,replacement_generation=replacement_generation,
                             sources=workspace.sources,versions=dict(browser=browser.identity,python=sys.version,sqlite=sqlite3.sqlite_version,
                                numerical={name:version(name) for name in ('numpy','numba','llvmlite')}),timings=timings,samples=samples,downloads=downloads,
                             previous_service_closures=service_closures,read_timings=read_timings,
                             maximum_absolute=max(row['maximum_absolute'] for row in fixture),maximum_relative=max(row['maximum_relative'] for row in fixture),
                             scope='Fictional eight-company pilot; ordinary reopen forbids calculation, readiness and financial access. No populated-universe capacity claim.')
                (storage.root/'evidence/reader-pilot.json').write_text(json.dumps(receipt,allow_nan=False),encoding='utf-8')
                print(json.dumps(receipt),flush=True)
            finally:
                browser.close();service.close()
                print(json.dumps(dict(check='native-evidence-closure',artifacts=storage.preserve(),application=service.owner.closure(),browser=browser.owned.closure() if browser.owned else None)),flush=True)


if __name__=='__main__':unittest.main()
