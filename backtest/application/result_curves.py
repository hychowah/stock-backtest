"""Asset curves of original saved periods, without financial inputs.

A period saved with a curve holds the strategy's and its paired SPY's return to
date on each market session (portfolio_results). One traversal chains a trial's
periods into the growth of 1 from its start: a period compounds on the value
at its entry, in the order and with the expression of the saved total growth,
so the last value equals it. Both sides hold cash at 1 before the first trade.

A result saved before periods carried curves has none: available is False.
"""
import statistics

from backtest.runtime import backtest_control


def _trials(records, trial):
    """[(days, strategy, spy)] of the requested trials, or None when a period has no curve."""
    found = []
    active = False
    for record in records:
        backtest_control.checkpoint()
        kind = record['type']
        if kind == 'trial':
            active = trial == 'all' or record['number'] == trial
            days, strategy, spy = [], [], []
            growth = paired_growth = 1.
        elif active and kind == 'period':
            period = record['value']
            if 'curve' not in period:
                return None
            if not days:
                days.append(period['entry']); strategy.append(1.); spy.append(1.)
            for day, portfolio, paired in period['curve']:
                days.append(day); strategy.append(growth*(1+portfolio)); spy.append(paired_growth*(1+paired))
            growth, paired_growth = strategy[-1], spy[-1]
        elif active and kind == 'end_trial':
            start = record['summary']['start']
            if start < days[0]:
                days.insert(0, start); strategy.insert(0, 1.); spy.insert(0, 1.)
            found.append((days, strategy, spy))
            if trial != 'all':
                return found
            active = False
    if trial != 'all' or not found:
        raise ValueError('Stored trial not found.')
    return found


def _on(grid, days, values):
    """values on every day of grid: the last value on or before the day, and 1 before the first."""
    result = []
    index, value = 0, 1.
    for day in grid:
        while index < len(days) and days[index] <= day:
            value = values[index]
            index += 1
        result.append(value)
    return result


def evidence(reader, trial='all'):
    """One trial's curve, or the spread of every trial's curve on each day.

    A trial returns days, strategy and spy: the growth of 1 on each day. 'all'
    returns, on every day of any trial, the median, lowest and highest
    strategy value across the trials and the median of their paired SPY
    values. A trial holds its last value on a day it does not record.
    """
    if trial != 'all' and (type(trial) is not int or trial < 1):
        raise ValueError('Invalid evidence selection.')
    if reader.metadata.get('mode') == 'latest':
        raise ValueError('Latest screens have no holding periods.')
    found = _trials(reader.verified_records(), trial)
    if found is None:
        return dict(available=False)
    if trial != 'all':
        days, strategy, spy = found[0]
        return dict(available=True, days=days, strategy=strategy, spy=spy)
    grid = sorted(set().union(*(days for days, _, _ in found)))
    strategy = list(zip(*(_on(grid, days, values) for days, values, _ in found)))
    spy = zip(*(_on(grid, days, values) for days, _, values in found))
    return dict(available=True, trials=len(found), days=grid, median=[statistics.median(day) for day in strategy],
                lowest=[min(day) for day in strategy], highest=[max(day) for day in strategy],
                spy=[statistics.median(day) for day in spy])
