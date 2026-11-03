"""Bounded point-in-time observations, independent of formula evaluation.

Plans describe observations, never executable expressions. An admitted input
view owns source facts and root membership. This module owns dated contexts,
annual alignment, units and detached evidence. Keep the attachment's existing
outer ownership until observe() returns and borrowed views have closed.
"""
import calendar
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
from types import MappingProxyType

from backtest.variables import parameters
from backtest.financial import rules
from backtest.inputs.observation_inputs import encoded

VERSION = 1
CEILINGS = MappingProxyType(dict(contexts=256, requests=1024, members=10240,
                                 rows=2000000, bytes=16 * 1024 * 1024))
_CATALOG = {
    'annual.revenue': ('USD', 'Selected annual revenue', 'revenue'),
    'annual.operating_income': ('USD', 'Selected annual operating income', 'operatingIncome'),
    'annual.operating_margin': ('scalar', 'Operating income / positive revenue', None),
    'market.enterprise_value': ('USD', 'Existing dated enterprise value', None),
}
_ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
_SYMBOL = re.compile(r'[A-Za-z0-9^._-]{1,64}\Z')
_LOADED_POLICY = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class ObservationError(ValueError):
    """Safe deterministic validation failure, with a code and JSON-style path."""
    def __init__(self, code, path, message):
        self.code, self.path = code, path
        super().__init__(message)


@dataclass(frozen=True)
class ObservationPlan:
    """Immutable normalized request bytes. observe() revalidates this content."""
    document: str

    def to_dict(self):
        return json.loads(self.document)


@dataclass(frozen=True)
class ObservationBlock:
    """Detached JSON evidence; decoding never touches an attachment or library."""
    document: str

    def to_dict(self):
        return json.loads(self.document)

    def to_json(self):
        return self.document


def catalog():
    """Exactly the four admitted capabilities; support does not prove coverage."""
    return [dict(id=key, unit=value[0], description=value[1],
                 counts=dict(minimum=1, maximum=10 if key.startswith('annual.') else 1),
                 contexts=['root', 'at', 'lookback']) for key, value in _CATALOG.items()]


def _fail(code, path, message):
    raise ObservationError(code, path, message)


def _shape(value, keys, path):
    if not isinstance(value, dict) or set(value) != set(keys):
        _fail('INVALID_SHAPE', path, 'Observation fields do not match the declared shape.')


def _identifier(value, path):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail('INVALID_SHAPE', path, 'Observation identifier is invalid.')


def _day(value, path):
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        _fail('INVALID_DATE', path, 'An ISO calendar date is required.')
    if str(parsed) != value:
        _fail('INVALID_DATE', path, 'An ISO calendar date is required.')
    return parsed


def _integer(value, minimum, maximum, path):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail('INVALID_SHAPE', path, 'Observation count is outside its declared bounds.')


