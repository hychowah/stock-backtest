# Backtest reports

The January study's reports are a frozen record. Nothing regenerates, collects
or changes them.

- `summary-exits.txt` is the study result: holdings that stop trading are retained at the last available price, with explicitly identified bankruptcies treated as total losses. Its 2026 row is marked through its Through date.
- `stops/` contains early-stop listings and SEC filing classifications used in the exit review. Classification flags are clues, not automatic bankruptcy decisions.
- `legacy/summary.txt` and `legacy/picks.csv` use the older exit rule. They are preserved for comparison and are not the study result.
- `baseline-history/<generation>/` is ignored by Git and stays on the runtime. Each revision there retains the report that an earlier preparation replaced, its priced snapshots and `audit.json`.

Run the study again as a custom schedule every 12 months from 1 January. On a
real-data copy, `python3 scripts/check.py` compares that run with the
independent reference engine and with `summary-exits.txt`.

`experiments/` holds small cited experiment summaries.
