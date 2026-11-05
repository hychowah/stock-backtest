"""Checked formula work and complete detached evidence, without arithmetic.

Requests keep ordered root/output slots while identical contexts share tasks.
The provider owns admission, report choice, annual alignment and dated EV. The
caller keeps its borrowed view and outer ownership alive until evaluation ends.

An arithmetic owner prepares bounded resources before any input access. It yields
one recorded outcome per checked task. This owner assembles those outcomes; it
never recomputes their values. Limits bound counts and encoded retained content,
plus explicitly reserved native buffers. They do not claim a process RSS bound.
Every complete block receives final source/input checks after encoding.
"""
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

from backtest import observations
from backtest.variables import definitions

VERSION = 1
CEILINGS = MappingProxyType(dict(tasks=65536, outputs=8192,
    plan_bytes=2 * 1024 * 1024, output_bytes=16 * 1024 * 1024,
    retained_bytes=64 * 1024 * 1024))
_LOADED_EVALUATION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_ARITHMETIC = dict(number='binary64', order='tree-left-before-right',
    mean='first-member; add oldest-to-newest; divide by count',
    extrema='first oldest member wins equal values, including signed zero',
    division='signed nonzero', missing='first unavailable operand; no substitution')


@dataclass(frozen=True)
class EvaluationPlan:
    """Canonical captured inputs and derived work.

    plan() marks the plans it compiles; evaluate() reconstructs any other plan
    before trusting it.
    """
    document: str
    compiled: bool = field(default=False, compare=False, repr=False)

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
    """Bound each retained canonical encoding; check cancellation before writing.

    The C encoder writes the same bytes as the incremental one, several times
    faster. The value is already in memory, so encoding it whole adds no risk.
    """
    checkpoint()
    text = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    if len(text) > maximum:  # ensure_ascii makes every encoded character one byte.
        _fail('WORK_LIMIT', '/limits', 'Encoded formula evidence exceeds its byte bound.')
    return text


def policy_fingerprint():
    """Identify the loaded shared planning and evidence policy."""
    return _LOADED_EVALUATION


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
    elif node['op'] == 'positive_div':
        item['denominator_rule'] = 'positive'
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
        if type(root) is not dict or set(root) not in ({'symbol', 'pool', 'mode', 'date'}, {'symbol', 'pool', 'mode', 'date', 'owner_scope'}):
            _fail('INVALID_SHAPE', path, 'A root needs symbol, pool, mode, date and optional owner scope.')
        # Check types before hashing, including malformed unhashable fields.
        if any(type(root[name]) is not str for name in ('symbol', 'pool', 'mode', 'date')):
            _fail('INVALID_SHAPE', path, 'Root request fields must be strings.')
        # Canonical encoding distinguishes explicitly directed roots from legacy
        # roots, and from each other, even when their dates are equal.
        try:
            key = definitions.canonical(root)
        except (TypeError, ValueError, RecursionError):
            _fail('INVALID_SHAPE', path, 'Invalid root owner scope.')
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
        if op in ('add', 'sub', 'mul', 'div', 'positive_div'):
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
    return EvaluationPlan(_compile(program, roots, _limits(limits), lambda: None), compiled=True)


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
    if evaluation_plan.compiled:
        # plan() built this document in this process from a checked program.
        return submitted
    try:
        program_document = definitions.canonical(submitted['program'])
    except (TypeError, ValueError, RecursionError):
        _fail('INVALID_SHAPE', '/program', 'Captured formula program is malformed.')
    program = definitions.FormulaProgram(program_document)
    rebuilt = _compile(program, submitted['requests'], _limits(submitted['limits']), checkpoint)
    if rebuilt != evaluation_plan.document:
        _fail('INVALID_SHAPE', '', 'Evaluation plan is not its canonical checked projection.')
    return submitted



def evaluate(evaluation_plan, inputs, arithmetic, checkpoint=lambda: None):
    """Prepare arithmetic, observe once and retain complete original outcomes.

    prepare() and its resource preflight run before inputs.validate(). The
    returned execution owns no view. close() releases only its own resources.
    Encoded provider evidence may have a lower byte allowance to pay for native
    buffers inside the same authoritative retained_bytes ceiling.
    """
    checked = require_plan(evaluation_plan, checkpoint)
    checkpoint()
    execution = arithmetic.prepare(checked, checkpoint)
    try:
        return _evaluate(evaluation_plan, checked, inputs, execution,
                         arithmetic.policy_fingerprint, checkpoint)
    finally:
        execution.close()


