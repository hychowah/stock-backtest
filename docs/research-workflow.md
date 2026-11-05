# Fast local screening and backtesting

Normal research should query prepared January snapshots instead of reparsing daily JSON price files. The embedded SQLite engine is included in Python; no database server, package installation, API key, or network connection is required. The engine can later be replaced with DuckDB if larger analytical datasets warrant it; this project does not currently depend on DuckDB or Parquet.

## Prepare once

```bash
python3 scripts/research.py prepare
```

The first run reads the existing financial cache and each relevant stock-price file once. Subsequent preparation only checks source metadata when data and calculation code have not changed. Queries skip the full per-price-file scan to keep parameter changes fast. Raw downloads are preserved. The completed database and canonical report are published only after the SQL and independent engines agree on the original top-50 holdings, ranks, fiscal reports, price dates, prices, valuations, exit basis and returns at full precision. `--force` requests a complete offline rebuild.

When saved data changes, preparation builds a new database and copies unchanged company work from the published one. Reuse needs an equal reuse scope. The scope covers the content of the calculation source, the Python and SQLite versions, the report Through date, the universe file, the annual financial files, and the SPY and Treasury rows up to the historical horizon. The horizon is the later of the Through date and 31 days after the last January entry. Historical forward lookups start at a January entry and reach at most eight days. Exit lookups read backward from a day on or before Through. Historical calculations therefore cannot read rows after the horizon. Inside an equal scope, each company is a separate unit:

- Its historical snapshots, prices, filter values and measure contexts are copied when its saved price rows up to the horizon are equal.
- Its dated price evidence is copied when the price file bytes are equal. Its source evidence is copied only when its coverage receipt is also equal.
- Files save rows newest first, so a daily download adds rows before the saved rows and moves each saved row by the same number of places. When the saved rows are otherwise equal, only the days of the new rows are resolved. The evidence of every other day is copied with each row position moved by that number. Any other change resolves the whole file.
- Latest valuations are always recalculated. An unlisted company with equal file bytes is not parsed.

Downloads rewrite a checked file even when no row changes, so file content, not its timestamp, decides reuse. Copied rows keep their original order, so the database equals a full rebuild row for row. Freshness checks are unchanged. `--force` recalculates every company.

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
python3 scripts/research.py screen --top 100 --output tmp/top100.json

