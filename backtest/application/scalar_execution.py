"""Complete prepared scopes to scalar selected books and detached explanations.

Only this adapter combines captured source lanes. The borrowed view
(backtest/inputs/fact_view.View) owns financial meanings and the admission of
explicit preview roots; the column evaluator (backtest/variables/columns.py)
owns formula values and their explanations. One global scalar selection
follows complete evaluation of the prepared scope. A prepared scope is one
complete pool of a stored book, named by its book id and checked once by
book_store.require_scope. A stored row is its root's admission: books.book
stored only the companies that books.Screen.decide admitted, with their
candidate rank and entry valuation. The caller owns the admitted connection
and view, cancellation and the evidence sink.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import math
from pathlib import Path

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

from backtest import selection
from backtest.inputs import book_store
from backtest.application import strategy_requests
from backtest.runtime import backtest_control
from backtest.variables import columns, definitions

MAX_CANDIDATES = selection.MAX_CANDIDATES
MAX_PREVIEW_BYTES = 16 * 1024 * 1024


def _size(value):
    return len(definitions.canonical(value).encode('ascii'))


def check_preview(checked, roots):
    """Check a sample preview of a restored strategy before financial ownership; return its program projection.

    checked is the strategy that strategy_requests.check_options restored. A
    preview evaluates 1–16 explicit company/date roots and never certifies
    pool coverage.
    """
    if type(roots) is not list or not 1 <= len(roots) <= 16:
        raise definitions.FormulaError('WORK_LIMIT', '/preview', 'Preview needs 1–16 explicit company/date roots.')
    if checked['variables'] is None:
        raise definitions.FormulaError('INVALID_STRATEGY', '/preview', 'A formula preview requires captured formula roots.')
    projection = checked['variables']['program']
    columns.require_roots(roots)
    columns.Formulas(projection).require_contexts(roots)
    return projection


def evaluate_preview(projection, roots, view, *, checkpoint=backtest_control.checkpoint):
    """Explain explicit checked roots with the column evaluator; no complete-pool claim is made.

    A request names no book: a book id is a handle (book_store). The view
    admits each root (books.Screen.decide); a latest root, on the latest date,
    reads the open book's stored owner lanes.
    """
    block = columns.Formulas(projection).explain(roots, view, checkpoint, decisions=view.admit(roots, checkpoint))
    if _size(block) > MAX_PREVIEW_BYTES:
        raise definitions.FormulaError('WORK_LIMIT', '/preview', 'Complete preview exceeds its encoded byte ceiling.')
    return dict(population='explicit-request-scopes', requested=roots, evaluations=[block])


def _scope(db, capture, book, entry, *, latest):
    """Return one complete prepared scope's rows and the admission of row i, after the scope's one check.

    The scope is one complete pool of the stored book (book_store.require_scope);
    a latest scope names the open book. Its rows are the selection fields of
    every stored row (book_store.scope), in symbol order; MAX_CANDIDATES bounds
    them. admission(i) is (root, decision): the root carries the prepared owner
    scope of that book, whose stored lanes the owner parameters read, and the
    decision admits the stored row with its candidate rank and entry
    valuation. A latest decision also names its report, as the open book's
    screen chose it.
    """
    pool = capture['pool']
    try:
        book_store.require_scope(db, book, pool, entry, latest)
    except ValueError:
        raise definitions.FormulaError('INVALID_SHAPE', '/owner_scope', 'Prepared owner scope does not match the admitted projection.') from None
    owner_scope = dict(kind='prepared', book=book)
    mode, day = 'latest' if latest else 'historical', str(entry)
    try:
        rows = book_store.scope(db, book, pool, MAX_CANDIDATES + 1)
    except ValueError:
        raise definitions.FormulaError('INVALID_SHAPE', '/population', 'Prepared scope has a snapshot without a company.') from None
    if len(rows) > MAX_CANDIDATES:
        raise definitions.FormulaError('WORK_LIMIT', '/population', 'Complete pool exceeds the scalar candidate ceiling.')

    def admission(i):
        symbol, candidate_rank, fiscal, known, market_cap, enterprise_value, ebitda, _, _ = rows[i]
        decision = dict(root='r' + str(i), symbol=symbol, pool=pool, mode=mode, date=day, admitted=True, reason=None,
                        candidate_rank=candidate_rank, owner_scope=owner_scope,
                        valuation=dict(market_cap=market_cap, enterprise_value=enterprise_value, ebitda=ebitda))
        if latest:
            decision['statement'] = dict(fiscal=fiscal, known=known)
        return dict(symbol=symbol, pool=pool, mode=mode, date=day, owner_scope=owner_scope), decision
    return rows, admission


def _canonical(value, scale):
    """A stored lane value in canonical units, or None when it is not a valid input.

    A valid input is a finite number that stays finite in canonical units.
    scale is the decimal exponent from the stored lane to canonical units.
    """
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    canonical = float(Decimal(str(value)).scaleb(scale)) if scale else float(value)
    return canonical if math.isfinite(canonical) else None


class Executor:
    """One immutable strategy, borrowed view and bounded output sink per run.

    Formulas are evaluated values-only (variables/columns.py) for the rows that
    can still be selected. With explain, the same evaluator then traces the
    selected rows only: inputs, dates, reasons, source digests and operations.
    Without it (random-date runs), selected rows keep their formula values and
    reasons but no step trace. Stored lanes build their evidence for the
    selected rows only.
    """
    contract = 2
    def __init__(self, capture, view, sink, *, record_bytes=8 * 1024 * 1024,
                 checkpoint=backtest_control.checkpoint, explain=True):
        # The execution boundary of a queued row: restore it with the current code.
        self.capture = strategy_requests.require_strategy(capture, checkpoint=checkpoint)
        self.pool = self.capture['pool']; self.view = view; self.sink = sink
        self.checkpoint = checkpoint; self.record_bytes = record_bytes
        self.number = 0; self.explain = explain
        # The restore checked the program; its projection is the evaluator's input.
        variables = self.capture['variables']
        self.formulas = columns.Formulas(variables['program']) if variables is not None else None
        self.descriptors = {item['id']: item for item in self.capture['builtins']}

    def select(self, db, book, entry, exit_day=None, *, latest=False):
        """Select one complete prepared scope: the pool of the stored book named by its id (the open book when latest)."""
        self.checkpoint()
        rows, admission = _scope(db, self.capture, book, entry, latest=latest)
        self.number += 1; identity = 'scope:' + str(self.number)
        specification = deepcopy(self.capture['selection'])
        role_sources=[specification['ranking']['source']]+[item['source'] for item in specification['conditions']]
        lane_of = lambda role: 'ranking' if role == 0 else 'c' + str(role - 1)
        mode = 'latest' if latest else 'historical'
        receipt = dict(policy=dict(executor=_LOADED,selection=selection.policy_fingerprint()),id=identity,
            population='complete-prepared-scope', mode=mode, pool=self.pool, date=str(entry),
            exit=str(exit_day) if exit_day is not None else None, prepared_period=None if latest else book,
            input=self.view.identity, rows=len(rows), source_population=self.view.bounds['population'],
            # A recorded receipt field: a stored row is admitted, so it equals rows by construction.
            provider_admitted_in_prepared_scope=len(rows),
            selection_population='prepared rows with usable return evidence' if not latest else 'prepared exact-session latest rows')
        # One read per stored table for the whole scope (book_store.lanes), one
        # {symbol: value} map per lane; primary keys make each value unique.
        stored = {}
        metrics = {role: self.descriptors[source['id']]['storage'] for role, source in enumerate(role_sources)
                   if source['kind'] == 'builtin' and self.descriptors[source['id']]['storage']['kind'] == 'metric'}
        fields = {role: self.descriptors[source['id']]['storage'] for role, source in enumerate(role_sources)
                  if source['kind'] == 'builtin' and self.descriptors[source['id']]['storage']['kind'] != 'metric'}
        pairs, filters = book_store.lanes(db, book, self.pool, [storage['metric'] for storage in metrics.values()],
                                          [storage['field'] for storage in fields.values()])
        for role, storage in metrics.items():
            stored[role] = pairs[storage['metric']][1 if storage['component'] == 'yield' else 0]
        for role, storage in fields.items():
            stored[role] = filters[storage['field']]
        scales = {role: self.descriptors[role_sources[role]['id']]['storage']['scale'] for role in stored}
        # Selection compares stored values. A finite value cannot overflow at a
        # scale of 0 or below, so the row check converts only at a positive scale.
        usable = {lane_of(role): {symbol: value if _canonical(value, max(scales[role], 0)) is not None else None
                                  for symbol, value in found.items()} for role, found in stored.items()}
        def builtin(role, symbol):
            """The evidence of one stored lane of a selected row."""
            source = role_sources[role]; descriptor = self.descriptors[source['id']]
            value = stored[role].get(symbol)
            canonical = _canonical(value, scales[role]); valid = canonical is not None
            return dict(scope=identity, symbol=symbol, source=source, stored=value if valid else None,
                canonical=canonical, unit=descriptor['unit'], valid=valid,
                reason=None if valid else 'MISSING_INPUT')
        # Each row's lanes: its usable stored values and the bound fields.
        values = []
        for symbol, _, _, _, market_cap, enterprise_value, _, sector, exchange in rows:
            item = {lane: found.get(symbol) for lane, found in usable.items()}
            item.update(market_cap=market_cap, enterprise_value=enterprise_value, sector=sector, exchange=exchange)
            values.append(item)
        conditions = [dict(lane='c'+str(i),op=item['op'],value=item['storage_comparison_value']) for i,item in enumerate(specification['conditions'])]
        bounds = self.capture['bounds']
        for field, op in [('min_cap','ge'),('max_cap','le'),('min_ev','ge'),('sector','eq'),('exchange','eq')]:
            if bounds[field] is not None:
                lane = {'min_cap':'market_cap','max_cap':'market_cap','min_ev':'enterprise_value'}.get(field,field)
                conditions.append(dict(lane=lane,op=op,value=bounds[field]))
        formula_roles = [role for role, source in enumerate(role_sources) if source['kind'] == 'formula']
        # With a stored ranking and filter-first order, a row that has no
        # ranking value or fails a stored condition can never be selected.
        # The stored conditions are checked here, once per row; formulas and
        # the selection see only the remaining rows, with the formula conditions.
        needed = list(range(len(rows)))
        if role_sources[0]['kind'] == 'builtin' and specification['selection_order'] == 'filter_first':
            formula_lanes = {lane_of(role) for role in formula_roles}
            stored_conditions = [item for item in conditions if item['lane'] not in formula_lanes]
            conditions = [item for item in conditions if item['lane'] in formula_lanes]
            needed = []
            for i, item in enumerate(values):
                self.checkpoint()
                if selection.finite(item.get('ranking')) is not None and selection.passes(item, stored_conditions):
                    needed.append(i)
        if formula_roles:
            roots, decisions = zip(*map(admission, needed)) if needed else ((), ())
            outputs = self.formulas.evaluate(list(roots), self.view, self.checkpoint, decisions=list(decisions))
            computed = dict(zip(needed, outputs))
            for i, output in computed.items():
                for role in formula_roles:
                    source = role_sources[role]
                    value, valid, reason = output[(source['variable_id'], source['revision'])]
                    values[i][lane_of(role)] = value if valid else None
        candidates = [dict(symbol=rows[i][0], candidate_rank=rows[i][1], values=values[i]) for i in needed]
        selected = selection.select(candidates, dict(ranking=dict(lane='ranking',direction=specification['ranking']['direction']),
            conditions=conditions, **{key:specification[key] for key in ('rank_from','rank_to','selection_order')}), self.checkpoint)
        # The recorded indexes address the scope's rows.
        for item in selected['selected']:
            item['index'] = needed[item['index']]
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
                roots, decisions = zip(*map(admission, indices))
                block = self.formulas.explain(list(roots), self.view, self.checkpoint, decisions=list(decisions))
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
                references[index][lane_of(role)] = builtin(role, rows[index][0])
        # Full rows (book_store.rows) for the selected rows only.
        full = {row['symbol']: row for row in book_store.rows(db, book, self.pool, [rows[index][0] for index in chosen])}
        output = []
        ranking_source = specification['ranking']['source']
        if ranking_source['kind'] == 'builtin':
            descriptor = self.descriptors[ranking_source['id']]
        else:
            descriptor = next(item for item in self.capture['variables']['program']['definitions'] if item['variable_id']==ranking_source['variable_id'] and item['revision']==ranking_source['revision'])
        for item in selected['selected']:
            index = item['index']; original = full[rows[index][0]]
            value = item['value']
            if ranking_source['kind']=='builtin':value=_canonical(value,descriptor['storage']['scale'])
            output.append(dict(original, rank=item['rank'], ranking_value=value, ranking_unit=descriptor['unit'],
                ranking_display=descriptor['display'], ranking_direction=specification['ranking']['direction'],
                scalar_evidence=dict(scope=identity, lanes=references[index])))
        records.append(dict(type='selection',value=dict(scope=identity, selected=selected, requested=specification,
            unavailable_ranking=sum(item.get('ranking') is None for item in values))))
        for record in records:
            self.checkpoint()
            self.sink(record)
        self.view.validate()
        return output
