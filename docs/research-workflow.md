# Fast local screening and backtesting

Normal research should query the prepared databases instead of reparsing daily JSON price files. The embedded SQLite engine is included in Python; no database server, package installation, API key, or network connection is required. The engine can later be replaced with DuckDB if larger analytical datasets warrant it; this project does not currently depend on DuckDB or Parquet.

## Market data and calculations

The source supports one market per run: US, Hong Kong (Main Board and GEM) or Japan (Tokyo). Hong Kong leaves out 4xxx codes. The provider lists bonds and dormant Hong Kong lines of US companies there; those lines have months-old prices and the companies' worldwide share counts. Preparation also applies this rule to a saved stock list. New website strategies use the broad cached-price pool. The legacy US pool remains for recorded work and the reference check. Missing market data requires an explicit data-panel action or the existing authorized scheduled update.

US raw paths stay unchanged. Foreign inventories and local-index calendars live at `raw/markets/<market>/universe.json` and `calendar.json`. Shared suffixed symbols keep annual endpoint files in `raw/financial-inputs/` and adjusted prices in `raw/px/`. Native unadjusted closes live in `raw/px-full/`; direct USD FX pairs live in `raw/fx/USD<currency>.json`. All use the current bounded transport, parent-owned publication and content-bound receipts. Foreign reports do not append to US `metrics.jsonl`. Every returned annual row and field stays in its endpoint asset.

Research adds `company_markets`, `annual_metadata`, `foreign_reports`, `stock_native`, `local_sessions` and `fx_days`. Its identity has `latest_dates` by market and preserves `latest_date` for US consumers. Each latest screen embeds only its market’s companies, choices and actual saved bounds. No missing foreign asset falls back to US data.

All displayed money, thresholds, holdings, returns and CAGR use USD. Foreign fiscal cap uses annual basic weighted-average shares and a native unadjusted fiscal close. The existing adjusted-price rescaling updates it to entry. Report amounts for every annual year use the context date’s FX. Holding prices use their own observation date’s FX. Daily date-only FX uses the previous completed fixing. SPY is always the S&P 500 total-return benchmark; Asian sessions use the previous completed US close within seven calendar days. Cash is USD at 0%. Reference yields remain US Treasury yields.

