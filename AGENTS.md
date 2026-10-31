# EBITDA/EV January book

This folder is a standalone US stock backtest. It is not a a different research session. Do not open the parent harness, do not invent a fair value, and do not edit product code from here.

The folder can move. Scripts resolve paths from their own file. Keep `raw/` with the Windows runtime code. The WSL source checkout does not hold a second full cache. The FMP key stays at `~/.grok/secrets/fmp_api_key`. Never print the key or a request URL.

## Parallel development boundary

The `main` worktree continues frontend and unrelated backend development. The
`cb02/input-ownership` worktree owns the new backtest engine and its supporting
financial/cache contracts. Before choosing files for a task, read
[docs/worktree-coordination.md](docs/worktree-coordination.md).

On main, preserve calculation rules, engine interfaces, prepared schemas,
freshness checks, worker/lock ownership and benchmark code. Keep edits to shared
files narrow. Avoid broad refactors, renames and formatting changes in these
areas. If a feature needs an overlapping change, identify the affected contract
and agree its owning branch before editing that part. Existing task agreements
can supply that coordination. Continue independent work while an overlap is
unresolved. This boundary keeps both worktrees active and limits merge conflicts.

## Git in this environment

The authoritative source checkout is `<wsl-checkout>` in
WSL. Its `.git` file points to the preserved `.git-local/` history. Ordinary Git
commands work there. The retained original Windows folder has an empty,
read-only `.git/`; use the explicit form below there or in the source checkout:

```
git --git-dir=.git-local --work-tree=. status
git --git-dir=.git-local --work-tree=. log --oneline
```

Use the same options for diff, add and commit. If the default Git wrapper fails
with a WSL socket error, use `/usr/bin/git` with these options.
Do not initialize a new repository or replace the saved history.
In the retained original folder, ordinary Git commands and apps may not detect
the repository automatically.

## WSL development and native Windows runtime

Edit and commit only in the WSL source checkout. `<windows-runtime>`
is the native Windows runtime, not a second repository. `python3 tools/deploy.py`
exports committed source there. Normal publication retains the installed commit;
a valid pending publication selects its recorded commit for recovery. Use
`--revision <commit>` from WSL only for a deliberate revision change. A fresh
runtime requires an explicit revision. Conflicting pending intent is rejected.
`--start` deploys and starts native Python;
`--check` deploys and runs the installed Windows checks. The installed Windows
`backtest-web.cmd` performs the same deploy/start flow through WSL. Local paths
and interpreter registration live in ignored `data/workspace.json`.

Preserve Windows-owned raw data, databases, logs, environments, local builds and
the verified canonical report. Do not edit runtime source or synchronize these
assets back into WSL. `--collect-report` explicitly collects a database-bound
report and priced evidence for review; it refuses conflicting source edits.
The WSL checkout has source and synthetic fixtures, not a second raw cache.
Run real-cache preparation and `tests/check_paths.py` with native Windows Python.

Source publication stops only authenticated project servers, owns the runtime
source exclusively, then takes financial cache ownership. Native server entry
takes shared source ownership before importing `website/serve_app.py` and holds
it through shutdown. Do not change source/bootstrap lock ordering or bypass a
`data/deployment.pending.json` journal. Retry deployment to complete recovery.
Only manifest-owned source can be removed. Preserve the original folder as a
fallback. See `docs/workspaces.md`. Verify deployment with
`python3 tests/test_deployment.py`, including native Windows.

## Current result

`results/summary-exits.txt` is the result to continue from. It is the pass that keeps a stock when trading stops.

`results/legacy/summary.txt` and `results/legacy/picks.csv` are the earlier pass. That pass dropped a stock when its price stopped more than 10 days before the January sale. Do not quote those files as the latest result.

`scripts/revalue.py` requests a verified refresh of `results/summary-exits.txt` and the research database. Its `calculate(through)` function is the independent read-only engine. It reads the cache and does not download. `scripts/run.py` still uses the old exit rule and rewrites `results/legacy/summary.txt`.

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

