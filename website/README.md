# January strategy screener

Open `dist/index.html` directly in Chrome or Edge. The page is self-contained: no server, API key, library downloads, or market-data requests are needed.

## Basic workflow

1. Choose **Latest stock picks** or **Historical backtest**, then choose **Original candidate set** to retain the original 250-name pre-price screen, or **All stocks with cached prices** for broader filters. The broader set is not the full universe.
2. Choose a ranking metric (EV/EBITDA is the default). Enter market-cap bounds and minimum enterprise value in **millions of USD**, minimum selected metric yield in **percent**, and optionally a maximum selected multiple, sector or exchange.
3. Choose inclusive ranks in either mode, and book years in historical mode. Rank 1 has the lowest selected valuation multiple after filtering. Top 50 and Top 100 are shortcuts; ranks 10–20 select up to 11 stocks each year.
4. Click **Screen latest** or **Run backtest** for the chosen mode. Year and rank changes also update the current filters. Reset strategy restores original filters and ranks 1–50 while preserving the chosen years.

In historical mode, the strategy reselects and equally weights stocks every January. Charts, returns, CAGR, growth of $1, median market cap, and stock tables update together. CSV download links export the **current selection**. Sector and exchange are cached company metadata, not historical classifications.

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

The first checks controls and rendering using a simulated DOM. The second compares browser selection directly with SQLite across nine historical and seven latest configurations, including short and empty years. It requires the current prepared database. These checks do not replace a real-browser appearance check.

A private Sites project is registered in `.openai/hosting.json`. Hosted publication remains blocked by source-host access from this environment. Preserve the project ID when retrying.

## Per-year return contributions

The latest selected year opens automatically in Explore the selected stocks. Choose another year or expand its entry to see gain/loss contribution pies, the top 10 contributors, and the full stock table. These views update with the current screen and rank range.

Contribution equals stock holding return divided by the actual number of selected stocks, expressed in percentage points of portfolio return. Contributions sum to the year's strategy return. Top 10 means the ten stocks with the highest signed contributions, regardless of portfolio size. If fewer than ten stocks are selected, all of them are shown. In an all-loss book, these are the smallest losses. This is historical attribution, not a new picking rule.

Gains and losses use separate pie charts so no negative slice is implied. Each pie is normalized to that side's total; it is not a percentage of the net portfolio return. Named slices are the top contributors; remaining gainers and losers are grouped separately. Zero-return stocks have no slice. The facts above the charts reconcile top contributors and other stocks to net return.

The full table includes a contribution column. Browser holdings CSV exports add fractional initial weight and `contribution_pp`. Static original-book pies and top-contributor tables are included for previews without JavaScript; baseline CSV files retain their original columns. Attribution is calculated when a year's stock table opens.

```bash
node tests/check-contributions.cjs
python3 tests/test_attribution.py
```

These cover signed contributions, the top-10 stock limit, positive/negative/zero/empty books, deterministic ties, input preservation, and the static fallback. Existing range/control tests also check year switching and attribution updates.

## Latest stock picks

The website opens in **Latest stock picks** mode. Historical backtest remains available in the view switch. The same size, valuation, sector, exchange, universe and rank controls apply in either mode. The latest view shows a current selection, with no holding returns or attribution charts because those outcomes do not exist yet.

The displayed date comes from the latest cached SPY session, not a hard-coded January date or a relative “yesterday” label. As of this build it is **2026-10-20**. Only companies marked currently listed in the cached universe, with a dividend-adjusted price on that exact session, are included. Earlier last-trade prices are not carried forward. The annual figure must be available under the existing strict 90-day lag and no more than 800 days old. Market cap and EV are revalued at the latest price using report net debt and the same adjusted-price method as the historical model.

Latest mode has separate prepared records for the original 250-candidate pool and all eligible cached-price companies. Both remain incomplete representations of the full market. The coverage line shows how many active names have financials and how many can be valued from current cached prices. Available-from dates are assumptions based on fiscal year-end, not verified filing dates. Listing status, sector and exchange are cached metadata.

Click **Screen latest**, **Top 50**, or **Top 100**. Download latest picks exports the currently selected stocks, including valuation date, adjusted price, estimated market cap/EV, ratios, fiscal date, and assumed availability date. `dist/latest-picks.csv` is the default-settings fallback export generated at build time; browser downloads reflect the current filters. The latest table is also embedded as a no-JavaScript fallback.

Updating source caches does not update an already-open standalone HTML file. Run `python3 scripts/research.py prepare` and `python3 website/build.py`, then reload the page. These commands never download data. Future latest sessions are prepared independently of the canonical backtest's saved Through date, so new current prices do not silently extend the old report.

## Ranking metrics

Choose **EV / EBITDA** (current-date valuation) or **EV / 3-year average EBITDA**
(current EV divided by mean EBITDA from three consecutive annual reports). Lower multiples rank first;
minimum selected yield is the reciprocal of the multiple. A missing annual
report excludes the stock from the three-year metric. Both latest and historical
modes use only reports eligible at their screening date. Selected stock tables
and CSV exports show the chosen signal. For a broader comparison, use all stocks
with cached prices: the original candidate set retains its single-year pre-screen.
See `../docs/research-workflow.md` for calculation and extension details.