US report availability retains its strict fiscal-plus-90-day rule. HK and JP use reliable publication dates where available; otherwise four and three calendar months. Period-end placeholders do not prove publication. The 800-day current-report limit remains. Missing inputs and conflicts stay unavailable. FMP source revisions, incomplete listing history, zero-heavy fields and dividend-adjustment limits remain disclosed. See [Dividends](#dividends).

New formulas use definition version 3, catalog `financial-parameters/4` and temporal policy `market-annual/1`. Catalogs /1–/3 preserve US meanings. Foreign execution requires explicit upgrade to /4. Upgrade rebinds immutable named measures to their /4 revisions. User-defined references retain their exact revisions; upgrade and save those definitions separately, then choose their new revisions. Existing captures, jobs, artifacts and durable records retain their bytes. The data-panel market selector scopes manual Update; scheduled maintenance refreshes inventories already present through its existing cycle.

### Dividends

The engine keeps no dividend cash. Every stock price is FMP's dividend-adjusted close, so a holding's return is `adjusted exit / adjusted entry − 1`. This is a total return: each dividend counts as reinvested in the same stock on its ex-date, before tax. Hong Kong and Tokyo prices are adjusted in the local currency, and each endpoint is converted to USD with its own date's FX. SPY and the trailing-return filters use the same kind of series.

This method has four known limits. They are accepted as they are.

- **Entry valuation is too high for dividend payers.** Fiscal market cap is rescaled to entry with the adjusted price ratio. That ratio includes the dividends paid between the two dates, so entry market cap and EV are too high by about that amount, and a high-dividend stock ranks slightly lower than it should.
- **FMP omits some dividends.** The adjusted series then shows no payment, and that holding's return is too low.
- **FMP records a few adjustments that are much too large.** That holding's return is too high.
- **Returns are before tax.** No withholding tax and no delay between ex-date and payment are modeled.

The sizes were measured for Hong Kong on the private bench copy of the runtime's raw cache (prices through 6 November 2026, source 3989437). The check ran outside the engine on stored book rows with the engine's price rules: the first session of each month from August 2001 to November 2025, the top 50 by EBITDA/EV with market cap of at least $100 million and EV of at least $50 million, held 12 months.

| Item | Measured for these Hong Kong picks |
|---|---|
| Mean 12-month return | 15.8% in USD, of which dividends are 4.4 percentage points. For picks entered from 2018: 7.0%, of which 5.5 points. |
| Entry market cap too high | Median 2.2%, mean 3.4%, one pick in ten above 7.9%. From 2018: median 3.4%, one in ten above 10.8%. |
| Effect of that on picks | Rescaling with the unadjusted close in `raw/px-full/` changes about 6% of picks. The mean return moves from 15.8% to 16.2%, inside the spread between periods (standard deviation 2.6 points). |
| Omitted dividends | In about 11% of pick-years the cash-flow statement shows dividends and the adjusted price shows none (for example Sinopec, fiscal 2017 and 2020). The yield implied by prices is 3.6% against 4.7% from statements. The gap is an upper bound: statement amounts can include payments to other holders. |
| Oversized adjustments | 19 symbols show a one-year adjustment above 25% of the price (for example 3903.HK: 73% of the price on one day in 2018). With these holds at their price-only return, the mean falls from 15.8% to 15.1%. |
| Tax | At most about 0.5 points a year if every pick had 10% withholding. This is arithmetic, not a measurement. |
| Rounding of low adjusted prices | Negligible: 0.6% of picks can be wrong by more than 1%. |

The two FMP errors have opposite directions, so the average Hong Kong return is probably correct to about one percentage point a year, while the return of one holding can be far wrong. These are observed values, not guarantees. US and Tokyo were not measured, and the US cache has no unadjusted prices.

Three changes would reduce these limits and are not made: leave out series with oversized adjustments at preparation, as for broken price series; rescale Hong Kong and Tokyo entry market cap with the unadjusted ratio, which changes calculations; and compare dividends with a second source, which needs a download.

## Prepare once

```bash
python3 scripts/research.py prepare
```

Compatible preparation reconciles changed typed rows in `data/research.sqlite`
in one transaction. Unchanged bulk sources skip decoding. Cold, schema or
fact-code builds use a temporary database and atomic replacement. A cold build
of 2,000 or more companies uses eight worker processes, one symbol range
each, and gives the same database as a one-process build. A failure
keeps the previous committed data. A current database is kept: when the saved
inputs and calculation code have not
changed, preparation only checks source metadata. Queries skip the full
per-price-file scan to keep parameter changes fast. Raw downloads are preserved.
`--force` reconciles a current database too. The last stage of either build
folds the valuation sums (below) in the same transaction: a cold build folds
every company; a compatible build refolds each affected company once, from its
earliest sheet cutoff over all markets (`books.affected_entries`), with its
current market. The sums add in day order from zero, so a refold that
continues from the stored sums equals a cold build bit for bit. Preparation
runs no second engine and publishes no report; the development check
(`python3 scripts/check.py`) compares the book code with the independent
reference on the real-data bench.

Research schema 21 stores facts and the valuation sums derived from them, no
book. It also retains income EBITDA for foreign-report derivation. The public
parameter catalog is unchanged. This section owns the current research schema
and daily cache versions; other documents link here.


- Each saved company with its name, exchange and sector (cached metadata, not
  historical profiles) and whether it is listed now (`companies`).
- Financial period end, assumed availability date, report market cap, enterprise
  value, inferred EBITDA, and EBITDA/EV for valid US reports (`statements`); foreign statement anchors use `foreign_reports`.
- The typed facts below: the extra annual inputs and the 10-year Treasury
  yields are typed facts too (`annual_facts`, `market_days.year10`).
- For each company and priced day with a yield, the running sums of daily
  E/P, S/P and B/P and their day counts (`valuation_sums`, folded by
  `facts.refold` from `books.valuation_days`). Books read them for the
  valuation averages.
- The one research record (`metadata`): the schema version, the accepted
  raw-file signature (`inputs`), each price file's size and time (`prices`),
  and the identity (below).

The daily cache, `data/schedules.sqlite` (version 13), holds compact entry
sheets in `books`, `book_pools` and `book_rows`. The header names an entry
session, its latest/historical policy and its candidate count. Pools share
one handle. `book_pools` marks complete pools, including empty ones. One row
per stock holds the report dates, actual entry date and price, valuation,
EBITDA, spreads, metric pairs and filter values. Catalog mappings in
`book_store.py` name `m_<id>_multiple`, `m_<id>_yield` and `f_<field>` columns.
NULL means unavailable. Stored owner lanes retain REAL rounding and zero
normalization; typed research facts and formula outputs preserve signed zero.
The version-11 metric/filter tables and stored exit/return/status fields are gone.

`book_store` owns the schema, writer and row/lane readers. SQL selection reads
its compact columns directly. A daily connection (`daily.connect`) attaches
research read-only as `research`; the daily cache copies no facts or company
metadata. Its binding names the research content and book-code identities.
Historical sheets are keyed by market, entry and pool. Runs build missing sheets on
demand. Different exits reuse the same sheet. Latest keeps a separate header:
it requires currently listed companies and an exact-session entry price.
Historical entries allow up to four calendar days of forward slack.

`books.Screen` and `Screen.decide` own entry admission: saved market session from
`rules.FIRST_DAY`, company, listing for latest only, eligible report, legacy
buffer, cached prices and entry valuation. `books.book` uses that one rule and
`owner_values` for both policies. It reads no holding exit. A dated run restricts
actual entry strictly before exit before ranking, either selection order, scalar
scope limits or formulas. It calls `books.close` only for selected holdings,
using the same scheduled/last-price/bankruptcy rules. A missing close fails
explicitly. SPY comes from the current admitted facts. `portfolio_results`
keeps final-mark labels and all portfolio arithmetic. Old result artifacts keep
their complete recorded holding rows and are never recalculated.

Preparation uses each market's reporting policy and the 800-day report-age rule. A report
must become available strictly before the buy date, matching the original code.
Entry EV is reconstructed using the dividend-adjusted price and report net debt,
with the same limitations as the original backtest. Reported financials may
contain later vendor revisions: fallback delays are availability assumptions,
not proof of a true point-in-time vendor archive.

### Identities: which code binds what

Two identities decide what a code edit makes stale. Each is a content digest
(sha256) of the files that hold one role's code, so a rewrite with equal bytes
keeps it. `research.code_sources(role)` holds the one role rule.

- The research identity binds the fact-row code: research preparation, the
  parsing and writing parts of `facts.py`, `books.statements`,
  `financial_inputs` with its parameter catalog, `cache_assets`, `market` and
  `rules`. The record's `identity` holds the schema version, the latest date,
  this code identity (`code`) and the facts' content identity (`content`: the
  code and the bytes of every saved file that preparation read, by their
  `fact_sources` digests and the universe and annual-metrics digests).
- The book identity (`research.code_identity('books')`) binds the book code:
  `books.py`, `metrics.py`, `rules.py`, `facts.BookFacts` and `book_store.py`.
  It also names the legacy annual field list that `BookFacts.legacy_annual`
  reads (`facts.LEGACY`). That list comes from fact-row code
  (`financial_inputs.ENDPOINTS` and the catalog), so an edit to it drops every
  saved book.
- Readers bind no identity: the formula view (`backtest/inputs/fact_view.py`),
  `schedules`, `book_batch`, `calendar`, `portfolio_results`, `screening`,
  `scalar_execution`, the command-line tools and the connection code. An edit
  to a reader neither rebuilds research nor drops a saved book.

The daily binding (`daily_inputs` in the daily cache) holds the daily cache
version, the research content identity and the book identity; `daily.binding`
is its one reader. Readers check the raw-file stamps and the fact-row code
against the research record, then the daily binding against the current one,
once at operation entry (`daily.connect`). A fact-row code edit rebuilds
research; a book code edit drops every saved book. Results record the daily
binding's digest as `input` and the research identity as `projection`.

## Inspect the prepared database

```bash
# Database size and the latest session's price coverage (the latest book of the daily cache)
python3 scripts/research.py status
```

There is no January screen command. A January study is a 12-month dated schedule from 1 January: run it as a custom schedule on the website or in the queue. By default, filter steps come before the Rank; rank 1 has the lowest selected multiple within the matching pool (EV/EBITDA by default). A Rank step placed before the filters selects the requested ranks before applying them. Selected stocks are equally weighted. Selection uses entry information, never future return. Treasury subtraction does not change the ordering within a date.

