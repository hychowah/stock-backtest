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
from backtest import calendar as schedule_calendar, calendar_requests, portfolio_results
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


def fixed(start, end, months, sessions):
    """The fixed monthly periods of a legacy request (calendar_requests.periods)."""
    return calendar_requests.periods(sessions,dict(start=start,end=end,months=months))[0]


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
        periods=fixed('2020-01-31','2020-05-31',1,sessions)
        self.assertEqual([a for a,b in periods],[date(2020,1,31),date(2020,3,2),date(2020,3,31),date(2020,4,30)])
        self.assertEqual(periods[-1][1],date(2020,5,29))
        self.assertTrue(all(periods[i][1]==periods[i+1][0] for i in range(len(periods)-1)))

    def test_supported_intervals(self):
        sessions=self.sessions(date(2015,1,1),date(2016,1,1))
        for months,count in [(1,12),(3,4),(6,2),(12,1),(24,1)]:
            self.assertEqual(len(fixed('2015-01-01','2016-01-01',months,sessions)),count)

    def test_leap_anniversary_and_invalid_dates(self):
        sessions=self.sessions(date(2020,1,1),date(2022,1,1))
        periods=fixed('2020-02-29','2021-12-31',12,sessions)
        self.assertEqual([a for a,b in periods],[date(2020,3,2),date(2021,3,1)])
        for start,end,months in [('2020-01-01','2020-02-01',2),('2020-02-01','2020-01-01',1),('2020-01-01','2023-01-01',1)]:
            with self.assertRaises(ValueError):fixed(start,end,months,sessions)


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
        with patch.object(schedule_calendar.SessionCalendar,'fixed',side_effect=AssertionError('No nominal schedule for explicit trades')):
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
        _,values=book_store.lanes(self.db,book_store.find(self.db,'2015-01-02','cached'),'cached')
        saved={field:found['A'] for field,found in values.items() if 'A' in found}
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
        self.assertAlmostEqual(self.db.execute("SELECT f_operating_yield_spread_3y FROM book_rows WHERE symbol='A'").fetchone()[0],5)
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
            self.assertEqual(empty['periods'][0]['names'],0);self.assertEqual(empty['cagr'],0.)
            result=s.backtest(self.db,**options,rank_to=2,selection_order='rank_first')
        survivor=result['periods'][0]['holdings'][0]
        self.assertEqual((survivor['symbol'],survivor['rank'],survivor['weight']),('B',2,1))
        self.assertEqual(result['growth'],2)
        self.assertEqual(survivor['contribution_pp'],100)

    def test_stopped_holding_and_bankruptcy_follow_the_one_admission_rule(self):
        entry,exit_day=date(2015,1,2),date(2015,7,1)
        def decide():
            held,reason=financial_books.Screen(entry,facts.BookFacts(self.db)).decide('A','legacy')
            self.assertIsNone(reason)
            return financial_books.close(held['entry'],exit_day,
                lambda day,forward,slack:facts.BookFacts(self.db).price('A',day,forward,slack),
                rules.bankrupt('A',entry,exit_day))
        self.assertEqual(decide(),(None,((exit_day,15.),-.25,'Scheduled exit')))
        self.db.research.execute("DELETE FROM stock_days WHERE symbol='A' AND day='2015-07-01'")
        self.assertEqual(decide()[1][1:],(.5,'Last available price'))
        with patch.object(rules,'BANKRUPT',{('A',date(2015,5,15))}):
            self.assertEqual(decide()[1][1:],(-1.,'Bankruptcy'))

    def test_rebalance_and_compounding(self):
        result=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
        self.assertEqual(result['start'],'2015-01-02')
        self.assertEqual([p['holdings'][0]['symbol'] for p in result['periods']],['A','A'])
        self.assertEqual([p['portfolio'] for p in result['periods']],[.5,-.5])
        self.assertAlmostEqual(result['growth'],.75)
        self.assertAlmostEqual(result['spy_growth'],1.21)
        self.assertEqual(result['periods'][0]['holdings'][0]['weight'],1)
        # Cached period books are independent of screening filters.
        with patch.object(financial_books,'book',side_effect=AssertionError('Repeated entries must reuse sheets')):
            second=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=2)
        self.assertAlmostEqual(second['growth'],1.75*.75)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM books').fetchone()[0],2)

    def test_cached_period_reads_share_one_transaction_and_release_before_next_period(self):
        options=dict(start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
        expected=s.backtest(self.db,**options)
        statements=[]
        self.db.set_trace_callback(lambda sql:statements.append((sql,self.db.in_transaction)))
        try:
            result=s.backtest(self.db,**options)
        finally:
            self.db.set_trace_callback(None)
        self.assertEqual(result['periods'],expected['periods'])
        self.assertFalse(self.db.in_transaction)
        reads=[active for sql,active in statements if 'book_rows' in sql or 'research.stock_days' in sql
               or sql.startswith('SELECT spy FROM research.market_days')]
        self.assertTrue(reads)
        self.assertTrue(all(reads),'Selection, holding exits and SPY must share the period transaction')
        self.assertEqual([active for sql,active in statements if sql.startswith('SELECT b.book FROM books')],
                         [False,False],'Release the read transaction before preparing the next period')
        self.assertEqual([sql for sql,_ in statements if sql in ('BEGIN','ROLLBACK')],
                         ['BEGIN','ROLLBACK','BEGIN','ROLLBACK'])

    def test_one_entry_sheet_serves_different_exits_and_closes_selected_rows_only(self):
        options=dict(start='2015-01-02',months=12,rank_to=1)
        close=financial_books.close
        with patch.object(financial_books,'close',wraps=close) as ending:
            first=s.backtest(self.db,end='2015-04-01',**options)
            self.assertEqual(ending.call_count,1)
        with patch.object(financial_books,'book',side_effect=AssertionError('Reuse across exits')), \
                patch.object(financial_books,'close',wraps=close) as ending:
            second=s.backtest(self.db,end='2015-07-01',**options)
            self.assertEqual(ending.call_count,1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM books').fetchone()[0],1)
        self.assertEqual((first['growth'],second['growth']),(1.5,.75))

    def test_impossible_missing_close_fails_instead_of_changing_selection(self):
        with patch.object(financial_books,'close',return_value=('MISSING_EXIT_PRICE',None)):
            with self.assertRaisesRegex(ValueError,'no valid exit'):
                s.backtest(self.db,start='2015-01-02',end='2015-07-01',rank_to=1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM books').fetchone()[0],0)

    def test_unavailable_report_and_missing_metric(self):
        self.db.research.execute("UPDATE statements SET known='2015-01-02' WHERE symbol='A'")
        result=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,rank_to=1)
        self.assertEqual(result['periods'][0]['holdings'][0]['symbol'],'B')
        result=s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=3,metric='ev_ebitda_3y')
        self.assertEqual(result['growth'],1.);self.assertEqual(result['cagr'],0.)
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
                with patch.object(financial_books,'book',side_effect=AssertionError('Completed pool')),patch.object(facts.BookFacts,'reports',side_effect=AssertionError('Completed pool')):
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
        self.assertEqual(empty['cagr'],0.)
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
                for table in ('stock_days','statements','books','book_rows','book_pools')}

    def contents(self,db):
        return {table:sorted([tuple(row) for row in db.execute('SELECT * FROM '+table)],key=repr)
                for table in ('stock_days','statements','books','book_rows','book_pools')}

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
            result=original(*args)
            if self.db.in_transaction:raise KeyboardInterrupt()
            return result
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
    if db.in_transaction:
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
                self.assertEqual(recovered.execute('SELECT COUNT(*) FROM books').fetchone()[0],2)
            finally:recovered.close()


