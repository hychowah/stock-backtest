"""Independent original screening, price arithmetic and legacy report."""
from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path
import json
import urllib.parse
from backtest.paths import RAW, LEGACY
from backtest.financial.rules import (FIRST_YEAR, LAST_YEAR, ASOF, MIN_MARKET_CAP, MIN_EV, BUFFER, HOLD, LAG, MAX_AGE, parse_day, num, latest_statement)
from backtest.inputs.market import load_bars, asof_yield, session_on_or_after, cache_path_for, load_price_pair

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
    from backtest.inputs.legacy_downloads import save_market, screener, delisted_pages, fetch_metrics, fetch_prices
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
