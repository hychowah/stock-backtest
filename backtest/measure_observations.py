"""Bounded bridge from formula contexts to existing financial owners.

Prepared scope membership is explicit: a prepared January or latest root reads
its stored book row (facts.View.prepared), and a missing row never falls back
to a recalculation. Other contexts use the dated owner policy here. One
resolved context serves every requested lane of that context.
"""
import json
import math
from datetime import date
from pathlib import Path
import hashlib

from backtest.financial import books, metrics

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_PERCENT = frozenset(('profit_margin', 'fcf_yield', 'roe', 'return_1y',
                       'return_3y', 'operating_yield_spread_3y'))


def policy_fingerprint():
    return _LOADED


def detached(value, checkpoint=lambda: None):
    """Detach evidence with cancellation and explicit nonfinite JSON states."""
    checkpoint()
    if isinstance(value, float) and not math.isfinite(value):
        return 'NaN' if math.isnan(value) else 'Infinity' if value > 0 else '-Infinity'
    if isinstance(value, dict):
        return {key: detached(item, checkpoint) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [detached(item, checkpoint) for item in value]
    return value


def prepared_scope(projection, root, context):
    if context['id'] != context['root']:
        return False
    owner = root.get('owner_scope')
    if owner is not None:
        return owner['kind'] == 'prepared'
    return any(scope['mode'] == root['mode'] and scope['pool'] == root['pool']
               and scope['context_date'] == context['date'] for scope in projection['scopes'])


class _CheckedReports(list):
    def __init__(self, rows, checkpoint):
        super().__init__(rows)
        self.checkpoint = checkpoint

    def __iter__(self):
        for row in super().__iter__():
            self.checkpoint()
            yield row


class _CheckedFinancials(dict):
    def __init__(self, values, checkpoint):
        super().__init__(values)
        self.checkpoint = checkpoint

    def items(self):
        for item in super().items():
            self.checkpoint()
            yield item


def dated(inputs, root, context, anchor, checkpoint, *, budget):
    """Resolve existing dated owners once, without an exit observation."""
    checkpoint()
    day = date.fromisoformat(context['date'])
    valuation, valuation_evidence = inputs.entry(root['symbol'], anchor, day)
    if valuation is None:
        return dict(reason='LEGACY_MEASURE_UNAVAILABLE', evidence=dict(
            policy='dated-owner', valuation=valuation_evidence))
    reports = inputs.broad_reports(root['symbol'], checkpoint, budget=budget)
    remaining = budget - len(json.dumps(reports, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8'))
    if remaining < 0:
        raise ValueError('Observation owner facts exceed their byte bound.')
    financials = inputs.legacy_financial_history(root['symbol'], checkpoint, budget=remaining)
    treasury = inputs.legacy_treasury(day, checkpoint)
    lookups = []
    def lookup(when, column, forward, slack):
        checkpoint()
        result = inputs.lookup(root['symbol'], when, column, forward, slack)
        lookups.append(dict(requested_date=str(when), column=column, forward=forward,
            slack=slack, observation=[str(result[0]), result[1]] if result else None))
        return result
    try:
        yield_value, multiple = books.ebitda_yield_and_multiple(
            valuation['ebitda'], valuation['enterprise_value'])
        if not math.isfinite(yield_value) or not math.isfinite(multiple):
            return dict(reason='NONFINITE_RESULT', evidence=dict(
                policy='dated-owner', valuation=valuation_evidence, treasury=treasury, lookups=lookups))
        observation = dict(fiscal=str(anchor['fiscal']), market_cap=valuation['market_cap'],
            enterprise_value=valuation['enterprise_value'], ebitda_yield=yield_value,
            ev_ebitda=multiple)
        pairs = metrics.evaluate(observation, _CheckedReports(reports, checkpoint))
        filters = metrics.filter_values(observation, pairs, day, lookup, _CheckedFinancials(financials, checkpoint),
                                        treasury['value'] if treasury else None)
    except (ArithmeticError, OverflowError):
        return dict(reason='LEGACY_MEASURE_UNAVAILABLE', evidence=dict(
            policy='dated-owner', valuation=valuation_evidence, treasury=treasury, lookups=lookups))
    checkpoint()
    return dict(reason=None, evidence=detached(dict(policy='dated-owner', valuation=valuation_evidence,
        treasury=treasury, lookups=lookups, reports=reports, financials=financials,
        snapshot=observation, metrics=pairs, filters=filters), checkpoint))


def lane(owner, name, checkpoint=lambda: None):
    """Detach one lane, including its original scale and conversion."""
    evidence = owner['evidence']
    if owner['reason']:
        return dict(value=None, valid=False, reason=owner['reason'], evidence=evidence)
    if name == 'market_cap':
        source, key = 'snapshot', 'market_cap'
        stored = evidence['snapshot'].get(key)
    elif name in ('ev_ebitda', 'ev_ebitda_3y', 'ebitda_yield'):
        source, key = 'metrics', 'ev_ebitda' if name == 'ebitda_yield' else name
        pair = evidence['metrics'].get(key)
        stored = (pair[1] if name == 'ebitda_yield' else pair[0]) if pair else None
    else:
        source, key = 'filters', name
        stored = evidence['filters'].get(key)
    conversion = 'percent-divided-by-100' if name in _PERCENT else 'identity'
    nonfinite = stored in ('NaN', 'Infinity', '-Infinity')
    value = (stored / 100 if name in _PERCENT else stored) if stored is not None and not nonfinite else None
    reason = 'NONFINITE_RESULT' if nonfinite else 'LEGACY_MEASURE_UNAVAILABLE' if value is None else None
    if value is not None and not math.isfinite(value):
        value, reason = None, 'NONFINITE_RESULT'
    return dict(value=value, valid=reason is None, reason=reason,
        evidence=dict(owner=detached(evidence, checkpoint), source=source, key=key, stored=stored, conversion=conversion))
