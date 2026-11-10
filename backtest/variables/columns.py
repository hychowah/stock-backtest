"""Formula evaluation over typed prepared facts: values only, or explained.

Formulas.evaluate returns one (value, valid, reason) per root and output for
complete prepared scopes; it builds no evidence, so one scope of thousands of
rows evaluates in milliseconds. Formulas.explain returns the
detached evaluation block of a few roots, with every input, date, reason,
source digest and operation, in the shape website/browser/variable-evidence.js
reads. Both run the same code, so an explanation shows the values that ranked
a stock. The evaluator implements the whole language: every program that
definitions.require_program (the one formula gate) returns.

Observation rules: legacy catalogs retain strict fiscal-plus-90 availability;
the market-aware catalog uses prepared publication/fallback metadata. The
current anchor is the financial-policy report at most 800 days old.
One income fiscal spine selects annual periods before any endpoint join;
other endpoints join those exact dates. Price and volume use the stock's own
saved row at the selected market's session on or before the context, within
seven days. Treasury uses the latest saved day on or before a US context,
strictly before an Asian context, and divides provider percent by 100.
A stored-book root (a prepared scope's row, whose
decision names its book, or a latest root) reads its book's stored owner
lanes; other roots and derived contexts use dated owner policy. Arithmetic is
binary64 in tree order; mean adds oldest first; min/max keep the oldest equal member;
growth and CAGR need a positive first (and, for CAGR, last) member; the first
unavailable operand's reason wins; a nonfinite result is unavailable.

The borrowed view (backtest/inputs/fact_view.View) owns admission, entry
valuation and the typed facts; it reads each company or day once.
"""
import calendar
from datetime import date
import hashlib
import math
from pathlib import Path

from backtest import measure_observations
from backtest.financial import metrics, rules
from backtest.inputs.facts import TREASURY
from backtest.variables import definitions, parameters

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _fail(code, path, message):
    raise definitions.FormulaError(code, path, message)


_MEANINGS = {item['id']: item for item in parameters.catalog(parameters.V3)}
# Preserve /1 presentation and order; every direct annual source comes from
# the versioned semantic owner.
_CATALOG = {
    'annual.revenue': ('USD', 'Selected annual revenue'),
    'annual.operating_income': ('USD', 'Selected annual operating income'),
    'annual.operating_margin': ('scalar', 'Operating income / positive revenue'),
    'market.enterprise_value': ('USD', 'Existing dated enterprise value'),
}
_ANNUAL = {key: item['source'] for key, item in _MEANINGS.items()
           if item['kind'] == 'direct' and key.startswith('annual.')}
_DATED = {key: item['source'] for key, item in _MEANINGS.items()
          if item['kind'] == 'direct' and not key.startswith('annual.')}
_CATALOG['annual.report_ebitda'] = ('USD', 'Accepted report-derived EBITDA')
for _key, _item in _MEANINGS.items():
    if _key.startswith('owner.'):
        _CATALOG[_key] = (_item['unit'], _item['description'])
for _key in (*_ANNUAL, *_DATED):
    _CATALOG.setdefault(_key, (_MEANINGS[_key]['unit'], _MEANINGS[_key]['description']))


def catalog():
    """The observed parameters: 57 direct inputs and the adapters; a listing proves no coverage."""
    return [dict(id=key, unit=value[0], description=value[1],
                 counts=dict(minimum=1, maximum=10 if key.startswith('annual.') else 1),
                 contexts=['root', 'at', 'lookback']) for key, value in _CATALOG.items()]


_SYMBOL_CHARACTERS = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789^._-')


