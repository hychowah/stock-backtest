"""Correctness-authority Python arithmetic over shared checked formula work.

Public plans and detached blocks retain their existing interface. Shared mechanics
own context planning, provider access, limits and evidence. This independent
interpreter owns binary64 tree order, oldest-first annual folds, signed division
and first-unavailable-operand precedence. Growth and CAGR require every member,
then a positive first value (NONPOSITIVE_DENOMINATOR). CAGR also requires a
positive last value (NONPOSITIVE_ENDPOINT). Nonfinite arithmetic is unavailable
as NONFINITE_RESULT. These version 2 operations are reference-only; scalar and
application admission are separate. It imports no numerical packages.
"""
import hashlib
import math
from pathlib import Path

from backtest import observations
from backtest.variables import definitions, evaluation
from backtest.variables.evaluation import VERSION, CEILINGS, EvaluationPlan, EvaluationBlock, plan, require_plan

_LOADED_REFERENCE = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def policy_fingerprint():
    """Bind independent arithmetic and shared loaded language/provider mechanics."""
    current = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if current != _LOADED_REFERENCE:
        raise definitions.FormulaError('STALE_INPUT_GENERATION', '', 'Loaded formula policy no longer matches its source.')
    return dict(backend='reference-formulas', version=VERSION, reference=current,
                evaluation=evaluation.policy_fingerprint(), definitions=definitions.policy_fingerprint(),
                provider=observations.policy_fingerprint(), arithmetic=dict(evaluation._ARITHMETIC))


def require_program(program, *, checkpoint=lambda: None):
    """Admit implemented direct-reference semantics before touching inputs.

    Application and scalar selection qualification belongs to selection.
    Semantic restoration remains independent of both execution policies.
    """
    checkpoint()
    checked = definitions.require_program(program)
    supported = {item['id'] for item in observations.catalog()}
    operations = {'constant', 'parameter', 'annual', 'ref', 'at', 'lookback',
                  'neg', 'add', 'sub', 'mul', 'div', 'positive_div'}
    for node in checked['nodes']:
        checkpoint()
        if node['op'] not in operations or (node['op'] == 'annual' and
                node['stat'] not in ('mean', 'min', 'max', 'growth', 'cagr')):
            raise definitions.FormulaError('UNSUPPORTED_CAPABILITY', node['path'],
                'Unsupported direct-reference operation.')
        if node['op'] in ('parameter', 'annual') and node['parameter'] not in supported:
            raise definitions.FormulaError('UNSUPPORTED_CAPABILITY', node['path'],
                'Unsupported direct-reference observation parameter.')
    return checked


class _Arithmetic:
    workspace_bytes = 0
    policy_fingerprint = staticmethod(policy_fingerprint)

    def prepare(self, checked, checkpoint):
        require_program(definitions.FormulaProgram(definitions.canonical(checked['program'])),
                        checkpoint=checkpoint)
        return self

    def close(self):
        pass

    def operations(self, checked, observed, checkpoint):
        nodes = {node['id']: node for node in checked['program']['nodes']}
        roots = {root['root']: root for root in observed['roots']}
        contexts = {context['id']: context for context in observed['contexts']}
        observations_by_id = {item['id']: item for item in observed['results']}
        operations = {}
        for task in checked['tasks']:
            checkpoint()
            node = nodes[task['node']]
            op = node['op']
            operands = [operations[identity] for identity in task['operands']]
            values = [item['value'] for item in operands]
            reason = next((item['reason'] for item in operands if not item['valid']), None)
            value = None
            root = roots[contexts[task['context']]['root']]
            if not root['admitted']:
                reason = 'ROOT_NOT_ADMITTED'
            elif op in ('parameter', 'annual'):
                observation = observations_by_id[task['observation']]
                values = [float(member['value']) if member['valid'] else None
                          for member in observation['members']]
                reason = observation['reason']
                if observation['valid']:
                    value = values[0]
                    if op == 'annual':
                        if node['stat'] in ('growth', 'cagr'):
                            # Provider validity covers every consecutive member before
                            # endpoint rules. Results are canonical scalar fractions.
                            if values[0] <= 0:
                                value, reason = None, 'NONPOSITIVE_DENOMINATOR'
                            elif node['stat'] == 'cagr' and values[-1] <= 0:
                                value, reason = None, 'NONPOSITIVE_ENDPOINT'
                            else:
                                ratio = values[-1] / values[0]
                                value = (ratio if node['stat'] == 'growth' else
                                         ratio ** (1 / (len(values) - 1))) - 1
                        else:
                            for member in values[1:]:
                                checkpoint()
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
            operations[task['id']] = dict(value=value, valid=reason is None, reason=reason)
            yield value, reason, values


def evaluate(evaluation_plan, inputs, checkpoint=lambda: None):
    """Return complete original arithmetic and provider evidence, or fail."""
    return evaluation.evaluate(evaluation_plan, inputs, _Arithmetic(), checkpoint)
