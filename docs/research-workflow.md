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

### Custom trade dates and rebalance intervals

For the full website, double-click `start.cmd` on Windows or run:

```bash
python3 website/serve.py
```

The launcher prepares stale research and daily caches in dependency order,
rebuilds changed website sources and opens the browser automatically. Unchanged
outputs are reused. `--no-browser` suppresses browser opening.
Select **Historical backtest**, choose **Custom trade
date and frequency**, enter a starting date and final mark date, and choose
monthly, quarterly, half-yearly or yearly. The original January view and latest
picks still work by opening the HTML directly; custom schedules need the local
service because daily histories are kept out of the embedded page.

Each target is anchored to the original starting calendar day. Invalid month
ends clamp to that month's last day; holidays/weekends roll forward to the next
cached SPY session. The final inclusive mark date rolls back to a session. The
last holding period may be shorter than the requested interval. Adjacent periods
share their exit/entry session, with no duplicated return interval. Annual
financial availability, age, valuation, cache coverage and original-pool buffer
rules remain the same at each new entry. Every period reselects and equally
weights stocks. Stopped holdings use the last price and hold cash proceeds until
the next rebalance; transaction costs remain zero.

The custom chart shows returns **per holding period**, not annualized period
returns. Full-period CAGR uses actual elapsed days. Empty books make strategy
CAGR and growth unavailable. Choose any period to see its stocks, valuations,
return contributions and top-10 gain/loss pies. CSV exports include period dates,
actual stock entry/exit dates, selected metrics, weights and contributions.

`scripts/schedules.py` owns the anchored calendar, daily SQLite index and dated
books. `data/schedules.sqlite` is ignored and atomically rebuilt when inputs or
calculation code change. Repeated preparation validates source freshness without
parsing prices. Newly requested entry/exit pairs are computed once and persisted;
filter, metric or rank changes reuse those books and shared SQL selection.
Only the requested stock pool is prepared. Switching between the original and
broader pools fills the missing pool once for each existing dated period; it
does not recompute the completed pool. Empty pools are recorded as complete too.
Daily cache version 3 tracks this in `period_pools`. Compatible version-1/2 caches
upgrade automatically at startup without reparsing prices or discarding books.
`metrics.evaluate()` is the common preparation boundary for all metric formulas.
`website/serve.py` serves only the built website and a loopback JSON calculation
endpoint; no keys, remote services or market-data downloads are involved.
`website/schedule.js` renders dated periods without assuming one book per year.
Run `python3 tests/test_schedules.py` in addition to the existing checks.

Before requested-pool preparation, observed in this workspace: the one-time daily index took 174 seconds and
occupied 430 MB. Building a previously unseen 20-period quarterly schedule took
52 seconds in a direct engine run; changing its metric and rank bounds reused
the books in 1.4 seconds. A 31-period January schedule through October 2026
matched every prepared baseline selection and annual return. The local service
uses a larger SQLite page cache for new-book calculations. Timings depend on disk
and schedule length; new dates can require additional book preparation.

The applied requested-pool engine was verified on native Windows Python 3.12:
100 annual random-date trials over the full cached history took 133.1 seconds,
versus 467.0 seconds for the saved eager reference (3.5× faster). The original
candidate pool, top 50 and seed 20261022 were used, ending on 2026-10-20. Loading
and per-trial saving were included; test-only cloning/reset was excluded. Every
selected holding, valuation, exit status and trial outcome matched exactly.
See `results/experiments/backtest-benchmark-applied.json`. The real daily cache
upgraded in place, retaining all 300 existing books without parsing JSON prices.

### Running and interrupted backtests

The custom-backtest page shows an indeterminate spinner and elapsed time while
awaiting the server. It does not invent a completion percentage. Controls are
locked against duplicate submissions, previous results remain labelled, and
completion or failure restores the controls. Switching views clears the visible
loading state and ignores the old response; it does not stop server computation.

Dated books for a request are written inside a SQLite transaction. Closing the
server before commit rolls those writes back on recovery. Previously committed
books and input prices/financials remain unchanged. Restart `start.cmd` and rerun
the schedule; unfinished requests are not resumed. `tests/test_schedules.py`
checks rollback after `KeyboardInterrupt`, then forcibly kills a real SQLite
writer while a new period is uncommitted, reopens the file, runs
`PRAGMA integrity_check`, verifies prior row counts, and retries the schedule.
`tests/check-range.cjs` checks loading/timer state, duplicate suppression,
completion, server/connection failures and mode-switch cleanup.

### Random independent rebalances

