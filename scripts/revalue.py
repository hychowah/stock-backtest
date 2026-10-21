"""Revalue the book. A trading stop is an acquisition or redemption at the last price.

A bankruptcy would be a total loss. None of the stops is marked that way
until a bankruptcy filing is identified.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import run

from paths import RAW, RESULTS
# Filled after the filing check. Symbol-year pairs that are bankruptcies.
BANKRUPT: set[tuple[int, str]] = set()


def last_in_window(div, entry: date, exit_day: date):
    last = None
    for day, price in div:
        if entry <= day <= exit_day:
            last = (day, price)
    return last


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    universe = {row["symbol"]: row for row in json.loads((RAW / "universe.json").read_text(encoding="utf-8"))}
    book = run.build_statements(universe)
    spy = run.load_bars(RAW / "spy-div.json", "adjClose")
    sessions = [day for day, _ in spy]
    treasury = json.loads((RAW / "treasury.json").read_text(encoding="utf-8"))
    yields = []
    for row in treasury:
        day = run.parse_day(row.get("date"))
        value = run.num(row.get("month3"))
        if day is not None and value is not None:
            yields.append((day, value / 100.0))
    yields.sort()
    picks = run.screen(book, yields, sessions)
    symbols = sorted({row["symbol"] for rows in picks.values() for row in rows})
    prices = {symbol: run.load_price_pair(symbol) for symbol in symbols}

    yearly = []
    stopped_rows = []
    bankrupt_rows = []
    for year in range(run.FIRST_YEAR, run.LAST_YEAR + 1):
        rows = picks.get(year) or []
        if not rows:
            continue
        rebalance = rows[0]["rebalance"]
        if year < run.LAST_YEAR:
            exit_day = run.session_on_or_after(sessions, date(year + 1, 1, 1))
        else:
            exit_day = sessions[-1]
        refreshed = []
        for row in rows:
            light, div_bars = prices.get(row["symbol"], ([], []))
            scaled = run.rescale(row, light or div_bars)
            if scaled is not None:
                refreshed.append(scaled)
        refreshed.sort(key=lambda item: item["spread"], reverse=True)
        returns = []
        n_stop = 0
        n_bust = 0
        for row in refreshed[: run.HOLD]:
            _light, div = prices.get(row["symbol"], ([], []))
            start = run.first_on_or_after(div, row["entry_day"], 4)
            if start is None:
                continue
            scheduled = run.last_on_or_before(div, exit_day, 10)
            if scheduled is not None and (year, row["symbol"]) not in BANKRUPT:
                returns.append(scheduled[1] / start[1] - 1)
                continue
            if (year, row["symbol"]) in BANKRUPT:
                returns.append(-1.0)
                n_bust += 1
                bankrupt_rows.append((year, row["symbol"]))
                continue
            last = last_in_window(div, start[0], exit_day)
            if last is None:
                continue
            ret = last[1] / start[1] - 1
            returns.append(ret)
            n_stop += 1
            stopped_rows.append((year, row["symbol"], last[0].isoformat(), ret))
        spy_start = run.first_on_or_after(spy, rebalance, 4)
        spy_end = run.last_on_or_before(spy, exit_day, 4)
        port = sum(returns) / len(returns)
        bench = spy_end[1] / spy_start[1] - 1
        yearly.append({
            "year": year,
            "rebalance": rebalance,
            "exit": exit_day,
            "names": len(returns),
            "stopped": n_stop,
            "bust": n_bust,
            "portfolio": port,
            "spy": bench,
        })
        print(
            f"year {year} n={len(returns)} stop={n_stop} bust={n_bust} "
            f"port={port:.1%} spy={bench:.1%}",
            flush=True,
        )

    completed = [row for row in yearly if row["year"] < run.LAST_YEAR]
    port_30 = run.wealth_path([row["portfolio"] for row in completed])
    spy_30 = run.wealth_path([row["spy"] for row in completed])
    start_30 = completed[0]["rebalance"]
    end_30 = completed[-1]["exit"]
    port_now = run.wealth_path([row["portfolio"] for row in yearly])
    spy_now = run.wealth_path([row["spy"] for row in yearly])
    end_now = yearly[-1]["exit"]
    lines = [
        "Trading that stops before the January sale is kept.",
        "If the shares were acquired or redeemed, the exit is the last price.",
        "A bankruptcy would be entered as a total loss. This pass found no bankruptcy among the stops.",
        f"Stops kept at the last price: {len(stopped_rows)}",
        f"Bankruptcies at -100%: {len(bankrupt_rows)}",
        "",
        f"30-year window {start_30.isoformat()} to {end_30.isoformat()}",
        f"strategy growth of $1: {port_30:.2f}",
        f"SPY growth of $1: {spy_30:.2f}",
        f"strategy CAGR: {run.cagr(port_30, start_30, end_30):.2%}",
        f"SPY CAGR: {run.cagr(spy_30, start_30, end_30):.2%}",
        "",
        f"Through {end_now.isoformat()}",
        f"strategy growth of $1: {port_now:.2f}",
        f"SPY growth of $1: {spy_now:.2f}",
        f"strategy CAGR: {run.cagr(port_now, start_30, end_now):.2%}",
        f"SPY CAGR: {run.cagr(spy_now, start_30, end_now):.2%}",
        "",
        "year,portfolio,spy,names,stopped,bankrupt",
    ]
    for row in yearly:
        lines.append(
            f"{row['year']},{row['portfolio']:.4f},{row['spy']:.4f},{row['names']},{row['stopped']},{row['bust']}"
        )
    text = "\n".join(lines) + "\n"
    (RESULTS / "summary-exits.txt").write_text(text, encoding="utf-8")
    print(text, flush=True)
    print("stopped detail", flush=True)
    for item in stopped_rows:
        print(f"  {item[0]} {item[1]:8} last={item[2]} ret={item[3]:.1%}", flush=True)


if __name__ == "__main__":
    main()
