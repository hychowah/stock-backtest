# Fast local screening and backtesting

Normal research should query prepared January snapshots instead of reparsing daily JSON price files. The embedded SQLite engine is included in Python; no database server, package installation, API key, or network connection is required. The engine can later be replaced with DuckDB if larger analytical datasets warrant it; this project does not currently depend on DuckDB or Parquet.

## Prepare once

```bash
python3 scripts/research.py prepare
```

The first run reads the existing financial cache and each relevant stock-price file once. Subsequent preparation only checks source metadata when data and calculation code have not changed. Queries skip the full per-price-file scan to keep parameter changes fast. Raw downloads are preserved. The completed database is published only after the original current top-50 return series passes verification. `--force` requests a complete offline rebuild.

Preparation stores historical observations and a separate latest-session valuation snapshot:

- Company name, exchange, sector (cached metadata, not historical profiles).
- Financial period end, assumed availability date, report market cap, enterprise value, inferred EBITDA, and EBITDA/EV for valid USD reports.
- January entry and scheduled exit dates, SPY return and Treasury yield.
- Latest cached session, exact-date price, fiscal/assumed availability dates, and entry-style valuations for cached currently-listed companies; no future holding return is attached to these picks.
- Stock entry market cap and EV, EBITDA/EV, EV/EBITDA, entry and exit dates, holding return, and exit basis.

It reuses the existing 90-day lag and 800-day report-age rule. A report must become available strictly before the buy date, matching the original code. Entry EV is reconstructed using the dividend-adjusted price and report net debt, with the same limitations as the original backtest. Reported financials may contain later vendor revisions: the 90-day rule is an availability assumption, not proof of a true point-in-time vendor archive.

## Change parameters in seconds

```bash
# Original top 50: reproduce the existing selection
python3 scripts/research.py screen

# Top 100, with the same original 250-name candidate buffer
python3 scripts/research.py screen --top 100

# Ranks 10–20 for six January books
python3 scripts/research.py screen --first 2015 --last 2020 --rank-from 10 --rank-to 20

# Apply new filters to the wider prepared set with cached prices
python3 scripts/research.py screen --pool cached --min-cap 500000000 --max-cap 5000000000 --min-yield 0.15 --top 100

# Other available filters, individually or in combination
python3 scripts/research.py screen --pool cached --min-ev 100000000 --max-multiple 8 --sector Technology --exchange NASDAQ

# Save a separate experiment, without overwriting the original report
python3 scripts/research.py screen --top 100 --output results/experiments/top100.json

# Inspect how much of the universe can be valued from the cached prices
python3 scripts/research.py status
```

Caps and EV are in nominal USD; minimum yield is a fraction (`0.15` means 15%). Sector and exchange filters match the cached text exactly. Filters apply before ranking; rank 1 has the lowest selected multiple within the matching pool (EV/EBITDA by default). Stocks are selected each January and equally weighted. Selection uses entry information, never future return. Treasury subtraction does not change the ordering within a date.

`legacy` pool means **original-screen-compatible candidate selection**, not the older exit rule: all pools retain early trading stops at their last price and apply the explicit `BANKRUPT` overrides. This pool preserves the original report-level $100m market cap/$50m EV filters and 250-name buffer, so lowering those filters in a query cannot recover companies already excluded by those rules. Use `cached` to vary those thresholds more broadly.

`cached` considers all available positive-EV USD reports for companies with cached price files. Its report selection can differ from the original pool because the original report-level size filters are not applied. It cannot claim to be the full 11,000-company universe. The status command reports financial eligibility and price-valued observations by year. Acquiring missing prices is a separate, explicit task.

If a filter leaves fewer names than requested, the result states which years are short. A year with no names is printed as `NA`; cumulative wealth covers only populated books and must not be treated as an uninterrupted invested strategy. SPY is compounded over those same populated books. Stock returns are full precision; no commissions or cash interest after an early exit are included. Expanded selections may include early stops outside the original 37-name review, so their default last-price exits have not received the prior manual bankruptcy investigation.

## Website

```bash
python3 website/build.py
```

The website builder queries the prepared database and embeds both historical and latest-session candidate pools in self-contained HTML. It opens in Latest stock picks mode; switch to Historical backtest for the year-based results. Latest screening uses exact-date prices and cached currently-listed status, excluding older stopped prices. The browser supports portfolio ranks and size (including top 100), market-cap bounds, minimum EV, minimum selected metric yield, maximum selected multiple, sector, exchange, pool and year filters. Click Screen latest or Run backtest to apply financial filters in the chosen mode. Year and rank changes also apply the entered filters. Charts, stock lists, market-cap medians, statistics and CSV exports reflect the selection. Each year also has gain/loss contribution pies and the top 10 stocks ranked by signed equal-weight return contribution (or all stocks when fewer than 10 are selected). No backend or hosting service is required. See `website/README.md` for units and controls. Unlike the CLI populated-book summary, browser strategy CAGR and cumulative growth are unavailable if any selected year has no matching stocks; SPY remains for the full selected period.