`legacy` pool means **original-screen-compatible candidate selection**, not the older exit rule: both pools retain early trading stops at their last price and apply the explicit `BANKRUPT` overrides (keyed by symbol and day of loss; a book whose window contains the day takes the loss). This pool preserves the original report-level $100m market cap/$50m EV filters and 250-name buffer, so lowering those filters in a query cannot recover companies already excluded by those rules. Use `cached` to vary those thresholds more broadly.

`cached` considers all available positive-EV USD reports for companies with cached price files. Its report selection can differ from the original pool because the original report-level size filters are not applied. It cannot claim to be the full 11,000-company universe. The status command reports the latest session's eligible financials and price-valued names. Acquiring missing prices is a separate, explicit task.

Expanded selections may include early stops outside the original 37-name review, so their default last-price exits have not received the prior manual bankruptcy investigation.

## Website

```bash
python3 website/build.py
```

Normal builds write ignored `website/local/`, which the local server serves. Startup and data-panel rebuilds leave the ignored portable export `website/dist/` unchanged. Only `python3 website/build.py --snapshot` writes it, with `snapshot.json` (its latest date and source hashes). Range and SQL/browser parity checks default to local output; pass `website/dist` to check the portable export instead.

The website builder reads the latest book of the daily cache and embeds the latest-session candidate pools in self-contained HTML. It opens in Latest stock picks mode; switch to Historical backtest for dated schedules on the local service. Latest screening uses exact-date prices and cached currently-listed status, excluding older stopped prices. The browser supports portfolio ranks and size (including top 100), market-cap bounds, minimum EV, minimum selected metric yield, maximum selected multiple, sector, exchange and pool filters. Click Screen latest to apply financial filters to the latest picks; a dated test runs from Add to queue. Each dated period has gain/loss contribution pies and the top 10 stocks ranked by signed equal-weight return contribution (or all stocks when fewer than 10 are selected). Saved January results open in the dated view without calculation. See `website/README.md` for units and controls. A complete period with no matching stocks holds cash at 0% until rebalance. SPY keeps its period return, and CAGR uses the full elapsed window. Saved originals retain their recorded totals.

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

Preparation of the real cache was measured on the private WSL bench copy of
the runtime's raw cache (US and Hong Kong files of 2026-11-09), with the
valuation-averages source, eight calculation workers and other load on the
machine:

- A cold research build took 138 s with eight range workers and 527 s in one
  process (files of 2026-11-11, quiet machine). No process used more than
  0.5 GB. `research.sqlite` is 3.8 GB.
- Precomputing all 15,396 historical sheets took 1,226 s. `schedules.sqlite`
  is 10.8 GB.
- An update from the 2026-10-21 files (US only) to those files took 584 s
  for research and sheet repair, plus 483 s for the new sheets. The result
  equals a cold build bit for bit.
- A random-date test (24 quarterly trials, 2013–2026, 1,344
  periods, ranks 1–30, the cached pool, three built-in conditions and one
  custom variable) took 52 s with its sheets precomputed.

These are observed timings, not guarantees. See also
`results/experiments/performance.json` for older measurements of a smaller
January-only database.

The 1996 legacy pre-price buffer yields only 61 usable holdings, so it cannot supply a complete top-100 book. The wider pool also has incomplete price coverage of the universe. The engine reports insufficient matches instead of claiming 100 names in every period.

## Current-date preparation

The latest book of the book store is the current-date screen. The latest target is the newest completed cached session of the selected market. Only cached companies marked listed with a price on that exact session and a usable available report receive current valuations. The original latest candidate pool retains the 250-name pre-price buffer; the broader pool uses all eligible active names with current cached prices. `screening.latest()` exposes the same SQL filters and rank semantics without return fields.

Updating a database and rebuilding HTML are separate from fetching missing or new market data.

### Select a ranking metric

Latest screens and dated books support
current EV divided by three-year average EBITDA. The denominator is the arithmetic mean of positive annual
EBITDA for three consecutive fiscal calendar years ending
at the selected report. EV is valued at the screening date.
Missing years exclude a stock. Reports after the selected fiscal end are never
used; the selected report still obeys its market's reporting policy and
800-day age limit. The original metric remains current-date EV/EBITDA.

Rank 1 has the lowest selected multiple. Minimum yield is its reciprocal;
maximum multiple applies to the selected metric. Tables and selected-holdings
CSV exports include the selected metric values. The original pool retains its
single-year top-250 pre-screen; use the cached pool to compare signals across
the broader available price universe. Neither pool represents full coverage.

`backtest/financial/metrics.py` owns the display catalog, calculator registry and
pure metric calculations. `books.book` stores each book's ready-to-rank
multiple/yield pairs in compact `book_rows` columns by entry, pool and symbol. Thus
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
choose monthly, quarterly, half-yearly, yearly or every 2 years, or a custom
interval in weeks or months. Latest picks still work by
opening the HTML directly; custom schedules need the local service because
daily histories are kept out of the embedded page.

Each target is anchored to the original starting calendar day. Invalid month
ends clamp to that month's last day; holidays/weekends roll forward to the next
cached session of the selected market. The final inclusive mark date rolls back to a session. The
last holding period may be shorter than the requested interval. Adjacent periods
share their exit/entry session, with no duplicated return interval. Annual
financial availability, age, valuation, cache coverage and original-pool buffer
rules remain the same at each new entry. Every period reselects and equally
weights stocks. Stopped holdings use the last price and hold cash proceeds until
the next rebalance; transaction costs remain zero.

The custom chart shows returns **per holding period**, not annualized period
returns. Full-period CAGR uses actual elapsed days, including complete empty
periods held in cash at 0%. SPY keeps its period return. Choose any period to see
its stocks, valuations, return contributions and top-10 gain/loss pies. CSV exports include period dates,
actual stock entry/exit dates, selected metrics, weights and contributions.

