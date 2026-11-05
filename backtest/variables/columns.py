"""Values-only formula evaluation for scalar scopes.

The meaning is the reference evaluator's (variables/reference.py over
observations.observe): the same anchor, annual spine, annual member, report
EBITDA, dated lookup and owner-measure rules, and the same binary64 arithmetic.
It builds no plan document and keeps no per-candidate evidence, so one scope of
thousands of rows evaluates in milliseconds. Explanations of selected rows still
come from the reference evaluator, which also cross-checks these values.

A Facts object reads the typed prepared facts (backtest/inputs/facts.py) on the
operation's research connection and caches them for one borrowed view. The
view still owns historical admission, entry valuation and dated owner measures.
Neither database can change while the view is open.
"""
from datetime import date
import math

from backtest import measure_observations, observations
from backtest.inputs import dated_observation_inputs as dated_inputs, facts as typed
from backtest.variables import definitions

_OWNER_BYTES = 16 * 1024 * 1024


def _fail(code, path, message):
    raise definitions.FormulaError(code, path, message)


class Facts:
    """Typed prepared facts of one borrowed view, read once per company or day."""

    def __init__(self, view, research):
        self.view, self.db = view, research
        self.projection = view.projection
        self._books = {(scope['mode'], scope['pool'], scope['context_date']): scope['book']
                       for scope in self.projection['scopes']}
        self._companies, self._reports, self._sessions, self._stock, self._treasury = {}, {}, {}, {}, {}

    def reports(self, symbol, pool):
        key = symbol, pool
        if key not in self._reports:
            self._reports[key] = typed.reports(self.db, symbol, pool)
        return self._reports[key]

    def company(self, symbol, pool, requirements):
        """Return observe()'s company facts: reports and requested annual states.

        Income-statement dates always form the fiscal spine when any annual field
        is required, as in ReadView._projected_company.
        """
        key = symbol, pool
        cached = self._companies.get(key)
        if cached is None:
            cached = self._companies[key] = dict(reports=self.reports(symbol, pool), annual={}, sources={}, loaded={})
        annual, loaded = cached['annual'], cached['loaded']
        wanted = dict(requirements)
        if wanted:
            wanted.setdefault('income-statement', set())
        for endpoint, fields in wanted.items():
            missing = sorted(set(fields) - loaded.get(endpoint, set())) if endpoint in loaded else sorted(fields)
            if endpoint in loaded and not missing:
                continue
            states = annual.setdefault(endpoint, {})
            for fiscal, values in typed.annual(self.db, symbol, endpoint, missing).items():
                states.setdefault(fiscal, {}).update(values)
            loaded.setdefault(endpoint, set()).update(missing)
        return cached

    def session(self, day):
        if day not in self._sessions:
            self._sessions[day] = typed.session(self.db, day, 7)
        return self._sessions[day]

    def stock(self, symbol, day):
        key = symbol, day
        if key not in self._stock:
            self._stock[key] = typed.stock_day(self.db, symbol, day)
        return self._stock[key]

    def treasury(self, day):
        if day not in self._treasury:
            self._treasury[day] = typed.treasury(self.db, day)
        return self._treasury[day]

    def prepared(self, decision, context):
        """Owner values of the stored book row in a prepared scope, as measure_observations.prepared."""
        owner = decision.get('owner_scope')
        book = owner['book'] if owner is not None else self._books[decision['mode'], decision['pool'], context['date']]
        lanes = typed.prepared_lanes(self.db, decision['mode'], decision['pool'], book, decision['symbol'])
        if lanes is None:
            return dict(reason='PREPARED_MEASURE_CONTEXT_UNAVAILABLE', evidence=None)
        return dict(reason=None, evidence=lanes)

    def admit(self, roots, checkpoint):
        """Admission decisions in root order, as ReadView.admit gives them.

        Latest roots read the typed latest admission. Historical roots use the
        view's complete-population admission, 256 roots per call.
        """
        self.view.validate()
        decisions = [None] * len(roots)
        historical = [(index, root) for index, root in enumerate(roots) if root['mode'] == 'historical']
        bounds = self.view.bounds
        for first in range(0, len(historical), 256):
            group = historical[first:first + 256]
            budget = dict(rows=2 * (bounds['report_rows'] + bounds['population']), bytes=16 * 1024 * 1024)
            requests = [dict(id='r' + str(index), **root) for index, root in group]
            for (index, _), decision in zip(group, self.view.admit(requests, budget, checkpoint)):
                decisions[index] = decision
        for index, root in enumerate(roots):
            if root['mode'] == 'historical':
                continue
            checkpoint()
            if root['mode'] != 'latest' or root['date'] != self.projection['latest_date']:
                raise ValueError('Latest observation root does not match prepared admission.')
            decision = dict(root='r' + str(index), symbol=root['symbol'], pool=root['pool'], mode='latest',
                            date=root['date'], admitted=False, reason=None, candidate_rank=None,
                            statement=None, valuation=None)
            row = typed.latest_admission(self.db, root['symbol'], root['pool'])
            if row is None:
                if self.db.execute('SELECT 1 FROM companies WHERE symbol=?', (root['symbol'],)).fetchone():
                    raise ValueError('Prepared latest-root admission is missing.')
                decision['reason'] = 'UNKNOWN_COMPANY'
            else:
                decision.update(row)
            decisions[index] = decision
        return decisions


