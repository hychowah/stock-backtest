"""Nightly/manual refresh behavior with private inputs and synthetic FMP replies."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from contextlib import ExitStack
from datetime import date, datetime, timezone
from contextlib import closing, redirect_stdout
import io
import json
import _thread
import signal
from threading import Event, Thread
import tempfile
import unittest
from unittest.mock import patch

from backtest.inputs import cache_assets, daily, financial_inputs, fmp_download, market, research
from backtest.runtime import cache_access
from backtest import screening
from website.server import data_manager as data, data_refresh as refresh


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.raw=self.root/'raw';self.raw.mkdir();(self.raw/'px').mkdir()
        self.context.enter_context(patch.object(data,'ROOT',self.root))
        for module in (data,market):self.context.enter_context(patch.object(module,'RAW',self.raw))
        self.context.enter_context(patch.object(data,'COVERAGE',self.raw/'download-coverage.json'))
        self.context.enter_context(patch.object(cache_access,'workspace',cache_access.WorkspaceAccess(self.root/'cache.lock')))
        self.context.enter_context(patch.object(fmp_download,'KEY_PATH',self.root/'absent-key'))
        self.context.enter_context(patch.object(fmp_download.Client,'request',side_effect=AssertionError('Unexpected network request')))
        self.context.enter_context(patch.object(data,'derived_status',return_value=[]))
        self.put('universe.json',[dict(symbol='A',listed=True,name='Alpha',sector='Energy')])
        self.old_report=self.report('2024-12-31')
        (self.raw/'metrics.jsonl').write_text(json.dumps(dict(symbol='A',rows=[self.old_report])))
        self.put('px/A.json',dict(div=self.prices([('2025-12-31',10),('2026-01-02',11)]),extra='keep'))
        self.put('spy-div.json',self.prices([('2025-12-31',100),('2026-01-02',110)]))
        self.put('treasury.json',[dict(date='2026-01-02',month3=4)])
        self.calls=[]
        self.context.enter_context(patch.object(data,'request_json',side_effect=self.provider))

    def put(self,name,value):cache_assets.write_json(self.raw/name,value)
    def prices(self,values):return [dict(date=day,adjClose=value) for day,value in values]
    def report(self,day):return dict(date=day,period='FY',reportedCurrency='USD',marketCap=200e6,enterpriseValue=100e6,evToEBITDA=5)
    def provider(self,endpoint,params,*args):
        self.calls.append((endpoint,params))
        symbol=params.get('symbol','A')
        if endpoint=='company-screener':return [dict(symbol='A',companyName='Alpha',exchange='NYSE',sector='Energy')]
        if endpoint=='delisted-companies':return []
        if endpoint in financial_inputs.ENDPOINTS:return [dict(self.report('2025-12-31'),symbol=symbol)]
        if endpoint=='treasury-rates':rows=[dict(date='2026-01-02',month3=3.9),dict(date='2026-01-05',month3=4.1)]
        else:rows=self.prices([('2025-12-31',100 if symbol=='SPY' else 10),('2026-01-02',110 if symbol=='SPY' else 11),('2026-01-05',120 if symbol=='SPY' else 12)])
        return [row for row in rows if params['from']<=row['date']<=params['to']]

    def download(self,state=None):
        state=dict(pending_symbols=[]) if state is None else state
        with cache_access.access(),fmp_download.Client() as client:
            refresh.download(state,date(2026,1,5),lambda **kw:None,lambda:None,client)
        return state

    def test_existing_company_gets_new_annual_report_and_refreshed_dates(self):
        before=(self.raw/'metrics.jsonl').read_bytes()
        self.download()
        records,_=data.financial_records()
        self.assertEqual([row['date'] for row in records['A']['rows']],['2024-12-31','2025-12-31'])
        self.assertTrue((self.raw/'metrics.jsonl').read_bytes().startswith(before))
        self.assertEqual(data.read_json(self.raw/'px/A.json')['extra'],'keep')
        self.assertEqual(cache_assets.SeriesAsset(self.raw/'px/A.json','adjClose',stock=True).rows[-1]['date'],'2026-01-05')
        self.assertEqual(data.read_json(self.raw/'treasury.json')[-1]['month3'],3.9)
        self.assertEqual(financial_inputs.read(self.raw,'A','income-statement')[0][0]['date'],'2025-12-31')

    def test_new_annual_report_enters_prepared_selection_only_after_existing_lag(self):
        provider=self.provider
        def with_history(endpoint,params,*args):
            rows=provider(endpoint,params,*args)
            if 'price' in endpoint:
                rows+=[row for row in self.prices([('2024-12-31',10),('2026-04-01',12)])
                       if params['from']<=row['date']<=params['to']]
            return rows
        self.put('px/A.json',dict(div=self.prices([('2024-12-31',10),('2025-12-31',10),('2026-01-02',11)])))
        source=self.root/'data/research.sqlite';path=self.root/'data/schedules.sqlite'
        with patch.object(research,'ROOT',self.root),patch.object(research,'RAW',self.raw),patch.object(data,'request_json',side_effect=with_history),redirect_stdout(io.StringIO()):
            state=self.download();daily.prepare(path,source)
            with closing(daily.connect(path,source)) as db:
                self.assertEqual(screening.latest(db,pool='cached')[0]['fiscal'],'2024-12-31')
            with cache_access.access(),fmp_download.Client() as client:
                refresh.download(state,date(2026,4,1),lambda **kw:None,lambda:None,client)
            daily.prepare(path,source)
            with closing(daily.connect(path,source)) as db:
                self.assertEqual(screening.latest(db,pool='cached')[0]['fiscal'],'2025-12-31')
        research.forget_signature()

    def test_unchanged_refresh_preserves_asset_bytes_and_timestamps(self):
        self.download()
        paths=[self.raw/'universe.json',self.raw/'metrics.jsonl',self.raw/'px/A.json',
               self.raw/'spy-div.json',self.raw/'treasury.json',financial_inputs.asset_path(self.raw,'A','income-statement')]
        before={path:(path.read_bytes(),path.stat().st_mtime_ns) for path in paths}
        self.download()
        self.assertEqual(before,{path:(path.read_bytes(),path.stat().st_mtime_ns) for path in paths})
        windows=data.read_json(data.COVERAGE)['px/A.json']['windows']
        self.assertEqual(windows,[['2025-12-31','2026-01-05']])

    def test_delisted_names_and_metadata_survive_refresh(self):
        self.put('universe.json',[dict(symbol='A',listed=True),dict(symbol='OLD',listed=True,sector='Energy',name='Old company')])
        self.download()
        old=data.universe_rows()['OLD']
        self.assertFalse(old['listed']);self.assertEqual(old['sector'],'Energy')

    def test_new_listing_receives_history_and_all_annual_assets(self):
        provider=self.provider
        def added(endpoint,params,*args):
            if endpoint=='company-screener':return provider(endpoint,params,*args)+[dict(symbol='NEW',companyName='New company',exchange='NASDAQ')]
            return provider(endpoint,params,*args)
        with patch.object(data,'request_json',side_effect=added):state=self.download()
        self.assertEqual(state['pending_symbols'],[])
        self.assertTrue(market.cache_path_for('NEW').exists())
        self.assertTrue(all(financial_inputs.read(self.raw,'NEW',endpoint)[0] for endpoint in financial_inputs.ENDPOINTS))
        ranges=[params['from'] for endpoint,params in self.calls if 'price' in endpoint and params.get('symbol')=='NEW']
        self.assertIn('1995-01-01',ranges)

    def test_pending_addition_survives_publication_then_provider_failure(self):
        provider=self.provider
        def interrupted(endpoint,params,*args):
            if endpoint=='company-screener':return provider(endpoint,params,*args)+[dict(symbol='NEW',companyName='New company',exchange='NASDAQ')]
            if params.get('symbol')=='NEW':raise OSError('provider unavailable')
            return provider(endpoint,params,*args)
        with patch.object(data,'request_json',side_effect=interrupted):attempt=self.download()
        self.assertGreater(attempt['failed_assets'],0)
        self.assertIn('NEW',data.universe_rows())
        state=refresh.status();self.assertIn('NEW',state['pending_symbols'])
        self.download(state)
        self.assertEqual(refresh.status()['pending_symbols'],[])
        self.assertTrue(market.cache_path_for('NEW').exists())

    def test_newly_eligible_existing_company_gets_its_first_history(self):
        self.put('universe.json',[dict(symbol='A',listed=True),dict(symbol='WAIT',listed=True)])
        with (self.raw/'metrics.jsonl').open('a') as output:output.write('\n'+json.dumps(dict(symbol='WAIT',rows=[])))
        self.download()
        self.assertTrue(market.cache_path_for('WAIT').exists())
        self.assertEqual(refresh.status()['pending_symbols'],[])

    def test_one_failed_company_does_not_block_prices_and_spy(self):
        self.put('universe.json',[dict(symbol='A',listed=True),dict(symbol='BAD',listed=False)])
        provider=self.provider
        def failed_company(endpoint,params,*args):
            if endpoint=='key-metrics' and params.get('symbol')=='BAD':
                raise ValueError('Provider failed for one historical company')
            return provider(endpoint,params,*args)
        with patch.object(data,'request_json',side_effect=failed_company),patch.object(data,'rebuild'),cache_access.access():
            state=refresh.run()
        self.assertEqual(state['outcome'],'partial')
        self.assertEqual(state['latest_session'],'2026-01-05')
        self.assertEqual(cache_assets.SeriesAsset(self.raw/'px/A.json','adjClose',stock=True).rows[-1]['date'],'2026-01-05')
        self.assertNotIn('last_success',state)

    def test_unmanaged_company_keeps_every_returned_key_metric_field(self):
        self.put('universe.json',[dict(symbol='A',listed=True),dict(symbol='HOLD',listed=True)])
        with (self.raw/'metrics.jsonl').open('a') as output:
            output.write('\n'+json.dumps(dict(symbol='HOLD',rows=[self.old_report])))
        provider=self.provider
        def extra_fields(endpoint,params,*args):
            if endpoint=='key-metrics' and params.get('symbol')=='HOLD':
                return [dict(self.old_report,providerMetadata={'extra':42})]
            return provider(endpoint,params,*args)
        with patch.object(data,'request_json',side_effect=extra_fields):self.download()
        rows=financial_inputs.read(self.raw,'HOLD','key-metrics')[0]
        self.assertEqual(rows[0]['providerMetadata'],{'extra':42})
        self.assertFalse(market.cache_path_for('HOLD').exists())

    def test_failed_universe_fetch_does_not_change_saved_listings(self):
        before=(self.raw/'universe.json').read_bytes()
        with patch.object(data,'request_json',side_effect=lambda endpoint,params,*args:[] if endpoint=='company-screener' else self.provider(endpoint,params,*args)):
            with self.assertRaises(ValueError):self.download()
        self.assertEqual((self.raw/'universe.json').read_bytes(),before)

    def test_adjustment_change_replaces_whole_history_together(self):
        self.put('px/A.json',dict(div=self.prices([('1996-01-02',5),('2025-12-31',10),('2026-01-02',11)]),extra='keep'))
        provider=self.provider
        def adjusted(endpoint,params,*args):
            if 'price' in endpoint and params.get('symbol')=='A':
                rows=self.prices([('1996-01-02',2.5),('2025-12-31',5),('2026-01-02',5.5),('2026-01-05',6)])
                return [row for row in rows if params['from']<=row['date']<=params['to']]
            return provider(endpoint,params,*args)
        with patch.object(data,'request_json',side_effect=adjusted):self.download()
        saved=data.read_json(self.raw/'px/A.json')
        self.assertEqual([row['adjClose'] for row in reversed(saved['div'])],[2.5,5,5.5,6])
        self.assertEqual(saved['extra'],'keep')

    def test_incomplete_adjusted_replacement_keeps_original_bytes(self):
        self.put('px/A.json',dict(div=self.prices([('1996-01-02',5),('2025-12-31',10),('2026-01-02',11)])))
        before=(self.raw/'px/A.json').read_bytes();provider=self.provider
        def incomplete(endpoint,params,*args):
            if 'price' in endpoint and params.get('symbol')=='A':
                return [dict(row,adjClose=row['adjClose']/2) for row in provider(endpoint,params,*args)]
            return provider(endpoint,params,*args)
        with patch.object(data,'request_json',side_effect=incomplete):state=self.download()
        self.assertEqual(state['failed_assets'],1)
        self.assertEqual((self.raw/'px/A.json').read_bytes(),before)

    def test_adjusted_replacement_cannot_lose_newly_returned_dates(self):
        before=(self.raw/'px/A.json').read_bytes();provider=self.provider
        def unstable(endpoint,params,*args):
            if 'price' in endpoint and params.get('symbol')=='A':
                rows=[dict(row,adjClose=row['adjClose']/2) for row in provider(endpoint,params,*args)]
                return rows if params['from']=='2025-12-31' else [row for row in rows if row['date']!='2026-01-05']
            return provider(endpoint,params,*args)
        with patch.object(data,'request_json',side_effect=unstable):self.download()
        self.assertEqual((self.raw/'px/A.json').read_bytes(),before)

    def test_equivalent_numeric_prices_do_not_trigger_a_full_history_fetch(self):
        provider=self.provider
        def numeric_text(endpoint,params,*args):
            rows=provider(endpoint,params,*args)
            if 'price' in endpoint and params.get('symbol')=='A':
                return [dict(row,adjClose=str(row['adjClose'])) for row in rows]
            return rows
        with patch.object(data,'request_json',side_effect=numeric_text):self.download()
        starts=[params['from'] for endpoint,params in self.calls if 'price' in endpoint and params.get('symbol')=='A']
        self.assertEqual(starts,['2025-12-31'])

    def test_publication_io_failure_stops_further_download_stages(self):
        before=(self.raw/'spy-div.json').read_bytes()
        with patch.object(financial_inputs,'publish',side_effect=OSError('disk full')),self.assertRaises(OSError):self.download()
        self.assertEqual((self.raw/'spy-div.json').read_bytes(),before)
        self.assertFalse(any('price' in endpoint for endpoint,_ in self.calls))

    def test_refresh_resumes_known_unfinished_historical_windows(self):
        path=self.raw/'px/A.json';path.unlink()
        asset=cache_assets.SeriesAsset(path,'adjClose',stock=True);ledger={}
        asset.publish(self.prices([('1996-01-02',5)]),'1995-01-01','1999-12-31',ledger,data.COVERAGE)
        asset.publish(self.prices([('2025-12-31',10),('2026-01-02',11)]),'2020-01-01','2026-01-02',ledger,data.COVERAGE)
        provider=self.provider
        def with_missing_history(endpoint,params,*args):
            rows=provider(endpoint,params,*args)
            if 'price' in endpoint and params.get('symbol')=='A' and params['from']<='2005-01-03'<=params['to']:
                rows+=self.prices([('2005-01-03',7)])
            return rows
        with patch.object(data,'request_json',side_effect=with_missing_history):self.download()
        self.assertIn('2005-01-03',[row['date'] for row in cache_assets.SeriesAsset(path,'adjClose',stock=True).rows])

    def test_empty_history_reuses_checked_old_windows_and_rechecks_recent_dates(self):
        self.put('px/A.json',dict(div=[]));provider=self.provider
        def empty_stock(endpoint,params,*args):
            if 'price' in endpoint and params.get('symbol')=='A':
                self.calls.append((endpoint,params));return []
            return provider(endpoint,params,*args)
        with patch.object(data,'request_json',side_effect=empty_stock):
            self.download();self.calls.clear();self.download()
        starts=[params['from'] for endpoint,params in self.calls if 'price' in endpoint and params.get('symbol')=='A']
        self.assertTrue(starts)
        self.assertGreaterEqual(min(starts),'2025-12-29')

    def test_recent_empty_response_is_rechecked_and_saved_rows_survive(self):
        before=(self.raw/'px/A.json').read_bytes();provider=self.provider
        def delayed(endpoint,params,*args):
            if 'price' in endpoint and params.get('symbol')=='A':return []
            return provider(endpoint,params,*args)
        with patch.object(data,'request_json',side_effect=delayed):self.download()
        self.assertEqual((self.raw/'px/A.json').read_bytes(),before)
        self.download()
        self.assertEqual(cache_assets.SeriesAsset(self.raw/'px/A.json','adjClose',stock=True).rows[-1]['date'],'2026-01-05')

    def test_raw_statement_conflicts_remain_unavailable_and_metrics_keep_saved_values(self):
        old=dict(self.report('2025-12-31'),revenue=100)
        financial_inputs.publish(self.raw,'A','income-statement',[old],{},data.COVERAGE)
        self.put('universe.json',[dict(symbol='A',listed=True)])
        (self.raw/'metrics.jsonl').write_text(json.dumps(dict(symbol='A',rows=[dict(self.old_report,evToEBITDA=8)])))
        provider=self.provider
        def revised(endpoint,params,*args):
            rows=provider(endpoint,params,*args)
            if endpoint=='income-statement':return [dict(rows[0],revenue=200)]
            return rows
        with patch.object(data,'request_json',side_effect=revised):self.download()
        self.assertNotIn('revenue',financial_inputs.history(self.raw,'A').get('2025-12-31',{}))
        self.assertEqual(data.financial_records()[0]['A']['rows'][0]['evToEBITDA'],8)

    def test_annual_refresh_retains_old_duplicate_rows_without_accumulating_copies(self):
        old=dict(self.report('2024-12-31'),revenue=100)
        financial_inputs.publish(self.raw,'A','income-statement',[old,old],{},data.COVERAGE)
        self.download();self.download()
        rows=financial_inputs.read(self.raw,'A','income-statement')[0]
        self.assertEqual(rows.count(old),2)
        self.assertEqual(len(rows),3)

    def test_failed_refresh_prepares_valid_downloads_and_records_safe_partial_status(self):
        def publish_then_fail(*args):
            self.put('spy-div.json',self.prices([('2026-01-05',120)]))
            raise RuntimeError('https://provider.invalid/?apikey=PRIVATE-CANARY')
        with patch.object(refresh,'download',side_effect=publish_then_fail),patch.object(data,'rebuild') as rebuild,cache_access.access():state=refresh.run()
        rebuild.assert_called_once()
        self.assertEqual(state['outcome'],'partial');self.assertEqual(state['latest_session'],'2026-01-05')
        self.assertNotIn('last_success',state)
        self.assertNotIn('PRIVATE-CANARY',json.dumps(refresh.status()))

    def test_preparation_failure_cannot_record_success(self):
        with patch.object(refresh,'download'),patch.object(data,'rebuild',side_effect=ValueError('bad input')),cache_access.access(),self.assertRaises(ValueError):refresh.run()
        self.assertEqual(refresh.status()['outcome'],'failed');self.assertNotIn('last_success',refresh.status())

    def test_cancel_keeps_status_and_does_not_start_preparation(self):
        with patch.object(refresh,'download',side_effect=fmp_download.Cancelled),patch.object(data,'rebuild') as rebuild,cache_access.access(),self.assertRaises(fmp_download.Cancelled):refresh.run()
        rebuild.assert_not_called();self.assertEqual(refresh.status()['outcome'],'cancelled')

    def test_cancel_joins_fetchers_before_releasing_cache_ownership(self):
        entered=Event();release=Event();provider=self.provider;jobs=data.Jobs()
        def held(endpoint,params,*args):
            if endpoint=='key-metrics':entered.set();release.wait(3)
            return provider(endpoint,params,*args)
        with patch.object(data,'request_json',side_effect=held),patch.object(data,'rebuild') as rebuild:
            try:
                jobs.start('refresh',{});self.assertTrue(entered.wait(2));jobs.cancel_job()
                with self.assertRaises(cache_access.Contention):
                    with cache_access.access(timeout=.02):pass
                self.assertTrue(jobs.thread.is_alive())
            finally:release.set();jobs.thread.join(3)
        self.assertFalse(jobs.thread.is_alive());rebuild.assert_not_called()
        self.assertEqual(refresh.status()['outcome'],'cancelled')
        with cache_access.access(timeout=.02):pass

    def test_repeated_startup_interrupts_keep_cache_until_fetch_workers_finish(self):
        entered=Event();release=Event();provider=self.provider;outcomes=[]
        before=signal.getsignal(signal.SIGINT)
        def held(endpoint,params,*args):
            if endpoint=='key-metrics':entered.set();release.wait(3)
            return provider(endpoint,params,*args)
        def interrupt():
            if not entered.wait(2):release.set();return
            _thread.interrupt_main()
            try:
                with cache_access.access(timeout=.05):outcomes.append('released early')
            except cache_access.Contention:outcomes.append('held')
            _thread.interrupt_main();release.set()
        thread=Thread(target=interrupt)
        with patch.object(data,'request_json',side_effect=held),patch.object(data,'rebuild') as rebuild:
            try:
                with cache_access.access(),self.assertRaises(KeyboardInterrupt):
                    thread.start();refresh.startup(lambda **kw:None)
            finally:release.set();thread.join(3)
        self.assertEqual(outcomes,['held']);rebuild.assert_not_called()
        self.assertEqual(signal.getsignal(signal.SIGINT),before)
        self.assertEqual(refresh.status()['outcome'],'cancelled')

    def test_manual_refresh_uses_complete_coverage_and_rebuilds_before_completion(self):
        jobs=data.Jobs()
        with patch.object(data,'rebuild') as rebuild:
            jobs.start('refresh',{});jobs.thread.join(5)
        self.assertFalse(jobs.thread.is_alive());self.assertTrue(jobs.rebuilt)
        self.assertIsNone(jobs.snapshot()['job']['error'])
        self.assertEqual(jobs.snapshot()['refresh']['outcome'],'complete')
        rebuild.assert_called_once()
        with self.assertRaises(ValueError):jobs.start('refresh',dict(scope='symbols',symbols='A'))

    def test_refresh_requests_only_dates_whose_utc_cutoff_has_passed(self):
        for instant,end in [(datetime(2026,1,5,21,59,59,tzinfo=timezone.utc),'2026-01-04'),
                            (datetime(2026,1,5,22,0,tzinfo=timezone.utc),'2026-01-05')]:
            with self.subTest(instant=instant):
                self.calls.clear()
                with patch.object(refresh,'datetime',wraps=datetime) as clock,patch.object(data,'rebuild'),cache_access.access():
                    clock.now.return_value=instant
                    state=refresh.run()
                spans=[params for _,params in self.calls if 'to' in params]
                self.assertTrue(spans)
                self.assertTrue(all(params['to']<=end for params in spans))
                self.assertTrue(any(params['to']==end for params in spans))
                self.assertEqual(state['outcome'],'complete')


if __name__=='__main__':unittest.main()
