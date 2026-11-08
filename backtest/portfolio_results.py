"""Financial result contracts: ordered selected books to detached results.

evaluate consumes contiguous (datetime.date entry, exit) pairs. select_period
returns {entry: ISO date, exit: ISO date, holdings: ordered SQL row dictionaries,
spy: fractional total return}. It owns book acquisition, not aggregation.

Contract 1 remains the default. Explicit contract 2 admits scalar selected rows
through the same reducer. See docs/portfolio-results.md for fields and units. The
version belongs to evidence headers, never existing application payloads.
This standard-library module opens no resources and takes no ownership.
"""
from copy import deepcopy
from datetime import date
import math

CONTRACT_VERSION = 1
COVERAGE = ('Cached-price companies only; additional early exits have not received '
            'the original manual review. Stopped proceeds stay in cash until the '
            'next rebalance. Equal weights reset each period; no transaction costs.')
HOLDING_FIELDS = frozenset(('pool', 'symbol', 'candidate_rank', 'fiscal', 'entry',
    'exit', 'market_cap', 'enterprise_value', 'ebitda', 'ebitda_yield',
    'ev_ebitda', 'spread', 'return_value', 'status', 'name', 'sector', 'exchange',
    'metric_yield', 'metric_multiple', 'rank'))
NUMERIC_FIELDS = ('market_cap', 'enterprise_value', 'ebitda', 'ebitda_yield',
                  'ev_ebitda', 'spread', 'return_value', 'metric_yield', 'metric_multiple')
STATUSES = ('Scheduled exit', 'Marked to date', 'Last available price', 'Bankruptcy')


def validate_periods(periods, common_start=None):
    """Validate the whole request before calling a provider or writing books.

    Session membership belongs to SessionCalendar. Return an immutable sequence
    so provider work cannot change the request being evaluated.
    """
    if not isinstance(periods, (list, tuple)) or not periods:
        raise ValueError('Choose a nonempty ordered period sequence.')
    result = []
    for pair in periods:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('Each period needs entry and exit dates.')
        entry, exit_day = pair
        if type(entry) is not date or type(exit_day) is not date or entry >= exit_day:
            raise ValueError('Period dates must have positive duration.')
        if result and result[-1][1] != entry:
            raise ValueError('Period boundaries must be contiguous and increasing.')
        result.append((entry, exit_day))
    if common_start is not None and (type(common_start) is not date or common_start > result[0][0]):
        raise ValueError('Common start must be on or before the first trade.')
    return tuple(result)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


SCALAR_HOLDING_FIELDS = (HOLDING_FIELDS - {'metric_yield', 'metric_multiple'}) | {
    'ranking_value','ranking_unit','ranking_display','ranking_direction','scalar_evidence'}


def validate_scalar_row(row):
    """Check generic scalar presentation without current catalog or evaluation."""
    if (type(row) is not dict or not _finite(row.get('ranking_value'))
            or row.get('ranking_unit') not in ('scalar','USD','USD/share','shares')
            or type(row.get('ranking_display')) is not str
            or row.get('ranking_direction') not in ('highest','lowest')
            or type(row.get('scalar_evidence')) is not dict
            or type(row.get('symbol')) is not str or type(row.get('rank')) is not int):
        raise ValueError('Malformed scalar selected row.')
    return row


def _holdings(book, entry, exit_day, contract=1):
    if (not isinstance(book, dict) or book.get('entry') != str(entry)
            or book.get('exit') != str(exit_day) or not _finite(book.get('spy'))
            or book['spy'] < -1 or not isinstance(book.get('holdings'), list)):
        raise ValueError('Selected-book identity or financial contract differs.')
    stocks = []
    symbols = set()
    previous_rank = 0
    for original in book['holdings']:
        if not isinstance(original, dict) or not (HOLDING_FIELDS if contract == 1 else SCALAR_HOLDING_FIELDS).issubset(original):
            raise ValueError('Selected holding is missing required fields.')
        if contract == 2: validate_scalar_row(original)
        if any(not _finite(original[key]) for key in NUMERIC_FIELDS if contract == 1 or key not in ('metric_yield','metric_multiple')):
            raise ValueError('Selected holding has an unavailable financial value.')
        if (not isinstance(original['symbol'], str) or not original['symbol']
                or original['symbol'] in symbols or type(original['rank']) is not int
                or original['rank'] <= previous_rank
                or original['pool'] not in ('legacy', 'cached')
                or original['status'] not in STATUSES or original['return_value'] < -1
                or (original['candidate_rank'] is not None and
                    (type(original['candidate_rank']) is not int or original['candidate_rank'] < 1))
                or any(original[key] is not None and not isinstance(original[key], str)
                       for key in ('name', 'sector', 'exchange'))):
            raise ValueError('Selected holding identity, rank or status differs.')
        try:
            actual_entry, actual_exit, fiscal = (date.fromisoformat(original[key])
                                                  for key in ('entry', 'exit', 'fiscal'))
        except (ValueError, TypeError):
            raise ValueError('Selected holding dates differ.') from None
        if (any(str(day) != original[key] for key, day in
                (('entry', actual_entry), ('exit', actual_exit), ('fiscal', fiscal)))
                or not entry <= actual_entry < exit_day or not actual_entry <= actual_exit <= exit_day):
            raise ValueError('Selected holding dates differ.')
        symbols.add(original['symbol'])
        previous_rank = original['rank']
        stock = deepcopy(original)
        stock.pop('year', None)  # Private SQL period identity is not a holding field.
        stock['weight'] = 1/len(book['holdings'])
        stock['contribution_pp'] = stock['return_value']/len(book['holdings'])*100
        stocks.append(stock)
    return stocks


