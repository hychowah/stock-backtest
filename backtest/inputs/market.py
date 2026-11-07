"""Stable saved price-file names. No network access."""
from pathlib import Path
import urllib.parse

from backtest.paths import RAW


def cache_path_for(symbol: str) -> Path:
    safe = urllib.parse.quote(symbol, safe="")
    return RAW / "px" / f"{safe}.json"
