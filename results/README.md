# Backtest reports

- `summary-exits.txt` is the current result: holdings that stop trading are retained at the last available price, with explicitly identified bankruptcies treated as total losses.
- `stops/` contains early-stop listings and SEC filing classifications used in the exit review. Classification flags are clues, not automatic bankruptcy decisions.
- `legacy/summary.txt` and `legacy/picks.csv` use the older exit rule. They are preserved for comparison and are not the latest report or latest holdings.

Recompute the current report with `python3 scripts/revalue.py` from the project folder. This reads the cache and does not download data. Website holdings exports are under `website/dist/` and are checked against the current report.
