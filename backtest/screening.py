"""Validation and SQL selection over acquired prepared tables.

validate_selection(**options) performs no SQL and preserves submitted settings.
select(db, *, period=None, **options) selects latest when period is None;
an inclusive period range selects historical or dated rows without year checks.
historical(db, *, first=1996, last=2026, **options) validates January years.
latest(db, **options) applies the common selector to latest snapshots.
"""
from .financial import metrics


def validate_selection(*, rank_from=1,rank_to=50,pool='legacy',metric=metrics.DEFAULT_METRIC,min_cap=100e6,max_cap=None,min_ev=50e6,min_yield=0.,max_multiple=None,sector=None,exchange=None,filters=None,selection_order='filter_first'):
    """Validate stock options without acquiring or querying a database."""
    import math
    if any(type(v) is not int for v in (rank_from,rank_to)) or not 1 <= rank_from <= rank_to <= 5000:
        raise ValueError('Choose increasing integer ranks between 1 and 5000.')
    if pool not in ('legacy','cached'):
        raise ValueError('Pool must be legacy or cached')
    for value in (min_cap,max_cap,min_ev,min_yield,max_multiple):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError('Financial filters must be non-negative numbers.')
    if max_cap is not None and max_cap < min_cap:
        raise ValueError('Maximum market cap must be at least the minimum.')
    if metric not in metrics.METRICS:
        raise ValueError('Choose a valid ranking metric.')
    filters=metrics.validate_filters(filters)
    if selection_order not in ('filter_first','rank_first'):
        raise ValueError('Choose filter first or rank first.')


def select(db, *, period=None, rank_from=1,rank_to=50,pool='legacy',metric=metrics.DEFAULT_METRIC,min_cap=100e6,max_cap=None,min_ev=50e6,min_yield=0.,max_multiple=None,sector=None,exchange=None,filters=None,selection_order='filter_first'):
    """Select ranks before or after user filters; keep ranks without refilling."""
    validate_selection(rank_from=rank_from,rank_to=rank_to,pool=pool,metric=metric,min_cap=min_cap,max_cap=max_cap,min_ev=min_ev,min_yield=min_yield,max_multiple=max_multiple,sector=sector,exchange=exchange,filters=filters,selection_order=selection_order)
    filters=metrics.validate_filters(filters)
    mode='historical' if period is not None else 'latest'
    table='snapshots' if period is not None else 'latest_snapshots'
    base=['s.pool=?'];values=[mode,metric,pool]
    if period is not None:
        base.append('s.year BETWEEN ? AND ?');values.extend(period)
    clauses=['s.market_cap>=?','s.enterprise_value>=?','s.metric_yield>=?']
    thresholds=[min_cap,min_ev,min_yield]
    for clause,value in [('s.market_cap<=?',max_cap),('s.metric_multiple<=?',max_multiple),('s.sector=?',sector),('s.exchange=?',exchange)]:
        if value is not None:
            clauses.append(clause);thresholds.append(value)
    for condition in filters:
        comparator='<' if condition['op']=='lt' else '>'
        clauses.append('EXISTS (SELECT 1 FROM filter_values f WHERE f.symbol=s.symbol AND f.pool=s.pool AND f.year='+('s.year' if period is not None else '0')+' AND f.mode=? AND f.field=? AND f.value'+comparator+'?)')
        thresholds.extend([mode,condition['field'],condition['value']])
    join=' JOIN screening_metrics m ON m.symbol=s.symbol AND m.pool=s.pool AND '+('m.year=s.year' if period is not None else 'm.year=0')+' AND m.mode=? AND m.metric=?'
    partition,ordering=('PARTITION BY s.year ','year,rank') if period is not None else ('','rank')
    conditions=' AND '.join(clauses)
    # Only the position of user conditions changes. Pool membership, available
    # ranking pairs and deterministic ties always precede the requested ranks.
    before=' WHERE '+conditions if selection_order=='filter_first' else ''
    after=' AND '+conditions if selection_order=='rank_first' else ''
    sql=f"""WITH candidates AS (
      SELECT s.*,c.name,c.sector,c.exchange,m.yield_value AS metric_yield,m.multiple AS metric_multiple
      FROM {table} s JOIN companies c USING(symbol){join} WHERE """+' AND '.join(base)+f"""), ranked AS (
      SELECT s.*,ROW_NUMBER() OVER({partition}ORDER BY s.metric_yield DESC,s.candidate_rank ASC,s.symbol ASC) AS rank
      FROM candidates s{before}) SELECT * FROM ranked s WHERE rank BETWEEN ? AND ?{after} ORDER BY {ordering}"""
    arguments=values+(thresholds+[rank_from,rank_to] if selection_order=='filter_first' else [rank_from,rank_to]+thresholds)
    cursor=db.execute(sql,arguments)
    fields=[c[0] for c in cursor.description]
    return [dict(zip(fields,row)) for row in cursor]


def historical(db, *, first=1996,last=2026,rank_from=1,rank_to=50,pool='legacy',metric=metrics.DEFAULT_METRIC,min_cap=100e6,max_cap=None,min_ev=50e6,min_yield=0.,max_multiple=None,sector=None,exchange=None,filters=None,selection_order='filter_first'):
    if any(type(v) is not int for v in (first,last)) or not 1996 <= first <= last <= 2026:
        raise ValueError('Choose increasing integer years within 1996–2026.')
    return select(db,period=(first,last),rank_from=rank_from,rank_to=rank_to,pool=pool,metric=metric,min_cap=min_cap,max_cap=max_cap,min_ev=min_ev,min_yield=min_yield,max_multiple=max_multiple,sector=sector,exchange=exchange,filters=filters,selection_order=selection_order)


def latest(db, *, rank_from=1,rank_to=50,pool='legacy',metric=metrics.DEFAULT_METRIC,min_cap=100e6,max_cap=None,min_ev=50e6,min_yield=0.,max_multiple=None,sector=None,exchange=None,filters=None,selection_order='filter_first'):
    return select(db,rank_from=rank_from,rank_to=rank_to,pool=pool,metric=metric,min_cap=min_cap,max_cap=max_cap,min_ev=min_ev,min_yield=min_yield,max_multiple=max_multiple,sector=sector,exchange=exchange,filters=filters,selection_order=selection_order)
