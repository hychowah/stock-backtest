"""Read-only saved dated facts, separate from legacy valid-series projection.

Shared Treasury/calendar sources use the empty symbol. Source hashes identify
bytes even when SeriesAsset cannot establish completion. No provider metadata,
URLs or credentials enter evidence. Missing receipts never erase saved facts.
"""
from datetime import date
import hashlib
import json
import math

from backtest.inputs import cache_assets, market

MAX_HISTORY = 16384
MAX_RECORD_BYTES = 4 * 1024 * 1024
STOCK = 'historical-price-eod/dividend-adjusted'
TREASURY = 'treasury-rates'
CALENDAR = 'spy-calendar'


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, float, int)):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, OverflowError):
        return None


def _day(value):
    try:
        return str(date.fromisoformat(value[:10])) if isinstance(value, str) else None
    except ValueError:
        return None


def resolve(path, endpoint, ledger, *, stock=False, checkpoint=lambda: None):
    """Return bounded detached rows and exact-content source/receipt evidence.

    Equal admissible values agree; null and invalid variants remain identified.
    Currency-free stock routes use the admitted USD-company/share basis. Explicit
    foreign currency disqualifies only price, never volume. All signed rates are
    valid. Receipt acceptance delegates to the unchanged SeriesAsset contract.
    """
    source = dict(endpoint=endpoint, asset='px/' + path.name if stock else path.name,
                  sha256=None, disposition='missing', receipt=None, invalid_rows=[])
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return dict(source=source, dated={})
    checkpoint()
    source.update(sha256=hashlib.sha256(content).hexdigest(), disposition='unreadable')
    try:
        payload = json.loads(content)
        rows = payload.get('div') if stock and isinstance(payload, dict) else payload
        if endpoint == CALENDAR and isinstance(rows, dict):
            # Match the retained SPY reader. Wrapper metadata is not a receipt;
            # unchanged SeriesAsset rules still decide completion separately.
            rows = rows.get('historical') or rows.get('data') or []
        if not isinstance(rows, list):
            return dict(source=source, dated={})
    except (ValueError, UnicodeDecodeError):
        return dict(source=source, dated={})
    if len(rows) > MAX_HISTORY:
        raise ValueError('Prepared observation history exceeds its bound.')
    field = 'month3' if endpoint == TREASURY else 'adjClose'
    try:
        asset = cache_assets.SeriesAsset(path, field, stock=stock)
    except (ValueError, TypeError, OverflowError):
        asset = None
    if asset and asset.valid and asset.digest != source['sha256']:
        raise ValueError('Dated observation source changed during preparation.')
    receipt = asset.evidence(ledger if isinstance(ledger, dict) else {}) if asset else {}
    # Keep only the existing receipt contract. Arbitrary ledger metadata is not
    # observation evidence and may contain sensitive provider configuration.
    if receipt:
        source['receipt'] = dict(sha256=receipt['sha256'], windows=asset.checked(ledger),
                                 base_span=asset.base_span(ledger), skipped_dates=asset.skipped_dates(ledger))
    source['disposition'] = 'valid' if asset and asset.valid else 'salvaged'
    grouped = {}
    for index, row in enumerate(rows):
        checkpoint()
        # Hash all original variants, including invalid dates and repeated rows.
        raw = json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=True)
        if len(raw.encode()) > MAX_RECORD_BYTES:
            raise ValueError('Prepared observation record exceeds its byte bound.')
        identity = dict(index=index, sha256=hashlib.sha256(raw.encode()).hexdigest())
        day = _day(row.get('date')) if isinstance(row, dict) else None
        if day is None:
            source['invalid_rows'].append(identity)
            continue
        grouped.setdefault(day, []).append((row, identity))
    dated = {}
    fields = ('month3', 'year10') if endpoint == TREASURY else ('adjClose', 'volume') if stock else ('adjClose',)
    for day, variants in grouped.items():
        checkpoint()
        states = {}
        for field in fields:
            candidates, retained, invalid, foreign = set(), [], False, False
            for row, identity in variants:
                checkpoint()
                value = _number(row.get(field))
                currency, reported = row.get('currency'), row.get('reportedCurrency')
                incompatible = field == 'adjClose' and any(c not in (None, '', 'USD') for c in (currency, reported))
                acceptable = (value is not None and (value > 0 if field == 'adjClose'
                              else value >= 0 if field == 'volume' else True))
                if acceptable and not incompatible:
                    candidates.add(value)
                foreign |= incompatible and value is not None
                invalid |= row.get(field) not in (None, '') and not acceptable
                retained.append(dict(identity, value=value, currency=currency if isinstance(currency, str) and len(currency) <= 16 else None,
                                     reported_currency=reported if isinstance(reported, str) and len(reported) <= 16 else None,
                                     admissible=bool(acceptable and not incompatible)))
            reason = (None if len(candidates) == 1 else 'CONFLICTING_INPUT' if len(candidates) > 1
                      else 'NON_USD_INPUT' if foreign else 'INVALID_INPUT' if invalid else 'MISSING_INPUT')
            states[field] = dict(value=next(iter(candidates)) if reason is None else None,
                                 valid=reason is None, reason=reason, rows=retained)
        dated[day] = states
        if len(_encode(states).encode()) > MAX_RECORD_BYTES:
            raise ValueError('Prepared observation record exceeds its byte bound.')
    if len(_encode(source).encode()) > MAX_RECORD_BYTES:
        raise ValueError('Prepared observation record exceeds its byte bound.')
    return dict(source=source, dated=dated)


def stock(raw, symbol, ledger, checkpoint=lambda: None):
    return resolve(raw/'px'/market.cache_path_for(symbol).name, STOCK, ledger,
                   stock=True, checkpoint=checkpoint)


def shared(raw, ledger, checkpoint=lambda: None):
    return {endpoint: resolve(raw/name, endpoint, ledger, checkpoint=checkpoint)
            for endpoint, name in ((TREASURY, 'treasury.json'), (CALENDAR, 'spy-div.json'))}
