# Fast local screening and backtesting

Normal research should query the prepared databases instead of reparsing daily JSON price files. The embedded SQLite engine is included in Python; no database server, package installation, API key, or network connection is required. The engine can later be replaced with DuckDB if larger analytical datasets warrant it; this project does not currently depend on DuckDB or Parquet.

## Prepare once

```bash
python3 scripts/research.py prepare
```

Every preparation is a full build. It reads the saved universe, annual
financials and each cached price file, writes a temporary database and replaces
`data/research.sqlite` in one step. A failure keeps the previous database. A
current database is kept: when the saved inputs and calculation code have not
changed, preparation only checks source metadata. Queries skip the full
per-price-file scan to keep parameter changes fast. Raw downloads are preserved.
`--force` rebuilds a current database too. Preparation runs no second engine and
publishes no report; the development check (`python3 scripts/check.py`) compares
the book code with the independent reference on the real-data bench.

Research schema 17 stores facts only, no book:

- Each saved company with its name, exchange and sector (cached metadata, not
  historical profiles) and whether it is listed now (`companies`).
- Financial period end, assumed availability date, report market cap, enterprise
  value, inferred EBITDA, and EBITDA/EV for valid USD reports, and the extra
  annual inputs in `financial_inputs`.
- Saved 10-year Treasury yields in `treasury10`.
- The typed facts below.

The daily cache, `data/schedules.sqlite` (version 9), holds the book store
(`backtest/inputs/book_store.py`): one row shape, one writer and the readers of
latest and dated books. `books(book, entry, exit, spy, candidates)` names one
entry and exit, in one book-id space; `book_pools(book, pool)` marks each
completed pool; `book_rows` has one row per pool and company (rank, fiscal and
known dates, entry date and price, exit, valuation, EBITDA, yield, multiple,
spread, return and status), with `book_metrics` and `book_filters`. The latest
book is the book with no exit at the research database's latest date; it has
no return or status, and `candidates` is its count of eligible financials. No
future holding return is attached to its picks. Daily preparation writes it from
the typed facts with `books.book`; dated books are computed with the same
function when a backtest first needs them. A daily connection
(`daily.connect`) attaches the research database read-only as the schema
`research`: books, sessions and company names come from there, and the daily
cache copies no research table. Readers select a book's rows in the row shape
that results and the website keep: a dated row has the old daily snapshot
columns and a latest row the old latest snapshot columns (`price_date` is the
entry session). The daily cache also keeps parsed prices, SPY sessions, 3-month
and copied 10-year yields; only its kept-book check reads them.

`books.Screen(day, facts)` is the one admission rule, and
`Screen(...).decide(symbol, pool, exit_day)` decides one company of the latest
book, of a dated book, or of a formula root (no exit). The entry day must be a
saved SPY session on or after `rules.FIRST_DAY`. The gates, in order, give
these denial reasons (`books.REASONS`): `UNKNOWN_COMPANY`, `NOT_LISTED` (latest
book only), `NO_ELIGIBLE_REPORT`, `OUTSIDE_LEGACY_BUFFER`,
`MISSING_CACHED_PRICES`, then the entry valuation (`MISSING_PRICE`,
`NONPOSITIVE_VALUATION`, `NONFINITE_RESULT`), `INELIGIBLE_VALUATION`, and for a
dated book `ENTRY_NOT_BEFORE_EXIT` and `MISSING_EXIT_PRICE`. Formula roots
(`facts.View.admit`) and saved results show these reasons; results saved
earlier keep the reasons they stored.

Preparation reuses the existing 90-day lag and 800-day report-age rule. A report
must become available strictly before the buy date, matching the original code.
Entry EV is reconstructed using the dividend-adjusted price and report net debt,
with the same limitations as the original backtest. Reported financials may
contain later vendor revisions: the 90-day rule is an availability assumption,
not proof of a true point-in-time vendor archive.

## Inspect the prepared database

```bash
# Database size and the latest session's price coverage (the latest book of the daily cache)
python3 scripts/research.py status
```

The January `screen` command was removed with the January mode. A January study is a 12-month dated schedule from 1 January: run it as a custom schedule on the website or in the queue. By default, filters apply before ranking; rank 1 has the lowest selected multiple within the matching pool (EV/EBITDA by default). **Rank first, then filter** selects the requested ranks before applying user filters. Selected stocks are equally weighted. Selection uses entry information, never future return. Treasury subtraction does not change the ordering within a date.

`legacy` pool means **original-screen-compatible candidate selection**, not the older exit rule: both pools retain early trading stops at their last price and apply the explicit `BANKRUPT` overrides (keyed by symbol and day of loss; a book whose window contains the day takes the loss). This pool preserves the original report-level $100m market cap/$50m EV filters and 250-name buffer, so lowering those filters in a query cannot recover companies already excluded by those rules. Use `cached` to vary those thresholds more broadly.

