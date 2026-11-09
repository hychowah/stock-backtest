"""Validation and SQL selection over one stored book of the book store.

validate_selection(**options) performs no SQL and preserves submitted settings.
select(db, *, book=None, **options) selects from one book of a daily
connection (backtest/inputs/book_store.py); None is the open (latest) book.
latest(db, **options) applies the common selector to the open book. This
ranked SELECT is the one SQL reader of book tables outside the book store; it
takes the table names and the book's row shape from the store.
"""
from .financial import metrics
from .inputs import book_store
from . import selection as policy


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



def legacy_specification(*, rank_from=1,rank_to=50,pool='legacy',metric=metrics.DEFAULT_METRIC,min_cap=100e6,max_cap=None,min_ev=50e6,min_yield=0.,max_multiple=None,sector=None,exchange=None,filters=None,selection_order='filter_first'):
    """Translate existing options into explicit scalar comparison lanes.

    Stored yield ranks highest; stored multiple and filter values remain in
    their original scale. No reciprocal or canonical conversion occurs here.
    Existing validation owns accepted legacy values, including null numeric
    bounds and unbounded metadata. Do not apply callable-formula limits to it.
    """
    validate_selection(rank_from=rank_from,rank_to=rank_to,pool=pool,metric=metric,min_cap=min_cap,max_cap=max_cap,min_ev=min_ev,min_yield=min_yield,max_multiple=max_multiple,sector=sector,exchange=exchange,filters=filters,selection_order=selection_order)
    spec=policy.validate(dict(ranking=dict(lane='metric_yield',direction='highest'),
        rank_from=rank_from,rank_to=rank_to,selection_order=selection_order))
    conditions=[dict(lane=lane,op='ge',value=value) for lane,value in
        [('market_cap',min_cap),('enterprise_value',min_ev),('metric_yield',min_yield)]]
    for lane,op,value in [('market_cap','le',max_cap),('metric_multiple','le',max_multiple),
                          ('sector','eq',sector),('exchange','eq',exchange)]:
        if value is not None:conditions.append(dict(lane=lane,op=op,value=value))
    conditions.extend(dict(lane='filter.'+item['field'],op=item['op'],value=item['value'])
                      for item in metrics.validate_filters(filters))
    # The current validator permits 50 threshold filters plus seven bounds.
    # Keep its accepted values rather than revalidating under custom limits.
    spec['conditions']=conditions
    return spec


def _sql_conditions(specification):
    """Render only adapter-owned lanes; all submitted values stay parameters."""
    columns={lane:'s.'+lane for lane in ('market_cap','enterprise_value',
             'metric_yield','metric_multiple','sector','exchange')}
    comparisons={'lt':'<','gt':'>','le':'<=','ge':'>=','eq':'='}
    clauses,values=[],[]
    for item in specification['conditions']:
        lane,op=item['lane'],comparisons[item['op']]
        if lane in columns:
            clauses.append(columns[lane]+op+'?');values.append(item['value'])
        elif lane.startswith('filter.') and lane[7:] in metrics.FILTERS:
            clauses.append('s.'+book_store.FILTERS[lane[7:]]+op+'?')
            values.append(item['value'])
        else:
            raise ValueError('Unsupported legacy selection lane.')
    return ' AND '.join(clauses),values


def select(db, *, book=None, exit_day=None, market='us', rank_from=1,rank_to=50,pool='legacy',metric=metrics.DEFAULT_METRIC,min_cap=100e6,max_cap=None,min_ev=50e6,min_yield=0.,max_multiple=None,sector=None,exchange=None,filters=None,selection_order='filter_first'):
    """Execute the legacy scalar adapter in SQL over one book; preserve rows and SQL pushdown.

    Rows keep the book's row shape (book_store.DATED or LATEST) plus the
    company name, sector and exchange, the metric pair and the rank.
    """
    spec=legacy_specification(rank_from=rank_from,rank_to=rank_to,pool=pool,metric=metric,min_cap=min_cap,max_cap=max_cap,min_ev=min_ev,min_yield=min_yield,max_multiple=max_multiple,sector=sector,exchange=exchange,filters=filters,selection_order=selection_order)
    if book is None:
        book=book_store.open_book(db,market)
    conditions,thresholds=_sql_conditions(spec)
    before=' WHERE '+conditions if spec['selection_order']=='filter_first' else ''
    after=' AND '+conditions if spec['selection_order']=='rank_first' else ''
    direction={'highest':'DESC','lowest':'ASC'}[spec['ranking']['direction']]
    multiple,yield_column=book_store.METRICS[metric]
    filter_columns=tuple(book_store.FILTERS.values())
    projection=''.join(',s.'+column for column in filter_columns)
    window='' if exit_day is None else ' AND s.entry<?'
    sql=f"""WITH candidates AS (
      SELECT {book_store.columns(db,book)},c.name,c.sector,c.exchange,s.{yield_column} AS metric_yield,s.{multiple} AS metric_multiple{projection}
      FROM {book_store.ROWS} s JOIN research.companies c USING(symbol)
      WHERE s.book=? AND s.pool=? AND s.{yield_column} IS NOT NULL AND s.{multiple} IS NOT NULL{window}), ranked AS (
      SELECT s.*,ROW_NUMBER() OVER(ORDER BY s.metric_yield {direction},s.candidate_rank ASC,s.symbol ASC) AS rank
      FROM candidates s{before}) SELECT * FROM ranked s WHERE rank BETWEEN ? AND ?{after} ORDER BY rank"""
    bounds=[spec['rank_from'],spec['rank_to']]
    arguments=[book,pool]+([str(exit_day)] if exit_day is not None else [])+(thresholds+bounds if spec['selection_order']=='filter_first' else bounds+thresholds)
    cursor=db.execute(sql,arguments)
    fields=[c[0] for c in cursor.description]
    return [{key:value for key,value in zip(fields,row) if key not in filter_columns} for row in cursor]


def latest(db, **options):
    return select(db, book=None, **options)
