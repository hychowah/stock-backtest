"""Selection policy over supplied scalar lanes; no financial or formula access.

A specification names a ranking lane, explicit direction, inclusive rank range
and conditions. Numeric conditions use their supplied comparison scale. Source
adapters own unit conversion and admission. Metadata equality and inequality
are separate from numeric comparison. Missing lanes fail only active conditions
that need them, including inequality.

execute() returns input indexes and original ranks, never modified input rows.
Null candidate ranks sort first. Equal binary64 values, including signed zero,
tie by candidate rank then symbol. Rank-first never adds replacement survivors.
"""
import math
import operator
import re
import hashlib
from pathlib import Path

_LANE = re.compile(r'[A-Za-z0-9_.:-]{1,160}\Z')
MAX_CONDITIONS = 57
MAX_CANDIDATES = 8192
_LOADED_POLICY = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def policy_fingerprint():
    """Identify the loaded ordering policy; deployment restarts on source change."""
    return _LOADED_POLICY


class SelectionError(ValueError):
    """Safe static selection failure, independent of a formula language."""
    def __init__(self, path, message):
        self.code, self.path = 'INVALID_STRATEGY', path
        super().__init__(message)

    def to_dict(self):
        return dict(errors=[dict(code=self.code, path=self.path, message=str(self))])


def _fail(path, message):
    raise SelectionError(path, message)


def finite(value):
    """Return a binary64 scalar or None; booleans are not numeric evidence."""
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def validate(specification):
    """Normalize selection only; numeric comparisons preserve the supplied scale.

    Strict gt/lt serve custom thresholds. Inclusive ge/le and metadata eq are
    available for explicit compatibility adapters. No yield/default filter exists.
    """
    allowed = {'ranking', 'rank_from', 'rank_to', 'selection_order', 'conditions'}
    if type(specification) is not dict or set(specification) - allowed or 'ranking' not in specification:
        _fail('', 'A selection specification with explicit ranking is required.')
    ranking = specification['ranking']
    if (type(ranking) is not dict or set(ranking) != {'lane', 'direction'}
            or type(ranking['lane']) is not str or not _LANE.fullmatch(ranking['lane'])
            or ranking['direction'] not in ('highest', 'lowest')):
        _fail('/ranking', 'Ranking needs a lane and explicit highest or lowest direction.')
    first, last = specification.get('rank_from', 1), specification.get('rank_to', 50)
    if any(type(v) is not int for v in (first, last)) or not 1 <= first <= last <= 5000:
        _fail('/rank_from', 'Choose increasing integer ranks between 1 and 5000.')
    order = specification.get('selection_order', 'filter_first')
    if order not in ('filter_first', 'rank_first'):
        _fail('/selection_order', 'Choose filter first or rank first.')
    submitted = specification.get('conditions', [])
    if type(submitted) is not list or len(submitted) > MAX_CONDITIONS:
        _fail('/conditions', 'Choose at most 57 conditions.')
    conditions = []
    for index, item in enumerate(submitted):
        path = '/conditions/' + str(index)
        if (type(item) is not dict or set(item) != {'lane', 'op', 'value'}
                or type(item['lane']) is not str or not _LANE.fullmatch(item['lane'])
                or item['op'] not in ('lt', 'gt', 'le', 'ge', 'eq')):
            _fail(path, 'A condition needs a lane, comparison and value.')
        value = item['value']
        if item['op'] == 'eq':
            if type(value) is not str or len(value) > 256:
                _fail(path + '/value', 'Metadata equality needs a bounded string.')
        else:
            value = finite(value)
            if value is None:
                _fail(path + '/value', 'A numeric condition needs a finite binary64 value.')
        conditions.append(dict(lane=item['lane'], op=item['op'], value=value))
    return dict(ranking=dict(ranking), rank_from=first, rank_to=last,
                selection_order=order, conditions=conditions)


_COMPARE = {'lt': operator.lt, 'gt': operator.gt, 'le': operator.le, 'ge': operator.ge}


def passes(values, conditions):
    """Test active conditions; an unavailable required lane always fails."""
    for item in conditions:
        value = values.get(item['lane'])
        if item['op'] in ('eq', 'ne'):
            if type(value) is not str or (value == item['value']) != (item['op'] == 'eq'):
                return False
            continue
        value = finite(value)
        if value is None or not _COMPARE[item['op']](value, item['value']):
            return False
    return True


