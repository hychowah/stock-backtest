"""Plan and evaluate captured formulas through the admitted observation provider.

Requests are ordered company/date roots. Outputs visit requests first, then
the program's ordered roots. Identical requests share work, not output slots.
Tasks share only within an actual context; an explicit date never becomes its
parent merely because both dates agree. Every root, including constants, goes
through provider admission. The caller keeps the borrowed input view alive.

Limits bound counts and retained encoded content, not process RSS. Plans pay
conservative record reservations before observation. The provider owns its row
preflight. Actual evidence is charged before retention and never truncated.
Returned blocks contain every evidence target and retain no input handles.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType

from backtest import observations
from backtest.variables import definitions

VERSION = 1
CEILINGS = MappingProxyType(dict(tasks=65536, outputs=8192,
    plan_bytes=2 * 1024 * 1024, output_bytes=16 * 1024 * 1024,
    retained_bytes=64 * 1024 * 1024))
_LOADED_REFERENCE = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_ARITHMETIC = dict(number='binary64', order='tree-left-before-right',
    mean='first-member; add oldest-to-newest; divide by count',
    extrema='first oldest member wins equal values, including signed zero',
    division='signed nonzero', missing='first unavailable operand; no substitution')


@dataclass(frozen=True)
class EvaluationPlan:
    """Canonical captured inputs and derived work; evaluate() reconstructs it."""
    document: str

    def to_dict(self):
        return json.loads(self.document)

    def to_json(self):
        return self.document


@dataclass(frozen=True)
class EvaluationBlock:
    """Complete detached scalar results, program and resolvable dated evidence."""
    document: str

    def to_dict(self):
        return json.loads(self.document)

    def to_json(self):
        return self.document


def _fail(code, path, message):
    raise definitions.FormulaError(code, path, message)


def _hash(text):
    return 'sha256:' + hashlib.sha256(text.encode('utf-8')).hexdigest()


def _encode(value, maximum, checkpoint=lambda: None):
    """Bound each retained canonical encoding and allow cancellation while writing."""
    chunks, count = [], 0
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'),
                               ensure_ascii=True, allow_nan=False)
    for chunk in encoder.iterencode(value):
        checkpoint()
        count += len(chunk)  # ensure_ascii makes every encoded character one byte.
        if count > maximum:
            _fail('WORK_LIMIT', '/limits', 'Encoded formula evidence exceeds its byte bound.')
        chunks.append(chunk)
    return ''.join(chunks)


def policy_fingerprint():
    """Bind arithmetic and loaded language/provider source, with no library lookup."""
    reference = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    language = definitions.policy_fingerprint()
    if reference != _LOADED_REFERENCE:
        _fail('STALE_INPUT_GENERATION', '', 'Loaded formula policy no longer matches its source.')
    return dict(backend='reference-formulas', version=VERSION, reference=reference,
                definitions=language, provider=observations.policy_fingerprint(),
                arithmetic=dict(_ARITHMETIC))


def _limits(limits):
    if limits is None:
        return dict(CEILINGS)
    if type(limits) is not dict or set(limits) - set(CEILINGS):
        _fail('INVALID_SHAPE', '/limits', 'Unknown evaluator limit.')
    result = dict(CEILINGS)
    for name, value in limits.items():
        if type(value) is not int or not 1 <= value <= CEILINGS[name]:
            _fail('INVALID_SHAPE', '/limits/' + name, 'Evaluator limits can only lower fixed ceilings.')
        result[name] = value
    return result


def _operation(task, node, *, value=None, reason=None, inputs=None):
    item = dict(id=task['id'], node=node['id'], context=task['context'],
                operation=node['op'], path=node['path'], operands=task['operands'],
                inputs=[] if inputs is None else inputs,
                value=value, valid=reason is None, reason=reason)
    if 'observation' in task:
        item['observation'] = task['observation']
    if node['op'] == 'div':
        item['denominator_rule'] = 'signed nonzero'
    return item


def _result(slot, definition, operation):
    return dict(request=slot['request'], root=slot['root'],
                variable_id=definition['variable_id'], revision=definition['revision'],
                unit=definition['unit'], display=definition['display'],
                value=operation['value'], valid=operation['valid'], reason=operation['reason'],
                evidence=dict(operation=slot['task'], admission=slot['root']))


def _compile(program, roots, limits, checkpoint):
    projection = definitions.require_program(program)
    if type(roots) is not list or not roots:
        _fail('INVALID_SHAPE', '/requests', 'An ordered nonempty root request list is required.')
    if len(roots) > limits['outputs'] // len(projection['roots']):
        _fail('WORK_LIMIT', '/requests', 'Requested scalar outputs exceed their count bound.')
    contexts, requests, request_roots, task_list, slots = [], [], [], [], []
    root_ids, context_ids, task_ids, observation_ids = {}, {}, {}, {}
    nodes = {node['id']: node for node in projection['nodes']}

    def add_context(item, path):
        checkpoint()
        # The public provider owns all date arithmetic and immediate-parent rules.
        # Only the new prefix can be invalid, so diagnostics retain formula paths.
        if len(contexts) >= observations.CEILINGS['contexts']:
            _fail('WORK_LIMIT', path, 'Formula contexts exceed the provider ceiling.')
        item['id'] = 'c' + str(len(contexts))
        try:
            observations.plan([], contexts + [item])
        except observations.ObservationError as error:
            raise definitions.FormulaError(error.code, path, str(error)) from None
        contexts.append(item)
        return item['id']

    for index, root in enumerate(roots):
        checkpoint()
        path = '/requests/' + str(index)
        if type(root) is not dict or set(root) != {'symbol', 'pool', 'mode', 'date'}:
            _fail('INVALID_SHAPE', path, 'A root needs symbol, pool, mode and date only.')
        # Check types before hashing, including malformed unhashable fields.
        if any(type(value) is not str for value in root.values()):
            _fail('INVALID_SHAPE', path, 'Root request fields must be strings.')
        key = tuple(root[name] for name in ('symbol', 'pool', 'mode', 'date'))
        if key not in root_ids:
            root_ids[key] = add_context(dict(kind='root', **root), path)
        request_roots.append(root_ids[key])

    def expand(identity, context):
        checkpoint()
        key = identity, context
        if key in task_ids:
            return task_ids[key]
        if len(task_ids) >= limits['tasks']:
            _fail('WORK_LIMIT', '/limits/tasks', 'Formula tasks exceed their count bound.')
        # Reserve the key before descending so the bound includes active parents.
        task_ids[key] = None
        node, operands = nodes[identity], []
        op = node['op']
        observation = None
        if op in ('add', 'sub', 'mul', 'div'):
            operands = [expand(node[field], context) for field in ('left', 'right')]
        elif op in ('neg', 'ref'):
            operands = [expand(node['target'] if op == 'ref' else node['arg'], context)]
        elif op in ('at', 'lookback'):
            field = 'date' if op == 'at' else 'months'
            context_key = context, op, node[field]
            if context_key not in context_ids:
                context_ids[context_key] = add_context(
                    dict(kind=op, parent=context, **{field: node[field]}), node['path'] + '/' + field)
            operands = [expand(node['arg'], context_ids[context_key])]
        elif op in ('parameter', 'annual'):
            observation_key = context, node['parameter'], node['count']
            if observation_key not in observation_ids:
                observation = 'o' + str(len(requests))
                observation_ids[observation_key] = observation
                requests.append(dict(id=observation, parameter=node['parameter'],
                                     context=context, count=node['count']))
                if len(requests) > observations.CEILINGS['requests']:
                    _fail('WORK_LIMIT', '/limits', 'Formula observations exceed the provider ceiling.')
            observation = observation_ids[observation_key]
        task = dict(id='t' + str(len(task_list)), node=identity, context=context, operands=operands)
        if observation is not None:
            task['observation'] = observation
        task_list.append(task)
        task_ids[key] = task['id']
        return task['id']

    for index, context in enumerate(request_roots):
        for definition_index in projection['roots']:
            task = expand(projection['definitions'][definition_index]['root'], context)
            slots.append(dict(request=index, root=context, definition=definition_index, task=task))
    provider_plan = observations.plan(requests, contexts).to_dict()
    result = dict(format='formula-evaluation-plan', version=VERSION, program=projection,
                  requests=roots, limits=limits, request_roots=request_roots,
                  tasks=task_list, outputs=slots, provider=provider_plan)
    # A string of 24 characters encodes longer than any finite binary64 value.
    # Known reasons are shorter than this 64-character reservation. Runtime
    # charging still rejects any future provider growth rather than truncating.
    worst_value, worst_reason = '-' * 24, '-' * 64
    operation_bytes = 2
    for task in task_list:
        node = nodes[task['node']]
        count = node.get('count', len(task['operands']))
        record = _operation(task, node, value=worst_value, reason=worst_reason,
                            inputs=[worst_value] * count)
        operation_bytes += len(definitions.canonical(record)) + 1
    output_bytes = 2
    for slot in slots:
        record = _result(slot, projection['definitions'][slot['definition']],
                         dict(value=worst_value, valid=False, reason=worst_reason))
        output_bytes += len(definitions.canonical(record)) + 1
    # Reserve bounded identity/projection metadata before inputs are inspected.
    # The full trusted projection is charged again at runtime.
    skeleton = dict(format='formula-evaluation', version=VERSION, program=projection,
        requests=roots, plan_revision='sha256:' + '0' * 64,
        calculation_identity='sha256:' + '0' * 64, identity={},
        observations={}, operations=[], results=[])
    envelope_bytes = len(definitions.canonical(skeleton)) + 8192
    plan_reservation = len(definitions.canonical(result)) + 1024
    output_remaining = limits['output_bytes'] - envelope_bytes - operation_bytes - output_bytes
    # Retained records and their final encoding coexist. Provider JSON and its
    # decoded graph are charged separately, plus its copy in final encoding.
    retained_base = (plan_reservation + len(program.document) + envelope_bytes
                     + 2 * operation_bytes + 2 * output_bytes)
    retained_remaining = (limits['retained_bytes'] - retained_base) // 3
    provider_bytes = min(observations.CEILINGS['bytes'], output_remaining, retained_remaining)
    if provider_bytes < 1:
        _fail('WORK_LIMIT', '/limits', 'Formula evidence reservations exceed their byte bounds.')
    try:
        result['provider'] = observations.plan(requests, contexts, dict(bytes=provider_bytes)).to_dict()
    except observations.ObservationError as error:
        raise definitions.FormulaError(error.code, '/limits', str(error)) from None
    result['reservations'] = dict(operations=operation_bytes, results=output_bytes,
        envelope=envelope_bytes, plan=plan_reservation, provider_bytes=provider_bytes)
    return _encode(result, limits['plan_bytes'], checkpoint)


def plan(program, roots, limits=None):
    """Bind a checked program to ordered roots without touching financial inputs.

    Fixed ceilings can only be lowered. Provider generation-dependent row work
    remains observe()'s responsibility. Explicit dates apply to the whole subtree,
    including references, and must be valid for every enclosing requested root.
    """
    return EvaluationPlan(_compile(program, roots, _limits(limits), lambda: None))


def require_plan(evaluation_plan, checkpoint=lambda: None):
    """Rebuild every task, context and reservation before an input view is touched."""
    if type(evaluation_plan) is not EvaluationPlan or type(evaluation_plan.document) is not str:
        _fail('INVALID_SHAPE', '', 'A checked immutable evaluation plan is required.')
    if len(evaluation_plan.document) > CEILINGS['plan_bytes']:
        _fail('WORK_LIMIT', '/limits/plan_bytes', 'Evaluation plan exceeds its byte ceiling.')
    try:
        submitted = evaluation_plan.to_dict()
    except (TypeError, ValueError, RecursionError):
        _fail('INVALID_SHAPE', '', 'Evaluation plan is malformed.')
    if type(submitted) is not dict or set(submitted) != {
            'format', 'version', 'program', 'requests', 'limits', 'request_roots',
            'tasks', 'outputs', 'provider', 'reservations'}:
        _fail('INVALID_SHAPE', '', 'Evaluation plan fields do not match its format.')
    try:
        program_document = definitions.canonical(submitted['program'])
    except (TypeError, ValueError, RecursionError):
        _fail('INVALID_SHAPE', '/program', 'Captured formula program is malformed.')
    program = definitions.FormulaProgram(program_document)
    rebuilt = _compile(program, submitted['requests'], _limits(submitted['limits']), checkpoint)
    if rebuilt != evaluation_plan.document:
        _fail('INVALID_SHAPE', '', 'Evaluation plan is not its canonical checked projection.')
    return submitted


def evaluate(evaluation_plan, inputs, checkpoint=lambda: None):
    """Return a complete detached block or fail without publishing partial results.

    Annual mean starts with the oldest member, adds later members in order, then
    divides. Min/max retain the oldest equal member, including its zero sign.
    Binary operations inspect left then right; all missing inputs propagate.
    No financial input, admission decision or built-in denominator is recreated.
    """
    checked = require_plan(evaluation_plan, checkpoint)
    limits, projection = checked['limits'], checked['program']
    checkpoint()
    policy = policy_fingerprint()
    inputs.validate()
    generation, input_projection = inputs.identity, inputs.projection
    provider = observations.observe(observations.ObservationPlan(
        definitions.canonical(checked['provider'])), inputs, checkpoint)
    observed = provider.to_dict()
    if (observed['generation'] != generation or observed['projection'] != input_projection['content']
            or observed['provider_policy'] != policy['provider']):
        _fail('STALE_INPUT_GENERATION', '', 'Observation identity changed during formula evaluation.')
    identity = dict(plan=_hash(evaluation_plan.document), bundle=projection['bundle_revision'],
                    policy=policy, generation=generation, projection=input_projection)
    calculation_identity = _hash(definitions.canonical(identity))
    block = dict(format='formula-evaluation', version=VERSION, program=projection,
        requests=checked['requests'], plan_revision=identity['plan'],
        calculation_identity=calculation_identity, identity=identity,
        observations=observed, operations=[], results=[])
    # Charge captured plan, captured program and both provider representations.
    retained = len(evaluation_plan.document) + len(definitions.canonical(projection)) + 2 * len(provider.document)
    if retained > limits['retained_bytes']:
        _fail('WORK_LIMIT', '/limits/retained_bytes', 'Captured formula inputs exceed their byte bound.')
    used = len(_encode(block, limits['output_bytes'], checkpoint))
    nodes = {node['id']: node for node in projection['nodes']}
    roots = {root['root']: root for root in observed['roots']}
    contexts = {context['id']: context for context in observed['contexts']}
    observations_by_id = {item['id']: item for item in observed['results']}
    operations = {}

    def retain(record, field):
        nonlocal retained, used
        encoded = _encode(record, limits['output_bytes'], checkpoint)
        charged = len(encoded) + int(bool(block[field]))
        if used + charged > limits['output_bytes']:
            _fail('WORK_LIMIT', '/limits/output_bytes', 'Formula result exceeds its byte bound.')
        if retained + len(encoded) > limits['retained_bytes']:
            _fail('WORK_LIMIT', '/limits/retained_bytes', 'Formula records exceed their byte bound.')
        retained += len(encoded)
        used += charged
        block[field].append(record)

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
            elif values[1] == 0:
                reason = 'ZERO_DENOMINATOR'
            else:
                value = values[0] / values[1]
        if value is not None and not math.isfinite(value):
            value, reason = None, 'NONFINITE_RESULT'
        record = _operation(task, node, value=value, reason=reason, inputs=values)
        retain(record, 'operations')
        operations[task['id']] = record
    for slot in checked['outputs']:
        checkpoint()
        retain(_result(slot, projection['definitions'][slot['definition']], operations[slot['task']]), 'results')

    def current():
        checkpoint()
        inputs.validate()
        if (inputs.identity != generation or inputs.projection != input_projection
                or policy_fingerprint() != policy):
            _fail('STALE_INPUT_GENERATION', '', 'Formula inputs or policy changed during evaluation.')

    current()
    available = min(limits['output_bytes'], limits['retained_bytes'] - retained)
    if available < 1:
        _fail('WORK_LIMIT', '/limits/retained_bytes', 'Final formula encoding exceeds its retained byte bound.')
    document = _encode(block, available, checkpoint)
    # Encoding itself calls user checkpoints. Revalidate after its final one.
    current()
    return EvaluationBlock(document)
