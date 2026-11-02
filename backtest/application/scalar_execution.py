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

from backtest import selection
from backtest.application import strategy_requests
from backtest.runtime import backtest_control
from backtest.variables import definitions, library, reference

MAX_CANDIDATES = selection.MAX_CANDIDATES
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_TASKS = 16 * 1024 * 1024
MAX_SCOPES = 16384
MAX_INSPECTED_ROWS = 2**31


def _size(value):
    return len(definitions.canonical(value).encode('ascii'))


class Budget:
    """Aggregate planned work and scalar metadata; encoded output belongs to sink."""
    def __init__(self):
        self.tasks = self.scopes = self.rows = 0
    def reserve(self, plans, metadata, inspected_rows):
        tasks = sum(len(plan.to_dict()['tasks']) for plan in plans)
        if (self.scopes + 1 > MAX_SCOPES or self.tasks + tasks > MAX_TASKS
                or self.rows + inspected_rows > MAX_INSPECTED_ROWS
                or 2*_size(metadata) + sum(len(plan.document) for plan in plans) > MAX_METADATA_BYTES):
            raise definitions.FormulaError('WORK_LIMIT', '/execution', 'Scalar execution exceeds its aggregate work or scope bound.')
        self.tasks += tasks; self.scopes += 1; self.rows += inspected_rows


def scope_rows(db, *, pool, period=None):
    """Read one complete prepared snapshot scope without metric-availability joins."""
    table = 'snapshots' if period is not None else 'latest_snapshots'
    args = [pool]
    where = 's.pool=?'
    if period is not None:
        where += ' AND s.year=?'; args.append(period)
    cursor = db.execute('SELECT s.*,c.name,c.sector,c.exchange FROM ' + table +
        ' s JOIN companies c USING(symbol) WHERE ' + where + ' ORDER BY s.rowid', args)
    names = [item[0] for item in cursor.description]
    rows = [];used=0
    for row in cursor:
        backtest_control.checkpoint()
        if len(rows) == MAX_CANDIDATES:
            raise definitions.FormulaError('WORK_LIMIT', '/population', 'Complete pool exceeds the scalar candidate ceiling.')
        detached=dict(zip(names,row));used+=_size(detached)+1
        if used>MAX_METADATA_BYTES:raise definitions.FormulaError('WORK_LIMIT','/population','Complete pool metadata exceeds its byte ceiling.')
        rows.append(detached)
    if _size(rows) > MAX_METADATA_BYTES:
        raise definitions.FormulaError('WORK_LIMIT', '/population', 'Complete pool metadata exceeds its byte ceiling.')
    return rows


