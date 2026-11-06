"""Captured scalar strategy intent; no financial, execution or storage lifetime.

capture_strategy() turns editable sources into complete detached intent. Formula
identity, graph and unit policy stay with definitions; atomic labels stay with
library. Built-ins describe stored scalar lanes, never invented formulas.
require_strategy() restores original meaning without a current catalog/library.
check_options() is the separate current-capability admission operation.

The namespaced strategy-capture/1 version allocates no application result version.
A capture is at most 192 KiB. check_request() counts the complete custom request
against the existing 256 KiB queue ceiling. Neither operation changes old requests.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext
import json
import math
import re

from backtest import selection
from backtest.financial import metrics
from backtest.runtime import backtest_control
from backtest.variables import definitions, library

STRATEGY_BYTES = 192 * 1024
REQUEST_BYTES = 256 * 1024
MAX_CONDITIONS = 50
SCALAR_MODES = ('latest', 'custom', 'random')  # bounded captured-strategy execution
_ID = re.compile(r'[A-Za-z0-9_.:-]{1,160}\Z')
_SELECTION_FIELDS = {'ranking', 'conditions', 'rank_from', 'rank_to', 'selection_order'}
_BOUND_DEFAULTS = dict(min_cap=100e6, max_cap=None, min_ev=50e6, sector=None, exchange=None)
_OVERLAP = _SELECTION_FIELDS | set(_BOUND_DEFAULTS) | {
    'pool', 'metric', 'min_yield', 'max_multiple', 'filters', 'variables', 'formula',
    'definition', 'bundle', 'strategy_version'}


def _fail(code, path, message):
    raise definitions.FormulaError(code, path, message)


def failure_details(error):
    """Detach ordered safe scalar diagnostics without changing legacy errors.

    Admission responses and asynchronous status retain the same code/path/issues.
    Ordinary exceptions keep their existing text-only error contract.
    """
    if isinstance(error, definitions.FormulaError):
        issues = error.to_dict()['errors']
    else:
        return None
    return dict(code=error.code, path=error.path, errors=issues)


def _shape(value, required, optional=(), path=''):
    if type(value) is not dict or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        _fail('INVALID_STRATEGY', path, 'Fields do not match the declared strategy shape.')


def _encode(value, bound, checkpoint=backtest_control.checkpoint):
    pieces, size = [], 0
    try:
        for piece in json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                                      allow_nan=False).iterencode(value):
            checkpoint()
            size += len(piece)
            if size > bound:
                _fail('WORK_LIMIT', '', 'Complete strategy or request exceeds its encoded byte bound.')
            pieces.append(piece)
    except (TypeError, ValueError, RecursionError) as error:
        if isinstance(error, definitions.FormulaError):
            raise
        _fail('INVALID_STRATEGY', '', 'Strategy content must be finite JSON data.')
    return ''.join(pieces)


def _bound(value):
    if type(value) is not int or not 1 <= value <= STRATEGY_BYTES:
        _fail('WORK_LIMIT', '/limits/bytes', 'Strategy byte limits can only lower the fixed ceiling.')
    return value


def builtin_catalog():
    """Detached sources over prepared values, including their arithmetic scale.

    storage.scale is the decimal exponent from the saved lane to canonical units.
    Pair components remain independent; no reciprocal is calculated. Filter lanes
    keep the financial owner's display scale. Support says nothing about coverage.
    """
    result = []
    for key, item in metrics.METRICS.items():
        for component, label, display in [('yield', ' yield', 'percent'),
                                           ('multiple', ' multiple', 'multiple')]:
            result.append(dict(id='metric:' + key + ':' + component,
                label=item['label'] + label, unit='scalar', display=display,
                storage=dict(kind='metric', metric=key, component=component, scale=0)))
    dollars = {'market_cap', 'enterprise_value', 'fcf'}
    percentages = {'fcf_yield', 'profit_margin', 'operating_yield_spread_3y',
                   'roe', 'return_1y', 'return_3y', 'ebitda_yield'}
    for key, item in metrics.FILTERS.items():
        unit = 'USD' if key in dollars else 'scalar'
        display = ('usd_million' if key in dollars else
                   'percentage_points' if key == 'operating_yield_spread_3y' else
                   'percent' if key in percentages else 'multiple')
        scale = 6 if key in dollars else -2 if key in percentages else 0
        result.append(dict(id='filter:' + key, label=item['label'], unit=unit, display=display,
                           storage=dict(kind='filter', field=key, scale=scale)))
    return result


def _descriptor(value, path):
    """Validate captured lane semantics without consulting a mutable display catalog."""
    _shape(value, ('id', 'label', 'unit', 'display', 'storage'), path=path)
    if (type(value['id']) is not str or not _ID.fullmatch(value['id']) or
            type(value['label']) is not str or not 1 <= len(value['label']) <= 256):
        _fail('INVALID_STRATEGY', path, 'A captured built-in needs a bounded ID and label.')
    storage = value['storage']
    if type(storage) is not dict:
        _fail('INVALID_STRATEGY', path, 'A captured scalar storage descriptor is required.')
    if storage.get('kind') == 'metric':
        _shape(storage, ('kind', 'metric', 'component', 'scale'), path=path + '/storage')
        key = storage['metric']
        if (type(key) is not str or not _ID.fullmatch(key) or
                storage['component'] not in ('yield', 'multiple') or
                type(storage['scale']) is not int or storage['scale'] != 0 or
                value['id'] != 'metric:' + key + ':' + storage['component'] or
                value['unit'] != 'scalar' or
                value['display'] != ('percent' if storage['component'] == 'yield' else 'multiple')):
            _fail('INVALID_STRATEGY', path, 'Captured pair semantics are inconsistent.')
    elif storage.get('kind') == 'filter':
        _shape(storage, ('kind', 'field', 'scale'), path=path + '/storage')
        key, scale = storage['field'], storage['scale']
        if (type(key) is not str or not _ID.fullmatch(key) or type(scale) is not int or
                scale not in (-2, 0, 6) or value['id'] != 'filter:' + key or
                value['unit'] != ('USD' if scale == 6 else 'scalar') or
                value['display'] not in ({6: ('usd_million',), -2: ('percent', 'percentage_points'),
                                         0: ('number', 'multiple')}[scale])):
            _fail('INVALID_STRATEGY', path, 'Captured filter semantics are inconsistent.')
    else:
        _fail('INVALID_STRATEGY', path, 'Unknown captured scalar storage kind.')
    return value


def _source(value, path):
    if type(value) is not dict:
        _fail('INVALID_STRATEGY', path, 'An explicit built-in or exact formula source is required.')
    if value.get('kind') == 'builtin':
        _shape(value, ('kind', 'id'), path=path)
        if type(value['id']) is not str or not _ID.fullmatch(value['id']):
            _fail('INVALID_STRATEGY', path, 'A bounded built-in source ID is required.')
    elif value.get('kind') == 'formula':
        _shape(value, ('kind', 'variable_id', 'revision'), path=path)
        # The existing resolver/checked program owns exact identity validation.
        if any(type(value[key]) is not str for key in ('variable_id', 'revision')):
            _fail('INVALID_STRATEGY', path, 'An exact formula identity is required.')
    else:
        _fail('INVALID_STRATEGY', path, 'Unknown scalar source kind.')
    return dict(value)


def _sources(spec):
    _shape(spec, ('ranking',), _SELECTION_FIELDS - {'ranking'}, '/selection')
    _shape(spec['ranking'], ('source', 'direction'), path='/selection/ranking')
    conditions = spec.get('conditions', [])
    if type(conditions) is not list or len(conditions) > MAX_CONDITIONS:
        _fail('WORK_LIMIT', '/selection/conditions', 'Choose at most 50 scalar conditions.')
    result = [_source(spec['ranking']['source'], '/selection/ranking/source')]
    for index, item in enumerate(conditions):
        path = '/selection/conditions/' + str(index)
        _shape(item, ('source', 'op', 'threshold'),
               ('submitted_threshold', 'comparison_value', 'storage_comparison_value'), path)
        if item['op'] not in ('lt', 'gt'):
            _fail('INVALID_STRATEGY', path + '/op', 'Scalar conditions use strict less than or greater than.')
        result.append(_source(item['source'], path + '/source'))
    return result


def _root(source):
    return {key: source[key] for key in ('variable_id', 'revision')}


def _bounds(value):
    _shape(value, (), _BOUND_DEFAULTS, '/bounds')
    result = {**_BOUND_DEFAULTS, **value}
    for key in ('min_cap', 'max_cap', 'min_ev'):
        number = result[key]
        if number is not None and (selection.finite(number) is None or number < 0):
            _fail('INVALID_STRATEGY', '/bounds/' + key, 'Size bounds must be finite nonnegative values or null.')
        result[key] = None if number is None else float(number)
    if result['max_cap'] is not None and result['min_cap'] is not None and result['max_cap'] < result['min_cap']:
        _fail('INVALID_STRATEGY', '/bounds/max_cap', 'Maximum market cap must be at least the minimum.')
    for key in ('sector', 'exchange'):
        if result[key] is not None and (type(result[key]) is not str or len(result[key]) > 256):
            _fail('INVALID_STRATEGY', '/bounds/' + key, 'Metadata filters need a bounded string or null.')
    return result


def _compile(spec, variables, builtins, pool, bounds, bound, checkpoint):
    sources = _sources(spec)
    formula_roots = [_root(source) for source in sources if source['kind'] == 'formula']
    if formula_roots:
        captured = library.require_capture(library.VariableCapture(_encode(variables, library.CAPTURE_BYTES, checkpoint)),
                                           checkpoint=checkpoint)
        program = captured['program']
        if program['bundle']['roots'] != formula_roots:
            _fail('INVALID_STRATEGY', '/variables/program', 'Captured formula roots must match ordered strategy roles exactly.')
        outputs = {(item['variable_id'], item['revision']): item for item in program['definitions']}
    else:
        if variables is not None:
            _fail('INVALID_STRATEGY', '/variables', 'A strategy without formula roots has no variable capture.')
        captured, outputs = None, {}
    if type(builtins) is not list:
        _fail('INVALID_STRATEGY', '/builtins', 'Captured scalar descriptors must be an ordered list.')
    descriptors = {}
    for index, item in enumerate(builtins):
        _descriptor(item, '/builtins/' + str(index))
        if item['id'] in descriptors:
            _fail('INVALID_STRATEGY', '/builtins', 'Captured scalar descriptors must be unique.')
        descriptors[item['id']] = item
    expected = list(dict.fromkeys(source['id'] for source in sources if source['kind'] == 'builtin'))
    if list(descriptors) != expected:
        _fail('INVALID_STRATEGY', '/builtins', 'Captured scalar descriptors must match first-use source order.')
    if pool not in ('legacy', 'cached'):
        _fail('INVALID_STRATEGY', '/pool', 'Pool must be legacy or cached.')
    normalized = dict(ranking=dict(source=sources[0], direction=spec['ranking']['direction']), conditions=[])
    def output(source):
        if source['kind'] == 'builtin':
            return descriptors[source['id']]
        return outputs[source['variable_id'], source['revision']]
    for index, item in enumerate(spec.get('conditions', [])):
        checkpoint()
        descriptor = output(sources[index + 1])
        quantity = definitions.normalize_quantity(item.get('submitted_threshold', item['threshold']), descriptor['unit'])
        # Built-in saved lanes retain their original arithmetic scale. Convert
        # the canonical decimal threshold back to that scale once, without
        # rescaling saved financial values or synthesizing pair reciprocals.
        with localcontext() as context:
            context.prec = 2048
            threshold = Decimal(quantity['threshold']['value'])
            exponent = descriptor['storage']['scale'] if sources[index + 1]['kind'] == 'builtin' else 0
            storage_value = float(threshold.scaleb(-exponent))
        if not math.isfinite(storage_value) or storage_value == 0 and threshold != 0:
            _fail('INVALID_LITERAL', '/selection/conditions/' + str(index),
                  'Threshold must remain finite and non-underflowing in its stored comparison scale.')
        checked = dict(source=sources[index + 1], op=item['op'], **quantity,
                       storage_comparison_value=storage_value)
        for key in ('threshold', 'comparison_value', 'storage_comparison_value'):
            if key in item and (key != 'threshold' or 'submitted_threshold' in item) and item[key] != checked[key]:
                _fail('INVALID_STRATEGY', '/selection/conditions/' + str(index) + '/' + key,
                      'Submitted and captured threshold evidence disagree.')
        normalized['conditions'].append(checked)
    try:
        policy = selection.validate(dict(ranking=dict(lane='ranking', direction=spec['ranking']['direction']),
            conditions=[dict(lane='c' + str(i), op=item['op'], value=item['storage_comparison_value'])
                        for i, item in enumerate(normalized['conditions'])],
            **{key: spec[key] for key in ('rank_from', 'rank_to', 'selection_order') if key in spec}))
    except selection.SelectionError as error:
        _fail(error.code, error.path, str(error))
    normalized.update({key: policy[key] for key in ('rank_from', 'rank_to', 'selection_order')})
    value = dict(format='strategy-capture', version=1, selection=normalized, variables=captured,
                 builtins=builtins, pool=pool, bounds=_bounds(bounds), limits=dict(bytes=bound))
    return value


@dataclass(frozen=True)
class CapturedStrategy:
    """Complete immutable intent; decoded copies never mutate accepted content."""
    document: str

    def to_dict(self):
        return json.loads(self.document)

    def to_json(self):
        return self.document


def capture_strategy(intent, variable_store=None, *, submitted=None, labels=None,
                     limits=None, checkpoint=backtest_control.checkpoint):
    """Capture editable intent before assigning a job/queue retry identity.

    Intent has format=strategy-intent/version=1 and selection, with optional
    pool/bounds. Formula sources name exact revisions; built-ins name catalog IDs.
    A provided Store captures one snapshot. Without it, all authored dependencies
    must be submitted; no durable file is opened or initialized.
    """
    if limits is not None and (type(limits) is not dict or set(limits) - {'bytes'}):
        _fail('INVALID_STRATEGY', '/limits', 'Only a lower strategy byte bound is accepted.')
    bound = _bound((limits or {}).get('bytes', STRATEGY_BYTES))
    _encode(intent, STRATEGY_BYTES, checkpoint)
    _shape(intent, ('format', 'version', 'selection'), ('pool', 'bounds'))
    if intent['format'] != 'strategy-intent' or type(intent['version']) is not int or intent['version'] != 1:
        _fail('UNKNOWN_VERSION', '', 'Unsupported strategy intent version.')
    sources = _sources(intent['selection'])
    roots = [_root(source) for source in sources if source['kind'] == 'formula']
    current = {item['id']: item for item in builtin_catalog()}
    builtins = []
    for key in dict.fromkeys(source['id'] for source in sources if source['kind'] == 'builtin'):
        if key not in current:
            _fail('UNSUPPORTED_CAPABILITY', '/selection', 'Unknown built-in scalar source.')
        builtins.append(current[key])
    if roots:
        if variable_store is None:
            variables = library.capture_submitted(roots, submitted=submitted, labels=labels, checkpoint=checkpoint)
        else:
            variables = variable_store.capture(roots, submitted=submitted, labels=labels, checkpoint=checkpoint)
        variables = variables.to_dict()
    else:
        if submitted not in (None, []) or labels not in (None, []):
            _fail('INVALID_STRATEGY', '/variables', 'Submitted formulas need an explicit formula role.')
        variables = None
    value = _compile(intent['selection'], variables, builtins, intent.get('pool', 'legacy'),
                     intent.get('bounds', {}), bound, checkpoint)
    capture = CapturedStrategy(_encode(value, bound, checkpoint))
    require_strategy(capture, checkpoint=checkpoint)
    return capture


def require_strategy(capture, *, checkpoint=backtest_control.checkpoint):
    """Restore complete captured meaning; no current source catalog or library.

    This validates content, not current execution capability. Historical captured
    built-in labels/storage descriptors remain evidence when catalogs evolve.
    check_options performs current admission separately before input work.
    """
    checkpoint()
    if type(capture) is not CapturedStrategy or type(capture.document) is not str:
        _fail('INVALID_STRATEGY', '', 'An immutable captured strategy is required.')
    if len(capture.document) > STRATEGY_BYTES:
        _fail('WORK_LIMIT', '', 'Captured strategy exceeds its fixed byte bound.')
    try:
        value = capture.to_dict()
    except (ValueError, TypeError, RecursionError):
        _fail('INVALID_STRATEGY', '', 'Captured strategy is malformed.')
    _shape(value, ('format', 'version', 'selection', 'variables', 'builtins', 'pool', 'bounds', 'limits'))
    if value['format'] != 'strategy-capture' or type(value['version']) is not int or value['version'] != 1:
        _fail('UNKNOWN_VERSION', '', 'Unsupported strategy capture version.')
    _shape(value['limits'], ('bytes',), path='/limits')
    bound = _bound(value['limits']['bytes'])
    rebuilt = _compile(value['selection'], value['variables'], value['builtins'], value['pool'],
                       value['bounds'], bound, checkpoint)
    if _encode(rebuilt, bound, checkpoint) != capture.document:
        _fail('INVALID_STRATEGY', '', 'Strategy capture must use its complete canonical checked representation.')
    return rebuilt


def from_wire(value, *, checkpoint=backtest_control.checkpoint):
    """Restore complete JSON transport content to the strict immutable form.

    JSON has one number type. A browser writes 100000000.0 as 100000000.
    Only checked floating-point fields accept that equivalent spelling. Integer
    fields, complete derived evidence, strings, ordering and shapes stay exact.
    No catalog or library is read. One compile checks and normalizes the
    content; the capture is the canonical encoding of its result, which
    require_strategy restores to the same meaning.
    """
    document = _encode(value, STRATEGY_BYTES, checkpoint)
    _shape(value, ('format', 'version', 'selection', 'variables', 'builtins', 'pool', 'bounds', 'limits'))
    if value['format'] != 'strategy-capture' or type(value['version']) is not int or value['version'] != 1:
        _fail('UNKNOWN_VERSION', '', 'Unsupported strategy capture version.')
    _shape(value['limits'], ('bytes',), path='/limits')
    bound = _bound(value['limits']['bytes'])
    rebuilt = _compile(value['selection'], value['variables'], value['builtins'], value['pool'],
                       value['bounds'], bound, checkpoint)
    def equivalent(submitted, checked):
        checkpoint()
        if type(checked) is float:
            return (type(submitted) is int or type(submitted) is float and math.isfinite(submitted)) and submitted == checked
        if type(submitted) is not type(checked):
            return False
        if type(checked) is dict:
            return submitted.keys() == checked.keys() and all(equivalent(submitted[key], item) for key, item in checked.items())
        if type(checked) is list:
            return len(submitted) == len(checked) and all(equivalent(a, b) for a, b in zip(submitted, checked))
        return submitted == checked
    if not equivalent(value, rebuilt):
        _fail('INVALID_STRATEGY', '', 'Strategy transport must retain its complete checked content.')
    # Check the received and normalized representations against the same limit.
    if len(document) > bound:
        _fail('WORK_LIMIT', '', 'Captured strategy exceeds its lowered byte bound.')
    return CapturedStrategy(_encode(rebuilt, bound, checkpoint))


def canonical_options(options, *, checkpoint=backtest_control.checkpoint):
    """Copy accepted scalar transport to one canonical durable representation."""
    if type(options) is dict and 'strategy' in options:
        return {**options, 'strategy': from_wire(options['strategy'], checkpoint=checkpoint).to_dict()}
    return options


def check_options(options, *, checkpoint=backtest_control.checkpoint):
    """Admit custom options before readiness/input work; leave legacy options alone.

    Custom options carry one strategy projection. Duplicate selection settings are
    rejected rather than guessed. Unsupported engines fail without fallback.
    Routes, jobs and queue admission use this owner for new scalar submissions.
    Return the restored strategy: one compile (from_wire) checks its formula
    program, and preview and coverage pass the result on.
    """
    if type(options) is not dict:
        _fail('INVALID_STRATEGY', '', 'Calculation options must be an object.')
    if 'strategy' not in options:
        return None
    engine=options.get('engine','original')
    if type(engine) is not str or engine not in ('original','experimental'):
        _fail('UNSUPPORTED_CAPABILITY','/engine','Choose a supported calculation engine without changing the captured strategy.')
    if set(options)-{'strategy','engine','start','end','months','calendar','dates','trials','seed'}:
        _fail('INVALID_STRATEGY','','Unknown custom calculation option.')
    if _OVERLAP.intersection(options):
        _fail('INVALID_STRATEGY', '', 'Use one captured strategy without duplicate selection settings.')
    checked = from_wire(options['strategy'], checkpoint=checkpoint).to_dict()
    current = {item['id']: item for item in builtin_catalog()}
    for descriptor in checked['builtins']:
        expected = current.get(descriptor['id'])
        if expected is None or any(descriptor[key] != expected[key] for key in ('unit', 'display', 'storage')):
            _fail('UNSUPPORTED_CAPABILITY', '/builtins', 'Captured scalar semantics are unsupported by the current backend.')
    if checked['variables'] is not None:
        require_formula_support(engine)
    return checked


def require_formula_support(engine):
    """Check the pinned backend before readiness or financial access.

    Only Original runs formulas. Original's preflight refuses another engine
    before it calls check_options; a direct call that names one fails here.
    require_strategy has already restored the program through the language
    check, the one formula gate.
    """
    if engine != 'original':
        _fail('UNSUPPORTED_CAPABILITY', '/engine', 'Unsupported calculation engine.')


def preview_engine(engine='original'):
    """Sample preview explicitly uses Original, independent of run selection."""
    if engine!='original':
        _fail('UNSUPPORTED_CAPABILITY','/engine','Sample preview supports Original execution only.')
    return engine


def require_mode(mode):
    """Refuse the removed January mode before any option check.

    A stale browser tab or an API client may still send it. The request is
    refused, never converted to a dated schedule.
    """
    if mode == 'january':
        _fail('UNSUPPORTED_CAPABILITY', '/mode', 'January backtests were removed. '
              'Run a custom schedule every 12 months from 1 January instead.')
    return mode


def execution_options(mode,options,*,planned=None,checkpoint=backtest_control.checkpoint):
    """Normalize one scalar mode before opening financial resources."""
    options=canonical_options(options,checkpoint=checkpoint)
    if check_options(options,checkpoint=checkpoint) is None:
        raise ValueError('Bounded scalar execution requires a captured strategy.')
    if mode not in SCALAR_MODES:raise ValueError('Unsupported scalar mode.')
    allowed={'strategy','engine'}|(set() if mode=='latest' else
        {'start','end','months','calendar','dates'} if mode=='custom' else {'start','end','months','calendar','trials','seed'})
    if set(options)-allowed:raise ValueError('Unknown option for the scalar execution mode.')
    if planned is not None:
        if mode!='random':raise ValueError('A recorded plan requires random mode.')
        validate_recorded({key:value for key,value in options.items() if key!='engine'},planned)
    return options


def check_request(request, *, checkpoint=backtest_control.checkpoint):
    """Count every custom submission byte, including wrapper/display metadata.

    The limit matches existing queue transport/specification limits. Legacy
    requests are untouched. Call this on the actual complete request before
    assigning/publishing submission identity; never truncate or drop evidence.
    """
    if type(request) is not dict or type(request.get('options')) is not dict or 'strategy' not in request['options']:
        return None
    checked = check_options(request['options'], checkpoint=checkpoint)
    _encode(request, REQUEST_BYTES, checkpoint)
    return checked


def submission_equal(left, right):
    """Exact canonical payload equality, including original descriptive evidence."""
    return _encode(left, REQUEST_BYTES) == _encode(right, REQUEST_BYTES)


def calculation_projection(capture):
    """Comparable selection meaning; not a submission receipt or a new hash.

    Names, provenance, submitted threshold spelling and lowerable resource limits
    do not alter selected values. Formula/display revisions and exact root order
    do. The caller compares other date/seed/engine options through their owners.
    """
    value = require_strategy(capture)
    if value['variables'] is not None:
        value['variables'] = value['variables']['program']['bundle']
    for descriptor in value['builtins']:
        descriptor.pop('label')
    for condition in value['selection']['conditions']:
        condition.pop('submitted_threshold')
    value.pop('limits')
    return value


def calculation_equal(left, right):
    return definitions.canonical(calculation_projection(left)) == definitions.canonical(calculation_projection(right))


def options_calculation_equal(left, right):
    """Waiting-plan equality; keep complete submitted payload equality separate."""
    a, b = dict(left), dict(right)
    if 'strategy' in a or 'strategy' in b:
        if 'strategy' not in a or 'strategy' not in b or not calculation_equal(
                from_wire(a.pop('strategy')), from_wire(b.pop('strategy'))):return False
    return {'engine':'original','selection_order':'filter_first',**a} == {'engine':'original','selection_order':'filter_first',**b}


def validate_recorded(options, planned):
    """Compare detached meaning while preserving the original recorded plan bytes."""
    from backtest import calendar_requests
    submitted = {key:value for key,value in options.items() if key!='engine'}
    if 'strategy' in submitted:
        old = planned.get('options',{}).get('strategy') if type(planned) is dict else None
        if old is None or not calculation_equal(from_wire(submitted['strategy']), from_wire(old)):
            _fail('INVALID_STRATEGY','/planned','Captured strategy differs from the recorded plan.')
        submitted['strategy'] = old
    calendar_requests.validate_submitted(submitted,planned)
