"""Daily paths of one dated book: its holdings' mean return and SPY's return to date on every session.

A reader of prepared facts. It binds no prepared-data identity (see
research.code_sources), so an edit here rebuilds no research record and drops
no book. The paths follow the exit rule of books.close and the period's SPY
return, so their last day equals the stored period returns. portfolio_results
checks that equality and gives the period its curve.
"""
from bisect import bisect_right

from backtest.financial import books, rules
from backtest.runtime import backtest_control


def days(sessions, entry, exit_day):
    """The market sessions after the entry day, through the exit day, in order."""
    return sessions[bisect_right(sessions, entry):bisect_right(sessions, exit_day)]


def holding(db, book_facts, symbol, start, entry, exit_day, texts, local):
    """One holding's fractional return to date on each day of texts (ISO days, in order).

    start is its (entry day, USD entry price); entry and exit_day bound its
    book. A day before its own entry is 0. A day without a close keeps the
    last price, as a stopped stock does at its exit. From the day of a
    bankruptcy in the book's window (rules.BANKRUPT) the return is -1. local
    is None for a US book. For a foreign book it holds the book's local
    session days: a close counts on one of them or on the entry day only, and
    takes the currency rate of its own day, as BookFacts.usd_price does. A
    close without a rate keeps the last value.
    """
    first = str(start[0])
    closes = db.execute('SELECT day,adjusted FROM research.stock_days WHERE symbol=? AND day>=? AND day<=? '
                        'AND adjusted IS NOT NULL ORDER BY day', (symbol, first, str(exit_day))).fetchall()
    if local is not None:
        currency = book_facts.quote_currency(symbol)
        closes = [(day, value) for day, value in ((day, book_facts.convert(close, currency, day))
                                                  for day, close in closes if day in local or day == first) if value is not None]
    loss = min((str(day) for name, day in rules.BANKRUPT if name == symbol and entry < day <= exit_day), default=None)
    values = []
    index, count, value = 0, len(closes), 0.
    for day in texts:
        while index < count and closes[index][0] <= day:
            value = closes[index][1]/start[1]-1
            index += 1
        values.append(-1. if loss is not None and day >= loss else value)
    return values


def benchmark(book_facts, start, sessions):
    """SPY's fractional return to date from the entry close start, on each of sessions.

    Each day reads the close that the period's SPY return reads (BookFacts.spy).
    A day without one keeps the last value.
    """
    values = []
    value = 0.
    for day in sessions:
        close = book_facts.spy(day)
        if close is not None:
            value = books.benchmark_return(start, close)
        values.append(value)
    return values


def book(db, book_facts, sessions, entry, exit_day, holdings, start_spy):
    """The daily paths of one book: {days, portfolio, spy, exits}.

    sessions are the market's saved sessions and holdings the selected
    (symbol, start) pairs in rank order. days are the ISO days of days().
    portfolio is, on each day, the mean of the holdings' returns to date
    (holding); an empty book holds cash at 0. Weights do not reset inside the
    book. exits is each holding's return on the last
    day, in rank order. Only one holding's path is held at a time.
    """
    found = days(sessions, entry, exit_day)
    texts = [str(day) for day in found]
    local = None if book_facts.market == 'us' else set(texts)
    sums = [0.]*len(texts)
    exits = []
    for symbol, start in holdings:
        backtest_control.checkpoint()
        path = holding(db, book_facts, symbol, start, entry, exit_day, texts, local)
        for index, value in enumerate(path):
            sums[index] += value
        exits.append(path[-1])
    return dict(days=texts, portfolio=[total/len(exits) if exits else 0. for total in sums],
                spy=benchmark(book_facts, start_spy, found), exits=exits)
