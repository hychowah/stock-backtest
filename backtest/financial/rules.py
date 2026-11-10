"""Financial policy that latest and dated books share, and saved-value decoding.

No storage or execution dependencies. The reference engine keeps its own study
constants (backtest/engines/reference/legacy.py).
"""
from datetime import date, datetime, timedelta

# The first day a schedule, a dated book or a historical formula root can use.
FIRST_DAY = date(1996, 1, 1)
MIN_MARKET_CAP = 100_000_000
MIN_EV = 50_000_000
BUFFER = 250
LAG = timedelta(days=90)
MAX_AGE = timedelta(days=800)


def parse_day(value: object) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    # Saved rows use ASCII YYYY-MM-DD. This faster path gives exactly the
    # strptime result for that form; every other form keeps strptime.
    if len(text) == 10 and text.isascii() and text[4] == text[7] == '-' and (text[:4] + text[5:7] + text[8:]).isdigit():
        try:
            return date(int(text[:4]), int(text[5:7]), int(text[8:]))
        except ValueError:
            return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def num(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def selectable(fiscal: date, known: date, day: date) -> bool:
    """Whether a report can be selected on day: known before day and at most MAX_AGE old."""
    return known < day and day - fiscal <= MAX_AGE


def latest_statement(rows: list[dict], rebalance: date) -> dict | None:
    chosen = None
    for row in rows:
        if selectable(row["fiscal"], row["known"], rebalance):
            chosen = row
    return chosen

def us_exchange(name: str) -> bool:
    text = (name or "").upper()
    if any(token in text for token in ("ARCA", "OTC", "PINK", "BATS")):
        return False
    return any(token in text for token in ("NYSE", "NASDAQ", "AMEX", "ASE"))


def common_stock(symbol: str, name: str) -> bool:
    if not symbol or not symbol.isupper() or "." in symbol or len(symbol) > 6:
        return False
    if "-" in symbol:
        left, right = symbol.split("-", 1)
        if not (left.isalpha() and len(right) == 1 and right.isalpha()):
            return False
    elif not symbol.isalnum():
        return False
    label = (name or "").upper()
    if any(token in label for token in (" ETF", "ETF ", " FUND", "FUND ", " ETN", "PROSHARES", "ISHARES")):
        return False
    return True


# (symbol, day of loss) pairs checked as bankruptcies. A holding returns -100%
# in a dated book, and in the reference engine, only when the book's window
# contains that day: after the entry day, through the exit day. A loss on a
# rebalance day counts in the book that ends there.
BANKRUPT: set[tuple[str, date]] = set()


def bankrupt(symbol: str, entry: date, exit_day: date) -> bool:
    return any(name == symbol and entry < day <= exit_day for name, day in BANKRUPT)