The website source lives in `website/`. Normal builds, startup and data-panel rebuilds write ignored `website/local/`, which the server serves. Build with `python3 website/build.py`. The tracked `website/dist/` is a portable snapshot. Refresh it only with explicit `python3 website/build.py --snapshot`. Do not auto-stage snapshot changes with unrelated code. Review its `snapshot.json` cutoffs and source hashes with generated diffs. Browser parity and range checks default to local output; pass `website/dist` to check the portable snapshot. Verify path handling with `python3 tests/check_paths.py` and website calculations with `node tests/check-range.cjs`. Python uses the standard library; the JavaScript check needs Node.js. Cache-only workflows require no API key.

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

`scripts/research.py prepare` creates the offline `data/research.sqlite` January data layer from the raw cache. It compares the prepared baseline with `revalue.calculate(through)` at full precision; repeated preparation skips parsing when inputs are current. `scripts/baseline.py` owns the report cutoff, report rendering, holding-level agreement, revision evidence and recoverable report/database publication. Both engines must agree on all years, ranks, symbols, dates, prices, valuations, returns and exit basis. Verified changes update the canonical report without advancing its Through date. Preserve previous reports verbatim and priced snapshots under ignored `results/baseline-history/`. First-run unavailable prices must stay null. An unfinished `data/research.sqlite.publication.json` blocks readers; preparation completes its hash-verified publication before freshness checks. Do not bypass disagreement or relax the full-precision tolerance. Test with `python3 tests/test_baseline.py`, including native Windows. Use `scripts/research.py screen --top 100` or other flags for experiments, rather than editing `HOLD` and reparsing daily history. The website uses the prepared database. `scripts/revalue.py` remains the independent slower reference calculation.

The `legacy` research pool preserves the original 250-candidate pre-price screen and uses the **current** exit rule. The `cached` pool broadens the screen to available cached-price companies, not the full universe. Report missing coverage and unreviewed new early stops; do not imply all expanded holdings received the earlier bankruptcy review. See `docs/research-workflow.md`. Test with `python3 tests/test_research.py`.

## Website strategy builder

`website/dataset.py` exports both prepared January pools as compact records embedded in the HTML. `website/screener.js` implements browser filtering/ranking; `website/range.js` connects controls and renders results. Each runtime shares filtering and ranking between historical and latest modes; only historical mode validates years. Browser parameters must match the SQL selection semantics in `scripts/research.py`. Check parity with `python3 tests/check_screener.py` after building; it requires a current prepared database. Keep the original static top-50 fallback and baseline CSV/JSON exports. Browser downloads reflect the current strategy. Show short/empty-year coverage explicitly; do not calculate a full-period strategy CAGR when any selected year is empty.

Yearly attribution uses `website/contributions.js` for browser calculations and `website/attribution.py` for the static fallback. Top contributors means the first `min(10, actual selected count)` stocks, ordered by signed contribution (return / actual selected count), with ties by symbol. Gain/loss pies are normalized separately; never draw negative slices or describe them as shares of net return. Check with `node tests/check-contributions.cjs`, `python3 tests/test_attribution.py`, and the existing range/control tests.

## Selection order

`selection_order` is `filter_first` by default. `rank_first` selects the requested
inclusive rank range from the prepared pool before all user filters apply.
Keep original ranks and add no replacements. Equal weights use the survivor
count. Pool eligibility and available ranking metrics precede both orders.
SQL and browser selection must agree in both modes and pools. Each historical
year ranks independently. Orders reuse the same dated books and sampled plans.
Preserve the order through manual jobs, queued tests, saved results and replay.
Older saved settings omit it and mean filter-first. Do not rewrite these records
or recalculate them when opened. Check `python3 tests/test_selection_order.py`,
research/schedule/robustness/queue checks and browser/artifact controls.

## Latest-date website screening

