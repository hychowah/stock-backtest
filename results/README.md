# Backtest reports

- `summary-exits.txt` is the current result: holdings that stop trading are retained at the last available price, with explicitly identified bankruptcies treated as total losses.
- `stops/` contains early-stop listings and SEC filing classifications used in the exit review. Classification flags are clues, not automatic bankruptcy decisions.
- `legacy/summary.txt` and `legacy/picks.csv` use the older exit rule. They are preserved for comparison and are not the latest report or latest holdings.

Recompute the current report with `python3 scripts/revalue.py` from the project folder. This forces preparation and compares the SQL and independent engines at the saved Through date. Agreement updates the report/database pair. Disagreement stops publication. This reads the cache and does not download data. Website holdings exports are under `website/dist/` and are checked against the current report.

`baseline-history/<generation>/` stores local revision evidence and is ignored by
Git. Each historical revision retains the previous report verbatim, previous and
new priced snapshots, a current report copy and `audit.json`. First-run prices
that older files did not retain are marked unavailable. Export the audit from
Manage backtest data after a check or rebuild. Later saved sessions can advance
latest screening without extending the historical report.