def workspace_limit(checked):
    """Conservative room for arithmetic before observing any provider rows."""
    reserved = checked['reservations']
    base = (reserved['plan'] + len(definitions.canonical(checked['program']))
            + reserved['envelope'] + 2 * reserved['operations'] + 2 * reserved['results'])
    return checked['limits']['retained_bytes'] - base - 3


def _evaluate(evaluation_plan, checked, inputs, execution, fingerprint, checkpoint):
    limits, projection = checked['limits'], checked['program']
    workspace = execution.workspace_bytes
    if type(workspace) is not int or not 0 <= workspace <= workspace_limit(checked):
        _fail('WORK_LIMIT', '/limits/retained_bytes', 'Arithmetic buffers exceed the retained byte bound.')
    policy = fingerprint()
    provider_plan = checked['provider']
    if workspace:
        # Keep the canonical evaluation plan unchanged. The complete observation
        # block records the actual lowered allowance in its own checked plan.
        provider_plan = json.loads(definitions.canonical(provider_plan))
        available = (workspace_limit(checked) + 3 - workspace) // 3
        provider_plan['limits']['bytes'] = min(provider_plan['limits']['bytes'], available)
    inputs.validate()
    generation, input_projection = inputs.identity, inputs.projection
    provider = observations.observe(observations.ObservationPlan(
        definitions.canonical(provider_plan)), inputs, checkpoint)
    observed = provider.to_dict()
    if (observed['generation'] != generation or observed['projection'] != input_projection['content']
            or observed['provider_policy'] != policy['provider']):
        _fail('STALE_INPUT_GENERATION', '', 'Observation identity changed during formula evaluation.')
    identity = dict(plan=_hash(evaluation_plan.document), bundle=projection['bundle_revision'],
                    policy=policy, generation=generation, projection=input_projection)
    block = dict(format='formula-evaluation', version=VERSION, program=projection,
        requests=checked['requests'], plan_revision=identity['plan'],
        calculation_identity=_hash(definitions.canonical(identity)), identity=identity,
        observations=observed, operations=[], results=[])
    retained = (workspace + len(evaluation_plan.document)
                + len(definitions.canonical(projection)) + 2 * len(provider.document))
    if retained > limits['retained_bytes']:
        _fail('WORK_LIMIT', '/limits/retained_bytes', 'Captured formula inputs exceed their byte bound.')
    used = len(_encode(block, limits['output_bytes'], checkpoint))
    nodes = {node['id']: node for node in projection['nodes']}
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

    outcomes = iter(execution.operations(checked, observed, checkpoint))
    for task in checked['tasks']:
        checkpoint()
        try:
            value, reason, values = next(outcomes)
        except StopIteration:
            raise RuntimeError('Arithmetic omitted a checked task outcome.') from None
        record = _operation(task, nodes[task['node']], value=value, reason=reason, inputs=values)
        retain(record, 'operations')
        operations[task['id']] = record
    try:
        next(outcomes)
    except StopIteration:
        pass
    else:
        raise RuntimeError('Arithmetic returned an extra task outcome.')
    for slot in checked['outputs']:
        checkpoint()
        retain(_result(slot, projection['definitions'][slot['definition']], operations[slot['task']]), 'results')

    def current():
        checkpoint()
        inputs.validate()
        if (inputs.identity != generation or inputs.projection != input_projection
                or fingerprint() != policy):
            _fail('STALE_INPUT_GENERATION', '', 'Formula inputs or policy changed during evaluation.')

    current()
    available = min(limits['output_bytes'], limits['retained_bytes'] - retained)
    if available < 1:
        _fail('WORK_LIMIT', '/limits/retained_bytes', 'Final formula encoding exceeds its retained byte bound.')
    document = _encode(block, available, checkpoint)
    current()  # Encoding calls user checkpoints, including its final chunk.
    return EvaluationBlock(document)
