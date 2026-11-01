"""Probe FMP bulk shapes. Does not print the key or the request URL."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY = None

def _key():
    global KEY
    if KEY is None:
        KEY = Path.home().joinpath(".grok", "secrets", "fmp_api_key").read_text(encoding="utf-8").strip()
    return KEY
BASE = "https://financialmodelingprep.com/stable/"


def fetch(path: str, params: dict) -> tuple[int, str, bytes]:
    query = dict(params)
    query["apikey"] = _key()
    url = BASE + path + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={"Accept": "application/json, text/csv, */*"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read()
            ctype = response.headers.get("Content-Type", "")
            return int(response.status), ctype, body
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return int(exc.code), exc.headers.get("Content-Type", ""), body


def show(label: str, path: str, params: dict) -> None:
    print(f"requesting {label}", flush=True)
    status, ctype, body = fetch(path, params)
    text = body[:600].decode("utf-8", errors="replace")
    text = text.replace(KEY, "[key]")
    print(f"--- {label} status={status} type={ctype} bytes={len(body)}")
    print(text.replace("\r", ""))
    print()


def main():
    import sys
    if any(value in ("-h", "--help") for value in sys.argv[1:]):
        print(__doc__)
        return
    import sys

    which = sys.argv[1] if len(sys.argv) > 1 else "metrics"
    if which == "metrics":
        show("key-metrics FY 2023", "key-metrics-bulk", {"year": "2023", "period": "FY"})
    elif which == "income":
        show("income FY 2023", "income-statement-bulk", {"year": "2023", "period": "FY"})
    elif which == "profile":
        show("profile part 0", "profile-bulk", {"part": "0"})
    else:
        raise SystemExit("use metrics, income, or profile")


if __name__ == "__main__":
    main()
