"""Plan missing books once, calculate ahead, and commit through one SQLite writer.

Only requested entry/pool sheets are planned. Processes use read-only daily
connections that attach the research database the parent admitted, and the
ordinary book function (books.book over facts.BookFacts). Ordered, bounded
prefetch keeps trial saves atomic and deterministic. Large staged trials spill
to a temporary local file.
"""
from collections import deque
from bisect import bisect_right
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

from backtest import screening
from backtest.engines.original import schedules
from backtest.financial import books, rules
from backtest.inputs import book_store, daily, facts, market
from backtest import calendar_requests as calendar_requests
from backtest.runtime import backtest_control as backtest_control
from backtest.runtime import diagnostics

DEFAULT_WORKERS=8
MIN_PARALLEL_BOOKS=16
_reader=None
_facts=None


def plan(db,configuration,book_selection=None):
    """Deduplicate all required books, retaining first-use order by trial."""
    options=configuration['options']
    market_id=options.get('market','us')
    if book_selection is None:screening.validate_selection(**{key:value for key,value in options.items() if key!='market'})
    if len(configuration['samples'])!=configuration['requested']:
        raise ValueError('The number of sampled schedules must match the requested trials.')
    pool=book_selection.pool if book_selection is not None else options.get('pool','cached' if market_id!='us' else 'legacy')
    available={(entry,pool) if market_id=='us' else (entry,pool,market_id) for _,entry,latest in book_store.completed(db,pool,market=market_id) if not latest}
    sessions=facts.sessions(db,market_id)
    seen=set();jobs=[];trials=[]
    for dates in configuration['samples']:
        periods,_,_,_,_=calendar_requests.periods(sessions,dict(calendar_requests.request_fields(configuration),dates=dates),checkpoint=backtest_control.checkpoint)
        new=[]
        for entry,exit_day in periods:
            key=(str(entry),pool) if market_id=='us' else (str(entry),pool,market_id)
            if key not in seen:
                seen.add(key)
                if key not in available:
                    jobs.append(key);new.append(key)
        trials.append(new)
    return dict(jobs=jobs,trials=trials,unique_books=len(seen),reused_books=len(seen)-len(jobs))


def database_path(db,schema='main'):
    return next((row[2] for row in db.execute('PRAGMA database_list') if row[1]==schema), '')


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


def open_reader(path,research,expected):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=60)
    db.row_factory=sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        # The parent admitted this generation and its research file under cache ownership.
        if daily.binding(db)!=expected:
            raise ValueError('The daily cache changed before a calculation worker started.')
        daily.attach(db,research)
        # Books read the research facts; the cache size is per schema.
        db.execute('PRAGMA research.cache_size=-65536')
        return db
    except BaseException:
        db.close();raise


def initialize_worker(path,research,expected,market='us'):
    global _reader,_facts
    parent=multiprocessing.parent_process()
    if parent is not None:
        def follow_parent():
            parent.join()
            # Closing the launcher can kill the parent before executor cleanup.
            # These children only read, so exit promptly and release their locks.
            os._exit(0)
        Thread(target=follow_parent,daemon=True).start()
    _reader=open_reader(path,research,expected)
    _facts=facts.BookFacts(_reader,market)


def calculate(key,symbols=None):
    return calculate_book(_reader,key,_facts,symbols)


def calculate_book(db,key,book_facts,symbols=None):
    """One short read transaction per book, released before any parent write.

    Autocommit otherwise acquires a file read lock for every price lookup, which
    dominates native Windows runtime. Holding a transaction across several books
    would block the writer. A book is the smallest useful consistent read unit.
    """
    entry,pool=key[:2]
    owned=not db.in_transaction
    if owned:db.execute('BEGIN')
    try:
        return books.book(date.fromisoformat(entry),pool,book_facts,backtest_control.checkpoint,
                          **({} if symbols is None else dict(symbols=symbols)))
    finally:
        if owned:db.rollback()


@contextmanager
def calculations(db,jobs,workers,on_wait,*,symbols=None):
    """At most twice the worker count is in flight; no writer runs in children."""
    if not jobs:
        yield iter(());return
    market_id=jobs[0][2] if len(jobs[0])==3 else 'us'
    if workers==1:
        book_facts=facts.BookFacts(db,market_id)
        yield (calculate_book(db,key,book_facts,None if symbols is None else symbols[key]) for key in jobs)
        return
    executor=ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),
                                 initializer=initialize_worker,initargs=(database_path(db),database_path(db,'research'),daily.binding(db),market_id))
    pending=deque();remaining=iter(jobs)
    def submit():
        key=next(remaining,None)
        if key is not None:pending.append(executor.submit(calculate,key,None if symbols is None else symbols[key]))
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


