"""Bounded Numba arithmetic for the existing checked formula task graph.

The provider supplies admission and selected annual members. This module lowers
only checked expression operations; it never selects reports, aligns years or
calculates EV. Its typed tape is internal compiler data, not a saved language.

One Evaluator owns its warmed kernel and bounded tape cache. The caller closes
it before releasing outer execution ownership. Each evaluate() call borrows its
input view, reserves buffers before observations and returns detached evidence.
Native chunks preserve tape order and have cooperative checkpoints between them.
Annual folds have separate member steps. No cross-call process reuse is implied.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

import numpy as np
from numba import njit

from backtest import observations
from backtest.variables import definitions, evaluation
from backtest.engines.numerical import identity, formula_capabilities

VERSION = formula_capabilities.VERSION
MAX_CHUNK_STEPS = formula_capabilities.MAX_CHUNK_STEPS
MAX_CACHE_BYTES = formula_capabilities.MAX_CACHE_BYTES
_LOADED_FORMULAS = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OPS = {'constant': 0, 'parameter': 1, 'annual': 1, 'ref': 2, 'at': 2,
        'lookback': 2, 'neg': 3, 'add': 4, 'sub': 5, 'mul': 6, 'div': 7}
_PARAMETERS = formula_capabilities.PARAMETERS
# Fold instructions are separate so cancellation can occur between members.
_SUM, _MIN, _MAX, _MEAN, _FINAL = 8, 9, 10, 11, 12
_ROOT, _ZERO, _NONFINITE = 1, 2, 3


def capabilities():
    """Detached support declaration; package/readiness checks remain separate."""
    return formula_capabilities.capabilities()



def policy_fingerprint(*, chunk_steps=MAX_CHUNK_STEPS):
    current = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    compiler_source = hashlib.sha256(Path(identity.__file__).read_bytes()).hexdigest()
    if current != _LOADED_FORMULAS or compiler_source != identity._LOADED_IDENTITY:
        raise definitions.FormulaError('STALE_INPUT_GENERATION', '', 'Loaded numerical formula source changed.')
    environment = identity.compiler_environment(1)
    return dict(backend='numba-formulas', version=VERSION, formulas=current,
        capabilities=formula_capabilities.fingerprint(),
        compiler_source=compiler_source, compiler=environment,
        evaluation=evaluation.policy_fingerprint(), definitions=definitions.policy_fingerprint(),
        provider=observations.policy_fingerprint(), arithmetic=dict(evaluation._ARITHMETIC),
        native=dict(parallel=False, boundscheck=True, chunk_steps=chunk_steps))

def _execute(tape, constants, admitted, source_reasons, members, values, reasons, first, last):
    """Trusted ordered arithmetic; finite checks occur at each task's final step."""
    for step in range(first, last):
        code, target, left, right, member, final = tape[step]
        if not admitted[target]:
            reasons[target] = _ROOT
            values[target] = 0.0
            continue
        if code == 0:
            values[target] = constants[target]
            reasons[target] = 0
        elif code == 1:
            reasons[target] = source_reasons[target]
            if reasons[target] == 0:
                values[target] = members[member]
        elif code >= _SUM and code <= _FINAL:
            if reasons[target] == 0:
                if code == _SUM:
                    values[target] = values[target] + members[member]
                elif code == _MIN:
                    if members[member] < values[target]:
                        values[target] = members[member]
                elif code == _MAX:
                    if members[member] > values[target]:
                        values[target] = members[member]
                elif code == _MEAN:
                    values[target] = values[target] / right
        elif code >= 2 and code <= 7:
            reason = reasons[left]
            if reason == 0 and right >= 0:
                reason = reasons[right]
            reasons[target] = reason
            if reason == 0:
                if code == 2:
                    values[target] = values[left]
                elif code == 3:
                    values[target] = -values[left]
                elif code == 4:
                    values[target] = values[left] + values[right]
                elif code == 5:
                    values[target] = values[left] - values[right]
                elif code == 6:
                    values[target] = values[left] * values[right]
                elif values[right] == 0.0:
                    reasons[target] = _ZERO
                else:
                    values[target] = values[left] / values[right]
        else:
            raise RuntimeError('Unknown compiled formula instruction.')
        if final and reasons[target] == 0 and not math.isfinite(values[target]):
            reasons[target] = _NONFINITE
            values[target] = 0.0


