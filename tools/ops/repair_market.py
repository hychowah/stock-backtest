"""Refetch Treasury yields and SPY in short windows. The full-range calls were capped."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "raw"
KEY = None

def _key():
    global KEY
    if KEY is None:
        KEY = Path.home().joinpath(".grok", "secrets", "fmp_api_key").read_text(encoding="utf-8").strip()
    return KEY
BASE = "https://financialmodelingprep.com/stable/"


def get(path: str, params: dict) -> list:
    query = dict(params)
    query["apikey"] = _key()
    url = BASE + path + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(path)
    return payload


def months() -> list[tuple[str, str]]:
    windows = []
    year, month = 1995, 12
    while (year, month) <= (2026, 10):
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        windows.append((start.isoformat(), end.isoformat()))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return windows


def years() -> list[tuple[str, str]]:
    return [(f"{year}-01-01", f"{year + 1}-01-05") for year in range(1995, 2027)]


def main() -> None:
    import sys
    if any(value in ("-h", "--help") for value in sys.argv[1:]):
        print(__doc__)
        return
    windows = months()
    with ThreadPoolExecutor(max_workers=12) as pool:
        batches = list(pool.map(lambda item: get("treasury-rates", {"from": item[0], "to": item[1]}), windows))
    treasury = {}
    for batch in batches:
        for row in batch:
            treasury[row["date"]] = row
    rows = [treasury[key] for key in sorted(treasury, reverse=True)]
    (RAW / "treasury.json").write_text(json.dumps(rows), encoding="utf-8")
    print(f"treasury {len(rows)} {rows[-1]['date']} {rows[0]['date']}", flush=True)

    spans = years()
    with ThreadPoolExecutor(max_workers=8) as pool:
        spy_batches = list(pool.map(
            lambda item: get("historical-price-eod/dividend-adjusted", {
                "symbol": "SPY", "from": item[0], "to": item[1],
            }),
            spans,
        ))
    spy = {}
    for batch in spy_batches:
        for row in batch:
            spy[row["date"]] = row
    spy_rows = [spy[key] for key in sorted(spy, reverse=True)]
    (RAW / "spy-div.json").write_text(json.dumps(spy_rows), encoding="utf-8")
    print(f"spy {len(spy_rows)} {spy_rows[-1]['date']} {spy_rows[0]['date']}", flush=True)


if __name__ == "__main__":
    main()
