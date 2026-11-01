"""Stream one FMP bulk file to disk and print bytes as they arrive.

Does not print the key or the URL.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "raw" / "archive"
KEY = None

def _key():
    global KEY
    if KEY is None:
        KEY = Path.home().joinpath(".grok", "secrets", "fmp_api_key").read_text(encoding="utf-8").strip()
    return KEY
BASE = "https://financialmodelingprep.com/stable/"

JOBS = {
    "metrics": ("key-metrics-bulk", {"year": "2023", "period": "FY"}, "key-metrics-2023.csv"),
    "income": ("income-statement-bulk", {"year": "2023", "period": "FY"}, "income-2023.csv"),
    "profile": ("profile-bulk", {"part": "0"}, "profile-part0.csv"),
}


def main() -> None:
    import sys
    if any(value in ("-h", "--help") for value in sys.argv[1:]):
        print(__doc__)
        return
    which = sys.argv[1] if len(sys.argv) > 1 else "metrics"
    path, params, name = JOBS[which]
    query = dict(params)
    query["apikey"] = _key()
    url = BASE + path + "?" + urllib.parse.urlencode(query)
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / name
    print(f"start {which} -> {dest.name}", flush=True)
    request = urllib.request.Request(url, headers={"Accept": "text/csv, application/json, */*"})
    try:
        response = urllib.request.urlopen(request, timeout=180)
    except urllib.error.HTTPError as exc:
        err = exc.read(400).decode("utf-8", errors="replace").replace(KEY, "[key]")
        print(f"http {exc.code} {err}", flush=True)
        return
    got = 0
    with response, dest.open("wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
            got += len(chunk)
            print(f"bytes {got}", flush=True)
    print(f"done {got}", flush=True)


if __name__ == "__main__":
    main()