Schema version 2 prepares `latest_snapshots` separately from historical snapshots. Latest date means the latest cached SPY session. Require an exact-session dividend-adjusted price and cached `listed=True`; never reuse old stopped prices in the latest screen. Use the same 90-day lag, strict availability-before-date rule and 800-day report-age limit. No future return or contribution is stored for latest picks. `research.latest_screen()` and `StockScreener.latestScreen()` must agree. The website opens in latest mode; historical mode retains year controls.

Historical preparation is bounded by the canonical report's Through date and historical ASOF, while latest preparation can advance independently. The report cutoff participates in source freshness. Its full content hash binds the committed database to the report. Capture schedule fingerprints after research preparation, since preparation can update the report. Refresh prepared data and rebuild the HTML after cache updates; strategy calculations do not fetch market data. The separate data panel downloads missing inputs only after an explicit button action. Tests include exact-date exclusion, unavailable/stale reports, cached listing status, unchanged historical periods when latest prices advance, both SQL/browser screen modes and latest CSV output.

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
and completed pools. Daily inputs also bind to the price inventory accepted by research
metadata. After accepted in-place price edits, rebuild daily prices before numeric
export. Old caches without this binding cannot establish compatibility. Version-1 books mark both pools complete; version-2 books
retain their individual markers. Changed research inputs still require preparation.

## Automatic local launcher

`backtest-web.cmd` and `start.cmd` (Windows) use `website/launcher.py` to manage a terminal-owned server. Terminal logs stay visible; Ctrl+C stops the server. Safe development diagnostics also persist in `data/logs/website-<namespace>-<pid>.log`, with a 5 MiB active log and two rotated backups per process. `scripts/diagnostics.py` owns this logging. Startup removes logs older than 14 days, then oldest logs toward a 100 MiB total target. Delete only stopped-process logs from the current process namespace. Preserve legacy logs and foreign or unknown namespaces. Linux ownership includes the boot and PID namespace; Windows ownership uses the machine identity. Protected files and growth between starts can exceed the target. Cleanup errors do not stop startup. Keep exception types, OS codes and stack locations; omit exception text, source lines, locals, keys, provider URLs and response bodies. Startup and the data panel show the current log path. Test with `python3 tests/test_diagnostics.py`, including native Windows. The default listener is `0.0.0.0:3000`; the local browser uses `http://127.0.0.1:3000`. A per-port startup lock serializes preparation and binding. A separate lifetime lock stays held until the listener and all request threads close. An unreachable HTTP endpoint never proves that the old server has finished. Replacement waits up to 30 seconds for ownership, then reports a retry instruction. `website/launcher.py` owns identity publication, control requests, cleanup and both locks. An authenticated loopback identity endpoint identifies this project. Each managed launch stops the identified previous server and starts current code in the invoking terminal. This transfers ownership even from an unchanged background instance. Do not stop unknown port owners. Identity and startup lock files live under ignored `data/website-*` paths. Direct `python3 website/serve.py` remains a foreground option. The daily
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
at the chosen selection stage. Missing values fail only conditions that need them. Use display
units: millions of USD, percent, or multiples. `metrics.filter_values()` owns
threshold calculations for January, latest and dated books. Trailing returns
use only adjusted prices on or before the screen date and its anniversary,
within seven calendar days. Clamp leap-day anniversaries to 28 February. Financial ratio filters include P/E, P/B, free cash flow amount/yield, price/FCF,
net profit margin, historical PEG, ROE, current ratio, interest coverage and debt/equity.
`scripts/financial_inputs.py` validates separate annual statement assets under
`raw/financial-inputs/`. Downloads require the data-panel Full annual financial data action.
Save full annual income, balance-sheet, cash-flow, key-metrics and ratios responses.
Preserve all returned fields, nulls, currencies and filing metadata in raw assets.
Repeated fiscal dates are valid. Preserve all returned rows and distinct saved
variants on repair. Prepare each input only when nonmissing USD values agree
within the endpoint and fiscal date. Conflicting inputs remain absent.
Select eligible USD numerical inputs separately for calculations. New key-metric
records in metrics.jsonl also keep full responses. Backfill old trimmed key metrics
in the separate full-data cache without rewriting baseline inputs.
Content-bound receipts include empty responses. Rebuild after download.
`scripts/metrics.py` owns the formulas. Use the selected fiscal report only;
never fill missing fields with a newer report. PEG uses positive three-year
diluted EPS CAGR in percentage points with four consecutive positive EPS years.
ROE uses mean positive equity from the selected and previous fiscal years.
Other ratio denominators must be positive. Keep signed cash flow and margin values.
Check `python3 tests/test_financial_inputs.py` alongside research, schedule and browser parity checks.

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

