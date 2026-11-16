# Backtest reports

The January study's reports are a frozen record. Nothing regenerates, collects
or changes them.

- `summary-exits.txt` is the study result: holdings that stop trading are retained at the last available price, with explicitly identified bankruptcies treated as total losses. Its 2026 row is marked through its Through date.
- `stops/` contains early-stop listings and SEC filing classifications used in the exit review. Classification flags are clues, not automatic bankruptcy decisions. The merger flag in `stops/stops-class.json` is broad.
- `legacy/summary.txt` and `legacy/picks.csv` use the older exit rule. They are preserved for comparison and are not the study result.

The study was produced by the earlier Python product, whose last source is at
the Git tag `python-oracle`. The
[methodology](../docs/methodology.md#the-january-study-19962026) describes it.