@dataclass(frozen=True)
class _Tape:
    instructions: object
    constants: object
    member_offsets: dict
    members: int
    bytes: int


def _shape(checked, checkpoint):
    """Count all native arrays and tape metadata before allocating them."""
    nodes = {node['id']: node for node in checked['program']['nodes']}
    steps = 0
    for task in checked['tasks']:
        checkpoint()
        node = nodes[task['node']]
        if node['op'] not in _OPS:
            raise definitions.FormulaError('UNSUPPORTED_CAPABILITY', node['path'], 'Unsupported numerical formula operation.')
        if node['op'] in ('parameter', 'annual') and node['parameter'] not in _PARAMETERS:
            raise definitions.FormulaError('UNSUPPORTED_CAPABILITY', node['path'], 'Unsupported numerical observation parameter.')
        steps += node['count'] + 1 if node['op'] == 'annual' else 1
    count = len(checked['tasks'])
    members = sum(request['count'] for request in checked['provider']['requests'])
    # Two encodings pay for immutable task/member indexing and cache keys. These
    # are encoded-content reservations, not a claim about Python object RSS.
    metadata = 2 * len(definitions.canonical(dict(tasks=checked['tasks'],
        requests=checked['provider']['requests']))) + 128 * count + 256
    tape_bytes = steps * 6 * 4 + count * 8 + metadata
    run_bytes = count * (1 + 4 + 8 + 4) + members * 8
    return nodes, steps, members, tape_bytes, run_bytes


def _lower(checked, shape, checkpoint):
    nodes, steps, members, size, _ = shape
    tasks = checked['tasks']
    indices = {task['id']: number for number, task in enumerate(tasks)}
    offsets = {}
    offset = 0
    for request in checked['provider']['requests']:
        offsets[request['id']] = (offset, request['count'])
        offset += request['count']
    instructions = np.empty((steps, 6), dtype=np.int32)
    constants = np.zeros(len(tasks), dtype=np.float64)
    position = 0
    for number, task in enumerate(tasks):
        checkpoint()
        node = nodes[task['node']]
        op = node['op']
        operands = [indices[operand] for operand in task['operands']]
        left = operands[0] if operands else -1
        right = operands[1] if len(operands) > 1 else -1
        member = offsets[task['observation']][0] if 'observation' in task else -1
        if op == 'constant':
            constants[number] = float(node['value'])
        instructions[position] = (_OPS[op], number, left, right, member, int(op != 'annual'))
        position += 1
        if op == 'annual':
            fold = {'mean': _SUM, 'min': _MIN, 'max': _MAX}[node['stat']]
            for index in range(1, node['count']):
                instructions[position] = (fold, number, -1, -1, member + index, 0)
                position += 1
            instructions[position] = (_MEAN if node['stat'] == 'mean' else _FINAL,
                                      number, -1, node['count'], -1, 1)
            position += 1
    if position != steps:
        raise RuntimeError('Compiled formula instruction count differs from its reservation.')
    instructions.flags.writeable = constants.flags.writeable = False
    return _Tape(instructions, constants, offsets, members, size)