def steps(spec):
    """Translate a checked legacy specification without changing its comparison lanes."""
    rank = dict(kind='rank', **spec['ranking'], rank_from=spec['rank_from'], rank_to=spec['rank_to'])
    filters = [dict(kind='filter', **item) for item in spec['conditions']]
    return filters + [rank] if spec['selection_order'] == 'filter_first' else [rank] + filters


def execute(candidates, chain, checkpoint=lambda: None, *, load=None, lazy_lanes=(),
            evidence=False, count_selected=False):
    """Run checked steps over admitted lanes, loading lazy lanes for survivors.

    Consecutive filters commute: stored checks precede one lazy batch. load
    receives the needed lane names and surviving indexes. Adapters own source
    validation and population limits. count_selected retains legacy rank-first
    counts, including a chain with no filters. Evidence follows captured order.
    """
    alive = list(range(len(candidates)))
    selected = {}
    matches = 0
    number = 0
    while number < len(chain):
        checkpoint()
        step = chain[number]
        if step['kind'] == 'filter':
            end = number + 1
            while end < len(chain) and chain[end]['kind'] == 'filter':
                checkpoint()
                end += 1
            group = chain[number:end]
            stored = [item for item in group if item['lane'] not in lazy_lanes]
            lazy = [item for item in group if item['lane'] in lazy_lanes]
            if stored:
                alive = [index for index in alive if passes(candidates[index]['values'], stored)]
            if lazy and alive:
                load([item['lane'] for item in lazy], alive)
                alive = [index for index in alive if passes(candidates[index]['values'], lazy)]
            matches = len(alive)
            number = end
            continue
        if step['lane'] in lazy_lanes and alive:
            load([step['lane']], alive)
        eligible = [(index, value) for index in alive
                    if (value := finite(candidates[index]['values'].get(step['lane']))) is not None]
        highest = step['direction'] == 'highest'
        def ordering(item):
            row = candidates[item[0]]
            rank = row['candidate_rank']
            return ((-item[1] if highest else item[1]),
                    rank is not None, rank if rank is not None else 0, row['symbol'])
        eligible.sort(key=ordering)
        matches = len(eligible)
        ranked = {}
        for rank, (index, value) in enumerate(eligible[step['rank_from'] - 1:step['rank_to']], step['rank_from']):
            item = dict(index=index, rank=rank, value=value)
            if evidence:
                item['steps'] = selected.get(index, {}).get('steps', []) + [dict(step=number, rank=rank)]
            ranked[index] = item
        selected = ranked
        alive = list(selected)
        number += 1
    checkpoint()
    result = [selected[index] for index in alive]
    if evidence:
        for item in result:
            ranks = {outcome['step']: outcome for outcome in item['steps']}
            item['steps'] = [ranks[index] if step['kind'] == 'rank' else dict(step=index, passed=True)
                             for index, step in enumerate(chain)]
    return dict(selected=result, matches=len(result) if count_selected else matches)


def union(results):
    """Join execute() results in order; a row that is selected again keeps its first position.

    Each joined item has the row's index, its rank (its position in the union),
    the value of its first picking chain and its picks. A pick names its chain
    (sleeve) and keeps that chain's rank, value and steps. matches lists each chain's count.
    """
    picks = {}
    for number, result in enumerate(results):
        for item in result['selected']:
            picks.setdefault(item['index'], []).append(
                dict({key: value for key, value in item.items() if key != 'index'}, sleeve=number))
    return dict(selected=[dict(index=index, rank=rank, value=found[0]['value'], sleeves=found)
                          for rank, (index, found) in enumerate(picks.items(), 1)],
                matches=[result['matches'] for result in results])


def rank_range(options):
    """Read recorded final ranks without catalog lookup, preparation or recapture.

    A sleeve strategy holds at most the sum of its sleeves' final Rank sizes.
    """
    capture = options.get('strategy')
    if capture is None:
        rank = options
    elif capture['version'] == 3:
        ranks = [next(step for step in reversed(sleeve['steps']) if step['kind'] == 'rank') for sleeve in capture['sleeves']]
        return 1, sum(rank['rank_to'] - rank['rank_from'] + 1 for rank in ranks)
    elif capture['version'] == 2:
        rank = next(step for step in reversed(capture['steps']) if step['kind'] == 'rank')
    else:
        rank = capture['selection']
    return rank.get('rank_from', 1), rank.get('rank_to', 50)
