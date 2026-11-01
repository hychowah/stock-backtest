"""See which date parameters return a full history."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

KEY = None

def _key():
    global KEY
    if KEY is None:
        KEY = Path.home().joinpath(".grok", "secrets", "fmp_api_key").read_text(encoding="utf-8").strip()
    return KEY
BASE = "https://financialmodelingprep.com/stable/"


def get_abs(url_base: str, params: dict) -> object:
    params = dict(params)
    params["apikey"] = _key()
    url = url_base + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def get(path: str, params: dict) -> object:
    params = dict(params)
    params["apikey"] = _key()
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def span(label: str, payload: object) -> None:
    if not isinstance(payload, list) or not payload:
        print(label, type(payload).__name__, str(payload)[:120].replace(KEY, "[key]"), flush=True)
        return
    print(label, "n", len(payload), payload[0].get("date"), payload[-1].get("date"), flush=True)


def main():
    import sys
    if any(value in ("-h", "--help") for value in sys.argv[1:]):
        print(__doc__)
        return
    span("t-short", get("treasury-rates", {"from": "1996-01-01", "to": "1996-01-31"}))
    span("t-v4", get_abs("https://financialmodelingprep.com/api/v4/treasury", {"from": "1996-01-01", "to": "1996-01-31"}))


if __name__ == "__main__":
    main()