`scripts/robustness.py` owns seeded date sampling and distribution summaries.
It divides the requested calendar window into nominal frequency blocks anchored
to the lower bound and independently samples one cached SPY session in each
nonempty block for each trial. The final partial block participates, and the end
mark is fixed. Samples across trials may coincide; the UI reports the number of
distinct schedules. Trial count is configurable from 1 to 100 (default 24).
Schedules support 24 months as well as 1, 3, 6 and 12.

`schedules.backtest_dates()` validates the sampled sessions and delegates to the
same dated-book evaluator as regular schedules. All trial CAGRs use a common
elapsed window, with zero-return cash before the first trade for both strategy
and paired SPY. Average CAGR is the arithmetic average of complete-trial CAGRs;
there is no compounding of the average. P10/P25/P75/P90 use linear interpolation
on ordered values; standard deviation is the population dispersion of the sampled
scenarios. Empty-book trials stay in the table and are excluded from both sides
of paired averages. Percentiles are scenario descriptions, not confidence limits.

The loopback `/api/robustness` endpoint streams NDJSON trial progress and a final
summary. `scripts/book_batch.py` validates every sampled schedule upfront and
deduplicates missing date-pair/pool books across the batch. Bounded process
workers read prepared inputs with read-only SQLite connections and calculate
ahead through `schedules.compute_period`. Each process loads report histories
once. Price queries share one short read transaction per book, avoiding repeated
native Windows lock operations. The reader releases it before returning the book;
no reader holds a transaction across multiple books. Only the parent saves books, using `schedules.store_period` in short write
transactions. New books for a whole trial are staged before its atomic commit;
large trials spill to a temporary file. No calculation holds the writer lock.
The automatic policy uses up to four workers for at least 64 missing books,
bounded by CPU count. Smaller batches stay serial. Workers monitor parent lifetime
and exit if the launcher is forcibly closed. Cached-only batches launch no processes. Each individual trial commits its books,
so a disconnected/stopped batch can be repeated with the same seed and reuse
completed work. Prefetched books for later trials are not saved if the batch is
stopped first. The frontend reports worker counts and book preparation separately
from real completed-trial counts and exports dates,
seed, frequency and trial outcomes. Inspection calls the existing schedule API
with that trial's exact dates rather than implementing another selection engine.
Test sampling, statistics, interruption and the stream contract with
`python3 tests/test_robustness.py` and `python3 tests/test_book_batch.py`; test incremental decoding and distribution
rendering with `node tests/check-robustness.cjs`.

Random batches choose a fresh system-generated seed by default; the actual key
is recorded in results and CSV exports. Advanced repeat mode supplies an explicit
seed so comparisons or interrupted requests can reproduce the sampled dates.
On an occupied port the launcher binds an available loopback port and opens the
new server's URL, leaving the older process untouched. Missing API routes in old
tabs instruct the user to relaunch and use the newly opened tab.

Dated financial policy is shared in `scripts/books.py`: report-pool eligibility,
candidate buffering, entry valuation and holding returns. January preparation
and the daily engine supply array and SQL price adapters respectively;
`revalue.py` remains the independent baseline.

Random streams publish their resolved configuration before executing trials.
The browser saves that configuration locally immediately. **Replay saved date
test** repeats the window, filters, frequency, trial count and seed after a
disconnection or launcher restart; completed books are reused. Fresh runs still
generate a new seed by default.

### Upfront parallel-book benchmark

On native Windows Python 3.12, 100 full-history annual random-date trials took
103.4 seconds with one worker, 62.0 with two, 40.9 with four, and 33.2 with eight.
A fresh serial requested-pool control took 133.3 seconds, matching the earlier
133.1-second measurement. Four workers are the automatic default. The final applied implementation,
including forced-shutdown worker cleanup, took 43.2 seconds (about 3.1× faster
than the serial control). Eight workers saved another 7.7 seconds while
doubling the processes. Cached replays took about 5.6 seconds.

All 100 complete holding/result digests and aggregate outcomes matched the saved
reference exactly for every variant. Each batch prepared the same 3,082 unique
books and 537,906 stock snapshots. Loading, Windows process startup, transfers,
staging and per-trial saving are included; common test-only cloning is excluded.
Settings remain original pool, top 50, current EV/EBITDA, seed 20261022,
1996-01-01 through 2026-10-20. Broader-pool and monthly timings were not measured.
See `results/experiments/backtest-benchmark-parallel.json` and the final applied
run in `backtest-benchmark-parallel-applied.json`.

The rejected first implementation let every price query acquire a read lock.
It took 261.4/178.6/163.3/155.0 seconds with 1/2/4/8 workers. One short read
transaction per book removed that overhead. The failed variant is retained in
`results/experiments/backtest-benchmark-parallel-locking.json`; its timings are
not the applied implementation. The production cache was unchanged by all runs.