def _subtract(day, months):
    total = day.year * 12 + day.month - 1 - months
    year, month = divmod(total, 12)
    if year < 1:
        _fail('INVALID_DATE', '/contexts', 'Lookback exceeds the supported calendar.')
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def _compile(requests, contexts, limits):
    if not isinstance(limits, dict) or set(limits) - set(CEILINGS):
        _fail('INVALID_SHAPE', '/limits', 'Unknown observation limit.')
    maximum = dict(CEILINGS)
    for key, value in limits.items():
        _integer(value, 1, CEILINGS[key], '/limits/' + key)
        maximum[key] = value
    for key, values in (('contexts', contexts), ('requests', requests)):
        if not isinstance(values, list):
            _fail('INVALID_SHAPE', '/' + key, 'An ordered list is required.')
        if len(values) > maximum[key]:
            _fail('WORK_LIMIT', '/' + key, 'Observation plan exceeds its count bound.')
    nodes = {}
    for index, item in enumerate(contexts):
        path = '/contexts/' + str(index)
        kind = item.get('kind') if isinstance(item, dict) else None
        fields = {'root': ('id', 'kind', 'symbol', 'pool', 'mode', 'date'),
                  'at': ('id', 'kind', 'parent', 'date'),
                  'lookback': ('id', 'kind', 'parent', 'months')}
        if not isinstance(kind, str) or kind not in fields:
            _fail('UNSUPPORTED_OPERATION', path, 'Unsupported observation context.')
        _shape(item, fields[kind], path)
        _identifier(item['id'], path + '/id')
        if item['id'] in nodes:
            _fail('INVALID_SHAPE', path, 'Duplicate observation context.')
        if kind == 'root':
            if (not isinstance(item['symbol'], str) or not _SYMBOL.fullmatch(item['symbol'])
                    or item['pool'] not in ('cached', 'legacy') or item['mode'] not in ('historical', 'latest')):
                _fail('INVALID_SHAPE', path, 'Invalid root company, pool or mode.')
            _day(item['date'], path + '/date')
        else:
            _identifier(item['parent'], path + '/parent')
            if kind == 'at':
                _day(item['date'], path + '/date')
            else:
                _integer(item['months'], 1, 120, path + '/months')
        nodes[item['id']] = item
    resolved, visiting, depths = {}, set(), {}
    def resolve(identity, depth=1):
        if depth > 32:
            _fail('WORK_LIMIT', '/contexts', 'Observation context depth exceeds its bound.')
        if identity in visiting:
            _fail('DEPENDENCY_CYCLE', '/contexts', 'Observation context cycle.')
        if identity in resolved:
            return resolved[identity]
        if identity not in nodes:
            _fail('MISSING_REFERENCE', '/contexts', 'Observation parent is absent.')
        item = nodes[identity]
        visiting.add(identity)
        if item['kind'] == 'root':
            value = dict(id=identity, root=identity, date=item['date'])
            depths[identity] = 1
        else:
            parent = resolve(item['parent'], depth + 1)
            depths[identity] = depths[item['parent']] + 1
            if depths[identity] > 32:
                _fail('WORK_LIMIT', '/contexts', 'Observation context depth exceeds its bound.')
            parent_day = _day(parent['date'], '/contexts')
            day = _day(item['date'], '/contexts') if item['kind'] == 'at' else _subtract(parent_day, item['months'])
            if day > parent_day:
                _fail('FUTURE_DATE', '/contexts', 'An observation date exceeds its parent date.')
            value = dict(id=identity, root=parent['root'], date=str(day))
        visiting.remove(identity)
        resolved[identity] = value
        return value
    for identity in nodes:
        resolve(identity)
    identifiers, members = set(), 0
    for index, item in enumerate(requests):
        path = '/requests/' + str(index)
        _shape(item, ('id', 'parameter', 'context', 'count'), path)
        _identifier(item['id'], path + '/id')
        if item['id'] in identifiers:
            _fail('INVALID_SHAPE', path, 'Duplicate observation request.')
        identifiers.add(item['id'])
        if not isinstance(item['parameter'], str) or item['parameter'] not in _CATALOG:
            if type(item['parameter']) is str and any(value['id'] == item['parameter']
                    for value in parameters.catalog(parameters.V2)):
                _fail('UNSUPPORTED_CAPABILITY', path + '/parameter', 'Recognized parameter has no implemented observation.')
            _fail('UNKNOWN_PARAMETER', path + '/parameter', 'Unsupported observation parameter.')
        _identifier(item['context'], path + '/context')
        if item['context'] not in resolved:
            _fail('MISSING_REFERENCE', path + '/context', 'Observation context is absent.')
        _integer(item['count'], 1, 10 if item['parameter'].startswith('annual.') else 1, path + '/count')
        members += item['count']
    if members > maximum['members']:
        _fail('WORK_LIMIT', '/requests', 'Observation plan exceeds its member bound.')
    document = encoded(dict(requests=requests, contexts=contexts, limits=maximum))
    if len(document.encode('utf-8')) > maximum['bytes']:
        _fail('WORK_LIMIT', '/', 'Observation plan exceeds its byte bound.')
    return document, resolved, maximum


def plan(requests, contexts, limits=None):
    """Validate shape, graph, dates and structural work without reading inputs."""
    document, _, _ = _compile(requests, contexts, {} if limits is None else limits)
    return ObservationPlan(document)


def policy_fingerprint():
    current = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if current != _LOADED_POLICY:
        _fail('STALE_INPUT_GENERATION', '/', 'Loaded observation policy no longer matches its source.')
    try:
        semantic = parameters.policy_fingerprint()
    except ValueError:
        _fail('STALE_INPUT_GENERATION', '/', 'Loaded parameter semantics no longer match their source.')
    return hashlib.sha256(encoded(dict(observations=current, parameters=semantic)).encode()).hexdigest()


def _report(row):
    return dict(row, fiscal=date.fromisoformat(row['fiscal']), known=date.fromisoformat(row['known']))


