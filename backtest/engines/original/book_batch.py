
from backtest import screening
"""Plan missing books once, calculate ahead, and commit through one SQLite writer.

Only requested date pairs are planned. Processes use read-only connections and
the ordinary financial calculator. Ordered, bounded prefetch keeps trial saves
atomic and deterministic. Large staged trials spill to a temporary local file.
"""
from collections import deque
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from contextlib import contextmanager
from datetime import date
import multiprocessing
import os
from pathlib import Path
import pickle
import sqlite3
import tempfile
from threading import Thread
import time

from backtest.engines.original import schedules
from backtest.inputs import daily
from backtest import calendar_requests as calendar_requests
from backtest.runtime import backtest_control as backtest_control
from backtest.runtime import diagnostics

DEFAULT_WORKERS=8
MIN_PARALLEL_BOOKS=16
_reader=None
_books=None
_cached=None
_financials={}


def generation(db):
    row=db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()
    return row[0] if row else None


def plan(db,configuration,book_selection=None):
    """Deduplicate all required books, retaining first-use order by trial."""
    options=configuration['options']
    if book_selection is None:screening.validate_selection(**options)
    if len(configuration['samples'])!=configuration['requested']:
        raise ValueError('The number of sampled schedules must match the requested trials.')
    pool=book_selection.pool if book_selection is not None else options.get('pool','legacy')
    available={(row[0],row[1],pool) for row in db.execute('''
        SELECT p.entry,p.exit FROM periods p JOIN period_pools b ON b.period_id=p.year
        WHERE b.pool=?''',(pool,))}
    sessions=[date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
    seen=set();jobs=[];trials=[]
    for dates in configuration['samples']:
        periods,_,_,_,_=calendar_requests.periods(sessions,dict(calendar_requests.request_fields(configuration),dates=dates),checkpoint=backtest_control.checkpoint)
        new=[]
        for entry,exit_day in periods:
            key=(str(entry),str(exit_day),pool)
            if key not in seen:
                seen.add(key)
                if key not in available:
                    jobs.append(key);new.append(key)
        trials.append(new)
    return dict(jobs=jobs,trials=trials,unique_books=len(seen),reused_books=len(seen)-len(jobs))


def database_path(db):
    return next((row[2] for row in db.execute('PRAGMA database_list') if row[1]=='main'), '')


def worker_count(db,jobs,requested):
    if requested is not None and (type(requested) is not int or not 1<=requested<=8):
        raise ValueError('Choose between 1 and 8 calculation workers.')
    if not jobs:return 0
    if not database_path(db):
        if requested is not None and requested>1:
            raise ValueError('Parallel workers require a file-backed daily cache.')
        return 1
    if db.in_transaction:
        if requested is not None and requested>1:
            raise ValueError('Commit input changes before starting parallel workers.')
        return 1
    count=requested if requested is not None else (DEFAULT_WORKERS if len(jobs)>=MIN_PARALLEL_BOOKS else 1)
    return min(count,len(jobs),os.cpu_count() or 1)


def open_reader(path,expected):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=60)
    db.row_factory=sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA cache_size=-65536')
        # The parent admitted this generation under cache ownership.
        if generation(db)!=expected:
            raise ValueError('The daily cache changed before a calculation worker started.')
        return db
    except BaseException:
        db.close();raise


def initialize_worker(path,expected):
    global _reader,_books,_cached
    parent=multiprocessing.parent_process()
    if parent is not None:
        def follow_parent():
            parent.join()
            # Closing the launcher can kill the parent before executor cleanup.
            # These children only read, so exit promptly and release their locks.
            os._exit(0)
        Thread(target=follow_parent,daemon=True).start()
    _reader=open_reader(path,expected)
    _books=daily.histories(_reader);_cached=daily.cached_symbols(_reader)


def calculate(key):
    return calculate_book(_reader,key,_books,_cached,_financials)


def calculate_book(db,key,books,cached,financials=None):
    """One short read transaction per book, released before any parent write.

    Autocommit otherwise acquires a file read lock for every price lookup, which
    dominates native Windows runtime. Holding a transaction across several books
    would block the writer. A book is the smallest useful consistent read unit.
    """
    entry,exit_day,pool=key
    owned=not db.in_transaction
    if owned:db.execute('BEGIN')
    try:
        return schedules.compute_period(db,date.fromisoformat(entry),date.fromisoformat(exit_day),books,cached,pool,financials)
    finally:
        if owned:db.rollback()


