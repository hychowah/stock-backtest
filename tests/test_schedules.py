"""Dated books: calendar anchoring, point-in-time prices, compounding and reuse."""
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.inputs import market
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import book_store, daily, facts, financial_inputs, research
from backtest.runtime import cache_access, diagnostics
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
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from backtest.engines.original import schedules as s
import book_store_fixture as store


def legacy(db, symbol, fiscal, **values):
    """Store legacy annual values as the typed annual facts that books read (facts.legacy_annual)."""
    annual = {}
    for field, value in values.items():
        endpoint = next(endpoint for endpoint, fields in financial_inputs.ENDPOINTS.items() if field in fields)
        annual.setdefault(endpoint, {}).setdefault(fiscal, {})[field] = dict(value=value, valid=True, reason=None)
    facts.store_annual(db, symbol, dict(sources={}, annual=annual))


def research_file(path, content):
    """A research file whose record passes research.identity under a fixture signature."""
    with closing(sqlite3.connect(path)) as db:
        db.executescript(research.SCHEMA)
        db.executemany('INSERT INTO metadata VALUES(?,?)', [(key, json.dumps(value)) for key, value in dict(
            version=research.SCHEMA_VERSION, inputs={'fixture': 1}, identity=dict(
                version=research.SCHEMA_VERSION, latest_date='2015-01-05', code=research.code_identity('facts'),
                content=content)).items()])
        db.commit()