def require_roots(roots):
    """Check explicit company/date roots before any input is read: exactly symbol, pool, mode and date.

    A request names no book; only a prepared scope's rows carry an owner scope
    (scalar_execution._scope).
    """
    if type(roots) is not list or not roots:
        _fail('INVALID_SHAPE', '/requests', 'An ordered nonempty root request list is required.')
    for index, root in enumerate(roots):
        path = '/requests/' + str(index)
        if type(root) is not dict or set(root) != {'symbol', 'pool', 'mode', 'date'}:
            _fail('INVALID_SHAPE', path, 'A root needs exactly symbol, pool, mode and date.')
        if any(type(root[name]) is not str for name in ('symbol', 'pool', 'mode', 'date')):
            _fail('INVALID_SHAPE', path, 'Root request fields must be strings.')
        if (not 1 <= len(root['symbol']) <= 64 or not set(root['symbol']) <= _SYMBOL_CHARACTERS
                or root['pool'] not in ('cached', 'legacy') or root['mode'] not in ('historical', 'latest')):
            _fail('INVALID_SHAPE', path, 'Invalid root company, pool or mode.')
        try:
            valid = str(date.fromisoformat(root['date'])) == root['date']
        except ValueError:
            valid = False
        if not valid:
            _fail('INVALID_DATE', path + '/date', 'An ISO calendar date is required.')
    return roots


def _subtract(day, months):
    """day minus whole calendar months, month ends clamped; None before year 1."""
    total = day.year * 12 + day.month - 1 - months
    year, month = divmod(total, 12)
    if year < 1:
        return None
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def _anchor(facts, day):
    rows = facts['reports']
    anchor = rules.latest_statement(rows, day)
    reason = None if anchor else ('STALE_REPORT' if any(row['known'] < day for row in rows)
                                 else 'NO_ELIGIBLE_REPORT')
    return anchor, reason


def _periods(facts, anchor, day, count, checkpoint):
    """Select the income fiscal spine once, independently of requested fields.

    The current period is the financial-policy anchor. Earlier periods keep
    the latest eligible income date in each year, even if its fields are absent.
    Other endpoints join these exact dates and cannot supply replacement periods.
    """
    periods = []
    income = facts['annual'].get('income-statement', {})
    for year in range(anchor['fiscal'].year - count + 1, anchor['fiscal'].year + 1):
        checkpoint()
        if year == anchor['fiscal'].year:
            fiscal = str(anchor['fiscal'])
        else:
            choices = [text for text in income if date.fromisoformat(text).year == year
                       and date.fromisoformat(text) <= anchor['fiscal']
                       and date.fromisoformat((facts.get('metadata', {}).get('income-statement', {}).get(text) or {}).get(
                           'known', str(date.fromisoformat(text) + rules.LAG))) < day]
            fiscal = max(choices, default=None)
        periods.append((year, fiscal))
    return periods


def _annual(parameter, facts, periods, checkpoint, detail):
    """One member per period; detail adds each member's evidence (source, field states, known date)."""
    members = []
    source = _ANNUAL.get(parameter)
    endpoint = source['endpoint'] if source else 'income-statement'
    fields = (source['field'],) if source else ('operatingIncome', 'revenue')
    for year, fiscal in periods:
        checkpoint()
        row = facts['annual'].get(endpoint, {}).get(fiscal) if fiscal else None
        reason, value = None, None
        for field in fields:
            state = row.get(field) if row else None
            if reason is None and (state is None or not state['valid']):
                reason = state['reason'] if state else ('MISSING_FISCAL_YEAR' if fiscal is None else 'MISSING_INPUT')
        if reason is None:
            if parameter == 'annual.operating_margin':
                value = metrics.operating_margin(row['operatingIncome']['value'], row['revenue']['value'])
                if value is None:
                    reason = 'NONPOSITIVE_DENOMINATOR'
            else:
                value = row[fields[0]]['value']
            if value is not None and not math.isfinite(value):
                value, reason = None, 'NONFINITE_RESULT'
        member = dict(value=value, valid=reason is None, reason=reason, fiscal_date=fiscal, fiscal_year=year)
        if detail:
            metadata = facts.get('metadata', {}).get(endpoint, {}).get(fiscal) or {}
            member['evidence'] = dict(source=facts['sources'].get(endpoint),
                fields={field: row.get(field) if row else None for field in fields},
                known_date=metadata.get('known', str(date.fromisoformat(fiscal) + rules.LAG) if fiscal else None),
                availability_model=metadata.get('basis', 'fiscal-plus-90-strict; saved statements are not filing vintages'))
        members.append(member)
    return members


