# EBITDA/EV January book

This folder is a standalone US stock backtest. It is not a a different research session. Do not open the parent harness, do not invent a fair value, and do not edit product code from here.

The folder can move. Scripts resolve paths from their own file. Keep `raw/` with the code. The FMP key stays at `~/.grok/secrets/fmp_api_key`. Never print the key or a request URL.

## Git in this environment

The normal `.git/` folder is empty and read-only in this workspace.
The repository history is in `.git-local/`. Run Git from the project folder:

```
git --git-dir=.git-local --work-tree=. status
git --git-dir=.git-local --work-tree=. log --oneline
```

Use the same options for diff, add and commit. If the default Git wrapper fails
with a WSL socket error, use `/usr/bin/git` with these options.
Do not initialize a new repository or replace the saved history.
Ordinary Git commands and apps may not detect this repository automatically.

## Current result

`results/summary-exits.txt` is the result to continue from. It is the pass that keeps a stock when trading stops.

`results/legacy/summary.txt` and `results/legacy/picks.csv` are the earlier pass. That pass dropped a stock when its price stopped more than 10 days before the January sale. Do not quote those files as the latest result.

`scripts/revalue.py` writes `results/summary-exits.txt`. It reads the cache and does not download. `scripts/run.py` still uses the old exit rule and rewrites `results/legacy/summary.txt`.

## What the test does

Each January, from 1996 through 2026, buy the 50 US common stocks with the highest EBITDA/EV. Sell at the next January. The 2026 book is marked through the last SPY session on or before 2026-10-21. Compare with SPY, dividends included. Equal weight. No commissions.

The 3-month Treasury yield is one number for every stock that day. Subtracting it does not change the rank.

## Rules already chosen

- Exchanges: NYSE, Nasdaq, NYSE American. ETFs and funds are out. Delisted US names are in the universe.
- The annual figure is treated as known 90 days after fiscal year-end. A report older than 800 days is dropped.
- Enterprise value at the buy date uses the report's debt and cash, and the buy-date price. That price series is dividend-adjusted.
- Market cap at least $100 million. Enterprise value at least $50 million. Currency USD.
- A stock with no buy price is left out.
- If trading stops before the January sale, the exit is the last price. That covers an acquisition, a called note, and a SPAC that returns cash.
- A bankruptcy is a total loss. `BANKRUPT` in `scripts/revalue.py` is the set of `(year, symbol)` pairs that get −100%. It is empty. The 37 stops were checked. They were acquisitions, redemptions, SPAC cash, or warrants. None was marked a bankruptcy.
- A stock that still has a January price keeps that price. A later delisting does not rewrite the year.

## Cache

Do not refetch data that is already here.

- `raw/universe.json` — about 11,054 US names, including 5,068 delisted names. Delisted rows have no sector and no delisted date.
- `raw/metrics.jsonl` — annual key metrics. One JSON object per line: symbol, date, fiscal year, currency, market cap, enterprise value, EV/EBITDA.
- `raw/px/` — dividend-adjusted price history for the screened names, about 1,999 files.
- `raw/spy-div.json` — SPY total-return prices from 1995.
- `raw/treasury.json` — daily Treasury yields from 1995. The 3-month yield is `month3`, in percent.

`raw/archive/*.csv` and `raw/archive/delisted-*.json` are leftover bulk downloads. `scripts/run.py` does not read them.

## FMP limits

A 30-year price or Treasury request returns only the latest rows. Request short date windows. One stock price history is capped at about 5,000 sessions, so `scripts/run.py` asks for three windows.

Bulk statement files (`key-metrics-bulk`, `income-statement-bulk`) are refused when many run at once. Per-symbol `key-metrics` calls work at about 16 at a time. The pace gate inside `scripts/run.py` made those calls stall. `fetch_metrics` turns that gate off.

## How to continue

Recompute exits from the cache:

```
python scripts/revalue.py
```

Add a bankruptcy as a total loss by putting `(year, "SYMBOL")` in `BANKRUPT` in `scripts/revalue.py`, then run that file again.

Change the screen, the universe, or the price cache in `scripts/run.py`. Run it only when the cache is missing data. Merge any new exit rule into `scripts/revalue.py` before treating `results/legacy/summary.txt` as current.

`scripts/classify_stops.py` and `results/stops/stops-class.json` record SEC form types for the 37 stops. The merger flag in that file is broad. `scripts/revalue.py` does not read it. It uses the last price for every stop. Use the form list as a clue, and check a name before calling it a bankruptcy.

## Project layout

Backtest entry points live in `scripts/`, with shared paths in `scripts/paths.py`. API experiments and repair tools are in `tools/`. Current reports are in `results/`, older reports in `results/legacy/`, and stop analyses in `results/stops/`. Unused acquisition files are preserved in `raw/archive/`; active cache locations are unchanged.

