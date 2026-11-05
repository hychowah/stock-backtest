"""Complete prepared scopes to scalar selected books and detached explanations.

Only this adapter combines captured source lanes. The provider retains admission
and financial meanings; reference retains arithmetic. Chunking never ranks.
One global scalar selection follows complete evaluation of the prepared scope.
The caller owns admitted connections/view, cancellation and the evidence sink.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

from backtest import observations, selection
from backtest.financial import books
from backtest.application import strategy_requests
from backtest.runtime import backtest_control
from backtest.variables import columns, definitions, library, reference, evaluation

MAX_CANDIDATES = selection.MAX_CANDIDATES
# Retained per-scope rows and lane references. 16 MiB failed a real cached-pool
# scope with four built-in lanes and one formula; MAX_CANDIDATES bounds the rows.
MAX_METADATA_BYTES = 256 * 1024 * 1024
MAX_SCOPES = 16384


def _size(value):
    return len(definitions.canonical(value).encode('ascii'))


class Budget:
    """Count planned work for receipts and bound one scope's retained metadata.

    A whole run has no work ceiling: it fails late, after the work is done, and
    a run can be stopped. Encoded output belongs to the sink.
    """
    def __init__(self, *, metadata_bytes=None):
        self.metadata_bytes=MAX_METADATA_BYTES if metadata_bytes is None else metadata_bytes
        self.tasks = self.rows = 0
    def reserve(self, plans, metadata, inspected_rows):
        if 2*_size(metadata) + sum(len(plan.document) for plan in plans) > self.metadata_bytes:
            raise definitions.FormulaError('WORK_LIMIT', '/execution', 'Scalar scope metadata exceeds its byte bound.')
        self.extend(plans, inspected_rows)
    def extend(self, plans, inspected_rows):
        """Count plans, including those compiled after their scope's reservation."""
        self.tasks += sum(len(plan.to_dict()['tasks']) for plan in plans); self.rows += inspected_rows


def scope_rows(db, *, pool, period=None, metadata_bytes=None):
    """Read one complete prepared snapshot scope without metric-availability joins."""
    maximum=MAX_METADATA_BYTES if metadata_bytes is None else metadata_bytes
    table = 'snapshots' if period is not None else 'latest_snapshots'
    args = [pool]
    where = 's.pool=?'
    if period is not None:
        where += ' AND s.year=?'; args.append(period)
    cursor = db.execute('SELECT s.*,c.name,c.sector,c.exchange,c.symbol AS _company_symbol FROM ' + table +
        ' s LEFT JOIN companies c USING(symbol) WHERE ' + where + ' ORDER BY s.rowid', args)
    names = [item[0] for item in cursor.description]
    rows = [];used=0
    for row in cursor:
        backtest_control.checkpoint()
        if len(rows) == MAX_CANDIDATES:
            raise definitions.FormulaError('WORK_LIMIT', '/population', 'Complete pool exceeds the scalar candidate ceiling.')
        detached=dict(zip(names,row))
        if detached.pop('_company_symbol') is None:
            raise definitions.FormulaError('INVALID_SHAPE', '/population', 'Prepared scope has a snapshot without a company.')
        used+=_size(detached)+1
        if used>maximum:raise definitions.FormulaError('WORK_LIMIT','/population','Complete pool metadata exceeds its byte ceiling.')
        rows.append(detached)
    if _size(rows) > maximum:
        raise definitions.FormulaError('WORK_LIMIT', '/population', 'Complete pool metadata exceeds its byte ceiling.')
    return rows


