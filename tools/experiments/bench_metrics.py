"""Time 24 key-metrics calls at a small concurrency."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

KEY = None

def _key():
    global KEY
    if KEY is None:
        KEY = Path.home().joinpath(".grok", "secrets", "fmp_api_key").read_text(encoding="utf-8").strip()
    return KEY
BASE = "https://financialmodelingprep.com/stable/"
RAW = Path(__file__).resolve().parents[2] / "raw"


def one(symbol: str) -> str:
    params = {"symbol": symbol, "period": "annual", "limit": "40", "apikey": _key()}
    url = BASE + "key-metrics?" + urllib.parse.urlencode(params)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as response:
            body = response.read()
            status = response.status
    except Exception as exc:
        return f"{symbol} {type(exc).__name__} {time.perf_counter() - started:.1f}s"
    payload = json.loads(body.decode("utf-8"))
    n = len(payload) if isinstance(payload, list) else -1
    return f"{symbol} {status} rows={n} {time.perf_counter() - started:.1f}s bytes={len(body)}"


def main():
    import sys
    if any(value in ("-h", "--help") for value in sys.argv[1:]):
        print(__doc__)
        return
    universe = json.loads((RAW / "universe.json").read_text(encoding="utf-8"))
    symbols = [row["symbol"] for row in universe[24:88]]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=16) as pool:
        for line in pool.map(one, symbols):
            print(line, flush=True)
    print(f"elapsed {time.perf_counter() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