`cached` considers all available positive-EV USD reports for companies with cached price files. Its report selection can differ from the original pool because the original report-level size filters are not applied. It cannot claim to be the full 11,000-company universe. The status command reports the latest session's eligible financials and price-valued names. Acquiring missing prices is a separate, explicit task.

Expanded selections may include early stops outside the original 37-name review, so their default last-price exits have not received the prior manual bankruptcy investigation.

## Website

```bash
python3 website/build.py
```

Normal builds write ignored `website/local/`, which the local server serves. Startup and data-panel rebuilds leave the tracked `website/dist/` snapshot unchanged. Refresh that portable snapshot only with `python3 website/build.py --snapshot`. Review its generated files and the `snapshot.json` latest date and source hashes before committing. Range and SQL/browser parity checks default to local output; pass `website/dist` to check the portable snapshot instead.

The website builder reads the latest book of the daily cache and embeds the latest-session candidate pools in self-contained HTML. It opens in Latest stock picks mode; switch to Historical backtest for dated schedules on the local service. Latest screening uses exact-date prices and cached currently-listed status, excluding older stopped prices. The browser supports portfolio ranks and size (including top 100), market-cap bounds, minimum EV, minimum selected metric yield, maximum selected multiple, sector, exchange and pool filters. Click Screen latest or Run backtest to apply financial filters in the chosen mode. Each dated period has gain/loss contribution pies and the top 10 stocks ranked by signed equal-weight return contribution (or all stocks when fewer than 10 are selected). Saved January results open in the dated view without calculation. See `website/README.md` for units and controls. Strategy CAGR and cumulative growth are unavailable if any period has no matching stocks; SPY remains for the full selected period.

`backtest/engines/reference/revalue.py` remains a slower, independent cache-based calculation of the January study. Only the development check uses it; no build, startup or preparation runs it. After editing raw data, run preparation again. Queries detect changed core data files, price-directory changes, bankruptcy overrides and calculation code; preparation also detects edits to existing individual price files. Run one preparation process at a time. Choose the portfolio size with the ranks in the strategy builder.

## Checks

```bash
python3 tests/test_research.py
python3 tests/test_prepared_facts.py
python3 tests/check_paths.py
node tests/check-range.cjs
node tests/check-contributions.cjs
python3 tests/check_screener.py
```

The research tests cover availability dates, rank selection before future returns, filters before ranking, early stops, bankruptcy overrides, price alignment, read-only access, stale database detection, failed builds and Windows sharing retries. `python3 tests/test_reference_check.py` runs the development check on a private fictional cache. Website tests check rank and screen controls and the saved-January dated view using a simulated DOM, and compare browser latest picks against SQLite, including combined threshold conditions. These automated checks do not replace a real-browser visual review.

## Measured performance

Research and daily preparation of the real cache were measured on the private
bench copy; the typed-storage plan records the stage times and sizes. These are
observed timings, not guarantees. See also `results/experiments/performance.json`
for older measurements of a smaller January-only database.

The 1996 legacy pre-price buffer yields only 61 usable holdings, so it cannot supply a complete top-100 book. The wider pool also has incomplete price coverage of the universe. The engine reports insufficient matches instead of claiming 100 names in every period.

## Current-date preparation

The latest book of the book store is the current-date screen. The latest target is the newest cached SPY session. Only cached companies marked listed with a price on that exact session and a usable available report receive current valuations. The original latest candidate pool retains the 250-name pre-price buffer; the broader pool uses all eligible active names with current cached prices. `screening.latest()` exposes the same SQL filters and rank semantics without return fields.

Updating a database and rebuilding HTML are separate from fetching missing or new market data.

### Select a ranking metric

Latest screens and dated books support
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
pure metric calculations. `books.book` stores each book's ready-to-rank
multiple/yield pairs in `book_metrics` by book, pool, symbol and metric ID. Thus
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
Select **Historical backtest**, enter a starting date and final mark date, and
choose monthly, quarterly, half-yearly or yearly. Latest picks still work by
opening the HTML directly; custom schedules need the local service because
daily histories are kept out of the embedded page.

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
rows and existing application envelopes.
`data/schedules.sqlite` is ignored. It is replaced atomically when inputs or
calculation code change, and preparation refreshes it from the previous cache
(below). Repeated preparation validates source freshness without
parsing prices. Newly requested entry/exit pairs are computed once and persisted;
filter, metric or rank changes reuse those books and shared SQL selection.
Only the requested stock pool is prepared. Switching between the original and
broader pools fills the missing pool once for each existing dated period; it
does not recompute the completed pool. Empty pools are recorded as complete too.
The book store tracks this in `book_pools`. Daily inputs include a digest
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
the books in 1.4 seconds. A 31-period 12-month schedule from January 1996
through October 2026 matched every reference selection and annual return. The local service
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