@contextmanager
def calculations(db,jobs,workers,on_wait):
    """At most twice the worker count is in flight; no writer runs in children."""
    if not jobs:
        yield iter(());return
    if workers==1:
        books=daily.histories(db);cached=daily.cached_symbols(db);financials={}
        yield (calculate_book(db,key,books,cached,financials) for key in jobs)
        return
    executor=ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),
                                 initializer=initialize_worker,initargs=(database_path(db),generation(db)))
    pending=deque();remaining=iter(jobs)
    def submit():
        key=next(remaining,None)
        if key is not None:pending.append(executor.submit(calculate,key))
    def ordered():
        for unused in range(2*workers):submit()
        while pending:
            future=pending.popleft()
            while True:
                try:book=future.result(timeout=.25);break
                except TimeoutError:on_wait()
            submit()
            yield book
    results=ordered()
    try:
        yield results
    finally:
        results.close()
        for future in pending:future.cancel()
        executor.shutdown(wait=True,cancel_futures=True)


def evaluate_trials(db,configuration,progress=None,workers=None,*,book_selection=None,trial_sink=None):
    """Yield ordinary backtest results after each trial's missing books commit."""
    planned=plan(db,configuration,book_selection)
    count=worker_count(db,planned['jobs'],workers)
    stats=dict(workers=count,unique_books=planned['unique_books'],missing_books=len(planned['jobs']),
               reused_books=planned['reused_books'],saved_books=0,calculation_wait_seconds=0.,write_seconds=0.)
    completed=0;calculated=0;number=0;last_notice=0.
    def event(kind):
        if progress:
            progress(dict(type=kind,completed=completed,total=configuration['requested'],trial=number,
                          workers=count,calculated_books=calculated,total_new_books=len(planned['jobs']),
                          saved_books=stats['saved_books'],reused_books=planned['reused_books']))
    def notice(force=False):
        nonlocal last_notice
        backtest_control.checkpoint()
        now=time.perf_counter()
        if force or now-last_notice>=.2:
            event('preparation');last_notice=now
    with calculations(db,planned['jobs'],count,notice) as results:
        for number,(dates,missing) in enumerate(zip(configuration['samples'],planned['trials']),1):
            backtest_control.checkpoint()
            started=time.perf_counter();event('progress')
            if missing:
                # Spill large monthly/broad-pool trials rather than retaining all
                # stock rows in Python memory. The temporary file is never a cache.
                with tempfile.SpooledTemporaryFile(max_size=8*1024**2) as staged:
                    for key in missing:
                        waiting=time.perf_counter()
                        with diagnostics.stage('book_calculation'):book=next(results)
                        stats['calculation_wait_seconds']+=time.perf_counter()-waiting
                        if (book['entry'],book['exit'],book['pool'])!=key:
                            raise ValueError('A calculation returned a different dated book.')
                        pickle.dump(book,staged,protocol=pickle.HIGHEST_PROTOCOL)
                        calculated+=1;notice()
                    staged.seek(0);writing=time.perf_counter()
                    with diagnostics.stage('book_write'),db:
                        # Take the writer lock only after the whole trial is
                        # calculated. A second server may have saved a shared book.
                        if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
                        for unused in missing:
                            backtest_control.checkpoint()
                            daily.store_period(db,pickle.load(staged))
                        backtest_control.checkpoint()
                    stats['write_seconds']+=time.perf_counter()-writing
                    stats['saved_books']+=len(missing)
            if trial_sink is not None:trial_sink.start_trial(number)
            selection_args = dict(book_selection=book_selection, emit_period=trial_sink.period if trial_sink is not None else None) if book_selection is not None or trial_sink is not None else {}
            if 'calendar' in configuration:
                result=schedules.backtest_calendar(db,calendar=configuration['calendar'],dates=dates,**selection_args,**configuration['options'])
            else:
                result=schedules.backtest_dates(db,dates=dates,start=configuration['start'],end=configuration['end'],
                                       months=configuration['months'],**selection_args,**configuration['options'])
            result['seconds']=time.perf_counter()-started
            completed+=1;event('progress')
            yield number,result,stats
