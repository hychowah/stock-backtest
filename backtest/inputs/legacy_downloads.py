"""Retained original cache acquisition. Invoked only by its explicit command."""
from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path
import json
import urllib.parse
from backtest.paths import RAW
import threading
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from backtest.financial.rules import common_stock, us_exchange
from backtest.inputs.cache_assets import financial_record
from backtest.inputs.market import cache_path_for
from backtest.inputs import fmp_download
WORKERS=16
STARTS_PER_SEC=12
_lock=threading.Lock()
_next_start=0.0
_pause_until=0.0

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
    query["apikey"] = fmp_download.KEY_PATH.read_text(encoding="utf-8").strip()
    url = fmp_download.BASE + path + "?" + urllib.parse.urlencode(query)
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
