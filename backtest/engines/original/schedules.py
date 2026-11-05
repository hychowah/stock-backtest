"""Original dated calculation and calendar execution over prepared inputs."""
from backtest import screening
from datetime import date
import json
import time

from backtest.inputs import research as r
from backtest.financial import metrics as metrics
from backtest.financial import books as financial_books
from backtest.runtime import backtest_control as backtest_control
from backtest.runtime import diagnostics
from backtest import calendar as schedule_calendar
from backtest import portfolio_results as portfolio_results

from backtest.inputs import daily
from backtest.financial import rules

def schedule(start, end, months, sessions):
    """Adapt the established monthly interface to the shared pure calendar."""
    configuration=schedule_calendar.legacy_configuration(dict(start=start,end=end,months=months))
    return schedule_calendar.SessionCalendar(sessions).fixed(
        configuration,checkpoint=backtest_control.checkpoint)

def compute_period(db,entry,exit_day,books,cached,pool):
    """Calculate a dated pool without writes; workers share this financial path."""
    broad,legacy=books
    statements,ranks=financial_books.candidates(books,entry)
    existing=db.execute('SELECT spy,treasury FROM periods WHERE entry=? AND exit=?',(str(entry),str(exit_day))).fetchone()
    if existing is not None:
        spy_return,treasury=existing
    else:
        spy=dict(db.execute('SELECT day,price FROM sessions WHERE day IN (?,?)',(str(entry),str(exit_day))).fetchall())
        treasury=db.execute('SELECT yield_value FROM treasuries WHERE day<=? ORDER BY day DESC LIMIT 1',(str(entry),)).fetchone()
        treasury=treasury[0] if treasury else 0.
        spy_return=financial_books.benchmark_return(spy[str(entry)],spy[str(exit_day)])
    treasury10=r.ten_year_yield(db,entry)
    snapshots=[];pairs=[];filter_rows=[]
    for symbol,s in statements[pool].items():
        backtest_control.checkpoint()
        if symbol not in cached or (pool=='legacy' and symbol not in ranks):continue
        lookup=lambda day,column,forward,slack:daily.price(db,symbol,day,column,forward=forward,slack=slack)
        row=financial_books.snapshot(s,entry,exit_day,lookup,(entry.year,symbol) in rules.BANKRUPT)
        if row is None:continue
        fiscal,entry_date,end_date,cap,ev,ebitda,yield_value,multiple,ret,status=row
        if not financial_books.eligible(pool,cap,ev):continue
        observation=dict(symbol=symbol,fiscal=fiscal,market_cap=cap,enterprise_value=ev,ev_ebitda=multiple,ebitda_yield=yield_value)
        snapshots.append((symbol,ranks.get(symbol),fiscal,entry_date,end_date,cap,ev,ebitda,yield_value,multiple,financial_books.yield_spread(yield_value,treasury),ret,status))
        history=[dict(row,fiscal=str(row['fiscal']),known=str(row['known'])) for row in broad[symbol]]
        evaluated=metrics.evaluate(observation,history)
        filter_rows.extend((symbol,key,value) for key,value in metrics.filter_values(observation,evaluated,entry,lookup,{record[0]:json.loads(record[1]) for record in db.execute('SELECT fiscal,values_json FROM financial_inputs WHERE symbol=?',(symbol,))},treasury10).items())
        for metric,(multiple,yield_value) in evaluated.items():
            pairs.append((symbol,metric,multiple,yield_value))
    return dict(entry=str(entry),exit=str(exit_day),pool=pool,
                period=(str(entry),str(exit_day),spy_return,treasury,len(ranks),len(statements['cached'])),
                snapshots=snapshots,metrics=pairs,filters=filter_rows)

def prepare_period(db,entry,exit_day,books,cached,pool='legacy'):
    completed=daily.prepared_period(db,entry,exit_day,pool)
    if completed is not None:return completed
    diagnostics.count('books_calculated')
    return daily.store_period(db,compute_period(db,entry,exit_day,books,cached,pool))

