"""Foreign cache acquisition and detached browser projections, with private inputs."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from contextlib import ExitStack
from datetime import date
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from backtest import screening
from backtest.application import scalar_execution, strategy_requests as s
from backtest.inputs import book_store, cache_assets, fact_view, financial_inputs, fmp_download, market
from backtest.runtime import cache_access
from website.rendering.data import load_screening_data
from website.server import data_manager as data, data_refresh
import book_store_fixture as store
from test_strategy_requests import pipeline, rank_step


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.raw=self.root/'raw';self.raw.mkdir()
        for module in (data,market):self.context.enter_context(patch.object(module,'RAW',self.raw))
        self.context.enter_context(patch.object(data,'ROOT',self.root))
        self.context.enter_context(patch.object(data,'COVERAGE',self.raw/'download-coverage.json'))
        self.context.enter_context(patch.object(data,'derived_status',return_value=[]))
        self.context.enter_context(patch.object(cache_access,'workspace',cache_access.WorkspaceAccess(self.root/'cache.lock')))
        self.calls=[]

    def provider(self,endpoint,params,*args):
        self.calls.append((endpoint,params))
        if endpoint=='company-screener':
            return [dict(symbol='0700.HK',companyName='Tencent',exchangeShortName='HKSE',currency='HKD',isActivelyTrading=True)]
        if endpoint in financial_inputs.ENDPOINTS:
            return [dict(date='2019-12-31',reportedCurrency='CNY',period='FY',weightedAverageShsOut=100,
                         revenue=500,providerExtra='preserved'),
                    dict(date='2018-12-31',reportedCurrency='CNY',period='FY',providerExtra='older')]
        field='month3' if endpoint=='treasury-rates' else 'adjClose' if endpoint.endswith('dividend-adjusted') else 'close'
        return [dict(date='2020-01-02',**{field:10})] if params['from']<='2020-01-02'<=params['to'] else []

    def test_selected_market_download_uses_existing_receipts_and_shared_annual_files(self):
        original=b'{"symbol":"US","rows":[]}\n';(self.raw/'metrics.jsonl').write_bytes(original)
        options=data.options(dict(market='hk',scope='symbols',symbols='0700.HK',start='2020-01-01',end='2020-01-03'))
        with patch.object(data,'request_json',side_effect=self.provider):
            report=data.download(options,lambda **kw:None,lambda:None)
            first=len(self.calls)
            data.download(options,lambda **kw:None,lambda:None)
        self.assertEqual(len(self.calls),first,'Completed foreign assets reuse the ordinary receipts.')
        self.assertEqual((self.raw/'metrics.jsonl').read_bytes(),original)
        ledger=cache_assets.read_json(data.COVERAGE,{})
        for key in ('px/0700.HK.json','px-full/0700.HK.json','markets/hk/calendar.json','fx/USDHKD.json','fx/USDCNY.json'):
            self.assertIn(key,ledger)
        annual,_=financial_inputs.read(self.raw,'0700.HK','income-statement')
        self.assertEqual([row['providerExtra'] for row in annual],['preserved','older'])
        self.assertTrue(any(endpoint=='historical-price-eod/full' and params.get('symbol')=='0700.HK' for endpoint,params in self.calls))
        self.assertEqual(report['options']['market'],'hk')
        self.assertEqual(report['prices'][0]['native_windows'],0)
        self.assertTrue(any(asset['name']=='USDCNY daily FX' for asset in report['assets']))
        self.assertFalse({'key-metrics','ratios'} & {endpoint for endpoint,_ in self.calls})
        self.assertEqual(set(report['missing_ratio_inputs']),{'income-statement','balance-sheet-statement','cash-flow-statement'})
        self.assertEqual(report['missing_financials'],[])
        self.assertEqual(next(asset['count'] for asset in report['assets'] if asset['name']=='Annual financials'),2)

    def test_managed_foreign_reports_skip_weekdays_and_sweep_delisted(self):
        options=data.options(dict(market='hk',scope='financials',start='2020-01-01',end='2020-01-03'))
        cache_assets.write_json(market.universe_path(self.raw,'hk'),[
            dict(symbol=symbol,listed=listed,market='hk',currency='HKD') for symbol,listed in [('0700.HK',True),('0001.HK',False)]])
        financial_inputs.publish(self.raw,'0001.HK','income-statement',[dict(date='2019-12-31',reportedCurrency='CNY')],{},data.COVERAGE)
        for due,sweep,expected in [(False,False,set()),(True,False,{'0700.HK'}),(True,True,{'0700.HK','0001.HK'})]:
            with self.subTest(due=due,sweep=sweep):
                self.calls.clear();progress=data_refresh.Progress({},scope=options)
                with patch.object(data,'request_json',side_effect=self.provider),fmp_download.Client() as client:
                    success=data.download_market(options,progress.emit,lambda:None,client,refresh=True,refresh_state=progress.state,
                                                 reports=dict(due=due,sweep=sweep))
                self.assertTrue(success)
                for endpoint in data.FOREIGN_STATEMENTS:
                    self.assertEqual({params['symbol'] for name,params in self.calls if name==endpoint},expected)
                self.assertTrue(any(params.get('symbol')=='USDCNY' for _,params in self.calls))
                if not due:self.assertTrue(progress.state['work']['statements']['skipped'])

    def test_market_only_primary_update_retains_us_managed_additions(self):
        jobs=data.Jobs()
        with patch.object(data_refresh,'run',return_value=dict(ready=True,error=None)) as update:
            jobs.start('update',dict(market='us'));jobs.thread.join(5)
        selected=update.call_args.kwargs['scope']
        self.assertEqual(selected['market'],'us');self.assertTrue(selected['managed'])
        progress=data_refresh.Progress({},scope=selected)
        with patch.object(data,'fetch_universe',return_value={'A':dict(symbol='A',listed=True)}),patch.object(data,'request_json',side_effect=self.provider),fmp_download.Client() as client:
            data_refresh.download(progress.state,date(2020,1,3),progress.emit,lambda:None,client,progress)
        self.assertTrue(cache_assets.SeriesAsset(market.cache_path_for('A'),'adjClose',stock=True).rows)

    def test_refresh_retry_keeps_new_foreign_stock_in_existing_pending_state(self):
        options=data.options(dict(market='hk',start='2020-01-01',end='2020-01-03'))
        state=data_refresh.Progress({},scope=options).state
        failed=False
        def interrupted(endpoint,params,*args):
            nonlocal failed
            if endpoint.endswith('dividend-adjusted') and params.get('symbol')=='0700.HK' and not failed:
                failed=True;raise ValueError('offline')
            if endpoint=='cash-flow-statement':return []
            return self.provider(endpoint,params,*args)
        with patch.object(data,'request_json',side_effect=interrupted),fmp_download.Client() as client:
            data.download_market(options,lambda **kw:None,lambda:None,client,refresh=True,refresh_state=state)
        self.assertGreater(state['failed_assets'],0)
        self.assertEqual(state['pending_markets']['hk'],['0700.HK'])
        state['failed_assets']=0
        with patch.object(data,'request_json',side_effect=interrupted),fmp_download.Client() as client:
            data.download_market(options,lambda **kw:None,lambda:None,client,refresh=True,refresh_state=state)
        self.assertEqual(state['failed_assets'],0)
        self.assertEqual(state['pending_markets']['hk'],[])
        self.assertTrue(cache_assets.SeriesAsset(market.cache_path_for('0700.HK'),'adjClose',stock=True).rows)
        self.assertFalse({'key-metrics','ratios'} & {endpoint for endpoint,_ in self.calls})

    def test_refresh_preserves_endpoint_and_symbol_for_native_calendar_and_fx(self):
        options=data.options(dict(market='jp',scope='symbols',symbols='7203.T',start='2020-01-01',end='2020-01-03'))
        specs=data.market_series('jp',['7203.T'],{'JPY'})
        state=dict(scope=options,failed_assets=0)
        with patch.object(data,'request_json',side_effect=self.provider),fmp_download.Client() as client:
            data_refresh.refresh_series(specs,date(2020,1,3),{},lambda **kw:None,lambda:None,client,state)
        self.assertEqual(state['failed_assets'],0)
        symbols={params.get('symbol') for endpoint,params in self.calls if endpoint=='historical-price-eod/full'}
        self.assertEqual(symbols,{'^N225','USDJPY','7203.T'})
        self.assertTrue(market.calendar_path(self.raw,'jp').exists())
        self.assertTrue(market.native_path(self.raw,'7203.T').exists())

    def test_private_website_build_runs_form_restore_and_manual_market_checks(self):
        from website.rendering import build as rendering
        from website.rendering.data import PageData
        with store.connection() as db:
            for code,exchange in [('us','NYSE'),('hk','HKSE'),('jp','JPX')]:
                if code=='us':store.session(db,'2015-01-05',100)
                else:db.research.execute('INSERT INTO local_sessions VALUES(?,?)',(code,'2015-01-05'))
                for number in range(20):
                    symbol=code+str(number)
                    store.company(db,symbol,exchange=exchange,sector=code+' sector')
                    db.research.execute('INSERT INTO company_markets VALUES(?,?,?)',(symbol,code,market.MARKETS[code]['currency']))
                row=(1,'2014-01-01','2014-05-01','2015-01-05',10,1000e6,100e6,20e6,.2,5,.18)
                for pool in (('legacy','cached') if code=='us' else ('cached',)):
                    book_store.store(db,dict(market=code,entry='2015-01-05',latest=True,pool=pool,candidates=20,
                        rows=[(code+str(number),*row) for number in range(20)],
                        metrics=[(code+str(number),metric,5,.2) for number in range(20) for metric in ('ev_ebitda','ev_ebitda_3y')],filters=[]))
            store.record(db.research,db,'2015-01-05')
            prepared=load_screening_data(db)
            prepared['markets']={code:load_screening_data(db,code) for code in ('hk','jp')}
            page=PageData(prepared,screening.latest(db,pool='cached'))
        output=self.root/'website'
        with patch.object(rendering,'load_page_data',return_value=page),patch.object(rendering,'inputs',return_value={'sources':{}}):
            rendering.build(output)
        subprocess.run(['node',str(Path(__file__).resolve().parent/'check-range.cjs'),str(output)],check=True)

    def test_market_projection_scopes_choices_and_matches_sql_selection(self):
        with store.connection() as db:
            # Two listed companies per market; yields order them differently in each.
            for code,companies,exchange,sector in [('us',[('A',.2),('B',.3)],'NYSE','Energy'),('hk',[('0700.HK',.2),('0005.HK',.25)],'HKSE','Finance'),
                                                   ('jp',[('7203.T',.2),('6758.T',.1)],'JPX','Industry')]:
                for symbol,_ in companies:
                    store.company(db,symbol,exchange=exchange,sector=sector)
                    db.research.execute('INSERT INTO company_markets VALUES(?,?,?)',(symbol,code,market.MARKETS[code]['currency']))
                if code=='us':store.session(db,'2020-01-03',100)
                else:db.research.execute('INSERT INTO local_sessions VALUES(?,?)',(code,'2020-01-03'))
                rows=[(symbol,*(dict(candidate_rank=rank,fiscal='2018-12-31',known='2019-04-30',entry='2020-01-03',price=10,market_cap=200e6,
                        enterprise_value=100e6,ebitda=20e6,ebitda_yield=value,ev_ebitda=1/value,spread=value-.02)[column] for column in store.ROW))
                      for rank,(symbol,value) in enumerate(companies,1)]
                for pool in (('legacy','cached') if code=='us' else ('cached',)):
                    book_store.store(db,dict(market=code,entry='2020-01-03',latest=True,pool=pool,candidates=len(rows),
                        rows=rows,metrics=[(symbol,'ev_ebitda',1/value,value) for symbol,value in companies],filters=[]))
            store.record(db.research,db,'2020-01-03')
            db.research.execute("UPDATE metadata SET value=json_set(value,'$.latest_dates',json(?)) WHERE key='identity'",
                                (json.dumps(dict(hk='2020-01-03',jp='2020-01-03')),))
            cases=[]
            # The default chain run by the service: size floors, then EBITDA/EV yield highest.
            chain=s.capture_strategy(pipeline(*(dict(kind='filter',source=dict(kind='field',field=field),op='ge',threshold=dict(value=value,unit='usd_million'))
                                                for field,value in (('market_cap','100'),('enterprise_value','50'))),rank_step(last=2)))
            for code,exchange in [('us','NYSE'),('hk','HKSE'),('jp','JPX')]:
                prepared=load_screening_data(db,code)
                self.assertEqual(prepared['choices']['exchange'],[exchange])
                self.assertEqual(prepared['bounds'],dict(first='2020-01-03',last='2020-01-03'))
                options=dict(pool='cached',rank_to=2)
                sql=screening.latest(db,market=code,**options)
                expected=[[row['symbol'],row['rank']] for row in sql]
                self.assertEqual(len(expected),2)
                cases.append(dict(prepared=prepared,options=options,expected=expected))
                # A server latest chain matches the equivalent built-in screen.
                with fact_view.View(db,lambda:None,lambda:None,market=code) as view:
                    served=scalar_execution.Executor(chain,view,lambda record:None).select(db,view.open_book,date(2020,1,3),latest=True)
                fields=('symbol','rank','price','price_date','fiscal','known')
                self.assertEqual([(*(row[key] for key in fields),row['ranking_value']) for row in served],
                                 [(*(row[key] for key in fields),row['metric_yield']) for row in sql])
        code="const fs=require('fs'),assert=require('assert'),s=require(process.argv[1]);for(const c of JSON.parse(fs.readFileSync(0,'utf8')))assert.deepStrictEqual(s.latestScreen(c.prepared,c.options).stocks.map(h=>[h.symbol,h.rank]),c.expected);"
        subprocess.run(['node','-e',code,str(Path(__file__).resolve().parents[1]/'website/browser/screener.js')],
                       input=json.dumps(cases),text=True,check=True)


if __name__=='__main__':unittest.main()
