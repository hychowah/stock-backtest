"""Bounded bridge from formula contexts to existing financial owners.

Prepared scope membership is explicit: the root context of a stored-book root
reads that book's stored owner lanes (fact_view.View.prepared). A prepared
scope's decision names its book by id in its owner scope; any other latest
root reads the open book. A missing row never falls back to a recalculation.
Every other context uses the dated owner policy here: books.owner_values at
the context date. One resolved context serves every requested lane of that
context. Values carry no evidence beyond the lane's own source, key and stored
value.
"""
import math
from datetime import date

from backtest.financial import books

_PERCENT = frozenset(('profit_margin', 'fcf_yield', 'roe', 'return_1y',
                       'return_3y', 'operating_yield_spread_3y'))


def detached(value):
    """One stored value as an explanation keeps it: a nonfinite float as its JSON state name."""
    if isinstance(value, float) and not math.isfinite(value):
        return 'NaN' if math.isnan(value) else 'Infinity' if value > 0 else '-Infinity'
    return value


def prepared_scope(decision, context):
    """Whether the context is a root context whose owner lanes are stored book lanes (View.prepared).

    decision is the root's admission: a prepared scope's decision has an owner
    scope (scalar_execution._scope); a latest root reads the open book.
    """
    return context['id'] == context['root'] and ('owner_scope' in decision or decision['mode'] == 'latest')


def dated(view, root, context, anchor, checkpoint):
    """Resolve the dated owner policy once at the context date, without an exit observation.

    The entry valuation of the anchor report (books.admit) feeds
    books.owner_values over the view's facts port.
    """
    checkpoint()
    day = date.fromisoformat(context['date'])
    symbol, facts = root['symbol'], view.facts
    unavailable = dict(reason='LEGACY_MEASURE_UNAVAILABLE', evidence=dict(policy='dated-owner'))

    def lookup(when, forward, slack):
        return facts.price(symbol, when, forward, slack)
    reason, valuation = books.admit(anchor, day, lookup, books.ENTRY_SLACK)
    if valuation is None:
        return unavailable
    _, _, cap, ev, ebitda = valuation
    try:
        yield_value, multiple, pairs, filters = books.owner_values(
            symbol, str(anchor['fiscal']), day, cap, ev, ebitda, facts, facts.ten_year(day))
    except (ArithmeticError, OverflowError):
        return unavailable
    if not math.isfinite(yield_value) or not math.isfinite(multiple):
        return dict(reason='NONFINITE_RESULT', evidence=dict(policy='dated-owner'))
    return dict(reason=None, evidence=dict(policy='dated-owner', snapshot=dict(market_cap=cap),
                                           metrics={metric: list(pair) for metric, pair in pairs.items()},
                                           filters=filters))


def lane(owner, name):
    """One lane of a resolved owner context, with its original scale and conversion."""
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
    nonfinite = isinstance(stored, float) and not math.isfinite(stored)
    value = (stored / 100 if name in _PERCENT else stored) if stored is not None and not nonfinite else None
    reason = 'NONFINITE_RESULT' if nonfinite else 'LEGACY_MEASURE_UNAVAILABLE' if value is None else None
    if value is not None and not math.isfinite(value):
        value, reason = None, 'NONFINITE_RESULT'
    return dict(value=value, valid=reason is None, reason=reason,
                evidence=dict(source=source, key=key, stored=stored, conversion=conversion))
