"""Historical ratio formulas, temporal isolation and resumable annual assets."""

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import financial_inputs as f
from backtest.financial import metrics as metrics
from website.server import data_manager as d
class FinancialTests(unittest.TestCase):
    def reports(self):
        reports={f'{year}-12-31':dict(epsDiluted=eps,totalStockholdersEquity=80e6) for year,eps in [(2016,1),(2017,1.1),(2018,1.2),(2019,1.728)]}
        reports['2019-12-31'].update(netIncome=20e6,revenue=100e6,totalStockholdersEquity=120e6,freeCashFlow=15e6,totalDebt=60e6,totalCurrentAssets=40e6,totalCurrentLiabilities=20e6,ebit=30e6,interestExpense=5e6)
        return reports

    def values(self,reports):
        return metrics.financial_values(dict(fiscal='2019-12-31',market_cap=200e6),reports)

    def test_formulas_screen_date_cap_and_units(self):
        values=self.values(self.reports())
        for field,value in dict(pe=10,pb=200/120,fcf=15,fcf_yield=7.5,price_fcf=200/15,profit_margin=20,peg=.5,roe=20,current_ratio=2,interest_coverage=6,debt_equity=.5).items():
            self.assertAlmostEqual(values[field],value,msg=field)
        larger=metrics.financial_values(dict(fiscal='2019-12-31',market_cap=400e6),self.reports())
        self.assertEqual(larger['pe'],20);self.assertEqual(larger['fcf_yield'],3.75)

    def test_future_missing_consecutive_years_and_nonpositive_denominators(self):
        reports=self.reports();expected=self.values(reports)
        reports['2020-12-31']=dict(netIncome=1,epsDiluted=1000,totalStockholdersEquity=1)
        self.assertEqual(self.values(reports),expected)
        del reports['2017-12-31'];self.assertNotIn('peg',self.values(reports))
        del reports['2018-12-31'];self.assertNotIn('roe',self.values(reports))
        reports['2019-12-31'].update(netIncome=-1,totalStockholdersEquity=-1,interestExpense=0,totalCurrentLiabilities=0,freeCashFlow=-1)
        values=self.values(reports)
        for key in ('pe','pb','peg','roe','interest_coverage','current_ratio','debt_equity','price_fcf'):self.assertNotIn(key,values)
        self.assertLess(values['profit_margin'],0);self.assertLess(values['fcf_yield'],0)
        self.assertEqual(self.values({}),{})

    def test_operating_spread_equal_year_weights_current_sales_ev_and_units(self):
        observation=dict(fiscal='2019-12-31',enterprise_value=200e6)
        reports={f'{year}-12-31':dict(revenue=sales,operatingIncome=income,ebit=999e6)
                 for year,sales,income in [(2017,50e6,5e6),(2018,100e6,20e6),(2019,200e6,60e6)]}
        # Mean margin = (10% + 20% + 30%) / 3 = 20%, not sales-weighted.
        self.assertAlmostEqual(metrics.operating_yield_spread(observation,reports,4),16)
        self.assertAlmostEqual(metrics.operating_yield_spread(dict(observation,enterprise_value=400e6),reports,4),6)
        reports['2020-12-31']=dict(revenue=1e12,operatingIncome=1e12)
        reports['2019-12-30']=dict(revenue=1e12,operatingIncome=1e12)
        self.assertAlmostEqual(metrics.operating_yield_spread(observation,reports,4),16)
        for row in reports.values():row['operatingIncome']=-row['revenue']*.1
        self.assertAlmostEqual(metrics.operating_yield_spread(observation,reports,0),-10)
        self.assertAlmostEqual(metrics.operating_yield_spread(observation,reports,-1),-9)

    def test_operating_spread_missing_inputs_never_fill_from_newer_reports(self):
        observation=dict(fiscal='2019-12-31',enterprise_value=200e6)
        reports={f'{year}-12-31':dict(revenue=100e6,operatingIncome=10e6)
                 for year in (2017,2018,2019,2020)}
        self.assertIsNone(metrics.operating_yield_spread(observation,reports,None))
        for ev in (0,-1,None):
            self.assertIsNone(metrics.operating_yield_spread(dict(observation,enterprise_value=ev),reports,4))
        for field in ('revenue','operatingIncome'):
            for year in (2017,2018,2019):
                missing={day:dict(row) for day,row in reports.items()}
                del missing[f'{year}-12-31'][field]
                self.assertIsNone(metrics.operating_yield_spread(observation,missing,4))
        for revenue in (0,-1):
            reports['2018-12-31']['revenue']=revenue
            self.assertIsNone(metrics.operating_yield_spread(observation,reports,4))
        del reports['2018-12-31']
        self.assertIsNone(metrics.operating_yield_spread(observation,reports,4))

    def test_operating_income_is_validated_and_conflicting_variants_stay_absent(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder);ledger={};endpoint='income-statement'
            row=dict(date='2019-12-31',reportedCurrency='USD',revenue=100,operatingIncome=10)
            with self.assertRaises(ValueError):
                f.publish(raw,'A',endpoint,[dict(row,operatingIncome='invalid')],ledger,raw/'coverage.json')
            f.publish(raw,'A',endpoint,[row,dict(row,operatingIncome=20)],ledger,raw/'coverage.json')
            self.assertEqual(f.history(raw,'A'),{'2019-12-31':{'revenue':100}})

    def test_asset_receipts_empty_reuse_tamper_repair_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder);ledger={};receipt=raw/'coverage.json';endpoint='income-statement'
            f.publish(raw,'A',endpoint,[],ledger,receipt)
            self.assertTrue(f.completed(raw,'A',endpoint,ledger))
            path=f.asset_path(raw,'A',endpoint);path.write_text('{}')
            self.assertFalse(f.completed(raw,'A',endpoint,ledger))
            rows=[dict(date='2019-12-31',symbol='A',period='FY',reportedCurrency='USD',netIncome=20)]
            f.publish(raw,'A',endpoint,rows,ledger,receipt)
            self.assertTrue(path.with_suffix('.json.before-repair').exists())
            self.assertEqual(f.history(raw,'A')['2019-12-31']['netIncome'],20)
            before=path.read_bytes()
            with self.assertRaises(ValueError):f.publish(raw,'A',endpoint,[dict(rows[0],netIncome=float('nan'))],ledger,receipt)
            self.assertEqual(path.read_bytes(),before)
            with patch.object(f.cache_assets,'publish_bytes',side_effect=PermissionError):
                with self.assertRaises(PermissionError):f.publish(raw,'A',endpoint,rows,ledger,receipt)
            self.assertTrue(f.completed(raw,'A',endpoint,ledger))
            path.unlink();self.assertFalse(f.completed(raw,'A',endpoint,ledger))

    def test_damaged_asset_salvages_reports_and_repeated_publication_keeps_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder);ledger={};endpoint='income-statement';receipt=raw/'coverage.json'
            good=dict(date='2019-12-31',reportedCurrency='USD',netIncome=20,extraField=99)
            f.publish(raw,'A',endpoint,[good],ledger,receipt)
            path=f.asset_path(raw,'A',endpoint)
            asset=json.loads(path.read_text());asset['rows'].append('damaged');path.write_text(json.dumps(asset))
            f.publish(raw,'A',endpoint,[],ledger,receipt)
            self.assertEqual(f.read(raw,'A',endpoint)[0],[good])
            original=f.cache_assets.publish_bytes
            def deny_asset(destination,content):
                if destination==path:raise PermissionError()
                original(destination,content)
            for _ in range(2):
                with patch.object(f.cache_assets,'publish_bytes',side_effect=deny_asset):
                    with self.assertRaises(PermissionError):f.publish(raw,'A',endpoint,[dict(date='2018-12-31',reportedCurrency='USD',netIncome=10)],ledger,receipt)
                self.assertTrue(f.completed(raw,'A',endpoint,ledger))

    def test_full_payload_preserves_unknown_fields_nulls_currency_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder);ledger={}
            rows=[dict(date='2019-12-31',symbol='A',period='FY',reportedCurrency='USD',netIncome=20,
                       filingDate='2020-02-10',acceptedDate='2020-02-10 12:30:00',newProviderField=42,
                       providerNull=None,nestedMetadata={'label':'unchanged'}),
                  dict(date='2018-12-31',symbol='A',period='FY',reportedCurrency='EUR',netIncome=15)]
            f.publish(raw,'A','income-statement',rows,ledger,raw/'coverage.json')
            saved=json.loads(f.asset_path(raw,'A','income-statement').read_text())
            self.assertEqual(saved['rows'],rows)
            self.assertEqual(f.read(raw,'A','income-statement')[0],rows)
            self.assertEqual(f.history(raw,'A'),{'2019-12-31':{'netIncome':20}})
            self.assertTrue(f.completed(raw,'A','income-statement',ledger))
            metrics_rows=[dict(date='2019-12-31',otherMetric=123,nullable=None)]
            record=d.cache_assets.financial_record('A',metrics_rows)
            self.assertEqual(record['rows'],metrics_rows);self.assertTrue(record['full_response'])

    def test_duplicate_dates_preserve_all_rows_and_only_prepare_agreed_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder);ledger={};receipt=raw/'coverage.json'
            common=dict(date='2019-12-31',symbol='A',period='FY',reportedCurrency='USD')
            rows=[dict(common,netIncome=20,revenue=100,epsDiluted=None,filingDate='2020-02-01'),
                  dict(common,netIncome=30,revenue=100,epsDiluted=2,filingDate='2020-03-01'),
                  dict(common,reportedCurrency='EUR',netIncome=999,revenue=999)]
            rows.append(dict(rows[0]))
            for endpoint in f.ENDPOINTS:
                f.publish(raw,'A',endpoint,rows,ledger,receipt)
                self.assertEqual(f.read(raw,'A',endpoint)[0],rows)
                self.assertTrue(f.completed(raw,'A',endpoint,ledger))
            prepared=f.history(raw,'A')
            self.assertEqual(prepared,{'2019-12-31':dict(revenue=100,epsDiluted=2)})
            f.publish(raw,'A','income-statement',list(reversed(rows)),ledger,receipt)
            self.assertEqual(f.history(raw,'A'),prepared)
            # A repair keeps every distinct prior variant, rather than overwriting
            # the entire fiscal date with a single incoming report.
            f.publish(raw,'A','income-statement',[dict(common,revenue=100,newField=42)],ledger,receipt)
            saved=f.read(raw,'A','income-statement')[0]
            self.assertTrue(all(row in saved for row in rows))
            self.assertEqual(f.history(raw,'A'),prepared)

    def test_download_with_duplicate_dates_finishes_and_retry_makes_no_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder);(raw/'universe.json').write_text(json.dumps([dict(symbol='A')]))
            rows=[dict(date='2019-12-31',symbol='A',period='FY',reportedCurrency='USD',netIncome=20)]*2
            (raw/'metrics.jsonl').write_text(json.dumps(d.cache_assets.financial_record('A',rows)))
            o=d.options(dict(scope='symbols',symbols='A',datasets=['fundamentals']))
            with patch.object(d,'RAW',raw),patch.object(d,'COVERAGE',raw/'coverage.json'),patch.object(d,'inspect',return_value={}),patch.object(d,'request_json',return_value=rows) as get:
                d.download(o,lambda **kw:None,lambda:None)
                self.assertEqual(get.call_count,4)
                d.download(o,lambda **kw:None,lambda:None)
                self.assertEqual(get.call_count,4)
                for endpoint in f.ENDPOINTS:self.assertEqual(f.read(raw,'A',endpoint)[0],rows)

    def test_full_key_metrics_are_reused_without_another_request(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder);(raw/'universe.json').write_text(json.dumps([dict(symbol='A')]))
            rows=[dict(date='2019-12-31',reportedCurrency='USD',futureMetric=123)]
            (raw/'metrics.jsonl').write_text(json.dumps(d.cache_assets.financial_record('A',rows)))
            o=d.options(dict(scope='symbols',symbols='A',datasets=['fundamentals']))
            with patch.object(d,'RAW',raw),patch.object(d,'COVERAGE',raw/'coverage.json'),patch.object(d,'inspect',return_value={}),patch.object(d,'request_json',return_value=[]) as get:
                d.download(o,lambda **kw:None,lambda:None)
                self.assertEqual(get.call_count,4)
                self.assertNotIn('key-metrics',[call.args[0] for call in get.call_args_list])
                self.assertEqual(f.read(raw,'A','key-metrics')[0],rows)

    def test_download_fills_only_missing_endpoints(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder);(raw/'universe.json').write_text(json.dumps([dict(symbol='A')]))
            (raw/'metrics.jsonl').write_text(json.dumps(dict(symbol='A',rows=[])))
            o=d.options(dict(scope='symbols',symbols='A',datasets=['fundamentals']))
            with patch.object(d,'RAW',raw),patch.object(d,'COVERAGE',raw/'coverage.json'),patch.object(d,'inspect',return_value={}),patch.object(d,'request_json',return_value=[]) as get:
                d.download(o,lambda **kw:None,lambda:None)
                self.assertEqual(get.call_count,5)
                d.download(o,lambda **kw:None,lambda:None)
                self.assertEqual(get.call_count,5)
                f.asset_path(raw,'A','income-statement').unlink()
                d.download(o,lambda **kw:None,lambda:None)
                self.assertEqual(get.call_count,6)


if __name__=='__main__':unittest.main()