def backtest(db, *, start, end, months=12, book_selection=None, emit_period=None, **options):
    """Regular schedules and random-date batches share one book evaluator."""
    sessions=[date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
    periods=schedule(start,end,months,sessions)
    return backtest_periods(db,periods,months=months,book_selection=book_selection,emit_period=emit_period,**options)

def backtest_calendar(db, *, book_selection=None, emit_period=None, **request):
    """Evaluate a version-1 calendar with the ordinary complete-book policy.

    Requested calendar metadata remains separate from resolved trading sessions.
    Explicit dates preserve the common cash window used by random trials.
    """
    from backtest import calendar_requests as calendar_requests
    sessions=[date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
    periods,first,options,metadata=calendar_requests.periods(
        sessions,request,checkpoint=backtest_control.checkpoint)
    return _backtest_periods(db,periods,common_start=first,frequency=metadata,book_selection=book_selection,emit_period=emit_period,**options)

def dated_periods(dates,start,end,months,sessions):
    """Keep legacy month validation; explicit trades need no nominal schedule."""
    schedule_calendar.legacy_configuration(dict(start=start,end=end,months=months))
    return schedule_calendar.SessionCalendar(sessions).explicit(
        dates,start,end,checkpoint=backtest_control.checkpoint)

def backtest_dates(db, *, dates, start, end, months=12, book_selection=None, emit_period=None, **options):
    """Evaluate explicit trades, holding cash before the first trade for both sides."""
    sessions=[date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
    first,final,periods=dated_periods(dates,start,end,months,sessions)
    return _backtest_periods(db,periods,months=months,common_start=first,book_selection=book_selection,emit_period=emit_period,**options)

def backtest_periods(db, periods, *, months, book_selection=None, emit_period=None, **options):
    return _backtest_periods(db,periods,months=months,book_selection=book_selection,emit_period=emit_period,**options)

def _backtest_periods(db, periods, *, months=None, common_start=None, frequency=None, book_selection=None, emit_period=None, **options):
    """Prepare missing books atomically and apply the shared SQL screener."""
    backtest_control.checkpoint()
    started=time.perf_counter()
    periods=portfolio_results.validate_periods(periods,common_start)
    allowed={'rank_from','rank_to','pool','metric','min_cap','max_cap','min_ev','min_yield','max_multiple','sector','exchange','filters','selection_order'}
    if book_selection is None:
        if set(options)-allowed:raise ValueError('Unknown screening option.')
        screening.validate_selection(**options)
    pool=book_selection.pool if book_selection is not None else options.get('pool','legacy')
    missing=any(daily.prepared_period(db,a,b,pool) is None for a,b in periods)
    with diagnostics.stage('histories'):
        books=daily.histories(db) if missing else None
        cached=daily.cached_symbols(db) if missing else set()
    def select_period(entry,exit_day):
        with diagnostics.stage('books'):
            period_id=prepare_period(db,entry,exit_day,books,cached,pool)
        with diagnostics.stage('selection'):
            stocks=(screening.select(db,period=(period_id,period_id),**options) if book_selection is None
                    else book_selection.select(db,period_id,entry,exit_day))
        spy=db.execute('SELECT spy FROM periods WHERE year=?',(period_id,)).fetchone()[0]
        return dict(entry=str(entry),exit=str(exit_day),holdings=stocks,spy=spy)
    with db:
        contract = book_selection.contract if book_selection is not None else 1
        if emit_period is None:
            result=portfolio_results.evaluate(periods,select_period,common_start=common_start,
                checkpoint=backtest_control.checkpoint,contract=contract)
        else:
            result=portfolio_results.evaluate_into(periods,select_period,emit_period,common_start=common_start,
                checkpoint=backtest_control.checkpoint,contract=contract)
    result.update(frequency if frequency is not None else dict(months=months),options=options,seconds=time.perf_counter()-started)
    return result