# Inspect how much of the universe can be valued from the cached prices
python3 scripts/research.py status
```

Caps and EV are in nominal USD; minimum yield is a fraction (`0.15` means 15%). Sector and exchange filters match the cached text exactly. By default, filters apply before ranking; rank 1 has the lowest selected multiple within the matching pool (EV/EBITDA by default). Use `--selection-order rank_first` to select the requested ranks before applying user filters. Stocks are selected each January and equally weighted. Selection uses entry information, never future return. Treasury subtraction does not change the ordering within a date.

`legacy` pool means **original-screen-compatible candidate selection**, not the older exit rule: all pools retain early trading stops at their last price and apply the explicit `BANKRUPT` overrides. This pool preserves the original report-level $100m market cap/$50m EV filters and 250-name buffer, so lowering those filters in a query cannot recover companies already excluded by those rules. Use `cached` to vary those thresholds more broadly.

`cached` considers all available positive-EV USD reports for companies with cached price files. Its report selection can differ from the original pool because the original report-level size filters are not applied. It cannot claim to be the full 11,000-company universe. The status command reports financial eligibility and price-valued observations by year. Acquiring missing prices is a separate, explicit task.

If a filter leaves fewer names than requested, the result states which years are short. A year with no names is printed as `NA`; cumulative wealth covers only populated books and must not be treated as an uninterrupted invested strategy. SPY is compounded over those same populated books. Stock returns are full precision; no commissions or cash interest after an early exit are included. Expanded selections may include early stops outside the original 37-name review, so their default last-price exits have not received the prior manual bankruptcy investigation.

## Website

```bash
python3 website/build.py
```

Normal builds write ignored `website/local/`, which the local server serves. Startup and data-panel rebuilds leave the tracked `website/dist/` snapshot unchanged. Refresh that portable snapshot only with `python3 website/build.py --snapshot`. Review its generated files and `snapshot.json` cutoffs and source hashes before committing. Range and SQL/browser parity checks default to local output; pass `website/dist` to check the portable snapshot instead.

The website builder queries the prepared database and embeds both historical and latest-session candidate pools in self-contained HTML. It opens in Latest stock picks mode; switch to Historical backtest for the year-based results. Latest screening uses exact-date prices and cached currently-listed status, excluding older stopped prices. The browser supports portfolio ranks and size (including top 100), market-cap bounds, minimum EV, minimum selected metric yield, maximum selected multiple, sector, exchange, pool and year filters. Click Screen latest or Run backtest to apply financial filters in the chosen mode. Year and rank changes also apply the entered filters. Charts, stock lists, market-cap medians, statistics and CSV exports reflect the selection. Each year also has gain/loss contribution pies and the top 10 stocks ranked by signed equal-weight return contribution (or all stocks when fewer than 10 are selected). No backend or hosting service is required. See `website/README.md` for units and controls. Unlike the CLI populated-book summary, browser strategy CAGR and cumulative growth are unavailable if any selected year has no matching stocks; SPY remains for the full selected period.

The original `backtest/engines/reference/revalue.py` remains a slower, independent cache-based reference calculation. Keep it for auditing or deliberately recomputing the canonical saved report. After editing raw data, run preparation again. Queries detect changed core data files, price-directory changes, bankruptcy overrides and calculation code; preparation also detects edits to existing individual price files. Run one preparation process at a time. Do not edit `HOLD` just to try a different portfolio size; pass `--top`.

## Checks

```bash
python3 tests/test_research.py
python3 tests/check_paths.py
node tests/check-range.cjs
node tests/check-contributions.cjs
python3 tests/test_attribution.py
python3 tests/check_screener.py
```

The research tests cover availability dates, rank selection before future returns, filters before ranking, early stops, bankruptcy overrides, price alignment, read-only access and stale database detection. Preparation compares every historical year with the independent engine. `python3 tests/test_baseline.py` checks changed prices, holding-level mismatches, latest-only updates, interrupted publication, recovery receipts and Windows sharing locks. Website tests check year/rank and screen controls using a simulated DOM, and compare browser picks against SQLite across historical and latest configurations, including combined threshold conditions. These automated checks do not replace a real-browser visual review.

## Measured performance

Incremental preparation was measured on 5 November 2026 in WSL with fictional data only: 250 priced companies, 1.56 million price rows and a 2.2 GB research database. One product-like daily download followed each forced build. When every price file gained one session, preparation took 31.5 seconds and a forced full rebuild of the same inputs took 64.5 seconds. When half of the companies were unlisted, so that their files were rewritten with equal bytes, the times were 34.4 and 65.9 seconds. Every table matched the full rebuild in both cases. The disk was shared with other jobs, so single timings vary by tens of seconds. At that time a hash of every observation row took most of the remaining time. That hash is gone. A second WSL measurement on the same day used 150 fictional companies from 2000 to 2015. With every price file gaining one session, a startup took 28.0 seconds before the change and 14.4 seconds after it. The remaining time is mostly the moved dated evidence of every stored day, price parsing and publication of the complete database file.

The full daily cycle was measured in the same workspace, with half of the companies unlisted and the Original engine. After one download, it ran `scripts/schedules.py prepare` and then a monthly schedule from 2010-01-01 to 2026-10-21 with 202 books. The cycle took 115 seconds with the previous source, which rebuilt both databases and recalculated every book. It took 59 seconds with the refresh, which kept every book. These timings do not describe the real cache or native Windows.

The completed local database contains 39,468 January snapshots for the two candidate pools and occupies about 17 MB. On this environment, a full preparation took 62 seconds. After preparation, measured end-to-end times including Python startup were 0.45 seconds for top 100 in 2015–2020, 0.59 seconds for a filtered version, and 1.8 seconds for the website rebuild. These are observed timings, not guarantees. See `results/experiments/performance.json`.

The original 1996 pre-price buffer yields only 61 usable holdings, so it cannot supply a complete top-100 book. The wider pool also has incomplete price coverage of the universe. The engine reports insufficient matches instead of claiming 100 names in every year.

## Current-date preparation

Schema version 2 adds `latest_snapshots` and latest-date metadata. The latest target is the newest cached SPY session. Only cached companies marked listed with a price on that exact session and a usable available report receive current valuations. The original latest candidate pool retains the 250-name pre-price buffer; the broader pool uses all eligible active names with current cached prices. `screening.latest()` exposes the same SQL filters and rank semantics without return fields.

Historical preparation is capped at the saved canonical report's Through date (and the configured historical ASOF). Latest preparation can advance beyond that date without silently extending the historical backtest. The report cutoff is included in source freshness. The committed database stores the report content hash. Updating the generated report does not invalidate its own source signature. Updating a database and rebuilding HTML are separate from fetching missing or new market data.

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

`backtest/financial/metrics.py` owns the display catalog, calculator registry and
pure metric calculations. `research.prepare_metrics()` populates the prepared
metric tables within the preparation transaction. `screening_metrics` stores ready-to-rank multiple/yield pairs by
mode, pool, year, symbol and metric ID (year 0 represents latest mode). Thus
screening-date values remain separate even when observations use the same fiscal
report. Preparation preserves both default EV/EBITDA values exactly.
`website/rendering/data.py` exports the display catalog and prepared pairs; SQL and
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

`backtest/calendar.py` owns calendar configuration, anchored boundaries,
session rolling and seeded sampling. Read the
[calendar contract](schedule-calendar.md) for its version and old-request mapping.
The website runs Original. It accepts the five existing month counts and
version-1 calendars with 1–104 weeks or 1–24 months.
`backtest/inputs/daily.py` owns the daily SQLite index and saved books.
`backtest/engines/original/schedules.py` calculates missing dated books.
`backtest/portfolio_results.py` reduces ordered selected books into complete
dated results. It owns equal weights, signed contributions, compounding and
common-window cash. It reads no files. The
[financial result contract](portfolio-results.md) preserves complete holding
rows and existing application envelopes. An offline numerical diagnostic uses
the same reducer after complete-book calculation and unchanged SQL selection.
This diagnostic does not route website requests to a new engine.
`data/schedules.sqlite` is ignored. It is replaced atomically when inputs or
calculation code change, and preparation refreshes it from the previous cache
(below). Repeated preparation validates source freshness without
parsing prices. Newly requested entry/exit pairs are computed once and persisted;
filter, metric or rank changes reuse those books and shared SQL selection.
Only the requested stock pool is prepared. Switching between the original and
broader pools fills the missing pool once for each existing dated period; it
does not recompute the completed pool. Empty pools are recorded as complete too.
Daily cache version 5 tracks this in `period_pools`. Daily inputs include a digest
of the price inventory accepted by committed research metadata. The digest covers
filenames, sizes and modification times. Normal daily connections do not scan raw
prices. An older cache without this binding or without refresh evidence takes the
full build path. This affects derived data only; durable library and queue
snapshots remain independent.

When the daily inputs change, preparation writes a new daily cache from the
previous one. Prices of a company whose file bytes and price code are unchanged
are copied without parsing. A changed file is parsed, and its first changed day
is found from a saved digest of its rows or from a row comparison. Saved dated
books are kept as follows:

- All books are dropped when a book input without dates changes: the copied
  companies, statements or financial inputs, the cached company set, or the
  content of the book calculation code.
- Otherwise a book is kept when it reads no input on or after the earliest
  changed day of any price, SPY session, Treasury yield or 10-year yield. A book
  reads nothing after the later of its exit and its entry plus
  `books.FORWARD_REACH` (eight days: two four-day forward lookups).

A daily download therefore keeps every book whose reach ends before the new
session. The refreshed cache equals a full build of the same inputs, and each
kept book equals the book a full build calculates.

`metrics.evaluate()` is the common preparation boundary for all metric formulas.
`website/serve.py` serves the built website and local JSON calculation endpoints.
The default listener is `0.0.0.0:3000`; the browser opens
`http://127.0.0.1:3000` on this computer. Use `--host` and `--port` to change the
listener. Backtest calculations use saved data only. The separate data panel can download missing data when requested.
`website/browser/schedule.js` renders dated periods without assuming one book per year.
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
The [experiment summaries](../results/experiments/README.md) keep these numbers. The real daily cache
upgraded in place, retaining all 300 existing books without parsing JSON prices.

