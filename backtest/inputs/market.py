"""Saved market-series readers and stable asset filenames. No network access."""
from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path
import json
import urllib.parse
from backtest.paths import RAW
from backtest.financial.rules import parse_day, num

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

def cache_path_for(symbol: str) -> Path:
    safe = urllib.parse.quote(symbol, safe="")
    return RAW / "px" / f"{safe}.json"

def load_price_pair(symbol: str) -> tuple[list[tuple[date, float]], list[tuple[date, float]]]:
    path = cache_path_for(symbol)
    if not path.exists():
        return [], []
    payload = json.loads(path.read_text(encoding="utf-8"))
    light = []
    div = []
    for row in payload.get("light") or []:
        if isinstance(row, dict):
            day = parse_day(row.get("date"))
            price = num(row.get("price") if row.get("price") is not None else row.get("close"))
            if day is not None and price is not None and price > 0:
                light.append((day, price))
    for row in payload.get("div") or []:
        if isinstance(row, dict):
            day = parse_day(row.get("date"))
            price = num(row.get("adjClose"))
            if day is not None and price is not None and price > 0:
                div.append((day, price))
    light.sort()
    div.sort()
    return light, div
