"""Bounded reference formula selection over explicit company/date scopes.

plan(program, roots, specification, limits=None) captures ranking and conditions
by immutable formula-root identity. evaluate(plan, inputs, checkpoint) borrows
an already admitted input view and returns complete detached selection evidence.
The caller keeps source/cache ownership and the attachment/view alive as usual.

The provider owns admission and original ranks. Explicit roots do not certify
complete pool coverage. Selection never changes dates, financial rules or returns.
An empty scope is retained; no return, reciprocal yield or CAGR is invented.
All encoded-content limits are fixed and lowerable. Nothing is truncated to fit.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

from backtest import selection as policy
from backtest.variables import definitions, reference

VERSION = 1

# Fixed qualification inventory. Provider or language expansion alone does not
# qualify application execution. Admission remains closed until verified.
QUALIFIED_PARAMETERS = ('annual.revenue',
 'annual.operating_income',
 'annual.operating_margin',
 'market.enterprise_value',
 'annual.report_ebitda',
 'owner.market_cap',
 'owner.profit_margin',
 'owner.pe',
 'owner.pb',
 'owner.fcf_yield',
 'owner.price_fcf',
 'owner.peg',
 'owner.roe',
 'owner.current_ratio',
 'owner.interest_coverage',
 'owner.debt_equity',
 'owner.return_1y',
 'owner.return_3y',
 'owner.ev_ebitda',
 'owner.ev_ebitda_3y',
 'owner.ebitda_yield',
 'owner.operating_yield_spread_3y',
 'annual.cost_of_revenue',
 'annual.selling_general_administrative_expense',
 'annual.research_development_expense',
 'annual.interest_income',
 'annual.interest_expense',
 'annual.pretax_income',
 'annual.income_tax_expense',
 'annual.net_income',
 'annual.weighted_average_basic_shares',
 'annual.weighted_average_diluted_shares',
 'annual.cash_and_equivalents',
 'annual.short_term_investments',
 'annual.long_term_investments',
 'annual.net_receivables',
 'annual.accounts_receivable',
 'annual.inventory',
 'annual.prepaid_expenses',
 'annual.current_assets',
 'annual.property_plant_equipment_net',
 'annual.goodwill',
 'annual.intangible_assets',
 'annual.total_assets',
 'annual.accounts_payable',
 'annual.accrued_expenses',
 'annual.current_deferred_revenue',
 'annual.noncurrent_deferred_revenue',
 'annual.current_liabilities',
 'annual.total_liabilities',
 'annual.short_term_debt',
 'annual.long_term_debt',
 'annual.lease_obligations',
 'annual.equity',
 'annual.preferred_stock',
 'annual.noncontrolling_interests',
 'annual.depreciation_amortization',
 'annual.stock_based_compensation',
 'annual.operating_cash_flow',
 'annual.capital_expenditure',
 'annual.net_acquisitions',
 'annual.income_taxes_paid',
 'annual.interest_paid',
 'annual.net_debt_issuance',
 'annual.common_dividends_paid',
 'annual.preferred_dividends_paid',
 'annual.common_stock_repurchased',
 'annual.common_stock_issuance',
 'annual.ebit',
 'annual.basic_eps',
 'annual.diluted_eps',
 'annual.total_debt',
 'annual.free_cash_flow',
 'market.adjusted_price',
 'market.volume',
 'treasury.us_3m',
 'treasury.us_10y')
QUALIFIED_NAMESPACES = frozenset((version, 'financial-parameters/' + str(catalog), 'annual-lag90/1')
    for version in (1, 2, 3) for catalog in (1, 2, 3))
QUALIFIED_OPERATIONS = frozenset(('constant', 'parameter', 'annual', 'ref', 'at', 'lookback',
    'neg', 'add', 'sub', 'mul', 'div', 'positive_div'))
QUALIFIED_ANNUAL_STATISTICS = frozenset(('mean', 'min', 'max', 'growth', 'cagr'))
CEILINGS = MappingProxyType(dict(conditions=50, plan_bytes=4 * 1024 * 1024,
    output_bytes=24 * 1024 * 1024, retained_bytes=96 * 1024 * 1024))
_LOADED_SELECTION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class SelectionPlan:
    """Canonical captured intent and reservations, reconstructed before input access."""
    document: str

    def to_dict(self):
        return json.loads(self.document)

    def to_json(self):
        return self.document


@dataclass(frozen=True)
class SelectionBlock:
    """Detached scopes and selections with the complete formula-evaluation block."""
    document: str

    def to_dict(self):
        return json.loads(self.document)

    def to_json(self):
        return self.document


def _fail(code, path, message):
    raise definitions.FormulaError(code, path, message)


def _hash(document):
    return 'sha256:' + hashlib.sha256(document.encode()).hexdigest()


def _encode(value, maximum, checkpoint=lambda: None):
    # The C encoder writes the same bytes as the incremental one, several times faster.
    checkpoint()
    text = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    if len(text) > maximum:
        _fail('WORK_LIMIT', '/limits', 'Selection evidence exceeds its encoded-content bound.')
    return text


def policy_fingerprint():
    """Bind loaded selection, scalar ordering and reference/provider policies."""
    return dict(backend='reference-scalar-selection', version=VERSION,
                selection=_LOADED_SELECTION, scalar=policy.policy_fingerprint(), reference=reference.policy_fingerprint())


def _limits(limits):
    result = dict(CEILINGS)
    if limits is None:
        return result
    if type(limits) is not dict or set(limits) - set(result):
        _fail('INVALID_SHAPE', '/limits', 'Unknown scalar-selection limit.')
    for name, value in limits.items():
        if type(value) is not int or not 1 <= value <= result[name]:
            _fail('INVALID_SHAPE', '/limits/' + name, 'Selection limits can only lower fixed ceilings.')
        result[name] = value
    return result


def _specification(program, submitted, limits):
    projection = definitions.require_program(program)
    available = {(projection['definitions'][i]['variable_id'], projection['definitions'][i]['revision']):
                 projection['definitions'][i] for i in projection['roots']}
    def variable(item, path):
        key = (item.get('variable_id'), item.get('revision'))
        if any(type(value) is not str for value in key) or key not in available:
            _fail('INVALID_STRATEGY', path, 'Selection must name an exact captured program root.')
        return available[key]
    allowed = {'ranking', 'rank_from', 'rank_to', 'selection_order', 'conditions'}
    if type(submitted) is not dict or set(submitted) - allowed or 'ranking' not in submitted:
        _fail('INVALID_STRATEGY', '/specification', 'An explicit scalar selection specification is required.')
    ranking = submitted['ranking']
    if type(ranking) is not dict or set(ranking) != {'variable_id', 'revision', 'direction'}:
        _fail('INVALID_STRATEGY', '/ranking', 'Ranking needs a captured variable and explicit direction.')
    variable(ranking, '/ranking')
    conditions = submitted.get('conditions', [])
    if type(conditions) is not list or len(conditions) > limits['conditions']:
        _fail('WORK_LIMIT', '/conditions', 'Scalar conditions exceed their count bound.')
    normalized, lanes = [], []
    for index, item in enumerate(conditions):
        path = '/conditions/' + str(index)
        required = {'variable_id', 'revision', 'op', 'threshold'}
        if (type(item) is not dict or not required <= set(item)
                or set(item) - required - {'submitted_threshold', 'comparison_value'}
                or item['op'] not in ('lt', 'gt')):
            _fail('INVALID_STRATEGY', path, 'A custom condition needs a captured variable, strict comparison and threshold.')
        definition = variable(item, path)
        quantity = definitions.normalize_quantity(item.get('submitted_threshold', item['threshold']), definition['unit'])
        if 'submitted_threshold' in item and item['threshold'] != quantity['threshold']:
            _fail('INVALID_STRATEGY', path + '/threshold', 'Submitted and canonical thresholds disagree.')
        if 'comparison_value' in item and (type(item['comparison_value']) is not float or item['comparison_value'] != quantity['comparison_value']):
            _fail('INVALID_STRATEGY', path + '/comparison_value', 'Captured binary64 threshold disagrees.')
        normalized.append(dict(variable_id=item['variable_id'], revision=item['revision'], op=item['op'], **quantity))
        lanes.append(dict(lane='v' + str(index), op=item['op'], value=quantity['comparison_value']))
    base = {name: submitted[name] for name in ('rank_from', 'rank_to', 'selection_order') if name in submitted}
    try:
        checked = policy.validate(dict(ranking=dict(lane='ranking', direction=ranking['direction']), conditions=lanes, **base))
    except policy.SelectionError as error:
        _fail(error.code, error.path, str(error))
    specification = dict(ranking=dict(ranking), conditions=normalized,
                         **{name: checked[name] for name in ('rank_from', 'rank_to', 'selection_order')})
    return projection, specification, checked


def _compile(program, roots, specification, limits, checkpoint):
    projection, spec, scalar = _specification(program, specification, limits)
    # The reference owner validates every root/date and its aggregate work limits.
    base_reference = reference.plan(program, roots).to_dict()
    seen, scopes = set(), []
    scope_indexes = {}
    for index, root in enumerate(base_reference['requests']):
        checkpoint()
        scope_key = tuple(root[name] for name in ('pool', 'mode', 'date'))
        company_key = (scope_key, root['symbol'])
        if company_key in seen:
            _fail('INVALID_STRATEGY', '/requests/' + str(index), 'Duplicate company request within one selection scope.')
        seen.add(company_key)
        if scope_key not in scope_indexes:
            scope_indexes[scope_key] = len(scopes)
            scopes.append(dict(pool=root['pool'], mode=root['mode'], date=root['date'], requests=[]))
        scopes[scope_indexes[scope_key]]['requests'].append(index)
    result = dict(format='scalar-selection-plan', version=VERSION,
        reference=base_reference, specification=spec, scalar_policy=scalar,
        scopes=scopes, limits=limits)
    # Reserve every candidate as a selected result; rank-first cannot exceed it.
    # Repeated formula roles use result indexes, keeping their explanations in
    # the complete nested evaluation block instead of copying them per condition.
    record = dict(request=8192, symbol='X' * 128, candidate_rank=8192, rank=8192,
        ranking_value='-' * 24, unit='USD/share', direction='highest', weight='-' * 24,
        evidence=dict(ranking_result=8192, condition_results=[8192] * len(spec['conditions']), admission='c999'))
    selection_bytes = (16384 + len(definitions.canonical(spec))
        + len(definitions.canonical(scopes)) + (len(definitions.canonical(record)) + 1) * len(roots))
    plan_reservation = len(definitions.canonical(result)) + 8192
    retained_remaining = limits['retained_bytes'] - 2 * plan_reservation - 2 * selection_bytes
    reference_output = min(reference.CEILINGS['output_bytes'], limits['output_bytes'] - selection_bytes,
                           retained_remaining // 3)
    reference_retained = min(reference.CEILINGS['retained_bytes'], retained_remaining)
    if reference_output < 1 or reference_retained < 1:
        _fail('WORK_LIMIT', '/limits', 'Selection reservations exceed their byte bounds.')
    result['reference'] = reference.plan(program, roots,
        dict(output_bytes=reference_output, retained_bytes=reference_retained)).to_dict()
    result['reservations'] = dict(selection=selection_bytes, plan=plan_reservation)
    document = _encode(result, limits['plan_bytes'], checkpoint)
    if len(document) > plan_reservation:
        _fail('WORK_LIMIT', '/limits/plan_bytes', 'Selection plan exceeds its retained reservation.')
    return document


def plan(program, roots, specification, limits=None):
    """Plan explicit scopes before observation; custom conditions are strictly lt/gt.

    ranking names variable_id/revision and direction. Conditions name the same
    immutable identities and threshold {value: decimal string, unit: display or
    canonical unit}. Optional submitted_threshold plus canonical threshold must
    agree. Raw submitted decimals keep the language's 64-character ceiling.
    """
    return SelectionPlan(_compile(program, roots, specification, _limits(limits), lambda: None))


def require_plan(selection_plan, checkpoint=lambda: None):
    """Reconstruct all captured intent, scopes and reservations before input use."""
    if type(selection_plan) is not SelectionPlan or type(selection_plan.document) is not str:
        _fail('INVALID_SHAPE', '', 'An immutable scalar selection plan is required.')
    if len(selection_plan.document) > CEILINGS['plan_bytes']:
        _fail('WORK_LIMIT', '/limits/plan_bytes', 'Selection plan exceeds its byte ceiling.')
    try:
        submitted = selection_plan.to_dict()
        if type(submitted) is not dict or set(submitted) != {'format', 'version', 'reference', 'specification', 'scalar_policy', 'scopes', 'limits', 'reservations'}:
            _fail('INVALID_SHAPE', '', 'Selection plan fields do not match its format.')
        reference_plan = reference.EvaluationPlan(definitions.canonical(submitted['reference']))
        checked = reference.require_plan(reference_plan, checkpoint)
        program = definitions.FormulaProgram(definitions.canonical(checked['program']))
    except (TypeError, ValueError, RecursionError) as error:
        if isinstance(error, definitions.FormulaError):
            raise
        _fail('INVALID_SHAPE', '', 'Captured scalar selection plan is malformed.')
    rebuilt = _compile(program, checked['requests'], submitted['specification'], _limits(submitted['limits']), checkpoint)
    if rebuilt != selection_plan.document:
        _fail('INVALID_SHAPE', '', 'Selection plan differs from its canonical checked projection.')
    return submitted


def require_program(program, *, checkpoint=lambda: None):
    checked = definitions.require_program(program)
    if checked['version'] != 1 or any(
            (item['definition']['version'], item['definition']['parameter_catalog'],
             item['definition']['temporal_policy']) not in QUALIFIED_NAMESPACES
            for item in checked['bundle']['definitions']):
        _fail('UNSUPPORTED_CAPABILITY', '/variables', 'Unsupported Original formula namespace.')
    for node in checked['nodes']:
        checkpoint()
        if node['op'] not in QUALIFIED_OPERATIONS or (node['op'] == 'annual' and
                node['stat'] not in QUALIFIED_ANNUAL_STATISTICS):
            _fail('UNSUPPORTED_CAPABILITY', node['path'], 'Unsupported Original formula operation.')
        if node['op'] in ('parameter', 'annual') and node['parameter'] not in QUALIFIED_PARAMETERS:
            _fail('UNSUPPORTED_CAPABILITY', node['path'], 'Unsupported Original observation parameter.')
    return reference.require_program(program, checkpoint=checkpoint)


def evaluate(selection_plan, inputs, checkpoint=lambda: None):
    """Return complete detached evidence or propagate cancellation/staleness/faults.

    The requested subset is explicit. Provider admission and original ranks remain
    authoritative, including for constant-only formulas. Each scope ranks alone.
    """
    checked = require_plan(selection_plan, checkpoint)
    checkpoint()
    require_program(definitions.FormulaProgram(
        definitions.canonical(checked['reference']['program'])), checkpoint=checkpoint)
    current_policy = policy_fingerprint()
    inputs.validate()
    generation, projection = inputs.identity, inputs.projection
    formula = reference.evaluate(reference.EvaluationPlan(definitions.canonical(checked['reference'])), inputs, checkpoint)
    evaluated = formula.to_dict()
    by_result = {(item['request'], item['variable_id'], item['revision']): index
                 for index, item in enumerate(evaluated['results'])}
    roots = {item['root']: item for item in evaluated['observations']['roots']}
    spec = checked['specification']
    def result_index(request, variable):
        return by_result[(request, variable['variable_id'], variable['revision'])]
    scopes = []
    for scope in checked['scopes']:
        checkpoint()
        candidates, selected_metadata = [], []
        for request in scope['requests']:
            checkpoint()
            ranking_index = result_index(request, spec['ranking'])
            ranking = evaluated['results'][ranking_index]
            admission = roots[ranking['root']]
            if not admission['admitted']:
                continue
            condition_indexes = [result_index(request, item) for item in spec['conditions']]
            values = {'ranking': ranking['value'] if ranking['valid'] else None}
            values.update({'v' + str(index): evaluated['results'][slot]['value'] if evaluated['results'][slot]['valid'] else None
                           for index, slot in enumerate(condition_indexes)})
            candidates.append(dict(symbol=evaluated['requests'][request]['symbol'],
                                   candidate_rank=admission['candidate_rank'], values=values))
            selected_metadata.append(dict(request=request, ranking=ranking_index, conditions=condition_indexes, admission=ranking['root']))
        chosen = policy.select(candidates, checked['scalar_policy'], checkpoint)
        selected = []
        for item in chosen['selected']:
            row, meta = candidates[item['index']], selected_metadata[item['index']]
            selected.append(dict(request=meta['request'], symbol=row['symbol'], candidate_rank=row['candidate_rank'],
                rank=item['rank'], ranking_value=item['value'], unit=evaluated['results'][meta['ranking']]['unit'],
                direction=spec['ranking']['direction'], weight=1 / len(chosen['selected']),
                evidence=dict(ranking_result=meta['ranking'], condition_results=meta['conditions'], admission=meta['admission'])))
        scopes.append(dict(**scope, requested=len(scope['requests']), admitted=len(candidates),
                           matches=chosen['matches'], empty=not selected, selected=selected))
    identity = dict(plan=_hash(selection_plan.document), formula=evaluated['calculation_identity'], policy=current_policy)
    block = dict(format='scalar-selection', version=VERSION, specification=spec,
                 population='explicit-request-scopes', identity=identity,
                 calculation_identity=_hash(definitions.canonical(identity)), evaluation=evaluated, scopes=scopes)
    limits = checked['limits']
    metadata_bytes = len(_encode(dict(block, evaluation=None), limits['output_bytes'], checkpoint))
    retained = 2 * len(selection_plan.document) + 2 * len(formula.document) + metadata_bytes
    maximum = min(limits['output_bytes'], limits['retained_bytes'] - retained)
    if maximum < 1:
        _fail('WORK_LIMIT', '/limits/retained_bytes', 'Selection evidence exceeds its retained bound.')
    def current():
        checkpoint()
        inputs.validate()
        if inputs.identity != generation or inputs.projection != projection or policy_fingerprint() != current_policy:
            _fail('STALE_INPUT_GENERATION', '', 'Selection inputs or source policy changed during evaluation.')
    current()
    document = _encode(block, maximum, checkpoint)
    current()
    return SelectionBlock(document)