### Running and interrupted backtests

Custom and random backtests run in a server-owned thread. The browser saves an
unguessable run ID before submission. It follows `/api/backtest-runs/<id>/status`
with short polling requests. This route omits the large result. The browser
retrieves completed holdings from `/api/backtest-runs/<id>`. Repeated submissions
with that ID reuse the same run.
Each run has a separate browser recovery record. The record tracks server
acceptance and Stop intent. A refresh before acceptance retries the same
submission ID. Once accepted, recovery retrieves the run and never starts
expired work again. A rejected submission in another tab does not remove
the accepted run's recovery record.
Recovery checks saved candidates against current server status. It selects
active work first. Otherwise, it selects the newest available completed run.
It skips failed, stopped and expired candidates.
Locking a phone, refreshing, closing the page or changing views does not cancel
the calculation. Reopen the same address in the same browser to restore the
submitted settings and retrieve progress or the completed result. Browser
storage must remain available. A lost connection retries without starting a new
calculation.

The page shows a spinner and elapsed time. It does not invent a completion
percentage. Settings remain editable. Edits do not change the submitted run or
queue a second run. The Run button prevents duplicate submissions. Previous
results remain labelled until a new run finishes. Use **Stop backtest** to send
an explicit stop request. The controls stay busy until the server confirms
worker cleanup and database closure. A Stop request made while disconnected
retries when this browser reconnects.

`backtest/application/jobs.py` accepts one active run per server. It uses the
existing engine cancellation checks and `cache_access.daily()` ownership.
Shutdown requests a stop and joins the thread before server lifetime ownership
ends. Finished results remain in server memory for 24 hours, up to four recent
runs. They are temporary and disappear when the server exits. Use the existing
saved-backtest library to retain a result. The server computer must stay awake.

Dated books for a request are written inside a SQLite transaction. Closing the
server before commit rolls those writes back on recovery. Previously committed
books and input prices/financials remain unchanged. Restart `start.cmd` and rerun
the schedule; unfinished requests are not resumed. `tests/test_schedules.py`
checks rollback after `KeyboardInterrupt`, then forcibly kills a real SQLite
writer while a new period is uncommitted, reopens the file, runs
`PRAGMA integrity_check`, verifies prior row counts, and retries the schedule.
`tests/test_backtest_jobs.py` checks real HTTP disconnects, reconnects, explicit
stops, idempotent submission, retention and shutdown ownership on WSL and native
Windows. `tests/check-backtest-runs.cjs` checks browser transport and stored-ID
recovery. `tests/check-range.cjs` checks loading/timer state, duplicate
suppression, completion, reconnects and changes of view.

### Overnight queue

Use **Backtest queue** for fixed or random-date tests. Select the custom calendar,
set parameters and add the current test. Change settings to add more tests.
Auto-run is suspended while waiting/running queue work exists. Adding, copying
or editing a queue item also turns it off so setup stays manual between fast
cached tests. Explicit Run still starts an immediate test. Queue tests run one at a time. Browser closure
does not affect them. Keep the server computer awake and its terminal open.