class _Execution:
    """One borrowed tape plus prepaid mutable buffers; never owns an input view."""
    def __init__(self, owner, tape, count, workspace_bytes):
        self.owner, self.tape = owner, tape
        self.workspace_bytes = workspace_bytes
        self.admitted = np.zeros(count, dtype=np.bool_)
        self.source_reasons = np.zeros(count, dtype=np.int32)
        self.members = np.zeros(tape.members, dtype=np.float64)
        self.values = np.zeros(count, dtype=np.float64)
        self.reasons = np.zeros(count, dtype=np.int32)

    def close(self):
        self.owner = self.tape = None
        self.admitted = self.source_reasons = self.members = self.values = self.reasons = None

    def operations(self, checked, observed, checkpoint):
        roots = {item['root']: item['admitted'] for item in observed['roots']}
        contexts = {item['id']: item['root'] for item in observed['contexts']}
        sources = {item['id']: item for item in observed['results']}
        names = [None, 'ROOT_NOT_ADMITTED', 'ZERO_DENOMINATOR', 'NONFINITE_RESULT']
        codes = {name: number for number, name in enumerate(names)}
        for observation, (offset, count) in self.tape.member_offsets.items():
            checkpoint()
            item = sources[observation]
            if len(item['members']) > count or item['valid'] and len(item['members']) != count:
                raise RuntimeError('Provider member count differs from its checked request.')
            for index, member in enumerate(item['members']):
                if member['valid']:
                    self.members[offset + index] = member['value']
            reason = item['reason']
            if reason not in codes:
                codes[reason] = len(names)
                names.append(reason)
        for number, task in enumerate(checked['tasks']):
            checkpoint()
            self.admitted[number] = roots[contexts[task['context']]]
            if 'observation' in task:
                self.source_reasons[number] = codes[sources[task['observation']]['reason']]
        kernel = self.owner._kernel
        for first in range(0, len(self.tape.instructions), self.owner.chunk_steps):
            checkpoint()
            last = min(first + self.owner.chunk_steps, len(self.tape.instructions))
            kernel(self.tape.instructions, self.tape.constants, self.admitted,
                   self.source_reasons, self.members, self.values, self.reasons, first, last)
            self.owner._check_signatures()
            self.owner.stats['native_chunks'] += 1
            checkpoint()
        indices = {task['id']: number for number, task in enumerate(checked['tasks'])}
        for number, task in enumerate(checked['tasks']):
            checkpoint()
            # Inputs are original provider members or recorded operand outcomes.
            # There is no Python arithmetic or annual reduction in this path.
            if 'observation' in task and self.admitted[number]:
                values = [float(member['value']) if member['valid'] else None
                          for member in sources[task['observation']]['members']]
            else:
                values = [float(self.values[indices[operand]]) if self.reasons[indices[operand]] == 0 else None
                          for operand in task['operands']]
            reason = names[int(self.reasons[number])]
            yield float(self.values[number]) if reason is None else None, reason, values


