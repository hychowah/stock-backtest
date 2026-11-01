"""Shared strategy configuration, scalar decoding and report availability.

No storage or execution dependencies. Reference arithmetic remains independent.
"""
from datetime import date, datetime, timedelta

FIRST_YEAR = 1996
LAST_YEAR = 2026
ASOF = date(2026, 10, 21)
MIN_MARKET_CAP = 100_000_000
MIN_EV = 50_000_000
BUFFER = 250
HOLD = 50
LAG = timedelta(days=90)
MAX_AGE = timedelta(days=800)


def parse_day(value: object) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
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


def latest_statement(rows: list[dict], rebalance: date) -> dict | None:
    chosen = None
    for row in rows:
        if row["known"] < rebalance and rebalance - row["fiscal"] <= MAX_AGE:
            chosen = row
    return chosen