The website source and ready-to-open output live in `website/` and `website/dist/`. Rebuild with `python3 website/build.py`. Verify path handling with `python3 tests/check_paths.py` and website calculations with `node tests/check-range.cjs`. Python uses the standard library; the JavaScript check needs Node.js. Cache-only workflows require no API key.

## Keep the user architecture guide current

Before every commit, compare the full commit diff with
`docs/architecture-guide/dist/index.html`. This is the human-facing guide to how
the program works. Update affected explanations, diagrams, setting examples,
cache rules and file maps in the same commit as the change they describe.
Check changes to preparation, selection, metrics, exits, schedules, random trials,
startup, website controls, cache schemas and file locations. If the commit does
not affect the guide, leave its content and checked date unchanged and state
that no guide update was needed in the completion report.

Use ASD-STE100 principles: short sentences, one main idea per sentence, consistent
names and definitions for technical terms. Explain the user-visible behavior
before the implementation details. Distinguish current source, a running server,
and benchmark-only prototypes. Keep measured timings tied to their original
settings and reference engine; do not present old measurements as new tests.
Change the guide's checked date only after checking its claims against the code.

When the guide changes, run `node docs/architecture-guide/check.cjs`. Update that
check when guide controls change. Keep the guide self-contained and usable by
opening its HTML file directly. Review affected diagrams and responsive layouts
when browser tools are available; report any unverified browser checks.
Preserve the guide's existing Site identity if hosted publishing is retried.
Publication failures must not prevent the local guide update from being included
in the implementation commit. Do not create an empty documentation change just
to satisfy this rule.

## Fast research workflow

`scripts/research.py prepare` creates the offline `data/research.sqlite` January data layer from the raw cache. It verifies the baseline against `results/summary-exits.txt`; repeated preparation skips parsing when inputs are current. Use `scripts/research.py screen --top 100` or other flags for experiments, rather than editing `HOLD` and reparsing daily history. The website uses the prepared database. `scripts/revalue.py` remains the independent slower reference calculation.

The `legacy` research pool preserves the original 250-candidate pre-price screen and uses the **current** exit rule. The `cached` pool broadens the screen to available cached-price companies, not the full universe. Report missing coverage and unreviewed new early stops; do not imply all expanded holdings received the earlier bankruptcy review. See `docs/research-workflow.md`. Test with `python3 tests/test_research.py`.

## Website strategy builder

`website/dataset.py` exports both prepared January pools as compact records embedded in the HTML. `website/screener.js` implements browser filtering/ranking; `website/range.js` connects controls and renders results. Each runtime shares filtering and ranking between historical and latest modes; only historical mode validates years. Browser parameters must match the SQL selection semantics in `scripts/research.py`. Check parity with `python3 tests/check_screener.py` after building; it requires a current prepared database. Keep the original static top-50 fallback and baseline CSV/JSON exports. Browser downloads reflect the current strategy. Show short/empty-year coverage explicitly; do not calculate a full-period strategy CAGR when any selected year is empty.

Yearly attribution uses `website/contributions.js` for browser calculations and `website/attribution.py` for the static fallback. Top contributors means the first `min(10, actual selected count)` stocks, ordered by signed contribution (return / actual selected count), with ties by symbol. Gain/loss pies are normalized separately; never draw negative slices or describe them as shares of net return. Check with `node tests/check-contributions.cjs`, `python3 tests/test_attribution.py`, and the existing range/control tests.

## Latest-date website screening

Schema version 2 prepares `latest_snapshots` separately from historical snapshots. Latest date means the latest cached SPY session. Require an exact-session dividend-adjusted price and cached `listed=True`; never reuse old stopped prices in the latest screen. Use the same 90-day lag, strict availability-before-date rule and 800-day report-age limit. No future return or contribution is stored for latest picks. `research.latest_screen()` and `StockScreener.latestScreen()` must agree. The website opens in latest mode; historical mode retains year controls.

Historical preparation is bounded by the canonical report's Through date and historical ASOF, while latest preparation can advance independently. The reference report participates in freshness checks. Refresh prepared data and rebuild the HTML after cache updates; strategy calculations do not fetch market data. The separate data panel downloads missing inputs only after an explicit button action. Tests include exact-date exclusion, unavailable/stale reports, cached listing status, unchanged historical periods when latest prices advance, both SQL/browser screen modes and latest CSV output.

## Ranking metric catalog