class Evaluator:
    """Own reusable compilation; evaluate() still performs fresh admission.

    Tape reuse binds exact program content and context-sensitive checked tasks.
    Every block additionally binds its whole ordered plan, current source and
    input identity. The bounded cache owns no observations or financial handles.
    The outer numerical process lifetime remains the application owner's choice.
    """
    def __init__(self, *, cache_bytes=4 * 1024 * 1024, chunk_steps=MAX_CHUNK_STEPS):
        if type(cache_bytes) is not int or not 0 <= cache_bytes <= MAX_CACHE_BYTES:
            raise definitions.FormulaError('INVALID_SHAPE', '/cache_bytes', 'Invalid numerical formula cache bound.')
        if type(chunk_steps) is not int or not 1 <= chunk_steps <= MAX_CHUNK_STEPS:
            raise definitions.FormulaError('INVALID_SHAPE', '/chunk_steps', 'Invalid numerical formula chunk bound.')
        self.cache_bytes, self.chunk_steps = cache_bytes, chunk_steps
        self.cache = OrderedDict()
        self.closed = False
        self._kernel = self._signatures = self._environment = None
        self.stats = dict(tape_builds=0, tape_hits=0, native_chunks=0,
                          retained_tape_bytes=0, peak_workspace_bytes=0, kernel_compilations=0)

    def _warm(self, checkpoint):
        if self._kernel is not None:
            self._check_signatures()
            return
        checkpoint()
        kernel = njit(fastmath=False, cache=False, error_model='numpy', boundscheck=True)(_execute)
        instructions = np.empty((0, 6), dtype=np.int32)
        constants = np.empty(0, dtype=np.float64)
        instructions.flags.writeable = constants.flags.writeable = False
        kernel(instructions, constants, np.empty(0, dtype=np.bool_), np.empty(0, dtype=np.int32),
               np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64),
               np.empty(0, dtype=np.int32), 0, 0)
        checkpoint()
        if len(kernel.nopython_signatures) != 1:
            raise RuntimeError('Compiled formula kernel did not produce one nopython signature.')
        self._kernel = kernel
        self._signatures = tuple(kernel.nopython_signatures)
        self.stats['kernel_compilations'] += 1

    def warm(self, checkpoint=lambda: None):
        """Initialize the trusted kernel without observing any financial input."""
        if self.closed:raise ValueError('Numerical formula evaluator is closed.')
        fingerprint=self.policy_fingerprint()
        self._warm(checkpoint)
        self._environment=fingerprint['compiler']
        return dict(self.stats)

    def _check_signatures(self):
        if tuple(self._kernel.nopython_signatures) != self._signatures:
            raise RuntimeError('Compiled formula signature changed after warming.')

    def policy_fingerprint(self):
        result=policy_fingerprint(chunk_steps=self.chunk_steps)
        if self._environment is not None and result['compiler']!=self._environment:
            raise definitions.FormulaError('STALE_INPUT_GENERATION','','Numerical formula compiler environment changed.')
        return result

    def prepare(self, checked, checkpoint):
        if self.closed:
            raise ValueError('Numerical formula evaluator is closed.')
        formula_capabilities.require_program(definitions.FormulaProgram(
            definitions.canonical(checked['program'])),checkpoint=checkpoint)
        fingerprint = self.policy_fingerprint()
        shape = _shape(checked, checkpoint)
        _, _, _, tape_bytes, run_bytes = shape
        key = definitions.canonical(dict(bundle=checked['program']['bundle_revision'],
            tasks=checked['tasks'], requests=checked['provider']['requests']))
        key = hashlib.sha256(key.encode()).hexdigest()
        limit = evaluation.workspace_limit(checked)
        tape = self.cache.pop(key, None)
        if tape is not None:
            self.cache[key] = tape
            self.stats['tape_hits'] += 1
        # Pay also for construction copies before allocating a new tape. Evict
        # only reusable compiler data; captured evidence is never evicted.
        construction = tape_bytes if tape is None else 0
        retained = sum(item.bytes for item in self.cache.values())
        needed = run_bytes + retained + construction
        while self.cache and needed + construction > limit:
            removed_key, removed = self.cache.popitem(last=False)
            retained -= removed.bytes
            if removed_key == key:
                tape = None
                construction = tape_bytes
            needed = run_bytes + retained + construction
        if needed + construction > limit:
            raise definitions.FormulaError('WORK_LIMIT', '/limits/retained_bytes', 'Compiled formula buffers exceed their prepaid byte bound.')
        if tape is None:
            tape = _lower(checked, shape, checkpoint)
            self.stats['tape_builds'] += 1
            if tape.bytes <= self.cache_bytes:
                while self.cache and retained + tape.bytes > self.cache_bytes:
                    _, removed = self.cache.popitem(last=False)
                    retained -= removed.bytes
                self.cache[key] = tape
                retained += tape.bytes
        self._warm(checkpoint)
        self._environment = fingerprint['compiler']
        self.stats['retained_tape_bytes'] = retained
        workspace = run_bytes + retained + (0 if key in self.cache else tape.bytes)
        self.stats['peak_workspace_bytes'] = max(self.stats['peak_workspace_bytes'], workspace)
        return _Execution(self, tape, len(checked['tasks']), workspace)

    def evaluate(self, evaluation_plan, inputs, checkpoint=lambda: None):
        """Validate and compile before input access; return complete evidence."""
        return evaluation.evaluate(evaluation_plan, inputs, self, checkpoint)

    def close(self):
        self.cache.clear()
        self._kernel = self._signatures = self._environment = None
        self.stats['retained_tape_bytes'] = 0
        self.closed = True

    def __enter__(self):
        if self.closed:
            raise ValueError('Numerical formula evaluator is closed.')
        return self

    def __exit__(self, *unused):
        self.close()


def evaluate(evaluation_plan, inputs, checkpoint=lambda: None):
    """One explicitly closed compiled evaluation; reusable callers own Evaluator."""
    with Evaluator() as evaluator:
        return evaluator.evaluate(evaluation_plan, inputs, checkpoint)
