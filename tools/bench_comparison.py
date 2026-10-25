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
STEP_COSTS = ('clone', 'setup', 'proof', 'request', 'collection', 'shutdown')
QUALIFICATIONS = ('participating_source', 'live_priority', 'resource_enforcement',
                  'descendant_closure', 'concurrent_workflows', 'real_input_binding')
STOP_RULES = ('cancelled', 'busy', 'stale', 'limit', 'unsupported', 'mismatch',
              'child_failed', 'closure_pending', 'control_drift', 'noncontemporary', 'interrupted')


def validate_prospective(value):
    """Validate a source-only cost declaration, never execute or grant admission.

    Pending real bindings are explicit. Even complete caller declarations cannot
    certify qualifications: they are unverified claims, not admission evidence.
    This route reads only its JSON input. It discovers no runtime or dependencies.
    """
    try:
        if (value['version'] != 1 or set(value['step_costs']) != set(STEPS)
                or set(value['global_costs']) != {'attachment', 'finalization'}
                or set(value['qualification']) != set(QUALIFICATIONS)
                or set(value['stop_rules']) != set(STOP_RULES)
                or not value['resource_requirements'] or not value['benchmark_tools']):
            raise ComparisonError('incomplete')
        totals = dict.fromkeys(COSTS, 0.)
        for step, costs in value['step_costs'].items():
            if set(costs) != set(STEP_COSTS): raise ComparisonError('incomplete')
            for key, seconds in costs.items():
                if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
                    raise ComparisonError('infeasible_costs')
                totals[key] += seconds
        totals.update(value['global_costs'])
        protocol = ComparisonProtocol.freeze(configuration=value['configuration'],
            binding=value['binding'], environment=value['environment'], costs=totals,
            whole_seconds=value['whole_seconds'], max_control_drift=value['max_control_drift'],
            max_bracket_seconds=value['max_bracket_seconds'], order=value['order'],
            step_costs=value['step_costs'])
        unresolved = [name for name in QUALIFICATIONS if value['qualification'][name] != 'qualified']
        return dict(declaration_sha256=digest(value), protocol_sha256=protocol.identity,
            arithmetic='feasible', allocated_seconds=sum(totals.values()), costs=totals,
            unresolved=unresolved, qualification_claims='unverified',
            execution_admission='unavailable', compiled_real_cost='unmeasured',
            workflow_budgets='unresolved', request_boundary='freshness_through_transport')
    except (KeyError, TypeError, AttributeError):
        raise ComparisonError('incomplete') from None


def main():
    """Validate one declaration from stdin; no path argument or execution mode."""
    import sys
    try:
        data = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024: raise ComparisonError('limit')
        value = validate_prospective(json.loads(data))
    except (ValueError, TypeError) as error:
        print(encoded(dict(reason=getattr(error, 'reason', 'unsupported'),
                           execution_admission='unavailable')).decode())
        return 2
    print(encoded(value).decode())
    return 0


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
               max_control_drift, max_bracket_seconds, order=STEPS, step_costs=None):
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
        if step_costs is not None:
            if (set(step_costs) != set(STEPS) or any(set(row) != set(STEP_COSTS)
                    or not all(positive(v) for v in row.values()) for row in step_costs.values())
                    or any(sum(step_costs[step][key] for step in STEPS) > costs[key] for key in STEP_COSTS)):
                raise ComparisonError('infeasible_costs')
            payload['step_costs'] = step_costs
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
        self.step_costs = {step: dict.fromkeys(STEP_COSTS, 0.) for step in STEPS}
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
        if self._events and self.clock() - self.started - self._events[0]['elapsed'] > self.protocol.value['max_bracket_seconds']:
            self.stop('noncontemporary')
            raise ComparisonError('noncontemporary')

    def charge(self, category, seconds):
        self.check()
        if (category not in self.costs or type(seconds) not in (int, float)
                or not math.isfinite(seconds) or seconds < 0):
            raise ComparisonError('invalid_cost')
        self.costs[category] += seconds
        if self.active is not None and category in STEP_COSTS:
            self.step_costs[self.active][category] += seconds
            allocations = self.protocol.value.get('step_costs')
            if allocations is not None and self.step_costs[self.active][category] > allocations[self.active][category]:
                self.stop('limit')
                raise ComparisonError('limit')
        if self.costs[category] > self.protocol.value['costs'][category]:
            self.stop('limit')
            raise ComparisonError('limit')

    def remaining(self, category):
        """Enforce both the active step and whole-comparison allocation."""
        self.check()
        total = self.protocol.value['costs'][category] - self.costs[category]
        allocations = self.protocol.value.get('step_costs')
        if allocations is not None and self.active is not None and category in STEP_COSTS:
            total = min(total, allocations[self.active][category] - self.step_costs[self.active][category])
        return total

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
                    step_costs=json.loads(encoded(self.step_costs)),
                    events=list(self.events), closed=True)


if __name__ == '__main__':
    raise SystemExit(main())
