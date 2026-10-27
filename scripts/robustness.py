"""Reproducible date sensitivity: independent random trades in every cycle.

Each cycle is anchored to the requested lower date bound and spans the chosen
nominal rebalance interval. Every trial independently samples one cached SPY
session from each cycle (including the last partial cycle). Actual holding
intervals vary. Portfolio and paired SPY hold zero-return cash before the first
sampled trade; CAGR uses a common start/end window. Percentiles describe
correlated historical scenarios, not confidence intervals or one portfolio.
"""
from bisect import bisect_right
from calendar import monthrange
from datetime import date
import math
import random
import statistics
import time

import schedules
import book_batch


def plan(db, *, start, end, months=12, trials=24, seed=None, **options):
    if type(trials) is not int or not 1<=trials<=100:
        raise ValueError('Choose between 1 and 100 random-date trials.')
    if seed is None:seed=random.SystemRandom().getrandbits(32)
    if type(seed) is not int or not 0<=seed<=4294967295:
        raise ValueError('Choose a whole-number seed between 0 and 4294967295.')
    schedules.r._select(db,period=(-1,-1),**options)
    sessions=[date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
    window=schedules.schedule(start,end,months,sessions)
    lower=date.fromisoformat(start);final=window[-1][1]
    blocks=[];offset=0
    while True:
        absolute=lower.year*12+lower.month-1+offset
        year,month=divmod(absolute,12);month+=1
        left=date(year,month,min(lower.day,monthrange(year,month)[1]))
        if left>=final:break
        absolute+=months;year,month=divmod(absolute,12);month+=1
        right=min(date(year,month,min(lower.day,monthrange(year,month)[1])),final)
        choices=[day for day in sessions if left<=day<right]
        if choices:blocks.append(dict(start=str(left),end=str(right),sessions=[str(day) for day in choices]))
        offset+=months
    generator=random.Random(seed)
    samples=[[generator.choice(block['sessions']) for block in blocks] for _ in range(trials)]
    if not blocks:raise ValueError('No trading sessions available for random-date trials.')
    return dict(start=start,end=end,window_start=str(window[0][0]),window_end=str(final),
                months=months,seed=seed,requested=trials,options=options,
                blocks=[dict(start=b['start'],end=b['end'],available=len(b['sessions'])) for b in blocks],
                samples=samples)


def percentile(values, probability):
    """Linear interpolation between adjacent ordered observations (R type 7)."""
    if not values:return None
    ordered=sorted(values);position=(len(ordered)-1)*probability
    left=math.floor(position);right=math.ceil(position)
    return ordered[left]+(ordered[right]-ordered[left])*(position-left)


def distribution(values):
    if not values:
        return dict(n=0,mean=None,median=None,p10=None,p25=None,p75=None,p90=None,min=None,max=None,stddev=None)
    return dict(n=len(values),mean=statistics.mean(values),median=statistics.median(values),
                p10=percentile(values,.1),p25=percentile(values,.25),p75=percentile(values,.75),
                p90=percentile(values,.9),min=min(values),max=max(values),stddev=statistics.pstdev(values))


def summarize(result, number, dates):
    periods=result['periods']
    requested=result['options'].get('rank_to',50)-result['options'].get('rank_from',1)+1
    return dict(trial=number,start=result['start'],first_trade=result['first_trade'],end=result['end'],dates=dates,
                cash_days=result['cash_days'],periods=len(periods),cagr=result['cagr'],spy_cagr=result['spy_cagr'],
                excess_cagr=result['cagr']-result['spy_cagr'] if result['cagr'] is not None else None,
                total_return=result['growth']-1 if result['growth'] is not None else None,
                growth=result['growth'],spy_growth=result['spy_growth'],
                empty_periods=sum(p['names']==0 for p in periods),short_periods=sum(p['names']<requested for p in periods),seconds=result['seconds'])


def summarize_trials(configuration, rows, started):
    """Aggregate ordinary trial summaries without changing paired coverage."""
    complete=[row for row in rows if row['cagr'] is not None]
    distributions={key:distribution([row[key] for row in complete])
                   for key in ('cagr','spy_cagr','excess_cagr','total_return','growth')}
    return dict(kind='random_dates',configuration=configuration,trials=rows,
                completed=len(rows),valid=len(complete),incomplete=len(rows)-len(complete),
                distributions=distributions,beat_spy=sum(row['excess_cagr']>0 for row in complete),
                unique_schedules=len({tuple(row['dates']) for row in rows}),seconds=time.perf_counter()-started,
                note='Each trial independently samples one trading date in every rebalance block, including a final partial block. Actual holding intervals vary. All trials use the same window, with zero-return cash until their first trade for both strategy and paired SPY. Mean CAGR averages trial CAGRs; it is not the return of one portfolio. Incomplete trials remain listed and are excluded from paired statistics. Scenarios overlap; percentiles are not confidence intervals.')


def run(db, configuration, progress=None, *, workers=None, capture=None):
    """Plan shared books upfront; calculate ahead and commit each complete trial.

    Workers only read immutable prepared inputs. One parent writes books and
    applies the ordinary screener; retrying a seed reuses completed trials.
    An optional observer receives each completed trial's full result. It must
    not mutate that result. Ordinary callers still receive only the summary.
    """
    started=time.perf_counter();rows=[];execution={}
    for number,result,stats in book_batch.evaluate_trials(db,configuration,progress,workers):
        rows.append(summarize(result,number,configuration['samples'][number-1]))
        if capture is not None:capture(number,result)
        execution=dict(stats)
    result=summarize_trials(configuration,rows,started)
    result['execution']=execution
    return result
