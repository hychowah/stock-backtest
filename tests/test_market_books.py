"""Original books retain market identity and USD proceeds without changing US math."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from contextlib import closing, redirect_stdout
from datetime import date, timedelta
import io
import json
from types import SimpleNamespace
import unittest
from backtest import measure_observations
from backtest.engines.original import schedules,robustness,book_batch
from backtest.inputs import book_store,daily,fact_view,facts,financial_inputs,market,research
from backtest.financial import books, rules
from test_market_inputs import prepared_markets
import book_store_fixture as store


class MarketBooksTests(unittest.TestCase):
    def test_holding_fx_and_early_exit_proceeds_remain_usd_cash(self):
        with prepared_markets() as (db,*_):
            result=schedules.backtest(db,start='2015-07-01',end='2015-08-03',market='jp',pool='cached',min_cap=0,min_ev=0,rank_to=2)
            self.assertAlmostEqual(result['growth'],1.25)
            self.assertAlmostEqual(result['spy_growth'],1.30)
            holding=result['periods'][0]['holdings'][0]
            self.assertEqual((holding['entry'],holding['exit']),('2015-07-01','2015-07-20'))
            self.assertEqual(holding['status'],'Last available price')
            self.assertAlmostEqual(holding['return_value'],.25)
            book=book_store.find(db,date(2015,7,1),'cached',market='jp')
            self.assertEqual([row['price'] for row in book_store.rows(db,book,'cached')],[10,10])

    def test_empty_foreign_selection_keeps_cash_and_full_benchmark_window(self):
        with prepared_markets() as (db,*_):
            result=schedules.backtest(db,start='2015-07-01',end='2015-08-03',market='jp',pool='cached',min_cap=1e15)
            self.assertEqual(result['growth'],1.)
            self.assertAlmostEqual(result['spy_growth'],1.30)
            self.assertEqual(result['periods'][0]['holdings'],[])

    def test_foreign_benchmark_allows_us_holiday_but_refuses_stale_history(self):
        with store.connection() as db:
            db.research.executemany('INSERT INTO local_sessions VALUES(?,?)',
                                   [('hk','2020-01-02'),('hk','2020-01-03')])
            store.session(db,'2010-01-04',100)
            with self.assertRaisesRegex(ValueError,'SPY comparison coverage is missing'):
                schedules.backtest(db,start='2020-01-02',end='2020-01-03',market='hk')
            store.session(db,'2019-12-31',200)
            store.session(db,'2020-01-02',220)
            result=schedules.backtest(db,start='2020-01-02',end='2020-01-03',market='hk')
            self.assertAlmostEqual(result['spy_growth'],1.1)

    def test_market_separated_headers_and_native_valuation(self):
        with prepared_markets() as (db,*_):
            entry=date(2015,7,1)
            ids=[schedules.prepare_period(db,entry,'cached',facts.BookFacts(db,code)) for code in ('us','hk','jp')]
            self.assertEqual(len(set(ids)),3)
            self.assertEqual([book_store.record(db,book)['market'] for book in ids],['us','hk','jp'])
            hk=list(book_store.rows(db,ids[1],'cached'))
            self.assertEqual(hk[0]['market_cap'],12.5e6)
            self.assertEqual(hk[0]['enterprise_value'],14.5e6)
            us=list(book_store.rows(db,ids[0],'cached'))
            self.assertEqual((us[0]['market_cap'],us[0]['enterprise_value'],us[0]['ebitda']),(100e6,120e6,24e6))

    def test_prior_report_published_later_does_not_enter_annual_metric(self):
        day=date(2015,7,1);symbol='1000.T'
        rows=[dict(fiscal=date(year,12,31),known=date(year+1,4,1),ebitda=1e6) for year in (2012,2013,2014)]
        port=SimpleNamespace(market='jp',reports=lambda context,*,symbol:({symbol:rows},{}),
                             legacy_annual=lambda symbol,context:{},usd_price=lambda *args:None,
                             valuation=lambda symbol,day:(0.,0.,0.,0,0,0))
        def pairs():
            return books.owner_values(symbol,'2014-12-31',day,10e6,12e6,1e6,port,None)[2]
        self.assertIn('ev_ebitda_3y',pairs())
        rows[1]['known']=day
        self.assertNotIn('ev_ebitda_3y',pairs())

    def test_foreign_valuation_sums_equal_a_brute_force_over_converted_reports(self):
        with prepared_markets() as (db,*_):
            stored=0
            for code,symbols in (('hk',('0001.HK',)),('jp',('1000.T','2000.T'))):
                port=facts.BookFacts(db,code)
                for symbol in symbols:
                    # The narrow reader selects and converts as reports(day) and legacy_annual(symbol, day) do.
                    day=date(2013,12,1)
                    while day<=date(2015,8,10):
                        statement=rules.latest_statement(port.reports(day)[0].get(symbol,[]),day)
                        found=port.report_at(symbol,day)
                        self.assertEqual(found,None if statement is None else
                                         (statement,port.legacy_annual(symbol,day).get(str(statement['fiscal']),{})),(symbol,day))
                        day+=timedelta(days=1)
                    # Every priced day's yields, summed in day order: the rows research preparation stored.
                    total=[0.,0.,0.,0,0,0];expected=[]
                    for day,close in port.closes(symbol,None):
                        statement=rules.latest_statement(port.reports(day)[0].get(symbol,[]),day)
                        fiscal=None if statement is None else port.price(symbol,statement['fiscal'],False,7)
                        if fiscal is None:continue
                        cap=statement['market_cap']*(close/fiscal[1])
                        annual=port.legacy_annual(symbol,day).get(str(statement['fiscal']),{})
                        yields=[None if annual.get(field) is None else annual[field]/cap
                                for field in ('netIncome','revenue','totalStockholdersEquity')]
                        if all(value is None for value in yields):continue
                        for k,value in enumerate(yields):
                            if value is not None:total[k]+=value;total[3+k]+=1
                        expected.append((symbol,str(day),*total))
                    rows=db.execute('SELECT * FROM research.valuation_sums WHERE symbol=? ORDER BY day',(symbol,)).fetchall()
                    self.assertEqual([tuple(row) for row in rows],expected)
                    stored+=len(rows)
            self.assertEqual(stored,6)

    def test_hong_kong_dated_owner_values_equal_the_stored_lanes(self):
        """The formula path (measure_observations.dated) gives an HK sheet's stored values, the averages included."""
        def edit(path,change):
            value=json.loads(path.read_text());change(value);path.write_text(json.dumps(value))
        with redirect_stdout(io.StringIO()),prepared_markets() as (_,raw,source,store):
            # Weekly sessions from 2009 and CNY reports for 2009-2012 (a loss and a zero year) give 0001.HK
            # five years of daily yields; each session's FX serves the next one.
            symbol='0001.HK';weeks=[date(2009,1,5)+timedelta(weeks=n) for n in range(260)]
            closes=[dict(date=str(day),close=100.+n%5) for n,day in enumerate(weeks)]
            edit(market.calendar_path(raw,'hk'),lambda rows:rows.extend(closes))
            edit(market.native_path(raw,symbol),lambda rows:rows.extend(closes))
            edit(raw/'px'/market.cache_path_for(symbol).name,lambda payload:payload['div'].extend(
                dict(date=row['date'],adjClose=row['close']) for row in closes))
            for currency,rate in (('CNY',5.),('HKD',8.)):
                edit(market.fx_path(raw,currency),lambda rows,rate=rate:rows.extend(dict(date=str(day),close=rate) for day in weeks))
            for endpoint,change in (('income-statement',lambda row,year:row.update(revenue=(80+5*(year-2009))*1e6,netIncome=(year-2010)*1e6)),
                                    ('balance-sheet-statement',lambda row,year:row.update(totalStockholdersEquity=(40+year-2009)*1e6)),
                                    ('cash-flow-statement',lambda row,year:row.update(filingDate=f'{year+1}-04-01'))):
                def earlier(payload,change=change):
                    for year in (2009,2010,2011,2012):
                        row=dict(payload['rows'][0],date=f'{year}-12-31');change(row,year);payload['rows'].append(row)
                edit(financial_inputs.asset_path(raw,symbol,endpoint),earlier)
            research.prepare(source)
            daily.prepare(store,source,repair=book_batch.repair)
            day=date(2015,7,20)
            with closing(daily.connect(store,source)) as db:
                with db:book=schedules.prepare_period(db,day,'cached',facts.BookFacts(db,'hk'))
                _,lanes=book_store.lanes(db,book,'cached')
                stored={field:values[symbol] for field,values in lanes.items() if symbol in values}
                with fact_view.View(db,lambda:None,lambda:None,market='hk') as view:
                    [decision]=view.admit([dict(symbol=symbol,pool='cached',mode='historical',date=str(day))])
                    anchor=rules.latest_statement(view.reports(symbol,'cached',day),day)
                    owner=measure_observations.dated(view,decision,dict(date=str(day)),anchor,lambda:None)
            self.assertEqual(owner['evidence']['filters'],stored)
            self.assertLessEqual({'ps',*(f'{key}_{kind}_{years}y' for key in ('pe','ps','pb') for kind in ('avg','vs_avg') for years in (3,5))},set(stored))

    def test_random_plan_uses_local_sessions_and_preserves_market(self):
        with prepared_markets() as (db,*_):
            configuration=robustness.plan(db,start='2015-07-01',end='2015-08-03',months=1,trials=2,seed=7,market='jp',pool='cached',min_cap=0,min_ev=0,rank_to=2)
            self.assertEqual(configuration['options']['market'],'jp')
            local={str(day) for day in facts.sessions(db,'jp')}
            self.assertTrue(all(set(sample)<=local for sample in configuration['samples']))
            planned=book_batch.plan(db,configuration)
            self.assertTrue(all(key[2]=='jp' for key in planned['jobs']))
            result=robustness.run(db,configuration,workers=1)
            self.assertEqual(result['completed'],2)


if __name__=='__main__':unittest.main()
