"""US EBITDA/EV spread, rebalanced each January, versus SPY.

Past 30 years: buy at the first session of 1996 through the first session
of 2026. Each book is the 50 US common stocks with the highest
EBITDA/EV minus the 3-month Treasury yield. Equal weight. Sell at the
next January. The 2026 book is marked to the latest SPY session on or
before 2026-10-21.

The yield is the same for every stock on a rebalance date, so the rank
matches EBITDA/EV. It is still subtracted and stored.

Does not print the API key or request URLs.
"""

from __future__ import annotations

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

from backtest.paths import RAW, LEGACY
from backtest.financial.rules import (FIRST_YEAR, LAST_YEAR, ASOF, MIN_MARKET_CAP, MIN_EV, BUFFER, HOLD, LAG, MAX_AGE, parse_day, num, latest_statement)
KEY_PATH = Path.home().joinpath(".grok", "secrets", "fmp_api_key")
BASE = "https://financialmodelingprep.com/stable/"

WORKERS = 16
STARTS_PER_SEC = 12

_lock = threading.Lock()
_next_start = 0.0
_pause_until = 0.0


def _pace() -> None:
    global _next_start
    while True:
        with _lock:
            now = time.monotonic()
            if now < _pause_until:
                wait = _pause_until - now
            elif now >= _next_start:
                _next_start = now + (1 / STARTS_PER_SEC)
                return
            else:
                wait = _next_start - now
                _next_start += 1 / STARTS_PER_SEC
        time.sleep(wait)


def _penalize(seconds: float) -> None:
    global _pause_until
    with _lock:
        _pause_until = max(_pause_until, time.monotonic() + seconds)


def get_json(path: str, params: dict, *, paced: bool = True) -> tuple[int, object]:
    query = dict(params)
    query["apikey"] = KEY_PATH.read_text(encoding="utf-8").strip()
    url = BASE + path + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(6):
        if paced:
            _pace()
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read()
                status = int(response.status)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 5:
                _penalize(8 + 4 * attempt)
                continue
            if exc.code in (500, 502, 503, 504) and attempt < 5:
                time.sleep(1 + attempt)
                continue
            return int(exc.code), None
        except Exception:
            if attempt < 5:
                time.sleep(0.5 + attempt)
                continue
            return 0, None
        try:
            return status, json.loads(body.decode("utf-8"))
        except Exception:
            return status, None
    return 0, None


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


def screener(exchange: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for page in range(30):
        print(f"screener {exchange} request page={page}", flush=True)
        status, rows = get_json("company-screener", {
            "exchange": exchange,
            "isEtf": "false",
            "isFund": "false",
            "isActivelyTrading": "true",
            "limit": "1000",
            "page": str(page),
        })
        if status != 200 or not isinstance(rows, list) or not rows:
            break
        added = 0
        for row in rows:
            symbol = str(row.get("symbol") or "")
            if symbol in found:
                continue
            if not common_stock(symbol, str(row.get("companyName") or "")):
                continue
            if row.get("isEtf") or row.get("isFund"):
                continue
            if not us_exchange(str(row.get("exchangeShortName") or row.get("exchange") or exchange)):
                continue
            found[symbol] = {
                "symbol": symbol,
                "exchange": str(row.get("exchangeShortName") or exchange),
                "sector": str(row.get("sector") or ""),
                "name": str(row.get("companyName") or ""),
                "listed": True,
            }
            added += 1
        print(f"screener {exchange} page={page} rows={len(rows)} new={added}", flush=True)
        if len(rows) < 1000 or added == 0:
            break
    return found


def delisted_pages() -> dict[str, dict]:
    found: dict[str, dict] = {}

    def one(page: int) -> tuple[int, list]:
        status, rows = get_json("delisted-companies", {"page": str(page), "limit": "100"}, paced=False)
        if status != 200 or not isinstance(rows, list):
            return page, []
        return page, rows

    pages = list(range(0, 200))
    finished = 0
    empty_run = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(one, page) for page in pages]
        for future in as_completed(futures):
            page, rows = future.result()
            finished += 1
            if not rows:
                empty_run += 1
            if finished % 20 == 0 or not rows:
                print(f"delisted {finished}/{len(pages)} page={page} n={len(rows)}", flush=True)
            for row in rows:
                symbol = str(row.get("symbol") or "")
                exchange = str(row.get("exchange") or "")
                name = str(row.get("companyName") or "")
                if not us_exchange(exchange) or not common_stock(symbol, name):
                    continue
                found[symbol] = {
                    "symbol": symbol,
                    "exchange": exchange,
                    "sector": "",
                    "name": name,
                    "listed": False,
                }
    print(f"delisted us={len(found)}", flush=True)
    return found


