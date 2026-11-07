"""Independent original screening and price arithmetic of the January study.

The study constants live here: each January from FIRST_YEAR through LAST_YEAR,
the HOLD highest EBITDA/EV spreads, the last book marked through ASOF. No app
code imports this package; revalue.calculate and the development check
(check.py) use it on the bench.
"""
from __future__ import annotations
from datetime import date, timedelta
import json
from pathlib import Path
from backtest.paths import RAW
from backtest.financial.rules import (MIN_MARKET_CAP, MIN_EV, BUFFER, LAG, parse_day, num, latest_statement)
from backtest.inputs.market import cache_path_for

FIRST_YEAR = 1996
LAST_YEAR = 2026
ASOF = date(2026, 10, 21)
HOLD = 50

def load_bars(path: Path, price_key: str) -> list[tuple[date, float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    bars = []
    if isinstance(payload, dict):
        payload = payload.get("historical") or payload.get("data") or []
    for row in payload:
        day = parse_day(row.get("date"))
        price = num(row.get(price_key))
        if day is not None and price is not None and price > 0:
            bars.append((day, price))
    bars.sort()
    return bars

def asof_yield(points: list[tuple[date, float]], day: date) -> float | None:
    # points sorted ascending
    lo, hi = 0, len(points)
    while lo < hi:
        mid = (lo + hi) // 2
        if points[mid][0] <= day:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return None
    return points[lo - 1][1]

def session_on_or_after(days: list[date], day: date) -> date | None:
    lo, hi = 0, len(days)
    while lo < hi:
        mid = (lo + hi) // 2
        if days[mid] < day:
            lo = mid + 1
        else:
            hi = mid
    if lo >= len(days):
        return None
    return days[lo]

def load_prices(symbol: str) -> list[tuple[date, float]]:
    """Dividend-adjusted closes of one saved price file, in date order."""
    path = cache_path_for(symbol)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    div = []
    for row in payload.get("div") or []:
        if isinstance(row, dict):
            day = parse_day(row.get("date"))
            price = num(row.get("adjClose"))
            if day is not None and price is not None and price > 0:
                div.append((day, price))
    div.sort()
    return div

def first_on_or_after(bars: list[tuple[date, float]], day: date, slack: int) -> tuple[date, float] | None:
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if bars[mid][0] < day:
            lo = mid + 1
        else:
            hi = mid
    if lo >= len(bars):
        return None
    found = bars[lo]
    if found[0] > day + timedelta(days=slack):
        return None
    return found

def last_on_or_before(bars: list[tuple[date, float]], day: date, slack_back: int) -> tuple[date, float] | None:
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if bars[mid][0] <= day:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return None
    found = bars[lo - 1]
    if found[0] < day - timedelta(days=slack_back):
        return None
    return found

def build_statements(universe: dict[str, dict]) -> dict[str, list[dict]]:
    book: dict[str, list[dict]] = {}
    path = RAW / "metrics.jsonl"
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            symbol = record["symbol"]
            if symbol not in universe:
                continue
            parsed = []
            for row in record["rows"]:
                fiscal = parse_day(row.get("date"))
                multiple = num(row.get("evToEBITDA"))
                market_cap = num(row.get("marketCap"))
                enterprise = num(row.get("enterpriseValue"))
                if fiscal is None or multiple is None or market_cap is None or enterprise is None:
                    continue
                if multiple <= 0 or market_cap < MIN_MARKET_CAP or enterprise < MIN_EV:
                    continue
                currency = str(row.get("reportedCurrency") or "USD").upper()
                if currency and currency != "USD":
                    continue
                parsed.append({
                    "fiscal": fiscal,
                    "known": fiscal + LAG,
                    "market_cap": market_cap,
                    "enterprise": enterprise,
                    "yield": 1.0 / multiple,
                })
            parsed.sort(key=lambda item: item["fiscal"])
            if parsed:
                book[symbol] = parsed
    print(f"statements symbols={len(book)}", flush=True)
    return book

def screen(book: dict[str, list[dict]], yields: list[tuple[date, float]], sessions: list[date]) -> dict[int, list[dict]]:
    picks: dict[int, list[dict]] = {}
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        rebalance = session_on_or_after(sessions, date(year, 1, 1))
        if rebalance is None or rebalance > ASOF:
            continue
        tbill = asof_yield(yields, rebalance)
        if tbill is None:
            continue
        ranked = []
        for symbol, rows in book.items():
            statement = latest_statement(rows, rebalance)
            if statement is None:
                continue
            ranked.append({
                "symbol": symbol,
                "rebalance": rebalance,
                "tbill": tbill,
                "fiscal": statement["fiscal"],
                "market_cap": statement["market_cap"],
                "enterprise": statement["enterprise"],
                "ebitda_yield": statement["yield"],
                "stale_spread": statement["yield"] - tbill,
            })
        ranked.sort(key=lambda item: item["stale_spread"], reverse=True)
        picks[year] = ranked[:BUFFER]
        print(f"screen {year} candidates={len(ranked)} kept={len(picks[year])}", flush=True)
    return picks

def rescale(row: dict, prices: list[tuple[date, float]]) -> dict | None:
    fiscal_px = last_on_or_before(prices, row["fiscal"], 7)
    entry_px = first_on_or_after(prices, row["rebalance"], 4)
    if fiscal_px is None or entry_px is None or fiscal_px[1] <= 0:
        return None
    equity_now = row["market_cap"] * (entry_px[1] / fiscal_px[1])
    net_debt = row["enterprise"] - row["market_cap"]
    ev_now = equity_now + net_debt
    if equity_now < MIN_MARKET_CAP or ev_now < MIN_EV:
        return None
    ebitda = row["ebitda_yield"] * row["enterprise"]
    ebitda_yield = ebitda / ev_now
    if ebitda_yield <= 0:
        return None
    out = dict(row)
    out["ev_now"] = ev_now
    out["equity_now"] = equity_now
    out["ebitda_yield_now"] = ebitda_yield
    out["spread"] = ebitda_yield - row["tbill"]
    out["entry_day"] = entry_px[0]
    return out
