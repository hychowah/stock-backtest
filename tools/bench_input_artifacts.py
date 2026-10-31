"""Internal pure prepared-artifact inspection. No paths, engines or ownership.

Owners choose error types, historical ordering and checkpoint cadence. Manifest
interpretation, financial identity and publication remain with each owner.
"""
import hashlib
import json

RESEARCH_VERSION = 7
DAILY_VERSION = 3
BASE_TABLES = {
    'companies': 'symbol name exchange sector',
    'statements': 'symbol fiscal known market_cap enterprise_value ebitda ebitda_yield',
    'financial_inputs': 'symbol fiscal values_json',
}
RESEARCH_TABLES = dict(BASE_TABLES, **{
    'metadata': 'key value',
    'screening_metrics': 'mode pool year symbol metric multiple yield_value',
    'filter_values': 'mode pool year symbol field value',
    'baseline_prices': 'year symbol fiscal_price_date valuation_date fiscal_price valuation_price entry_price exit_price',
    'baseline_periods': 'year spy_entry spy_exit spy_entry_price spy_exit_price',
    'periods': 'year entry exit spy treasury legacy_candidates cached_candidates',
    'snapshots': 'pool year symbol candidate_rank fiscal entry exit market_cap enterprise_value ebitda ebitda_yield ev_ebitda spread return_value status',
    'latest_snapshots': 'pool symbol candidate_rank fiscal known price_date price market_cap enterprise_value ebitda_yield ev_ebitda spread',
})
DAILY_BASE = dict(BASE_TABLES, **{
    'prices': 'symbol day price adjusted', 'sessions': 'day price',
    'treasuries': 'day yield_value',
})
DAILY_TABLES = dict(RESEARCH_TABLES, **DAILY_BASE,
                    period_pools='period_id pool')
DERIVED = ('periods', 'snapshots', 'screening_metrics', 'filter_values',
           'baseline_prices', 'baseline_periods', 'latest_snapshots', 'period_pools')

def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def table_hash(db, table, budget, error, *, reason, every=1, pool_order=True):
    # Statement order is financial input: original-buffer ties use row order.
    orders = {'prices': 'symbol,day', 'sessions': 'day', 'treasuries': 'day'}
    if pool_order:
        orders['period_pools'] = 'period_id,pool'
    order = orders.get(table, 'rowid')
    result = hashlib.sha256()
    for number, row in enumerate(db.execute(f'SELECT * FROM {table} ORDER BY {order}')):
        if number % every == 0:
            budget.check()
        try:
            result.update(encoded(list(row)) + b'\n')
        except (TypeError, ValueError) as cause:
            raise error(reason) from cause
    return result.hexdigest()


def metadata(db, error, *, reason):
    try:
        result = {row[0]: json.loads(row[1]) for row in db.execute('SELECT key,value FROM metadata')}
        encoded(result)
        return result
    except (TypeError, ValueError) as cause:
        raise error(reason) from cause


def schema(db, expected, budget, error, *, reason, integrity_reason=None,
           integrity=True, integrity_first=True):
    budget.check()
    def inspect_integrity():
        if integrity and [row[0] for row in db.execute('PRAGMA integrity_check')] != ['ok']:
            raise error(integrity_reason or reason)
    if integrity_first:
        inspect_integrity()
    for table, columns in expected.items():
        if [row[1] for row in db.execute(f'PRAGMA table_info({table})')] != columns.split():
            raise error(reason)
    if not integrity_first:
        inspect_integrity()


def shared_rows(research, daily, row_hash, error):
    shared = {table: row_hash(research, table) for table in BASE_TABLES}
    if shared != {table: row_hash(daily, table) for table in BASE_TABLES}:
        raise error('mismatch')
