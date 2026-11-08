"""Original dated calculation and calendar execution over prepared inputs."""
from backtest import screening
import time

from backtest.financial import books as financial_books
from backtest.financial import rules
from backtest.runtime import backtest_control as backtest_control
from backtest.runtime import diagnostics
from backtest import calendar as schedule_calendar
from backtest import calendar_requests
from backtest import portfolio_results as portfolio_results

from backtest.inputs import book_store, facts

def prepare_period(db,entry,pool,book_facts):
    """Return the historical entry/pool handle, building a missing sheet once.

    book_facts is the operation's facts port over the attached research
    schema (facts.BookFacts); it caches each company's inputs across books.
    """
    completed=book_store.find(db,entry,pool)
    if completed is not None:return completed
    diagnostics.count('books_calculated')
    return book_store.store(db,financial_books.book(entry,pool,book_facts,backtest_control.checkpoint))

def backtest(db, *, start, end, months=12, book_selection=None, emit_period=None, **options):
    """Regular schedules and random-date batches share one book evaluator."""
    sessions=facts.sessions(db)
    periods,_,marked,_,_=calendar_requests.periods(sessions,dict(start=start,end=end,months=months),
                                                   checkpoint=backtest_control.checkpoint)
    return _backtest_periods(db,periods,final_mark=marked,months=months,book_selection=book_selection,emit_period=emit_period,**options)

def backtest_calendar(db, *, book_selection=None, emit_period=None, **request):
    """Evaluate a version-1 calendar with the ordinary complete-book policy.

    Requested calendar metadata remains separate from resolved trading sessions.
    Explicit dates preserve the common cash window used by random trials.
    """
    sessions=facts.sessions(db)
    periods,first,marked,options,metadata=calendar_requests.periods(
        sessions,request,checkpoint=backtest_control.checkpoint)
    return _backtest_periods(db,periods,final_mark=marked,common_start=first,frequency=metadata,book_selection=book_selection,emit_period=emit_period,**options)

def dated_periods(dates,start,end,months,sessions):
    """Keep legacy month validation; explicit trades need no nominal schedule."""
    schedule_calendar.legacy_configuration(dict(start=start,end=end,months=months))
    return schedule_calendar.SessionCalendar(sessions).explicit(
        dates,start,end,checkpoint=backtest_control.checkpoint)

def backtest_dates(db, *, dates, start, end, months=12, book_selection=None, emit_period=None, **options):
    """Evaluate explicit trades, holding cash before the first trade for both sides."""
    sessions=facts.sessions(db)
    first,final,periods=dated_periods(dates,start,end,months,sessions)
    # Explicit trades end on the final mark.
    return _backtest_periods(db,periods,final_mark=True,months=months,common_start=first,book_selection=book_selection,emit_period=emit_period,**options)

def _backtest_periods(db, periods, *, final_mark, months=None, common_start=None, frequency=None, book_selection=None, emit_period=None, **options):
    """Prepare missing books atomically and apply the shared SQL screener.

    final_mark: the last period ends on a mark to date (portfolio_results).
    """
    backtest_control.checkpoint()
    started=time.perf_counter()
    periods=portfolio_results.validate_periods(periods,common_start)
    allowed={'rank_from','rank_to','pool','metric','min_cap','max_cap','min_ev','min_yield','max_multiple','sector','exchange','filters','selection_order'}
    if book_selection is None:
        if set(options)-allowed:raise ValueError('Unknown screening option.')
        screening.validate_selection(**options)
    pool=book_selection.pool if book_selection is not None else options.get('pool','legacy')
    book_facts=facts.BookFacts(db)
    def select_period(entry,exit_day):
        with diagnostics.stage('books'):
            book=prepare_period(db,entry,pool,book_facts)
        # Cached periods need an explicit read transaction. Missing sheets can
        # already belong to the caller's atomic write transaction.
        owned=not db.in_transaction
        if owned:db.execute('BEGIN')
        try:
            with diagnostics.stage('selection'):
                stocks=(screening.select(db,book=book,exit_day=exit_day,**options) if book_selection is None
                        else book_selection.select(db,book,entry,exit_day))
            for stock in stocks:
                backtest_control.checkpoint()
                start=(rules.parse_day(stock['entry']),stock.pop('price'))
                def lookup(day,forward,slack):
                    return book_facts.price(stock['symbol'],day,forward,slack)
                reason,ending=financial_books.close(start,exit_day,lookup,rules.bankrupt(stock['symbol'],entry,exit_day))
                if reason is not None:
                    raise ValueError('A selected sheet row has no valid exit: '+reason)
                end,value,status=ending
                stock.update(exit=str(end[0]),return_value=value,status=status)
            spy=financial_books.benchmark_return(book_facts.spy(entry),book_facts.spy(exit_day))
            return dict(entry=str(entry),exit=str(exit_day),holdings=stocks,spy=spy)
        finally:
            if owned:db.rollback()
    with db:
        contract = book_selection.contract if book_selection is not None else 1
        if emit_period is None:
            result=portfolio_results.evaluate(periods,select_period,common_start=common_start,
                checkpoint=backtest_control.checkpoint,contract=contract,final_mark=final_mark)
        else:
            result=portfolio_results.evaluate_into(periods,select_period,emit_period,common_start=common_start,
                checkpoint=backtest_control.checkpoint,contract=contract,final_mark=final_mark)
    result.update(frequency if frequency is not None else dict(months=months),options=options,seconds=time.perf_counter()-started)
    return result