Edit holds a waiting item so it cannot start with incomplete edits. Save changes
to release it. Cancel keeps the original parameters. Held edits survive page and
server restarts. Move up/down changes waiting order. Copy settings creates a new
test without changing the original. Pause lets the active item finish but does
not claim another item. Stop cancels the selected item and waits for normal
worker cleanup. Failed items remain visible; the consumer continues to the next.

The strategy form owns a queued edit session. While that session is active,
opening a queue or saved-library result, copying another test, or recovering a
manual run cannot replace its settings. Save or cancel the edit first. The same
form boundary handles every restoration source. A failed server hold releases
the local form session without leaving the controls reserved.

Up to 100 records, including completed results, persist in
`data/backtest-queue.sqlite`. There is no automatic eviction. Open a result to
restore its immutable artifact and downloads without running it again. The queue
is separate from the 20-record saved library. Delete confirms removal of only
the selected test/result. A deleted-ID receipt prevents a lost acknowledgement
from recreating it. Keep the queue database during cache cleanup and deployment.

One OS lock, `data/backtest-queue.lock`, elects a consumer across server
instances. Queue database transactions close before financial ownership starts.
The queue calls the ordinary website calculation adapter. It waits through
financial cache contention instead of failing every queued test. Server shutdown
requeues unfinished work after engine cleanup. A successor recovers abandoned
running items only after obtaining the consumer lock. Pending Stop requests
remain cancelled. A random seed is recorded at admission. Once planned, the full
trial date plan is recorded and reused after interruption. Changing waiting
calculation parameters discards the previous plan. Renaming a test keeps its
dates. Tests use the saved financial data available when they execute. Completed artifacts retain their original priced evidence.

The same-origin `/api/backtest-queue` API lists metadata with GET and enqueues
with POST. Enqueue supplies an idempotent 32-character hex ID, name, mode,
options, catalog and semantic presentation. `GET /<id>` includes the completed
snapshot. `POST /pause` accepts a boolean `paused`. Item POST actions are
`hold`, `release`, `update`, `move` and `stop`; DELETE removes an item.
Mutations carry its current `revision`. Move supplies `direction: -1` or `1`.
Update supplies new settings/labels and requires a held item. A revision conflict
returns 409. Listing never loads result blobs or the full random date plan.

Check `python3 tests/test_queue.py` on WSL/native Windows and
`node tests/check-queue.cjs`, plus the existing background-run, website, saved
library and deployment checks. Synthetic tests cover serial execution, failed
tests, holds, revisions, pause, cancellation, consumer competition, process death,
cache contention and exact random-date recovery.

### Random independent rebalances

The offline numerical diagnostic now has separate completed-trial checkpoints.
It uses the same ordered summary and capture consumer as the ordinary driver.
The website runs these requests on Original, which keeps ordinary saved-book
recovery. The frozen experimental engine kept generation-bound checkpoints; the
website no longer runs it.
Checkpoint retention applies only to derived calculations. Saved-library and
completed queue snapshots remain readable after current input changes. See the
[checkpoint contract](trial-checkpoints.md) for identity and retention rules.

`backtest/engines/original/robustness.py` owns the random-date application adapter, fresh-seed
policy and distribution summaries. It uses `backtest/calendar.py` to
divide the requested calendar window into nominal frequency blocks anchored
to the lower bound and independently sample one cached SPY session in each
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

The browser submits each run to the loopback `/api/backtest-runs/<id>` service and
polls its status; progress counts real completed trials, and the run continues on
the server if the page closes. `backtest/engines/original/book_batch.py` validates every sampled schedule upfront and
deduplicates missing date-pair/pool books across the batch. Bounded process
workers read prepared inputs with read-only SQLite connections and calculate
ahead through `schedules.compute_period`. Each process loads report histories
once. Price queries share one short read transaction per book, avoiding repeated
native Windows lock operations. The reader releases it before returning the book;
no reader holds a transaction across multiple books. Only the parent saves books, using `schedules.store_period` in short write
transactions. New books for a whole trial are staged before its atomic commit;
large trials spill to a temporary file. No calculation holds the writer lock.
The automatic policy uses up to eight workers for at least 16 missing books,
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
Windows `backtest-web.cmd` and `start.cmd` use managed startup. They stop this
project’s identified server and transfer ownership to the invoking terminal.
Replacement waits up to 30 seconds for the old listener and request threads to
close before preparation. If ownership remains held, wait or stop the old terminal
and retry. Unknown port owners stay running; the service selects an available
port and opens that address. Direct `python3 website/serve.py` starts a foreground
server without replacement; `--managed` enables replacement. Missing API routes
in old tabs instruct the user to relaunch and use the newly opened tab.

Dated financial policy is shared in `backtest/financial/books.py`: report-pool eligibility,
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
The [experiment summaries](../results/experiments/README.md) keep these numbers and
the final applied run.

The rejected first implementation let every price query acquire a read lock.
It took 261.4/178.6/163.3/155.0 seconds with 1/2/4/8 workers. One short read
transaction per book removed that overhead. Those timings belong to the
rejected variant, not the applied implementation. The production cache was unchanged by all runs.


### Selection order

**Selection order** applies to January, latest, fixed and random-date views.
The default is **Filter first, then rank**. All user conditions pass first.
Rank the matches and take the requested inclusive range.

