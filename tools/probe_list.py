"""Confirm the symbol-list endpoints. Prints counts and keys only."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

KEY = Path.home().joinpath(".grok", "secrets", "fmp_api_key").read_text(encoding="utf-8").strip()
BASE = "https://financialmodelingprep.com/stable/"


def get(path: str, params: dict) -> tuple[int, object]:
    params = dict(params)
    params["apikey"] = KEY
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
        status = response.status
    try:
        return status, json.loads(body.decode("utf-8"))
    except Exception:
        return status, body[:200]


def brief(label: str, status: int, payload: object) -> None:
    if isinstance(payload, list):
        keys = sorted(payload[0].keys()) if payload else []
        print(f"{label} status={status} n={len(payload)} keys={keys}", flush=True)
    elif isinstance(payload, dict):
        print(f"{label} status={status} dict_keys={list(payload)[:8]}", flush=True)
    else:
        print(f"{label} status={status} type={type(payload).__name__}", flush=True)


if __name__ == "__main__":
    brief("nyse", *get("company-screener", {
        "exchange": "NYSE", "isEtf": "false", "isFund": "false",
        "isActivelyTrading": "true", "limit": "1000", "page": "0",
    }))
    brief("delisted", *get("delisted-companies", {"page": "0", "limit": "1000"}))
    status, page1 = get("company-screener", {
        "exchange": "NYSE", "isEtf": "false", "isFund": "false",
        "isActivelyTrading": "true", "limit": "1000", "page": "1",
    })
    brief("nyse-page1", status, page1)
    _, page0 = get("company-screener", {
        "exchange": "NYSE", "isEtf": "false", "isFund": "false",
        "isActivelyTrading": "true", "limit": "1000", "page": "0",
    })
    s0 = {row["symbol"] for row in page0}
    s1 = {row["symbol"] for row in page1}
    print(f"overlap page0-page1 {len(s0 & s1)}", flush=True)
    brief("delisted-80", *get("delisted-companies", {"page": "80", "limit": "100"}))
    brief("delisted-200", *get("delisted-companies", {"page": "200", "limit": "100"}))
    brief("nasdaq-p4", *get("company-screener", {
        "exchange": "NASDAQ", "isEtf": "false", "isFund": "false",
        "isActivelyTrading": "true", "limit": "1000", "page": "4",
    }))
