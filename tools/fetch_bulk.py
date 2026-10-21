"""Download FMP bulk files concurrently.

US annual fundamentals for fiscal 1994-2025, company profiles, Treasury
yields, and SPY. Writes raw files. Does not print the key or the URL.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "raw" / "archive"
KEY = Path.home().joinpath(".grok", "secrets", "fmp_api_key").read_text(encoding="utf-8").strip()
BASE = "https://financialmodelingprep.com/stable/"
WORKERS = 16
YEARS = range(1994, 2026)


def jobs() -> list[tuple[str, dict, str]]:
    work: list[tuple[str, dict, str]] = []
    for year in YEARS:
        work.append(("key-metrics-bulk", {"year": str(year), "period": "FY"}, f"key-metrics-{year}.csv"))
        work.append(("income-statement-bulk", {"year": str(year), "period": "FY"}, f"income-{year}.csv"))
    for part in range(0, 40):
        work.append(("profile-bulk", {"part": str(part)}, f"profile-{part}.csv"))
    for page in range(0, 80):
        work.append(("delisted-companies", {"page": str(page), "limit": "100"}, f"delisted-{page}.json"))
    work.append(("treasury-rates", {"from": "1995-12-01", "to": "2026-10-21"}, "treasury.json"))
    work.append(
        (
            "historical-price-eod/dividend-adjusted",
            {"symbol": "SPY", "from": "1995-12-01", "to": "2026-10-21"},
            "spy-div.json",
        )
    )
    work.append(
        (
            "historical-price-eod/light",
            {"symbol": "SPY", "from": "1995-12-01", "to": "2026-10-21"},
            "spy-light.json",
        )
    )
    return work


def looks_done(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 200:
        return False
    with path.open("rb") as handle:
        head = handle.read(180).lstrip()
    if head.startswith(b"{") or head.startswith(b"["):
        # A short JSON error body is not a finished bulk file.
        if path.stat().st_size < 500 and (b"Error" in head or b"error" in head or b"Restricted" in head):
            return False
    return True


def fetch_one(path: str, params: dict, name: str) -> str:
    dest = OUT / name
    if looks_done(dest):
        return f"skip {name}"
    query = dict(params)
    query["apikey"] = KEY
    url = BASE + path + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={"Accept": "text/csv, application/json, */*"})
    last = "fail"
    for attempt in range(5):
        try:
            response = urllib.request.urlopen(request, timeout=180)
        except urllib.error.HTTPError as exc:
            body = exc.read(240).decode("utf-8", errors="replace").replace(KEY, "[key]")
            if exc.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(1.5 * (attempt + 1))
                continue
            # Profile parts past the end are empty on purpose.
            if exc.code in (400, 404) and (name.startswith("profile-") or name.startswith("delisted-")):
                dest.write_text("", encoding="utf-8")
                return f"empty {name} http {exc.code}"
            return f"fail {name} http {exc.code} {body[:160]}"
        except Exception as exc:
            last = f"fail {name} {type(exc).__name__}"
            if attempt < 4:
                time.sleep(1.5 * (attempt + 1))
                continue
            return last
        part = dest.with_suffix(dest.suffix + ".part")
        got = 0
        try:
            with response, part.open("wb") as handle:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    handle.write(chunk)
                    got += len(chunk)
        except Exception as exc:
            part.unlink(missing_ok=True)
            last = f"fail {name} {type(exc).__name__} after {got}"
            if attempt < 4:
                time.sleep(1.5 * (attempt + 1))
                continue
            return last
        if got < 200:
            text = part.read_text(encoding="utf-8", errors="replace").replace(KEY, "[key]")
            if name.startswith("profile-") or text.strip() in ("", "[]", "{}"):
                part.unlink(missing_ok=True)
                dest.write_text("", encoding="utf-8")
                return f"empty {name}"
            part.replace(dest)
            return f"ok {name} {got}"
        part.replace(dest)
        return f"ok {name} {got}"
    return last


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    work = jobs()
    print(f"start {len(work)} files workers={WORKERS}", flush=True)
    ok = 0
    bad = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(fetch_one, path, params, name) for path, params, name in work]
        for done, future in enumerate(as_completed(futures), start=1):
            line = future.result()
            if line.startswith("ok") or line.startswith("skip") or line.startswith("empty"):
                ok += 1
            else:
                bad += 1
                print(line, flush=True)
            if done % 10 == 0 or done == len(work):
                print(f"progress {done}/{len(work)} good={ok} bad={bad}", flush=True)
    if bad:
        print(f"FAILED good={ok} bad={bad}", flush=True)
    else:
        print(f"DONE good={ok} bad={bad}", flush=True)


if __name__ == "__main__":
    main()