def _anchor(facts, day):
    rows = [_report(row) for row in facts['reports']]
    anchor = rules.latest_statement(rows, day)
    reason = None if anchor else ('STALE_REPORT' if any(row['known'] < day for row in rows)
                                 else 'NO_ELIGIBLE_REPORT')
    return anchor, reason


def _annual(parameter, facts, anchor, day, count, checkpoint):
    members = []
    for year in range(anchor['fiscal'].year - count + 1, anchor['fiscal'].year + 1):
        checkpoint()
        if year == anchor['fiscal'].year:
            fiscal = str(anchor['fiscal'])
        else:
            choices = [text for text in facts['annual'] if date.fromisoformat(text).year == year
                       and date.fromisoformat(text) <= anchor['fiscal']
                       and date.fromisoformat(text) + rules.LAG < day]
            fiscal = max(choices, default=None)
        row = facts['annual'].get(fiscal) if fiscal else None
        evidence = dict(source=facts['sources'].get('income-statement'), fields={},
                        known_date=str(date.fromisoformat(fiscal) + rules.LAG) if fiscal else None,
                        availability_model='fiscal-plus-90-strict; saved statements are not filing vintages')
        reason, value = None, None
        fields = ('operatingIncome', 'revenue') if parameter == 'annual.operating_margin' else (_CATALOG[parameter][2],)
        for field in fields:
            state = row.get(field) if row else None
            evidence['fields'][field] = state
            if reason is None and (state is None or not state['valid']):
                reason = state['reason'] if state else ('MISSING_FISCAL_YEAR' if fiscal is None else 'MISSING_INPUT')
        if reason is None:
            if parameter == 'annual.operating_margin':
                revenue, income = row['revenue']['value'], row['operatingIncome']['value']
                evidence.update(denominator_rule='positive revenue', canonical_inputs=dict(revenue=revenue, operating_income=income))
                if revenue <= 0:
                    reason = 'NONPOSITIVE_DENOMINATOR'
                else:
                    value = income / revenue
            else:
                value = row[fields[0]]['value']
            if value is not None and not math.isfinite(value):
                value, reason = None, 'NONFINITE_RESULT'
        members.append(dict(value=value, valid=reason is None, reason=reason,
                            fiscal_date=fiscal, fiscal_year=year, evidence=evidence))
    return members