`scripts/fmp_download.py` owns the data panel transport. Use 32 request
workers with reusable connections, gzip responses and a shared 45-starts-per-second
default cap (2,700/minute, below this account's stated 3,000/minute allowance).
Decode successful gzip responses inside the transport. Accept plain responses.
Encoding failures use bounded transport retries. Error status and Retry-After
take precedence over body encoding. Keep one publishing owner.
At most `client.workers` tasks may be submitted at once. Workers
must not write raw files or completion receipts. Retain completed windows after
cancellation; do not release cache ownership before in-flight workers finish.

Use up to ten-year windows for adjusted stock and SPY histories. Keep Treasury
windows monthly. Respect shared Retry-After cooldowns, reduce the start rate on
429, and bound retries to three attempts. Retry waits must be cancellable. Socket
timeout is 15 seconds; the read deadline is 30 seconds. Close each exhausted HTTP
response explicitly before connection reuse, including Python 3.12 read1 EOF.

The native Windows experiment and its limitations are recorded in
`results/experiments/fmp-download-benchmark.json`. Temporary API responses and
experiment caches live in ignored `tmp/`. The 23 October transport experiment
is recorded in `results/experiments/fmp-throughput-2026-10-23.json`. It supports
the new defaults but is not a sustained-rate or full application benchmark.
Keep the earlier eight-worker measurements historical. Do not reuse old timings as a new
measurement. Test `python3 tests/test_fmp_download.py` and the data-manager and
cache-access checks, including native Windows.


Benchmark observations now use source-bound cooperative live-intent leases.
They take source ownership before short cache ownership and yield at checkpoints.
They release ownership before calculation. This does not qualify zero-delay
access or the installed older runtime. Keep `data/website-data-*.lock.live/`
ignored. Real benchmark admission stays closed.
## Saved backtest library

`website/saved_backtests.py` owns durable user records in
`data/saved-backtests.sqlite`. This is not a rebuildable cache. Preserve it during
preparation, cleanup and source deployment. `website/saved-backtests.js` saves the
last completed result and its submitted settings, even when controls have pending
edits. Opening a record restores stored stock rows, returns, labels and downloads
without calculation. Cap the library at 20 records atomically across instances.
Never evict an existing record automatically. Delete only the record selected by
the user. Check `python3 tests/test_saved_backtests.py`, including native Windows,
`node tests/check-saved-backtests.cjs` and the existing range/control checks.

Existing `/api/robustness` streaming clients opt into full trial details with
`X-Backtest-Details: holdings`. Background jobs and queued random tests capture
full trial holdings through `backtest_jobs.calculate`.
The optional `robustness.run(..., capture=observer)` receives each completed
trial's original result. Observers must not mutate it. Preserve the default
summary-only result and all existing calculation/progress contracts. Saved
random records require ordered `trial_results` for every completed trial.

`website/result-artifacts.js` owns the immutable completed artifact for each
browser view. Publish fresh and reopened results through this same boundary.
Views, downloads, setting-match notices and saving must read that artifact;
keep live form edits separate. Persist semantic presentation fields, not DOM
selectors or CSS classes. Decode version-1 saved records without rewriting them.
Confirmed library mutations must remain successful if list reconciliation fails.
Ignore list responses that precede a newer acknowledged mutation. Check
`node tests/check-result-artifacts.cjs` and the saved-library/range checks.

## Overnight backtest queue

`website/backtest_queue.py` owns durable fixed/random test records in
`data/backtest-queue.sqlite`. Preserve this file during rebuilds, cleanup and
deployment. It is separate from financial caches and the 20-slot saved library.
Keep up to 100 visible records without automatic eviction. Only explicit
deletion removes a selected test and its result. Retain a small deleted-ID
receipt so retrying an unacknowledged submission cannot recreate it.

`data/backtest-queue.lock` elects one consumer across local server instances.
Only the consumer holding this OS lock may recover interrupted running rows.
End queue database transactions before requesting financial cache ownership.
Use the existing `backtest_jobs.calculate` adapter and engine cancellation
checks. Retain queue/source/financial ownership through worker completion and
financial database closure. Cache contention defers queue work. It must not
turn a batch into failed tests after a manual-run lock timeout.

Pause prevents the next claim. Held edits do not execute. Only waiting tests
can change settings or order. An edit has a stable ID and settings version.
Queue position changes keep that edit valid. Save and Cancel retain one edit
receipt per test. Exact retries remain safe after execution starts. A new hold
replaces the preceding receipt. Ordinary mutation revisions still protect
queue actions and older clients. Existing durable records upgrade in place.
Server shutdown requeues interrupted work; an explicit Stop stays cancelled.
Record a random seed at admission and the full date plan before execution.
Reuse that plan after interruption. Changing waiting calculation parameters
discards its previous plan. Renaming a test keeps its dates. Each completed
result is an immutable version-2 artifact with all trial holdings and original
display labels. Opening it does not calculate.

`website/queue.js` manages queue controls. Auto-run is suspended while the queue
has waiting/running work or an active edit. Adding, copying or editing an item
turns Auto-run off for batch setup. Explicit Run remains available.
The Add to queue action stays beside Run backtest in the strategy toolbar.
From latest or January mode, it opens custom-date setup with Auto-run off and
does not submit a calculation. A second click submits the selected fixed/random
settings. View queue links to the list below the form.
Parameter edits never mutate submitted tests. Preserve acknowledged queue
mutations if a list refresh fails, and ignore stale list responses. Checks:
`python3 tests/test_queue.py` on WSL and native Windows,
`node tests/check-queue.cjs`, existing background-run/range/library checks and
`python3 tests/test_deployment.py` on both platforms.

`StrategyDraft` in `website/range.js` owns the strategy form. A queued edit
reserves a form session before requesting its server hold. Only that session
can restore settings until a save, cancel, deletion or server reconciliation
ends it. Reconcile the session by its edit ID and version. An externally ended
or replaced hold releases the form without replacing its current settings.
Retry an unacknowledged hold or Save/Cancel with the same identity and payload.
Queue result opening/copying, saved-library opening and manual recovery use
the same restoration boundary. They must refuse replacement with a clear
save-or-cancel message instead of overwriting a held draft. A definitively
rejected hold must release its local form session. An unacknowledged hold keeps
the session for reconciliation or retry. Do not add queue-specific restoration guards
to individual callers. Check these interactions in `tests/check-range.cjs`.

## Experimental engine readiness

CB-14 reconciles schema-8 preparation and both selection orders. The numerical
policy recognizes Original's full threshold catalog but explicitly rejects
`operating_yield_spread_3y` in experimental requests. Keep that rejection before
result or checkpoint reuse. Unknown future catalogs must fail preparation.
Candidate application calls confirm runtime closure before publishing every
outcome. No idle application child may retain financial ownership between calls.
Disk checkpoints remain reusable; cross-call compiler memory is not retained.
Legacy omitted selection order means filter-first when comparing a submitted
request with a recorded plan. Do not rewrite the plan or accept a real change.
See `docs/plans/compiled-backtest/phases/CB-14.readiness.md`. CB-15 owns the
normal-app selector, engine-pinned submissions, producer labels and release.
Original remains default. This readiness work authorizes no deployment.
