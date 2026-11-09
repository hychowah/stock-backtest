"""Sector composition of original saved holdings, without financial inputs.

One traversal retains trial/sector statistics. A selected trial also returns
its compact period counts. Means weight rebalances equally within a trial,
then complete trials equally; empty books contribute cash, not a sector.
"""
from collections import Counter
import math

from backtest.application import evidence_views
from backtest.runtime import backtest_control


def _name(row):
    return row.get('sector') or None


def _order(name):
    return (name is None, name or '')


def _summarize(records, trial):
    if trial != 'all':
        evidence_views.integer(trial, 1)
    trials = []
    history = []
    active = False
    for record in records:
        backtest_control.checkpoint()
        kind = record['type']
        if kind == 'trial':
            number = record['number']
            active = trial == 'all' or number == trial
            totals, minimum, maximum, present = Counter(), {}, {}, Counter()
            periods = empty = 0
        elif active and kind == 'period':
            period = record['value']
            period_number = record['number']
            counts = Counter()
        elif active and kind == 'holding':
            counts[_name(record['value'])] += 1
        elif active and kind == 'end_period':
            names = period['names']
            weights = {name: count / names for name, count in counts.items()}
            for name in totals.keys() | weights.keys():
                weight = weights.get(name, 0.)
                minimum[name] = min(minimum.get(name, 0. if periods else weight), weight)
                maximum[name] = max(maximum.get(name, 0.), weight)
                totals[name] += weight
                present[name] += weight > 0
            periods += 1
            empty += names == 0
            if trial != 'all':
                history.append(dict(number=period_number, entry=period['entry'], exit=period['exit'],
                    names=names, sectors=[dict(name=name, count=counts[name], weight=weights[name])
                        for name in sorted(counts, key=_order)]))
        elif active and kind == 'end_trial':
            if not periods:
                raise ValueError('Complete saved holding periods are required.')
            summary = record['summary']
            complete = all(type(summary.get(key)) in (int, float) and math.isfinite(summary[key])
                for key in ('cagr', 'spy_cagr'))
            trials.append(dict(number=number, complete=complete, periods=periods, empty=empty,
                cash=empty / periods,
                sectors=[dict(name=name, mean=totals[name] / periods, minimum=minimum[name],
                    maximum=maximum[name], present=present[name]) for name in sorted(totals, key=_order)]))
            if trial != 'all':
                return dict(trials=trials, periods=history)
            active = False
    if trial != 'all' or not trials:
        raise ValueError('Complete stored trial details are unavailable.')
    complete = [row for row in trials if row['complete']]
    names = sorted({sector['name'] for row in complete for sector in row['sectors']}, key=_order)
    values = [{sector['name']: sector['mean'] for sector in row['sectors']} for row in complete]
    sectors = []
    for name in names:
        weights = [value.get(name, 0.) for value in values]
        sectors.append(dict(name=name, mean=sum(weights) / len(weights),
            minimum=min(weights), maximum=max(weights),
            leading=sum(value.get(name, 0.) > 0 and value[name] == max(value.values()) for value in values)))
    return dict(trials=trials, sectors=sectors, complete=len(complete), incomplete=len(trials)-len(complete),
        cash=sum(row['cash'] for row in complete) / len(complete) if complete else None)


def evidence(reader, trial='all'):
    """Read pinned, completely validated evidence with its usual freshness proof."""
    if reader.metadata.get('mode') == 'latest':
        raise ValueError('Latest screens have no holding periods.')
    return _summarize(reader.verified_records(), trial)


def eager(result, trial='all'):
    """Adapt existing inline records at the HTTP boundary; never retain them."""
    if type(result) is not dict:
        raise ValueError('Complete stored trial details are unavailable.')
    originals = result.get('trial_results') if 'trial_results' in result else [result]
    if (type(originals) is not list or not 1 <= len(originals) <= 100
            or 'trial_results' in result and result.get('completed') != len(originals)):
        raise ValueError('Complete stored trial details are unavailable.')
    def records():
        for number, original in enumerate(originals, 1):
            if type(original) is not dict or type(original.get('periods')) is not list:
                raise ValueError('Complete stored trial details are unavailable.')
            yield dict(type='trial', number=number)
            for index, period in enumerate(original['periods'], 1):
                if (type(period) is not dict or type(period.get('holdings')) is not list or type(period.get('names')) is not int
                        or period['names'] != len(period['holdings'])):
                    raise ValueError('Complete saved holdings are required.')
                yield dict(type='period', number=index, value=period)
                for row in period['holdings']:
                    if type(row) is not dict or row.get('sector') is not None and type(row['sector']) is not str:
                        raise ValueError('Invalid recorded sector.')
                    yield dict(type='holding', value=row)
                yield dict(type='end_period')
            yield dict(type='end_trial', summary=original)
    return _summarize(records(), trial)


def holdings(reader, trial, period, sector, cursor=0):
    """Page one recorded sector, preserving ranks, weights and original values."""
    if sector is not None and type(sector) is not str:
        raise ValueError('Invalid recorded sector.')
    return evidence_views.page((row for row in evidence_views.holdings(reader, trial, period)
        if _name(row) == sector), cursor)
