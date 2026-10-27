"""Financial result contract 1: ordered selected books to detached results.

evaluate consumes contiguous (datetime.date entry, exit) pairs. select_period
returns {entry: ISO date, exit: ISO date, holdings: ordered SQL row dictionaries,
spy: fractional total return}. It owns book acquisition, not aggregation.

See docs/portfolio-results.md for complete fields, units and nullability. The
version belongs to the diagnostic envelope, never existing application payloads.
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


def _holdings(book, entry, exit_day):
    if (not isinstance(book, dict) or book.get('entry') != str(entry)
            or book.get('exit') != str(exit_day) or not _finite(book.get('spy'))
            or book['spy'] < -1 or not isinstance(book.get('holdings'), list)):
        raise ValueError('Selected-book identity or financial contract differs.')
    stocks = []
    symbols = set()
    previous_rank = 0
    for original in book['holdings']:
        if not isinstance(original, dict) or not HOLDING_FIELDS.issubset(original):
            raise ValueError('Selected holding is missing required fields.')
        if any(not _finite(original[key]) for key in NUMERIC_FIELDS):
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


def evaluate(periods, select_period, *, common_start=None, checkpoint=None):
    """Reduce complete selections in their original Python arithmetic order.

    Empty books remain visible and make strategy growth/CAGR unavailable. A
    common start adds the established explicit-date cash fields. Cash has zero
    return for both sides. Cancellation and provider errors propagate unchanged.
    """
    periods = validate_periods(periods, common_start)
    results = []
    for entry, exit_day in periods:
        if checkpoint is not None: checkpoint()
        book = select_period(entry, exit_day)
        stocks = _holdings(book, entry, exit_day)
        results.append(dict(entry=str(entry), exit=str(exit_day), holdings=stocks,
            names=len(stocks), portfolio=sum(h['return_value'] for h in stocks)/len(stocks) if stocks else None,
            spy=book['spy'], is_final_period=exit_day==periods[-1][1]))
    if checkpoint is not None: checkpoint()
    growth=spy_growth=1.
    for period in results:
        if growth is not None:growth=growth*(1+period['portfolio']) if period['portfolio'] is not None else None
        spy_growth*=1+period['spy']
    first = periods[0][0] if common_start is None else common_start
    duration=(periods[-1][1]-first).days/365.25
    result = dict(periods=results, start=str(first), end=str(periods[-1][1]),
        growth=growth, spy_growth=spy_growth, cagr=growth**(1/duration)-1 if growth is not None else None,
        spy_cagr=spy_growth**(1/duration)-1, coverage=COVERAGE)
    if common_start is not None:
        result.update(first_trade=str(periods[0][0]), cash_days=(periods[0][0]-first).days)
    return result