The website runs these requests on Original, which keeps ordinary saved-book
recovery. Saved-library and completed queue snapshots remain readable after
current input changes.

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
workers read prepared inputs with read-only daily connections that attach the
research file the parent admitted, and calculate ahead with `books.book`. Each
process loads report histories once. Price queries share one short read
transaction per book, avoiding repeated native Windows lock operations. The
reader releases it before returning the book; no reader holds a transaction
across multiple books. Only the parent saves books, using `book_store.store` in short write
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
candidate buffering, entry valuation and holding returns. Latest preparation
and the daily engine supply array and SQL price adapters respectively;
`revalue.py` remains the independent reference of the development check.

Random streams publish their resolved configuration before executing trials.
The browser saves that configuration locally immediately. **Replay saved date
test** repeats the window, filters, frequency, trial count and seed after a
disconnection or launcher restart; completed books are reused. Fresh runs still
generate a new seed by default.

### Upfront parallel-book benchmark

On native Windows Python 3.12, 100 full-history annual random-date trials took
103.4 seconds with one worker, 62.0 with two, 40.9 with four, and 33.2 with eight.
A fresh serial requested-pool control took 133.3 seconds, matching the earlier
133.1-second measurement. A four-worker run of the applied implementation,
including forced-shutdown worker cleanup, took 43.2 seconds (about 3.1× faster
than the serial control). Cached replays took about 5.6 seconds. These timings
do not measure the current automatic policy of up to eight workers for at least
16 missing books, or the once-per-worker financial decoding.

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

**Selection order** applies to latest, fixed and random-date views.
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
nulls first, then symbol ascending. Each dated book ranks independently.

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
Each book stores them in `book_filters`, separately from ranking pairs.
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
date. There is no added yield-age limit. Latest uses its exact saved SPY
session. Dated books use their entry session, even if a stock's first buy price
is a later session. The filter uses
percentage points: enter `5` for a spread above or below 5 pp.

Research keeps `treasury10(day, yield_percent)` from saved `year10` fields in
`raw/treasury.json`; books read the valid 10-year values of `market_days`
(`facts.ten_year`). Prepared
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
existing price-cache stocks (the default, which dated books need), all eligible
financial stocks, or up to 200 specific symbols. Choose a price-history range;
the default ends on the latest available day, today. Include prior prices for
report-date valuation and trailing returns.

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
the file's other saved keys are retained; no calculation reads a key other than `div`. Each price or market window is published by
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
and the website build without network requests. Every research build is a full
build. Open the
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
prepared database or prior website build.
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


## Frozen January record

`results/summary-exits.txt`, `results/baseline-history/`, `results/legacy/` and
`results/stops/` are a frozen record of the January study. Nothing regenerates,
collects or changes them.

The development check, `python3 scripts/check.py [--through YYYY-MM-DD] [--json
OUT]`, runs one Original custom run: every 12 months from 1 January 1996 to the
through date (default: the frozen report's Through date, 2026-10-20), legacy
pool, `ev_ebitda` ranks 1–50 and the default floors. It compares every book,
holding, date, valuation, return and exit status with `revalue.calculate(through)`
at full precision (relative and absolute tolerance `1e-12`) and names each
difference. It also compares the annual rows with the frozen report at four
decimals. It passes with no difference in either comparison. The reference
engine keeps the January study's label rule: a book that ends in its entry year
is marked to date. In this 12-month run only the last book is a mark, so the
labels agree. Run it on the real-data bench after a change to book policy
(`books.py`, `rules.py`, the dated book writer or its price lookups). The study
constants (`FIRST_YEAR`, `LAST_YEAR`, `ASOF`, `HOLD`) live in
`backtest/engines/reference/legacy.py`.

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

### Typed prepared facts

Research preparation writes the inputs of custom-variable formulas as typed
tables in `research.sqlite`, owned by `backtest/inputs/facts.py`. Typed facts
version 4 belongs to research schema 17; older caches rebuild. The daily cache
does not copy them: Original reads them on the operation's research
connection, and books read them through the attached `research` schema. Preparation reads and parses each saved price, SPY and Treasury
file once. A saved file that cannot be read stops preparation, as an invalid
`metrics.jsonl` record does; the data panel downloads it again.

One rule gives each saved day its value, for formulas and books alike. Equal
admissible values agree. A conflicting, non-USD or invalid value gives no
value and a reason. Prices are the dividend-adjusted closes (`div`); valuation
and returns read the same series. `facts.BookFacts` is the facts port of books:
reports by pool, cached companies (from `fact_sources`), listing (from
`companies`), the valid adjusted closes, SPY sessions and yields.

- `stock_days(symbol, day, adjusted, adjusted_reason, volume, volume_reason)`:
  one row per company and saved price day.
- `market_days(day, spy, month3, month3_reason, year10, year10_reason)`: `spy`
  is set on a valid SPY session; a saved Treasury day has a value or a reason
  for both fields (both yields in percent).
- `companies(symbol, name, exchange, sector, listed)`: each saved company and
  whether it is listed now.
- `facts.legacy_annual` derives the legacy annual values
  (`financial_inputs.ENDPOINTS`, valid values only) from `annual_facts`, and
  `facts.ten_year` reads the valid 10-year values. `books.book` and the dated
  owner policy read them through these two functions.
- `annual_facts(symbol, endpoint, fiscal, <field>, <field>_reason, ...)`: one row
  per company, statement endpoint and fiscal date, with one value and one
  reason column for each annual catalog field (parameter id without `annual.`).
- `fact_sources(symbol, endpoint, sha256, disposition)`: the digest of each
  annual, price, Treasury (`''`) and SPY (`''`) source file.
- `fact_metadata`: version, latest date, prepared scopes, policy and content
  identity.

A field is valid when its value is present; otherwise its reason column names
the reason (`MISSING_INPUT`, `CONFLICTING_INPUT`, `NON_USD_INPUT` or
`INVALID_INPUT`). Value columns have no declared type, so SQLite keeps the
binary64 bits exactly, including -0.0, which a REAL column stores as the
integer 0. Days are keyed by date, never by raw-file row. Prepared latest owner
lanes are the latest book's stored rows (`book_rows`, `book_metrics`,
`book_filters`), read in place; a missing row never falls back to a
recalculation. A formula root is admitted by `books.Screen.decide`: a latest
root by the latest book's screen (listed companies, the exact session), a
historical root by its date's screen. A historical decision that reaches the
entry valuation keeps the lookups that the view's recording facts port saw.