def _plans(program, roots, record_bytes, checkpoint):
    """Compile every chunk before reading its observations; adapt temporal contexts."""
    plans = [];used=0
    remaining = roots
    while remaining:
        checkpoint()
        count = min(256, len(remaining))
        while True:
            try:
                plan = reference.plan(program, remaining[:count],
                    dict(output_bytes=min(reference.CEILINGS['output_bytes'], record_bytes - 4096)))
                break
            except definitions.FormulaError as error:
                if error.code != 'WORK_LIMIT' or count == 1:
                    raise
                count = max(1, count // 2)
        used+=len(plan.document)
        if used>MAX_METADATA_BYTES:raise definitions.FormulaError('WORK_LIMIT','/execution','Compiled chunks exceed their aggregate encoded bound.')
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


class Executor:
    """One immutable strategy, borrowed view and bounded output sink per run."""
    contract = 2
    def __init__(self, capture, view, sink, *, record_bytes=8 * 1024 * 1024,
                 checkpoint=backtest_control.checkpoint):
        self.capture = strategy_requests.require_strategy(capture, checkpoint=checkpoint)
        self.pool = self.capture['pool']; self.view = view; self.sink = sink
        self.checkpoint = checkpoint; self.record_bytes = record_bytes
        self.budget = Budget(); self.number = 0
        self.program = library.VariableCapture(definitions.canonical(self.capture['variables'])).program if self.capture['variables'] else None
        self.descriptors = {item['id']: item for item in self.capture['builtins']}

    def select(self, db, period, entry, exit_day=None, *, latest=False):
        self.checkpoint()
        rows = scope_rows(db, pool=self.pool, period=None if latest else period)
        self.number += 1; identity = 'scope:' + str(self.number)
        roots = [dict(symbol=row['symbol'], pool=self.pool, mode='latest' if latest else 'historical', date=str(entry)) for row in rows]
        plans = _plans(self.program, roots, self.record_bytes, self.checkpoint) if self.program else []
        bounds=self.view.bounds
        inspected=2*len(rows)
        role_sources=[self.capture['selection']['ranking']['source']]+[item['source'] for item in self.capture['selection']['conditions']]
        inspected+=len(rows)*sum(source['kind']=='builtin' for source in role_sources)
        if plans:
            for plan in plans:
                compiled=plan.to_dict();dates={root['date'] for root in compiled['requests'] if root['mode']=='historical'}
                inspected+=2*len(dates)*(bounds['report_rows']+bounds['population'])
                inspected+=len(compiled['requests'])*(bounds['max_reports']+bounds['max_annual']+8)
                inspected+=4*len(compiled['provider']['contexts'])
        else:
            inspected+=(len(rows)+255)//256*(2*(bounds['report_rows']+bounds['population']) if not latest else 2*256)
        self.budget.reserve(plans,rows,inspected)
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=_LOADED:
            raise definitions.FormulaError('STALE_INPUT_GENERATION','','Loaded scalar execution source changed.')
        policy=selection.policy_fingerprint()
        receipt = dict(policy=dict(executor=_LOADED,selection=policy),id=identity, population='complete-prepared-scope', mode='latest' if latest else 'historical',
            pool=self.pool, date=str(entry), exit=str(exit_day) if exit_day is not None else None,
            prepared_period=period, input=self.view.identity, projection=self.view.projection,
            work=dict(inspected_rows=inspected,cumulative_inspected_rows=self.budget.rows,cumulative_tasks=self.budget.tasks),
            rows=len(rows), digest=hashlib.sha256(definitions.canonical(rows).encode()).hexdigest(),
            source_population=self.view.bounds['population'], provider_admitted=0,
            selection_population='prepared rows with usable return evidence' if not latest else 'prepared exact-session latest rows')
        # Preserve a distinct root-admission count without fabricating return data.
        admitted = 0
        values = [{} for row in rows]; references = [{} for row in rows]
        permitted = [False for row in rows]
        retained = 2*_size(rows)+128*len(rows)+sum(len(plan.document) for plan in plans)
        def charge(value):
            nonlocal retained
            retained += 2*_size(value)+128
            if retained>MAX_METADATA_BYTES:raise definitions.FormulaError('WORK_LIMIT','/execution','Retained scalar lanes exceed their byte ceiling.')
        offset = 0
        for chunk, plan in enumerate(plans):
            self.checkpoint()
            block = reference.evaluate(plan, self.view, self.checkpoint).to_dict()
            block_roots = block['observations']['roots']
            admitted += sum(root['admitted'] for root in block_roots)
            for local,decision in enumerate(block_roots):permitted[offset+local]=decision['admitted']
            self.sink(dict(type='evaluation', value=dict(scope=identity, chunk=chunk, block=block)))
            width = len(plan.to_dict()['requests'])
            for item in block['results']:
                position = offset + item['request']
                key = (item['variable_id'], item['revision'])
                for role, source in enumerate(role_sources):
                    if source['kind'] == 'formula' and (source['variable_id'], source['revision']) == key:
                        lane = 'ranking' if role == 0 else 'c' + str(role - 1)
                        values[position][lane] = item['value'] if item['valid'] else None
                        references[position][lane] = dict(scope=identity, chunk=chunk, request=item['request'],
                            variable_id=item['variable_id'], revision=item['revision'], evidence=item['evidence'],
                            valid=item['valid'], reason=item['reason'])
                        charge(references[position][lane])
            offset += width
        if not plans and roots:
            # Admission is required even when every source is a stored built-in.
            for first in range(0, len(roots), 256):
                group = [dict(id='r' + str(i), **root) for i, root in enumerate(roots[first:first+256])]
                budget = dict(rows=2*(self.view.bounds['report_rows']+self.view.bounds['population']), bytes=16*1024*1024)
                decisions=self.view.admit(group, budget, self.checkpoint)
                admitted += sum(item['admitted'] for item in decisions)
                for local,decision in enumerate(decisions):permitted[first+local]=decision['admitted']
                self.sink(dict(type='admission',value=dict(scope=identity,roots=decisions)))
        receipt['provider_admitted_in_prepared_scope'] = admitted
        receipt.pop('provider_admitted')
        self.sink(dict(type='scope', value=receipt))
        mode = 'latest' if latest else 'historical'; year = 0 if latest else period
        for index, row in enumerate(rows):
            self.checkpoint()
            lanes = []
            for role, source in enumerate(role_sources):
                if source['kind'] != 'builtin':
                    continue
                descriptor = self.descriptors[source['id']]; storage = descriptor['storage']
                if storage['kind'] == 'metric':
                    column = 'yield_value' if storage['component'] == 'yield' else 'multiple'
                    result = db.execute('SELECT ' + column + ' FROM screening_metrics WHERE mode=? AND pool=? AND year=? AND symbol=? AND metric=?',
                        (mode,self.pool,year,row['symbol'],storage['metric'])).fetchone()
                else:
                    result = db.execute('SELECT value FROM filter_values WHERE mode=? AND pool=? AND year=? AND symbol=? AND field=?',
                        (mode,self.pool,year,row['symbol'],storage['field'])).fetchone()
                stored = result[0] if result else None
                canonical = float(Decimal(str(stored)).scaleb(storage['scale'])) if stored is not None else None
                valid = type(stored) in (int,float) and math.isfinite(stored) and canonical is not None and math.isfinite(canonical)
                lane = 'ranking' if role == 0 else 'c' + str(role-1)
                values[index][lane] = stored if valid else None
                refs = dict(scope=identity, symbol=row['symbol'], source=source, stored=stored if valid else None,
                    canonical=canonical if valid else None, unit=descriptor['unit'], valid=valid,
                    reason=None if valid else 'MISSING_INPUT')
                charge(refs)
                references[index][lane] = refs; lanes.append(dict(lane=lane, **refs))
            if lanes:self.sink(dict(type='lanes', value=dict(scope=identity, symbol=row['symbol'], lanes=lanes)))
        for index,allowed in enumerate(permitted):
            if not allowed:values[index]['ranking']=None
        specification = deepcopy(self.capture['selection'])
        conditions = [dict(lane='c'+str(i),op=item['op'],value=item['storage_comparison_value']) for i,item in enumerate(specification['conditions'])]
        bounds = self.capture['bounds']
        for field, op in [('min_cap','ge'),('max_cap','le'),('min_ev','ge'),('sector','eq'),('exchange','eq')]:
            if bounds[field] is not None:
                lane = {'min_cap':'market_cap','max_cap':'market_cap','min_ev':'enterprise_value'}.get(field,field)
                conditions.append(dict(lane=lane,op=op,value=bounds[field]))
        candidates = [dict(symbol=row['symbol'], candidate_rank=row['candidate_rank'],
            values=dict(values[i], **{key:row.get(key) for key in ('market_cap','enterprise_value','sector','exchange')})) for i,row in enumerate(rows)]
        selected = selection.select(candidates, dict(ranking=dict(lane='ranking',direction=specification['ranking']['direction']),
            conditions=conditions, **{key:specification[key] for key in ('rank_from','rank_to','selection_order')}), self.checkpoint)
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
        self.sink(dict(type='selection',value=dict(scope=identity, selected=selected, requested=specification,
            unavailable_ranking=sum(candidate['values'].get('ranking') is None for candidate in candidates))))
        self.view.validate()
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=_LOADED or selection.policy_fingerprint()!=policy:
            raise definitions.FormulaError('STALE_INPUT_GENERATION','','Scalar selection policy changed.')
        return output
