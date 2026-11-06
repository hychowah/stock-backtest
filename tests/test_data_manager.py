"""Data inventory, resumable missing-only downloads, job and HTTP boundaries."""
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.inputs import daily, fmp_download, market
from contextlib import ExitStack, nullcontext
from datetime import date
import io
import gzip
import json
import errno
import os
from pathlib import Path
import sys
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from website.server import data_manager as d
from website.server import app as serve
class CacheTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.raw=self.root/'raw';self.raw.mkdir();(self.raw/'px').mkdir()
        for module in (d,market):self.context.enter_context(patch.object(module,'RAW',self.raw))
        self.context.enter_context(patch.object(d,'ROOT',self.root))
        self.context.enter_context(patch.object(d,'COVERAGE',self.raw/'download-coverage.json'))
        self.context.enter_context(patch.object(d,'derived_status',return_value=[]))
        self.context.enter_context(patch.object(fmp_download,'KEY_PATH',self.root/'absent-key'))
        self.context.enter_context(patch.object(d.cache_access,'access',side_effect=lambda timeout=30:nullcontext()))
        self.context.enter_context(patch('urllib.request.urlopen',side_effect=AssertionError('Unexpected request')))
        self.put('universe.json',[dict(symbol='A',listed=True),dict(symbol='B',listed=True)])
        (self.raw/'metrics.jsonl').write_text(json.dumps(dict(symbol='A',rows=[])))
        self.o=d.options(dict(scope='symbols',symbols='A',start='2020-01-01',end='2020-12-31'))

    def put(self,name,value):d.write_json(self.raw/name,value)
    def prices(self,days):return [dict(date=day,adjClose=value) for day,value in days]
    def stop(self):pass
    def emit(self,**kw):pass

    def test_missing_windows_exclude_saved_span_and_checked_ranges(self):
        rows=self.prices([('2020-03-01',10),('2020-09-01',20)])
        spans=d.cache_assets.missing_spans(rows,'adjClose',date(2020,1,1),date(2020,12,31),[['2020-01-01','2020-02-29']])
        self.assertEqual(spans,[(date(2020,9,2),date(2020,12,31))])
        self.assertEqual(list(d.spans(date(2020,1,15),date(2020,3,1),True)),[('2020-01-15','2020-01-31'),('2020-02-01','2020-02-29'),('2020-03-01','2020-03-01')])

    def test_existing_records_and_other_saved_keys_are_preserved(self):
        payload=dict(div=self.prices([('2020-01-01',10),('2020-06-30',20)]),extra=[dict(date='2020-06-30',price=21)])
        self.put('px/A.json',payload)
        with patch.object(d,'request_json',return_value=self.prices([('2020-12-31',30)])) as get:
            d.fill_series(None,'adjClose','prices',self.o,{},self.emit,self.stop,symbol='A')
        self.assertEqual(get.call_args.args[1],dict(symbol='A',**{'from':'2020-07-01','to':'2020-12-31'}))
        saved=d.read_json(self.raw/'px/A.json')
        self.assertEqual(saved['extra'],payload['extra'])
        self.assertEqual(saved['div'][-1],payload['div'][0])

    def test_noop_needs_no_key_and_makes_no_requests(self):
        self.put('px/A.json',dict(div=self.prices([('2020-01-01',10),('2020-12-31',20)])))
        self.o['datasets']=['prices']
        report=d.download(self.o,self.emit,self.stop)
        self.assertFalse(report['api_key_present'])
        self.assertEqual(report['prices_available'],1)
        self.assertEqual(report['prices'][0]['windows'],0)

    def test_empty_response_is_checkpointed_and_not_retried(self):
        ledger={}
        with patch.object(d,'request_json',return_value=[]) as get:
            d.fill_series(None,'adjClose','prices',self.o,ledger,self.emit,self.stop,symbol='A')
            d.fill_series(None,'adjClose','prices',self.o,ledger,self.emit,self.stop,symbol='A')
        self.assertEqual(get.call_count,1)
        self.assertEqual(d.read_json(d.COVERAGE)['px/A.json']['windows'],[['2020-01-01','2020-12-31']])

    def test_failure_keeps_original_and_does_not_mark_coverage(self):
        payload=dict(div=self.prices([('2020-01-01',10),('2020-06-30',20)]))
        self.put('px/A.json',payload)
        original=(self.raw/'px/A.json').read_bytes()
        with patch.object(d,'request_json',side_effect=ValueError('Provider failed')),self.assertRaises(ValueError):
            d.fill_series(None,'adjClose','prices',self.o,{},self.emit,self.stop,symbol='A')
        self.assertEqual((self.raw/'px/A.json').read_bytes(),original)
        self.assertFalse(d.COVERAGE.exists())

    def test_nonpositive_prices_keep_good_rows_and_persistent_warnings(self):
        self.put('px/A.json',dict(div=[],extra=[dict(date='2020-01-03',price=13)]))
        batch=self.prices([('2020-01-02',0),('2020-01-03',12),('2020-01-06',-1)])
        events=[];ledger={}
        with patch.object(d,'request_json',return_value=batch) as get:
            d.fill_series(None,'adjClose','prices',self.o,ledger,lambda **kw:events.append(kw),self.stop,symbol='A')
            d.fill_series(None,'adjClose','prices',self.o,ledger,self.emit,self.stop,symbol='A')
        self.assertEqual(get.call_count,1)
        saved=d.read_json(self.raw/'px/A.json')
        self.assertEqual(saved['div'],self.prices([('2020-01-03',12)]))
        self.assertEqual(saved['extra'],[dict(date='2020-01-03',price=13)])
        self.assertTrue(any('2020-01-02' in event.get('warning','') for event in events))
        report=d.inspect(self.o)
        self.assertEqual(report['prices'][0]['skipped_dates'],['2020-01-02','2020-01-06'])
        self.assertEqual(report['prices'][0]['windows'],0)
        self.assertIn('A: skipped 2',report['warnings'][0])
        # Later windows preserve exclusions and bind them to the updated asset.
        asset=d.cache_assets.SeriesAsset(self.raw/'px/A.json','adjClose',stock=True)
        asset.publish([], '2021-01-01','2021-12-31',ledger,d.COVERAGE)
        self.assertEqual(d.inspect(self.o)['warnings'],report['warnings'])
        # Replaced files cannot inherit a warning from another file generation.
        self.put('px/A.json',dict(div=self.prices([('2020-01-03',99)])))
        self.assertEqual(d.inspect(self.o)['warnings'],[])

    def test_spy_report_exports_all_skipped_dates_with_concise_warning(self):
        skipped=['2020-01-02','2020-01-03','2020-01-06','2020-01-07']
        batch=self.prices([(day,0) for day in skipped]+[('2020-01-08',300)])
        with patch.object(d,'request_json',return_value=batch):
            d.fill_series('spy-div.json','adjClose','prices',self.o,{},self.emit,self.stop)
        report=json.loads(json.dumps(d.inspect(self.o),allow_nan=False))
        spy=next(asset for asset in report['assets'] if asset['name']=='SPY total-return prices')
        self.assertEqual(spy['skipped_dates'],skipped)
        self.assertEqual(spy['count'],1)
        warning=report['warnings'][0]
        self.assertIn('skipped 4',warning)
        self.assertTrue(all(day in warning for day in skipped[:3]))
        self.assertNotIn(skipped[3],warning)
        self.assertIn('…',warning)

    def test_download_and_check_jobs_show_skipped_price_warning(self):
        jobs=d.Jobs();request=dict(scope='symbols',symbols='A',start='2020-01-01',end='2020-12-31',datasets=['prices'])
        with patch.object(d,'request_json',return_value=self.prices([('2020-01-02',0),('2020-01-03',12)])):
            jobs.start('download',request);jobs.thread.join(5)
        self.assertFalse(jobs.snapshot()['job']['running'])
        self.assertIsNone(jobs.snapshot()['job']['error'])
        self.assertIn('A: skipped 1',jobs.snapshot()['job']['warning'])
        jobs.start('check',request);jobs.thread.join(5)
        self.assertIn('2020-01-02',jobs.snapshot()['job']['warning'])

    def test_bad_price_row_does_not_stop_other_stock_histories(self):
        self.o.update(symbols=['A','B'],datasets=['prices'])
        def fetch(endpoint,params,*args):
            return self.prices([('2020-01-02',0),('2020-01-03',12)]) if params['symbol']=='A' else self.prices([('2020-01-03',20)])
        with patch.object(d,'request_json',side_effect=fetch):
            report=d.download(self.o,self.emit,self.stop)
        self.assertEqual(report['prices_available'],2)
        self.assertTrue(all(row['windows']==0 for row in report['prices']))
        self.assertEqual(d.read_json(self.raw/'px/B.json')['div'],self.prices([('2020-01-03',20)]))
        self.assertIn('A: skipped 1',report['warnings'][0])

    def test_all_nonpositive_prices_record_unavailable_window_and_continue_batch(self):
        self.o.update(symbols=['A','B'],datasets=['prices'])
        batch=self.prices([('2020-01-02',0),('2020-01-03',-1)])
        def fetch(endpoint,params,*args):
            return batch if params['symbol']=='A' else self.prices([('2020-01-03',20)])
        with patch.object(d,'request_json',side_effect=fetch) as get:
            report=d.download(self.o,self.emit,self.stop)
            again=d.download(self.o,self.emit,self.stop)
        self.assertEqual(get.call_count,2,'Both completed histories must be reused on retry.')
        self.assertEqual(d.read_json(self.raw/'px/A.json')['div'],[])
        a=next(row for row in report['prices'] if row['symbol']=='A')
        self.assertEqual(a['skipped_dates'],['2020-01-02','2020-01-03'])
        self.assertEqual(a['state'],'empty');self.assertEqual(a['windows'],0)
        self.assertEqual(report['prices_available'],1)
        self.assertEqual(again['warnings'],report['warnings'])
        self.assertIn('A: skipped 2',report['warnings'][0])

    def test_all_nonpositive_response_preserves_saved_prices_and_other_keys(self):
        self.o['start']='2020-01-02'
        payload=dict(div=self.prices([('2020-01-02',12)]),extra=[dict(date='2020-01-02',price=13)])
        self.put('px/A.json',payload)
        batch=self.prices([('2020-12-31',0)])
        with patch.object(d,'request_json',return_value=batch):
            d.fill_series(None,'adjClose','prices',self.o,{},self.emit,self.stop,symbol='A')
        self.assertEqual(d.read_json(self.raw/'px/A.json'),payload)
        self.assertEqual(d.inspect(self.o)['prices'][0]['skipped_dates'],['2020-12-31'])

    def test_malformed_windows_still_fail_without_publication(self):
        payload=dict(div=self.prices([('2020-01-01',10)]))
        batches=[{},[None],[dict(date='bad',adjClose=12)],
                 [dict(date='2020-01-02')],self.prices([('2020-01-02',float('nan'))]),
                 self.prices([('2020-01-02',12),('2020-01-02',13)]),
                 self.prices([('2020-01-02',12),('2021-01-01',0)])]
        for batch in batches:
            with self.subTest(batch=batch):
                self.put('px/A.json',payload);original=(self.raw/'px/A.json').read_bytes()
                asset=d.cache_assets.SeriesAsset(self.raw/'px/A.json','adjClose',stock=True);ledger={}
                with self.assertRaisesRegex(ValueError,'px/A.json, 2020-01-01 to 2020-12-31'):
                    asset.publish(batch,'2020-01-01','2020-12-31',ledger,d.COVERAGE)
                self.assertEqual((self.raw/'px/A.json').read_bytes(),original)
                self.assertEqual(ledger,{})
                self.assertFalse(d.COVERAGE.exists())

    def test_zero_and_negative_treasury_yields_are_valid(self):
        asset=d.cache_assets.SeriesAsset(self.raw/'treasury.json','month3');ledger={}
        batch=[dict(date='2020-01-02',month3=0),dict(date='2020-01-03',month3=-.1)]
        self.assertEqual(asset.publish(batch,'2020-01-01','2020-12-31',ledger,d.COVERAGE),[])
        self.assertEqual(len(asset.rows),2)
        self.assertEqual(asset.skipped_dates(ledger),[])

    def test_transient_windows_locks_retry_receipt_and_asset_publication(self):
        asset=d.cache_assets.SeriesAsset(self.raw/'px/A.json','adjClose',stock=True)
        write=Path.write_bytes;replace=Path.replace
        failed=set()
        def locked():
            error=PermissionError(errno.EACCES,'locked');error.winerror=5;return error
        def write_once(path,content):
            if path.name=='download-coverage.json.download' and 'write' not in failed:
                failed.add('write');raise locked()
            return write(path,content)
        def replace_once(path,target):
            if target not in failed:
                failed.add(target);raise locked()
            return replace(path,target)
        with patch.object(Path,'write_bytes',write_once),patch.object(Path,'replace',replace_once),patch.object(d.cache_assets.time,'sleep') as sleep:
            asset.publish(self.prices([('2020-01-02',12)]),'2020-01-01','2020-12-31',{},d.COVERAGE)
        self.assertEqual(sleep.call_count,3)
        self.assertEqual(d.read_json(asset.path)['div'],self.prices([('2020-01-02',12)]))
        self.assertTrue(asset.checked(d.read_json(d.COVERAGE)))

    def test_persistent_windows_lock_preserves_saved_file_and_receipt(self):
        asset=d.cache_assets.SeriesAsset(self.raw/'px/A.json','adjClose',stock=True);ledger={}
        asset.publish(self.prices([('2020-01-02',12)]),'2020-01-01','2020-06-30',ledger,d.COVERAGE)
        original=asset.path.read_bytes();receipt=d.COVERAGE.read_bytes()
        error=PermissionError(errno.EACCES,'locked');error.winerror=5
        with patch.object(Path,'replace',side_effect=error) as replace,patch.object(d.cache_assets.time,'sleep') as sleep,self.assertRaises(PermissionError):
            asset.publish(self.prices([('2020-12-31',15)]),'2020-07-01','2020-12-31',ledger,d.COVERAGE)
        self.assertEqual(replace.call_count,8)
        self.assertLess(sum(call.args[0] for call in sleep.call_args_list),2)
        self.assertEqual(asset.path.read_bytes(),original)
        self.assertEqual(d.COVERAGE.read_bytes(),receipt)
        self.assertEqual(asset.checked(ledger),[['2020-01-01','2020-06-30']])

    def test_disk_full_failure_is_not_retried(self):
        with patch.object(Path,'write_bytes',side_effect=OSError(errno.ENOSPC,'full')),patch.object(d.cache_assets.time,'sleep') as sleep,self.assertRaises(OSError):
            d.write_json(self.raw/'spy-div.json',[])
        sleep.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Native Windows file sharing test')
    def test_native_windows_reader_lock_recovers_after_reader_closes(self):
        path=self.raw/'probe.json';d.write_json(path,dict(old=True))
        handle=path.open('rb')
        try:
            with patch.object(d.cache_assets.time,'sleep',side_effect=lambda delay:handle.close()) as sleep:
                d.write_json(path,dict(new=True))
            self.assertTrue(sleep.called)
            self.assertEqual(d.read_json(path),dict(new=True))
        finally:handle.close()

    def test_partial_download_resumes_from_last_saved_window(self):
        self.o.update(start='2010-01-01',end='2020-12-31');ledger={}
        published=Event();publish=d.cache_assets.SeriesAsset.publish
        def save(asset,*args,**kwargs):
            result=publish(asset,*args,**kwargs)
            published.set()
            return result
        def fetch(endpoint,params,*args):
            if params['from']=='2010-01-01':return self.prices([('2019-01-02',10)])
            self.assertTrue(published.wait(5),'The first window must be saved before the failure.')
            raise ValueError('offline')
        with patch.object(d.cache_assets.SeriesAsset,'publish',save),patch.object(d,'request_json',side_effect=fetch),self.assertRaisesRegex(ValueError,'offline'):
            d.fill_series(None,'adjClose','prices',self.o,ledger,self.emit,self.stop,symbol='A')
        with patch.object(d,'request_json',return_value=[]) as get:
            d.fill_series(None,'adjClose','prices',self.o,d.read_json(d.COVERAGE),self.emit,self.stop,symbol='A')
        self.assertEqual(get.call_count,1)
        self.assertEqual(get.call_args.args[1]['from'],'2020-01-01')

    def test_corrupt_price_repair_keeps_backup(self):
        (self.raw/'px/A.json').write_text('broken')
        with patch.object(d,'request_json',return_value=self.prices([('2020-01-02',12)])):
            d.fill_series(None,'adjClose','prices',self.o,{},self.emit,self.stop,symbol='A')
        self.assertEqual((self.raw/'archive/A.json.before-data-repair').read_text(),'broken')
        self.assertEqual(len(d.read_json(self.raw/'px/A.json')['div']),1)

    def test_deleted_or_corrupt_completed_asset_is_downloaded_again(self):
        for damage in ('missing','corrupt'):
            with self.subTest(damage=damage):
                ledger={};path=self.raw/'px/A.json';path.unlink(missing_ok=True)
                with patch.object(d,'request_json',return_value=self.prices([('2020-01-02',12)])):
                    d.fill_series(None,'adjClose','prices',self.o,ledger,self.emit,self.stop,symbol='A')
                if damage=='missing':path.unlink()
                else:path.write_text('broken')
                self.assertTrue(d.inspect(self.o)['prices'][0]['windows'])
                with patch.object(d,'request_json',return_value=self.prices([('2020-01-02',13)])) as get:
                    d.fill_series(None,'adjClose','prices',self.o,ledger,self.emit,self.stop,symbol='A')
                self.assertEqual(get.call_count,1)
                self.assertEqual(d.read_json(path)['div'][0]['adjClose'],13)

    def test_replaced_asset_drops_old_empty_windows_and_preserves_new_rows(self):
        ledger={}
        with patch.object(d,'request_json',return_value=[]):
            d.fill_series(None,'adjClose','prices',self.o,ledger,self.emit,self.stop,symbol='A')
        self.put('px/A.json',dict(div=self.prices([('2020-06-01',99)])))
        with patch.object(d,'request_json',return_value=[]) as get:
            d.fill_series(None,'adjClose','prices',self.o,ledger,self.emit,self.stop,symbol='A')
        self.assertEqual(get.call_count,2)
        self.assertEqual(d.read_json(self.raw/'px/A.json')['div'][0]['adjClose'],99)

    def test_legacy_ledger_cannot_prove_a_missing_file_is_complete(self):
        ledger={'px/A.json':[['2020-01-01','2020-12-31']]}
        with patch.object(d,'request_json',return_value=[]) as get:
            d.fill_series(None,'adjClose','prices',self.o,ledger,self.emit,self.stop,symbol='A')
        self.assertEqual(get.call_count,1)
        self.assertIn('sha256',ledger['px/A.json'])

    def test_financial_rows_have_one_validation_and_eligibility_policy(self):
        good=dict(date='2019-01-01',marketCap=100e6,enterpriseValue=200e6,evToEBITDA=10)
        path=self.raw/'metrics.jsonl';path.write_text(json.dumps(dict(symbol='A',rows=[good,None,'broken'])))
        records,invalid=d.financial_records()
        self.assertEqual(invalid,1);self.assertEqual(records['A']['rows'],[good])
        self.assertEqual(d.target_symbols({**self.o,'scope':'financials'},d.universe_rows(),records),['A'])
        self.o['datasets']=['financials']
        with patch.object(d,'request_json',return_value=[]):d.download(self.o,self.emit,self.stop)
        records,invalid=d.financial_records()
        self.assertEqual(invalid,0);self.assertEqual(records['A']['rows'],[good])
        self.assertEqual(d.r.books.statements(records,d.universe_rows())['A'][0]['ebitda'],20e6)

    def test_out_of_order_publication_leaves_internal_window_missing(self):
        path=self.raw/'px/A.json';asset=d.cache_assets.SeriesAsset(path,'adjClose',stock=True);ledger={}
        asset.publish(self.prices([('2020-01-02',12)]),'2020-01-01','2020-12-31',ledger,d.COVERAGE)
        asset.publish(self.prices([('2000-01-03',6)]),'2000-01-01','2009-12-31',ledger,d.COVERAGE)
        resumed=d.cache_assets.SeriesAsset(path,'adjClose',stock=True)
        self.assertEqual(resumed.missing(date(2000,1,1),date(2020,12,31),ledger),[(date(2010,1,1),date(2019,12,31))])

    def test_failed_asset_replace_retains_previous_coverage_and_holes(self):
        path=self.raw/'px/A.json';asset=d.cache_assets.SeriesAsset(path,'adjClose',stock=True);ledger={}
        asset.publish(self.prices([('2000-01-03',6)]),'2000-01-01','2009-12-31',ledger,d.COVERAGE)
        asset.publish(self.prices([('2020-01-02',12)]),'2020-01-01','2020-12-31',ledger,d.COVERAGE)
        replace=Path.replace
        def fail_asset(source,target):
            if target==path:raise OSError('Interrupted publication')
            return replace(source,target)
        with patch.object(Path,'replace',fail_asset),self.assertRaises(OSError):
            asset.publish(self.prices([('2010-01-04',9)]),'2010-01-01','2019-12-31',ledger,d.COVERAGE)
        resumed=d.cache_assets.SeriesAsset(path,'adjClose',stock=True)
        self.assertEqual(resumed.missing(date(2000,1,1),date(2020,12,31),d.read_json(d.COVERAGE)),[(date(2010,1,1),date(2019,12,31))])

    def test_price_fetches_are_parallel_and_publication_has_one_writer(self):
        import threading
        self.o.update(start='2000-01-01',end='2020-12-31')
        writers=[];fetchers=[];lock=threading.Lock();gate=threading.Barrier(3)
        store=d.cache_assets.SeriesAsset._store
        def record(asset,*args,**kwargs):writers.append(threading.get_ident());return store(asset,*args,**kwargs)
        def fetch(endpoint,params,stop,client):
            with lock:fetchers.append(threading.get_ident())
            gate.wait(3)
            return self.prices([(params['from'],10)])
        with patch.object(d,'request_json',side_effect=fetch),patch.object(d.cache_assets.SeriesAsset,'_store',record):
            d.fill_series(None,'adjClose','prices',self.o,{},self.emit,self.stop,symbol='A')
        self.assertEqual(len(set(fetchers)),3)
        self.assertEqual(set(writers),{threading.get_ident()})
        self.assertEqual(d.inspect(self.o)['prices'][0]['windows'],0)

    def test_gzip_transport_publishes_on_owner_and_reuses_saved_windows(self):
        import threading
        import urllib.parse
        self.o.update(start='2000-01-01',end='2020-12-31',datasets=['prices'])
        fmp_download.KEY_PATH.write_text('test-key')
        writers=[];fetchers=[];responses=[];gate=threading.Barrier(3)
        store=d.cache_assets.SeriesAsset._store
        def record(asset,*args,**kwargs):writers.append(threading.get_ident());return store(asset,*args,**kwargs)
        class Response:
            status=200
            def __init__(response,start):
                response.body=io.BytesIO(gzip.compress(json.dumps(self.prices([(start,10)])).encode()))
                response.closed=False
            def read1(response,size):return response.body.read1(size)
            def getheader(response,key):return 'gzip' if key=='Content-Encoding' else None
            def close(response):response.closed=True
        class Connection:
            sock=None
            def __init__(connection,*args,**kwargs):pass
            def request(connection,method,path,headers):
                self.assertEqual(headers['Accept-Encoding'],'gzip')
                connection.start=urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)['from'][0]
                fetchers.append(threading.get_ident());gate.wait(3)
            def getresponse(connection):
                response=Response(connection.start);responses.append(response);return response
            def close(connection):pass
        with patch.object(d.fmp_download.http.client,'HTTPSConnection',Connection),patch.object(d.cache_assets.SeriesAsset,'_store',record):
            report=d.download(self.o,self.emit,self.stop)
        self.assertEqual(len(set(fetchers)),3);self.assertEqual(set(writers),{threading.get_ident()})
        self.assertEqual(report['prices'][0]['windows'],0);self.assertTrue(all(r.closed for r in responses))
        saved=(self.raw/'px/A.json').read_bytes();receipt=d.COVERAGE.read_bytes()
        fmp_download.KEY_PATH.unlink()
        with patch.object(d.fmp_download.http.client,'HTTPSConnection',side_effect=AssertionError('No network for saved windows')):
            report=d.download(self.o,self.emit,self.stop)
        self.assertFalse(report['api_key_present']);self.assertEqual(report['prices'][0]['windows'],0)
        self.assertEqual((self.raw/'px/A.json').read_bytes(),saved);self.assertEqual(d.COVERAGE.read_bytes(),receipt)

    def test_close_during_download_joins_fetchers_and_stops_submission(self):
        import threading
        self.o.update(start='1990-01-01',end='2020-12-31')
        entered=threading.Event();release=threading.Event();calls=[];jobs=d.Jobs()
        def fetch(endpoint,params,stop,client):
            calls.append(params);entered.set();release.wait(3);stop();return []
        with patch.object(d,'request_json',side_effect=fetch):
            jobs.start('download',dict(scope='symbols',symbols='A',start=self.o['start'],end=self.o['end'],datasets=['prices']))
            self.assertTrue(entered.wait(3));jobs.cancel.set();release.set();jobs.close()
        self.assertFalse(jobs.thread.is_alive());self.assertIn('Cancelled',jobs.snapshot()['job']['message'])
        self.assertLessEqual(len(calls),d.fmp_download.WORKERS)
        self.assertFalse(any(t.name.startswith('fmp') and t.is_alive() for t in threading.enumerate()))

    def test_close_permanently_latches_admission_before_late_start(self):
        jobs=d.Jobs();jobs.close()
        for action in ('check','download','rebuild'):
            with self.assertRaisesRegex(ValueError,'stopping'):jobs.start(action,{})
        self.assertTrue(jobs.cancel.is_set());self.assertIsNone(jobs.thread)

    def test_start_paused_before_admission_cannot_clear_shutdown_cancellation(self):
        from threading import Thread
        jobs=d.Jobs();entered=Event();release=Event();errors=[];original=d.options
        def options(request):
            value=original(request);entered.set();release.wait(3);return value
        def start():
            try:jobs.start('rebuild',{})
            except ValueError as error:errors.append(str(error))
        with patch.object(d,'options',side_effect=options),patch.object(jobs,'work') as work:
            thread=Thread(target=start);thread.start();self.assertTrue(entered.wait(3))
            jobs.close();release.set();thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(len(errors),1)
        self.assertTrue(jobs.cancel.is_set());self.assertIsNone(jobs.thread);work.assert_not_called()

    def test_metrics_append_handles_missing_final_newline(self):
        self.o.update(scope='symbols',symbols=['B'],datasets=['financials'])
        with patch.object(d,'request_json',return_value=[]):d.download(self.o,self.emit,self.stop)
        records,invalid=d.financial_records()
        self.assertEqual(set(records),{'A','B'});self.assertEqual(invalid,0)

    def test_invalid_financial_lines_are_reported_and_not_overwritten(self):
        path=self.raw/'metrics.jsonl';path.write_text('broken\n')
        report=d.inspect(self.o)
        self.assertEqual(report['invalid_financial_lines'],1)
        self.o['datasets']=['financials']
        with patch.object(d,'request_json',return_value=[]):d.download(self.o,self.emit,self.stop)
        self.assertEqual((self.raw/'archive/metrics.jsonl.before-data-repair').read_text(),'broken\n')
        self.assertEqual(d.financial_records()[1],0)

    def test_default_scope_is_cached_prices_through_today(self):
        default=d.options({})
        self.assertEqual((default['scope'],default['start'],default['end']),('cached','1995-01-01',str(date.today())))
        (self.raw/'px'/'A.json').write_text('{}')
        self.assertEqual(d.target_symbols(default,d.universe_rows(),{}),['A'])
        with self.assertRaisesRegex(ValueError,'stock group'):d.options(dict(scope='baseline'))

    def test_invalid_symbol_and_option_validation(self):
        for request in [dict(scope='symbols',symbols='../secret'),dict(scope='symbols',symbols=''),dict(start='2021-01-01',end='2020-01-01'),dict(datasets=[]),dict(arbitrary_path='/tmp')]:
            with self.subTest(request=request),self.assertRaises(ValueError):d.options(request)
        self.o['symbols']=['UNKNOWN']
        with self.assertRaisesRegex(ValueError,'absent'):d.inspect(self.o)

    def test_provider_failure_does_not_expose_payload_or_url(self):
        with patch.object(d.fmp_download.Client,'_once',return_value=(403,b'sensitive response',None)),self.assertRaises(ValueError) as error:
            d.request_json('key-metrics',{},self.stop)
        self.assertNotIn('secret',str(error.exception));self.assertNotIn('https:',str(error.exception))

    def test_audit_does_not_read_key_or_contact_provider(self):
        report=d.inspect(self.o)
        self.assertEqual(report['missing_financials'],['B'])
        self.assertEqual(report['prices'][0]['state'],'missing')
        self.assertEqual(report['missing_ratio_inputs']['income-statement'],['A'])

    def test_rebuild_runs_offline_dependency_chain_then_checks(self):
        jobs=d.Jobs();calls=[]
        with patch.object(daily,'prepare',side_effect=lambda:calls.append('prepare')),patch.object(d.subprocess,'run',side_effect=lambda *a,**kw:calls.append('build')),patch.object(d,'inspect',return_value={'checked_at':'new'}) as inspect:
            jobs.start('rebuild',{});jobs.thread.join(3)
        self.assertEqual(calls,['prepare','build']);self.assertTrue(jobs.rebuilt)
        self.assertFalse(jobs.snapshot()['job']['running']);inspect.assert_called_once()

    def test_cancel_queued_job_does_not_touch_data(self):
        from contextlib import contextmanager
        gate=Event();entered=Event();jobs=d.Jobs()
        @contextmanager
        def queued(timeout=30):
            entered.set();gate.wait(3);yield
        with patch.object(d.cache_access,'access',side_effect=queued),patch.object(d,'inspect') as inspect:
            jobs.start('check',{});self.assertTrue(entered.wait(3));jobs.cancel_job();gate.set();jobs.thread.join(3)
        inspect.assert_not_called();self.assertIn('Cancelled',jobs.snapshot()['job']['message'])

    def test_cancel_while_another_owner_holds_the_cache_ends_promptly(self):
        owner=d.cache_access.WorkspaceAccess(self.root/'held.lock');attempted=Event();jobs=d.Jobs()
        def access(timeout=30):
            attempted.set();return owner.hold(timeout)
        with patch.object(d.cache_access,'access',side_effect=access),owner.hold():
            jobs.start('check',{});self.assertTrue(attempted.wait(3))
            began=time.monotonic();jobs.cancel_job();jobs.thread.join(3)
            self.assertFalse(jobs.thread.is_alive());self.assertLess(time.monotonic()-began,2)
        self.assertEqual(jobs.snapshot()['job']['message'],'Cancelled before data admission.')
        self.assertFalse(jobs.snapshot()['job']['running'])

    def test_jobs_single_writer_cancel_and_sanitized_failure(self):
        gate=Event();entered=Event();jobs=d.Jobs()
        def inspect(*args):
            entered.set();gate.wait(3);return {'checked_at':'test'}
        with patch.object(d,'inspect',side_effect=inspect):
            jobs.start('check',dict(scope='symbols',symbols='A'))
            self.assertTrue(entered.wait(3))
            with self.assertRaisesRegex(ValueError,'already running'):jobs.start('check',{})
            gate.set();jobs.thread.join(3)
        self.assertFalse(jobs.snapshot()['job']['running'])
        self.assertEqual(jobs.snapshot()['report']['checked_at'],'test')
        with patch.object(d,'inspect',side_effect=RuntimeError('https://x/?apikey=secret')):
            jobs.start('check',{});jobs.thread.join(3)
        self.assertNotIn('secret',jobs.snapshot()['job']['error'])
        jobs.cancel.set()
        with self.assertRaises(d.Cancelled):jobs.stop()

    def test_unexpected_job_failure_has_persistent_sanitized_trace(self):
        path=d.diagnostics.configure(self.root/'logs')
        self.addCleanup(d.diagnostics.close)
        jobs=d.Jobs()
        with patch.object(d,'inspect',side_effect=RuntimeError('https://provider.invalid/?apikey=PRIVATE-CANARY')):
            jobs.start('check',dict(scope='symbols',symbols='A'));jobs.thread.join(3)
        state=jobs.snapshot()
        self.assertIn('development log',state['job']['error'])
        self.assertTrue(state['log_file'].endswith('.log'))
        content=path.read_text()
        self.assertIn('data.failed',content);self.assertIn('RuntimeError',content)
        self.assertIn('data_manager.py',content)
        job,=[record for record in d.diagnostics.records(self.root/'logs') if record['event']=='data.job']
        self.assertEqual((job['action'],job['outcome'],job['error']),('check','failed','RuntimeError'))
        self.assertIn('admission',job['stages'])
        self.assertNotIn('PRIVATE-CANARY',content);self.assertNotIn('https:',content)