def mean_return(values):
    """Mean of ordered holding returns, or zero for an empty cash selection.

    Consume once without retaining the values. Keep Python's sum arithmetic;
    saved-result views and calculation use the same financial reduction.
    """
    count = 0
    def counted():
        nonlocal count
        for value in values:
            count += 1
            yield value
    total = sum(counted())
    return total/count if count else 0.


def reduce_returns(periods, *, start, end):
    """Compound ordered (strategy, SPY) returns without retaining periods.

    Inputs belong to the caller's validated result. An unavailable strategy
    return makes full-window growth unavailable. Unknown legacy boundary dates
    allow growth but no CAGR. This function opens no resources.
    """
    growth = spy_growth = 1.
    for portfolio, spy in periods:
        if growth is not None:growth=growth*(1+portfolio) if portfolio is not None else None
        spy_growth *= 1+spy
    duration = (end-start).days/365.25 if start is not None and end is not None else None
    return dict(growth=growth, spy_growth=spy_growth,
        cagr=growth**(1/duration)-1 if growth is not None and duration else None,
        spy_cagr=spy_growth**(1/duration)-1 if duration else None)


def evaluate(periods, select_period, *, common_start=None, checkpoint=None, contract=1, final_mark=False):
    """Collect the incremental reduction into the existing detached contract."""
    results = []
    summary = evaluate_into(periods, select_period, results.append,
        common_start=common_start, checkpoint=checkpoint, contract=contract, final_mark=final_mark)
    return dict(periods=results, **summary)


def evaluate_into(periods, select_period, emit_period, *, common_start=None, checkpoint=None, contract=1, final_mark=False):
    """Emit each complete holding period in order.

    Retain only aggregation state and the current period. The collecting adapter
    preserves the existing financial result. The returned summary omits periods;
    successful emission transfers detached evidence to the caller's sink. Sink
    failures propagate. No partial completion summary is returned.

    Empty books remain visible and hold zero-return cash until rebalance. A
    common start adds the established explicit-date cash fields. Cash has zero
    return for both sides. Cancellation and provider errors propagate unchanged.

    A book row records only how a holding exited. The run labels its final
    mark: with final_mark (the last period ends on a mark to date, not on a
    scheduled exit), the last period's 'Scheduled exit' holdings show 'Marked
    to date'.
    """
    if type(contract) is not int or contract not in (1,2):raise ValueError('Unsupported selected-book contract.')
    periods = validate_periods(periods, common_start)
    def returns():
        for entry, exit_day in periods:
            if checkpoint is not None: checkpoint()
            book = select_period(entry, exit_day)
            stocks = _holdings(book, entry, exit_day, contract)
            final = exit_day == periods[-1][1]
            if final and final_mark:
                for stock in stocks:
                    if stock['status'] == 'Scheduled exit':
                        stock['status'] = 'Marked to date'
            period = dict(entry=str(entry), exit=str(exit_day), holdings=stocks,
                names=len(stocks), portfolio=mean_return(h['return_value'] for h in stocks),
                spy=book['spy'], is_final_period=final)
            portfolio, spy = period['portfolio'], period['spy']
            emit_period(period)
            # Retain only returns while reducing, never the previous book.
            del period, stocks, book
            yield portfolio, spy
        if checkpoint is not None: checkpoint()
    first = periods[0][0] if common_start is None else common_start
    result = dict(start=str(first), end=str(periods[-1][1]),
        **reduce_returns(returns(), start=first, end=periods[-1][1]), coverage=COVERAGE)
    if common_start is not None:
        result.update(first_trade=str(periods[0][0]), cash_days=(periods[0][0]-first).days)
    return result
