"""Dated books: calendar anchoring, point-in-time prices, compounding and reuse."""
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import json
import io
import tempfile
import subprocess
import time
from contextlib import ExitStack
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import schedules as s


class CalendarTests(unittest.TestCase):
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
        self.addCleanup(self.db.close);self.db.executescript(s.SCHEMA)
        self.db.executemany('INSERT INTO sessions VALUES(?,?)',[('2015-01-02',100),('2015-04-01',110),('2015-07-01',121)])
        for symbol,ebitda,prices in [('A',30e6,[10,20,30,15]),('B',10e6,[10,10,20,20])]:
            self.db.execute('INSERT INTO companies VALUES(?,?,?,?)',(symbol,symbol,'NYSE','Energy'))
            self.db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',(symbol,'2014-06-30','2014-09-28',100e6,150e6,ebitda,ebitda/150e6))
            for day,price in zip(['2014-06-30','2015-01-02','2015-04-01','2015-07-01'],prices):
                self.db.execute('INSERT INTO prices VALUES(?,?,?,?)',(symbol,day,price,price))
        self.db.commit()

    def test_array_and_sql_price_adapters_share_financial_policy(self):
        statement=s.histories(self.db)[0]['A'][0]
        entry,exit_day=date(2015,1,2),date(2015,7,1)
        series=[(date.fromisoformat(row[0]),row[1]) for row in self.db.execute("SELECT day,price FROM prices WHERE symbol='A' ORDER BY day")]
        array=s.r.snapshot(statement,entry,exit_day,series,series,False)
        lookup=lambda day,column,forward,slack:s.price(self.db,'A',day,column,forward=forward,slack=slack)
        self.assertEqual(array,s.financial_books.snapshot(statement,entry,exit_day,lookup,False))
        # A stopped holding is retained, and a declared bankruptcy overrides price.
        self.db.execute("DELETE FROM prices WHERE symbol='A' AND day='2015-07-01'")
        stopped=s.financial_books.snapshot(statement,entry,exit_day,lookup,False)
        self.assertEqual(stopped[-1],'Last available price')
        self.assertEqual(stopped[-2],.5)
        bankrupt=s.financial_books.snapshot(statement,entry,exit_day,lookup,True)
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
        with patch.object(s,'price',side_effect=AssertionError('Repeated books must not read daily prices')):
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


class ShutdownTests(unittest.TestCase):
    def setUp(self):
        BacktestTests.setUp(self)
        # Keep a committed book to verify an interrupted new schedule cannot
        # remove completed work or change its source prices/financials.
        s.backtest(self.db,start='2015-01-01',end='2015-07-01',months=12,rank_to=1)

    def counts(self,db):
        return {table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                for table in ('prices','statements','periods','snapshots','screening_metrics')}

    def contents(self,db):
        return {table:sorted([tuple(row) for row in db.execute('SELECT * FROM '+table)],key=repr)
                for table in ('prices','statements','periods','snapshots','screening_metrics')}

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
import schedules as s
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
            process=subprocess.Popen([sys.executable,'-c',child_code,str(Path(s.__file__).parent),str(path),str(marker)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
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
        db=sqlite3.connect(self.source);db.executescript(s.r.SCHEMA)
        db.execute("INSERT INTO companies VALUES('A','A','NYSE','Energy')")
        db.execute("INSERT INTO statements VALUES('A','2014-06-30','2014-09-28',100000000,150000000,30000000,.2)")
        db.commit();db.close()
        self.context.enter_context(patch.object(s.r,'RAW',raw))
        self.context.enter_context(patch.object(s.r.run,'RAW',raw))
        self.context.enter_context(patch.object(s,'fingerprint',return_value={'fixture':1}))
        self.context.enter_context(patch.object(s.r,'connect',side_effect=lambda *args,**kwargs:sqlite3.connect(self.source)))

    def test_publish_and_unchanged_skip(self):
        with patch.object(s.r,'prepare') as prerequisite:
            s.prepare(self.path,self.source)
        prerequisite.assert_called_once_with(self.source)
        original=self.path.read_bytes()
        db=s.connect(self.path)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM prices').fetchone()[0],1);db.close()
        with patch.object(Path,'read_text',side_effect=AssertionError('Unchanged preparation must not parse prices')):
            s.prepare(self.path,self.source)
        self.assertEqual(self.path.read_bytes(),original)

    def test_failure_preserves_previous_cache(self):
        s.prepare(self.path,self.source);original=self.path.read_bytes()
        with patch.object(s,'fingerprint',return_value={'fixture':2}),patch.object(s.r,'bars',side_effect=ValueError('bad fixture')):
            with self.assertRaisesRegex(ValueError,'bad fixture'):s.prepare(self.path,self.source)
        self.assertEqual(self.path.read_bytes(),original)
        self.assertFalse(self.path.with_name(self.path.name+'.building').exists())


class ServiceTests(unittest.TestCase):
    def setUp(self):
        BacktestTests.setUp(self)
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'website'))
        import serve
        self.serve=serve

    def request(self,payload,origin=None):
        handler=object.__new__(self.serve.Handler)
        body=json.dumps(payload).encode()
        handler.path='/api/schedule';handler.rfile=io.BytesIO(body)
        handler.headers={'Content-Length':str(len(body)),'Host':'127.0.0.1:8765'}
        if origin:handler.headers['Origin']=origin
        response=[];handler.reply=lambda status,payload:response.append((status,payload))
        def connection():
            db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
            self.db.backup(db);return db
        with patch.object(self.serve.schedules,'connect',side_effect=connection):handler.do_POST()
        return response[0]

    def test_real_handler_calculates_dates_without_a_socket(self):
        status,payload=self.request(dict(start='2015-01-01',end='2015-07-01',months=3,rank_to=1))
        self.assertEqual(status,200);self.assertEqual(len(payload['periods']),2)
        self.assertAlmostEqual(payload['growth'],.75)
        self.assertEqual(payload['periods'][0]['holdings'][0]['symbol'],'A')

    def test_errors_are_json_and_foreign_origin_is_rejected(self):
        self.assertEqual(self.request(dict(start='bad',end='2015-07-01'))[0],400)
        self.assertEqual(self.request({},origin='http://different.example')[0],403)


if __name__=='__main__':unittest.main()