class SheetGenerationTests(unittest.TestCase):
    """Sheets bind exact research content; changed inputs invalidate every entry."""
    SESSIONS=['2015-01-02','2015-02-02','2015-03-02','2015-04-01','2015-05-01','2015-06-01','2015-07-01']
    OPTIONS=dict(start='2015-01-01',end='2015-07-01',months=1,rank_to=3,min_cap=0,min_ev=0)
    DAY='2015-04-02'

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
        return {(entry,pool):[tuple(row)[2:] for row in db.execute(
            'SELECT * FROM book_rows WHERE book=? AND pool=? ORDER BY symbol',(book,pool))]
            for book,entry in db.execute('SELECT book,entry FROM books WHERE latest=0')
            for pool, in db.execute('SELECT pool FROM book_pools WHERE book=?',(book,))}

    def stored(self):
        with closing(sqlite3.connect(self.path)) as db:return self.book_rows(db)

    def backtest(self,path=None):
        with closing(daily.connect(path or self.path,self.source)) as cache:
            s.backtest(cache,**self.OPTIONS)
            return self.book_rows(cache)

    def update(self):
        self.generation+=1
        daily.prepare(self.path,self.source)

    def test_changed_research_content_drops_every_historical_sheet(self):
        self.edit('px/A.json',lambda value:value['div'].append(dict(date=self.DAY,adjClose=25)))
        self.update()
        self.assertEqual(self.stored(),{})
        rerun=self.backtest()
        fresh=self.root/'data'/'fresh.sqlite'
        daily.prepare(fresh,self.source)
        self.assertEqual(rerun,self.backtest(fresh))

    def test_unchanged_content_and_reader_code_keep_sheets(self):
        before=self.path.read_bytes()
        # Code outside both identities never changes the binding.
        from backtest import screening
        with patch.object(screening,'__doc__','Reader-only edit'):
            self.update()
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.stored(),self.saved)
        with closing(daily.connect(self.path,self.source)) as cache, \
                patch.object(financial_books,'book',side_effect=AssertionError('Reuse entries')):
            s.backtest(cache,**self.OPTIONS)

    def test_book_identity_change_empties_and_refills_the_cache(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            binding=json.loads(daily.binding(db));binding['books']='0'*64
            db.execute("UPDATE metadata SET value=? WHERE key='daily_inputs'",(json.dumps(binding),))
        daily.prepare(self.path,self.source)
        self.assertEqual(self.stored(),{})
        self.assertEqual(self.backtest(),self.saved)

    def test_interrupted_replacement_leaves_unbound_empty_cache(self):
        self.edit('px/A.json',lambda value:value['div'].append(dict(date=self.DAY,adjClose=25)))
        self.generation+=1
        with patch.object(financial_books,'book',side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):daily.prepare(self.path,self.source)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertIsNone(daily.binding(db))
            self.assertEqual(book_store.stored(db),[])
        with self.assertRaisesRegex(ValueError,'changed'):daily.connect(self.path,self.source)
        daily.prepare(self.path,self.source)
        self.assertEqual(self.stored(),{})
        self.backtest()

    def test_older_version_cache_is_rebuilt_from_empty(self):
        self.path.unlink()
        with closing(sqlite3.connect(self.path)) as db,db:
            db.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);'
                             'CREATE TABLE prices(symbol TEXT,day TEXT,adjusted REAL);')
            db.execute("INSERT INTO metadata VALUES('daily_inputs',?)",(json.dumps(dict(version=11,research='old',books='old')),))
        daily.prepare(self.path,self.source)
        self.assertEqual(self.backtest(),self.saved)
        with closing(daily.connect(self.path,self.source)) as db:
            self.assertEqual({row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")},
                             {'metadata',*book_store.TABLES})

    def test_locked_cache_is_preserved_and_foreign_files_rebuild(self):
        before=self.path.read_bytes()
        locked=sqlite3.OperationalError('database is locked');locked.sqlite_errorcode=sqlite3.SQLITE_BUSY
        with patch.object(daily,'binding',side_effect=locked):
            with self.assertRaises(sqlite3.OperationalError):daily.prepare(self.path,self.source)
        self.assertEqual(self.path.read_bytes(),before)
        for content in (b'not a database file '*64,b''):
            self.path.write_bytes(content)
            daily.prepare(self.path,self.source)
            self.assertEqual(self.stored(),{})
            self.assertEqual(self.backtest(),self.saved)

    def test_current_cache_reads_no_raw_file(self):
        before=self.path.read_bytes();read=Path.read_bytes
        def source_only(path):
            if path.is_relative_to(self.raw):raise AssertionError('No raw reads')
            return read(path)
        with patch.object(Path,'read_text',side_effect=AssertionError('No raw parsing')), \
                patch.object(Path,'read_bytes',source_only):
            daily.prepare(self.path,self.source)
        self.assertEqual(self.path.read_bytes(),before)


if __name__=='__main__':unittest.main()