def _report_ebitda(reports, anchor, count, checkpoint, detail, day):
    # The anchor remains the pool-selected report. Earlier values come from the
    # broad accepted report spine, without requiring statement endpoint rows.
    by_year = {}
    for row in reports:
        checkpoint()
        if row['fiscal'] <= anchor['fiscal'] and row['known'] < day:
            by_year[row['fiscal'].year] = row
    by_year[anchor['fiscal'].year] = anchor
    result = []
    for year in range(anchor['fiscal'].year - count + 1, anchor['fiscal'].year + 1):
        checkpoint()
        row = by_year.get(year)
        value = row.get('ebitda') if row else None
        reason = 'MISSING_FISCAL_YEAR' if row is None else 'MISSING_INPUT' if value is None else None
        if value is not None and not math.isfinite(value):
            value, reason = None, 'NONFINITE_RESULT'
        member = dict(value=value, valid=reason is None, reason=reason,
                      fiscal_date=str(row['fiscal']) if row else None, fiscal_year=year)
        if detail:
            member['evidence'] = dict(policy='accepted-report-ebitda', report={
                key: str(v) if isinstance(v, date) else v for key, v in row.items()} if row else None)
        result.append(member)
    return result


def _slim(evidence):
    """Keep values, dates, reasons, the source file and its digest; drop raw row positions and row hashes."""
    if not isinstance(evidence, dict):
        return evidence
    slim = {key: evidence[key] for key in ('known_date', 'availability_model', 'lookup_policy', 'lookups',
                                           'session', 'field', 'conversion', 'policy', 'source', 'key',
                                           'stored', 'reason') if key in evidence}
    if isinstance(slim.get('source'), dict):
        slim['source'] = {key: slim['source'][key] for key in ('endpoint', 'sha256', 'disposition') if key in slim['source']}
    if 'stored' in slim:
        slim['stored'] = measure_observations.detached(slim['stored'])
    state_keys = ('value', 'valid', 'reason', 'source_currency', 'source_value', 'fx_date', 'fx_rate')
    if 'fields' in evidence:
        slim['fields'] = {name: None if state is None else {key: state[key] for key in state_keys if key in state}
                          for name, state in evidence['fields'].items()}
    if 'state' in evidence:
        state = evidence['state']
        slim['state'] = None if state is None else {key: state[key] for key in state_keys if key in state}
    if 'report' in evidence:
        slim['report'] = _dates(evidence['report'])
    return slim


def _dates(report):
    if report is None:
        return None
    result = {key: str(report[key]) for key in ('fiscal', 'known')}
    result.update({key: report[key] for key in ('currency', 'quote_currency', 'availability_basis',
                  'fx_date', 'quote_fx_date', 'fx_rate') if key in report})
    return result


class _Trace:
    """One explained chunk in the block shape that the evidence viewer reads.

    Root contexts come first, one per distinct root, then derived contexts,
    observations and operations in evaluation order.
    """

    def __init__(self):
        self.contexts, self.roots, self.observations, self.operations, self.results = [], [], [], [], []

    def root(self, root, decision):
        identity = 'c' + str(len(self.contexts))
        context = dict(id=identity, root=identity, date=root['date'])
        if 'owner_scope' in root:
            context['owner_scope'] = root['owner_scope']
        self.contexts.append(context)
        admission = {key: decision.get(key) for key in ('symbol', 'pool', 'mode', 'date', 'admitted', 'reason',
                                                         'candidate_rank', 'valuation')}
        if 'owner_scope' in root:
            admission['owner_scope'] = root['owner_scope']
        self.roots.append(dict(root=identity, **admission))
        return identity

    def context(self, root, day):
        identity = 'c' + str(len(self.contexts))
        self.contexts.append(dict(id=identity, root=root, date=day))
        return identity


