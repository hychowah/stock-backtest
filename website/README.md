# January strategy screener

Open `dist/index.html` directly in Chrome or Edge. The page is self-contained: no server, API key, library downloads, or market-data requests are needed.

## Basic workflow

1. Choose **Original candidate set** to retain the original 250-name pre-price screen, or **All stocks with cached prices** for broader filters. The broader set is not the full universe.
2. Enter market-cap bounds and minimum enterprise value in **millions of USD**, minimum EBITDA/EV in **percent**, and optionally a maximum EV/EBITDA multiple, sector or exchange.
3. Choose inclusive book years and ranks. Rank 1 has the highest EBITDA/EV after filtering. Top 50 and Top 100 are shortcuts; ranks 10–20 select up to 11 stocks each year.
4. Click **Run backtest**. Year and rank changes also update the current filters. Reset strategy restores original filters and ranks 1–50 while preserving the chosen years.

The strategy reselects and equally weights stocks every January. Charts, returns, CAGR, growth of $1, median market cap, and stock tables update together. CSV download links export the **current selection**. Sector and exchange are cached company metadata, not historical classifications.

If fewer stocks match than requested, the available picks receive equal weights and short years are listed. A year with no matches displays no strategy return; CAGR and cumulative strategy growth are unavailable for a period containing an empty book. SPY continues to show the full selected period. This is distinct from the CLI's explicitly labelled populated-book compounding. Early stops outside the original top-50 review are flagged when selected.

## Rebuild from saved data

```bash
python3 scripts/research.py prepare
python3 website/build.py
```

Preparation is only needed after changing data or calculation code. The builder queries the compact SQLite database, exports both pools as compact tuples, and embeds them in HTML. Changing screen parameters runs locally in JavaScript without reparsing prices. Stock tables are rendered when a year is opened to avoid creating thousands of hidden rows for large portfolios.

The original top-50 result and tables remain embedded as a fallback for previews that block JavaScript. Interactive screening requires JavaScript. `dist/returns.csv`, `dist/holdings.csv`, and `dist/valuations.json` retain the baseline exports; browser-generated CSV downloads contain the selected strategy. The original canonical report remains `../results/summary-exits.txt` and is never overwritten by screening.

The 2026 book is partial through 20 October 2026. Other book years are January-to-January, not calendar-year returns. Strategy and SPY returns in the interactive screener use full-precision prepared values.

## Checks

```bash
node tests/check-range.cjs
python3 tests/check_screener.py
```

The first checks controls and rendering using a simulated DOM. The second compares browser selection directly with SQLite across eight configurations, including short and empty years. It requires the current prepared database. These checks do not replace a real-browser appearance check.

A private Sites project is registered in `.openai/hosting.json`. Hosted publication remains blocked by source-host access from this environment. Preserve the project ID when retrying.