def observe(observation_plan, inputs, checkpoint=lambda: None):
    """Return complete detached observations, or fail without a partial block.

    Preflight pays for complete-population root admission, including uncached
    reports. Ceilings are fixed capabilities; callers may only lower them.
    Financial unavailability is data. Stale/closed inputs remain operation errors.
    """
    if type(observation_plan) is not ObservationPlan:
        _fail('INVALID_SHAPE', '/', 'A validated observation plan is required.')
    try:
        submitted = observation_plan.to_dict()
    except (TypeError, ValueError):
        _fail('INVALID_SHAPE', '/', 'Observation plan is malformed.')
    _shape(submitted, ('requests', 'contexts', 'limits'), '/')
    document, resolved, limits = _compile(submitted['requests'], submitted['contexts'], submitted['limits'])
    if document != observation_plan.document:
        _fail('INVALID_SHAPE', '/', 'Observation plan is not normalized.')
    inputs.validate()
    checkpoint()
    policy = policy_fingerprint()
    bounds = inputs.bounds
    roots = [item for item in submitted['contexts'] if item['kind'] == 'root']
    root_nodes = {item['id']: item for item in roots}
    dates = {item['date'] for item in roots if item['mode'] == 'historical'}
    fact_keys = {(root_nodes[resolved[item['context']]['root']]['symbol'],
                  root_nodes[resolved[item['context']]['root']]['pool'], resolved[item['context']]['date'])
                 for item in submitted['requests']}
    inspected = len(dates) * 2 * (bounds['report_rows'] + bounds['population']) + len(roots)
    companies = {(symbol, pool) for symbol, pool, _ in fact_keys}
    inspected += len(companies) * (bounds['max_reports'] + bounds['max_annual'] + 6)
    inspected += len(fact_keys) * bounds['max_reports']
    inspected += sum(item['count'] * (bounds['max_annual'] + 1)
                     for item in submitted['requests'] if item['parameter'].startswith('annual.'))
    if inspected > limits['rows']:
        _fail('WORK_LIMIT', '/limits/rows', 'Observation request exceeds its inspected-row bound.')
    decisions = inputs.admit(roots, dict(rows=limits['rows'], bytes=limits['bytes']), checkpoint)
    roots_by_id = {item['root']: item for item in decisions}
    result = dict(format='parameter-observations', version=VERSION, generation=inputs.identity,
                  projection=inputs.projection['content'], provider_policy=policy,
                  roots=decisions, contexts=list(resolved.values()), results=[])
    used_bytes = len(encoded(result).encode('utf-8'))
    facts_cache, anchor_cache = {}, {}
    facts_bytes = 0
    for request in submitted['requests']:
        checkpoint()
        context = resolved[request['context']]
        root = roots_by_id[context['root']]
        day = date.fromisoformat(context['date'])
        item = dict(id=request['id'], parameter=request['parameter'], context=request['context'],
                    root=context['root'], unit=_CATALOG[request['parameter']][0], anchor=None,
                    anchor_report=None,
                    candidate_rank=root['candidate_rank'], members=[], valid=False, reason=None)
        if not root['admitted']:
            item['reason'] = 'ROOT_NOT_ADMITTED'
        else:
            is_root = context['id'] == context['root']
            if request['parameter'] == 'market.enterprise_value' and is_root:
                anchor = _report(root['statement'])
                valuation, evidence = root['valuation'], root.get('admission_evidence')
                item['anchor'] = str(anchor['fiscal'])
                item['anchor_report'] = {key: str(value) if isinstance(value, date) else value for key, value in anchor.items()}
                item['members'] = [dict(value=valuation['enterprise_value'], valid=True, reason=None,
                                        fiscal_date=str(anchor['fiscal']), fiscal_year=anchor['fiscal'].year,
                                        evidence=evidence)]
            else:
                key = root['symbol'], root['pool']
                if key not in facts_cache:
                    facts_cache[key] = inputs.company(root['symbol'], root['pool'],
                        budget=dict(bytes=limits['bytes'] - facts_bytes), checkpoint=checkpoint)
                    facts_bytes += len(encoded(facts_cache[key]).encode('utf-8'))
                    if facts_bytes > limits['bytes']:
                        _fail('WORK_LIMIT', '/limits/bytes', 'Observation facts exceed their byte bound.')
                facts = facts_cache[key]
                context_key = (*key, context['date'])
                if context_key not in anchor_cache:
                    anchor_cache[context_key] = _anchor(facts, day)
                anchor, reason = anchor_cache[context_key]
                item['reason'] = reason
                if anchor is not None:
                    item['anchor'] = str(anchor['fiscal'])
                    item['anchor_report'] = {key: str(value) if isinstance(value, date) else value for key, value in anchor.items()}
                    if request['parameter'].startswith('annual.'):
                        item['members'] = _annual(request['parameter'], facts, anchor, day, request['count'], checkpoint)
                    else:
                        valuation, evidence = inputs.entry(root['symbol'], anchor, day)
                        reason = evidence['reason']
                        item['members'] = [dict(value=valuation['enterprise_value'] if valuation else None,
                                                valid=valuation is not None, reason=reason,
                                                fiscal_date=str(anchor['fiscal']), fiscal_year=anchor['fiscal'].year,
                                                evidence=evidence)]
        if item['members']:
            item['valid'] = all(member['valid'] for member in item['members'])
            item['reason'] = next((member['reason'] for member in item['members'] if not member['valid']), None)
        used_bytes += len(encoded(item).encode('utf-8')) + int(bool(result['results']))
        if used_bytes > limits['bytes']:
            _fail('WORK_LIMIT', '/limits/bytes', 'Observation result exceeds its byte bound.')
        result['results'].append(item)
    checkpoint()
    inputs.validate()
    if policy_fingerprint() != policy:
        _fail('STALE_INPUT_GENERATION', '/', 'Observation policy changed during observation.')
    payload = encoded(result)
    if len(payload.encode('utf-8')) > limits['bytes']:
        _fail('WORK_LIMIT', '/limits/bytes', 'Observation result exceeds its byte bound.')
    return ObservationBlock(payload)


def example(inputs, *, symbol, pool, mode, screen_date, checkpoint=lambda: None):
    """Fixture consumer: request ingredients without evaluating a formula."""
    contexts = [dict(id='screen', kind='root', symbol=symbol, pool=pool, mode=mode, date=screen_date)]
    requests = [dict(id=name, parameter=parameter, context='screen', count=count) for name, parameter, count in
                (('revenue', 'annual.revenue', 1), ('margins', 'annual.operating_margin', 3),
                 ('enterprise', 'market.enterprise_value', 1))]
    return observe(plan(requests, contexts), inputs, checkpoint)
