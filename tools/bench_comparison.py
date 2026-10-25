"""Frozen comparison costs and evidence, independent of engines and resources.

A pair is one uninterrupted contemporary control bracket. Retained evidence
from a stopped attempt can support correctness, but cannot finish another pair.
Budgets are prospective upper bounds, not predictions or user latency targets.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import time


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


class ComparisonError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('Comparison: ' + reason)


STEPS = ('control_before', 'numba_source', 'numba_compiled', 'control_after')
COSTS = ('attachment', 'clone', 'setup', 'proof', 'request', 'collection', 'shutdown', 'finalization')


@dataclass(frozen=True)
class ComparisonProtocol:
    """Own exact settings, order, costs and drift rules before any effects.

    costs contains whole-comparison allocations for each named cost. The two
    controls share a bracket across both candidates. Every method gets fresh
    results and setup; only immutable inputs/reference evidence may be shared.
    The protocol identity includes environment and complete sampled dates.
    """
    declaration: bytes

    def __post_init__(self):
        if type(self.declaration) is not bytes:
            raise ComparisonError('unsupported')

    @classmethod
    def freeze(cls, *, configuration, binding, environment, costs, whole_seconds,
               max_control_drift, max_bracket_seconds, order=STEPS):
        def positive(value):
            return type(value) in (int, float) and math.isfinite(value) and value > 0
        if (set(costs) != set(COSTS) or not all(positive(v) for v in costs.values())
                or not all(positive(v) for v in (whole_seconds, max_control_drift, max_bracket_seconds))
                or max_control_drift < 1 or sum(costs.values()) > whole_seconds
                or max_bracket_seconds > whole_seconds):
            raise ComparisonError('infeasible_costs')
        if (tuple(order)[0:1] != ('control_before',) or tuple(order)[-1:] != ('control_after',)
                or len(order) != 4 or set(order) != set(STEPS)):
            raise ComparisonError('unsupported_order')
        if (not isinstance(configuration, dict) or not configuration.get('samples')
                or configuration.get('requested') != len(configuration['samples'])
                or not isinstance(binding, dict) or not binding or not environment):
            raise ComparisonError('incomplete')
        payload = dict(version=1, configuration=configuration, binding=binding,
            environment=environment, costs=costs, whole_seconds=whole_seconds,
            max_control_drift=max_control_drift, max_bracket_seconds=max_bracket_seconds,
            order=list(order))
        return cls(encoded(payload))

    @property
    def value(self):
        return json.loads(self.declaration)

    @property
    def identity(self):
        return hashlib.sha256(self.declaration).hexdigest()


class ComparisonLedger:
    """Append completed phases; no timing resumption or caller-supplied success.

    The owner persists each snapshot atomically. A stop is terminal. Completion
    requires all four steps, exact reference agreement and confirmed closure.
    """
    def __init__(self, protocol, *, clock=time.monotonic):
        self.protocol = protocol
        self.clock = clock
        self.started = clock()
        self._events = []
        self.costs = dict.fromkeys(COSTS, 0.)
        self.stopped = None
        self.active = None

    @property
    def events(self):
        return json.loads(encoded(self._events))

    def check(self):
        if self.stopped:
            raise ComparisonError(self.stopped)
        if self.clock() - self.started > self.protocol.value['whole_seconds']:
            self.stop('limit')
            raise ComparisonError('limit')

    def charge(self, category, seconds):
        self.check()
        if (category not in self.costs or type(seconds) not in (int, float)
                or not math.isfinite(seconds) or seconds < 0):
            raise ComparisonError('invalid_cost')
        self.costs[category] += seconds
        if self.costs[category] > self.protocol.value['costs'][category]:
            self.stop('limit')
            raise ComparisonError('limit')

    def begin(self, step):
        self.check()
        completed = [event['step'] for event in self._events if event['event'] == 'complete']
        if self.active is not None or len(completed) >= 4 or self.protocol.value['order'][len(completed)] != step:
            raise ComparisonError('protocol')
        self.active = step
        self._events.append(dict(event='start', step=step, elapsed=self.clock() - self.started))

    def finish(self, step, evidence):
        self.check()
        if self.active != step or evidence.get('financial_agreement') is not True or evidence.get('closed') is not True:
            self.stop('mismatch')
            raise ComparisonError('mismatch')
        self._events.append(dict(event='complete', step=step, elapsed=self.clock() - self.started,
                                 evidence=json.loads(encoded(evidence))))
        self.active = None

    def stop(self, reason):
        if self.stopped is None:
            self.stopped = reason
            self._events.append(dict(event='stopped', reason=reason, elapsed=self.clock() - self.started))

    def result(self, *, closed=False):
        self.check()
        finished = [event for event in self.events if event['event'] == 'complete']
        if len(finished) != 4 or not closed or self.active is not None:
            raise ComparisonError('incomplete')
        a, b = finished[0], finished[-1]
        times = [event['evidence']['request_seconds'] for event in (a, b)]
        if any(type(v) not in (float, int) or not math.isfinite(v) or v <= 0 for v in times):
            raise ComparisonError('invalid_timing')
        if max(times) / min(times) > self.protocol.value['max_control_drift']:
            self.stop('control_drift')
            raise ComparisonError('control_drift')
        if b['elapsed'] - self.events[0]['elapsed'] > self.protocol.value['max_bracket_seconds']:
            self.stop('noncontemporary')
            raise ComparisonError('noncontemporary')
        return dict(status='fixture_pair_complete', protocol=self.protocol.identity,
                    execution_admission='unavailable', speed_gate='unqualified',
                    control_drift=max(times) / min(times), costs=dict(self.costs),
                    events=list(self.events), closed=True)
