"""Temporary saved-return selections, for one trial or a whole random batch.

Consume original holding returns in rank order. Both representations use the
same Python reduction. Batch scans keep one evidence record at a time and only
compact trial metadata between passes. No financial inputs or stores are opened.
"""
from datetime import date
import math
import time

from backtest import portfolio_results
from backtest.engines.original import robustness
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
    try:day=date.fromisoformat(value)
    except (ValueError,TypeError):raise ValueError('Stored period boundary is invalid.') from None
    if str(day)!=value:raise ValueError('Stored period boundary is invalid.')
    return day


def _selection(value):
    keys={'trial','period_from','period_to','rank_from','rank_to'}
    if (type(value) is not dict or set(value)!=keys
            or any(type(value[key]) is not int or value[key]<1 for key in keys-{'trial'})
            or not (value['trial']=='all' or type(value['trial']) is int and value['trial']>=1)
            or value['period_from']>value['period_to'] or value['rank_from']>value['rank_to']):
        raise ValueError('Choose increasing saved periods and ranks.')
    return value


def _require_trial(result):
    if type(result) is not dict or type(result.get('periods')) is not list or not result['periods']:
        raise ValueError('Complete saved holding periods are required.')
    for period in result['periods']:
        if (type(period) is not dict or type(period.get('holdings')) is not list
                or not {'entry','exit','portfolio','spy'}<=period.keys()
                or type(period.get('names')) is not int or period['names']!=len(period['holdings'])):
            raise ValueError('Complete saved holdings are required.')


def _eager_records(result):
    for number,period in enumerate(result['periods'],1):
        yield dict(type='period',number=number,value=period)
        for row in period['holdings']:yield dict(type='holding',value=row)
        yield dict(type='end_period')
    yield dict(type='end_trial',summary=result)


def eager(result, selection):
    """Explore a request-owned trial or random batch; retain no server result."""
    chosen=_selection(selection)
    if chosen['trial']=='all':
        trials=result.get('trial_results') if type(result) is dict else None
        if type(trials) is not list or not 1<=len(trials)<=100 or result.get('completed')!=len(trials):
            raise ValueError('All completed random trials are required.')
        for trial in trials:_require_trial(trial)
        def records():
            for number,trial in enumerate(trials,1):
                yield dict(type='trial',number=number)
                yield from _eager_records(trial)
        return _batch(records,{key:value for key,value in result.items() if key!='trial_results'},chosen)
    if chosen['trial']!=1:raise ValueError('Expected one completed trial.')
    _require_trial(result)
    read=lambda:_eager_records(result)
    return _reduce(read(),chosen,_metadata(read(),chosen))


def evidence(reader, selection):
    """Explore a pinned reader. Batch work takes two sequential whole scans."""
    chosen=_selection(selection)
    if chosen['trial']=='all':
        if reader.metadata.get('mode')!='random':raise ValueError('Expected a random-trial result.')
        return _batch(reader.verified_records,reader.manifest['summary'],chosen)
    if reader.metadata.get('mode')=='latest':raise ValueError('Latest screens have no holding periods.')
    read=lambda:evidence_views.records(reader,chosen['trial'])
    return _reduce(read(),chosen,_metadata(read(),chosen))


def _metadata(records, selection):
    """Keep scalar boundaries and original totals, never captured programs."""
    first,last=selection['period_from'],selection['period_to']
    total=0;entry=exit_day=None;summary=None
    for record in records:
        backtest_control.checkpoint()
        if record['type']=='period':
            total+=1
            if total==first:entry=record['value']['entry']
            if total==last:exit_day=record['value']['exit']
        elif record['type']=='end_trial':summary=record['summary']
    if last>total or summary is None:raise ValueError('Choose periods within every original trial.')
    options=summary.get('options',{})
    if type(options) is not dict or type(options.get('strategy',{})) is not dict:
        raise ValueError('Original selection settings are unavailable.')
    requested=options.get('strategy',{}).get('selection',options)
    if type(requested) is not dict:raise ValueError('Original selection settings are unavailable.')
    lower,upper=requested.get('rank_from',1),requested.get('rank_to',50)
    if not lower<=selection['rank_from']<=selection['rank_to']<=upper:
        raise ValueError('Choose ranks within every original trial.')
    start=summary.get('start',entry) if first==1 else entry
    start_day,end_day=_day(start),_day(exit_day)
    if start_day is not None and end_day is not None and start_day>=end_day:
        raise ValueError('Stored periods must have positive duration.')
    return dict(total=total,entry=entry,exit=exit_day,start=start,lower=lower,upper=upper,
        cash_days=summary.get('cash_days',0) if first==1 else 0,
        original={key:summary.get(key) for key in ('growth','spy_growth','cagr','spy_cagr')})


