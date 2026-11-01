"""Native equivalent of check-source-service-browser.js on fictional inputs."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
import base64
import csv
import io
import json
import math
import os
from pathlib import Path
import sys
import unittest

from bench_native_browser import BrowserStorage, NativeBrowser
from bench_source_service_fixture import FictionalWorkspace, SourceService

STOCK_FIELDS = ['rank','symbol','name','exchange','sector','market_cap',
    'enterprise_value','metric_multiple','metric_yield','fiscal']
EVIDENCE_FIELDS = STOCK_FIELDS+['candidate_rank','ebitda_yield','ev_ebitda',
    'year','entry','exit','return_value','status','price','known','price_date']


def equal(actual, expected, where='result'):
    """Same exact categories and 1e-12 absolute/relative policy as WSL matrix."""
    if type(expected) in (int,float):
        assert type(actual) in (int,float) and math.isfinite(actual),where
        assert math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-12),(where,actual,expected)
    elif isinstance(expected,list):
        assert isinstance(actual,list) and len(actual)==len(expected),(where,'length')
        for i,value in enumerate(expected): equal(actual[i],value,where+'['+str(i)+']')
    elif isinstance(expected,dict):
        assert isinstance(actual,dict),where
        for key,value in expected.items():
            if key not in ('seconds','execution'): equal(actual[key],value,where+'.'+key)
    else: assert type(actual) is type(expected) and actual==expected,(where,actual,expected)


def stocks(rows):
    return [{key:row[key] for key in EVIDENCE_FIELDS if key in row} for row in rows]


@unittest.skipUnless(os.name=='nt','Native browser requires Windows.')
class SourceBrowserTests(unittest.TestCase):
    def test_actual_controls_seven_csvs_six_scenario_groups(self):
        checks,downloads = [],[]
        with FictionalWorkspace() as workspace:
            storage = workspace.own(BrowserStorage())
            service = SourceService(workspace,oracle=True).start()
            browser = workspace.own(NativeBrowser(storage,service))
            failed = False
            try:
                browser.start()
                print(json.dumps(dict(check='native-source-browser-started',identity=browser.identity,
                                      root=str(storage.root))),flush=True)
                expected = json.loads((service.control/'expected.json').read_bytes())
                oracle = json.loads((service.control/'oracle.json').read_bytes())
                url = 'http://127.0.0.1:'+str(service.port)+'/'
                def text(selector): return browser.evaluate('document.querySelector('+json.dumps(selector)+').textContent')
                def submit():
                    browser.click('#run-screen')
                    browser.wait('!document.querySelector("#run-screen").disabled')
                    self.assertEqual(text('#screen-error'),'')
                def download(selector,reference,fields):
                    receipt,data = browser.download(selector)
                    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig'),newline=''),strict=True)
                    rows = list(reader)
                    self.assertEqual(len(rows),len(reference),selector)
                    self.assertTrue(all(key in reader.fieldnames for key in fields))
                    for i,row in enumerate(rows):
                        self.assertIsNone(row.get(None),'Extra CSV columns.')
                        for key in fields:
                            value = reference[i].get(key)
                            if type(value) in (int,float): equal(float(row[key]),value,selector+'.'+key)
                            else: self.assertEqual(row[key],'' if value is None else str(value))
                    downloads.append(dict(selector=selector,rows=len(rows),headers=reader.fieldnames,**receipt))
                def request(path):
                    event = browser.event('Network.requestWillBeSent',lambda p:
                        p['request']['url']==url[:-1]+path and p['request']['method']=='POST')
                    sent = event['request'].get('postData')
                    if sent is None:
                        sent = browser.command('Network.getRequestPostData',dict(requestId=event['requestId']),page=True)['postData']
                    return event['requestId'],json.loads(sent)
                def response(request_id):
                    browser.event('Network.loadingFinished',lambda p:p['requestId']==request_id)
                    result = browser.command('Network.getResponseBody',dict(requestId=request_id),page=True)
                    raw = base64.b64decode(result['body']) if result['base64Encoded'] else result['body'].encode('utf-8')
                    return json.loads(raw)
                def group(name):
                    checks.append(name)
                    browser.clear_events()
                    print(json.dumps(dict(check='native-source-browser-group',group=name,downloads=len(downloads))),flush=True)
                browser.viewport(1440,1000)
                browser.navigate(url)
                browser.wait('typeof currentLatest !== "undefined" && currentLatest !== null')
                equal(stocks(browser.evaluate('currentLatest.stocks')),stocks(expected['latest']),'Latest SQL')
                self.assertEqual(text('#latest-count'),'50')
                browser.screenshot('desktop')
                download('#download-latest',expected['latest'],STOCK_FIELDS+['price','known','price_date'])
                group('default_latest_SQL_and_CSV')
                for selector,value in (('#stock-pool','cached'),('#ranking-metric','ev_ebitda_3y'),('#rank-to','7')):
                    browser.fill(selector,value)
                browser.click('#add-filter')
                browser.fill('.condition-row select[data-key="field"]','pe')
                browser.fill('.condition-row select[data-key="op"]','lt')
                browser.fill('.condition-row input','20'); submit()
                equal(stocks(browser.evaluate('currentLatest.stocks')),stocks(expected['browser_latest']),'Changed metric SQL')
                download('#download-latest',expected['browser_latest'],STOCK_FIELDS+['price','known','price_date'])
                group('changed_metric_threshold_SQL_and_CSV')
                browser.click('#reset-strategy'); browser.click('#mode-backtest')
                for selector,value in (('#stock-pool','cached'),('#from-year','2015'),('#to-year','2016'),('#rank-from','2'),('#rank-to','4')):
                    browser.fill(selector,value)
                submit()
                equal(stocks(browser.evaluate('currentScreen.years.flatMap(y=>y.holdings)')),stocks(expected['browser_historical']),'Historical SQL')
                historical = [dict(h,weight=1/3,contribution_pp=h['return_value']/3*100) for h in expected['browser_historical']]
                download('#download-holdings',historical,STOCK_FIELDS+['year','entry','exit','return_value','status','weight','contribution_pp'])
                years = browser.evaluate('currentScreen.years')
                download('#download-returns',years,['year','names','portfolio','spy','median_market_cap'])
                browser.fill('#min-cap','1000000'); submit()
                self.assertTrue(browser.evaluate('currentScreen.empty_years.length === 2 && currentScreen.cagr === null'))
                group('historical_year_rank_SQL_CSV_and_empty_coverage')
                for selector,value in (('#min-cap','100'),('#rank-from','1'),('#schedule-kind','custom'),
                    ('#trade-start','2015-01-01'),('#trade-end','2016-12-30'),('#rebalance-months','12'),('#date-testing','single')):
                    browser.fill(selector,value)
                browser.wait('!document.querySelector("#run-screen").disabled')
                browser.clear_events(); submit()
                request_id,sent = request('/api/schedule')
                fixed = response(request_id)
                equal(fixed,oracle['fixed'],'Fixed direct-function oracle')
                fixed_stocks = [dict(h,period_start=p['entry'],period_end=p['exit']) for p in fixed['periods'] for h in p['holdings']]
                download('#schedule-download-returns',fixed['periods'],['entry','exit','names','portfolio','spy'])
                download('#schedule-download-holdings',fixed_stocks,STOCK_FIELDS+['period_start','period_end','entry','exit','return_value','weight','contribution_pp','status'])
                group('fixed_schedule_HTTP_oracle_and_CSV')
                browser.fill('#date-testing','random'); browser.fill('#random-trials','5')
                def random(action='#run-screen'):
                    browser.clear_events(); browser.click(action)
                    browser.wait('!document.querySelector("#run-screen").disabled')
                    self.assertEqual(text('#screen-error'),'')
                    _,sent = request('/api/robustness')
                    configuration = browser.evaluate('JSON.parse(localStorage.getItem("backtest-experiment"))')
                    self.assertTrue(text('#schedule-message').startswith('Random-date test complete · 5 trials'))
                    replay = service.request('POST','/api/robustness',dict(sent,seed=configuration['seed']))
                    self.assertEqual(replay[-1]['type'],'complete')
                    return replay[-1]['result']
                fresh_a,fresh_b = random(),random()
                self.assertEqual(fresh_a['completed'],5); self.assertEqual(fresh_b['completed'],5)
                self.assertNotEqual(fresh_a['configuration']['seed'],fresh_b['configuration']['seed'])
                browser.click('.random-advanced summary'); browser.click('#repeat-random')
                browser.fill('#random-seed','42')
                seeded = random(); equal(seeded,oracle['random'],'Random direct-function oracle')
                cached = random(); equal(cached,seeded,'Cached random')
                self.assertEqual(cached['execution']['missing_books'],0)
                trials = [dict(t,seed=42,months=12,dates=';'.join(t['dates'])) for t in seeded['trials']]
                download('#robustness-download',trials,['trial','start','first_trade','end','cash_days','periods','cagr','spy_cagr','excess_cagr','total_return','growth','spy_growth','empty_periods','short_periods','seed','months','dates'])
                browser.fill('#robustness-trial','2')
                browser.clear_events(); browser.click('#robustness-inspect')
                browser.wait('!document.querySelector("#run-screen").disabled')
                request_id,_ = request('/api/schedule')
                equal(response(request_id),oracle['inspected'],'Saved date inspection')
                browser.navigate(url)
                browser.wait('typeof currentLatest !== "undefined" && currentLatest !== null')
                browser.click('#mode-backtest'); browser.fill('#schedule-kind','custom')
                browser.wait('!document.querySelector("#run-screen").disabled')
                replay = random('#robustness-replay'); equal(replay,seeded,'Reload saved replay')
                group('fresh_random_cached_seed_inspection_real_CSV_reload_replay')
                browser.viewport(390,844)
                self.assertTrue(browser.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                browser.screenshot('mobile')
                browser.navigate(url+'data.html')
                for selector,value in (('#data-scope','symbols'),('#data-symbols','ZZ000 ZZ063'),('#data-start','2015-01-01'),('#data-end','2016-12-30')):
                    browser.fill(selector,value)
                browser.click('#data-check')
                browser.wait('document.querySelector("#data-message").textContent === "Data check complete."')
                self.assertEqual(text('#data-error'),'')
                self.assertIn('missing',text('#data-key').lower())
                browser.click('#data-rebuild')
                browser.wait('document.querySelector("#data-message").textContent.startsWith("Rebuild complete.")')
                self.assertEqual(text('#data-error'),'')
                self.assertTrue(browser.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                browser.screenshot('panel-mobile')
                group('actual_panel_check_rebuild_mobile_layout')
                self.assertEqual(browser.errors,[])
                self.assertEqual(len(downloads),7)
                print(json.dumps(dict(check='native-source-browser-matrix',checks=checks,downloads=downloads,
                    page_errors=browser.errors,financial_tolerance=dict(absolute=1e-12,relative=1e-12),
                    browser_resources='unqualified',real_admission='closed',sources=workspace.sources,
                    inventory=storage.inventory())),flush=True)
            except BaseException:
                failed = True
                print(json.dumps(dict(check='native-source-browser-failed',checks=checks,downloads=downloads,
                    root=str(storage.root),page_errors=browser.errors)),flush=True)
                raise
            finally:
                try:
                    browser.close()
                    print(json.dumps(dict(check='native-source-browser-closure',closure=browser.owned.closure() if browser.owned else None)),flush=True)
                    service.close()
                    if not failed: print(json.dumps(dict(check='native-source-browser-artifacts',**storage.preserve())),flush=True)
                except BaseException:
                    if not failed: raise
                    import traceback
                    traceback.print_exc()


if __name__=='__main__': unittest.main()