class HttpTests(unittest.TestCase):
    def handler(self,method,path,body=None,origin=None,client='127.0.0.1',host='127.0.0.1:3000'):
        handler=object.__new__(serve.Handler)
        handler.path=path;handler.client_address=(client,5555)
        encoded=json.dumps(body or {}).encode();handler.rfile=io.BytesIO(encoded)
        handler.headers={'Host':host,'Content-Length':str(len(encoded))}
        if origin:handler.headers['Origin']=origin
        results=[];handler.reply=lambda status,payload:results.append((status,payload))
        if method=='POST':serve.data.data_request(handler,serve.DATA_JOBS)
        else:results.append(serve.data.data_allowed(handler))
        return results

    def test_only_local_same_origin_may_manage_data(self):
        for kwargs in [dict(client='192.168.1.2'),dict(origin='http://evil.example'),dict(host='evil.example:3000')]:
            with self.subTest(kwargs=kwargs),patch.object(serve.DATA_JOBS,'start') as start:
                self.assertEqual(self.handler('POST','/api/data/check',**kwargs)[0][0],403);start.assert_not_called()
        self.assertEqual(self.handler('GET','/',host='localhost:3000'),[True])

    def test_data_actions_are_allowlisted(self):
        with patch.object(serve.DATA_JOBS,'start',return_value={'job':{}}) as start:
            self.assertEqual(self.handler('POST','/api/data/check',dict(scope='cached'))[0][0],202)
            start.assert_called_once_with('check',dict(scope='cached'))
            self.assertEqual(self.handler('POST','/api/data/arbitrary')[0][0],404)
            self.assertEqual(self.handler('POST','/api/data/prepare')[0][0],404)
        self.assertNotIn('candidate',serve.DATA_JOBS.snapshot())

    def test_recovery_page_does_not_need_build_or_database(self):
        page=serve.data.data_page()
        self.assertIn('Download missing data',page)
        self.assertNotIn('__DATA_SCRIPT__',page)
        self.assertIn('/api/data/',page)


if __name__=='__main__':unittest.main()