class Formulas:
    """One checked program, evaluated values-only over ordered roots."""

    def __init__(self, program):
        self.projection = definitions.require_program(program)
        self.nodes = {node['id']: node for node in self.projection['nodes']}
        self.outputs = [self.projection['definitions'][index] for index in self.projection['roots']]
        # Annual fields each company needs, as observe() unions them per root.
        self.requirements = {}
        for node in self.projection['nodes']:
            if node['op'] in ('parameter', 'annual'):
                source = observations._ANNUAL.get(node['parameter'])
                if source:
                    self.requirements.setdefault(source['endpoint'], set()).add(source['field'])
                elif node['parameter'] == 'annual.operating_margin':
                    self.requirements.setdefault('income-statement', set()).update(('operatingIncome', 'revenue'))

    def evaluate(self, roots, view, checkpoint, *, decisions, facts):
        """Return one {(variable_id, revision): (value, valid, reason)} per root.

        decisions are the roots' admission decisions in order. facts caches the
        view's decoded company facts across calls.
        """
        return [self._root(root, decision, view, facts, checkpoint) for root, decision in zip(roots, decisions)]

    def _root(self, root, decision, view, facts, checkpoint):
        checkpoint()
        decision = dict(decision, owner_scope=root['owner_scope']) if 'owner_scope' in root else decision
        root_context = dict(id='root', root='root', date=root['date'])
        if 'owner_scope' in root:
            root_context['owner_scope'] = root['owner_scope']
        state = dict(tasks={}, observations={}, contexts={('root',): root_context}, anchors={})
        result = {}
        for definition in self.outputs:
            outcome = self._task(definition['root'], ('root',), 1, root, decision, view, facts, state, checkpoint)
            result[(definition['variable_id'], definition['revision'])] = (outcome[0], outcome[1] is None, outcome[1])
        return result

    def _context(self, parent, node, state, depth):
        field = 'date' if node['op'] == 'at' else 'months'
        key = parent + ((node['op'], node[field]),)
        if key not in state['contexts']:
            if depth > 32:
                _fail('WORK_LIMIT', node['path'] + '/' + field, 'Observation context depth exceeds its bound.')
            parent_context = state['contexts'][parent]
            parent_day = date.fromisoformat(parent_context['date'])
            try:
                day = (date.fromisoformat(node['date']) if node['op'] == 'at'
                       else observations._subtract(parent_day, node['months']))
            except observations.ObservationError as error:
                raise definitions.FormulaError(error.code, node['path'] + '/' + field, str(error)) from None
            if day > parent_day:
                _fail('FUTURE_DATE', node['path'] + '/' + field, 'An observation date exceeds its parent date.')
            state['contexts'][key] = dict(id=key, root='root', date=str(day))
        return key

    def _task(self, identity, context, depth, root, decision, view, facts, state, checkpoint):
        """Return (value, reason) with reference._Arithmetic's rules."""
        key = identity, context
        if key in state['tasks']:
            return state['tasks'][key]
        node = self.nodes[identity]
        op = node['op']
        operands = []
        if op in ('add', 'sub', 'mul', 'div', 'positive_div'):
            operands = [self._task(node[side], context, depth, root, decision, view, facts, state, checkpoint)
                        for side in ('left', 'right')]
        elif op in ('neg', 'ref'):
            operands = [self._task(node['target'] if op == 'ref' else node['arg'], context, depth,
                                   root, decision, view, facts, state, checkpoint)]
        elif op in ('at', 'lookback'):
            child = self._context(context, node, state, depth + 1)
            operands = [self._task(node['arg'], child, depth + 1, root, decision, view, facts, state, checkpoint)]
        values = [item[0] for item in operands]
        reason = next((item[1] for item in operands if item[1] is not None), None)
        value = None
        if not decision['admitted']:
            reason = 'ROOT_NOT_ADMITTED'
        elif op in ('parameter', 'annual'):
            members, reason = self._observation(node, context, root, decision, view, facts, state, checkpoint)
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
        return value, reason

    def _observation(self, node, context_key, root, decision, view, facts, state, checkpoint):
        """Return (members, reason) as observe() reports one request."""
        key = context_key, node['parameter'], node['count']
        if key in state['observations']:
            return state['observations'][key]
        context = state['contexts'][context_key]
        parameter = node['parameter']
        day = date.fromisoformat(context['date'])
        is_root = context_key == ('root',)
        members, reason = [], None
        if parameter in observations._DATED:
            members = [self._dated(parameter, root['symbol'], day, facts)]
        elif parameter.startswith('owner.') and measure_observations.prepared_scope(facts.projection, decision, context):
            owner = state.setdefault('owner', {})
            if context_key not in owner:
                checkpoint()
                owner[context_key] = facts.prepared(decision, context)
            members = [measure_observations.lane(owner[context_key], parameter.split('.', 1)[1], checkpoint)]
        elif parameter == 'market.enterprise_value' and is_root:
            members = [dict(value=decision['valuation']['enterprise_value'], valid=True, reason=None)]
        else:
            company = facts.company(root['symbol'], root['pool'], self.requirements)
            if context_key not in state['anchors']:
                state['anchors'][context_key] = observations._anchor(company, day)
            anchor, reason = state['anchors'][context_key]
            if anchor is not None:
                if parameter == 'annual.report_ebitda':
                    members = observations._report_ebitda(facts.reports(root['symbol'], 'cached'), anchor,
                                                          node['count'], checkpoint)
                elif parameter.startswith('owner.'):
                    owner = state.setdefault('owner', {})
                    if context_key not in owner:
                        owner[context_key] = measure_observations.dated(view, decision, context, anchor, checkpoint,
                                                                        budget=_OWNER_BYTES)
                    members = [measure_observations.lane(owner[context_key], parameter.split('.', 1)[1], checkpoint)]
                elif parameter.startswith('annual.'):
                    periods = observations._periods(company, anchor, day, node['count'], checkpoint)
                    members = observations._annual(parameter, company, periods, checkpoint)
                else:
                    valuation, evidence = view.entry(root['symbol'], anchor, day)
                    members = [dict(value=valuation['enterprise_value'] if valuation else None,
                                    valid=valuation is not None, reason=evidence['reason'])]
        if members:
            reason = next((member['reason'] for member in members if not member['valid']), None)
        elif reason is None:
            reason = 'ROOT_NOT_ADMITTED' if not decision['admitted'] else None
        state['observations'][key] = members, reason
        return members, reason

    @staticmethod
    def _dated(parameter, symbol, day, facts):
        source = observations._DATED[parameter]
        endpoint, field = source['endpoint'], source['field']
        treasury = endpoint == dated_inputs.TREASURY
        if treasury:
            row = facts.treasury(day)
            state = row[1].get(field) if row else None
            reason = state['reason'] if state else 'MISSING_INPUT'
        else:
            session = facts.session(day)
            row = facts.stock(symbol, date.fromisoformat(session)) if session else None
            state = row.get(field) if row else None
            reason = state['reason'] if state else 'MISSING_INPUT' if session else 'MISSING_SESSION'
        value = state['value'] if state and state['valid'] else None
        if value is not None and treasury:
            value /= 100
        return dict(value=value, valid=reason is None, reason=reason)