def load_done(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line)["symbol"])
            except Exception:
                continue
    return done


def financial_record(symbol: str, payload: object) -> dict:
    """Keep every provider field. Prepared calculations select their own inputs."""
    if not isinstance(payload,list) or any(not isinstance(row,dict) for row in payload):
        raise ValueError('Invalid annual financial response. Saved files were kept.')
    record={"symbol":symbol,"rows":payload,"full_response":True}
    # Reject nonfinite JSON values without discarding unknown fields or nulls.
    json.dumps(record,allow_nan=False)
    return record


def fetch_metrics(symbols: list[str], dest: Path) -> None:
    done = load_done(dest)
    pending = [symbol for symbol in symbols if symbol not in done]
    print(f"metrics have={len(done)} pending={len(pending)}", flush=True)
    if not pending:
        return
    write_lock = threading.Lock()
    counters = {"ok": 0, "empty": 0, "fail": 0}

    def one(symbol: str) -> str:
        status, payload = get_json("key-metrics", {
            "symbol": symbol,
            "period": "annual",
            "limit": "40",
        }, paced=False)
        if status != 200 or not isinstance(payload, list):
            return "fail"
        record = financial_record(symbol, payload)
        with write_lock:
            with dest.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        return "empty" if not record["rows"] else "ok"

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(one, symbol) for symbol in pending]
        finished = 0
        for future in as_completed(futures):
            kind = future.result()
            counters[kind] = counters.get(kind, 0) + 1
            finished += 1
            if finished % 100 == 0 or finished == len(pending):
                print(
                    f"metrics {finished}/{len(pending)} ok={counters['ok']} "
                    f"empty={counters['empty']} fail={counters['fail']}",
                    flush=True,
                )


def _covers(path: Path, earliest: str) -> bool:
    if not path.exists() or path.stat().st_size < 1000:
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) < 1000:
        return False
    dates = [str(row.get("date") or "") for row in payload if isinstance(row, dict)]
    return bool(dates) and min(dates) <= earliest


def save_market() -> None:
    """Short windows. A 30-year request is capped at the latest rows."""
    RAW.mkdir(parents=True, exist_ok=True)
    if _covers(RAW / "treasury.json", "1996-01-31") and _covers(RAW / "spy-div.json", "1996-01-31"):
        print("market history cached", flush=True)
        return

    def month_windows() -> list[tuple[str, str]]:
        windows = []
        year, month = 1995, 12
        while (year, month) <= (2026, 10):
            start = date(year, month, 1)
            end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            windows.append((start.isoformat(), end.isoformat()))
            month = 1 if month == 12 else month + 1
            if month == 1 and start.month == 12:
                year += 1
        return windows

    treasury: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        batches = pool.map(
            lambda item: get_json("treasury-rates", {"from": item[0], "to": item[1]}, paced=False)[1],
            month_windows(),
        )
        for batch in batches:
            if not isinstance(batch, list):
                continue
            for row in batch:
                if isinstance(row, dict) and row.get("date"):
                    treasury[str(row["date"])] = row
    if len(treasury) < 1000:
        raise SystemExit(f"treasury too short {len(treasury)}")
    (RAW / "treasury.json").write_text(
        json.dumps([treasury[key] for key in sorted(treasury, reverse=True)]),
        encoding="utf-8",
    )
    print(f"treasury rows={len(treasury)}", flush=True)

    spy: dict[str, dict] = {}
    spans = [(f"{year}-01-01", f"{year + 1}-01-05") for year in range(1995, 2027)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = pool.map(
            lambda item: get_json("historical-price-eod/dividend-adjusted", {
                "symbol": "SPY", "from": item[0], "to": item[1],
            }, paced=False)[1],
            spans,
        )
        for batch in batches:
            if not isinstance(batch, list):
                continue
            for row in batch:
                if isinstance(row, dict) and row.get("date"):
                    spy[str(row["date"])] = row
    if len(spy) < 5000:
        raise SystemExit(f"spy too short {len(spy)}")
    (RAW / "spy-div.json").write_text(
        json.dumps([spy[key] for key in sorted(spy, reverse=True)]),
        encoding="utf-8",
    )
    print(f"spy rows={len(spy)}", flush=True)






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


def cache_path_for(symbol: str) -> Path:
    safe = urllib.parse.quote(symbol, safe="")
    return RAW / "px" / f"{safe}.json"


def fetch_prices(symbols: list[str]) -> None:
    folder = RAW / "px"
    folder.mkdir(parents=True, exist_ok=True)
    pending = [symbol for symbol in symbols if not cache_path_for(symbol).exists()]
    print(f"prices pending={len(pending)} cached={len(symbols) - len(pending)}", flush=True)

    spans = [("1995-01-01", "2005-01-05"), ("2005-01-01", "2015-01-05"), ("2015-01-01", "2026-10-21")]

    def chunked(path: str, symbol: str) -> list | None:
        rows: dict[str, dict] = {}
        for start, end in spans:
            status, payload = get_json(path, {"symbol": symbol, "from": start, "to": end}, paced=False)
            if status != 200 or not isinstance(payload, list):
                return None
            for row in payload:
                if isinstance(row, dict) and row.get("date"):
                    rows[str(row["date"])] = row
        return [rows[key] for key in sorted(rows, reverse=True)]

    def one(symbol: str) -> str:
        # One 30-year request is capped at the latest 5000 sessions.
        # Dividend-adjusted prices are also used to move enterprise value
        # from the fiscal year-end to the buy date. A dividend in that gap
        # nudges the ratio by about that dividend.
        div = chunked("historical-price-eod/dividend-adjusted", symbol)
        if div is None:
            return "fail"
        cache_path_for(symbol).write_text(json.dumps({"div": div}), encoding="utf-8")
        return "ok"

    if not pending:
        return
    ok = 0
    fail = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(one, symbol) for symbol in pending]
        finished = 0
        for future in as_completed(futures):
            if future.result() == "ok":
                ok += 1
            else:
                fail += 1
            finished += 1
            if finished % 200 == 0 or finished == len(pending):
                print(f"prices {finished}/{len(pending)} ok={ok} fail={fail}", flush=True)


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


