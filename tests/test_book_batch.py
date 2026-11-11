"""Parallel read-only calculation, first-use planning, and atomic trial saves."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import book_store, daily, facts
from backtest.financial import books, metrics
from backtest.runtime import backtest_control
from datetime import date
import copy
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]
from backtest.engines.original import book_batch as b
from backtest.engines.original import robustness as r
from backtest.engines.original import schedules as s
import test_robustness as fixtures
import book_store_fixture as store


def financial(result):
    return {key:value for key,value in result.items() if key not in ('seconds','execution')}


class BookBatchTests(unittest.TestCase):
    config=fixtures.RobustnessTests.config

    def setUp(self):
        fixtures.RobustnessTests.setUp(self)
        store.company(self.db,'B',name='Stopped company')
        store.company(self.db,'C',name='Small company',exchange='NASDAQ',sector='Technology')
        store.price(self.db,'B','2014-06-30',10)
        store.price(self.db,'C','2014-06-30',10)
        self.db.research.execute("INSERT INTO stock_days SELECT 'C',day,adjusted,adjusted_reason,volume,volume_reason FROM stock_days WHERE symbol='A' AND day>'2014-06-30'")
        self.db.research.execute("INSERT INTO stock_days SELECT 'B',day,adjusted,adjusted_reason,volume,volume_reason FROM stock_days WHERE symbol='A' AND day>='2015-01-01' AND day<'2015-09-01'")
        for year in (2012,2013,2014,2015):
            self.db.research.execute('INSERT OR IGNORE INTO statements VALUES(?,?,?,?,?,?,?)',('A',f'{year}-06-30',f'{year}-09-28',100e6,150e6,30e6,.2))
            self.db.research.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',('B',f'{year}-06-30',f'{year}-09-28',100e6,150e6,35e6,.23))
            self.db.research.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',('C',f'{year}-06-30',f'{year}-09-28',50e6,75e6,20e6,20/75))
        # Stored valuation sums, so every book also reads the valuation averages.
        self.db.research.executemany('INSERT INTO valuation_sums VALUES(?,?,?,?,?,?,?,?)',[
            (symbol,day,earnings*scale,sales*scale,equity*scale,days,days,days) for symbol,scale in (('A',1.),('B',.5),('C',.25))
            for day,earnings,sales,equity,days in (('2011-01-03',.5,2.,1.,100),('2014-12-31',3.,14.,5.,400),('2016-01-04',-1.,20.,6.,650))])
        self.db.commit()

    def file_copy(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        path=Path(folder.name)/'daily.sqlite'
        db=sqlite3.connect(path);self.db.backup(db);db.row_factory=sqlite3.Row
        # Research is read-only, as in a daily connection: a trial write locks only the cache.
        daily.attach(db,self.research)
        self.addCleanup(db.close)
        return db,path

    def test_first_use_deduplication_and_completed_pool_reuse(self):
        config=self.config(trials=3,seed=11)
        config['samples'][1]=config['samples'][0][:]
        planned=b.plan(self.db,config)
        self.assertEqual(planned['trials'][1],[])
        self.assertEqual(len(planned['jobs']),len(set(planned['jobs'])))
        with patch.object(books,'book',wraps=books.book) as compute,patch.object(facts.books,'pools',wraps=facts.books.pools) as reports:
            result=r.run(self.db,config,workers=1)
        self.assertEqual(compute.call_count,len(planned['jobs']))
        # The operation's facts port reads the reports once.
        self.assertEqual(reports.call_count,1)
        self.assertEqual(result['execution']['saved_books'],len(planned['jobs']))
        with patch.object(facts.BookFacts,'reports',side_effect=AssertionError('Replay reads no reports')),patch.object(b,'ProcessPoolExecutor',side_effect=AssertionError('Replay starts no processes')):
            replay=r.run(self.db,config,workers=4)
        self.assertEqual(financial(replay)['distributions'],financial(result)['distributions'])
        self.assertEqual(replay['execution']['workers'],0)
        self.assertEqual(replay['execution']['reused_books'],len(planned['jobs']))

    def test_shared_entry_with_different_trial_exits_builds_once(self):
        config=self.config(trials=2,seed=11)
        config['samples']=[['2015-01-01','2016-01-04'],['2015-01-01','2016-02-01']]
        with patch.object(books,'book',wraps=books.book) as compute:
            result=r.run(self.db,config,workers=1)
        self.assertEqual(compute.call_count,3)
        self.assertEqual(result['execution']['unique_books'],3)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM books').fetchone()[0],3)
        self.assertEqual(result['completed'],2)

    def test_automatic_workers_for_large_batches_and_serial_small_batches(self):
        db,path=self.file_copy()
        with patch.object(b,'ProcessPoolExecutor',side_effect=AssertionError('Small batches stay serial')):
            small=r.run(db,self.config(trials=2,seed=17))
        self.assertEqual(small['execution']['workers'],1)
        config=self.config(trials=40,seed=11)
        self.assertGreaterEqual(len(b.plan(db,config)['jobs']),b.MIN_PARALLEL_BOOKS)
        result=r.run(db,config)
        self.assertEqual(result['completed'],40)
        self.assertEqual(result['execution']['workers'],min(b.DEFAULT_WORKERS,os.cpu_count() or 1))

    def test_spawn_matches_serial_holdings_both_pools_and_metrics(self):
        db,path=self.file_copy()
        tables=('companies','statements','stock_days','market_days','fact_sources','valuation_sums')
        sources=lambda:{table:[tuple(row) for row in self.db.execute('SELECT * FROM research.'+table)] for table in tables}
        before=sources()
        for pool in ('legacy','cached'):
            for metric in metrics.METRICS:
                config=self.config(trials=4,seed=51,pool=pool,metric=metric,min_cap=0,min_ev=0)
                serial=r.run(self.db,config,workers=1)
                parallel=r.run(db,config,workers=2)
                for a,c in zip(serial['trials'],parallel['trials']):
                    self.assertEqual({k:v for k,v in a.items() if k!='seconds'},{k:v for k,v in c.items() if k!='seconds'})
                self.assertEqual(serial['distributions'],parallel['distributions'])
                for dates in config['samples']:
                    options=dict(dates=dates,start=config['start'],end=config['end'],months=12,**config['options'])
                    self.assertEqual(financial(s.backtest_dates(self.db,**options)),financial(s.backtest_dates(db,**options)))
        # Financial source tables are immutable during planning and calculation.
        self.assertEqual(sources(),before)
        jobs=[('2015-01-02','cached'),('2015-02-02','cached')]
        symbols={key:('A',) for key in jobs}
        with b.calculations(db,jobs,1,lambda:None,symbols=symbols) as results:serial=list(results)
        with b.calculations(db,jobs,2,lambda:None,symbols=symbols) as results:parallel=list(results)
        self.assertEqual(serial,parallel)
        self.assertIn(('A','ps_avg_3y',1/(12./300)),parallel[0]['filters'])
        self.assertTrue(all(book['candidates']>1 for book in parallel))
        self.assertEqual({row[0] for book in parallel for row in book['rows']},{'A'})
        reader=b.open_reader(path,self.research,None)
        try:
            for table in ('book_rows','research.stock_days'):
                with self.assertRaises(sqlite3.OperationalError):reader.execute('DELETE FROM '+table)
        finally:reader.close()

    def test_mid_trial_calculation_failure_saves_no_partial_books(self):
        config=self.config(trials=3,seed=11)
        planned=b.plan(self.db,config);original=books.book;calls=0
        def fail(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==len(planned['trials'][0])+1:raise RuntimeError('calculation stopped')
            return original(*args,**kwargs)
        with patch.object(books,'book',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'calculation stopped'):r.run(self.db,config,workers=1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM book_pools').fetchone()[0],len(planned['trials'][0]))
        retry=r.run(self.db,config,workers=1)
        self.assertEqual(retry['completed'],3)
        self.assertEqual(retry['execution']['reused_books'],len(planned['trials'][0]))

    def test_mid_trial_write_failure_rolls_back_and_retry_completes(self):
        config=self.config(trials=3,seed=11)
        planned=b.plan(self.db,config);original=book_store.store;calls=0
        def fail(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==len(planned['trials'][0])+1:raise RuntimeError('write stopped')
            return original(*args,**kwargs)
        with patch.object(book_store,'store',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'write stopped'):r.run(self.db,config,workers=1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM books').fetchone()[0],len(planned['trials'][0]))
        self.assertEqual(r.run(self.db,config,workers=1)['completed'],3)

    def test_parallel_interrupt_retains_complete_trial_and_reuses_on_retry(self):
        db,path=self.file_copy();config=self.config(trials=4,seed=41)
        planned=b.plan(db,config);events=[]
        def stop(event):
            events.append(event)
            if event['completed']==1:raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):r.run(db,config,stop,workers=2)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM book_pools').fetchone()[0],len(planned['trials'][0]))
        retry=r.run(db,config,events.append,workers=2)
        self.assertEqual(retry['completed'],4)
        self.assertEqual(retry['execution']['reused_books'],len(planned['trials'][0]))
        self.assertTrue(any(e['type']=='preparation' and e['workers']==2 for e in events))
        self.assertTrue(all(e['completed']<=e['trial'] for e in events))
        self.assertEqual(events[-1]['calculated_books'],retry['execution']['missing_books'])
        self.assertEqual(events[-1]['saved_books'],retry['execution']['saved_books'])

    def test_validation_and_generation_failure_precede_writes(self):
        config=self.config(trials=3,seed=11)
        for count in (0,9,2.5,True):
            with self.assertRaises(ValueError):r.run(self.db,config,workers=count)
        with self.assertRaisesRegex(ValueError,'file-backed'):r.run(self.db,config,workers=2)
        invalid=copy.deepcopy(config);invalid['samples'][-1]=['2015-01-03']
        with self.assertRaises(ValueError):r.run(self.db,invalid,workers=1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM books').fetchone()[0],0)
        db,path=self.file_copy()
        db.execute("INSERT INTO metadata VALUES('pending','edit')")
        with self.assertRaisesRegex(ValueError,'Commit input'):r.run(db,config,workers=2)
        db.rollback()
        with self.assertRaisesRegex(ValueError,'changed'):b.open_reader(path,self.research,'different generation')

    def test_a_complete_pool_is_never_written_twice(self):
        entry=date(2015,1,1);end=date(2015,7,1)
        book=books.book(entry,'legacy',facts.BookFacts(self.db))
        with self.db:book_store.store(self.db,book)
        before=[tuple(row) for row in self.db.execute('SELECT * FROM book_rows')]
        with self.assertRaises(sqlite3.IntegrityError),self.db:book_store.store(self.db,book)
        self.assertEqual(before,[tuple(row) for row in self.db.execute('SELECT * FROM book_rows')])

    def test_precompute_continues_only_missing_cached_sheets_including_empty_completion(self):
        days=('2015-01-01','2015-01-02','2015-01-05')
        self.db.research.execute('DELETE FROM market_days WHERE day NOT IN (?,?,?)',days)
        store.book(self.db,days[0],days[-1],pools=('cached',))
        store.book(self.db,days[1],pools=('cached',))  # Latest does not complete a historical sheet.
        with patch.object(books,'book',wraps=books.book) as calculate:
            b.precompute(self.db,lambda **kw:None,lambda:None)
        self.assertEqual(calculate.call_count,2)
        self.assertEqual({args.args[0] for args in calculate.call_args_list},set(map(date.fromisoformat,days[1:])))
        self.assertEqual({entry for _,entry,latest in book_store.completed(self.db,'cached') if not latest},set(days))
        self.assertEqual(book_store.completed(self.db,'legacy'),[])
        with patch.object(books,'book',side_effect=AssertionError('Completed sheets must be reused')):
            b.precompute(self.db,lambda **kw:None,lambda:None)

    def test_precompute_cancellation_keeps_only_committed_sheets(self):
        days=('2015-01-01','2015-01-02','2015-01-05')
        self.db.research.execute('DELETE FROM market_days WHERE day NOT IN (?,?,?)',days)
        cancelled=False
        def emit(**values):
            nonlocal cancelled
            if values['completed']==1:cancelled=True
        def checkpoint():
            if cancelled:raise backtest_control.Cancelled()
        with self.assertRaises(backtest_control.Cancelled):b.precompute(self.db,emit,checkpoint)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual([(entry,latest) for _,entry,latest in book_store.completed(self.db,'cached')],[(days[0],0)])
        b.precompute(self.db,lambda **kw:None,lambda:None)
        self.assertEqual(len(book_store.completed(self.db,'cached')),3)

    def test_precompute_progress_counts_retained_and_committed_sheets(self):
        days=('2015-01-01','2015-01-02','2015-01-05')
        self.db.research.execute('DELETE FROM market_days WHERE day NOT IN (?,?,?)',days)
        store.book(self.db,days[0],days[-1],pools=('cached',))
        events=[]
        def emit(**values):
            self.assertFalse(self.db.in_transaction)
            self.assertEqual(values['completed'],len(book_store.completed(self.db,'cached')))
            events.append(values)
        b.precompute(self.db,emit,lambda:None)
        self.assertEqual(events,[dict(kind='sheets',completed=count,total=3) for count in (1,2,3)])

    def test_book_read_transaction_releases_on_success_and_failure(self):
        key=('2015-01-01','legacy')
        book_facts=facts.BookFacts(self.db)
        original=books.book
        def observed(*args):
            self.assertTrue(self.db.in_transaction)
            return original(*args)
        with patch.object(books,'book',side_effect=observed):
            book=b.calculate_book(self.db,key,book_facts)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(book['entry'],key[0])
        with patch.object(books,'book',side_effect=RuntimeError('read failed')):
            with self.assertRaisesRegex(RuntimeError,'read failed'):b.calculate_book(self.db,key,book_facts)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM books').fetchone()[0],0)

    def test_forced_parent_shutdown_does_not_leave_a_worker_running(self):
        db,path=self.file_copy()
        helper=path.with_name('parent.py');ready=path.with_name('ready.json')
        helper.write_text('''from concurrent.futures import ProcessPoolExecutor
import multiprocessing,os,sys
from pathlib import Path
from threading import Event
sys.path.insert(0,'''+repr(str(ROOT))+''')
from backtest.engines.original import book_batch as b
if __name__=='__main__':
    with ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'),initializer=b.initialize_worker,initargs=(sys.argv[1],sys.argv[3],None)) as pool:
        pid=pool.submit(os.getpid).result(timeout=15)
        Path(sys.argv[2]).write_text(str(pid))
        Event().wait()
''')
        def alive(pid):
            if os.name=='nt':
                import ctypes
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                kernel.OpenProcess.restype=ctypes.c_void_p
                kernel.WaitForSingleObject.argtypes=(ctypes.c_void_p,ctypes.c_ulong)
                kernel.CloseHandle.argtypes=(ctypes.c_void_p,)
                handle=kernel.OpenProcess(0x100000,False,pid)
                if not handle:return False
                try:return kernel.WaitForSingleObject(handle,0)==258
                finally:kernel.CloseHandle(handle)
            try:
                os.kill(pid,0)
                status=Path('/proc')/str(pid)/'stat'
                return not status.exists() or status.read_text().split(') ',1)[1][0]!='Z'
            except ProcessLookupError:return False
        parent=subprocess.Popen([sys.executable,str(helper),str(path),str(ready),str(self.research)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        worker=None
        try:
            deadline=time.monotonic()+15
            while not ready.exists() and parent.poll() is None and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(ready.exists(),'Worker did not start')
            worker=int(ready.read_text())
            self.assertTrue(alive(worker))
            parent.terminate();parent.wait(timeout=5)
            deadline=time.monotonic()+5
            while alive(worker) and time.monotonic()<deadline:time.sleep(.05)
            self.assertFalse(alive(worker),'Read-only worker outlived its launcher')
            # Both files the worker read are writable again.
            self.db.research.execute("UPDATE companies SET name='Reusable after shutdown' WHERE symbol='A'")
            with db:db.execute("INSERT INTO metadata VALUES('reusable','after shutdown')")
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        finally:
            if parent.poll() is None:parent.kill();parent.wait(timeout=5)
            if worker is not None and alive(worker):os.kill(worker,15)
            parent.stderr.close()


if __name__=='__main__':unittest.main()