The original `scripts/revalue.py` remains a slower, independent cache-based reference calculation. Keep it for auditing or deliberately recomputing the canonical saved report. After editing raw data, run preparation again. Queries detect changed core data files, price-directory changes, bankruptcy overrides and calculation code; preparation also detects edits to existing individual price files. Run one preparation process at a time. Do not edit `HOLD` just to try a different portfolio size; pass `--top`.

## Checks

```bash
python3 tests/test_research.py
python3 tests/check_paths.py
node tests/check-range.cjs
node tests/check-contributions.cjs
python3 tests/test_attribution.py
python3 tests/check_screener.py
```

The research tests cover availability dates, rank selection before future returns, filters before ranking, early stops, bankruptcy overrides, price alignment, read-only access and stale database detection. Preparation checks every year of the canonical saved result. Website tests check year/rank and screen controls using a simulated DOM, and compare browser picks against SQLite across nine historical and seven latest configurations; real browser visual QA remains unavailable in the current environment.

## Measured performance

The completed local database contains 39,468 January snapshots for the two candidate pools and occupies about 17 MB. On this environment, a full preparation took 62 seconds. After preparation, measured end-to-end times including Python startup were 0.45 seconds for top 100 in 2015–2020, 0.59 seconds for a filtered version, and 1.8 seconds for the website rebuild. These are observed timings, not guarantees. See `results/experiments/performance.json`.

The original 1996 pre-price buffer yields only 61 usable holdings, so it cannot supply a complete top-100 book. The wider pool also has incomplete price coverage of the universe. The engine reports insufficient matches instead of claiming 100 names in every year.

## Current-date preparation

Schema version 2 adds `latest_snapshots` and latest-date metadata. The latest target is the newest cached SPY session. Only cached companies marked listed with a price on that exact session and a usable available report receive current valuations. The original latest candidate pool retains the 250-name pre-price buffer; the broader pool uses all eligible active names with current cached prices. `research.latest_screen()` exposes the same SQL filters and rank semantics without return fields.

Historical preparation is capped at the saved canonical report's Through date (and the configured historical ASOF). Latest preparation can advance beyond that date without silently extending the historical backtest. The reference report is included in the freshness signature. Updating a database and rebuilding HTML are separate from fetching missing or new market data.

### Select a ranking metric

Both website modes and `research.py screen --metric ev_ebitda_3y` support
current EV divided by three-year average EBITDA. The denominator is the arithmetic mean of positive annual
EBITDA for three consecutive fiscal calendar years ending
at the selected report. EV is valued at the screening date.
Missing years exclude a stock. Reports after the selected fiscal end are never
used; the selected report still obeys the strict 90-day availability lag and
800-day age limit. The original metric remains current-date EV/EBITDA.

Rank 1 has the lowest selected multiple. Minimum yield is its reciprocal;
maximum multiple applies to the selected metric. Tables and selected-holdings
CSV exports include the selected metric values. The original pool retains its
single-year top-250 pre-screen; use the cached pool to compare signals across
the broader available price universe. Neither pool represents full coverage.

`scripts/metrics.py` owns the display catalog, calculator registry and metric
preparation. `screening_metrics` stores ready-to-rank multiple/yield pairs by
mode, pool, year, symbol and metric ID (year 0 represents latest mode). Thus
screening-date values remain separate even when observations use the same fiscal
report. Preparation preserves both default EV/EBITDA values exactly.
`website/dataset.py` exports the display catalog and prepared pairs; SQL and
JavaScript consume the same values without interpreting calculation types.

To add a metric, register its display metadata in `METRICS` and its calculation
in `CALCULATORS`. A calculator receives the valued observation and company report
history, returns a multiple/yield pair, or returns `None` for missing data. It
must only use history eligible for that observation. The selected fiscal report
bounds the existing three-year calculation. Catalog/registry mismatches fail
preparation. Add temporal/missing-history tests and SQL/browser parity cases;
selection and UI code do not need new formula branches. Calculation/catalog
changes invalidate prepared data. Rebuild once from the raw cache; changing the
selector never downloads or reparses price history.
