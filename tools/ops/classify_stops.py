"""Find the SEC filings path, then classify each early stop."""

from __future__ import annotations


import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from backtest.inputs import legacy_downloads
from backtest.financial import rules
from backtest.inputs import market, fmp_download, cache_assets
from backtest.engines.reference import legacy

from backtest.paths import STOPS
MERGER_PREFIXES = (
    "DEFM14A", "PREM14A", "DEFM14C", "PREM14C",
    "S-4", "SC TO", "SC 14D9", "425", "SC 13E3",
)


def load_forms(path: str, params: dict) -> tuple[int, object]:
    return legacy_downloads.get_json(path, params, paced=False)


def filings(symbol: str, start: str, end: str) -> list[dict]:
    rows_out = []
    for page in range(4):
        status, rows = load_forms("sec-filings-search/symbol", {
            "symbol": symbol,
            "from": start,
            "to": end,
            "page": str(page),
            "limit": "100",
        })
        if not isinstance(rows, list) or not rows:
            break
        rows_out.extend(row for row in rows if isinstance(row, dict))
        if len(rows) < 100:
            break
    return rows_out


def is_merger(kinds: set[str]) -> bool:
    for kind in kinds:
        if kind == "425" or any(kind.startswith(prefix) for prefix in MERGER_PREFIXES if prefix != "425"):
            return True
    return False


def main() -> None:
    import sys
    if any(value in ("-h", "--help") for value in sys.argv[1:]):
        print(__doc__)
        return
    STOPS.mkdir(parents=True, exist_ok=True)
    status, sample = load_forms("sec-filings-search/symbol", {
        "symbol": "OA", "from": "2018-01-01", "to": "2018-07-01", "limit": "5",
    })
    print("path status", status, "type", type(sample).__name__, flush=True)
    if not isinstance(sample, list):
        print(str(sample)[:200], flush=True)
        return
    stops = json.loads((STOPS / "stops.json").read_text(encoding="utf-8"))

    def one(row: dict) -> dict:
        last = row["last"] or row["entry"]
        start_day = datetime.strptime(row["entry"], "%Y-%m-%d").date() - timedelta(days=200)
        end_day = datetime.strptime(last, "%Y-%m-%d").date() + timedelta(days=45)
        docs = filings(row["symbol"], start_day.isoformat(), end_day.isoformat())
        kinds = {str(doc.get("formType") or "") for doc in docs}
        row = dict(row)
        row["merger"] = is_merger(kinds)
        row["forms"] = sorted(kind for kind in kinds if kind)[:12]
        return row

    done = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(one, row) for row in stops]
        for future in as_completed(futures):
            row = future.result()
            done.append(row)
            label = "acquisition" if row["merger"] else "not merger filing"
            print(f"{row['year']} {row['symbol']:8} {label} forms={','.join(row['forms'][:8])}", flush=True)
    done.sort(key=lambda item: (item["year"], item["symbol"]))
    (STOPS / "stops-class.json").write_text(json.dumps(done, indent=1), encoding="utf-8")
    print("merger", sum(1 for row in done if row["merger"]), "other", sum(1 for row in done if not row["merger"]), flush=True)


if __name__ == "__main__":
    main()