`backtest/calendar.py` owns calendar configuration, anchored boundaries,
session rolling and seeded sampling. Read the
[calendar contract](schedule-calendar.md) for its version and old-request mapping.
The website runs Original. It accepts the five existing month counts and
version-1 calendars with 1–104 weeks or 1–24 months.
`backtest/inputs/daily.py` owns the daily cache file, its binding and its
preparation; `backtest/inputs/book_store.py` owns the saved books.
`backtest/engines/original/schedules.py` calculates missing dated books.
`backtest/portfolio_results.py` reduces ordered selected books into complete
dated results. It owns equal weights, signed contributions, compounding and
common-window cash. It reads no files. The
[financial result contract](portfolio-results.md) preserves complete holding
rows and existing application envelopes.
`data/schedules.sqlite` is ignored. Preparation repairs compatible research changes (below). Repeated preparation
validates source freshness without parsing prices. Newly requested entry/pool sheets are computed once and persisted;
filter, metric or rank changes reuse those books and shared SQL selection.
Only the requested stock pool is prepared. Switching between the original and
broader pools fills the missing pool once for each existing dated period; it
does not recompute the completed pool. Empty pools are recorded as complete too.
The book store tracks this in `book_pools`. Normal daily connections do not scan
raw prices. This affects derived data only; durable library and queue snapshots
remain independent.

Sheet repair. Research records each company's earliest changed price, volume
or report date, plus shared rate, FX and session changes. With matching book code and the
saved research base, preparation recalculates only affected company rows in
historical cached sheets. US statement changes refresh all US candidate counts
and ranks from statements alone. Affected legacy pools rebuild on demand.
Removed sessions lose their sheets. Repairs commit per sheet; latest rebuilds
and the new binding commits last. An interruption keeps the old binding, which
readers refuse; retry repeats the repair safely. Changed book code or an
unmatched research base resets the disposable cache. Research keeps its previous
committed data on preparation failure.
Unchanged identities reuse sheets. Reader and custom-formula edits bind neither
identity and require no sheet rebuild.

A damaged, foreign or older-version daily cache also starts empty. A locked
file or an I/O failure stops preparation without replacing it. Preparation
builds latest and repairs existing sheets. Unified updates then fill missing historical cached sheets in their
`sheets` stage; ordinary startup, CLI preparation and runs do not precompute.
Missing historical sheets do not block readiness or website publication. Every
run builds misses under ordinary cache ownership and never fetches market data.

`metrics.evaluate()` is the common preparation boundary for all metric formulas.
`website/serve.py` serves the built website and local JSON calculation endpoints.
The default listener is `0.0.0.0:3000`; the browser opens
`http://127.0.0.1:3000` on this computer. Use `--host` and `--port` to change the
listener. Backtest calculations use saved data only. The separate data panel can download missing data when requested.
`website/browser/schedule.js` renders dated periods without assuming one book per year.
Run `python3 tests/test_schedules.py` in addition to the existing checks.

The local service uses a larger SQLite page cache for new-book calculations.
Timings depend on disk and schedule length; new dates can require additional
book preparation.

The applied requested-pool engine was verified on native Windows Python 3.12:
100 annual random-date trials over the full cached history took 133.1 seconds,
versus 467.0 seconds for the saved eager reference (3.5× faster). The original
candidate pool, top 50 and seed 20261022 were used, ending on 2026-10-20. Loading
and per-trial saving were included; test-only cloning/reset was excluded. Every
selected holding, valuation, exit status and trial outcome matched exactly.
The [experiment summaries](../results/experiments/README.md) keep these numbers.

### Running and interrupted backtests

