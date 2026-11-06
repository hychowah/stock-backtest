"""Complete prepared scopes to scalar selected books and detached explanations.

Only this adapter combines captured source lanes. The borrowed view
(backtest/inputs/facts.View) owns admission and financial meanings; the column
evaluator (backtest/variables/columns.py) owns formula values and their
explanations. One global scalar selection follows complete evaluation of the
prepared scope. The caller owns the admitted connections and view,
cancellation and the evidence sink.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

from backtest import selection
from backtest.financial import books
from backtest.application import strategy_requests
from backtest.runtime import backtest_control
from backtest.variables import columns, definitions, library

MAX_CANDIDATES = selection.MAX_CANDIDATES
# Encoded-byte bound on the recorded scope metadata that coverage returns.
MAX_METADATA_BYTES = 256 * 1024 * 1024
MAX_SCOPES = 16384
MAX_PREVIEW_BYTES = 16 * 1024 * 1024


def _size(value):
    return len(definitions.canonical(value).encode('ascii'))


def scope_rows(db, *, pool, period=None):
    """Read one complete prepared snapshot scope without metric-availability joins.

    MAX_CANDIDATES bounds the rows; a scope of that size retains a few MB.
    """
    table = 'snapshots' if period is not None else 'latest_snapshots'
    args = [pool]
    where = 's.pool=?'
    if period is not None:
        where += ' AND s.year=?'; args.append(period)
    cursor = db.execute('SELECT s.*,c.name,c.sector,c.exchange,c.symbol AS _company_symbol FROM ' + table +
        ' s LEFT JOIN companies c USING(symbol) WHERE ' + where + ' ORDER BY s.rowid', args)
    names = [item[0] for item in cursor.description]
    rows = []
    for row in cursor:
        backtest_control.checkpoint()
        if len(rows) == MAX_CANDIDATES:
            raise definitions.FormulaError('WORK_LIMIT', '/population', 'Complete pool exceeds the scalar candidate ceiling.')
        detached=dict(zip(names,row))
        if detached.pop('_company_symbol') is None:
            raise definitions.FormulaError('INVALID_SHAPE', '/population', 'Prepared scope has a snapshot without a company.')
        rows.append(detached)
    return rows


def check_preview(capture, roots, *, checkpoint=backtest_control.checkpoint):
    """Check a sample preview before financial ownership; return its program.

    A preview evaluates 1–16 explicit company/date roots and never certifies
    pool coverage.
    """
    checked = strategy_requests.require_strategy(capture, checkpoint=checkpoint)
    if type(roots) is not list or not 1 <= len(roots) <= 16:
        raise definitions.FormulaError('WORK_LIMIT', '/preview', 'Preview needs 1–16 explicit company/date roots.')
    if checked['variables'] is None:
        raise definitions.FormulaError('INVALID_STRATEGY', '/preview', 'A formula preview requires captured formula roots.')
    program = library.VariableCapture(definitions.canonical(checked['variables'])).program
    strategy_requests.require_formula_support(program, checkpoint=checkpoint)
    columns.require_roots(roots)
    columns.Formulas(program).require_contexts(roots)
    return program


def evaluate_preview(program, roots, view, *, checkpoint=backtest_control.checkpoint):
    """Explain explicit checked roots with the column evaluator; no complete-pool claim is made."""
    for index, root in enumerate(roots):
        scope = root.get('owner_scope')
        if scope and scope['kind'] == 'prepared' and not any(
                item['mode'] == root['mode'] and item['pool'] == root['pool'] and item['context_date'] == root['date']
                and item['book'] == scope['book'] for item in view.projection['scopes']):
            raise definitions.FormulaError('INVALID_SHAPE', '/requests/' + str(index) + '/owner_scope',
                                           'Prepared owner scope does not match the admitted projection.')
    block = columns.Formulas(program).explain(roots, view, checkpoint, decisions=view.admit(roots, checkpoint))
    if _size(block) > MAX_PREVIEW_BYTES:
        raise definitions.FormulaError('WORK_LIMIT', '/preview', 'Complete preview exceeds its encoded byte ceiling.')
    return dict(population='explicit-request-scopes', requested=roots, evaluations=[block])


def _scope(db, view, capture, period, entry, *, latest, owner_scope):
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
    rows=scope_rows(db,pool=pool,period=None if latest else period)
    if len({row['symbol'] for row in rows}) != len(rows):
        raise definitions.FormulaError('INVALID_SHAPE','/population','Prepared scope contains duplicate companies.')
    roots=[dict(symbol=row['symbol'],pool=pool,mode='latest' if latest else 'historical',date=str(entry),owner_scope=owner_scope) for row in rows]
    return rows,roots


class Executor:
    """One immutable strategy, borrowed view and bounded output sink per run.

    Formulas are evaluated values-only (variables/columns.py) for the rows that
    can still be selected. With explain, the same evaluator then traces the
    selected rows only: inputs, dates, reasons, source digests and operations.
    Without it (random-date runs), selected rows keep their formula values and
    reasons but no step trace.
    """
    contract = 2
    def __init__(self, capture, view, sink, *, record_bytes=8 * 1024 * 1024,
                 checkpoint=backtest_control.checkpoint, explain=True):
        self.capture = strategy_requests.require_strategy(capture, checkpoint=checkpoint)
        self.pool = self.capture['pool']; self.view = view; self.sink = sink
        self.checkpoint = checkpoint; self.record_bytes = record_bytes
        self.number = 0; self.explain = explain
        self.program = library.VariableCapture(definitions.canonical(self.capture['variables'])).program if self.capture['variables'] else None
        if self.program is not None:
            strategy_requests.require_formula_support(self.program, checkpoint=checkpoint)
        self.formulas = columns.Formulas(self.program) if self.program is not None else None
        self.descriptors = {item['id']: item for item in self.capture['builtins']}

    def _admit(self, rows, roots, entry, owner_scope, dated):
        """Admission decisions in row order.

        Dated scopes apply the view's admission rules (eligible report, legacy buffer,
        cached prices, eligible valuation) and take the entry valuation from the
        book row: compute_period derived it with the same function and prices.
        Other scopes use the view's admission: typed latest admission, and
        complete-population admission for January scopes.
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
        decisions = self.view.admit(roots, self.checkpoint)
        for decision in decisions:
            decision['owner_scope'] = owner_scope
        return decisions

    def select(self, db, period, entry, exit_day=None, *, latest=False, owner_scope=None):
        self.checkpoint()
        if owner_scope is None: owner_scope = dict(kind='dated')
        rows, roots = _scope(db, self.view, self.capture, period, entry, latest=latest, owner_scope=owner_scope)
        self.number += 1; identity = 'scope:' + str(self.number)
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
                                             decisions=[decisions[i] for i in needed])
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
        if formula_roles and chosen and not self.explain:
            # Values and reasons only; the definitions name each lane's unit.
            outputs = {(item['variable_id'], item['revision']): item for item in self.formulas.projection['definitions']}
            for index in chosen:
                for role in formula_roles:
                    source = role_sources[role]; key = (source['variable_id'], source['revision'])
                    value, valid, reason = computed[index][key]
                    references[index][lane_of(role)] = dict(scope=identity, variable_id=key[0], revision=key[1],
                        value=value, valid=valid, reason=reason, unit=outputs[key]['unit'], display=outputs[key]['display'])
        elif formula_roles and chosen:
            # Explain the selected rows with the column evaluator's detail
            # mode. A block larger than one evidence record is split in half.
            def explain(indices):
                self.checkpoint()
                block = self.formulas.explain([roots[i] for i in indices], self.view, self.checkpoint,
                                              decisions=[decisions[i] for i in indices])
                if _size(block) > self.record_bytes - 4096:
                    if len(indices) == 1:
                        raise definitions.FormulaError('WORK_LIMIT', '/execution',
                            'One explained row exceeds the evidence record bound.')
                    yield from explain(indices[:len(indices)//2]); yield from explain(indices[len(indices)//2:])
                    return
                yield indices, block
            for chunk, (group, block) in enumerate(explain(chosen)):
                records.append(dict(type='evaluation', value=dict(scope=identity, chunk=chunk, block=block)))
                for item in block['results']:
                    position = group[item['request']]
                    for role in formula_roles:
                        source = role_sources[role]
                        if (source['variable_id'], source['revision']) != (item['variable_id'], item['revision']):
                            continue
                        references[position][lane_of(role)] = dict(scope=identity, chunk=chunk, request=item['request'],
                            variable_id=item['variable_id'], revision=item['revision'], evidence=item['evidence'],
                            valid=item['valid'], reason=item['reason'])
        records.append(dict(type='scope', value=receipt))
        # Each holding carries its stored lane values; no separate lanes record repeats them.
        for index in chosen:
            for role in stored:
                references[index][lane_of(role)] = builtin(role, rows[index]['symbol'])[1]
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