def _plans(program, roots, record_bytes, checkpoint, limits=None, metadata_bytes=None, engine='original'):
    """Compile every chunk before reading its observations; adapt temporal contexts."""
    strategy_requests.require_formula_support(program, engine, checkpoint=checkpoint)
    maximum=MAX_METADATA_BYTES if metadata_bytes is None else metadata_bytes
    plans = [];used=0
    remaining = roots
    while remaining:
        checkpoint()
        count = min(256, len(remaining))
        while True:
            try:
                plan = evaluation.plan(program, remaining[:count],
                    dict(limits or {}, output_bytes=min(evaluation.CEILINGS['output_bytes'], record_bytes - 4096)))
                break
            except definitions.FormulaError as error:
                if error.code != 'WORK_LIMIT' or count == 1:
                    raise
                count = max(1, count // 2)
        used+=len(plan.document)
        if used>maximum:raise definitions.FormulaError('WORK_LIMIT','/execution','Compiled chunks exceed their aggregate encoded bound.')
        plans.append(plan)
        remaining = remaining[count:]
    return plans


def plan_preview(capture, roots, *, record_bytes=8 * 1024 * 1024,
                 checkpoint=backtest_control.checkpoint):
    """Evaluate only explicit bounded roots; this never certifies pool coverage."""
    checked = strategy_requests.require_strategy(capture, checkpoint=checkpoint)
    if type(roots) is not list or not 1 <= len(roots) <= 16:
        raise definitions.FormulaError('WORK_LIMIT', '/preview', 'Preview needs 1–16 explicit company/date roots.')
    if checked['variables'] is None:
        raise definitions.FormulaError('INVALID_STRATEGY', '/preview', 'A formula preview requires captured formula roots.')
    program = library.VariableCapture(definitions.canonical(checked['variables'])).program
    return _plans(program, roots, record_bytes, checkpoint)


def evaluate_preview(plans, roots, view, *, checkpoint=backtest_control.checkpoint):
    """Consume precompiled explicit requests; no complete-pool claim is made."""
    blocks = []
    used = 0
    for plan in plans:
        block = reference.evaluate(plan, view, checkpoint).to_dict()
        used += _size(block)
        if used > 16 * 1024 * 1024:
            raise definitions.FormulaError('WORK_LIMIT', '/preview', 'Complete preview exceeds its encoded byte ceiling.')
        blocks.append(block)
    return dict(population='explicit-request-scopes', requested=roots, evaluations=blocks)


def preview(capture, roots, view, *, record_bytes=8 * 1024 * 1024, checkpoint=backtest_control.checkpoint):
    """Callable composition of financial-free planning and bounded observation."""
    return evaluate_preview(plan_preview(capture,roots,record_bytes=record_bytes,checkpoint=checkpoint),roots,view,checkpoint=checkpoint)


def _plan_work(plans, bounds):
    """Upper bound of the provider rows that evaluating plans inspects."""
    inspected=0
    for plan in plans:
        compiled=plan.to_dict();dates={root['date'] for root in compiled['requests'] if root['mode']=='historical'}
        inspected+=2*len(dates)*(bounds['report_rows']+bounds['population'])
        annual=2*bounds['max_annual'] if observations.requires_annual_fields(compiled['provider']['requests']) else 0
        inspected+=len(compiled['requests'])*(bounds['max_reports']+annual+11)
        inspected+=4*len(compiled['provider']['contexts'])
        inspected+=observations.additional_work_bound(compiled['provider']['requests'],compiled['provider']['contexts'],bounds)
    return inspected


def _scope(db, view, capture, period, entry, *, latest, owner_scope, metadata_bytes=None):
    """Return one complete prepared scope's rows and roots after checking its owner scope."""
    if (type(owner_scope) is not dict or not (owner_scope == {'kind':'dated'} or
            (set(owner_scope) == {'kind','book'} and owner_scope['kind'] == 'prepared'
             and type(owner_scope['book']) is int and owner_scope['book'] >= 0))):
        raise definitions.FormulaError('INVALID_SHAPE', '/owner_scope', 'Invalid owner scope.')
    pool=capture['pool']
    if owner_scope['kind'] == 'prepared' and (owner_scope['book'] != (0 if latest else period) or not any(
            item['mode'] == ('latest' if latest else 'historical') and item['pool'] == pool
            and item['context_date'] == str(entry) and item['book'] == owner_scope['book']
            for item in view.projection['scopes'])):
        raise definitions.FormulaError('INVALID_SHAPE', '/owner_scope', 'Prepared owner scope does not match the admitted projection.')
    rows=scope_rows(db,pool=pool,period=None if latest else period,metadata_bytes=metadata_bytes)
    if len({row['symbol'] for row in rows}) != len(rows):
        raise definitions.FormulaError('INVALID_SHAPE','/population','Prepared scope contains duplicate companies.')
    roots=[dict(symbol=row['symbol'],pool=pool,mode='latest' if latest else 'historical',date=str(entry),owner_scope=owner_scope) for row in rows]
    return rows,roots


def plan_scope(db, view, program, capture, period, entry, *, latest=False, owner_scope=None,
               budget, record_bytes=8 * 1024 * 1024, checkpoint=backtest_control.checkpoint,
               limits=None, metadata_bytes=None, engine='original'):
    """Plan every root in one complete scope before observation. Chunking bounds evaluation resources and never changes membership, ranking or the meaning of a completed scope."""
    checkpoint()
    if program is not None:
        strategy_requests.require_formula_support(program, engine, checkpoint=checkpoint)
    if owner_scope is None: owner_scope = dict(kind='dated')
    rows,roots=_scope(db,view,capture,period,entry,latest=latest,owner_scope=owner_scope,metadata_bytes=metadata_bytes)
    plans=_plans(program,roots,record_bytes,checkpoint,limits,metadata_bytes,engine) if program else []
    bounds=view.bounds
    inspected=2*len(rows)
    sources=[capture['selection']['ranking']['source']]+[item['source'] for item in capture['selection']['conditions']]
    inspected+=len(rows)*sum(source['kind']=='builtin' for source in sources)
    if plans:
        inspected+=_plan_work(plans,bounds)
    else:
        inspected+=(len(rows)+255)//256*(2*(bounds['report_rows']+bounds['population']) if not latest else 2*256)
    budget.reserve(plans,rows,inspected)
    return rows,roots,plans,inspected


class Executor:
    """One immutable strategy, borrowed view and bounded output sink per run.

    Formulas are evaluated values-only (variables/columns.py) for the rows that
    can still be selected. The reference evaluator then explains the selected
    rows only, and its values must equal the column values. Prefixes qualify
    independent trial scopes.
    """
    contract = 2
    def __init__(self, capture, view, sink, *, record_bytes=8 * 1024 * 1024,
                 checkpoint=backtest_control.checkpoint, evaluate=None, scope_prefix='', evaluation_limits=None, metadata_bytes=None, engine='original'):
        self.metadata_bytes=MAX_METADATA_BYTES if metadata_bytes is None else metadata_bytes
        if (type(self.metadata_bytes) is not int or not 0<self.metadata_bytes<=MAX_METADATA_BYTES
                or type(scope_prefix) is not str or len(scope_prefix)>64):
            raise definitions.FormulaError('WORK_LIMIT','/execution','Invalid scalar execution reservation.')
        self.evaluate = evaluate or reference.evaluate
        self.engine = engine
        self.scope_prefix = scope_prefix
        self.evaluation_limits = evaluation_limits
        self.capture = strategy_requests.require_strategy(capture, checkpoint=checkpoint)
        self.pool = self.capture['pool']; self.view = view; self.sink = sink
        self.checkpoint = checkpoint; self.record_bytes = record_bytes
        self.number = 0
        self.program = library.VariableCapture(definitions.canonical(self.capture['variables'])).program if self.capture['variables'] else None
        if self.program is not None:
            strategy_requests.require_formula_support(self.program, engine, checkpoint=checkpoint)
        self.formulas = columns.Formulas(self.program) if self.program is not None else None
        self.facts = columns.Facts(view)
        self.descriptors = {item['id']: item for item in self.capture['builtins']}

    def _admit(self, rows, roots, entry, owner_scope, dated):
        """Admission decisions in row order.

        Dated scopes apply ReadView.admit's rules (eligible report, legacy buffer,
        cached prices, eligible valuation) and take the entry valuation from the
        book row: compute_period derived it with the same function and prices.
        Other scopes ask the view, as the reference provider does.
        """
        if dated:
            statements, ranks = self.view.candidates(str(entry), self.checkpoint)
            decisions = []
            for i,row in enumerate(rows):
                symbol = row['symbol']; rank = ranks.get(symbol)
                reason = ('NO_ELIGIBLE_REPORT' if statements[self.pool].get(symbol) is None
                          else 'OUTSIDE_LEGACY_BUFFER' if self.pool == 'legacy' and rank is None
                          else 'MISSING_CACHED_PRICES' if not self.view.is_cached(symbol)
                          else 'INELIGIBLE_VALUATION' if not books.eligible(self.pool, row['market_cap'], row['enterprise_value'])
                          else None)
                decisions.append(dict(root='r'+str(i), symbol=symbol, pool=self.pool, mode='historical', date=str(entry),
                    admitted=reason is None, reason=reason, candidate_rank=rank, owner_scope=owner_scope,
                    valuation=None if reason else dict(market_cap=row['market_cap'], enterprise_value=row['enterprise_value'], ebitda=row['ebitda'])))
            return decisions
        decisions = []
        for first in range(0, len(roots), 256):
            group = [dict(id='r' + str(i), **root) for i, root in enumerate(roots[first:first+256])]
            budget = dict(rows=2*(self.view.bounds['report_rows']+self.view.bounds['population']), bytes=16*1024*1024)
            for decision in self.view.admit(group, budget, self.checkpoint):
                decision['owner_scope'] = owner_scope
                decisions.append(decision)
        return decisions

    def select(self, db, period, entry, exit_day=None, *, latest=False, owner_scope=None):
        self.checkpoint()
        if owner_scope is None: owner_scope = dict(kind='dated')
        rows, roots = _scope(db, self.view, self.capture, period, entry, latest=latest,
                             owner_scope=owner_scope, metadata_bytes=self.metadata_bytes)
        self.number += 1; identity = self.scope_prefix + 'scope:' + str(self.number)
        specification = deepcopy(self.capture['selection'])
        role_sources=[specification['ranking']['source']]+[item['source'] for item in specification['conditions']]
        lane_of = lambda role: 'ranking' if role == 0 else 'c' + str(role - 1)
        mode = 'latest' if latest else 'historical'; year = 0 if latest else period
        decisions = self._admit(rows, roots, entry, owner_scope, not latest and owner_scope == {'kind': 'dated'})
        admitted = sum(decision['admitted'] for decision in decisions)
        receipt = dict(policy=dict(executor=_LOADED,selection=selection.policy_fingerprint()),id=identity,
            population='complete-prepared-scope', mode=mode, pool=self.pool, date=str(entry),
            exit=str(exit_day) if exit_day is not None else None, prepared_period=period, input=self.view.identity,
            rows=len(rows), source_population=self.view.bounds['population'],
            provider_admitted_in_prepared_scope=admitted,
            selection_population='prepared rows with usable return evidence' if not latest else 'prepared exact-session latest rows')
        values = [{} for row in rows]
        # One query per stored table for the whole scope; primary keys make each
        # symbol's value unique, as per-row lookups read.
        stored = {}
        metrics = {role: self.descriptors[source['id']]['storage'] for role, source in enumerate(role_sources)
                   if source['kind'] == 'builtin' and self.descriptors[source['id']]['storage']['kind'] == 'metric'}
        fields = {role: self.descriptors[source['id']]['storage'] for role, source in enumerate(role_sources)
                  if source['kind'] == 'builtin' and self.descriptors[source['id']]['storage']['kind'] != 'metric'}
        if metrics:
            names = sorted({storage['metric'] for storage in metrics.values()})
            by_metric = {}
            for symbol, metric, multiple, yield_value in db.execute(
                    'SELECT symbol,metric,multiple,yield_value FROM screening_metrics WHERE mode=? AND pool=? AND year=? AND metric IN ('
                    + ','.join('?' * len(names)) + ')', (mode, self.pool, year, *names)):
                by_metric[symbol, metric] = multiple, yield_value
            for role, storage in metrics.items():
                column = 1 if storage['component'] == 'yield' else 0
                stored[role] = {symbol: pair[column] for (symbol, metric), pair in by_metric.items() if metric == storage['metric']}
        if fields:
            names = sorted({storage['field'] for storage in fields.values()})
            by_field = {}
            for symbol, field, value in db.execute(
                    'SELECT symbol,field,value FROM filter_values WHERE mode=? AND pool=? AND year=? AND field IN ('
                    + ','.join('?' * len(names)) + ')', (mode, self.pool, year, *names)):
                by_field[symbol, field] = value
            for role, storage in fields.items():
                stored[role] = {symbol: value for (symbol, field), value in by_field.items() if field == storage['field']}
        def builtin(role, symbol):
            source = role_sources[role]
            descriptor = self.descriptors[source['id']]; storage = descriptor['storage']
            value = stored[role].get(symbol)
            canonical = float(Decimal(str(value)).scaleb(storage['scale'])) if value is not None else None
            valid = type(value) in (int,float) and math.isfinite(value) and canonical is not None and math.isfinite(canonical)
            return value if valid else None, dict(scope=identity, symbol=symbol, source=source, stored=value if valid else None,
                canonical=canonical if valid else None, unit=descriptor['unit'], valid=valid,
                reason=None if valid else 'MISSING_INPUT')
        for index, row in enumerate(rows):
            for role in stored:
                values[index][lane_of(role)] = builtin(role, row['symbol'])[0]
            if not decisions[index]['admitted']:
                values[index]['ranking'] = None
        conditions = [dict(lane='c'+str(i),op=item['op'],value=item['storage_comparison_value']) for i,item in enumerate(specification['conditions'])]
        bounds = self.capture['bounds']
        for field, op in [('min_cap','ge'),('max_cap','le'),('min_ev','ge'),('sector','eq'),('exchange','eq')]:
            if bounds[field] is not None:
                lane = {'min_cap':'market_cap','max_cap':'market_cap','min_ev':'enterprise_value'}.get(field,field)
                conditions.append(dict(lane=lane,op=op,value=bounds[field]))
        def row_values(i):
            return dict(values[i], **{key:rows[i].get(key) for key in ('market_cap','enterprise_value','sector','exchange')})
        formula_roles = [role for role, source in enumerate(role_sources) if source['kind'] == 'formula']
        if formula_roles:
            # With a stored ranking and filter-first order, a row that is not
            # admitted, has no ranking value or fails a stored condition can
            # never be selected; formulas run only for the remaining rows.
            if role_sources[0]['kind'] == 'builtin' and specification['selection_order'] == 'filter_first':
                formula_lanes = {lane_of(role) for role in formula_roles}
                stored_conditions = [item for item in conditions if item['lane'] not in formula_lanes]
                needed = [i for i in range(len(rows)) if decisions[i]['admitted'] and selection.finite(values[i].get('ranking')) is not None
                          and selection.passes(row_values(i), stored_conditions, self.checkpoint)]
            else:
                needed = list(range(len(rows)))
            outputs = self.formulas.evaluate([roots[i] for i in needed], self.view, self.checkpoint,
                                             decisions=[decisions[i] for i in needed], facts=self.facts)
            computed = dict(zip(needed, outputs))
            for i, output in computed.items():
                for role in formula_roles:
                    source = role_sources[role]
                    value, valid, reason = output[(source['variable_id'], source['revision'])]
                    values[i][lane_of(role)] = value if valid else None
                    if role == 0 and not decisions[i]['admitted']:
                        values[i]['ranking'] = None
        candidates = [dict(symbol=row['symbol'], candidate_rank=row['candidate_rank'], values=row_values(i)) for i,row in enumerate(rows)]
        selected = selection.select(candidates, dict(ranking=dict(lane='ranking',direction=specification['ranking']['direction']),
            conditions=conditions, **{key:specification[key] for key in ('rank_from','rank_to','selection_order')}), self.checkpoint)
        chosen = [item['index'] for item in selected['selected']]
        references = {index: {} for index in chosen}
        records = []
        if formula_roles and chosen:
            # Explain the selected rows with the reference evaluator. Its values
            # must equal the column values the selection used.
            plans = _plans(self.program, [roots[i] for i in chosen], self.record_bytes, self.checkpoint,
                           self.evaluation_limits, self.metadata_bytes, self.engine)
            offset = 0
            for chunk, plan in enumerate(plans):
                self.checkpoint()
                block = self.evaluate(plan, self.view, self.checkpoint).to_dict()
                # The result header carries the projection once; the block keeps its content hash.
                block['identity'] = dict(block['identity'], projection=block['identity']['projection']['content'])
                records.append(dict(type='evaluation', value=dict(scope=identity, chunk=chunk, block=block)))
                for item in block['results']:
                    position = chosen[offset + item['request']]
                    for role in formula_roles:
                        source = role_sources[role]
                        if (source['variable_id'], source['revision']) != (item['variable_id'], item['revision']):
                            continue
                        column = computed[position][(item['variable_id'], item['revision'])]
                        explained = (item['value'] if item['valid'] else None, item['valid'], item['reason'])
                        if (column[1], column[2]) != explained[1:] or (column[1] and column[0].hex() != float(explained[0]).hex()):
                            raise RuntimeError('Column and reference formula values differ for ' + rows[position]['symbol'] + '.')
                        references[position][lane_of(role)] = dict(scope=identity, chunk=chunk, request=item['request'],
                            variable_id=item['variable_id'], revision=item['revision'], evidence=item['evidence'],
                            valid=item['valid'], reason=item['reason'])
                offset += len(plan.to_dict()['requests'])
        records.append(dict(type='scope', value=receipt))
        for index in chosen:
            lanes = []
            for role in stored:
                refs = builtin(role, rows[index]['symbol'])[1]
                references[index][lane_of(role)] = refs; lanes.append(dict(lane=lane_of(role), **refs))
            if lanes:records.append(dict(type='lanes', value=dict(scope=identity, symbol=rows[index]['symbol'], lanes=lanes)))
        output = []
        ranking_source = specification['ranking']['source']
        if ranking_source['kind'] == 'builtin':
            descriptor = self.descriptors[ranking_source['id']]
        else:
            descriptor = next(item for item in self.capture['variables']['program']['definitions'] if item['variable_id']==ranking_source['variable_id'] and item['revision']==ranking_source['revision'])
        for item in selected['selected']:
            index = item['index']; original = rows[index]
            value = item['value']
            if ranking_source['kind']=='builtin':value=float(Decimal(str(value)).scaleb(descriptor['storage']['scale']))
            output.append(dict(original, rank=item['rank'], ranking_value=value, ranking_unit=descriptor['unit'],
                ranking_display=descriptor['display'], ranking_direction=specification['ranking']['direction'],
                scalar_evidence=dict(scope=identity, lanes=references[index])))
        records.append(dict(type='selection',value=dict(scope=identity, selected=selected, requested=specification,
            unavailable_ranking=sum(candidate['values'].get('ranking') is None for candidate in candidates))))
        for record in records:
            self.checkpoint()
            self.sink(record)
        self.view.validate()
        return output
