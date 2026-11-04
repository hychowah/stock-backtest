"""Actual native controls and downloads against isolated numerical execution."""
import csv
import io
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_browser_fixture import BrowserStorage
from candidate_browser_fixture import FictionalWorkspace,CandidateService,WorkflowBrowser


@unittest.skipUnless(os.name=='nt','Actual native Chrome requires Windows.')
class CandidateBrowserTests(unittest.TestCase):
    def test_original_snapshots_and_csvs_after_real_generation_replacement(self):
        # Durable snapshots retain completed evidence across input replacement.
        # Opening/exporting neither calculates nor checks against current inputs.
        with FictionalWorkspace() as workspace:
            service=CandidateService(workspace).start()
            storage=workspace.own(BrowserStorage())
            browser=workspace.own(WorkflowBrowser(storage,service))
            receipts=[];snapshots=[];exports={}
            try:
                browser.start();browser.viewport(1440,1000)
                def navigate():
                    browser.navigate('http://127.0.0.1:'+str(service.port)+'/')
                    browser.wait("!!ResultArtifacts.forView('latest')")
                def run():
                    previous=browser.evaluate("ResultArtifacts.forView('custom')?.captured_at??null")
                    browser.click('#run-screen')
                    browser.wait("!document.querySelector('#run-screen').disabled&&ResultArtifacts.forView('custom')?.captured_at!=="+json.dumps(previous))
                    self.assertEqual(browser.evaluate("document.querySelector('#screen-error').textContent"),'')
                    return browser.evaluate("ResultArtifacts.forView('custom')")
                def save(name,snapshot):
                    row=browser.evaluate("(async()=>{const r=await fetch('/api/backtests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify("+
                        json.dumps(dict(name=name,snapshot=snapshot))+ ")});if(!r.ok)throw Error('Save failed');return await r.json();})()")
                    return row['id']
                def open_saved(identifier,snapshot):
                    browser.click('#refresh-backtests')
                    browser.wait("!!document.querySelector('#saved-list [data-open=\""+identifier+"\"]')")
                    browser.click('#saved-list [data-open="'+identifier+'"]')
                    browser.wait("ResultArtifacts.forView('custom')?.captured_at==="+json.dumps(snapshot['captured_at']))
                    expected=browser.evaluate('ResultArtifacts.decode('+json.dumps(snapshot)+')')
                    self.assertEqual(browser.evaluate("ResultArtifacts.forView('custom')"),expected)
                def download_all(identifier,snapshot):
                    contents=[]
                    def take(selector,rows):
                        receipt,content=browser.download(selector);receipts.append(receipt)
                        self.assertEqual(len(list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))),len(rows))
                        contents.append(content)
                    result=snapshot['result']
                    if snapshot['kind']=='random':
                        take('#robustness-download',result['trials'])
                        trials=result['trial_results']
                    else:trials=[result]
                    for index,trial in enumerate(trials):
                        if snapshot['kind']=='random':
                            browser.fill('#robustness-trial',str(index));browser.click('#robustness-inspect')
                        take('#schedule-download-returns',trial['periods'])
                        take('#schedule-download-holdings',[h for p in trial['periods'] for h in p['holdings']])
                    return contents
                navigate();browser.click('#auto-run');browser.click('#mode-backtest');browser.fill('#schedule-kind','custom')
                # Saved records retain this choice, so replay stays numerical.
                browser.fill('#backtest-engine','experimental')
                for selector,value in [('#trade-start','2015-01-02'),('#trade-end','2015-02-27'),('#rank-to','3'),('#date-testing','random'),('#random-trials','3')]:browser.fill(selector,value)
                browser.wait("!document.querySelector('#calendar-controls').hidden");browser.click('#calendar-custom')
                candidate=run();original_result=candidate['result']
                self.assertEqual((original_result['completed'],original_result['valid']),(3,3))
                candidate['catalog']['metrics'][candidate['settings']['metric']]['label']='Original candidate metric'
                candidate['presentation']['periodLabel']='Original candidate period'
                snapshots.append(('Candidate original',candidate))
                browser.click('#calendar-custom');browser.fill('#date-testing','single');browser.fill('#rebalance-months','1')
                monthly=run()
                for version in (1,2):
                    old=json.loads(json.dumps(monthly));old['version']=version
                    old['captured_at']='2026-10-29T00:00:0'+str(version)+'Z'
                    old['catalog']['metrics'][old['settings']['metric']]['label']='Original monthly metric v'+str(version)
                    if version==1:
                        old['context']=dict(pill='Original monthly period v1',notes=[]);old.pop('presentation')
                    else:old['presentation']['periodLabel']='Original monthly period v2'
                    snapshots.append(('Old monthly v'+str(version),old))
                ids=[save(name,snapshot) for name,snapshot in snapshots]
                browser.click('details:has(#saved-list) summary')
                for identifier,(_,snapshot) in zip(ids,snapshots,strict=True):
                    open_saved(identifier,snapshot);exports[identifier]=download_all(identifier,snapshot)
                old_inputs=workspace.input_inventory()
                pointer=workspace.source/'data/numerical/current.json'
                old_generation=json.loads(pointer.read_text())['current']
                service.close()
                # Change saved fictional prices, then use ordinary candidate
                # preparation/publication. Do not patch freshness or identities.
                for path in (workspace.source/'raw/px').glob('*.json'):
                    value=json.loads(path.read_text())
                    for row in value['div']:
                        if row['date']>='2015-02-01':row['adjClose']*=1.2
                    path.write_text(json.dumps(value),encoding='utf-8')
                new_inputs=workspace.input_inventory();self.assertNotEqual(old_inputs,new_inputs)
                service=CandidateService(workspace).start();browser.service=service;storage.owners.append(service)
                new_generation=json.loads(pointer.read_text())['current']
                self.assertNotEqual(old_generation,new_generation)
                # A fresh numerical run really differs; its old checkpoints cannot
                # masquerade as work from this new generation.
                navigate();browser.click('details:has(#saved-list) summary')
                open_saved(ids[0],candidate);browser.click('#robustness-replay')
                browser.wait("!document.querySelector('#run-screen').disabled&&ResultArtifacts.forView('custom').captured_at!=="+json.dumps(candidate['captured_at']))
                changed=browser.evaluate("ResultArtifacts.forView('custom').result")
                self.assertEqual(changed['execution']['recovered_trials'],0)
                print(json.dumps(dict(check='generation-fresh-result-probe',old_generation=old_generation,
                    new_generation=new_generation,original_cagr=original_result['trial_results'][0]['cagr'],
                    changed_cagr=changed['trial_results'][0]['cagr'])),flush=True)
                self.assertNotEqual(changed['distributions'],original_result['distributions'])
                service.close();service=CandidateService(workspace,scenario='ordinary').start()
                browser.service=service;storage.owners.append(service)
                navigate();browser.click('details:has(#saved-list) summary')
                for identifier,(_,snapshot) in zip(ids,snapshots,strict=True):
                    open_saved(identifier,snapshot)
                    self.assertEqual(download_all(identifier,snapshot),exports[identifier])
                self.assertEqual(browser.errors,[])
                # Retain exact plans, original labels/settings and complete
                # snapshots alongside CSV receipts after the fixture is removed.
                (storage.root/'evidence/original-snapshots.json').write_text(json.dumps([
                    dict(id=identifier,name=name,snapshot=snapshot)
                    for identifier,(name,snapshot) in zip(ids,snapshots,strict=True)],
                    sort_keys=True,allow_nan=False),encoding='utf-8')
                print(json.dumps(dict(check='native-snapshots-generation-replacement',old_generation=old_generation,
                    new_generation=new_generation,old_inputs=old_inputs,new_inputs=new_inputs,
                    sources=workspace.sources,records=ids,downloads=receipts,
                    byte_identical_exports=sum(map(len,exports.values())),fresh_recovered_trials=changed['execution']['recovered_trials'])),flush=True)
            finally:
                browser.close();service.close()
                print(json.dumps(dict(browser_artifacts=storage.preserve(),check='native-generation-closure',
                    closure=service.owner.closure(),browser=browser.owned.closure() if browser.owned else None)),flush=True)

    def test_candidate_controls_artifacts_replay_exports_and_drafts(self):
        with FictionalWorkspace() as workspace:
            service=CandidateService(workspace).start()
            storage=workspace.own(BrowserStorage())
            browser=workspace.own(WorkflowBrowser(storage,service));downloads=[];checks=[]
            try:
                browser.start();browser.viewport(1440,1000)
                url='http://127.0.0.1:'+str(service.port)+'/'
                browser.navigate(url);browser.wait("!!ResultArtifacts.forView('latest')")
                browser.click('#auto-run');browser.click('#mode-backtest');browser.fill('#schedule-kind','custom')
                browser.fill('#backtest-engine','experimental')
                for selector,value in [('#trade-start','2015-01-02'),('#trade-end','2015-02-27'),('#rank-to','3'),('#date-testing','random'),('#random-trials','24')]:browser.fill(selector,value)
                browser.wait("!document.querySelector('#calendar-controls').hidden")
                browser.click('#calendar-custom')
                def run():
                    previous=browser.evaluate("ResultArtifacts.forView('custom')?.captured_at??null")
                    browser.click('#run-screen')
                    browser.wait("!document.querySelector('#run-screen').disabled&&ResultArtifacts.forView('custom')?.captured_at!=="+json.dumps(previous))
                    self.assertEqual(browser.evaluate("document.querySelector('#screen-error').textContent"),'')
                run()
                result=browser.evaluate("ResultArtifacts.forView('custom').result")
                self.assertEqual((result['completed'],result['valid'],len(result['trial_results'])),(24,24,24))
                self.assertEqual(browser.evaluate("ResultArtifacts.forView('custom').presentation.periodLabel"),'2015-01-02 → 2015-02-27')
                for index,trial in enumerate(result['trial_results']):
                    browser.fill('#robustness-trial',str(index));browser.click('#robustness-inspect')
                    self.assertEqual(browser.evaluate("document.querySelectorAll('#schedule-rows tr').length"),len(trial['periods']))
                    self.assertIn('week(s)',browser.evaluate("document.querySelector('#schedule-dates').textContent"))
                checks.append('24 complete trials and all stored inspection rows')
                def download(selector,rows,field):
                    receipt,content=browser.download(selector)
                    parsed=list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
                    self.assertEqual(len(parsed),len(rows));self.assertIn(field,parsed[0]);downloads.append(receipt)
                    return parsed
                rows=download('#robustness-download',result['trials'],'interval_unit')
                self.assertTrue(all(r['interval_unit']=='week' and r['interval_count']=='1' for r in rows))
                last=result['trial_results'][-1]
                download('#schedule-download-returns',last['periods'],'portfolio')
                download('#schedule-download-holdings',[h for p in last['periods'] for h in p['holdings']],'symbol')
                # Reopening stored results and exporting are independent of calculation.
                browser.fill('#saved-name','Candidate weekly original labels')
                browser.click('#save-backtest');browser.click('details:has(#saved-list) summary');browser.wait("document.querySelectorAll('#saved-list [data-open]').length===1")
                browser.fill('#rank-to','2')
                browser.click('#saved-list [data-open]')
                browser.wait("ResultArtifacts.forView('custom').settings.rank_to===3")
                self.assertEqual(browser.evaluate("ResultArtifacts.forView('custom').result.configuration.samples"),result['configuration']['samples'])
                previous=browser.evaluate("ResultArtifacts.forView('custom').captured_at")
                browser.click('#robustness-replay');browser.wait("!document.querySelector('#run-screen').disabled&&ResultArtifacts.forView('custom').captured_at!=="+json.dumps(previous))
                self.assertEqual(browser.evaluate("document.querySelector('#screen-error').textContent"),'')
                self.assertEqual(browser.evaluate("ResultArtifacts.forView('custom').result.configuration"),result['configuration'])
                checks.append('real CSV files, saved reopening and recorded-plan replay')
                # A held draft blocks result restoration, and confirmed Cancel releases it.
                browser.click('#queue-pause');browser.wait("document.querySelector('#queue-pause').textContent==='Resume queue'");browser.fill('#queue-name','Held weekly')
                browser.click('#queue-add');browser.wait("document.querySelector('#queue-list [data-action=edit]')")
                browser.click('#queue-list [data-action=edit]');browser.wait("!document.querySelector('#queue-cancel-edit').hidden")
                browser.fill('#rank-to','2');browser.click('#saved-list [data-open]')
                browser.wait("document.querySelector('#saved-message').textContent.includes('Save or cancel')")
                self.assertEqual(browser.evaluate("document.querySelector('#rank-to').value"),'2')
                browser.click('#queue-cancel-edit');browser.wait("document.querySelector('#queue-cancel-edit').hidden")
                checks.append('held draft prevents library overwrite and cancels coherently')
                browser.click('#queue-pause');browser.wait("document.querySelector('#queue-list [data-action=open]')")
                browser.click('#queue-list [data-action=open]')
                browser.wait("document.querySelector('#queue-status').textContent.startsWith('Opened')")
                browser.wait("ResultArtifacts.forView('custom').result.completed===24")
                checks.append('canonical queued calculation and stored result opening')
                browser.click('#calendar-custom');browser.fill('#date-testing','single');browser.fill('#rebalance-months','1');run()
                self.assertEqual(browser.evaluate("ResultArtifacts.forView('custom').result.months"),1)
                # Old snapshot versions reopen through the actual library UI.
                browser.evaluate("""(async()=>{const a=JSON.parse(JSON.stringify(ResultArtifacts.forView('custom')));for(const version of [1,2]){const old={...a,version};if(version===1){old.context={pill:'Original monthly period',notes:[]};delete old.presentation;}await fetch('/api/backtests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'Old monthly v'+version,snapshot:old})});}})()""")
                browser.click('#refresh-backtests');browser.wait("document.querySelectorAll('#saved-list [data-open]').length===3")
                for index in (0,1):
                    selector='#saved-list li:nth-child('+str(index+1)+')'
                    name=browser.evaluate('document.querySelector('+json.dumps(selector+' strong')+').textContent')
                    browser.click(selector+' [data-open]')
                    browser.wait("document.querySelector('#saved-message').textContent.startsWith("+json.dumps('Opened “'+name+'”')+")&&!document.querySelector('#refresh-backtests').disabled")
                    browser.wait("document.querySelector('#schedule-message').textContent.includes('No calculation')")
                    self.assertIn('No calculation',browser.evaluate("document.querySelector('#schedule-message').textContent"))
                browser.fill('#min-cap','1000000');run()
                self.assertIsNone(browser.evaluate("ResultArtifacts.forView('custom').result.cagr"))
                browser.fill('#min-cap','100');browser.click('#calendar-custom');browser.fill('#calendar-unit','month');browser.fill('#calendar-count','2');run()
                self.assertEqual(browser.evaluate("ResultArtifacts.forView('custom').result.calendar.interval.count"),2)
                checks.append('legacy month, canonical month and empty selection')
                # Navigation keeps a server-owned job; explicit Stop cancels it.
                browser.fill('#date-testing','random');browser.fill('#calendar-unit','week')
                browser.fill('#calendar-count','1');browser.fill('#trade-end','2015-04-30')
                browser.fill('#random-trials','24');browser.click('#run-screen')
                browser.navigate(url)
                browser.wait("ResultArtifacts.forView('custom')?.result.completed===24")
                self.assertEqual(browser.evaluate("ResultArtifacts.forView('custom').result.trial_results.length"),24)
                browser.fill('#random-trials','100');browser.fill('#trade-start','2014-01-02')
                browser.click('#run-screen');browser.click('#stop-backtest')
                browser.wait("document.querySelector('#stop-backtest').hidden")
                self.assertIn('stopped',browser.evaluate("document.querySelector('#schedule-message').textContent"))
                checks.append('navigation recovery and explicit Stop')
                for width,height,name in [(1440,1000,'candidate-desktop'),(390,844,'candidate-mobile')]:
                    browser.viewport(width,height)
                    self.assertTrue(browser.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    browser.screenshot(name)
                # The same durable canonical snapshot opens with calculation forbidden.
                service.close();service=CandidateService(workspace,scenario='ordinary').start()
                browser.service=service;storage.owners.append(service)
                browser.navigate('http://127.0.0.1:'+str(service.port)+'/')
                browser.wait("!!ResultArtifacts.forView('latest')")
                browser.click('details:has(#saved-list) summary')
                browser.wait("document.querySelectorAll('#saved-list [data-open]').length===3")
                browser.click('#saved-list li:nth-child(3) [data-open]')
                browser.wait("ResultArtifacts.forView('custom')?.result.completed===24")
                self.assertTrue(browser.evaluate('EngineControls.calendarSupported()'))
                self.assertIn('week(s)',browser.evaluate("CalendarSettings.label(ResultArtifacts.forView('custom').settings)"))
                receipt,content=browser.download('#robustness-download');downloads.append(receipt)
                self.assertIn(b'interval_unit',content)
                checks.append('canonical saved reopening and CSV without numerical preparation or calculation')
                self.assertEqual(browser.errors,[])
                print(json.dumps(dict(check='candidate-native-browser',checks=checks,downloads=downloads,sources=workspace.sources)),flush=True)
            except BaseException:
                try:print(json.dumps(dict(dom=browser.evaluate("({queue:document.querySelector('#queue-status').textContent,list:document.querySelector('#queue-list').innerText,error:document.querySelector('#screen-error').textContent,message:document.querySelector('#schedule-message').textContent,progress:document.querySelector('#schedule-progress-detail').textContent,artifact:ResultArtifacts.forView('custom')?.kind})"))),flush=True)
                except Exception:pass
                for log in (workspace.source/'data/logs').glob('*.log'):
                    print(log.read_text(encoding='utf8'),flush=True)
                raise
            finally:
                browser.close();service.close()
                print(json.dumps(dict(browser_artifacts=storage.preserve())),flush=True)
                print(json.dumps(dict(check='candidate-native-closure',closure=service.owner.closure(),browser=browser.owned.closure() if browser.owned else None)),flush=True)


if __name__=='__main__':unittest.main()