def rescale(row: dict, light: list[tuple[date, float]]) -> dict | None:
    fiscal_px = last_on_or_before(light, row["fiscal"], 7)
    entry_px = first_on_or_after(light, row["rebalance"], 4)
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


def holding_return(div: list[tuple[date, float]], entry: date, exit_day: date) -> tuple[float, date, date] | None:
    start = first_on_or_after(div, entry, 4)
    end = last_on_or_before(div, exit_day, 10)
    if start is None or end is None or end[0] <= start[0] or start[1] <= 0:
        return None
    return end[1] / start[1] - 1, start[0], end[0]


def wealth_path(returns: list[float]) -> float:
    value = 1.0
    for item in returns:
        value *= 1 + item
    return value


def cagr(value: float, start: date, end: date) -> float:
    days = (end - start).days
    return value ** (365.25 / days) - 1


def max_drawdown(returns: list[float]) -> float:
    value = 1.0
    peak = 1.0
    worst = 0.0
    for item in returns:
        value *= 1 + item
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    LEGACY.mkdir(parents=True, exist_ok=True)
    save_market()
    universe_path = RAW / "universe.json"
    if universe_path.exists():
        universe = {row["symbol"]: row for row in json.loads(universe_path.read_text(encoding="utf-8"))}
        print(f"universe cached={len(universe)}", flush=True)
    else:
        # One list at a time. Overlapping the three exchanges with the
        # delisted pages made the next screener page hang.
        universe = {}
        for name in ("NYSE", "NASDAQ", "AMEX"):
            universe.update(screener(name))
        for symbol, row in delisted_pages().items():
            universe.setdefault(symbol, row)
        universe_path.write_text(json.dumps(list(universe.values())), encoding="utf-8")
        print(f"universe size={len(universe)}", flush=True)

    fetch_metrics(sorted(universe), RAW / "metrics.jsonl")
    book = build_statements(universe)
    spy = load_bars(RAW / "spy-div.json", "adjClose")
    sessions = [day for day, _ in spy]
    treasury = json.loads((RAW / "treasury.json").read_text(encoding="utf-8"))
    yields = []
    for row in treasury:
        day = parse_day(row.get("date"))
        value = num(row.get("month3"))
        if day is not None and value is not None:
            yields.append((day, value / 100.0))
    yields.sort()
    picks = screen(book, yields, sessions)
    symbols = sorted({row["symbol"] for rows in picks.values() for row in rows})
    fetch_prices(symbols)
    prices = {symbol: load_price_pair(symbol) for symbol in symbols}

    yearly = []
    pick_lines = ["year,symbol,sector,spread,ebitda_yield,ev,fiscal,entry,exit,return,early_exit"]
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        rows = picks.get(year) or []
        if not rows:
            continue
        rebalance = rows[0]["rebalance"]
        if year < LAST_YEAR:
            exit_day = session_on_or_after(sessions, date(year + 1, 1, 1))
        else:
            exit_day = sessions[-1] if sessions[-1] <= ASOF else None
        if exit_day is None:
            continue
        refreshed = []
        for row in rows:
            light, div_bars = prices.get(row["symbol"], ([], []))
            scaled = rescale(row, light or div_bars)
            if scaled is not None:
                refreshed.append(scaled)
        refreshed.sort(key=lambda item: item["spread"], reverse=True)
        held = refreshed[:HOLD]
        returns = []
        early = 0
        for row in held:
            _light, div = prices.get(row["symbol"], ([], []))
            result = holding_return(div, row["entry_day"], exit_day)
            if result is None:
                continue
            ret, start, end = result
            if end < exit_day - timedelta(days=10):
                early += 1
                early_flag = "yes"
            else:
                early_flag = "no"
            returns.append(ret)
            sector = universe.get(row["symbol"], {}).get("sector", "")
            pick_lines.append(
                f"{year},{row['symbol']},{sector},{row['spread']:.6f},{row['ebitda_yield_now']:.6f},"
                f"{row['ev_now']:.0f},{row['fiscal'].isoformat()},{start.isoformat()},{end.isoformat()},"
                f"{ret:.6f},{early_flag}"
            )
        spy_start = first_on_or_after(spy, rebalance, 4)
        spy_end = last_on_or_before(spy, exit_day, 4)
        if not returns or spy_start is None or spy_end is None:
            print(f"skip year {year} names={len(returns)}", flush=True)
            continue
        port = sum(returns) / len(returns)
        bench = spy_end[1] / spy_start[1] - 1
        yearly.append({
            "year": year,
            "rebalance": rebalance,
            "exit": exit_day,
            "names": len(returns),
            "early": early,
            "portfolio": port,
            "spy": bench,
        })
        print(
            f"year {year} n={len(returns)} port={port:.1%} spy={bench:.1%} early={early}",
            flush=True,
        )

    completed = [row for row in yearly if row["year"] < LAST_YEAR]
    if not completed:
        raise SystemExit("no completed years")
    port_30 = wealth_path([row["portfolio"] for row in completed])
    spy_30 = wealth_path([row["spy"] for row in completed])
    start_30 = completed[0]["rebalance"]
    end_30 = completed[-1]["exit"]
    port_now = wealth_path([row["portfolio"] for row in yearly])
    spy_now = wealth_path([row["spy"] for row in yearly])
    end_now = yearly[-1]["exit"]

    lines = [
        "US stocks on NYSE, Nasdaq, and NYSE American.",
        "Each January, equal-weight the 50 highest EBITDA/EV minus the 3-month Treasury yield.",
        "EBITDA and the filing lag use the annual figure known 90 days after fiscal year-end.",
        "Enterprise value is rebuilt at the buy date from that report's debt and cash and the buy-date price.",
        "That price is dividend-adjusted, so a dividend between the fiscal year-end and the buy date nudges the value slightly.",
        "Market cap at the buy date at least $100 million. Enterprise value at least $50 million. Currency USD.",
        "The 3-month yield does not change the rank. It is the same number for every stock that day.",
        "Returns use dividend-adjusted prices. No commissions. A name that stops trading is sold at its last price.",
        "Compared with SPY over the same buy and sell dates, also dividend-adjusted.",
        "",
        f"30-year window {start_30.isoformat()} to {end_30.isoformat()}",
        f"strategy growth of $1: {port_30:.2f}",
        f"SPY growth of $1: {spy_30:.2f}",
        f"strategy CAGR: {cagr(port_30, start_30, end_30):.2%}",
        f"SPY CAGR: {cagr(spy_30, start_30, end_30):.2%}",
        f"strategy annual-path drawdown: {max_drawdown([row['portfolio'] for row in completed]):.1%}",
        f"SPY annual-path drawdown: {max_drawdown([row['spy'] for row in completed]):.1%}",
        "",
        f"Through {end_now.isoformat()}",
        f"strategy growth of $1: {port_now:.2f}",
        f"SPY growth of $1: {spy_now:.2f}",
        f"strategy CAGR: {cagr(port_now, start_30, end_now):.2%}",
        f"SPY CAGR: {cagr(spy_now, start_30, end_now):.2%}",
        "",
        "year,portfolio,spy,names,early_exit",
    ]
    for row in yearly:
        lines.append(
            f"{row['year']},{row['portfolio']:.4f},{row['spy']:.4f},{row['names']},{row['early']}"
        )
    text = "\n".join(lines) + "\n"
    (LEGACY / "summary.txt").write_text(text, encoding="utf-8")
    (LEGACY / "picks.csv").write_text("\n".join(pick_lines) + "\n", encoding="utf-8")
    print(text, flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