**Rank first, then filter** ranks the prepared pool and takes the requested
range before applying user conditions. All user filters move together, including
market-cap bounds, EV, selected yield/multiple, sector, exchange and additional
conditions. There are no replacements. Survivors keep their original ranks.
For example, if only ranks 2 and 7 pass a top-50 screen, hold those two stocks
at 50% each. Ranks 10–20 test only that original 11-stock shortlist.

Pool membership, financial eligibility, usable prices and available selected
ranking metrics still precede both orders. The original pool's 250-name buffer
and preparation floors remain. Missing threshold values fail only their own
conditions. Tie order stays yield descending, candidate rank ascending with
nulls first, then symbol ascending. Each January year ranks independently.

Both orders reuse the same prepared records and dated books. Changing this
setting needs no data download or new dated-book calculation. Source installation
still needs the usual freshness check and offline rebuild. Empty and short books
retain their existing warnings and CAGR rules. No cash allocation fills removed
positions; each survivor gets an equal share of the portfolio.

Python screen functions and schedule options accept
`selection_order='filter_first'` or `selection_order='rank_first'`.
The CLI accepts `--selection-order rank_first`. Omitted values retain the original
filter-first behavior. Invalid values fail validation. Browser results, exports,
background runs, queued settings, explicit-seed replay and saved artifacts retain
the submitted order. Older saved records omit the field and restore filter-first
without being rewritten or recalculated. Original ranks remain in CSV exports.
An older queued test keeps its random plan when a name-only edit exposes the
implicit filter-first default. Changing the order discards a waiting test's plan.
Check `python3 tests/test_selection_order.py`, research, schedule, robustness,
queue and saved-artifact tests, then browser/SQL parity and control checks.

### Multiple threshold conditions

The website has an **Additional filters** list. Add one condition per metric,
comparison and value. All conditions must pass at the chosen selection stage. Comparisons are
strict: `lt` means less than; `gt` means more than. Two conditions can bound the
same metric. Missing values fail only conditions that require those values.

The default catalog includes both EV/EBITDA multiples, EBITDA/EV yield,
market cap, enterprise value, and trailing 1-year and 3-year returns. Additional
financial filters include P/E, P/B, free cash flow amount/yield, price/FCF, net
profit margin, historical PEG, ROE, current ratio, interest coverage and debt/equity.
These use saved annual statement inputs. Select Full annual financial data in
the data panel, download missing assets, then rebuild. Changing filters makes no
provider requests. Missing inputs exclude only stocks filtered on those inputs.

`backtest/financial/metrics.py` defines the catalog and prepares threshold values.
Schema version 5 stores them in `filter_values`, separately from ranking pairs.
Returns use dividend-adjusted closes on or before the screening date and its
calendar anniversary, with a seven-calendar-day tolerance at each endpoint.
A leap-day anniversary clamps to 28 February. Return values use percent units;
market cap and EV use millions of dollars. Return filters never use the later
holding-period return. The same calculations serve dated books.

Python screens and schedule APIs accept `filters`, for example:

```python
filters = [
    {"field": "return_1y", "op": "gt", "value": 10},
    {"field": "ev_ebitda", "op": "lt", "value": 8},
]
```

After changing the catalog or calculations, prepare research and daily caches
and rebuild the website. Changing condition values reuses prepared books.

### Sales-based operating yield spread

Add **Sales × 3-year avg operating margin / EV − US 10Y (pp)** under
Additional filters. The formula is:

```
annual operating margin = operating income / revenue
spread (pp) = selected annual revenue × mean(last 3 annual margins) / screen-date EV × 100 − Treasury yield (%)
```

Use three consecutive fiscal calendar years ending at the selected report.
Each year's margin has equal weight. This is not a revenue-weighted margin.
Use the selected report's revenue for sales and its `operatingIncome` field for
operating income. Do not substitute EBIT. The existing 90-day availability lag,
strict availability-before-screen rule and 800-day report-age limit still apply.
Later reports cannot fill a missing year or field. Revenue and EV must be
positive. Operating income and the resulting spread can be negative.

Subtract the latest cached 10-year Treasury yield on or before the screening
date. There is no added yield-age limit. January uses the book's screening
session even if a stock's first buy price is a later session. Latest uses its
exact saved SPY session. Dated books use their entry session. The filter uses
percentage points: enter `5` for a spread above or below 5 pp.

Schema version 8 adds `treasury10(day, yield_percent)` from saved `year10`
fields in `raw/treasury.json`. The daily cache copies this table. Prepared
`financial_inputs` now includes unambiguous USD `operatingIncome` values from
full annual income statements. Both pools and all four website modes share
`metrics.operating_yield_spread`. Missing history or Treasury values omit only
this field. A stock fails only a condition that requires the missing field.
Existing 3-month Treasury spreads and ranking metrics keep their formulas.

