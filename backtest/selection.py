"""Selection policy over supplied scalar lanes; no financial or formula access.

A specification names a ranking lane, explicit direction, inclusive rank range
and conditions. Numeric conditions use their supplied comparison scale. Source
adapters own unit conversion and admission. Metadata equality is separate from
numeric comparison. Missing lanes fail only active conditions that need them.

select() returns input indexes and original ranks, never modified input rows.
Null candidate ranks sort first. Equal binary64 values, including signed zero,
tie by candidate rank then symbol. Rank-first never adds replacement survivors.
"""
import math
import re
import hashlib
from pathlib import Path

_LANE = re.compile(r'[A-Za-z0-9_.:-]{1,160}\Z')
MAX_CONDITIONS = 50
MAX_CANDIDATES = 8192
_LOADED_POLICY = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def policy_fingerprint():
    """Bind this loaded ordering policy and reject later source edits."""
    current = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if current != _LOADED_POLICY:
        _fail('', 'Loaded selection policy no longer matches its source.')
    return current


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
        _fail('/conditions', 'Choose at most 50 conditions.')
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


def passes(values, conditions, checkpoint=lambda: None):
    """Test active conditions; an unavailable required lane always fails."""
    for item in conditions:
        checkpoint()
        value = values.get(item['lane'])
        op, threshold = item['op'], item['value']
        if op == 'eq':
            if type(value) is not str or value != threshold:
                return False
            continue
        value = finite(value)
        if value is None or not {'lt': lambda: value < threshold,
                'gt': lambda: value > threshold, 'le': lambda: value <= threshold,
                'ge': lambda: value >= threshold}[op]():
            return False
    return True


def select(candidates, specification, checkpoint=lambda: None):
    """Select one supplied scope; adapters establish its admitted population.

    Candidate objects need symbol, candidate_rank and values. Extra fields are
    ignored. Output indexes address the original sequence. The count matches
    legacy browser semantics: filtered candidates or rank-first survivors.
    """
    spec = validate(specification)
    if type(candidates) is not list or len(candidates) > MAX_CANDIDATES:
        _fail('/candidates', 'The supplied candidate scope exceeds its bound.')
    eligible, symbols = [], set()
    for index, row in enumerate(candidates):
        checkpoint()
        if (type(row) is not dict or not {'symbol', 'candidate_rank', 'values'} <= set(row)
                or type(row['symbol']) is not str or not 1 <= len(row['symbol']) <= 128
                or type(row['values']) is not dict
                or row['candidate_rank'] is not None and
                    (type(row['candidate_rank']) is not int or row['candidate_rank'] < 1)):
            _fail('/candidates/' + str(index), 'A candidate needs a symbol, original rank and value lanes.')
        if row['symbol'] in symbols:
            _fail('/candidates/' + str(index), 'A company can occur only once in a scope.')
        symbols.add(row['symbol'])
        value = finite(row['values'].get(spec['ranking']['lane']))
        if value is not None:
            eligible.append((index, value))
    if spec['selection_order'] == 'filter_first':
        eligible = [item for item in eligible if passes(candidates[item[0]]['values'], spec['conditions'], checkpoint)]
    def ordering(item):
        row = candidates[item[0]]
        rank = row['candidate_rank']
        return ((-item[1] if spec['ranking']['direction'] == 'highest' else item[1]),
                rank is not None, rank if rank is not None else 0, row['symbol'])
    eligible.sort(key=ordering)
    selected = []
    for rank, (index, value) in enumerate(eligible, 1):
        checkpoint()
        if spec['rank_from'] <= rank <= spec['rank_to']:
            if spec['selection_order'] == 'filter_first' or passes(candidates[index]['values'], spec['conditions'], checkpoint):
                selected.append(dict(index=index, rank=rank, value=value))
    checkpoint()
    return dict(selected=selected, matches=len(selected) if spec['selection_order'] == 'rank_first' else len(eligible))
