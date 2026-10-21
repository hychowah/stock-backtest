# Annual return website

Open `dist/index.html` directly in a browser. The page is self-contained and makes no market-data or external library requests.

The chart and CSV use the current `../results/summary-exits.txt`, including the last-price exit rule. The 2026 row is partial through 20 October 2026. Each other row represents the January-to-January book, not a calendar-year return.

To refresh the chart and CSV after recomputing results:

```
python3 website/build.py
```

The headline 30-year statistics and methodology in `template.html` describe the current saved pass; update those if the backtest assumptions or headline results change.

A private Sites project is registered in `.openai/hosting.json`. Publication did not complete because this environment could not resolve the source hosting server. Reuse that project ID when retrying; do not create another Site.

## Valuations and holdings

The build reconstructs each year's selected holdings from the cached universe, metrics and prices, using `scripts/run.py` selection helpers and the current `scripts/revalue.py` exit rules. It checks the holding counts and mean returns against `results/summary-exits.txt` before writing the page. It never reads the older `picks.csv`.

The median chart and expandable year summaries show market capitalization at purchase in nominal US dollars. The median is the average of the middle two market caps for the 50 holdings. Individual rows also include EBITDA/EV and EV/EBITDA. Basic company metadata comes from the cached universe and is not point-in-time; absent sectors are marked unavailable. `dist/holdings.csv` exports all holdings and `dist/valuations.json` contains the underlying valuation data. The chart and expandable tables are embedded in HTML and work without JavaScript; the year selector and return-chart toggles require JavaScript.

`scripts/run.py` now reads the FMP key only when an API request is made, so cache-only builds no longer require a key file.

## Selected periods

Use From and To to choose inclusive book years. The default is 1996–2025, the 30 completed January books; 2026 is available as a partial book. Selecting 2015–2020 shows six books, from January 2015 to January 2021. Controls update both charts, return rows, visible holding years, CAGR and growth of $1. Strategy statistics compound the full-precision selected stock returns; SPY uses rounded annual returns from the saved summary. Small differences from original headline totals are possible. CSV links continue to download all years.

Check range calculations and DOM updates with `node tests/check-range.cjs` from the project folder. This check uses a simulated DOM; it does not replace a real browser appearance check.

## Selected ranks

Ranks controls select an inclusive slice of each year's original top 50, ordered by EBITDA/EV at purchase. For example, 10–20 means 11 stocks, equally weighted and reselected each January. Rank 1 is the highest EBITDA/EV. Both charts, annual strategy returns, compounded performance, median market caps and visible stock rows update for the selected slice and years. SPY remains the benchmark for the same period. Strategy statistics use full-precision cached stock returns; SPY uses rounded saved annual returns. “All 50” resets ranks independently of the year range. CSV downloads retain all ranks and years.