Every dated test runs from the [queue](#overnight-queue). Locking a phone,
refreshing or closing the page does not cancel it. Its row in Runs & saved shows
its progress, and **Stop test** in that row stops it.

The server keeps its direct run route, `/api/backtest-runs/<id>`. The page uses
it only for a latest screen of a chain that it cannot screen offline. The
browser sends an unguessable run ID with the submission and follows
`/api/backtest-runs/<id>/status` with short polling requests. Repeated
submissions with that ID reuse the same run, so a lost connection retries
without starting a new calculation. The page keeps no record of a screen: after
a reload, select **Screen latest** again.

`backtest/application/jobs.py` accepts one active run per server. It uses the
existing engine cancellation checks and the calculation owner's financial cache
ownership (`cache_access.access()`, held through the daily connection's close).
Shutdown requests a stop and joins the thread before server lifetime ownership
ends. Finished results remain in server memory for 24 hours, up to four recent
runs. They are temporary and disappear when the server exits. The server
computer must stay awake.

Dated books for a request are written inside a SQLite transaction. Closing the
server before commit rolls those writes back on recovery. Previously committed
books and input prices/financials remain unchanged. After a restart the queue
runs an interrupted test again. `tests/test_schedules.py`
checks rollback after `KeyboardInterrupt`, then forcibly kills a real SQLite
writer while a new period is uncommitted, reopens the file, runs
`PRAGMA integrity_check`, verifies prior row counts, and retries the schedule.
`tests/test_backtest_jobs.py` checks real HTTP disconnects, reconnects, explicit
stops, idempotent submission, retention and shutdown ownership on WSL and native
Windows. `tests/check-backtest-runs.cjs` checks the browser transport of a
latest screen. `tests/check-range.cjs` checks that Historical
backtest mode starts nothing outside the queue.

### Overnight queue

Use **Add to queue** in Build strategy for fixed or random-date tests. Select the custom calendar,
set parameters and add the current test. Change settings to add more tests.
**Runs & saved** shows the waiting and running tests under In progress and the saved
results under Saved backtests. The market buttons above them show the tests of one market. The line below the Add to queue button shows the result
of each addition and of a held edit.
The queue is the only way to run a dated test. Queue tests run one at a time. Browser closure
does not affect them. Keep the server computer awake and its terminal open.

Edit holds a waiting item so it cannot start with incomplete edits. Save changes
to release it. Cancel keeps the original parameters. Held edits survive page and
server restarts. Move up/down changes waiting order. Tune copies the settings to
the builder for a new test without changing the original. Pause lets the active item finish but does
not claim another item. Stop cancels the selected item and waits for normal
worker cleanup. Failed items remain visible; the consumer continues to the next.

The strategy form owns a queued edit session. While that session is active,
Tune on another test cannot replace its settings. Save or cancel the edit first. The same
form boundary handles every restoration source. A failed server hold releases
the local form session without leaving the controls reserved.

Up to 100 records, including completed results, persist in
`data/backtest-queue.sqlite`. There is no automatic eviction. Open a result to
restore its immutable artifact and downloads without running it again. The queue
is separate from the 100-record saved library. Delete confirms removal of only
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
to the lower bound and independently sample one cached market session in each
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
scenarios. Complete empty periods hold cash at 0%, keeping the full CAGR window
and SPY period returns. Their trials remain in both paired averages. Unavailable
trial results stay listed and are excluded from both averages. Percentiles are
scenario descriptions, not confidence limits.

`backtest/engines/original/book_batch.py` validates every sampled schedule upfront and
deduplicates missing entry/pool sheets across the batch. Bounded process
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
stopped first. The running queue row counts completed trials and new books.
The result exports dates, seed, frequency and trial outcomes. Trial inspection
reads the stored rows of the completed result.
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
and dated books both call `books.book` over `facts.BookFacts`;
`revalue.py` remains the independent reference of the development check.

Random streams publish their resolved configuration before executing trials.
The queue retries an interrupted test with that configuration; completed books
are reused. Fresh runs still generate a new seed by default.

### Upfront parallel-book benchmark

On native Windows Python 3.12, 100 full-history annual random-date trials took
103.4 seconds with one worker, 62.0 with two, 40.9 with four, and 33.2 with eight.
A fresh serial requested-pool control took 133.3 seconds, matching the earlier
133.1-second measurement. A four-worker run of the applied implementation,
including forced-shutdown worker cleanup, took 43.2 seconds (about 3.1× faster
than the serial control). Repeats with every book saved took about 5.6 seconds. These timings
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

The website builds a strategy as ordered Filter and Rank steps (see
[evidence views](evidence-views.md#ordered-strategy-requests)). There is no
separate order control. Filters → Rank is filter-first. Rank → filters is
rank-first. The builder copies older flat and capture/1 records into those
chains. The rest of this section describes the recorded `selection_order` field.

**Filter first, then rank** is the default. All user conditions pass first.
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
still needs the usual freshness check and offline rebuild. Short books give
survivors equal shares of the portfolio. No cash allocation fills removed
positions while any survivors remain. With zero survivors, the strategy holds
cash at 0% until rebalance.

Python screen functions and schedule options accept
`selection_order='filter_first'` or `selection_order='rank_first'`.
Omitted values retain the original
filter-first behavior. Invalid values fail validation. Browser results, exports,
queued settings, explicit-seed repeats and saved artifacts retain
the submitted order. Older saved records omit the field and restore filter-first
without being rewritten or recalculated. Original ranks remain in CSV exports.
An older queued test keeps its random plan when a name-only edit exposes the
implicit filter-first default. Changing the order discards a waiting test's plan.
Check `python3 tests/test_selection_order.py`, research, schedule, robustness,
queue and saved-artifact tests, then browser/SQL parity and control checks.

### Multiple threshold conditions

On the website, each condition is a Filter step: one source, comparison and
value. Flat requests and capture/1 conditions are strict: `lt` means less than;
`gt` means more than. Chain Filters also accept inclusive `le` and `ge`, and
equality for sector and exchange. Two conditions can bound the
same metric. Missing values fail only conditions that require those values.

The default catalog includes both EV/EBITDA multiples, EBITDA/EV yield,
market cap, enterprise value, and trailing 1-year and 3-year returns. Additional
financial filters include P/E, P/S, P/B, free cash flow amount/yield, price/FCF,
dividend yield, net profit margin, historical PEG, ROE, current ratio, interest
coverage and debt/equity. These use saved annual statement inputs. The 1-week
turnover rate also uses saved daily volumes. Choose **Manage backtest data →
Update data** to get their inputs and prepare them automatically. Changing filters makes no
provider requests. Missing inputs exclude only stocks filtered on those inputs.

`backtest/financial/metrics.py` defines the catalog and prepares threshold values.
Each entry sheet stores them in compact `f_<field>` columns beside its ranking pairs.
Returns use dividend-adjusted closes on or before the screening date and its
calendar anniversary, with a seven-calendar-day tolerance at each endpoint.
A leap-day anniversary clamps to 28 February. Return values use percent units;
market cap and EV use millions of dollars. Return filters never use the later
holding-period return. The same calculations serve dated books.

The valuation averages are **P/E, P/S and P/B 3-year and 5-year averages** and
each current multiple **vs its average** (current ÷ average; below 1 is
cheaper than usual). On each priced day, the daily yield is net income,
revenue or equity of the report a book selects that day, divided by that day's
rescaled market cap; a loss counts with its sign. The average multiple is
1 ÷ the mean daily yield over the priced days after the calendar anniversary
(leap day clamps to 28 February), through the screening date. It needs a
yield on or before the anniversary and a positive mean. A legacy-pool row uses
the same history with its own current multiples.

**Dividend yield** is the selected report's `commonDividendsPaid`, sign
reversed because the provider reports a payment as negative, divided by
screen-date market cap, in percent. No dividend gives 0; a missing value omits
the field. A special dividend counts in its fiscal year. **Turnover rate —
1-week average** is the mean saved session volume in the 7 calendar days that
end on the screening date, divided by the selected report's annual
weighted-average basic shares (`weightedAverageShsOut`), in percent. Days
without a saved volume are left out; zero-volume days count. Foreign stocks
use their local sessions. The provider restates both volumes and report shares
to the latest split, so a split after a report was saved skews that company's
turnover until its reports download again.

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

Add **Sales × 3-year avg operating margin / EV − US 10Y (pp)** as a Filter
step. The formula is:

```
annual operating margin = operating income / revenue
spread (pp) = selected annual revenue × mean(last 3 annual margins) / screen-date EV × 100 − Treasury yield (%)
```

Use three consecutive fiscal calendar years ending at the selected report.
Each year's margin has equal weight. This is not a revenue-weighted margin.
Use the selected report's revenue for sales and its `operatingIncome` field for
operating income. Do not substitute EBIT. The market's reporting policy,
strict availability-before-screen rule and 800-day report-age limit still apply.
Later reports cannot fill a missing year or field. Revenue and EV must be
positive. Operating income and the resulting spread can be negative.

Subtract the latest cached 10-year Treasury yield on or before the screening
date. There is no added yield-age limit. Latest uses its exact saved SPY
session. Dated books use their entry session, even if a stock's first buy price
is a later session. The filter uses
percentage points: enter `5` for a spread above or below 5 pp.

Books read the valid 10-year values that research keeps in `market_days` from
the saved `year10` fields of `raw/treasury.json` (`facts.ten_year`). The legacy
annual values (`facts.legacy_annual`, from `annual_facts`) include unambiguous
context-normalized USD `operatingIncome` values from full annual income statements. Both pools and all three website modes (latest, custom and random) share
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

Open **Manage backtest data** from the strategy builder. Select **Update data**
to check for missing and newer inputs, download them and prepare both databases
and the website. A saved annual record does not mean that the company has no
new report. Preparation is automatic. Saved backtests and queue records keep
all their recorded values.

The primary action maintains the selected market's saved-price companies, pending additions, newly
listed companies and companies that first acquire eligible financials. A saved
price receipt also identifies a managed company whose file was lost. The
missing file inherits no completion evidence and is downloaded again. Annual
key metrics are checked for the due US set below. US statements and ratios
update for managed stocks within that set. Foreign downloads use income,
balance-sheet and cash-flow statements only. Existing receipts record completion, including empty
responses; missing values remain unavailable to calculations. New managed
histories start in 1995. Historical companies remain in the universe. Existing
US fiscal-date valuations retain their values; new fiscal dates use the market's
reporting policy. Full annual
responses retain every field, currency, null and variant under the existing
conflict rules. Requests retain the 40-report limit.

Every managed refresh checks company lists, prices, SPY, Treasury and FX. This
includes the 07:00 Hong Kong update and managed data-panel updates. Reports
run when the Hong Kong date is Saturday and that day has not been checked,
or when the last successful report check is more than seven days old. A missing check is due immediately. These
checks cover listed companies and pending additions. A due check includes delisted
companies when the full sweep is missing or more than 90 days old. US key
metrics use this set. US statements and ratios cover managed stocks within it.
Foreign statements use the full due set. Custom-scoped updates and the separate
Download action keep their existing full report behavior.

**More options** selects a stock group, up to 200 specific symbols and a history
range. **Update selected stocks and history** updates that explicit coverage and
prepares it automatically. The primary Update data action uses full managed
coverage independently of those controls. An earlier start extends saved
history. Include earlier prices for report-date valuation and trailing returns.
A selected group is not a promise that every company has available prices.

**Details** contains technical messages, local file inspection, report export
and **Prepare saved data (offline)**. Checks inspect actual dates, missing
financial symbols, empty histories and prepared-data freshness. Checks and
preparation make no provider request. Opening the page only reads status; it
never starts a download. Offline preparation needs no API key. Downloads read
`~/.grok/secrets/fmp_api_key` only when a request needs it. Keys, provider URLs
and response bodies never enter the browser or progress state.

#### Progress and continuation

The main card shows estimated overall completion, elapsed running time and
estimated time remaining. The supporting steps are checking, company reports,
prices, preparation and final readiness. Preparation includes the `sheets` stage
after website output and before final verification. Per-symbol messages stay in Details.
The estimated percentage includes preparation. It stays below 100 until the
whole update succeeds. Partial completion and readiness are separate outcomes.

Estimates use the stage durations of the last successful update with the same
scope, excluding the end date. Current stage counts scale its remaining time
and completion fraction.
If the current stage is slower, elapsed time and its completed fraction revise
the estimate. Future stages use that previous update's durations. Without a
matching success, overall estimates stay unknown; elapsed time and current step
counts and percentages remain visible. These are approximate estimates.
Skipped reports show **Reports: next check Saturday** and add no estimated
time. Skipped runs retain the previous measured report durations for the next
due run.

Closing or reloading a browser page does not cancel work. Other tabs show the
same operation. The page polls while idle and reconnects automatically. A lost
connection shows **Cannot read update status** and freezes progress as **Last seen**.
It does not declare the update stopped. A lost start response causes a status
read, never an automatic repeat submission. **Stop update** stops new work and
joins active workers before cache
ownership ends. The card shows **Stopping safely** during cleanup.

After a server crash or machine shutdown, **Continue update** uses the saved
scope and target date. It reruns unfinished stages. A due, unfinished report stage
is checked again even when its files have valid receipts: those receipts do not
prove that the provider has no newer report. Finished download stages can be
reused while their content-bound receipts still apply. If only preparation is
unfinished, downloads are reused unless managed reports have become due.
Recorded active seconds survive continuation; stopped time is excluded.
Managed continuation recalculates whether reports are due on its current Hong
Kong date. If a full sweep becomes due, completed report stages are checked
again for delisted companies.

`website/server/data_refresh.py` persists one small atomic record at
`data/data-refresh.json`. It contains state, scope, target date, current stage,
stage counts, a successful stage prefix, verified running seconds, pending
additions, last success and the last successful scope's stage durations. It
also keeps `last_report_check` and `last_full_sweep`. Managed refreshes use
these dates. Only an all-markets managed run advances them, after its download
phase finishes with no report failures. A Stop or exception during downloads
keeps the old dates. A recorded price failure does not prevent this advance.
Single-market and custom-scoped updates preserve both dates. The refresh uses the existing financial cache ownership. Only that
owner publishes status and inputs. There is no separate update lock or per-asset work store.

A saved running status becomes interrupted when the cache is free and no local
update is running. If a foreign operation holds the cache, status is
**unconfirmed**: a backtest can own that cache too. The page does not claim that
an update is still running and does not offer Stop for that unidentified owner.
Status reads never publish or resume work.

The service exposes GET `/api/data/status` and POST `update`, `continue` and
`cancel`. Empty update options select managed coverage; normalized stock/date
options select explicit coverage. Continue takes an empty object and restores the saved options. Local support actions `check`, `rebuild`, `download` and
`refresh` remain available for existing callers; missing-only support downloads
are not the ordinary interface. Data actions use the same-origin policy of the
backtest website. Remote clients can use the same server address, including a
Windows Tailscale address. Cross-origin browser requests are refused.

#### Publication, preparation and provider limits

`website/server/data_refresh.py` owns the managed update policy. Prices and
Treasury yields resume known unfinished windows and recheck seven recent days.
Empty histories reuse checked old windows and recheck recent dates. This does
not infer missing sessions inside an imported saved span. A changed adjusted
price requires a consistent complete replacement in bounded windows. Saved and
new dates must remain present and recently returned prices must still agree.
An incomplete replacement keeps the old file. Unchanged assets keep their
bytes and timestamps. Recent overlap checks do not audit every old correction.

Stock and SPY windows cover up to ten years. Treasury windows are monthly. A
30-year price or Treasury request returns only the latest rows, so requests use
these short windows. Bulk statement files are refused when many run at once.
Per-symbol `key-metrics` calls work at about 16 at a time. Up
to 32 tasks are in flight, with a shared cap of 45 starts per second. Connections
are reused and support gzip. HTTP status and Retry-After take precedence over
response encoding. A 429 pauses workers and lowers the start rate. There are
at most three attempts, a 15-second socket timeout and a 30-second read deadline.
Cancellation interrupts retry waits and stops submission. Only the owner saves
responses. Finite non-positive prices are excluded and their dates stay in the
content-bound receipt. Other invalid rows fail that asset. Empty checked
responses do not invent prices or advance the latest SPY date.

`raw/download-coverage.json` retains its existing hash-bound receipts, windows,
base spans, prior generation and skipped dates. Publish receipts before assets.
An incomplete replacement can match only the exact saved generation. A missing,
damaged or replaced asset inherits no previous completion evidence. Known holes
remain missing even when other completed windows extend both sides of them.

Financial appends end with a newline, flush their contents and synchronize the
file. Before appending or preparing, the owner trims only an incomplete,
unparseable final line. A complete valid JSON tail without a newline is kept.
Earlier bytes are never rewritten by this tail cleanup. Read-only inspectors
keep the ordinary non-mutating reader. Main's existing complete-record repair
and archive behavior remains available for malformed records.

Atomic cache replacement flushes file contents before rename and synchronizes
the directory on POSIX. Python exposes no portable equivalent directory
synchronization on Windows. These durability steps are retained for WSL
shutdown. Tests use private fixtures; no physical power-cut claim is made.

Preparation runs under the same owner after downloads. It reuses current data
or reconciles research facts, then prepares daily sheets and the website.
Research failure keeps the prior committed data. Daily repairs commit per sheet
and publish the new binding last. Website
rebuilds remove the old completion marker and synchronize its directory before
changing output. All outputs are flushed before the new marker is published
last. Freshness requires that marker, its input identity and the output files. The
server builds in process so a killed owner cannot leave a build child publishing
after its cache lease ends.

After website publication, `data_refresh.run` calls `book_batch.precompute`
inside the same cache ownership. This is the only production caller. Its
`sheets` stage fills every historical cached entry from `rules.FIRST_DAY`
through each market's latest saved session. Latest-policy headers do not count. Empty
pools count through their `book_pools` completion rows. Legacy stays on demand.
The website embeds latest only; adding historical sheets does not change its
binding or build freshness. Plain startup, CLI preparation and support rebuilds
do not precompute.

Precomputation reuses the existing up-to-eight read-only workers, bounded
prefetch, lifetime watch and cancellation. Only the parent writes. Each sheet
commits its rows and completion together; interruption keeps earlier commits.
Continue admits the current binding and builds missing completions only. The
existing progress record reports retained/total sheets first, then advances
after each commit. Stage durations cover this work. Older timing evidence
without the sheets duration gives no overall estimate until a new success. No
new table or checkpoint format is needed. No VACUUM is run: changed bindings
already replace the disposable store. The scheduler owns no sheet rules.

A company failure does not stop unrelated assets. Publication I/O failures stop
further downloads. Valid saved inputs can still be prepared after a provider
failure, but the outcome stays visibly partial. Preparation failure cannot
report Ready or start the calculation service. Library and queue records are
never rewritten. The last successful update and actual latest SPY session stay
separate.

Source ownership precedes the existing process-local financial lock, project
financial file lock, connections and worker pools. A thread lock alone is not
ownership. Keep ownership through worker completion and connection closure. Nested preparation reuses it.
The 07:00 Hong Kong maintenance cycle uses the same update operation. A missed
schedule waits until the next day. The supervisor must be running. Its already
authorized cycle can update independently of the manual Continue action.
Ordinary startup remains offline and can prepare valid saved inputs locally.

The recovery page is served directly from source at `/data.html`, even when
essential inputs or prepared output are missing. A saved HTML copy requires the
local service. Verify with `tests/test_data_refresh.py`,
`tests/test_data_manager.py`, `tests/test_startup.py`, `tests/test_cache_access.py`
and `node tests/check-data-panel.cjs`, including affected native Windows checks.


### Download performance experiment

Temporary responses and disposable caches stay ignored. The durable record is
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

### Development check

The development check, `python3 scripts/check.py [--through YYYY-MM-DD] [--json
OUT]`, runs one Original custom run: every 12 months from 1 January 1996 to the
through date (default: the frozen report's Through date, 2026-10-20), legacy
pool, `ev_ebitda` ranks 1–50 and the default floors. It compares every book,
holding, date, valuation, return and exit status with `revalue.calculate(through)`
at full precision (relative and absolute tolerance `1e-12`) and names each
difference. Only differences between calculations on these identical inputs
fail the check. It also reports annual differences from the frozen report at
four decimals, in the console and the JSON `report` list. These historical
differences are informational; updated cached inputs can change them. The frozen
record is never rewritten. The reference
engine keeps the January study's label rule: a book that ends in its entry year
is marked to date. In this 12-month run only the last book is a mark, so the
labels agree. Run it on the real-data bench after a change to book policy
(`books.py`, `rules.py`, the dated book writer or its price lookups). The study
constants (`FIRST_YEAR`, `LAST_YEAR`, `ASOF`, `HOLD`) live in
`backtest/engines/reference/legacy.py`.

### Full annual financial data

Updates save complete annual income statements, balance sheets,
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

The legacy annual values (`financial_inputs.ENDPOINTS`, read through
`facts.legacy_annual`) are the eligible numerical inputs. The raw cache retains
the other fields for future metric preparation. Selected annual
inputs must match the report selected by the original eligibility rules. No newer
report fills an older report's missing fields. P/E, P/S and P/B use screen-date market
cap. ROE uses average positive equity from the selected and prior fiscal years.
PEG divides P/E by three-year diluted EPS CAGR in percentage points; it requires
four consecutive positive annual EPS values and positive growth. Ratios require
positive denominators. Negative FCF, FCF yield and profit margins remain valid.

Run `python3 tests/test_financial_inputs.py`, research and schedule checks, then
build and run browser parity checks. These checks use offline fixtures.

Annual responses can contain repeated fiscal dates. Keep every returned row, including identical rows. A repair also retains distinct saved variants. Preparation uses a numerical input only when all nonmissing USD values for that endpoint and fiscal date agree. Conflicting inputs stay absent. Nulls do not replace known values. Response order does not select a revision.

### Typed prepared facts

Research preparation writes the inputs of custom-variable formulas as typed
tables in `research.sqlite`, owned by `backtest/inputs/facts.py`. The
research schema version ([Prepare once](#prepare-once)) covers them; older
caches rebuild. The daily cache does not copy them: formulas and books read
them through the `research` schema that the operation's one daily connection
attaches. Preparation reads and parses each saved price, SPY and Treasury
file once. A saved file that cannot be read stops preparation, as an invalid
`metrics.jsonl` record does; the data panel downloads it again.

One rule gives each saved day its value, for formulas and books alike. Equal
admissible values agree. A conflicting, non-USD or invalid value gives no
value and a reason. Prices are the dividend-adjusted closes (`div`); valuation
and returns read the same series. `facts.BookFacts` is the facts port of books:
reports by pool, cached companies (from `fact_sources`), listing (from
`companies`), the valid adjusted closes and volumes, SPY sessions and yields.

- `stock_days(symbol, day, adjusted, adjusted_reason, volume, volume_reason)`:
  one row per company and saved price day.
- `market_days(day, spy, month3, month3_reason, year10, year10_reason)`: `spy`
  is set on a valid SPY session; a saved Treasury day has a value or a reason
  for both fields (both yields in percent).
- `companies(symbol, name, exchange, sector, listed)`: each saved company and
  whether it is listed now.
- `facts.legacy_annual` derives the legacy annual values
  (`financial_inputs.ENDPOINTS`, valid values only) from `annual_facts`, and
  `facts.ten_year` reads the valid 10-year values. `books.owner_values`, the
  owner values of a book row and of the dated owner policy, reads them through
  these two functions, with the valuation sums (`facts.valuation`), the
  selected report's dividends and shares (`facts.dividends`, `facts.shares`)
  and the saved session volumes (`facts.volumes`).
- `annual_facts(symbol, endpoint, fiscal, <field>, <field>_reason, ...)`: one row
  per company, statement endpoint and fiscal date, with one value and one
  reason column for each annual catalog field (parameter id without `annual.`).
- `fact_sources(symbol, endpoint, sha256, disposition)`: the digest of each
  annual, price, Treasury (`''`) and SPY (`''`) source file.

The research record (`metadata`, above) names their version and content
identity.

A field is valid when its value is present; otherwise its reason column names
the reason (`MISSING_INPUT`, `CONFLICTING_INPUT`, `NON_USD_INPUT`,
`INVALID_INPUT` or `INCONSISTENT_SERIES`). A stock price series with an
isolated spike, a close at least 8 times or at most 1/8 of both neighbouring
valid closes, mixes two provider price scales: `facts.stock` gives every valid
close of that series `INCONSISTENT_SERIES`, so the company has no price, and
preparation prints the symbols it left out. Value columns have no declared
type, so SQLite keeps the binary64 bits exactly, including -0.0, which a REAL
column stores as the integer 0. Days are keyed by date, never by raw-file row. A prepared scope is
one complete pool of a stored book, named by its book id; a latest scope names
the open book, and `book_store.require_scope` is its one check. A book id is a
handle, not a durable name: it names one book only while the cache keeps it,
and SQLite can reuse a deleted id. A recorded `owner_scope.book` is a label,
never a lookup key outside the operation or coverage generation that made it.
The owner lanes of a stored-book root are that book's stored lanes
(`book_store.market_caps` and `lanes`, one read per book pool), read in place; a
missing row never falls back to a recalculation. Every root of a latest or
dated scope names its book in a prepared owner scope; a latest preview root
reads the open book. A scope root's admission is its stored row, with the
stored candidate rank and entry valuation. An explicit preview root is
admitted by `books.Screen.decide`: a latest root by the latest book's screen
(listed companies, the exact session), a historical root by its date's
screen. A historical decision that reaches the entry valuation keeps the
lookups that the view's recording facts port saw. A request names no book: a
preview root is exactly its company, pool, mode and date. A coverage request
names only a scope that discovery listed in the same generation (the open
book's pools).

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
US 90-day availability rule and 800-day current-anchor limit remain in force.
Foreign contexts use the market reporting policy described above.
Earlier history members keep the calendar-year buckets and can be older than
800 days.

Price and volume use the saved market session on or before the context, within seven
calendar days. Each needs the stock's own field on that exact session. Price is
finite and positive. Volume is finite and nonnegative; zero and fractional saved
volume remain valid independently of price. Price uses USD/share in an admitted
USD company context when route currency is absent. Explicit foreign currency
makes that price unavailable under the US policy. Catalogs /1–/3 retain their US
identity conversion. Catalog /4 converts foreign prices to USD with the previous
completed FX fixing. Treasury uses the latest saved source date on or before a
US context, and strictly before an Asian context. It resolves month3 and year10 at that
one date and divides provider percent by 100. Signed and zero rates are valid.
Null, invalid or conflicting latest fields do not borrow older field values.
Dated inputs require no earlier annual anchor after root admission. Legacy
financial valid-series and as-of behavior keep their existing meanings.

The facts' content identity hashes what determines the rows: the fact-row code
identity and the bytes of every saved file that preparation read (the
`fact_sources` digests and the universe and annual-metrics digests), not the
rows themselves and not file stamps. A rewrite with equal bytes reconciles
research to the same identity, so the daily cache and its books stay. The
raw-file signature leaves out `raw/download-coverage.json`, which no
preparation reads. Operation entry checks the daily binding once (identities
above): the accepted raw-file signature, the fact-row code and the recorded
identities, not the prepared rows.
Inspecting about 36,000 raw files takes about 1.7 seconds on the real cache, so
readers reuse the signature taken by preparation or after the last data-panel
action. A hand edit to `raw/` needs a data-panel check before readers see it.
Between steps, Original checks one research-file status at each view boundary.
The exclusive cache lock keeps the prepared rows unchanged for the whole
operation. The borrowed view reads each company, day and source once.

The evaluator supports all 57 direct inputs plus operating margin, existing
dated EV and the reusable measure adapters. The 33 named measures use immutable
ordinary definitions and exact references. A stored-book root consumes its
book's stored owner lanes. An explicit historical preview root and every
derived context use dated owner policy (`books.owner_values` at the context
date), even at the root date. Values-only evaluation builds no evidence;
detail mode explains the selected rows only. Report EBITDA uses broad accepted report history.
Reported EBIT, FCF, debt and EPS use the income fiscal spine and exact endpoint
dates. Only those named annual adapters support annual history. A new research
schema or daily cache version ([Prepare once](#prepare-once)) makes
incompatible caches rebuild; durable records keep their formats. Version-3
authoring exposes all 57 direct
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