class Formulas:
    """One checked program, evaluated values-only over ordered roots, or explained in detail.

    projection is the checked program content that the language check
    (definitions.require_program) returned when its capture was restored.
    """

    def __init__(self, projection):
        self.projection = projection
        self.nodes = {node['id']: node for node in self.projection['nodes']}
        self.outputs = [self.projection['definitions'][index] for index in self.projection['roots']]
        self.by_id = {(item['variable_id'], item['revision']): item for item in self.outputs}
        # Annual fields each company needs, unioned over the program.
        self.requirements = {}
        for node in self.projection['nodes']:
            if node['op'] in ('parameter', 'annual'):
                source = _ANNUAL.get(node['parameter'])
                if source:
                    self.requirements.setdefault(source['endpoint'], set()).add(source['field'])
                elif node['parameter'] == 'annual.operating_margin':
                    self.requirements.setdefault('income-statement', set()).update(('operatingIncome', 'revenue'))

    def evaluate(self, roots, view, checkpoint, *, decisions, outputs=None):
        """Return one {(variable_id, revision): (value, valid, reason)} per root.

        decisions are the roots' admission decisions in order (view.admit, or
        the stored rows of a prepared scope). outputs optionally names the
        needed exact formula identities; their shared dependencies run once
        within each row. The checked program and its evidence stay complete.
        """
        selected = self.outputs if outputs is None else [self.by_id[key] for key in outputs]
        return [self._root(root, decision, view, checkpoint, outputs=selected)
                for root, decision in zip(roots, decisions)]

    def require_contexts(self, roots):
        """Resolve every dated context of the roots before any input is read.

        A context after its parent date fails FUTURE_DATE; a lookback before
        year 1 fails INVALID_DATE; nesting deeper than 32 fails WORK_LIMIT.
        """
        for root in roots:
            state = dict(contexts={('root',): dict(id='root', root='root', date=root['date'])})
            seen = set()

            def visit(identity, context, depth):
                if (identity, context) in seen:
                    return
                seen.add((identity, context))
                node = self.nodes[identity]
                if node['op'] in ('add', 'sub', 'mul', 'div', 'positive_div'):
                    visit(node['left'], context, depth); visit(node['right'], context, depth)
                elif node['op'] in ('neg', 'ref'):
                    visit(node['target'] if node['op'] == 'ref' else node['arg'], context, depth)
                elif node['op'] in ('at', 'lookback'):
                    visit(node['arg'], self._context(context, node, state, depth + 1), depth + 1)
            for definition in self.outputs:
                visit(definition['root'], ('root',), 1)

    def explain(self, roots, view, checkpoint, *, decisions):
        """Return one detached evaluation block that explains the roots.

        The block has the shape website/browser/variable-evidence.js reads:
        requests, program, observations (roots, contexts, results with members,
        dates, reasons and source digests), operations and results. Its values
        are the values-only evaluator's, computed by the same code.
        """
        trace, states = _Trace(), {}
        for root, decision in zip(roots, decisions):
            key = definitions.canonical(root)
            if key not in states:
                states[key] = dict(id=trace.root(root, decision))
        for index, (root, decision) in enumerate(zip(roots, decisions)):
            entry = states[definitions.canonical(root)]
            if 'state' not in entry:
                entry['state'] = self._root(root, decision, view, checkpoint, trace=trace, identity=entry['id'])[1]
            state = entry['state']
            for definition in self.outputs:
                task = state['ids'][definition['root'], ('root',)]
                value, reason = state['tasks'][definition['root'], ('root',)]
                trace.results.append(dict(request=index, root=entry['id'], variable_id=definition['variable_id'],
                    revision=definition['revision'], unit=definition['unit'], display=definition['display'],
                    value=value, valid=reason is None, reason=reason, evidence=dict(operation=task, admission=entry['id'])))
        identity = dict(evaluator='columns', policy=policy_fingerprint(), bundle=self.projection['bundle_revision'],
                        generation=view.identity, projection=view.projection['content'])
        return dict(format='formula-evaluation', version=1, program=self.projection, requests=list(roots),
                    identity=identity, observations=dict(format='parameter-observations', version=1,
                        generation=view.identity, projection=view.projection['content'], roots=trace.roots,
                        contexts=trace.contexts, results=trace.observations),
                    operations=trace.operations, results=trace.results)

    def _root(self, root, decision, view, checkpoint, *, trace=None, identity=None, outputs=None):
        checkpoint()
        state = dict(tasks={}, observations={}, contexts={('root',): dict(id='root', root='root', date=root['date'])},
                     anchors={})
        if trace is not None:
            state.update(trace=trace, root=identity, ids={}, context_ids={('root',): identity}, observation_ids={})
        result = {}
        for definition in self.outputs if outputs is None else outputs:
            outcome = self._task(definition['root'], ('root',), 1, root, decision, view, state, checkpoint)
            result[(definition['variable_id'], definition['revision'])] = (outcome[0], outcome[1] is None, outcome[1])
        return (result, state) if trace is not None else result

    def _context(self, parent, node, state, depth):
        field = 'date' if node['op'] == 'at' else 'months'
        key = parent + ((node['op'], node[field]),)
        if key not in state['contexts']:
            if depth > 32:
                _fail('WORK_LIMIT', node['path'] + '/' + field, 'Observation context depth exceeds its bound.')
            parent_context = state['contexts'][parent]
            parent_day = date.fromisoformat(parent_context['date'])
            day = date.fromisoformat(node['date']) if node['op'] == 'at' else _subtract(parent_day, node['months'])
            if day is None:
                _fail('INVALID_DATE', node['path'] + '/' + field, 'Lookback exceeds the supported calendar.')
            if day > parent_day:
                _fail('FUTURE_DATE', node['path'] + '/' + field, 'An observation date exceeds its parent date.')
            state['contexts'][key] = dict(id=key, root='root', date=str(day))
            if 'trace' in state:
                state['context_ids'][key] = state['trace'].context(state['root'], str(day))
        return key

    def _task(self, identity, context, depth, root, decision, view, state, checkpoint):
        """Return (value, reason) of one task; see the module rules for arithmetic."""
        key = identity, context
        if key in state['tasks']:
            return state['tasks'][key]
        node = self.nodes[identity]
        op = node['op']
        keys = []
        if op in ('add', 'sub', 'mul', 'div', 'positive_div'):
            keys = [(node[side], context, depth) for side in ('left', 'right')]
        elif op in ('neg', 'ref'):
            keys = [(node['target'] if op == 'ref' else node['arg'], context, depth)]
        elif op in ('at', 'lookback'):
            keys = [(node['arg'], self._context(context, node, state, depth + 1), depth + 1)]
        operands = [self._task(*item, root, decision, view, state, checkpoint) for item in keys]
        values = [item[0] for item in operands]
        reason = next((item[1] for item in operands if item[1] is not None), None)
        value = None
        if not decision['admitted']:
            reason = 'ROOT_NOT_ADMITTED'
        elif op in ('parameter', 'annual'):
            members, reason = self._observation(node, context, root, decision, view, state, checkpoint)
            values = [float(member['value']) if member['valid'] else None for member in members]
            if reason is None:
                value = values[0]
                if op == 'annual':
                    if node['stat'] in ('growth', 'cagr'):
                        if values[0] <= 0:
                            value, reason = None, 'NONPOSITIVE_DENOMINATOR'
                        elif node['stat'] == 'cagr' and values[-1] <= 0:
                            value, reason = None, 'NONPOSITIVE_ENDPOINT'
                        else:
                            ratio = values[-1] / values[0]
                            value = (ratio if node['stat'] == 'growth' else ratio ** (1 / (len(values) - 1))) - 1
                    else:
                        for member in values[1:]:
                            if node['stat'] == 'mean':
                                value = value + member
                            elif node['stat'] == 'min':
                                if member < value:
                                    value = member
                            elif member > value:
                                value = member
                        if node['stat'] == 'mean':
                            value = value / len(values)
        elif reason is None:
            if op == 'constant':
                value = float(node['value'])
            elif op in ('ref', 'at', 'lookback'):
                value = values[0]
            elif op == 'neg':
                value = -values[0]
            elif op == 'add':
                value = values[0] + values[1]
            elif op == 'sub':
                value = values[0] - values[1]
            elif op == 'mul':
                value = values[0] * values[1]
            elif op == 'positive_div' and values[1] <= 0:
                reason = 'NONPOSITIVE_DENOMINATOR'
            elif values[1] == 0:
                reason = 'ZERO_DENOMINATOR'
            else:
                value = values[0] / values[1]
        if value is not None and not math.isfinite(value):
            value, reason = None, 'NONFINITE_RESULT'
        state['tasks'][key] = value, reason
        if 'trace' in state:
            self._operation(key, node, [state['ids'][item[:2]] for item in keys], values, value, reason,
                            root, decision, state)
        return value, reason

    @staticmethod
    def _operation(key, node, operands, values, value, reason, root, decision, state):
        """Record one operation as the evaluation block lists it."""
        trace = state['trace']
        identity = state['ids'][key] = 't' + str(len(trace.operations))
        item = dict(id=identity, node=node['id'], context=state['context_ids'][key[1]], operation=node['op'],
                    path=node['path'], operands=operands, inputs=values, value=value, valid=reason is None, reason=reason)
        if node['op'] in ('parameter', 'annual'):
            observation = (key[1], node['parameter'], node['count'])
            if observation not in state['observation_ids']:
                # An unadmitted root observes nothing; its request still has a record.
                state['observation_ids'][observation] = 'o' + str(len(trace.observations))
                trace.observations.append(dict(id=state['observation_ids'][observation], parameter=node['parameter'],
                    context=item['context'], root=state['root'], unit=_CATALOG[node['parameter']][0],
                    anchor=None, anchor_report=None, candidate_rank=decision['candidate_rank'], members=[],
                    valid=False, reason='ROOT_NOT_ADMITTED'))
            item['observation'] = state['observation_ids'][observation]
        if node['op'] == 'div':
            item['denominator_rule'] = 'signed nonzero'
        elif node['op'] == 'positive_div':
            item['denominator_rule'] = 'positive'
        trace.operations.append(item)

    def _observation(self, node, context_key, root, decision, view, state, checkpoint):
        """Return (members, reason) of one observation: a parameter at one context."""
        key = context_key, node['parameter'], node['count']
        if key in state['observations']:
            return state['observations'][key]
        context = state['contexts'][context_key]
        parameter = node['parameter']
        day = date.fromisoformat(context['date'])
        is_root = context_key == ('root',)
        detail = 'trace' in state
        members, reason, anchor = [], None, None
        if parameter in _DATED:
            members = [self._dated(parameter, root['symbol'], day, view, detail)]
        elif parameter.startswith('owner.') and measure_observations.prepared_scope(decision, context):
            owner = state.setdefault('owner', {})
            if context_key not in owner:
                checkpoint()
                owner[context_key] = view.prepared(decision)
            members = [measure_observations.lane(owner[context_key], parameter.split('.', 1)[1])]
            if detail:
                # The stored row's report is the root's anchor (books.Screen.decide chose it).
                if context_key not in state['anchors']:
                    state['anchors'][context_key] = _anchor(view.company(root['symbol'], root['pool'], self.requirements, day), day)
                anchor = state['anchors'][context_key][0]
        elif parameter == 'market.enterprise_value' and is_root:
            members = [dict(value=decision['valuation']['enterprise_value'], valid=True, reason=None)]
            if detail:
                # The root's statement and admission evidence; a dated book row
                # repeats the entry valuation lookups that admitted it.
                statement = decision.get('statement')
                if statement is None:
                    anchor = _anchor(view.company(root['symbol'], root['pool'], self.requirements, day), day)[0]
                else:
                    anchor = dict(fiscal=date.fromisoformat(statement['fiscal']), known=date.fromisoformat(statement['known']))
                evidence = decision.get('admission_evidence')
                if evidence is None and statement is None:
                    evidence = view.entry(root['symbol'], anchor, day)[1]
                elif evidence is None:
                    evidence = dict(reason=decision['reason'])
                members[0].update(fiscal_date=str(anchor['fiscal']), fiscal_year=anchor['fiscal'].year,
                                  evidence=evidence)
        else:
            company = view.company(root['symbol'], root['pool'], self.requirements, day)
            if context_key not in state['anchors']:
                state['anchors'][context_key] = _anchor(company, day)
            anchor, reason = state['anchors'][context_key]
            if anchor is not None:
                if parameter == 'annual.report_ebitda':
                    members = _report_ebitda(view.reports(root['symbol'], 'cached', day), anchor,
                                             node['count'], checkpoint, detail, day)
                elif parameter.startswith('owner.'):
                    owner = state.setdefault('owner', {})
                    if context_key not in owner:
                        owner[context_key] = measure_observations.dated(view, decision, context, anchor, checkpoint)
                    members = [measure_observations.lane(owner[context_key], parameter.split('.', 1)[1])]
                elif parameter.startswith('annual.'):
                    periods = _periods(company, anchor, day, node['count'], checkpoint)
                    members = _annual(parameter, company, periods, checkpoint, detail)
                else:
                    valuation, evidence = view.entry(root['symbol'], anchor, day)
                    members = [dict(value=valuation['enterprise_value'] if valuation else None,
                                    valid=valuation is not None, reason=evidence['reason'])]
                    if detail:
                        members[0].update(fiscal_date=str(anchor['fiscal']), fiscal_year=anchor['fiscal'].year,
                                          evidence=evidence)
        if detail and parameter.startswith('owner.') and members:
            members[0].update(fiscal_date=None if anchor is None else str(anchor['fiscal']),
                              fiscal_year=None if anchor is None else anchor['fiscal'].year)
        if members:
            reason = next((member['reason'] for member in members if not member['valid']), None)
        elif reason is None:
            reason = 'ROOT_NOT_ADMITTED' if not decision['admitted'] else None
        state['observations'][key] = members, reason
        if detail:
            trace = state['trace']
            state['observation_ids'][key] = 'o' + str(len(trace.observations))
            trace.observations.append(dict(id=state['observation_ids'][key], parameter=parameter,
                context=state['context_ids'][context_key], root=state['root'], unit=_CATALOG[parameter][0],
                anchor=None if anchor is None else str(anchor['fiscal']), anchor_report=_dates(anchor),
                candidate_rank=decision['candidate_rank'],
                members=[dict(member, evidence=_slim(member.get('evidence'))) for member in members],
                valid=bool(members) and reason is None, reason=reason))
        return members, reason

    @staticmethod
    def _dated(parameter, symbol, day, view, detail=False):
        source = _DATED[parameter]
        endpoint, field = source['endpoint'], source['field']
        treasury = endpoint == TREASURY
        session = None
        if treasury:
            row = view.treasury(day)
            observed = row[0] if row else None
            state = row[1].get(field) if row else None
            reason = state['reason'] if state else 'MISSING_INPUT'
        else:
            session = view.session(day)
            observed = session
            row = view.stock(symbol, date.fromisoformat(session)) if session else None
            state = row.get(field) if row else None
            reason = state['reason'] if state else 'MISSING_INPUT' if session else 'MISSING_SESSION'
        value = state['value'] if state and state['valid'] else None
        if value is not None and treasury:
            value /= 100
        member = dict(value=value, valid=reason is None, reason=reason)
        if detail:
            member.update(fiscal_date=None, fiscal_year=None, observation_date=observed, evidence=dict(
                source=view.source('' if treasury else symbol, endpoint),
                session=None if session is None else dict(day=session), field=field, state=state,
                lookup_policy='latest-source-date' if treasury else
                    'exact-own-stock-at-backward-local-session-within-seven-days' if view.market != 'us' else
                    'exact-own-stock-at-backward-spy-session-within-seven-days',
                conversion='provider-percent-divided-by-100' if treasury else
                    'observation-date-quote-currency-to-usd' if view.market != 'us' and field == 'adjClose' else 'identity'))
        return member


def policy_fingerprint():
    """Identify the loaded column evaluator and its observation policy."""
    return _LOADED
