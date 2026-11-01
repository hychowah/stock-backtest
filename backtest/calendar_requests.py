"""Shared calendar requests and recorded evidence; no I/O or financial rules.

A request uses one calendar representation. Decoding preserves the submitted
representation and separates calendar settings from stock selection.
A recorded plan is execution evidence. Validation never replaces its samples
with newly generated dates.
"""
from copy import deepcopy
import json
import random

from backtest import calendar as c


def decode_request(options):
    value=deepcopy(options)
    if 'calendar' in value:
        if set(value)&{'start','end','months','interval','version'}:
            raise ValueError('Use one calendar representation.')
        configuration=c.decode_configuration(value.pop('calendar'))
        metadata={'calendar':configuration.to_dict()}
    else:
        configuration=c.legacy_configuration({k:value.pop(k) for k in ('start','end','months') if k in value})
        metadata={'months':configuration.interval.count}
    return configuration,value,metadata


def metadata(value):
    """Validate result/plan frequency without confusing resolved/requested dates."""
    if 'calendar' in value:
        if 'months' in value:raise ValueError('Use one calendar representation.')
        return {'calendar':c.decode_configuration(value['calendar']).to_dict()}
    months=value.get('months')
    if type(months) is not int or months not in c.LEGACY_MONTHS:
        raise ValueError('Invalid legacy month interval.')
    return {'months':months}


def request_fields(plan):
    return ({'calendar':deepcopy(plan['calendar'])} if 'calendar' in plan else
            {k:plan[k] for k in ('start','end','months')})


def plan(sessions, options, *, checkpoint=None):
    configuration,selection,meta=decode_request(options)
    trials=selection.pop('trials',24);seed=selection.pop('seed',None)
    if seed is None:seed=random.SystemRandom().getrandbits(32)
    sampled=c.SessionCalendar(sessions).sample(configuration,trials,seed,checkpoint=checkpoint)
    result=dict(window_start=sampled['window_start'],window_end=sampled['window_end'],seed=seed,
                requested=trials,options=selection,blocks=sampled['blocks'],samples=sampled['samples'])
    result.update(meta)
    if 'calendar' not in meta:result.update(start=configuration.start,end=configuration.end)
    return result


def validate_plan(sessions, recorded, *, checkpoint=None):
    common={'window_start','window_end','seed','requested','options','blocks','samples'}
    if type(recorded) is not dict or set(recorded)!=common|({'calendar'} if 'calendar' in recorded else {'start','end','months'}):
        raise ValueError('Incomplete recorded random configuration.')
    result=deepcopy(recorded)
    json.dumps(result,allow_nan=False)
    configuration,_,_=decode_request(request_fields(result))
    calendar=c.SessionCalendar(sessions)
    first,final=calendar.window(configuration.start,configuration.end)
    if (str(first),str(final))!=(result['window_start'],result['window_end']):
        raise ValueError('Recorded random window is unavailable in current inputs.')
    if (type(result['requested']) is not int or not 1<=result['requested']<=100
            or type(result['seed']) is not int or not 0<=result['seed']<=4294967295
            or not isinstance(result['options'],dict) or not isinstance(result['blocks'],list)
            or not isinstance(result['samples'],list) or len(result['samples'])!=result['requested']):
        raise ValueError('Invalid recorded random plan.')
    # Validate nominal block evidence without resampling recorded trades.
    blocks=[]
    for left,right in calendar._bounds(configuration,checkpoint):
        available=sum(left<=day<right for day in calendar.sessions)
        if available:blocks.append(dict(start=str(left),end=str(right),available=available))
    if result['blocks']!=blocks:raise ValueError('Recorded random blocks differ from saved sessions.')
    for dates in result['samples']:
        calendar.explicit(dates,configuration.start,configuration.end,checkpoint=checkpoint)
        if len(dates)!=len(blocks) or any(not block['start']<=day<block['end'] for day,block in zip(dates,blocks)):
            raise ValueError('Recorded trades differ from their nominal blocks.')
    return result


def periods(sessions, options, *, checkpoint=None):
    configuration,selection,meta=decode_request(options)
    calendar=c.SessionCalendar(sessions)
    if 'dates' in selection:
        first,_,pairs=calendar.explicit(selection.pop('dates'),configuration.start,configuration.end,checkpoint=checkpoint)
    else:
        first=None;pairs=calendar.fixed(configuration,checkpoint=checkpoint)
    return pairs,first,selection,meta


def validate_submitted(options, plan):
    """Compare submitted intent with immutable evidence, without resampling.

    Omitted legacy selection order means filter-first. Engine metadata is owned
    by the application and must be removed before entering financial plans.
    """
    if (not isinstance(plan, dict) or not isinstance(plan.get('options'), dict)
            or not {'requested', 'seed'}.issubset(plan)
            or not ({'calendar'} if 'calendar' in plan else {'start','end','months'}).issubset(plan)):
        raise ValueError('Invalid recorded random plan.')
    submitted = {'selection_order':'filter_first', **plan['options']}
    submitted.update(request_fields(plan), trials=plan['requested'], seed=plan['seed'])
    for key, value in {'selection_order':'filter_first', **options}.items():
        if key not in submitted or value != submitted[key]:
            raise ValueError('Submitted settings differ from the recorded random plan.')
