"""Dated books: calendar anchoring, point-in-time prices, compounding and reuse."""
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.inputs import market
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import daily, research
from backtest.runtime import cache_access
from backtest.financial import rules, books as financial_books, metrics
from backtest import calendar as schedule_calendar, portfolio_results
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import json
import tempfile
import subprocess
import time
from contextlib import ExitStack,closing,redirect_stdout
import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from backtest.engines.original import schedules as s


class CalendarTests(unittest.TestCase):
    def test_daily_binding_and_connect_use_explicit_research_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'custom-research.sqlite';path=Path(folder)/'daily.sqlite'
            with patch.object(research,'signature',return_value={'fixture':1}),patch.object(research,'prepared_price_binding',
                    side_effect=lambda selected:'custom' if selected==source else 'default'), \
                    patch.object(research,'prepared_observation_binding',return_value={'fixture':1}):
                inputs=daily.fingerprint(source)
                with closing(sqlite3.connect(path)) as db:
                    db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
                    db.execute('INSERT INTO metadata VALUES(?,?)',('daily_inputs',json.dumps(inputs)));db.commit()
                with closing(daily.connect(path,source)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM metadata').fetchone()[0],1)
                with self.assertRaisesRegex(ValueError,'Daily cache changed'):daily.connect(path)

    def test_daily_fingerprint_tracks_portfolio_reducer(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'portfolio_results.py';path.write_text('# first')
            with patch.object(research,'signature',return_value={'private-fixture':1}),patch.object(research,'prepared_price_binding',return_value='fixture'),patch.object(research,'prepared_observation_binding',return_value={'fixture':1}),patch.object(portfolio_results,'__file__',str(path)):
                before=daily.fingerprint()
                path.write_text('# changed portfolio source')
                after=daily.fingerprint()
        self.assertNotEqual(before['engine'][path.relative_to(research.ROOT).as_posix() if path.is_relative_to(research.ROOT) else path.name],after['engine'][path.relative_to(research.ROOT).as_posix() if path.is_relative_to(research.ROOT) else path.name])

    def test_daily_fingerprint_tracks_calendar_source(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'schedule_calendar.py';path.write_text('# first')
            with patch.object(research,'signature',return_value={'private-fixture':1}),patch.object(research,'prepared_price_binding',return_value='fixture'),patch.object(research,'prepared_observation_binding',return_value={'fixture':1}),patch.object(schedule_calendar,'__file__',str(path)):
                before=daily.fingerprint()
                path.write_text('# changed calendar source')
                after=daily.fingerprint()
        self.assertEqual(set(before['engine']),{'backtest/inputs/daily.py','backtest/engines/original/schedules.py','backtest/engines/original/book_batch.py',path.relative_to(research.ROOT).as_posix() if path.is_relative_to(research.ROOT) else path.name,'backtest/portfolio_results.py'})
        self.assertNotEqual(before['engine'][path.relative_to(research.ROOT).as_posix() if path.is_relative_to(research.ROOT) else path.name],after['engine'][path.relative_to(research.ROOT).as_posix() if path.is_relative_to(research.ROOT) else path.name])

    def sessions(self,first,last):
        days=[]
        while first<=last:
            if first.weekday()<5:days.append(first)
            first+=timedelta(days=1)
        return days

    def test_month_end_anchor_and_rolling(self):
        sessions=self.sessions(date(2020,1,1),date(2021,4,1))
        periods=s.schedule('2020-01-31','2020-05-31',1,sessions)
        self.assertEqual([a for a,b in periods],[date(2020,1,31),date(2020,3,2),date(2020,3,31),date(2020,4,30)])
        self.assertEqual(periods[-1][1],date(2020,5,29))
        self.assertTrue(all(periods[i][1]==periods[i+1][0] for i in range(len(periods)-1)))

    def test_supported_intervals(self):
        sessions=self.sessions(date(2015,1,1),date(2016,1,1))
        for months,count in [(1,12),(3,4),(6,2),(12,1),(24,1)]:
            self.assertEqual(len(s.schedule('2015-01-01','2016-01-01',months,sessions)),count)

    def test_leap_anniversary_and_invalid_dates(self):
        sessions=self.sessions(date(2020,1,1),date(2022,1,1))
        periods=s.schedule('2020-02-29','2021-12-31',12,sessions)
        self.assertEqual([a for a,b in periods],[date(2020,3,2),date(2021,3,1)])
        for start,end,months in [('2020-01-01','2020-02-01',2),('2020-02-01','2020-01-01',1),('2020-01-01','2023-01-01',1)]:
            with self.assertRaises(ValueError):s.schedule(start,end,months,sessions)


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close);self.db.executescript(daily.SCHEMA)
        self.db.executemany('INSERT INTO sessions VALUES(?,?)',[('2015-01-02',100),('2015-04-01',110),('2015-07-01',121)])
        for symbol,ebitda,prices in [('A',30e6,[10,20,30,15]),('B',10e6,[10,10,20,20])]:
            self.db.execute('INSERT INTO companies VALUES(?,?,?,?)',(symbol,symbol,'NYSE','Energy'))
            self.db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',(symbol,'2014-06-30','2014-09-28',100e6,150e6,ebitda,ebitda/150e6))
            for day,price in zip(['2014-06-30','2015-01-02','2015-04-01','2015-07-01'],prices):
                self.db.execute('INSERT INTO prices VALUES(?,?,?,?)',(symbol,day,price,price))
        self.db.commit()

    def test_weekly_dates_use_ordinary_financial_evaluation_with_legacy_metadata(self):
        sessions=[date.fromisoformat(row[0]) for row in self.db.execute('SELECT day FROM sessions ORDER BY day')]
        calendar=schedule_calendar.SessionCalendar(sessions)
        configuration=dict(version=1,start='2015-01-01',end='2015-07-01',interval=dict(unit='week',count=1))
        dates=[str(a) for a,b in calendar.fixed(configuration)]
        self.assertEqual(dates,['2015-01-02','2015-04-01'])
        self.assertEqual(calendar.sample(configuration,1,42)['samples'][0],dates)
        # Explicit evaluation has no reason to reconstruct a monthly schedule.
        with patch.object(s,'schedule',side_effect=AssertionError('No nominal schedule for explicit trades')):
            result=s.backtest_dates(self.db,dates=dates,start=configuration['start'],end=configuration['end'],rank_to=1)
        self.assertEqual(result['months'],12)  # Existing evaluator metadata; no weekly result claim.
        self.assertEqual([p['portfolio'] for p in result['periods']],[.5,-.5])
        self.assertEqual(result['growth'],.75)
        self.assertEqual(result['spy_growth'],1.1*1.1)
        self.assertEqual(result['cash_days'],0)
        self.assertEqual(result['periods'],s.backtest(self.db,start=configuration['start'],end=configuration['end'],months=3,rank_to=1)['periods'])

    def test_financial_ratios_use_selected_report_and_reuse_books(self):
        self.db.executemany('INSERT INTO financial_inputs VALUES(?,?,?)',[
            ('A','2014-06-30',json.dumps(dict(netIncome=20e6,revenue=100e6))),
            ('A','2015-06-30',json.dumps(dict(netIncome=1e9,revenue=1e9)))])
        options=dict(start='2015-01-02',end='2015-07-01',months=6,pool='cached',min_cap=0,min_ev=0)
        result=s.backtest(self.db,**options,filters=[dict(field='pe',op='lt',value=11),dict(field='profit_margin',op='gt',value=15)])
        self.assertEqual([h['symbol'] for h in result['periods'][0]['holdings']],['A'])
        saved=dict(self.db.execute("SELECT field,value FROM filter_values WHERE symbol='A'"))
        self.assertEqual(saved['pe'],10);self.assertEqual(saved['profit_margin'],20)
        with patch.object(s,'compute_period',side_effect=AssertionError('Books must be reused')):
            result=s.backtest(self.db,**options,filters=[dict(field='pe',op='lt',value=10)])
        self.assertEqual(result['periods'][0]['names'],0)

    def test_operating_spread_uses_entry_treasury_and_reuses_completed_books(self):
        self.db.executemany('INSERT INTO treasury10 VALUES(?,?)',[
            ('2014-12-31',3),('2015-01-05',99)])
        self.db.executemany('INSERT INTO financial_inputs VALUES(?,?,?)',[
            ('A',f'{year}-06-30',json.dumps(dict(revenue=100e6,operatingIncome=margin*100e6)))
            for year,margin in [(2012,.1),(2013,.2),(2014,.3),(2015,99)]])
        options=dict(start='2015-01-02',end='2015-07-01',months=6,pool='cached',min_cap=0,min_ev=0)
        filters=[dict(field='operating_yield_spread_3y',op='gt',value=4)]
        result=s.backtest(self.db,**options,filters=filters)
        self.assertEqual([h['symbol'] for h in result['periods'][0]['holdings']],['A'])
        self.assertAlmostEqual(self.db.execute("SELECT value FROM filter_values WHERE symbol='A' AND field='operating_yield_spread_3y'").fetchone()[0],5)
        with patch.object(s,'compute_period',side_effect=AssertionError('Reuse books')):
            unfiltered=s.backtest(self.db,**options)
            self.assertEqual(unfiltered['periods'][0]['names'],2)
            empty=s.backtest(self.db,**options,filters=[dict(filters[0],value=6)])
            self.assertEqual(empty['periods'][0]['names'],0)

    def test_conditions_reuse_dated_books_and_exclude_missing_returns(self):
        options=dict(start='2015-01-02',end='2015-07-01',months=6,pool='cached',min_cap=0,min_ev=0)
        initial=s.backtest(self.db,**options)
        count=self.db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0]
        filtered=s.backtest(self.db,**options,filters=[dict(field='market_cap',op='gt',value=150)])
        self.assertEqual([h['symbol'] for h in filtered['periods'][0]['holdings']],['A'])
        empty=s.backtest(self.db,**options,filters=[dict(field='return_1y',op='gt',value=-100)])
        self.assertEqual(empty['periods'][0]['names'],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0],count)

    def test_selection_order_reuses_books_and_weights_only_survivors(self):
        options=dict(start='2015-01-02',end='2015-07-01',months=6,pool='cached',max_cap=150e6)
        first=s.backtest(self.db,**options,rank_to=1)
        self.assertEqual([(h['symbol'],h['rank']) for h in first['periods'][0]['holdings']],[('B',1)])
        with patch.object(s,'compute_period',side_effect=AssertionError('Order must reuse books')):
            empty=s.backtest(self.db,**options,rank_to=1,selection_order='rank_first')
            self.assertEqual(empty['periods'][0]['names'],0);self.assertIsNone(empty['cagr'])
            result=s.backtest(self.db,**options,rank_to=2,selection_order='rank_first')
        survivor=result['periods'][0]['holdings'][0]
        self.assertEqual((survivor['symbol'],survivor['rank'],survivor['weight']),('B',2,1))
        self.assertEqual(result['growth'],2)
        self.assertEqual(survivor['contribution_pp'],100)

    def test_array_and_sql_price_adapters_share_financial_policy(self):
        statement=daily.histories(self.db)[0]['A'][0]
        entry,exit_day=date(2015,1,2),date(2015,7,1)
        series=[(date.fromisoformat(row[0]),row[1]) for row in self.db.execute("SELECT day,price FROM prices WHERE symbol='A' ORDER BY day")]
        array=research.snapshot(statement,entry,exit_day,series,series,False)
        lookup=lambda day,column,forward,slack:daily.price(self.db,'A',day,column,forward=forward,slack=slack)
        self.assertEqual(array,financial_books.snapshot(statement,entry,exit_day,lookup,False))
        # A stopped holding is retained, and a declared bankruptcy overrides price.
        self.db.execute("DELETE FROM prices WHERE symbol='A' AND day='2015-07-01'")
        stopped=financial_books.snapshot(statement,entry,exit_day,lookup,False)
        self.assertEqual(stopped[-1],'Last available price')
        self.assertEqual(stopped[-2],.5)
        bankrupt=financial_books.snapshot(statement,entry,exit_day,lookup,True)
        self.assertEqual(bankrupt[-2:],[-1.,'Bankruptcy'])

    def test_rebalance_and_compounding(self):
        result=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
        self.assertEqual(result['start'],'2015-01-02')
        self.assertEqual([p['holdings'][0]['symbol'] for p in result['periods']],['A','A'])
        self.assertEqual([p['portfolio'] for p in result['periods']],[.5,-.5])
        self.assertAlmostEqual(result['growth'],.75)
        self.assertAlmostEqual(result['spy_growth'],1.21)
        self.assertEqual(result['periods'][0]['holdings'][0]['weight'],1)
        # Cached period books are independent of screening filters.
        with patch.object(daily,'price',side_effect=AssertionError('Repeated books must not read daily prices')):
            second=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=2)
        self.assertAlmostEqual(second['growth'],1.75*.75)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],2)

    def test_unavailable_report_and_missing_metric(self):
        self.db.execute("UPDATE statements SET known='2015-01-02' WHERE symbol='A'")
        result=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
        self.assertEqual(result['periods'][0]['holdings'][0]['symbol'],'B')
        result=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,metric='ev_ebitda_3y')
        self.assertIsNone(result['growth']);self.assertIsNone(result['cagr'])
        self.assertTrue(all(p['names']==0 for p in result['periods']))

    def test_stop_and_missing_buy(self):
        self.db.execute("DELETE FROM prices WHERE symbol='A' AND day='2015-07-01'")
        self.db.execute("DELETE FROM prices WHERE symbol='B' AND day='2015-01-02'")
        result=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=2)
        self.assertEqual(result['periods'][0]['names'],1)
        a=next(h for h in result['periods'][1]['holdings'] if h['symbol']=='A')
        self.assertEqual(a['status'],'Last available price');self.assertEqual(a['return_value'],0.)
        self.assertEqual(a['exit'],'2015-04-01')

    def test_partial_period_and_validation_before_writes(self):
        result=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=12,rank_to=1)
        self.assertEqual(len(result['periods']),1)
        self.assertAlmostEqual(result['growth'],.75)
        self.assertTrue(result['periods'][0]['is_final_period'])
        with self.assertRaises(ValueError):s.backtest(self.db,start='2015-01-01',end='2015-07-01',min_yield=-1)

    def test_only_requested_pool_then_switch_and_reuse(self):
        # C is outside the original report-size screen, but belongs in the
        # broader pool when the user lowers the screen's market-cap floor.
        self.db.execute("INSERT INTO companies VALUES('C','C','NYSE','Energy')")
        self.db.execute("INSERT INTO statements VALUES('C','2014-06-30','2014-09-28',50000000,75000000,60000000,.8)")
        for day in ('2014-06-30','2015-01-02','2015-04-01','2015-07-01'):
            self.db.execute("INSERT INTO prices VALUES('C',?,10,10)",(day,))
        self.db.commit()
        options=dict(start='2015-01-01',end='2015-07-01',months=3,rank_to=1,min_cap=0,min_ev=0)
        original=s.backtest(self.db,pool='legacy',**options)
        self.assertEqual([p['holdings'][0]['symbol'] for p in original['periods']],['A','A'])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM snapshots WHERE pool='cached'").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM screening_metrics WHERE pool='cached'").fetchone()[0],0)
        saved=[tuple(row) for row in self.db.execute("SELECT * FROM snapshots WHERE pool='legacy' ORDER BY year,symbol")]
        periods=[tuple(row) for row in self.db.execute('SELECT * FROM periods ORDER BY year')]
        with patch.object(daily,'price',wraps=daily.price) as lookup:
            wider=s.backtest(self.db,pool='cached',**options)
        self.assertGreater(lookup.call_count,0)
        self.assertEqual([p['holdings'][0]['symbol'] for p in wider['periods']],['C','C'])
        self.assertEqual(wider['growth'],1.)
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM periods ORDER BY year')],periods)
        self.assertEqual([tuple(row) for row in self.db.execute("SELECT * FROM snapshots WHERE pool='legacy' ORDER BY year,symbol")],saved)
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT pool,COUNT(*) FROM period_pools GROUP BY pool')],[('cached',2),('legacy',2)])
        # A new connection must recognize both pools, including after changing
        # rank/filter/metric parameters. No reports or daily prices are reread.
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'daily.sqlite';copy=sqlite3.connect(path)
            self.db.backup(copy);copy.close()
            reopened=sqlite3.connect(path);reopened.row_factory=sqlite3.Row
            try:
                with patch.object(daily,'price',side_effect=AssertionError('Completed pool')),patch.object(daily,'histories',side_effect=AssertionError('Completed pool')):
                    for pool in ('cached','legacy'):
                        repeat=s.backtest(reopened,pool=pool,**options)
                        expected=wider if pool=='cached' else original
                        self.assertEqual(repeat['periods'],expected['periods'])
                        s.backtest(reopened,pool=pool,metric='ev_ebitda_3y',**options)
                        s.backtest(reopened,pool=pool,sector='Missing',**options)
            finally:reopened.close()

    def test_cached_pool_can_be_prepared_before_legacy(self):
        options=dict(start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
        first=s.backtest(self.db,pool='cached',**options)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM snapshots WHERE pool='legacy'").fetchone()[0],0)
        second=s.backtest(self.db,pool='legacy',**options)
        for period in first['periods']:
            for stock in period['holdings']:
                self.assertEqual(stock['pool'],'cached')
                stock['pool']='legacy'
        self.assertEqual(first['periods'],second['periods'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],2)

    def test_empty_pool_is_complete_and_other_pool_can_be_added(self):
        self.db.execute('UPDATE statements SET market_cap=50000000');self.db.commit()
        options=dict(start='2015-01-01',end='2015-07-01',months=3,rank_to=1,min_cap=0,min_ev=0)
        empty=s.backtest(self.db,pool='legacy',**options)
        self.assertIsNone(empty['cagr'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM period_pools').fetchone()[0],2)
        with patch.object(daily,'price',side_effect=AssertionError('Empty completed pool')),patch.object(daily,'histories',side_effect=AssertionError('Empty completed pool')):
            repeat=s.backtest(self.db,pool='legacy',**options)
        self.assertEqual(repeat['periods'],empty['periods'])
        populated=s.backtest(self.db,pool='cached',**options)
        self.assertTrue(all(p['names']==1 for p in populated['periods']))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],2)


class ShutdownTests(unittest.TestCase):
    def setUp(self):
        BacktestTests.setUp(self)
        # Keep a committed book to verify an interrupted new schedule cannot
        # remove completed work or change its source prices/financials.
        s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=12,rank_to=1)

    def counts(self,db):
        return {table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                for table in ('prices','statements','periods','snapshots','screening_metrics','period_pools')}

    def contents(self,db):
        return {table:sorted([tuple(row) for row in db.execute('SELECT * FROM '+table)],key=repr)
                for table in ('prices','statements','periods','snapshots','screening_metrics','period_pools')}

    def test_interrupted_second_pool_preserves_completed_first_pool(self):
        before=self.contents(self.db)
        with patch.object(metrics,'evaluate',side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=12,pool='cached',rank_to=1)
        self.assertEqual(self.contents(self.db),before)
        retry=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=12,pool='cached',rank_to=1)
        self.assertEqual(retry['growth'],.75)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM period_pools').fetchone()[0],2)

    def test_keyboard_interrupt_rolls_back_and_retry_succeeds(self):
        before=self.counts(self.db);rows=self.contents(self.db);original=s.prepare_period
        def interrupted(*args):
            original(*args)
            raise KeyboardInterrupt()
        with patch.object(s,'prepare_period',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
        self.assertEqual(self.counts(self.db),before)
        self.assertEqual(self.contents(self.db),rows)
        retry=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
        self.assertAlmostEqual(retry['growth'],.75)

    def test_killed_writer_recovers_database_and_preserves_committed_books(self):
        before=self.counts(self.db);rows=self.contents(self.db)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'daily.sqlite';marker=Path(tmp)/'writing'
            db=sqlite3.connect(path);self.db.backup(db);db.close()
            child_code="""
import sqlite3,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from backtest.engines.original import schedules as s
db=sqlite3.connect(sys.argv[2]);db.row_factory=sqlite3.Row
db.execute('PRAGMA cache_size=1')
original=s.prepare_period
def paused(*args):
    result=original(*args)
    Path(sys.argv[3]).write_text('uncommitted period written')
    sys.stdin.buffer.read(1)
    return result
s.prepare_period=paused
s.backtest(db,start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
"""
            process=subprocess.Popen([sys.executable,'-c',child_code,str(Path(__file__).resolve().parents[1]),str(path),str(marker)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+15
                while not marker.exists() and process.poll() is None and time.monotonic()<deadline:
                    time.sleep(.01)
                self.assertTrue(marker.exists(),'Child did not reach an uncommitted period')
                journal=Path(str(path)+'-journal')
                self.assertTrue(journal.exists(),'Expected a real SQLite rollback journal')
                self.assertGreater(journal.stat().st_size,0)
                process.kill()  # SIGKILL on Unix, TerminateProcess on Windows.
                process.communicate(timeout=5)
            finally:
                if process.poll() is None:process.kill()
                process.communicate(timeout=5)
            recovered=sqlite3.connect(path);recovered.row_factory=sqlite3.Row
            try:
                self.assertEqual(recovered.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(self.counts(recovered),before)
                self.assertEqual(self.contents(recovered),rows)
                retry=s.backtest(recovered,start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
                self.assertAlmostEqual(retry['growth'],.75)
                self.assertEqual(recovered.execute('SELECT COUNT(*) FROM periods').fetchone()[0],3)
            finally:recovered.close()


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.path=root/'daily.sqlite';self.source=root/'research.sqlite'
        raw=root/'raw';(raw/'px').mkdir(parents=True)
        (raw/'px'/'A.json').write_text(json.dumps(dict(div=[dict(date='2015-01-02',adjClose=10)])))
        (raw/'spy-div.json').write_text(json.dumps([dict(date='2015-01-02',adjClose=100)]))
        (raw/'treasury.json').write_text('[]')
        db=sqlite3.connect(self.source);db.executescript(research.SCHEMA)
        db.execute("INSERT INTO companies VALUES('A','A','NYSE','Energy')")
        db.execute("INSERT INTO statements VALUES('A','2014-06-30','2014-09-28',100000000,150000000,30000000,.2)")
        daily.observation_inputs.finish(db,'2015-01-02')
        db.commit();db.close()
        self.context.enter_context(patch.object(research,'RAW',raw))
        self.context.enter_context(patch.object(market,'RAW',raw))
        self.context.enter_context(patch.object(cache_access,'workspace',cache_access.WorkspaceAccess(root/'cache.lock')))
        self.context.enter_context(patch.object(daily,'fingerprint',return_value={'fixture':1}))
        self.context.enter_context(patch.object(research,'connect',side_effect=lambda *args,**kwargs:sqlite3.connect(self.source)))

    def test_publish_and_unchanged_skip(self):
        db=sqlite3.connect(self.source)
        db.execute("INSERT INTO treasury10 VALUES('2014-12-31',3)");db.commit();db.close()
        with patch.object(research,'prepare') as prerequisite:
            daily.prepare(self.path,self.source)
        prerequisite.assert_called_once_with(self.source)
        original=self.path.read_bytes()
        db=daily.connect(self.path)
        self.assertEqual(research.ten_year_yield(db,date(2015,1,2)),3)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM prices').fetchone()[0],1);db.close()
        with patch.object(Path,'read_text',side_effect=AssertionError('Unchanged preparation must not parse prices')), \
                patch.object(Path,'read_bytes',side_effect=AssertionError('Unchanged preparation must not read prices')):
            daily.prepare(self.path,self.source)
        self.assertEqual(self.path.read_bytes(),original)

    def test_failure_preserves_previous_cache(self):
        daily.prepare(self.path,self.source);original=self.path.read_bytes()
        # Changed bytes are parsed again; the parse fails.
        (research.RAW/'px'/'A.json').write_text(json.dumps(dict(div=[dict(date='2015-01-02',adjClose=11)])))
        with patch.object(daily,'fingerprint',return_value={'fixture':2}),patch.object(research,'bars',side_effect=ValueError('bad fixture')):
            with self.assertRaisesRegex(ValueError,'bad fixture'):daily.prepare(self.path,self.source)
        self.assertEqual(self.path.read_bytes(),original)
        self.assertFalse(self.path.with_name(self.path.name+'.building').exists())


class RefreshTests(unittest.TestCase):
    """A stale cache with refresh evidence must equal a full build of the same inputs."""
    SESSIONS=['2015-01-02','2015-02-02','2015-03-02','2015-04-01','2015-05-01','2015-06-01','2015-07-01']
    OPTIONS=dict(start='2015-01-01',end='2015-07-01',months=1,rank_to=3,min_cap=0,min_ev=0)
    TABLES={'prices':'symbol,day','sessions':'day','treasuries':'day','companies':'symbol','statements':'symbol,fiscal',
            'financial_inputs':'symbol,fiscal','treasury10':'day',**{t:'1' for t in daily.observation_inputs.TABLES}}

    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.root=root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.path=root/'daily.sqlite';self.source=root/'research.sqlite'
        self.raw=raw=root/'raw';(raw/'px').mkdir(parents=True)
        days=['2014-06-30']+self.SESSIONS
        for symbol,prices in [('A',[10,20,22,24,26,28,30,32]),('B',[10,10,11,12,13,12,11,10]),('C',[10,10,10,10,10,10,10,10])]:
            (raw/'px'/f'{symbol}.json').write_text(json.dumps(dict(div=[dict(date=d,adjClose=p) for d,p in zip(days,prices)])))
        (raw/'spy-div.json').write_text(json.dumps([dict(date=d,adjClose=100+i) for i,d in enumerate(self.SESSIONS)]))
        (raw/'treasury.json').write_text(json.dumps([dict(date=d,month3=2) for d in self.SESSIONS]))
        db=sqlite3.connect(self.source);db.executescript(research.SCHEMA)
        for symbol,ebitda in [('A',30e6),('B',20e6),('C',10e6)]:
            db.execute('INSERT INTO companies VALUES(?,?,?,?)',(symbol,symbol,'NYSE','Energy'))
            db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',(symbol,'2014-06-30','2014-09-28',100e6,150e6,ebitda,ebitda/150e6))
        db.execute("INSERT INTO treasury10 VALUES('2014-12-31',3)")
        daily.observation_inputs.finish(db,'2015-07-01')
        db.execute("INSERT INTO metadata VALUES('prices','{}')")
        db.commit();db.close()
        self.generation=0
        for owner,key,value in [(research,'RAW',raw),(market,'RAW',raw)]:
            self.context.enter_context(patch.object(owner,key,value))
        self.context.enter_context(patch.object(cache_access,'workspace',cache_access.WorkspaceAccess(root/'cache.lock')))
        self.context.enter_context(patch.object(daily,'fingerprint',side_effect=lambda source=None:{'fixture':self.generation}))
        self.context.enter_context(patch.object(research,'prepare'))
        self.context.enter_context(patch.object(research,'connect',side_effect=lambda *args,**kwargs:sqlite3.connect(self.source)))
        self.context.enter_context(redirect_stdout(io.StringIO()))
        self.accept_prices()
        daily.prepare(self.path,self.source)
        with closing(daily.connect(self.path)) as cache:
            self.books=s.backtest(cache,**self.OPTIONS)['periods']
            self.saved=self.book_rows(cache)
        self.assertEqual(len(self.saved),6)

    def accept_prices(self):
        """Record the price inventory as research preparation would, then make the cache stale."""
        with closing(sqlite3.connect(self.source)) as db,db:
            db.execute("UPDATE metadata SET value=? WHERE key='prices'",(json.dumps(research.price_sources()),))
        self.generation+=1

    def append(self,day='2015-08-03'):
        for name in ('A','B'):
            path=self.raw/'px'/f'{name}.json';payload=json.loads(path.read_text())
            payload['div'].insert(0,dict(date=day,adjClose=40));path.write_text(json.dumps(payload))
        for name,row in [('spy-div.json',dict(date=day,adjClose=120)),('treasury.json',dict(date=day,month3=2.5))]:
            path=self.raw/name;rows=json.loads(path.read_text());path.write_text(json.dumps(rows+[row]))
        with closing(sqlite3.connect(self.source)) as db,db:db.execute('INSERT INTO treasury10 VALUES(?,4)',(day,))
        self.accept_prices()

    @staticmethod
    def book_rows(db):
        """Saved books by (entry, exit, pool), independent of period ids."""
        books={}
        for period_id,entry,exit_day in db.execute('SELECT year,entry,exit FROM periods ORDER BY year'):
            for pool, in db.execute('SELECT pool FROM period_pools WHERE period_id=? ORDER BY pool',(period_id,)):
                tables=[]
                for table in ('snapshots','filter_values','screening_metrics'):
                    cursor=db.execute(f'SELECT * FROM {table} WHERE year=? AND pool=?',(period_id,pool))
                    year=[column[0] for column in cursor.description].index('year')
                    tables.append(sorted((tuple(row)[:year]+tuple(row)[year+1:] for row in cursor),key=repr))
                books[(entry,exit_day,pool)]=tables
        return books

    def contents(self,path):
        with closing(sqlite3.connect(path)) as db:
            return {table:sorted((tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY {order}')),key=repr) for table,order in self.TABLES.items()}

    def full_build(self):
        """A fresh cache of the same inputs, with the same books computed from scratch."""
        path=self.root/'fresh.sqlite'
        path.unlink(missing_ok=True)
        daily.prepare(path,self.source)
        with closing(daily.connect(path)) as fresh:
            periods=s.backtest(fresh,**self.OPTIONS)['periods']
            return path,periods,self.book_rows(fresh)

    def refresh(self):
        """Refresh the cache; return the price files whose rows were parsed."""
        parsed=[]
        original=daily._price_rows
        def recorded(payload):
            parsed.extend(p.name for p in sorted((self.raw/'px').glob('*.json')) if json.loads(p.read_bytes())==payload)
            return original(payload)
        with patch.object(daily,'_price_rows',side_effect=recorded):
            daily.prepare(self.path,self.source)
        return parsed

    def assert_matches_full_build(self,kept):
        with closing(daily.connect(self.path)) as cache:
            self.assertEqual(set(self.book_rows(cache)),set(kept))
            stored={key:value for key,value in self.book_rows(cache).items()}
            periods=s.backtest(cache,**self.OPTIONS)['periods']
            after=self.book_rows(cache)
        path,expected,fresh=self.full_build()
        self.assertEqual(self.contents(self.path),self.contents(path))
        self.assertEqual(periods,expected)
        self.assertEqual(after,fresh)
        for key in kept:self.assertEqual(stored[key],fresh[key])

    def test_pure_append_keeps_every_book_and_unchanged_files_unparsed(self):
        self.append()
        reads=self.refresh()
        self.assertNotIn('C.json',reads)
        self.assertIn('A.json',reads)
        with closing(daily.connect(self.path)) as cache:
            self.assertEqual(self.book_rows(cache),self.saved)
            self.assertEqual(cache.execute("SELECT price FROM prices WHERE symbol='A' AND day='2015-08-03'").fetchone()[0],40)
            with patch.object(s,'compute_period',side_effect=AssertionError('Kept books must be reused')):
                self.assertEqual(s.backtest(cache,**self.OPTIONS)['periods'],self.books)
        self.assert_matches_full_build(self.saved)

    def test_historical_edit_drops_only_books_that_can_read_it(self):
        path=self.raw/'px'/'A.json';payload=json.loads(path.read_text())
        next(row for row in payload['div'] if row['date']=='2015-04-01')['adjClose']=99
        path.write_text(json.dumps(payload));self.accept_prices()
        self.refresh()
        # Books that exit on or after the edited day, or whose entry window
        # reaches it, are dropped; earlier books are kept unchanged.
        kept={key:value for key,value in self.saved.items() if key[1]<'2015-04-01'}
        self.assertEqual(len(kept),2)
        self.assert_matches_full_build(kept)

    def test_changed_bytes_with_a_kept_stamp_are_parsed(self):
        # A restore that keeps size and timestamps must not hide changed rows.
        path=self.raw/'px'/'A.json';text=path.read_text();stamp=path.stat()
        path.write_text(text.replace('"adjClose": 26','"adjClose": 62'))
        os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        self.assertEqual([path.stat().st_size,path.stat().st_mtime_ns],[stamp.st_size,stamp.st_mtime_ns])
        self.generation+=1
        self.assertIn('A.json',self.refresh())
        self.assert_matches_full_build({key:value for key,value in self.saved.items() if key[1]<'2015-04-01'})

    def test_statement_change_drops_every_book(self):
        with closing(sqlite3.connect(self.source)) as db,db:
            db.execute("UPDATE statements SET ebitda=40e6,ebitda_yield=40e6/150e6 WHERE symbol='B'")
        self.generation+=1
        self.refresh()
        self.assert_matches_full_build({})

    def test_changed_book_code_drops_books_and_keeps_prices(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            evidence=json.loads(db.execute("SELECT value FROM metadata WHERE key='refresh'").fetchone()[0])
            evidence['code']['books']='0'*64
            db.execute("UPDATE metadata SET value=? WHERE key='refresh'",(json.dumps(evidence),))
        self.generation+=1
        reads=self.refresh()
        self.assertFalse({'A.json','B.json','C.json'}&set(reads))
        self.assert_matches_full_build({})

    def test_cache_without_refresh_evidence_is_rebuilt(self):
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("DELETE FROM metadata WHERE key='refresh'")
        self.append()
        with patch.object(daily,'_keep_books',side_effect=AssertionError('No evidence means a full build')):
            daily.prepare(self.path,self.source)
        self.assert_matches_full_build({})

    def test_failed_refresh_keeps_previous_cache_and_books(self):
        before=self.contents(self.path)
        self.append()
        with patch.object(daily,'_dated_change',side_effect=ValueError('bad fixture')):
            with self.assertRaisesRegex(ValueError,'bad fixture'):daily.prepare(self.path,self.source)
        self.assertEqual(self.contents(self.path),before)
        self.assertFalse(self.path.with_name(self.path.name+'.building').exists())
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(self.book_rows(db),self.saved)

    def test_short_book_reach_covers_prices_after_its_exit(self):
        for name,price in [('A',23),('B',11),('C',10)]:
            path=self.raw/'px'/f'{name}.json';payload=json.loads(path.read_text())
            payload['div'].append(dict(date='2015-03-04',adjClose=price));path.write_text(json.dumps(payload))
        path=self.raw/'spy-div.json';rows=json.loads(path.read_text())
        path.write_text(json.dumps(rows+[dict(date='2015-03-04',adjClose=103)]))
        self.accept_prices();self.refresh()
        short=dict(dates=['2015-03-02'],start='2015-03-01',end='2015-03-04',rank_to=3,min_cap=0,min_ev=0)
        with closing(daily.connect(self.path)) as cache:
            s.backtest_dates(cache,**short)
            before=self.book_rows(cache)
        self.assertIn(('2015-03-02','2015-03-04','legacy'),before)
        # A price after the two-day book's exit, but within its entry reach.
        path=self.raw/'px'/'A.json';payload=json.loads(path.read_text())
        payload['div'].append(dict(date='2015-03-06',adjClose=23.5));path.write_text(json.dumps(payload))
        self.accept_prices();self.refresh()
        with closing(daily.connect(self.path)) as cache:after=self.book_rows(cache)
        self.assertNotIn(('2015-03-02','2015-03-04','legacy'),after)
        self.assertEqual(after,{key:value for key,value in before.items()
            if max(date.fromisoformat(key[1]),date.fromisoformat(key[0])+financial_books.FORWARD_REACH)<date(2015,3,6)})
        self.assertEqual(len(after),2)


if __name__=='__main__':unittest.main()
