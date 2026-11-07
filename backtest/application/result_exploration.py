"""Return summaries for a temporary selection of completed result evidence.

Read only saved period/holding returns. Preserve original ranks and values;
never acquire financial inputs, evaluate a strategy or construct a new artifact.
Eager requests own one decoded trial. Evidence requests borrow a pinned reader
and scan bounded records. Both use the original Python financial reducer.
"""
from datetime import date
import math

from backtest import portfolio_results
from backtest.runtime import backtest_control
from . import evidence_views


def _number(value, nullable=False):
    if nullable and value is None:return None
    if type(value) not in (int,float) or not math.isfinite(value) or value < -1:
        raise ValueError('Stored return is unavailable or invalid.')
    return value


def _day(value):
    # Existing January records have bare book-year labels at inner boundaries.
    if isinstance(value,str) and len(value)==4 and value.isdigit():return None
    try:
        day=date.fromisoformat(value)
    except (ValueError,TypeError):
        raise ValueError('Stored period boundary is invalid.') from None
    if str(day)!=value:raise ValueError('Stored period boundary is invalid.')
    return day


def _selection(value):
    keys={'trial','period_from','period_to','rank_from','rank_to'}
    if (type(value) is not dict or set(value)!=keys
            or any(type(item) is not int or item<1 for item in value.values())
            or value['period_from']>value['period_to'] or value['rank_from']>value['rank_to']):
        raise ValueError('Choose increasing saved periods and ranks.')
    return value


def eager(result, selection):
    """Explore one browser-held completed trial, without keeping its request."""
    chosen=_selection(selection)
    if chosen['trial']!=1:raise ValueError('Expected one completed trial.')
    if type(result) is not dict or type(result.get('periods')) is not list or not result['periods']:
        raise ValueError('Complete saved holding periods are required.')
    for period in result['periods']:
        if (type(period) is not dict or type(period.get('holdings')) is not list
                or type(period.get('names')) is not int or period['names']!=len(period['holdings'])):
            raise ValueError('Complete saved holdings are required.')
    def records():
        for number,period in enumerate(result['periods'],1):
            yield dict(type='period',number=number,value=period)
            for row in period['holdings']:yield dict(type='holding',value=row)
            yield dict(type='end_period')
        yield dict(type='end_trial',summary=result)
    return _explore(records,chosen)


def evidence(reader, selection):
    """Explore a borrowed immutable evidence reader using sequential scans."""
    chosen=_selection(selection)
    if reader.metadata.get('mode')=='latest':raise ValueError('Latest screens have no holding periods.')
    return _explore(lambda:evidence_views.records(reader,chosen['trial']),chosen)


def _explore(records, selection):
    first,last=selection['period_from'],selection['period_to']
    lower,upper=selection['rank_from'],selection['rank_to']
    total=0;entry=exit_day=None;summary=None
    for record in records():
        backtest_control.checkpoint()
        if record['type']=='period':
            total+=1
            if total==first:entry=record['value']['entry']
            if total==last:exit_day=record['value']['exit']
        elif record['type']=='end_trial':summary=record['summary']
    if last>total or summary is None:raise ValueError('Choose periods within the original result.')
    options=summary.get('options',{})
    if type(options) is not dict or type(options.get('strategy',{})) is not dict:
        raise ValueError('Original selection settings are unavailable.')
    requested=options.get('strategy',{}).get('selection',options)
    if type(requested) is not dict:raise ValueError('Original selection settings are unavailable.')
    original_from,original_to=requested.get('rank_from',1),requested.get('rank_to',50)
    if not original_from<=lower<=upper<=original_to:
        raise ValueError('Choose ranks within the original result.')
    narrowed=(lower,upper)!=(original_from,original_to)
    start=summary.get('start',entry) if first==1 else entry
    start_day,end_day=_day(start),_day(exit_day)
    if start_day is not None and end_day is not None and start_day>=end_day:
        raise ValueError('Stored periods must have positive duration.')
    empty=short=0
    def returns():
        nonlocal empty,short
        source=iter(records())
        for record in source:
            backtest_control.checkpoint()
            if record['type']!='period' or not first<=record['number']<=last:continue
            period=record['value'];count=0
            if narrowed:
                def values():
                    nonlocal count
                    previous=0
                    for child in source:
                        backtest_control.checkpoint()
                        if child['type']=='end_period':return
                        if child['type']!='holding':continue
                        row=child['value']
                        if type(row) is not dict:raise ValueError('Original holding ranks are unavailable.')
                        rank=row.get('rank')
                        if type(rank) is not int or rank<=previous:
                            raise ValueError('Original holding ranks are unavailable or unordered.')
                        previous=rank
                        if lower<=rank<=upper:
                            count+=1
                            yield _number(row.get('return_value'))
                portfolio=portfolio_results.mean_return(values())
            else:
                count=period['names'];portfolio=_number(period.get('portfolio'),nullable=True)
                if (count==0)!=(portfolio is None):raise ValueError('Stored period return differs from its holding count.')
            empty+=count==0;short+=count<upper-lower+1
            yield portfolio,_number(period.get('spy'))
    totals=portfolio_results.reduce_returns(returns(),start=start_day,end=end_day)
    if first==1 and last==total and not narrowed:
        # Recorded summaries can have older stored rounding. Never recompute them.
        totals={key:_number(summary.get(key),nullable=key in ('growth','cagr'))
                for key in ('growth','spy_growth','cagr','spy_cagr')}
    if any(value is not None and not math.isfinite(value) for value in totals.values()):
        raise ValueError('Selected return exceeds the supported numerical range.')
    return dict(start=start,end=exit_day,period_from=first,period_to=last,
        rank_from=lower,rank_to=upper,periods=last-first+1,empty=empty,short=short,
        cash_days=summary.get('cash_days',0) if first==1 else 0,
        total_return=totals['growth']-1 if totals['growth'] is not None else None,
        spy_total_return=totals['spy_growth']-1,**totals)