Annual resolution (`financial_inputs.resolve_history`) keeps every admitted
endpoint and fiscal date, even when every requested field is unavailable.
Equal USD values agree. Conflicting values stay unavailable. A null does not
replace a known value. Boolean, malformed and nonfinite values are unavailable;
finite signed amounts and zero stay valid. This does not widen raw-response
acceptance or the legacy financial values projection.

The column evaluator (`backtest/variables/columns.py`) selects one income
fiscal spine per dated context and history depth. The current period is the
existing financial-policy report. Each earlier year uses its latest eligible
income fiscal date. Balance sheets and cash flows join those exact dates. They
cannot choose another date when a selected-period fact is missing. The strict
90-day availability rule and 800-day current-anchor limit remain in force.
Earlier history members keep the calendar-year buckets and can be older than
800 days.

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

The facts' content identity hashes what determines the rows: the raw-file
signature, each price file's content digest, the scopes and the preparation
policy: the content of each file in `research.calculation_sources()`, the
list that the raw-file signature also binds. An edit to one of these files
therefore rebuilds research before readers check the facts.
The raw-file signature leaves out `raw/download-coverage.json`, which no
preparation reads. Preparation does not hash the rows themselves. The daily cache binds
that metadata. Operation entry checks the daily fingerprint once: the accepted
raw-file signature and the recorded research metadata, not the prepared rows.
Inspecting about 36,000 raw files takes about 1.7 seconds on the real cache, so
readers reuse the signature taken by preparation or after the last data-panel
action. A hand edit to `raw/` needs a data-panel check before readers see it.
Between steps, Original checks one research-file status at each view boundary.
The exclusive cache lock keeps the prepared rows unchanged for the whole
operation. The borrowed view reads each company, day and source once.

The evaluator supports all 52 direct inputs plus operating margin, existing
dated EV and the reusable measure adapters. The 33 named measures use immutable
ordinary definitions and exact references. A latest root consumes its stored
latest owner lanes. Every other root, January sessions included, and every
derived context use dated owner policy, even at the root date. Report EBITDA uses broad accepted report history.
Reported EBIT, FCF, debt and EPS use the income fiscal spine and exact endpoint
dates. Only those named annual adapters support annual history. Typed facts 4,
research schema 17 and daily cache 9 require incompatible caches to rebuild;
durable records keep their formats. Version-3 authoring exposes all 52 direct
inputs, policy adapters and 33 exact measures. The original four-item catalog
remains available for legacy definitions. The language check,
`definitions.require_program()`, is the one formula gate, and the one evaluator
implements the whole language. Restored captures run through Original in
latest, fixed and random modes; a January request is refused. Original sample
preview and complete recorded latest coverage are separate operations. Eager scalar execution
remains unsupported. Old definitions, captures, artifacts and durable records
retain their bytes. Private synthetic tests establish source correctness, not
native/live-cache coverage. No download, publication to main or running-server
update is implied.