class CalendarTests(unittest.TestCase):
    def test_daily_binding_and_connect_use_explicit_research_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'custom-research.sqlite';other=Path(folder)/'research.sqlite';path=Path(folder)/'daily.sqlite'
            research_file(source,'custom');research_file(other,'default')
            # daily.connect attaches the bound research file.
            with patch.object(research,'signature',return_value={'fixture':1}),patch.object(research,'DATABASE',other):
                research.forget_signature();self.addCleanup(research.forget_signature)
                with closing(sqlite3.connect(':memory:',uri=True)) as probe:
                    daily.attach(probe,source);inputs=daily.current(probe)
                self.assertEqual(inputs['research'],'custom')
                with closing(sqlite3.connect(path)) as db:
                    db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
                    db.execute('INSERT INTO metadata VALUES(?,?)',('daily_inputs',json.dumps(inputs)));db.commit()
                with closing(daily.connect(path,source)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM metadata').fetchone()[0],1)
                with self.assertRaisesRegex(ValueError,'Daily cache changed'):daily.connect(path)

    def test_reader_sources_are_not_in_the_daily_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'research.sqlite';research_file(source,'fixture')
            with patch.object(research,'signature',return_value={'fixture':1}),closing(sqlite3.connect(':memory:',uri=True)) as probe:
                research.forget_signature();self.addCleanup(research.forget_signature)
                daily.attach(probe,source);before=daily.current(probe)
                for module in (portfolio_results,schedule_calendar,s,daily):
                    copy=Path(folder)/Path(module.__file__).name;copy.write_text('# changed reader source')
                    with patch.object(module,'__file__',str(copy)):
                        self.assertEqual(daily.current(probe),before)

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
        # The daily cache in memory; its research facts in a private file.
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.research=Path(folder.name)/'research.sqlite'
        self.db=store.connection(self.research);self.addCleanup(self.db.close)
        for day,spy in [('2015-01-02',100),('2015-04-01',110),('2015-07-01',121)]:
            store.session(self.db,day,spy)
        for symbol,ebitda,prices in [('A',30e6,[10,20,30,15]),('B',10e6,[10,10,20,20])]:
            store.company(self.db,symbol)
            self.db.research.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',(symbol,'2014-06-30','2014-09-28',100e6,150e6,ebitda,ebitda/150e6))
            for day,price in zip(['2014-06-30','2015-01-02','2015-04-01','2015-07-01'],prices):
                store.price(self.db,symbol,day,price)
        self.db.commit()

    def copy(self,path):
        """A file copy of the daily cache that attaches the same research file."""
        copy=sqlite3.connect(path);self.db.backup(copy);copy.close()
        db=sqlite3.connect(path,uri=True);db.row_factory=sqlite3.Row;daily.attach(db,self.research)
        return db

    def test_weekly_dates_use_ordinary_financial_evaluation_with_legacy_metadata(self):
        sessions=facts.sessions(self.db)
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
        fixed=s.backtest(self.db,start=configuration['start'],end=configuration['end'],months=3,rank_to=1)['periods']
        # Explicit trades end on the final mark; this fixed schedule ends on its scheduled 1 July exit.
        labels=lambda periods:[[h['status'] for h in p['holdings']] for p in periods]
        self.assertEqual(labels(result['periods']),[['Scheduled exit'],['Marked to date']])
        self.assertEqual(labels(fixed),[['Scheduled exit'],['Scheduled exit']])
        unlabelled=lambda periods:[dict(p,holdings=[dict(h,status=None) for h in p['holdings']]) for p in periods]
        self.assertEqual(unlabelled(result['periods']),unlabelled(fixed))

    def test_financial_ratios_use_selected_report_and_reuse_books(self):
        legacy(self.db.research,'A','2014-06-30',netIncome=20e6,revenue=100e6)
        legacy(self.db.research,'A','2015-06-30',netIncome=1e9,revenue=1e9)
        options=dict(start='2015-01-02',end='2015-07-01',months=6,pool='cached',min_cap=0,min_ev=0)
        result=s.backtest(self.db,**options,filters=[dict(field='pe',op='lt',value=11),dict(field='profit_margin',op='gt',value=15)])
        self.assertEqual([h['symbol'] for h in result['periods'][0]['holdings']],['A'])
        saved=dict(self.db.execute("SELECT field,value FROM book_filters WHERE symbol='A'"))
        self.assertEqual(saved['pe'],10);self.assertEqual(saved['profit_margin'],20)
        with patch.object(financial_books,'book',side_effect=AssertionError('Books must be reused')):
            result=s.backtest(self.db,**options,filters=[dict(field='pe',op='lt',value=10)])
        self.assertEqual(result['periods'][0]['names'],0)

    def test_operating_spread_uses_entry_treasury_and_reuses_completed_books(self):
        self.db.research.executemany('INSERT INTO market_days(day,year10) VALUES(?,?)',[
            ('2014-12-31',3),('2015-01-05',99)])
        for year,margin in [(2012,.1),(2013,.2),(2014,.3),(2015,99)]:
            legacy(self.db.research,'A',f'{year}-06-30',revenue=100e6,operatingIncome=margin*100e6)
        options=dict(start='2015-01-02',end='2015-07-01',months=6,pool='cached',min_cap=0,min_ev=0)
        filters=[dict(field='operating_yield_spread_3y',op='gt',value=4)]
        result=s.backtest(self.db,**options,filters=filters)
        self.assertEqual([h['symbol'] for h in result['periods'][0]['holdings']],['A'])
        self.assertAlmostEqual(self.db.execute("SELECT value FROM book_filters WHERE symbol='A' AND field='operating_yield_spread_3y'").fetchone()[0],5)
        with patch.object(financial_books,'book',side_effect=AssertionError('Reuse books')):
            unfiltered=s.backtest(self.db,**options)
            self.assertEqual(unfiltered['periods'][0]['names'],2)
            empty=s.backtest(self.db,**options,filters=[dict(filters[0],value=6)])
            self.assertEqual(empty['periods'][0]['names'],0)

    def test_conditions_reuse_dated_books_and_exclude_missing_returns(self):
        options=dict(start='2015-01-02',end='2015-07-01',months=6,pool='cached',min_cap=0,min_ev=0)
        initial=s.backtest(self.db,**options)
        count=self.db.execute('SELECT COUNT(*) FROM book_rows').fetchone()[0]
        filtered=s.backtest(self.db,**options,filters=[dict(field='market_cap',op='gt',value=150)])
        self.assertEqual([h['symbol'] for h in filtered['periods'][0]['holdings']],['A'])
        empty=s.backtest(self.db,**options,filters=[dict(field='return_1y',op='gt',value=-100)])
        self.assertEqual(empty['periods'][0]['names'],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM book_rows').fetchone()[0],count)

    def test_selection_order_reuses_books_and_weights_only_survivors(self):
        options=dict(start='2015-01-02',end='2015-07-01',months=6,pool='cached',max_cap=150e6)
        first=s.backtest(self.db,**options,rank_to=1)
        self.assertEqual([(h['symbol'],h['rank']) for h in first['periods'][0]['holdings']],[('B',1)])
        with patch.object(financial_books,'book',side_effect=AssertionError('Order must reuse books')):
            empty=s.backtest(self.db,**options,rank_to=1,selection_order='rank_first')
            self.assertEqual(empty['periods'][0]['names'],0);self.assertIsNone(empty['cagr'])
            result=s.backtest(self.db,**options,rank_to=2,selection_order='rank_first')
        survivor=result['periods'][0]['holdings'][0]
        self.assertEqual((survivor['symbol'],survivor['rank'],survivor['weight']),('B',2,1))
        self.assertEqual(result['growth'],2)
        self.assertEqual(survivor['contribution_pp'],100)

    def test_stopped_holding_and_bankruptcy_follow_the_one_admission_rule(self):
        entry,exit_day=date(2015,1,2),date(2015,7,1)
        decide=lambda:financial_books.Screen(entry,facts.BookFacts(self.db)).decide('A','legacy',exit_day)
        held,reason=decide()
        self.assertEqual((reason,held['return_value'],held['status'],held['exit']),(None,-.25,'Scheduled exit',(exit_day,15.)))
        # A stopped holding is retained, and a declared bankruptcy overrides price.
        self.db.research.execute("DELETE FROM stock_days WHERE symbol='A' AND day='2015-07-01'")
        held,reason=decide()
        self.assertEqual((held['status'],held['return_value']),('Last available price',.5))
        with patch.object(rules,'BANKRUPT',{('A',date(2015,5,15))}):
            held,reason=decide()
        self.assertEqual((held['return_value'],held['status']),(-1.,'Bankruptcy'))

    def test_rebalance_and_compounding(self):
        result=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
        self.assertEqual(result['start'],'2015-01-02')
        self.assertEqual([p['holdings'][0]['symbol'] for p in result['periods']],['A','A'])
        self.assertEqual([p['portfolio'] for p in result['periods']],[.5,-.5])
        self.assertAlmostEqual(result['growth'],.75)
        self.assertAlmostEqual(result['spy_growth'],1.21)
        self.assertEqual(result['periods'][0]['holdings'][0]['weight'],1)
        # Cached period books are independent of screening filters.
        with patch.object(facts.BookFacts,'price',side_effect=AssertionError('Repeated books must not read prices')):
            second=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=2)
        self.assertAlmostEqual(second['growth'],1.75*.75)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM books').fetchone()[0],2)

    def test_unavailable_report_and_missing_metric(self):
        self.db.research.execute("UPDATE statements SET known='2015-01-02' WHERE symbol='A'")
        result=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
        self.assertEqual(result['periods'][0]['holdings'][0]['symbol'],'B')
        result=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,metric='ev_ebitda_3y')
        self.assertIsNone(result['growth']);self.assertIsNone(result['cagr'])
        self.assertTrue(all(p['names']==0 for p in result['periods']))

    def test_a_bankruptcy_counts_only_in_the_book_whose_window_contains_its_day(self):
        # One temporary loss of A on 15 May 2015: inside the April book, outside the January book.
        with patch.object(rules,'BANKRUPT',{('A',date(2015,5,15))}):
            result=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=2)
            self.assertTrue(rules.bankrupt('A',date(2015,4,1),date(2015,5,15)))
            self.assertFalse(rules.bankrupt('A',date(2015,5,15),date(2015,7,1)))
        first,second=({h['symbol']:h for h in p['holdings']} for p in result['periods'])
        self.assertEqual((first['A']['return_value'],first['A']['status']),(.5,'Scheduled exit'))
        self.assertEqual((second['A']['return_value'],second['A']['status']),(-1.,'Bankruptcy'))
        self.assertEqual((second['B']['return_value'],second['B']['status']),(0.,'Scheduled exit'))

    def test_stop_and_missing_buy(self):
        self.db.research.execute("DELETE FROM stock_days WHERE symbol='A' AND day='2015-07-01'")
        self.db.research.execute("DELETE FROM stock_days WHERE symbol='B' AND day='2015-01-02'")
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
        store.company(self.db,'C')
        self.db.research.execute("INSERT INTO statements VALUES('C','2014-06-30','2014-09-28',50000000,75000000,60000000,.8)")
        for day in ('2014-06-30','2015-01-02','2015-04-01','2015-07-01'):
            store.price(self.db,'C',day,10)
        self.db.commit()
        options=dict(start='2015-01-01',end='2015-07-01',months=3,rank_to=1,min_cap=0,min_ev=0)
        original=s.backtest(self.db,pool='legacy',**options)
        self.assertEqual([p['holdings'][0]['symbol'] for p in original['periods']],['A','A'])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM book_rows WHERE pool='cached'").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM book_metrics WHERE pool='cached'").fetchone()[0],0)
        saved=[tuple(row) for row in self.db.execute("SELECT * FROM book_rows WHERE pool='legacy' ORDER BY book,symbol")]
        periods=[tuple(row) for row in self.db.execute('SELECT * FROM books ORDER BY book')]
        with patch.object(facts.BookFacts,'price',wraps=facts.BookFacts.price,autospec=True) as lookup:
            wider=s.backtest(self.db,pool='cached',**options)
        self.assertGreater(lookup.call_count,0)
        self.assertEqual([p['holdings'][0]['symbol'] for p in wider['periods']],['C','C'])
        self.assertEqual(wider['growth'],1.)
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM books ORDER BY book')],periods)
        self.assertEqual([tuple(row) for row in self.db.execute("SELECT * FROM book_rows WHERE pool='legacy' ORDER BY book,symbol")],saved)
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT pool,COUNT(*) FROM book_pools GROUP BY pool')],[('cached',2),('legacy',2)])
        # A new connection must recognize both pools, including after changing
        # rank/filter/metric parameters. No reports or daily prices are reread.
        with tempfile.TemporaryDirectory() as tmp:
            reopened=self.copy(Path(tmp)/'daily.sqlite')
            try:
                with patch.object(facts.BookFacts,'price',side_effect=AssertionError('Completed pool')),patch.object(facts.BookFacts,'reports',side_effect=AssertionError('Completed pool')):
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
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM book_rows WHERE pool='legacy'").fetchone()[0],0)
        second=s.backtest(self.db,pool='legacy',**options)
        for period in first['periods']:
            for stock in period['holdings']:
                self.assertEqual(stock['pool'],'cached')
                stock['pool']='legacy'
        self.assertEqual(first['periods'],second['periods'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM books').fetchone()[0],2)

    def test_empty_pool_is_complete_and_other_pool_can_be_added(self):
        self.db.research.execute('UPDATE statements SET market_cap=50000000')
        options=dict(start='2015-01-01',end='2015-07-01',months=3,rank_to=1,min_cap=0,min_ev=0)
        empty=s.backtest(self.db,pool='legacy',**options)
        self.assertIsNone(empty['cagr'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM book_rows').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM book_pools').fetchone()[0],2)
        with patch.object(facts.BookFacts,'price',side_effect=AssertionError('Empty completed pool')),patch.object(facts.BookFacts,'reports',side_effect=AssertionError('Empty completed pool')):
            repeat=s.backtest(self.db,pool='legacy',**options)
        self.assertEqual(repeat['periods'],empty['periods'])
        populated=s.backtest(self.db,pool='cached',**options)
        self.assertTrue(all(p['names']==1 for p in populated['periods']))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM books').fetchone()[0],2)


class ShutdownTests(unittest.TestCase):
    def setUp(self):
        BacktestTests.setUp(self)
        # Keep a committed book to verify an interrupted new schedule cannot
        # remove completed work or change its source prices/financials.
        s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=12,rank_to=1)

    def counts(self,db):
        return {table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                for table in ('stock_days','statements','books','book_rows','book_metrics','book_pools')}

    def contents(self,db):
        return {table:sorted([tuple(row) for row in db.execute('SELECT * FROM '+table)],key=repr)
                for table in ('stock_days','statements','books','book_rows','book_metrics','book_pools')}

    def test_interrupted_second_pool_preserves_completed_first_pool(self):
        before=self.contents(self.db)
        with patch.object(metrics,'evaluate',side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=12,pool='cached',rank_to=1)
        self.assertEqual(self.contents(self.db),before)
        retry=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=12,pool='cached',rank_to=1)
        self.assertEqual(retry['growth'],.75)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM books').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM book_pools').fetchone()[0],2)

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
from backtest.inputs import daily
db=sqlite3.connect(sys.argv[2],uri=True);db.row_factory=sqlite3.Row
daily.attach(db,sys.argv[4])
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
            process=subprocess.Popen([sys.executable,'-c',child_code,str(Path(__file__).resolve().parents[1]),str(path),str(marker),str(self.research)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
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
            recovered=sqlite3.connect(path,uri=True);recovered.row_factory=sqlite3.Row;daily.attach(recovered,self.research)
            try:
                self.assertEqual(recovered.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(self.counts(recovered),before)
                self.assertEqual(self.contents(recovered),rows)
                retry=s.backtest(recovered,start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
                self.assertAlmostEqual(retry['growth'],.75)
                self.assertEqual(recovered.execute('SELECT COUNT(*) FROM books').fetchone()[0],3)
            finally:recovered.close()


class KeptBookTests(unittest.TestCase):
    """The in-place book cache after research's fact diff: the change-day rule (books.kept) through daily.prepare.

    Each test edits the private raw cache once, as a download would, and runs
    the nightly preparation: research's full build, then the book cache in
    place. DAY is just after the horizon of the third monthly book (2015-03-02
    to 2015-04-01): that book and the two before it stay, the later three go.
    """
    SESSIONS=['2015-01-02','2015-02-02','2015-03-02','2015-04-01','2015-05-01','2015-06-01','2015-07-01']
    OPTIONS=dict(start='2015-01-01',end='2015-07-01',months=1,rank_to=3,min_cap=0,min_ev=0)
    DAY='2015-04-02'
    # A fiscal date whose known day (fiscal + rules.LAG) is DAY.
    FISCAL='2015-01-02'

    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.root=root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.raw=raw=root/'raw';(raw/'px').mkdir(parents=True)
        self.source=root/'data'/'research.sqlite';self.path=root/'data'/'schedules.sqlite'
        days=['2014-06-30']+self.SESSIONS
        for symbol,prices in [('A',[10,20,22,24,26,28,30,32]),('B',[10,10,11,12,13,12,11,10]),('C',[10,10,10,10,10,10,10,10])]:
            self.write('px/'+symbol+'.json',dict(div=[dict(date=d,adjClose=p) for d,p in zip(days,prices)]))
        self.write('universe.json',[dict(symbol=symbol,name=symbol,exchange='NYSE',sector='Energy',listed=True) for symbol in 'ABC'])
        self.reports={symbol:[self.report('2014-06-30',ebitda)] for symbol,ebitda in [('A',30e6),('B',20e6),('C',10e6)]}
        self.write_reports()
        self.write('spy-div.json',[dict(date=d,adjClose=100+i) for i,d in enumerate(self.SESSIONS)])
        self.write('treasury.json',[dict(date=d,month3=2,year10=3) for d in self.SESSIONS])
        self.annual('A',[dict(date='2014-06-30',reportedCurrency='USD',revenue=100e6,netIncome=10e6)])
        self.generation=0
        for owner,key,value in [(research,'ROOT',root),(research,'RAW',raw),(market,'RAW',raw)]:
            self.context.enter_context(patch.object(owner,key,value))
        self.context.enter_context(patch.object(cache_access,'workspace',cache_access.WorkspaceAccess(root/'cache.lock')))
        # Each edit is a new accepted raw signature, as a data-panel action gives.
        self.context.enter_context(patch.object(research,'signature',side_effect=lambda:{'fixture':self.generation}))
        research.forget_signature();self.addCleanup(research.forget_signature)
        self.context.enter_context(redirect_stdout(io.StringIO()))
        daily.prepare(self.path,self.source)
        self.saved=self.backtest()
        self.assertEqual(len(self.saved),6)
        self.before=[key for key in self.saved if key[1]<self.DAY]
        self.assertEqual(len(self.before),3)

    @staticmethod
    def report(fiscal,ebitda=20e6):
        return dict(date=fiscal,marketCap=100e6,enterpriseValue=150e6,evToEBITDA=150e6/ebitda,reportedCurrency='USD')

    def write(self,name,value):
        (self.raw/name).write_text(json.dumps(value))

    def edit(self,name,change):
        """Change one saved JSON file; change(value) edits its parsed value."""
        path=self.raw/name;value=json.loads(path.read_text());change(value);path.write_text(json.dumps(value))

    def write_reports(self):
        with (self.raw/'metrics.jsonl').open('w') as handle:
            for symbol,rows in self.reports.items():
                handle.write(json.dumps(dict(symbol=symbol,rows=rows))+'\n')

    def annual(self,symbol,rows):
        financial_inputs.publish(self.raw,symbol,'income-statement',rows,{},self.raw/'coverage.json')

    @staticmethod
    def book_rows(db):
        """Saved dated books by (entry, exit, pool), independent of book ids."""
        books={}
        for book,entry,exit_day in db.execute('SELECT book,entry,exit FROM books WHERE exit IS NOT NULL ORDER BY book'):
            for pool, in db.execute('SELECT pool FROM book_pools WHERE book=? ORDER BY pool',(book,)):
                books[(entry,exit_day,pool)]=[sorted((tuple(row)[2:] for row in db.execute(
                    f'SELECT * FROM {table} WHERE book=? AND pool=?',(book,pool))),key=repr)
                    for table in ('book_rows','book_filters','book_metrics')]
        return books

    def stored(self,path=None):
        with closing(sqlite3.connect(path or self.path)) as db:
            return self.book_rows(db)

    def backtest(self,path=None):
        """Run the monthly test on a cache; return its stored dated books."""
        with closing(daily.connect(path or self.path,self.source)) as cache:
            s.backtest(cache,**self.OPTIONS)
            return self.book_rows(cache)

    def update(self):
        """The nightly preparation after one edit; return research's fact diff rows."""
        self.generation+=1
        daily.prepare(self.path,self.source)
        with closing(sqlite3.connect(self.source)) as db:
            return research.changes(db)['rows']

    def assert_kept(self,kept):
        """Exactly kept stay, unchanged; one open book at the latest date; a rerun equals a full build."""
        self.assertEqual(self.stored(),{key:self.saved[key] for key in kept})
        with closing(daily.connect(self.path,self.source)) as cache:
            self.assertEqual([row[0] for row in cache.execute('SELECT entry FROM books WHERE exit IS NULL')],
                             [research.identity(cache,'research')['latest_date']])
        rerun=self.backtest()
        fresh=self.root/'data'/'fresh.sqlite'
        daily.prepare(fresh,self.source)
        self.assertEqual(rerun,self.backtest(fresh))

    def test_price_row_just_after_the_horizon_keeps_the_book_and_on_it_drops_it(self):
        self.edit('px/A.json',lambda value:value['div'].append(dict(date=self.DAY,adjClose=25)))
        self.assertEqual(self.update(),dict(prices={'A':self.DAY},market={},statements={},annual={}))
        self.assert_kept(self.before)
        self.saved=self.stored()
        self.edit('px/B.json',lambda value:next(row for row in value['div'] if row['date']=='2015-04-01').update(adjClose=99))
        self.assertEqual(self.update()['prices'],{'B':'2015-04-01'})
        self.assert_kept(self.before[:2])

    def test_market_row_just_after_the_horizon_keeps_the_book(self):
        self.edit('treasury.json',lambda rows:rows.append(dict(date=self.DAY,month3=2.5,year10=3)))
        self.assertEqual(self.update()['market'],{'':self.DAY})
        self.assert_kept(self.before)

    def test_statement_known_just_after_the_horizon_keeps_the_book(self):
        self.reports['B'].append(self.report(self.FISCAL,25e6));self.write_reports()
        self.assertEqual(self.update(),dict(prices={},market={},statements={'B':self.FISCAL},annual={}))
        self.assert_kept(self.before)

    def test_legacy_annual_value_known_just_after_the_horizon_keeps_the_book(self):
        self.annual('A',[dict(date=self.FISCAL,reportedCurrency='USD',revenue=120e6,netIncome=12e6)])
        self.assertEqual(self.update(),dict(prices={},market={},statements={},annual={'A':self.FISCAL}))
        self.assert_kept(self.before)

    def test_added_company_is_visible_from_its_earliest_known_statement(self):
        self.edit('universe.json',lambda rows:rows.append(dict(symbol='D',name='D',exchange='NYSE',sector='Energy',listed=True)))
        self.reports['D']=[self.report(self.FISCAL)];self.write_reports()
        self.assertEqual(self.update(),dict(prices={},market={},statements={'D':self.FISCAL},annual={}))
        self.assert_kept(self.before)

    def test_removed_company_drops_every_book_from_its_earliest_known_statement(self):
        # Statements keep only the saved companies: the statements diff covers the removal.
        self.edit('universe.json',lambda rows:rows.pop())
        self.assertEqual(self.update(),dict(prices={},market={},statements={'C':'2014-06-30'},annual={}))
        self.assert_kept([])

    def test_spy_session_alone_is_a_market_change(self):
        # The third book reads SPY on its exit day, 2015-04-01.
        self.edit('spy-div.json',lambda rows:next(row for row in rows if row['date']=='2015-04-01').update(adjClose=150))
        self.assertEqual(self.update(),dict(prices={},market={'':'2015-04-01'},statements={},annual={}))
        self.assert_kept(self.before[:2])

    def test_ten_year_yield_alone_is_a_market_change(self):
        # The third book reads the 10-year yield on its entry day, 2015-03-02.
        self.edit('treasury.json',lambda rows:next(row for row in rows if row['date']=='2015-03-02').update(year10=4))
        self.assertEqual(self.update(),dict(prices={},market={'':'2015-03-02'},statements={},annual={}))
        self.assert_kept(self.before[:1])

    def test_price_file_removed_or_added_for_a_company_that_stays(self):
        path=self.raw/'px'/'C.json';path.unlink()
        self.assertEqual(self.update(),dict(prices={'C':'2014-06-30'},market={},statements={},annual={}))
        self.assert_kept([])
        self.saved=self.stored()
        self.write('px/C.json',dict(div=[dict(date=day,adjClose=10) for day in [self.DAY,*self.SESSIONS[4:]]]))
        self.assertEqual(self.update(),dict(prices={'C':self.DAY},market={},statements={},annual={}))
        self.assert_kept(self.before)

    def test_annual_file_added_or_removed_for_a_company_that_stays(self):
        self.annual('B',[dict(date=self.FISCAL,reportedCurrency='USD',revenue=50e6,netIncome=5e6)])
        self.assertEqual(self.update(),dict(prices={},market={},statements={},annual={'B':self.FISCAL}))
        self.assert_kept(self.before)
        self.saved=self.stored()
        financial_inputs.asset_path(self.raw,'A','income-statement').unlink()
        self.assertEqual(self.update(),dict(prices={},market={},statements={},annual={'A':'2014-06-30'}))
        self.assert_kept([])

    def test_legacy_field_list_change_drops_every_book(self):
        # An edit to financial_inputs.ENDPOINTS is fact-row code only; the book identity names facts.LEGACY.
        legacy=tuple((endpoint,tuple(item for item in fields if item[0]!='netIncome')) for endpoint,fields in facts.LEGACY)
        identity=research.code_identity
        with patch.object(facts,'LEGACY',legacy), \
                patch.object(research,'code_identity',side_effect=lambda role:identity(role)+('x' if role=='facts' else '')):
            self.update()
            self.assertEqual(self.stored(),{})
            rerun=self.backtest()
            self.assertNotIn('pe',{row[1] for rows,filters,metrics in rerun.values() for row in filters})
            fresh=self.root/'data'/'fresh.sqlite'
            daily.prepare(fresh,self.source)
            self.assertEqual(rerun,self.backtest(fresh))
        self.assertIn('pe',{row[1] for rows,filters,metrics in self.saved.values() for row in filters})

    def test_names_sectors_and_listing_are_not_book_inputs(self):
        self.edit('universe.json',lambda rows:rows[0].update(name='Renamed',sector='Utilities',listed=False))
        self.assertEqual(self.update(),dict(prices={},market={},statements={},annual={}))
        self.assert_kept(list(self.saved))

    def test_one_session_append_keeps_every_book_and_skips_unchanged_files(self):
        folder=self.root/'logs';self.addCleanup(diagnostics.close);diagnostics.configure(folder)
        day='2015-08-03'
        for name in ('A','B'):
            self.edit(f'px/{name}.json',lambda value:value['div'].insert(0,dict(date=day,adjClose=40)))
        self.edit('spy-div.json',lambda rows:rows.append(dict(date=day,adjClose=120)))
        self.edit('treasury.json',lambda rows:rows.append(dict(date=day,month3=2.5,year10=4)))
        self.assertEqual(self.update(),dict(prices={'A':day,'B':day},market={'':day},statements={},annual={}))
        with closing(daily.connect(self.path,self.source)) as cache:
            with patch.object(financial_books,'book',side_effect=AssertionError('Kept books must be reused')):
                s.backtest(cache,**self.OPTIONS)
        self.assert_kept(list(self.saved))
        prepared=[record for record in diagnostics.records(folder) if record['event'] in ('prepare.research','prepare.daily')]
        built,refreshed=prepared[0],prepared[1]
        self.assertEqual((built['counts']['price_files_compared'],built['counts']['price_files_skipped']),(2,1))
        self.assertEqual((refreshed['outcome'],refreshed['books_previous'],refreshed['books_kept'],refreshed['changed_from']),
                         ('refreshed',7,6,day))
        self.assertLessEqual({'research','input_check','drop_books','latest_book','commit'},refreshed['stages'].keys())

    def test_short_book_reach_covers_prices_after_its_exit(self):
        for name,price in [('A',23),('B',11),('C',10)]:
            self.edit(f'px/{name}.json',lambda value:value['div'].append(dict(date='2015-03-04',adjClose=price)))
        self.edit('spy-div.json',lambda rows:rows.append(dict(date='2015-03-04',adjClose=103)))
        self.update()
        short=dict(dates=['2015-03-02'],start='2015-03-01',end='2015-03-04',rank_to=3,min_cap=0,min_ev=0)
        with closing(daily.connect(self.path,self.source)) as cache:
            s.backtest_dates(cache,**short)
        before=self.stored()
        key=('2015-03-02','2015-03-04','legacy')
        self.assertEqual(financial_books.horizon(date(2015,3,2),date(2015,3,4)),date(2015,3,6))
        # A price after the two-day book's exit and after its entry reach keeps it; one within the reach drops it.
        for day,stays in (('2015-03-07',True),('2015-03-06',False)):
            self.edit('px/A.json',lambda value:value['div'].append(dict(date=day,adjClose=23.5)))
            self.update()
            after=self.stored()
            self.assertEqual(key in after,stays,day)
            self.assertEqual(after,{book:value for book,value in before.items()
                if financial_books.horizon(date.fromisoformat(book[0]),date.fromisoformat(book[1]))<date.fromisoformat(day)})
            before=after

    def test_interrupted_update_leaves_the_previous_cache(self):
        before=self.path.read_bytes()
        self.edit('px/A.json',lambda value:value['div'].append(dict(date=self.DAY,adjClose=25)))
        original=financial_books.book
        def interrupted(entry,exit_day,*args):
            if exit_day is None:raise KeyboardInterrupt()
            return original(entry,exit_day,*args)
        self.generation+=1
        with patch.object(financial_books,'book',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):daily.prepare(self.path,self.source)
        # The deletes, the binding and the open book roll back together.
        self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(self.path.with_name(self.path.name+'-journal').exists())
        self.assertEqual(self.stored(),self.saved)
        daily.prepare(self.path,self.source)
        self.assert_kept(self.before)

    def test_book_identity_change_empties_and_refills_the_cache(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            binding=json.loads(daily.binding(db));binding['books']='0'*64
            db.execute("UPDATE metadata SET value=? WHERE key='daily_inputs'",(json.dumps(binding),))
        daily.prepare(self.path,self.source)
        self.assertEqual(self.stored(),{})
        self.assertEqual(self.backtest(),self.saved)

    def test_older_version_cache_is_rebuilt_from_empty(self):
        self.path.unlink()
        with closing(sqlite3.connect(self.path)) as db,db:
            db.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);'
                             'CREATE TABLE prices(symbol TEXT,day TEXT,adjusted REAL,PRIMARY KEY(symbol,day)) WITHOUT ROWID;')
            db.execute("INSERT INTO metadata VALUES('daily_inputs',?)",(json.dumps(dict(version=daily.VERSION-1,research='old',books='old')),))
        daily.prepare(self.path,self.source)
        with closing(daily.connect(self.path,self.source)) as cache:
            self.assertNotIn('prices',{row[0] for row in cache.execute("SELECT name FROM main.sqlite_master WHERE type='table'")})
            self.assertEqual(json.loads(daily.binding(cache))['version'],daily.VERSION)
        self.assertEqual(self.backtest(),self.saved)

    def test_a_diff_from_another_base_keeps_no_book(self):
        # Two research builds before one book-cache update: the second diff's base is not the bound research.
        for day in ('2015-08-03','2015-09-01'):
            self.edit('px/A.json',lambda value:value['div'].append(dict(date=day,adjClose=25)))
            self.generation+=1
            research.prepare(self.source)
        # No book stays, so an empty file replaces the cache before the transaction, which deletes nothing.
        deleted=[]
        with patch.object(book_store,'delete',side_effect=lambda db,books:deleted.extend(books)), \
                patch.object(financial_books,'book',side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):daily.prepare(self.path,self.source)
        self.assertEqual(deleted,[])
        # An interruption after that leaves the empty cache: valid, unbound and without a book.
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertIsNone(daily.binding(db))
            self.assertEqual(book_store.stored(db),[])
        with self.assertRaisesRegex(ValueError,'changed'):daily.connect(self.path,self.source)
        daily.prepare(self.path,self.source)
        self.assert_kept([])

    def test_only_an_old_or_foreign_file_starts_the_cache_from_empty(self):
        before=self.path.read_bytes()
        locked=sqlite3.OperationalError('database is locked');locked.sqlite_errorcode=sqlite3.SQLITE_BUSY
        self.generation+=1
        with patch.object(daily,'binding',side_effect=locked):
            with self.assertRaises(sqlite3.OperationalError):daily.prepare(self.path,self.source)
        self.assertEqual(self.path.read_bytes(),before)
        for content in (b'not a database file '*64,b''):
            with self.subTest(content=content[:4]):
                self.path.write_bytes(content)
                daily.prepare(self.path,self.source)
                self.assertEqual(self.stored(),{})
                self.assertEqual(self.backtest(),self.saved)

    def test_current_cache_reads_no_raw_file(self):
        original=self.path.read_bytes()
        read=Path.read_bytes
        def source_only(path):
            # The code identities read source files, never a saved raw file.
            if path.is_relative_to(self.raw):raise AssertionError('Unchanged preparation must not read prices')
            return read(path)
        with patch.object(Path,'read_text',side_effect=AssertionError('Unchanged preparation must not parse prices')), \
                patch.object(Path,'read_bytes',source_only):
            daily.prepare(self.path,self.source)
        self.assertEqual(self.path.read_bytes(),original)
        with closing(sqlite3.connect(self.path)) as db:
            # The daily cache holds the book store and its binding only.
            self.assertEqual({row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")},
                             {'metadata',*book_store.TABLES})


if __name__=='__main__':unittest.main()