def _reduce(records, selection, metadata, window=None):
    first,last=selection['period_from'],selection['period_to']
    lower,upper=selection['rank_from'],selection['rank_to']
    narrowed=(lower,upper)!=(metadata['lower'],metadata['upper'])
    start,end=window or (metadata['start'],metadata['exit'])
    start_day,end_day=_day(start),_day(end)
    empty=short=0
    def returns():
        nonlocal empty,short
        source=iter(records)
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
                if count==0:
                    # Older saved empty books have null returns. Only a known
                    # empty book can become cash in this temporary summary.
                    if portfolio not in (None,0.):raise ValueError('An empty saved period has a nonzero return.')
                    portfolio=0.
                elif portfolio is None:raise ValueError('A nonempty saved period has no return.')
            empty+=count==0;short+=count<upper-lower+1
            yield portfolio,_number(period.get('spy'))
    totals=portfolio_results.reduce_returns(returns(),start=start_day,end=end_day)
    if window is None and first==1 and last==metadata['total'] and not narrowed and not empty:
        totals={key:_number(value,nullable=key in ('growth','cagr')) for key,value in metadata['original'].items()}
    if any(value is not None and not math.isfinite(value) for value in totals.values()):
        raise ValueError('Selected return exceeds the supported numerical range.')
    result=dict(start=start,end=end,period_from=first,period_to=last,
        rank_from=lower,rank_to=upper,periods=last-first+1,empty=empty,short=short,
        cash_days=metadata['cash_days'] if window is None else (_day(metadata['entry'])-start_day).days,
        total_return=totals['growth']-1 if totals['growth'] is not None else None,
        spy_total_return=totals['spy_growth']-1,**totals)
    if window is not None:result.update(first_trade=metadata['entry'],last_exit=metadata['exit'],
        final_cash_days=(end_day-_day(metadata['exit'])).days)
    return result


def _trials(records):
    """Each child borrows the shared iterator and must be consumed in order."""
    source=iter(records)
    for record in source:
        backtest_control.checkpoint()
        if record['type']!='trial':continue
        def trial():
            for child in source:
                yield child
                if child['type']=='end_trial':return
        yield record['number'],trial()


def _batch(read, original, selection):
    started=time.perf_counter()
    metadata=[(number,_metadata(records,selection)) for number,records in _trials(read())]
    if not metadata or len(metadata)!=original.get('completed'):
        raise ValueError('Complete saved random trials are required.')
    start=min(item['start'] for _,item in metadata)
    end=max(item['exit'] for _,item in metadata)
    if _day(start) is None or _day(end) is None:raise ValueError('Random trials require exact saved dates.')
    view=dict(selection,start=start,end=end,periods=selection['period_to']-selection['period_from']+1)
    unchanged=all(selection['period_from']==1 and selection['period_to']==item['total']
        and (selection['rank_from'],selection['rank_to'])==(item['lower'],item['upper']) for _,item in metadata)
    if unchanged and all(item['original']['growth'] is not None for _,item in metadata):
        return dict(original,exploration=view)
    if type(original.get('trials')) is not list or len(original['trials'])!=len(metadata):
        raise ValueError('Original random-trial summaries are required.')
    rows=[]
    for (expected,meta),(number,records),original_row in zip(metadata,_trials(read()),original['trials']):
        if expected!=number or number!=original_row.get('trial'):raise ValueError('Original trial order differs.')
        result=_reduce(records,selection,meta,(start,end))
        dates=original_row.get('dates')
        if type(dates) is not list or len(dates)!=meta['total']:
            raise ValueError('Original random trade dates are required.')
        dates=dates[selection['period_from']-1:selection['period_to']]
        row=robustness.summarize(dict(result,options=selection,seconds=0.),number,dates,
            period_counts=(result['periods'],result['empty'],result['short']))
        row.update(last_exit=result['last_exit'],final_cash_days=result['final_cash_days'])
        rows.append(row)
    result=robustness.summarize_trials(original['configuration'],rows,started)
    result['exploration']=view
    result['note']='Selected saved periods and original ranks across all trials. Empty selections hold cash at 0% until the next rebalance; SPY keeps its saved period return. Actual trade dates vary. Strategy and paired SPY hold cash before the first selected trade and after the last selected exit to share one observation window. Incomplete trials remain listed and are excluded from paired statistics. Mean CAGR averages trial CAGRs; percentiles are not confidence intervals.'
    if 'producer' in original:result['producer']=original['producer']
    return result