def repair(db,changes,emit,checkpoint):
    """Repair complete historical sheets against the parent's admitted research.

    The old binding remains until daily.prepare publishes. Workers read facts
    only; each repaired sheet commits independently and is safe to repeat.
    """
    plans=[];total=0
    for code in market.MARKETS:
        port=facts.BookFacts(db,code)
        sessions={str(day) for day in facts.sessions(db,code)}
        cutoffs=sorted((day,symbol) for symbol,day in books.affected_entries(changes,port).items())
        starts=[day for day,_ in cutoffs];ordered=tuple(symbol for _,symbol in cutoffs);scopes={0:()}
        def dirty(entry):
            count=bisect_right(starts,entry)
            if count not in scopes:scopes[count]=ordered[:count]
            return scopes[count]
        for book,entry,latest in book_store.stored(db,code):
            checkpoint()
            if latest or entry not in sessions:
                with db:book_store.remove(db,book)
        ranks=code=='us' and changes['statements']
        for book,entry,_ in book_store.completed(db,'legacy',market=code):
            if ranks or dirty(entry):
                checkpoint()
                with db:book_store.remove(db,book,'legacy')
        jobs=[];symbols={}
        for _,entry,_ in sorted(book_store.completed(db,'cached',market=code),key=lambda row:row[1]):
            scope=dirty(entry)
            if scope or ranks:
                key=(entry,'cached') if code=='us' else (entry,'cached',code)
                jobs.append(key);symbols[key]=scope
        total+=len(jobs);plans.append((jobs,symbols,ranks))
    completed=0;emit(completed=0,total=total)
    for jobs,symbols,ranks in plans:
        count=worker_count(db,jobs,None)
        with calculations(db,jobs,count,checkpoint,symbols=symbols) as results:
            for key in jobs:
                checkpoint();book=next(results)
                actual=(book['entry'],book['pool']) if book.get('market','us')=='us' else (book['entry'],book['pool'],book['market'])
                if actual!=key:raise ValueError('A calculation returned a different entry sheet.')
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    book_id=book_store.store(db,book,symbols=symbols[key])
                    if ranks:book_store.refresh_ranks(db,book_id,book['pool'],book['ranks'])
                    checkpoint()
                completed+=1;emit(completed=completed,total=total)
    return completed


def precompute(db,emit,checkpoint):
    markets=['us']+[row[0] for row in db.execute('SELECT DISTINCT market FROM research.local_sessions ORDER BY market')]
    total=sum(sum(day>=rules.FIRST_DAY for day in facts.sessions(db,code)) for code in markets)
    offset=0
    for code in markets:
        def report(**value):
            emit(**{**value,'completed':offset+value['completed'],'total':total})
        _precompute_market(db,report,checkpoint,code)
        offset+=sum(day>=rules.FIRST_DAY for day in facts.sessions(db,code))


def _precompute_market(db,emit,checkpoint,market_id):
    """Fill historical cached sheets for an owned, admitted update connection.

    Existing pool completion rows, including empty sheets, are the only
    continuation evidence. Each sheet commits separately. Ordinary runs keep
    their per-trial commits and never request full historical coverage.
    """
    checkpoint()
    sessions=[str(day) for day in facts.sessions(db,market_id) if day>=rules.FIRST_DAY]
    available={entry for _,entry,latest in book_store.completed(db,'cached',market=market_id) if not latest}
    jobs=[(entry,'cached') if market_id=='us' else (entry,'cached',market_id) for entry in sessions if entry not in available]
    total=len(sessions);completed=total-len(jobs)
    emit(kind='sheets',completed=completed,total=total)
    count=worker_count(db,jobs,None)
    with calculations(db,jobs,count,checkpoint) as results:
        for key in jobs:
            checkpoint()
            book=next(results)
            if ((book['entry'],book['pool']) if book.get('market','us')=='us' else (book['entry'],book['pool'],book['market']))!=key:
                raise ValueError('A calculation returned a different entry sheet.')
            with db:
                db.execute('BEGIN IMMEDIATE')
                book_store.store(db,book)
                checkpoint()
            completed+=1
            emit(kind='sheets',completed=completed,total=total)
    checkpoint()


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
                        if ((book['entry'],book['pool']) if book.get('market','us')=='us' else (book['entry'],book['pool'],book['market']))!=key:
                            raise ValueError('A calculation returned a different dated book.')
                        pickle.dump(book,staged,protocol=pickle.HIGHEST_PROTOCOL)
                        calculated+=1;notice()
                    staged.seek(0);writing=time.perf_counter()
                    with diagnostics.stage('book_write'),db:
                        # Take the writer lock only after the whole trial is calculated.
                        if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
                        for unused in missing:
                            backtest_control.checkpoint()
                            book_store.store(db,pickle.load(staged))
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
