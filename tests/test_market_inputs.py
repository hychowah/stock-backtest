"""Market preparation uses native inputs and context-date USD values in private stores."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from contextlib import ExitStack, closing, contextmanager, redirect_stdout
from datetime import date, datetime, timezone
import json
import io
import math
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backtest.financial import books
from backtest.engines.original import book_batch, schedules
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
        save(raw/'px'/'TEST.json',dict(div=[dict(date=d,adjClose=20,volume=100) for d in ('2014-12-31','2015-07-01','2015-07-30')]))
        save(raw/'spy-div.json',[dict(date=d,adjClose=v) for d,v in [('2015-06-30',100),('2015-07-01',105),('2015-07-17',110),('2015-07-20',110),('2015-07-29',120),('2015-07-30',125),('2015-07-31',130)]])
        save(raw/'treasury.json',[dict(date='2015-06-30',month3=2,year10=3)])
        groups={'jp':[('1000.T','JPY'),('2000.T','USD')],'hk':[('0001.HK','CNY')]}
        for code,companies in groups.items():
            quote=market.MARKETS[code]['currency']
            save(market.universe_path(raw,code),[dict(symbol=s,name='Foreign '+s,exchange=market.MARKETS[code]['exchanges'][0],listed=True,market=code,currency=quote) for s,_ in companies])
            save(market.calendar_path(raw,code),[dict(date=d,close=100) for d in ('2013-12-30','2014-12-30','2015-07-01','2015-07-20','2015-07-30','2015-08-03')])
            for symbol,currency in companies:
                price=100 if code=='hk' else 1000
                save(raw/'px'/market.cache_path_for(symbol).name,dict(div=[dict(date=d,adjClose=price,volume=1000) for d in ('2013-12-30','2014-12-30','2015-07-01','2015-07-20')]))
                save(market.native_path(raw,symbol),[dict(date=d,close=price) for d in ('2013-12-30','2014-12-30')])
                rows=[]
                for year in (2013,2014):
                    rows.append(dict(date=f'{year}-12-31',reportedCurrency=currency,weightedAverageShsOut=1e6,
                        ebitda=5e6 if currency in ('USD','CNY') else 100e6,revenue=100e6 if year==2013 else 120e6,
                        netIncome=1e6,operatingIncome=2e6,epsDiluted=1,ebit=2e6,interestExpense=1e5))
                balance=[dict(date=r['date'],reportedCurrency=currency,totalDebt=20e6 if currency in ('USD','CNY') else 200e6,
                              cashAndCashEquivalents=10e6 if currency in ('USD','CNY') else 100e6,
                              totalStockholdersEquity=50e6,totalCurrentAssets=30e6,totalCurrentLiabilities=10e6) for r in rows]
                cash=[dict(date=r['date'],reportedCurrency=currency,freeCashFlow=3e6,commonDividendsPaid=-1e6,filingDate='2015-07-02' if r['date']=='2014-12-31' else '2014-04-01') for r in rows]
                for endpoint,values in [('income-statement',rows),('balance-sheet-statement',balance),('cash-flow-statement',cash)]:
                    financial_inputs.publish(raw,symbol,endpoint,values,{},raw/'coverage.json')
        for currency,rates in [('JPY',[('2015-06-30',100),('2015-07-19',80),('2015-07-29',50),('2015-08-02',40)]),('HKD',[('2015-06-30',8),('2015-07-19',8),('2015-07-29',8)]),('CNY',[('2015-06-30',5),('2015-07-19',4),('2015-07-29',4)])]:
            save(market.fx_path(raw,currency),[dict(date=d,close=v) for d,v in rates])
        research.prepare(source)
        daily.prepare(store,source,repair=book_batch.repair)
        db=daily.connect(store,source)
        try:yield db,raw,source,store
        finally:db.close()


class MarketInputsTests(unittest.TestCase):
    def test_incremental_research_and_sheets_match_cold_build_after_updates_and_retry(self):
        def edit(path,change):
            value=json.loads(path.read_text());change(value);path.write_text(json.dumps(value))
        def exact(value):
            if isinstance(value,float):return ('float',value.hex())
            if isinstance(value,dict):return {key:exact(item) for key,item in value.items()}
            if isinstance(value,(list,tuple)):return tuple(exact(item) for item in value)
            return value
        def snapshot(path):
            """The research tables (the valuation sums among them) and identity, and every sheet computed again."""
            with closing(sqlite3.connect(path)) as db:
                tables={}
                for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                    if name=='metadata':continue
                    keys=[row[1] for row in sorted(db.execute(f'PRAGMA table_info({name})'),key=lambda row:row[5]) if row[5]]
                    order='rowid' if name=='statements' else ','.join(keys)
                    tables[name]=exact(db.execute(f'SELECT * FROM {name} ORDER BY {order}').fetchall())
                identity=json.loads(db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0])
            with closing(sqlite3.connect(':memory:')) as db:
                daily.attach(db,path)
                sheets=[books.book(day,pool,facts.BookFacts(db,code),latest=latest)
                        for code in ('us','hk','jp') for day in facts.sessions(db,code)
                        for pool in (('legacy','cached') if code=='us' else ('cached',)) for latest in (False,True)]
            return tables,identity,exact(sheets)
        def cache_snapshot(path,source):
            daily.prepare(path,source,repair=book_batch.repair)
            with closing(daily.connect(path,source)) as cache:
                book_batch.precompute(cache,lambda **kw:None,lambda:None)
                with cache:
                    port=facts.BookFacts(cache)
                    for day in facts.sessions(cache):schedules.prepare_period(cache,day,'legacy',port)
                # Handles are local to a cache; compare every field by its sheet key.
                headers=cache.execute('SELECT market,entry,latest,candidates FROM books ORDER BY market,entry,latest').fetchall()
                pools=cache.execute('SELECT b.market,b.entry,b.latest,p.pool FROM books b JOIN book_pools p USING(book) ORDER BY b.market,b.entry,b.latest,p.pool').fetchall()
                columns=[row[1] for row in cache.execute('PRAGMA table_info(book_rows)')][1:]
                rows=cache.execute('SELECT b.market,b.entry,b.latest,'+','.join('r.'+name for name in columns)+
                                   ' FROM books b JOIN book_rows r USING(book) ORDER BY b.market,b.entry,b.latest,r.pool,r.symbol').fetchall()
                return exact([list(map(tuple,part)) for part in (headers,pools,rows)])
        def sums(path,symbols):
            """The days of each company's stored valuation sums, for the companies that have any."""
            with closing(sqlite3.connect(path)) as reader:
                return {symbol:[row[0] for row in found] for symbol in symbols
                        if (found:=reader.execute('SELECT day FROM valuation_sums WHERE symbol=? ORDER BY day',(symbol,)).fetchall())}
        with redirect_stdout(io.StringIO()),prepared_markets() as (db,raw,source,store):
            # Three equal-yield US names let removal and source order change ranks.
            universe=raw/'universe.json';metrics=raw/'metrics.jsonl'
            records=[json.loads(line) for line in metrics.read_text().splitlines()]
            for symbol in ('SECOND','REMOVE'):
                edit(universe,lambda rows,symbol=symbol:rows.append(dict(symbol=symbol,name=symbol,exchange='NYSE',listed=True)))
                records.append(dict(records[0],symbol=symbol))
                (raw/'px'/f'{symbol}.json').write_bytes((raw/'px/TEST.json').read_bytes())
            metrics.write_text(''.join(json.dumps(row)+'\n' for row in records))
            # Annual values give TEST valuation sums, so its new price day below
            # continues from the sums stored before its cutoff.
            financial_inputs.publish(raw,'TEST','income-statement',[dict(date='2014-12-31',reportedCurrency='USD',netIncome=1e6,revenue=10e6,weightedAverageShsOut=1e6)],{},raw/'coverage.json')
            research.prepare(source,force=True)
            self.assertEqual(sums(source,('TEST',)),{'TEST':['2015-07-01','2015-07-30']})
            cache_snapshot(store,source)
            with closing(sqlite3.connect(source)) as reader:
                base=json.loads(reader.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0])['content']
            for path in (raw/'px').glob('*.json'):
                edit(path,lambda payload:payload['div'].append(dict(date='2015-08-04',adjClose=payload['div'][-1]['adjClose'])))
            edit(raw/'spy-div.json',lambda rows:rows.append(dict(date='2015-08-04',adjClose=140.)))
            # A revised volume alone repairs the sheets from its day.
            edit(raw/'px/TEST.json',lambda payload:payload['div'][2].update(volume=300))
            for code in ('hk','jp'):
                edit(market.calendar_path(raw,code),lambda rows:rows.append(dict(date='2015-08-04',close=100.)))
            edit(universe,lambda rows:rows[0].update(listed=False,name='Renamed US Test',exchange='NASDAQ',sector='Technology'))
            research.prepare(source)
            with closing(sqlite3.connect(source)) as reader:
                change=json.loads(reader.execute("SELECT value FROM metadata WHERE key='changes'").fetchone()[0])
                self.assertEqual(change['base'],base)
                self.assertEqual(change['prices'].pop('TEST'),'2015-07-30')
                self.assertEqual(set(change['prices'].values()),{'2015-08-04'})
                self.assertEqual(change['companies'],{})
            self.assertEqual(sums(source,('TEST',)),{'TEST':['2015-07-01','2015-07-30','2015-08-04']})
            cold=source.with_name('cold.sqlite');cold_store=store.with_name('cold-daily.sqlite');research.prepare(cold)
            self.assertEqual(snapshot(source),snapshot(cold))
            self.assertEqual(cache_snapshot(store,source),cache_snapshot(cold_store,cold))
            cold.unlink();cold_store.unlink()

            edit(raw/'px/0001.HK.json',lambda payload:[row.update(adjClose=row['adjClose']*1.1) for row in payload['div']])
            income=financial_inputs.asset_path(raw,'1000.T','income-statement')
            def reports(payload):
                row=dict(payload['rows'][-1],date='2015-03-31',filingDate='2015-07-31',operatingIncome=-0.0)
                payload['rows']=[member for member in payload['rows'] if member['date']!='2013-12-31']+[row]
            edit(income,reports)
            balance=financial_inputs.asset_path(raw,'1000.T','balance-sheet-statement')
            edit(balance,lambda payload:payload['rows'].append(dict(payload['rows'][-1],date='2015-03-31',filingDate='2015-07-31')))
            edit(raw/'treasury.json',lambda rows:rows[0].update(month3=-0.0,year10=4.))
            edit(market.fx_path(raw,'CNY'),lambda rows:rows[0].update(close=6.))
            def sessions(rows):
                rows[:]=[row for row in rows if row['date']!='2014-12-30']
                rows.extend([dict(date='2014-12-29',close=100.),dict(date='2015-03-30',close=100.)])
            edit(market.calendar_path(raw,'jp'),sessions)
            edit(market.native_path(raw,'1000.T'),lambda rows:rows.extend([
                dict(date='2014-12-29',close=1200.),dict(date='2015-03-30',close=1300.)]))
            # Fiscal prices on the new sessions keep valuation rows for both jp companies.
            for symbol,days in (('1000.T',('2014-12-29','2015-03-30')),('2000.T',('2014-12-29',))):
                edit(raw/'px'/market.cache_path_for(symbol).name,lambda payload,days=days:payload['div'].extend(
                    dict(date=day,adjClose=1000) for day in days))
            edit(universe,lambda rows:rows.__setitem__(slice(None),[row for row in rows if row['symbol']!='REMOVE']))
            (raw/'px/SECOND.json').unlink()
            metrics.write_text(''.join(json.dumps(row)+'\n' for row in reversed(records)))
            before=source.read_bytes()
            with patch.object(facts,'store_market',side_effect=RuntimeError('interrupted fixture')):
                with self.assertRaisesRegex(RuntimeError,'interrupted fixture'):research.prepare(source)
            self.assertEqual(source.read_bytes(),before)
            # The valuation fold is the last stage of the same transaction.
            with patch.object(facts,'refold',side_effect=RuntimeError('interrupted fold')):
                with self.assertRaisesRegex(RuntimeError,'interrupted fold'):research.prepare(source)
            self.assertEqual(source.read_bytes(),before)
            research.prepare(source)
            research.prepare(cold)
            self.assertEqual(snapshot(source),snapshot(cold))
            with closing(sqlite3.connect(source)) as reader:
                pending=reader.execute("SELECT value FROM metadata WHERE key='changes'").fetchone()[0]
                change=json.loads(pending)
                self.assertTrue(change['statements'])
                self.assertEqual(change['companies']['REMOVE'],['us',None])
                self.assertIn('1000.T',change['reports'])
                self.assertEqual(change['prices']['0001.HK'],'2013-12-30')
            def interrupt(**value):
                if value['kind']=='daily' and value['completed']==1:raise RuntimeError('interrupted sheet repair')
            previous=daily.binding(db)
            with self.assertRaisesRegex(RuntimeError,'interrupted sheet repair'):
                daily.prepare(store,source,progress=interrupt,repair=book_batch.repair)
            self.assertEqual(daily.binding(db),previous)
            with self.assertRaisesRegex(ValueError,'changed'):daily.connect(store,source)
            self.assertEqual(cache_snapshot(store,source),cache_snapshot(cold_store,cold))
            research.prepare(source,force=True)
            with closing(sqlite3.connect(source)) as reader:
                self.assertEqual(reader.execute("SELECT value FROM metadata WHERE key='changes'").fetchone()[0],pending)
            cold.unlink();cold_store.unlink()

            # A market move (0001.HK from hk to us, with USD reports), a removed company (2000.T) and
            # a mid-history annual revision: 1000.T's 2015-03-31 net income, known after earlier rows.
            edit(universe,lambda rows:rows.append(dict(symbol='0001.HK',name='Moved',exchange='NYSE',listed=True)))
            edit(market.universe_path(raw,'hk'),lambda rows:rows.clear())
            for endpoint in ('income-statement','balance-sheet-statement','cash-flow-statement'):
                edit(financial_inputs.asset_path(raw,'0001.HK',endpoint),lambda payload:[row.update(reportedCurrency='USD') for row in payload['rows']])
            records.append(dict(symbol='0001.HK',rows=[dict(date='2014-12-31',marketCap=100e6,enterpriseValue=120e6,evToEBITDA=5,reportedCurrency='USD')]))
            metrics.write_text(''.join(json.dumps(row)+'\n' for row in records))
            edit(market.universe_path(raw,'jp'),lambda rows:rows.__setitem__(slice(None),[row for row in rows if row['symbol']!='2000.T']))
            edit(income,lambda payload:[row.update(netIncome=3e6) for row in payload['rows'] if row['date']=='2015-03-31'])
            before=sums(source,('0001.HK','1000.T','2000.T'))
            self.assertEqual(set(before),{'0001.HK','1000.T','2000.T'})
            self.assertEqual(before['1000.T'],['2015-07-01','2015-07-20','2015-08-04'])
            research.prepare(source)
            research.prepare(cold)
            with closing(sqlite3.connect(source)) as reader:
                change=json.loads(reader.execute("SELECT value FROM metadata WHERE key='changes'").fetchone()[0])
                self.assertEqual(change['companies'],{'0001.HK':['hk','us'],'2000.T':['jp',None]})
                self.assertEqual(change['annual']['1000.T'],'2015-07-31')
            incremental,rebuilt=snapshot(source),snapshot(cold)
            # Every research table, the moved company's native closes and the valuation sums
            # included, equals the cold build.
            self.assertIn('valuation_sums',incremental[0])
            self.assertEqual(incremental,rebuilt)
            self.assertEqual(cache_snapshot(store,source),cache_snapshot(cold_store,cold))
            self.assertEqual(sums(source,('0001.HK','1000.T','2000.T')),
                             {'0001.HK':['2015-07-01','2015-07-20','2015-08-04'],'1000.T':before['1000.T']})

    def test_preparation_leaves_out_saved_rows_the_market_no_longer_admits(self):
        with redirect_stdout(io.StringIO()),prepared_markets() as (db,raw,source,store):
            inventory=market.universe_path(raw,'hk');rows=json.loads(inventory.read_text())
            inventory.write_text(json.dumps(rows+[dict(rows[0],symbol='4338.HK',name='Microsoft Corporation',listed=False)]))
            (raw/'px'/'4338.HK.json').write_bytes((raw/'px'/'0001.HK.json').read_bytes())
            research.prepare(source)
            with closing(sqlite3.connect(source)) as reader:
                self.assertEqual(reader.execute("SELECT symbol FROM company_markets WHERE market='hk'").fetchall(),[('0001.HK',)])

    def test_market_paths_admission_and_calendar_month_lags(self):
        self.assertTrue(market.common_stock('0001.HK','Example',market='hk'))
        self.assertTrue(market.common_stock('8001.HK','Example',market='hk'))
        self.assertFalse(market.common_stock('80700.HK','Duplicate counter',market='hk'))
        self.assertFalse(market.common_stock('4338.HK','Microsoft Corporation',market='hk'))
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
            # Dividends convert like the other annual values, only once their report is known.
            self.assertIsNone(hk.dividends('0001.HK','2014-12-31',day))
            self.assertEqual(hk.dividends('0001.HK','2014-12-31',date(2015,7,3)),-200000)
            self.assertEqual(hk.shares('0001.HK','2014-12-31',date(2015,7,3)),1e6)
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
        with prepared_markets() as (db,_,source,_):
            jp=facts.BookFacts(db,'jp')
            with sqlite3.connect(source) as writer:
                writer.execute('INSERT INTO stock_days VALUES(?,?,?,?,?,?)',
                               ('1000.T','2015-07-19',777.,None,5,None))
            self.assertEqual(jp.price('1000.T',date(2015,7,19),slack=7),None)
            self.assertEqual(jp.volumes('1000.T',date(2015,7,14),date(2015,7,20)),[1000])
            self.assertEqual(jp.price('1000.T',date(2015,7,20)),(date(2015,7,20),1000))
            self.assertEqual(jp.usd_price('1000.T',date(2015,7,20)),(date(2015,7,20),12.5))
            self.assertEqual(facts.sessions(db,'jp')[-1],date(2015,8,3))
            self.assertEqual(set(jp.companies()),{'1000.T','2000.T'})
            self.assertEqual(set(facts.BookFacts(db).companies()),{'TEST'})


if __name__=='__main__':unittest.main()