Schema version 4 stores uniform `screening_metrics` pairs (multiple and yield)
for each mode, pool, year and symbol; `scripts/metrics.py` owns the display
catalog, calculator registry and all metric calculations. Both website modes and SQL selection accept a metric
ID, with the catalog embedded by `website/dataset.py`. Keep filtering/ranking
and rendering generic: consumers read prepared pairs without interpreting formulas
or calculator types. Three-year metric means current EV divided by mean EBITDA from three
consecutive annual reports, excluding incomplete histories; current
EV/EBITDA remains the default. Original-pool membership still comes from the
single-year buffer. Add temporal/missing-year and SQL/browser parity checks for
new metrics. Calculation/catalog changes require offline prepare and rebuild.

## Custom dated schedules

`scripts/schedules.py prepare` builds a separate ignored daily SQLite cache from
saved prices after research preparation. `website/serve.py` serves the built page
and a loopback custom-schedule API. January and latest views remain standalone;
custom dates use `website/schedule.js` and the local service. Dates are anchored
to the original starting day, clamp month ends, and roll forward to SPY sessions;
end marks roll back. Supported intervals are 1, 3, 6, 12 and 24 months. Persist dated
books independently of filters and reuse `research._select` and
`metrics.evaluate` rather than duplicating filtering or metric formulas. Custom
charts show dated period returns; don't label monthly/quarterly books as annual
returns. Keep canonical January reports untouched. Verify with
`python3 tests/test_schedules.py` and existing research/website checks.

Daily cache version 3 prepares only the requested pool. `period_pools` records
completion independently of snapshot counts, including empty pools. A pool switch
fills the missing pool in the same dated period; filters, ranks and metrics reuse
its prepared rows. Keep completion markers and rows in the same transaction.
Startup upgrades compatible version-1/2 caches in place, retaining daily prices
and completed pools. Version-1 books mark both pools complete; version-2 books
retain their individual markers. Changed research inputs still require preparation.

## Automatic local launcher

`backtest-web.cmd` and `start.cmd` (Windows) use `website/launcher.py` to manage a terminal-owned server. Terminal logs stay visible; Ctrl+C stops the server. Safe development diagnostics also persist in `data/logs/website-<pid>.log`, with a 5 MiB active log and two rotated backups per process. `scripts/diagnostics.py` owns this logging. Keep exception types, OS codes and stack locations; omit exception text, source lines, locals, keys, provider URLs and response bodies. Startup and the data panel show the current log path. Test with `python3 tests/test_diagnostics.py`, including native Windows. The default listener is `0.0.0.0:3000`; the local browser uses `http://127.0.0.1:3000`. A per-port startup lock serializes preparation and binding. A separate lifetime lock stays held until the listener and all request threads close. An unreachable HTTP endpoint never proves that the old server has finished. Replacement waits up to 30 seconds for ownership, then reports a retry instruction. `website/launcher.py` owns identity publication, control requests, cleanup and both locks. An authenticated loopback identity endpoint identifies this project. Each managed launch stops the identified previous server and starts current code in the invoking terminal. This transfers ownership even from an unchanged background instance. Do not stop unknown port owners. Identity and startup lock files live under ignored `data/website-*` paths. Direct `python3 website/serve.py` remains a foreground option. The daily
preparer first ensures the research cache, then the server checks the website
build stamp and rebuilds if needed. Open the browser only after successful
preparation and binding; `--no-browser` supports headless use. Keep dependency
repair automatic rather than making users chain preparation commands. Source
fingerprints use POSIX relative keys and exclude platform-specific directory
sizes. `website/build_state.py` tracks normalized source contents and the prepared
database generation. Test with `python3 tests/test_startup.py`.

## Random-date sensitivity

`scripts/robustness.py` samples one SPY trading session independently in every
nominal frequency block for each seeded trial. Trial count is configurable
(1–100, default 24). `schedules.backtest_dates` shares the dated-book evaluator
with fixed schedules. All trial CAGRs use a common window with zero-return cash
before the first trade for both strategy and paired SPY. Keep incomplete trials
visible and exclude them from both paired distributions. Average trial CAGR is
not one portfolio return; percentiles are not confidence intervals. Stream real
completed-trial counts through `/api/robustness`; commit per trial so retrying a
seed reuses books after interruption. Inspect trials using the ordinary schedule
API with explicit dates. Check `python3 tests/test_robustness.py` and
`node tests/check-robustness.cjs` alongside existing checks.

`scripts/book_batch.py` plans unique missing date-pair/pool books across the
whole random batch. Bounded process workers read the daily SQLite cache through
read-only connections and use `schedules.compute_period`; only the parent calls
`store_period`. Group price lookups into one read transaction per book and release
it before returning the book. Per-query autocommit locks are expensive on Windows;
long-lived readers block the writer. Calculate outside write transactions, stage a whole trial, then
commit its books together. Preserve first-use order, deterministic results and
completed-trial recovery. Share financial policy and SQL screening with ordinary
schedules. Cached-only batches start no workers. Report book preparation and
worker counts separately from real completed trials. Verify with
`python3 tests/test_book_batch.py`, including native Windows spawn coverage.
Use up to four workers automatically for at least 64 missing books, bounded by
CPU count. Small batches stay serial. Child workers monitor parent lifetime so a
forced launcher shutdown releases their read locks and memory.

