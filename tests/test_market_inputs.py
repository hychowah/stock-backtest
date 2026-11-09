"""Market preparation uses native inputs and context-date USD values in private stores."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timezone
import json
import math
import tempfile
import unittest
from unittest.mock import patch

from backtest.inputs import daily, facts, financial_inputs, market, research
from backtest.runtime import cache_access


@contextmanager
def prepared_markets():
    with tempfile.TemporaryDirectory() as folder, ExitStack() as patches:
        root=Path(folder);raw=root/'raw';raw.mkdir();(raw/'px').mkdir();(raw/'px-full').mkdir();(raw/'fx').mkdir()
        source=root/'research.sqlite';store=root/'daily.sqlite'
        patches.enter_context(patch.object(research,'ROOT',root));patches.enter_context(patch.object(research,'RAW',raw))
        patches.enter_context(patch.object(cache_access,'workspace',cache_access.WorkspaceAccess(root/'cache.lock')))
        def save(path,value):
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
        us=[dict(symbol='TEST',name='US Test',exchange='NYSE',listed=True)]
        save(raw/'universe.json',us)
        (raw/'metrics.jsonl').write_text(json.dumps(dict(symbol='TEST',rows=[dict(date='2014-12-31',marketCap=100e6,enterpriseValue=120e6,evToEBITDA=5,reportedCurrency='USD')]))+'\n')
        save(raw/'px'/'TEST.json',dict(div=[dict(date=d,adjClose=20) for d in ('2014-12-31','2015-07-01','2015-07-30')]))
        save(raw/'spy-div.json',[dict(date=d,adjClose=v) for d,v in [('2015-06-30',100),('2015-07-01',105),('2015-07-17',110),('2015-07-20',110),('2015-07-29',120),('2015-07-30',125),('2015-07-31',130)]])
        save(raw/'treasury.json',[dict(date='2015-06-30',month3=2,year10=3)])
        groups={'jp':[('1000.T','JPY'),('2000.T','USD')],'hk':[('0001.HK','CNY')]}
        for code,companies in groups.items():
            quote=market.MARKETS[code]['currency']
            save(market.universe_path(raw,code),[dict(symbol=s,name='Foreign '+s,exchange=market.MARKETS[code]['exchanges'][0],listed=True,market=code,currency=quote) for s,_ in companies])
            save(market.calendar_path(raw,code),[dict(date=d,close=100) for d in ('2013-12-30','2014-12-30','2015-07-01','2015-07-20','2015-07-30','2015-08-03')])
            for symbol,currency in companies:
                price=100 if code=='hk' else 1000
                save(raw/'px'/market.cache_path_for(symbol).name,dict(div=[dict(date=d,adjClose=price) for d in ('2013-12-30','2014-12-30','2015-07-01','2015-07-20')]))
                save(market.native_path(raw,symbol),[dict(date=d,close=price) for d in ('2013-12-30','2014-12-30')])
                rows=[]
                for year in (2013,2014):
                    rows.append(dict(date=f'{year}-12-31',reportedCurrency=currency,weightedAverageShsOut=1e6,
                        ebitda=5e6 if currency in ('USD','CNY') else 100e6,revenue=100e6 if year==2013 else 120e6,
                        netIncome=1e6,operatingIncome=2e6,epsDiluted=1,ebit=2e6,interestExpense=1e5))
                balance=[dict(date=r['date'],reportedCurrency=currency,totalDebt=20e6 if currency in ('USD','CNY') else 200e6,
                              cashAndCashEquivalents=10e6 if currency in ('USD','CNY') else 100e6,
                              totalStockholdersEquity=50e6,totalCurrentAssets=30e6,totalCurrentLiabilities=10e6) for r in rows]
                cash=[dict(date=r['date'],reportedCurrency=currency,freeCashFlow=3e6,filingDate='2015-07-02' if r['date']=='2014-12-31' else '2014-04-01') for r in rows]
                for endpoint,values in [('income-statement',rows),('balance-sheet-statement',balance),('cash-flow-statement',cash)]:
                    financial_inputs.publish(raw,symbol,endpoint,values,{},raw/'coverage.json')
        for currency,rates in [('JPY',[('2015-06-30',100),('2015-07-19',80),('2015-07-29',50),('2015-08-02',40)]),('HKD',[('2015-06-30',8),('2015-07-19',8),('2015-07-29',8)]),('CNY',[('2015-06-30',5),('2015-07-19',4),('2015-07-29',4)])]:
            save(market.fx_path(raw,currency),[dict(date=d,close=v) for d,v in rates])
        research.prepare(source)
        daily.prepare(store,source)
        db=daily.connect(store,source)
        try:yield db,raw,source,store
        finally:db.close()


class MarketInputsTests(unittest.TestCase):
    def test_market_paths_admission_and_calendar_month_lags(self):
        self.assertTrue(market.common_stock('0001.HK','Example',market='hk'))
        self.assertTrue(market.common_stock('8001.HK','Example',market='hk'))
        self.assertFalse(market.common_stock('80700.HK','Duplicate counter',market='hk'))
        self.assertTrue(market.common_stock('186A.T','Example',market='jp'))
        self.assertEqual(market.available(date(2024,10,31),'jp')[0],date(2025,1,31))
        self.assertEqual(market.available(date(2024,10,31),'hk')[0],date(2025,2,28))
        self.assertEqual(market.available(date(2024,10,31),'us')[0],date(2025,1,29))
        self.assertFalse(market.completed_session(date(2024,12,31),'jp'))
        self.assertFalse(market.completed_session(date(2025,1,2),'jp'))
        self.assertFalse(market.completed_session(date(2025,7,5),'hk'))
        before_close=datetime(2025,7,1,6,tzinfo=timezone.utc)
        after_close=datetime(2025,7,1,8,tzinfo=timezone.utc)
        with patch('datetime.datetime') as clock:
            clock.now.return_value=before_close
            self.assertFalse(market.completed_session(date(2025,7,1),'jp'))
            self.assertTrue(market.completed_session(date(2025,6,30),'jp'))
            clock.now.return_value=after_close
            self.assertTrue(market.completed_session(date(2025,7,1),'jp'))

    def test_native_reporting_currency_and_context_fx(self):
        with prepared_markets() as (db,*_):
            jp=facts.BookFacts(db,'jp');hk=facts.BookFacts(db,'hk');day=date(2015,7,1)
            j=jp.reports(day)[0]
            self.assertEqual(j['1000.T'][-1]['market_cap'],10e6)
            self.assertEqual(j['1000.T'][-1]['enterprise'],11e6)
            self.assertEqual(j['2000.T'][-1]['enterprise'],20e6)
            self.assertEqual(j['2000.T'][-1]['ebitda'],5e6)
            h=hk.reports(day)[0]['0001.HK'][-1]
            self.assertEqual((h['market_cap'],h['enterprise'],h['ebitda']),(12.5e6,14.5e6,1e6))
            history=hk.legacy_annual('0001.HK',day)
            self.assertEqual([history[y]['revenue'] for y in ('2013-12-31','2014-12-31')],[20e6,24e6])
            self.assertNotIn('freeCashFlow',history['2014-12-31'])
            self.assertEqual(hk.legacy_annual('0001.HK',date(2015,7,3))['2014-12-31']['freeCashFlow'],600000)
            self.assertIsNone(jp.fx('EUR',day))
            self.assertEqual(jp.fx('JPY',day),(date(2015,6,30),.01))
            self.assertIsNone(jp.fx('JPY',date(2015,7,10)))
            only=jp.reports(date(2015,7,20),symbol='2000.T')[0]
            self.assertEqual(set(only),{'2000.T'})
            self.assertEqual(only['2000.T'][-1]['market_cap'],12.5e6)
            self.assertEqual(jp.reports(day,symbol='1000.T')[0]['1000.T'][-1]['market_cap'],10e6)
            self.assertEqual(jp.spy(day),100)
            self.assertEqual(facts.BookFacts(db).spy(day),105)

    def test_foreign_conflicts_and_signed_zero_stay_unavailable_or_exact(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder);endpoint='cash-flow-statement';symbol='1000.T'
            rows=[dict(date='2014-12-31',reportedCurrency='JPY',freeCashFlow=-0.0),
                  dict(date='2013-12-31',reportedCurrency='JPY',freeCashFlow=100),
                  dict(date='2013-12-31',reportedCurrency='JPY',freeCashFlow=200),
                  dict(date='2012-12-31',reportedCurrency='JPY',freeCashFlow=100),
                  dict(date='2012-12-31',reportedCurrency='USD',freeCashFlow=100)]
            financial_inputs.publish(raw,symbol,endpoint,rows,{},raw/'coverage.json')
            annual=financial_inputs.resolve_history(raw,symbol,'jp')['annual'][endpoint]
            self.assertEqual(math.copysign(1,annual['2014-12-31']['freeCashFlow']['value']),-1)
            for fiscal in ('2013-12-31','2012-12-31'):
                self.assertEqual(annual[fiscal]['freeCashFlow']['reason'],'CONFLICTING_INPUT')
                self.assertIsNone(annual[fiscal]['freeCashFlow']['value'])
            path=market.native_path(raw,symbol);path.parent.mkdir()
            path.write_text(json.dumps([dict(date='2014-12-30',close=100,currency='CNY')]))
            native=facts.resolve(path,'native-price',fields=('close',),currency='JPY')
            self.assertFalse(native['dated']['2014-12-30']['close']['valid'])

    def test_local_sessions_and_native_vs_usd_prices(self):
        with prepared_markets() as (db,*_):
            jp=facts.BookFacts(db,'jp')
            self.assertEqual(jp.price('1000.T',date(2015,7,20)),(date(2015,7,20),1000))
            self.assertEqual(jp.usd_price('1000.T',date(2015,7,20)),(date(2015,7,20),12.5))
            self.assertEqual(facts.sessions(db,'jp')[-1],date(2015,8,3))
            self.assertEqual(set(jp.companies()),{'1000.T','2000.T'})
            self.assertEqual(set(facts.BookFacts(db).companies()),{'TEST'})


if __name__=='__main__':unittest.main()
