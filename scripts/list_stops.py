"""List holdings whose price stops more than 10 days before the January sale."""

from __future__ import annotations

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))

import json
from datetime import timedelta

from backtest.financial import rules
from backtest.inputs import market, fmp_download, cache_assets
from backtest.engines.reference import legacy

from backtest.paths import RAW, STOPS


def main() -> None:
    STOPS.mkdir(parents=True, exist_ok=True)
    universe = {row["symbol"]: row for row in json.loads((RAW / "universe.json").read_text(encoding="utf-8"))}
    book = legacy.build_statements(universe)
    spy = market.load_bars(RAW / "spy-div.json", "adjClose")
    sessions = [day for day, _ in spy]
    treasury = json.loads((RAW / "treasury.json").read_text(encoding="utf-8"))
    yields = []
    for row in treasury:
        day = rules.parse_day(row.get("date"))
        value = rules.num(row.get("month3"))
        if day is not None and value is not None:
            yields.append((day, value / 100.0))
    yields.sort()
    picks = legacy.screen(book, yields, sessions)
    symbols = sorted({row["symbol"] for rows in picks.values() for row in rows})
    prices = {symbol: market.load_price_pair(symbol) for symbol in symbols}
    stops = []
    for year, rows in picks.items():
        if not rows:
            continue
        if year < rules.LAST_YEAR:
            exit_day = market.session_on_or_after(sessions, legacy.date(year + 1, 1, 1))
        else:
            exit_day = sessions[-1]
        refreshed = []
        for row in rows:
            light, div_bars = prices.get(row["symbol"], ([], []))
            scaled = legacy.rescale(row, light or div_bars)
            if scaled is not None:
                refreshed.append(scaled)
        refreshed.sort(key=lambda item: item["spread"], reverse=True)
        for row in refreshed[: rules.HOLD]:
            _light, div = prices.get(row["symbol"], ([], []))
            result = legacy.holding_return(div, row["entry_day"], exit_day)
            last = None
            for day, price in div:
                if row["entry_day"] <= day <= exit_day:
                    last = (day, price)
            if result is None:
                stops.append({
                    "year": year,
                    "symbol": row["symbol"],
                    "entry": row["entry_day"].isoformat(),
                    "exit": exit_day.isoformat(),
                    "last": last[0].isoformat() if last else "",
                    "last_px": last[1] if last else None,
                    "listed": bool(universe.get(row["symbol"], {}).get("listed")),
                    "name": universe.get(row["symbol"], {}).get("name", ""),
                })
    (STOPS / "stops.json").write_text(json.dumps(stops, indent=1), encoding="utf-8")
    print(f"stops {len(stops)}", flush=True)
    for row in stops:
        print(f"{row['year']} {row['symbol']:8} last={row['last'] or 'none':10} listed={row['listed']} {row['name'][:40]}", flush=True)


if __name__ == "__main__":
    main()