Random date batches draw fresh dates by default; an omitted seed is generated
server-side and recorded for replay. An explicit seed remains deterministic,
exposed through an advanced repeat option rather than the main strategy controls.
If the default port is occupied, open a new loopback instance on an available
port rather than reusing a possibly outdated API process.


## Multiple threshold filters and data control panel

Schema version 5 adds `filter_values` separately from ranking pairs. Conditions
use `field`, strict `lt` or `gt`, and a finite `value`. All conditions must pass
before ranking. Missing values fail only conditions that need them. Use display
units: millions of USD, percent, or multiples. `metrics.filter_values()` owns
threshold calculations for January, latest and dated books. Trailing returns
use only adjusted prices on or before the screen date and its anniversary,
within seven calendar days. Clamp leap-day anniversaries to 28 February. P/E and
P/B remain unavailable; the current downloader does not add their input fields.

Manage backtest data opens `/data.html`. Checks and rebuilds use saved files.
Downloads require an explicit user action. Fill missing financial symbols and
unrequested price ranges; preserve valid records. Keep the key and provider
request URLs out of status responses. Serve the panel from source so startup can
open it when required raw files are missing or invalid.

`scripts/cache_assets.py` owns normalized annual records, series validation,
atomic series publication and completion evidence. Preparation and data-group
inspection share `books.statements()` for financial eligibility. Completion
entries in `raw/download-coverage.json` use `sha256`, `windows`, `base_span` and
one `previous` receipt. Bind either receipt to its exact valid asset. Keep the
original base span separate from managed completed windows, so out-of-order
results cannot hide unfinished middle windows. Publish expected-content receipts
before replacing the asset; retain the earlier receipt for interrupted writes. Reuse windows
only for the exact valid saved asset. Missing, corrupt, replaced or legacy
unbound files must not inherit completion evidence. Preserve usable rows and
back up invalid originals before repair. Empty provider responses can be reused
only while their associated asset remains intact. Saved date spans do not prove
that every session exists; internal gaps are not repaired automatically. Finite zero or negative adjusted prices are excluded and recorded as `skipped_dates` in the content-bound receipt. Even an entirely excluded price window is checked but unavailable; preserve existing usable prices, show the exclusion warning, and continue the batch. Malformed records, missing/nonfinite values and out-of-window dates still fail before publication. Atomic JSON publication retries Windows access or sharing locks up to eight attempts, with less than two seconds of total retry waits. Keep cache ownership and receipt-before-asset ordering through retries. Other file errors fail immediately.

`scripts/cache_access.py` owns shared resource coordination. Startup, standalone
preparation, data jobs, fixed schedules and random batches must use it. Lock
order is the process-local reentrant lock, project file lock, then database
connections and worker pools. Hold ownership through worker completion and
final database closure. Nested preparation reuses ownership. Build subprocesses
read under the parent’s ownership; workers must not acquire the parent lock.
Keep `data/website-data-0.lock` ignored. Do not replace this with a handler-only
thread lock; multiple local server instances share the same cache.

Focused checks: `python3 tests/test_data_manager.py`,
`python3 tests/test_cache_access.py`, and `node tests/check-data-panel.cjs`.
Run the cache-access and data-manager checks on native Windows too.


## Parallel FMP downloads

`scripts/fmp_download.py` owns the data panel transport. Use eight request
workers with reusable connections, a shared four-starts-per-second default cap,
and one publishing owner. At most eight tasks may be submitted at once. Workers
must not write raw files or completion receipts. Retain completed windows after
cancellation; do not release cache ownership before in-flight workers finish.

Use up to ten-year windows for adjusted stock and SPY histories. Keep Treasury
windows monthly. Respect shared Retry-After cooldowns, reduce the start rate on
429, and bound retries to three attempts. Retry waits must be cancellable. Socket
timeout is 15 seconds; the read deadline is 30 seconds. Close each exhausted HTTP
response explicitly before connection reuse, including Python 3.12 read1 EOF.

The native Windows experiment and its limitations are recorded in
`results/experiments/fmp-download-benchmark.json`. Temporary API responses and
experiment caches live in ignored `tmp/`. Do not reuse old timings as a new
measurement. Test `python3 tests/test_fmp_download.py` and the data-manager and
cache-access checks, including native Windows.