Rebuild research, daily data and HTML after installing this source change.
Preparation reuses saved files and does not download data. Full annual financial
data supplies missing income-statement assets through the existing explicit
download action. Treasury downloads keep the provider's full yield-curve rows.
Existing valid raw inputs are retained. Provider fields are documented in
[FMP annual statements](https://site.financialmodelingprep.com/datasets/fundamental-financial-statements)
and [FMP Treasury curves](https://site.financialmodelingprep.com/datasets/economics).

The request keeps the existing condition shape:

```python
filters = [{"field": "operating_yield_spread_3y", "op": "gt", "value": 5}]
```


### Data control panel

Open **Manage backtest data** from the strategy builder, or open `/data.html`
on the local service. The panel checks the universe, annual financials, stock
prices, SPY, Treasury yields, prepared databases and website build. Select the
original candidate sets, existing price-cache stocks, all eligible financial
stocks, or up to 200 specific symbols. Choose a price-history range. Include
prior prices for report-date valuation and trailing returns.

**Check data** reads saved files. It makes no provider request and does not read
the API key. Reports show actual first and last dates, record counts, missing
financial symbols, empty histories and invalid files. The JSON report includes
the full stock list and missing full-data endpoint assets for the chosen group.

**Download missing data** uses the selected data types. It reuses a saved
universe and existing annual records. Financial downloads fill missing symbols
across the universe, or only the explicitly entered symbols. Price downloads
fill ranges outside the existing saved date span. They do not refresh existing
values or repair internal session gaps. Short histories can reflect listings
or trading stops. The provider may have no additional data.

Stock and SPY requests use windows of up to ten years. Treasury uses monthly windows.
Up to 32 requests run concurrently. The default shared start-rate cap is 45 per
second (2,700/minute), below this account's stated 3,000/minute allowance.
Each worker reuses its HTTP connection. The transport requests gzip and decodes
successful compressed responses before JSON parsing. Plain responses also work.
Corrupt compressed bodies and unsupported encodings use bounded transport retries.
Error status and Retry-After take precedence over response-body encoding.
A 429 response applies a shared Retry-After cooldown and reduces the start rate.
There are at most three attempts, a 15-second socket timeout and a 30-second read
deadline. Cancellation stops submission and interrupts retry waits; active
requests are joined before cache ownership is released. Only the owner publishes
validated records and coverage receipts. Workers do not write raw files.
`raw/download-coverage.json` records successful requested windows, including
empty responses. Each asset entry has `sha256`, `windows` and `base_span`. The base span is the saved coverage before managed extension, or null for a new file. Each finished window is tracked separately. An out-of-order result cannot make an unfinished middle window disappear. `previous` retains one earlier receipt for interrupted replacement. The hash identifies
the exact saved file. Only a valid file with that hash can reuse the windows.
Missing, corrupt or manually replaced files lose old completion evidence.
Legacy list-only entries have no proof and are ignored; usable saved rows
remain. Retrying resumes unrequested windows for the validated asset. Valid saved rows and
legacy light prices are retained. Each price or market window is published by
atomic replacement. Expected-content receipts are saved before asset replacement.
The current or previous receipt applies only when its hash matches the actual
valid file. This covers interruption on either side of replacement. Completed windows survive interruption. Corrupt files are
backed up under `raw/archive/*.before-data-repair` before repair. Invalid JSONL
financial lines are backed up; valid symbol records remain and missing symbol
records are downloaded. Both preparation and group inspection use the same
validated mapping-only annual rows and financial eligibility policy. Provider
failures do not mark a window complete.

The key stays at `~/.grok/secrets/fmp_api_key`. The UI sees only file presence,
never its value or provider request URLs. Downloads can require a paid provider
subscription. Opening the panel never starts a download.

**Rebuild prepared data + website** runs research preparation, daily preparation,
and the website build without network requests. Two independent engines must agree before a changed January reference is published. Export the revision from the data panel to inspect its evidence. Historical dates do not advance with latest prices. Open the
strategy page after rebuilding to load the new embedded data.

`website/server/data_manager.py` owns the inventory and background job. The local
service exposes `/api/data/status` and the POST actions
`check`, `download`, `rebuild`, and `cancel`. Data endpoints accept only local,
same-origin requests. `backtest/runtime/cache_access.py` owns one project-wide resource
coordinator, backed by ignored `data/website-data-0.lock`. Startup, standalone
research/daily preparation, data jobs, fixed schedules and random batches use
the same coordinator. Lock order is process-local reentrant lock, project file
lock, then database connections and worker pools. Ownership remains held until
workers finish and databases close. Nested preparation reuses ownership. The
website build subprocess reads under its parent’s ownership. Polling reports real work progress. Cancel waits
for an active provider request or preparation step, retaining completed files.
Shutdown waits for the worker before releasing server lifetime ownership.

The service serves `/data.html` directly from current source. Missing or invalid
essential raw inputs route startup to this recovery panel. It does not need a
prepared database or prior website build. The canonical reference report must
be restored from backup if missing; it is never invented or downloaded.
The built `website/local/data.html` and portable `website/dist/data.html` are standalone copies with local-service
instructions when opened as a file.

Check with `python3 tests/test_data_manager.py`, `node tests/check-data-panel.cjs`,
`python3 tests/test_cache_access.py`, and `python3 tests/test_startup.py`.


### Download performance experiment

The experiment lives in `tmp/2026-10-22-fmp-download/`. Temporary responses and
disposable caches stay ignored. The durable record is
`results/experiments/fmp-download-benchmark.json`. It includes settings, per-request
measurements, request counts and the selected implementation fingerprints.
The run used native Windows Python 3.12. It did not replace active raw inputs.

Unpaced transport batches each contained 16 distinct uncached one-year stock
requests. Pooled workers 1, 4 and 8 were measured twice, in reversed order;
16 workers and the legacy urllib serial baseline were measured once. Eight
workers took 3.04–3.54 seconds, versus 22.09–31.81 seconds for one pooled worker.
Sixteen workers took 4.06 seconds. All 128 concurrency requests returned HTTP 200.
Companies, historical periods and provider load vary; the samples do not prove
a universal optimum.

The paced production path saved 16 histories in 6.56 seconds, with 16 HTTP 200
responses and no retries. It used the same symbols as the 42.47-second urllib
reference but a different year (2024 versus 2019). Do not label that comparison
a controlled same-period speedup. A replay of the earlier disposable production
cache took 0.06 seconds and made no request. A local publication-only control
took 0.31 seconds. An intermediate transport had a Python 3.12 `read1()` response
closure bug; it is recorded separately and was fixed before the final run.

The policy selected on 22 October used eight workers and at most four request starts per
second, leaving headroom below FMP’s published Starter allowance. Shared 429
cooldowns reduce that rate further. Ten-year price windows returned about 2,519
sessions for the long-lived sample stocks, below the known 5,000-row cap. The
Treasury probe was empty and did not justify changing the proven monthly policy.
Cancellation and out-of-order publication are checked offline and on Windows.
Run `python3 tests/test_fmp_download.py` alongside data-manager/cache-access tests.

The 23 October standalone transport experiment is recorded in
`results/experiments/fmp-throughput-2026-10-23.json`. It made 1,392 distinct
stock/window requests. All returned HTTP 200. Gzip reduced transferred body bytes
by 89.1% across compressed cases. In native Windows Python 3.12.1, the eight-worker,
four-starts-per-second case averaged 207 calls/minute. The 32-worker, 45-starts case
averaged 1,207 calls/minute without compression. In WSL Python 3.14.4, the larger
32-worker gzip case averaged 2,265 calls/minute. More workers were slower in the
sampled comparisons. These findings set the current 32-worker, 45-starts-per-second
gzip policy. They do not establish guaranteed throughput.

The runs used different companies, periods and environments. Each fresh-pool
batch lasted about 2–19 seconds. The experiment did not measure the full data
panel or a minute-long sustained rate. Do not describe the ratio between these
cases as a controlled application speedup. The implementation checks use local
provider fixtures and temporary caches; they make no live FMP calls.


## Verified baseline revisions

A data addition can change a historical result without changing its Through date.
Preparation compares the SQL baseline with `revalue.calculate(through)`. The
reference calculation reads raw files and keeps its original selection and return
arithmetic. It does not call the prepared engine. Full-precision numbers use
relative and absolute tolerances of `1e-12`. All years and holding identities must
match. Equal annual averages cannot conceal a holding mismatch.

The reference calculation runs when the reuse scope changes, or when any company's
historical rows are recalculated, added or removed. Sometimes every historical unit
is copied, and the copied baseline equals the published verified baseline. Then
preparation keeps the earlier agreement, because both engines already agreed on
these exact historical inputs. A daily price update after the Through date
therefore needs no reference run. `--force` and `scripts/revalue.py` always run it.

When the engines agree, `backtest/inputs/baseline.py` updates the report and research
database together under cache ownership. `results/baseline-history/<generation>/`
retains the previous report verbatim, previous and new priced snapshots, the new
report and `audit.json`. The audit lists changed years, added or removed stocks,
ranks, fiscal inputs, price dates, prices and returns. The first verification
cannot recover prices missing from older databases. Those previous prices are
null and the audit marks the migration. Later revisions use saved priced
snapshots. Latest-only updates retain the historical revision.

Publication first stages and hashes the evidence and closed database. The
`data/research.sqlite.publication.json` journal binds the pending report and
database to that evidence. Journal targets use logical names. Evidence locators
use relative POSIX paths, so recovery also works after moving the project or
switching between Windows and WSL. Readers reject unfinished publication. Retrying
preparation completes a verified pending publication before testing freshness.
Do not delete the journal or its referenced files to bypass recovery. Comparison
failure leaves the existing report, database and website in place. A filesystem
failure can interrupt replacement; its journal permits an idempotent retry.

`python3 scripts/revalue.py` forces this same verified refresh at the saved cutoff.
It no longer writes an unchecked report or advances the historical cutoff.
Standalone website builds take cache ownership. Managed build subprocesses use
`--cache-owned` while the parent retains ownership. Daily preparation captures its
fingerprint after research preparation. No rebuild makes a market-data request.

### Full annual financial data

The full-data option saves complete annual income statements, balance sheets,
cash flow statements, key metrics and ratios under `raw/financial-inputs/`.
All returned fields are retained, including unknown fields, null values,
currencies and filing metadata. New `metrics.jsonl` records also keep complete
key-metric responses. Older trimmed records stay unchanged. The separate full-data
cache can backfill their discarded fields without rewriting baseline inputs.

Each endpoint uses annual requests with a 40-report limit. Saved responses do not
prove complete historical coverage. Empty responses are bound to their exact saved
asset by a content hash. Valid full responses are reused. Invalid originals are
backed up before repair. Interrupted publication retains a receipt for the saved
generation. Workers fetch; one owner publishes under the shared cache lock.

Schema version 7 adds `financial_inputs` for eligible numerical inputs. The raw
cache retains the other fields for future metric preparation. Selected annual
inputs must match the report selected by the original eligibility rules. No newer
report fills an older report's missing fields. P/E and P/B use screen-date market
cap. ROE uses average positive equity from the selected and prior fiscal years.
PEG divides P/E by three-year diluted EPS CAGR in percentage points; it requires
four consecutive positive annual EPS values and positive growth. Ratios require
positive denominators. Negative FCF, FCF yield and profit margins remain valid.

Run `python3 tests/test_financial_inputs.py`, research and schedule checks, then
build and run browser parity checks. These checks use offline fixtures.

Annual responses can contain repeated fiscal dates. Keep every returned row, including identical rows. A repair also retains distinct saved variants. Preparation uses a numerical input only when all nonmissing USD values for that endpoint and fiscal date agree. Conflicting inputs stay absent. Nulls do not replace known values. Response order does not select a revision.

### Annual observation evidence on the feature branch

Phase 9 Slice 1 prepares all 48 direct annual inputs from the semantic catalog.
Income, balance-sheet and cash-flow evidence retain their endpoint, exact fiscal
date, saved asset hash and contributing row identities. All admitted dates stay
visible, even when every requested field is unavailable. Boolean, malformed and
nonfinite field values are unavailable. Finite signed amounts and zero stay valid.
This evidence does not widen raw-response acceptance or the legacy financial
values projection. Existing calculations and selections keep their inputs.

The direct observation provider selects one income fiscal spine per dated
context and history depth. The current period is the existing financial-policy
report. Each earlier year uses its latest eligible income fiscal date. Balance
sheets and cash flows join those exact dates. They cannot choose another date
when a selected-period fact is missing. The strict 90-day availability rule and
800-day current-anchor limit remain in force. Earlier history members keep the
existing calendar-year buckets and can be older than 800 days.

Observation evidence version 4 retains `observation_dated` and
`observation_sessions` and adds prepared measure contexts and explicit scope identities. Research schema 11 and daily cache version 5
require offline rebuilding of older observation projections. Their content
identity, preparation policy and semantic source bind reuse. The content
identity hashes what determines the rows: the raw-file signature, each price
file's content digest, the reuse scope and the scopes. Preparation does not
hash the rows themselves, so an incremental build and a full rebuild of the
same inputs record the same identity. The daily cache copies each observation
table with one SQL statement. The new
read-only `dated_observation_inputs.py` resolver also participates in freshness.
Optional `raw/download-coverage.json` presence and metadata participate too.
A matching current or previous SeriesAsset receipt identifies exact saved bytes.
Missing or unbound receipts do not erase usable facts or prove a download.
Daily and immutable numerical storage copy the complete projection unchanged.
Numerical temporal version 1, arrays and worker references keep their formats.

Price and volume use the saved SPY session on or before the context, within seven
calendar days. Each needs the stock's own field on that exact session. Price is
finite and positive. Volume is finite and nonnegative; zero and fractional saved
volume remain valid independently of price. Price uses USD/share in an admitted
USD company context when route currency is absent. Explicit foreign currency
makes that price unavailable. No FX conversion occurs. Treasury uses the latest
saved source date on or before the context. It resolves month3 and year10 at that
one date and divides provider percent by 100. Signed and zero rates are valid.
Null, invalid or conflicting latest fields do not borrow older field values.
Dated inputs require no earlier annual anchor after root admission. Legacy
financial valid-series and as-of behavior keep their existing meanings.

Borrowed session, exact-row, as-of-row and source reads use indexed bounded
queries. Their facts are detached. Individual records and endpoint histories
keep the existing ceilings. Provider preflight charges source, calendar and
row reads. Retained evidence counts against its byte limit. Company and dated
reads check view lifetime; they do not rescan the whole generation. Operation
entry checks the daily fingerprint once: raw file metadata and the recorded
research metadata, not the prepared rows. Between steps, Original checks one
research-file status at each view boundary. The exclusive cache lock keeps the
prepared rows unchanged for the whole operation.

The direct provider and callable reference evaluator support all 52 direct inputs
plus operating margin, existing dated EV and Phase 10 reusable measure adapters.
The 33 named measures use immutable ordinary definitions and exact references.
A prepared January or latest root consumes its stored owner lanes. A derived
context uses dated owner policy, even at the root date. Missing prepared lanes
never fall back to recalculation. Report EBITDA uses broad accepted report
history. Reported EBIT, FCF, debt and EPS use the income fiscal spine and exact
endpoint dates. Only those named annual adapters support annual history.
Projection 4, research schema 11 and daily cache 5 require incompatible caches
to rebuild; durable records keep their formats. Version-3 authoring exposes all
52 direct inputs, policy adapters and 33 exact measures. The original four-item
catalog remains available for legacy definitions. `variables.selection.require_program()`
owns qualified scalar admission. Supported captures run through Original in
Latest, January, fixed and random modes. Original sample preview and complete
recorded January/latest coverage are separate operations. Eager scalar execution
remains unsupported.
Semantic restoration remains independent of execution qualification.
Old definitions, captures, artifacts and durable records retain their bytes.
Private synthetic tests establish source correctness, not native/live-cache
coverage. No download, publication to main or running-server update is implied.
