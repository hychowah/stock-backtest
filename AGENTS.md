# EBITDA/EV January book

This folder is a standalone US stock backtest with a local website. It is not a
a different research session. Do not open the parent harness, do not invent a
fair value, and do not edit product code from a research session.

The folder can move. Scripts resolve paths from their own file. The FMP key stays
at `~/.grok/secrets/fmp_api_key`. Never print the key or a request URL.

## Records

Follow [docs/records-policy.md](docs/records-policy.md). Standing documents
describe the current system. An active multi-session plan lives in
`docs/plans/<initiative>/`, with working notes in `phases/phase-NN/working/`.
Close out a finished initiative: keep its summary and decisions, delete the rest.
Logs, timings, raw benchmark output and new experiment or probe code stay in
ignored `tmp/`. `tools/experiments/` holds only the API probes listed in
`tools/README.md`. An experiment that must survive
becomes a phase of an active plan. Put slice
evidence, audit findings and their dispositions in the commit message. Before
every commit, run `python3 tests/check_records.py` in the WSL source checkout. Do
not commit if it fails. After changing the check, run
`python3 tests/test_records_check.py`.

## Current state and authorization

Only `docs/plans/typed-storage/` is active. The other summaries give the
outcome, key decisions and known limits. Original is the only engine the
website runs. The source has no experimental (Numba) engine, benchmark
harness, engine comparison runner or Rust backend (see Engines).
Custom variables are integrated into `main`. Source work does not establish
installed readiness or real-cache coverage.

Do long work on a branch or linked worktree. Integrate into `main` only with the
user's authorization. Push, deployment, installed-runtime restart, downloads and
live runtime, cache or durable-store access each need explicit authorization. A
running supervisor publishes `main` at 01:00. Before advancing or
rewriting `main`, check read-only process metadata for `tools/deploy.py --start`
and native project servers. Preserve unrelated uncommitted files in the main
checkout. Verify with private synthetic fixtures, never the live cache.

When two lines of work touch the same contract, agree which branch owns it
before editing. Shared contracts are calculation rules, engine interfaces,
prepared schemas, freshness checks, and worker and lock ownership. Keep edits
to shared files narrow. Avoid broad refactors,
renames and formatting changes in these areas.

## Standing engineering rules

- Preserve financial calculations and policy, stored rounding, old immutable
  bytes, captured requests, queue records, artifacts and durable store formats
  that exist in a `main` commit or in user data. Do not add readers or upgrades
  for formats that never reached `main`.
- Build for current needs. An abstraction, option or mode needs a current
  caller. Check each input once, at its boundary. Freshness re-checks of files,
  databases and payloads that can change between steps are separate and stay.
- Tests check product behavior through public interfaces. Keep new tests fast;
  see Tests.
- Unsupported numerical work fails explicitly, with no fallback. A missing
  prepared company or lane never falls back to another calculation.
- Preserve operation-boundary freshness, bounded leaf reads, cancellation,
  worker/writer and lock ownership, attachment lifetime and resource ceilings.
- Strategy calculations never fetch market data. Downloads need an explicit
  data-panel action.
- Python uses the standard library. The JavaScript checks need Node.js.
  Cache-only workflows need no API key.

## Tests

`tests/run.py` runs each `tests/test_*.py` and `tests/check-*.cjs` file in its
own process. It skips the files that `NOT_ENTRIES` names.
`check-range.cjs` and `check_screener.py` still run after `website/build.py`.
`--tier` picks fast (default), heavy (`HEAVY`) or all. Eight files run at
once; `--jobs` overrides it. Tests reaching cache-coordinated code patch
`cache_access.workspace` with a private `WorkspaceAccess`; the runner fails a
file that touches the checkout's `data/` beyond reading `workspace.json`. Its
docstring describes the isolation. Every tier needs only `python3` and Node.js:
`python3 tests/run.py`.

`tests/test_package_structure.py` checks that the server entry and Original
load no numerical package.

- Before every commit, run the fast tier in the WSL source checkout. Do not
  commit if it fails. It takes under a minute. Give it a tool timeout of at
  least 10 minutes.
- Before integrating a branch into `main`, also run `--tier heavy` when a
  `HEAVY` file covers the change. Run it in the background.
- A new test file is fast. Keep it under 60 seconds; the runner lists fast
  files that take longer. Adding a file to `HEAVY` needs the user's agreement.
- To run one file, call it directly, for example `python3 tests/test_queue.py`
  or `node tests/check-queue.cjs`. A direct call uses the system temporary
  folder. WSL `/tmp` is too small for some fixtures, so set `TMPDIR` to a disk
  folder outside every checkout, such as `~/.cache/ebitda-ev-spread-tests`.

## Git in this environment

The authoritative source checkout is `<wsl-checkout>` in
WSL. Its `.git` file points to the preserved `.git-local/` history. Ordinary Git
commands work there. The retained original Windows folder has an empty,
read-only `.git/`; use the explicit form there:

```
git --git-dir=.git-local --work-tree=. status
```

If the default Git wrapper fails with a WSL socket error, use `/usr/bin/git`.
Do not initialize a new repository. Rewrite history only when the user asks, and
back up `.git-local/` first.

## WSL development and native Windows runtime

Edit and commit only in the WSL source checkout. `<windows-runtime>`
is the native Windows runtime, not a second repository. `python3 tools/deploy.py`
exports committed source there; uncommitted edits are excluded. A fresh
standalone publication needs an explicit `--revision`. A valid pending
publication selects its recorded commit for recovery. `--start` serves the
installed revision and updates to `main` at 01:00. `--revision <commit>
--start` fixes one launch. `--check` deploys and runs the installed Windows
checks. Windows `backtest-web.cmd` runs the same flow through WSL.
Local paths live in ignored `data/workspace.json`.

Preserve Windows-owned raw data, databases, logs, environments, local builds and
the verified canonical report. Do not edit runtime source or copy these assets
back into WSL. `--collect-report` collects a database-bound report and priced
evidence for review. The WSL checkout has source and synthetic fixtures, not a
second raw cache. Run real-cache preparation and `tests/check_paths.py` with
native Windows Python.

Publication stops only authenticated project servers, owns runtime source
exclusively, then takes financial cache ownership. Native server entry takes
shared source ownership before importing `website/server/app.py` and holds it
through shutdown. Do not change source/bootstrap lock ordering or bypass a
`data/deployment.pending.json` journal. Retry deployment to complete recovery.
Only manifest-owned source can be removed. See
[docs/workspaces.md](docs/workspaces.md). Verify with
`python3 tests/test_deployment.py`, including native Windows.

## What the test does

Each January, from 1996 through 2026, buy the 50 US common stocks with the
highest EBITDA/EV. Sell at the next January. The 2026 book is marked through the
last SPY session on or before 2026-10-21. Compare with SPY, dividends included.
Equal weight. No commissions. The 3-month Treasury yield is one number for every
stock that day, so subtracting it does not change the rank.

## Rules already chosen

- Exchanges: NYSE, Nasdaq, NYSE American. ETFs and funds are out. Delisted US
  names are in the universe.
- The annual figure is treated as known 90 days after fiscal year-end. A report
  older than 800 days is dropped.
- Enterprise value at the buy date uses the report's debt and cash and the
  dividend-adjusted buy-date price.
- Market cap at least $100 million. Enterprise value at least $50 million.
  Currency USD. A stock with no buy price is left out.
- If trading stops before the January sale, the exit is the last price. That
  covers an acquisition, a called note and a SPAC that returns cash.
- A bankruptcy is a total loss. `BANKRUPT` in `backtest/financial/rules.py` is
  the set of `(year, symbol)` pairs that get −100%. It is empty. The 37 stops
  were checked: acquisitions, redemptions, SPAC cash or warrants.
- A stock that still has a January price keeps that price. A later delisting
  does not rewrite the year.

## Current result

`results/summary-exits.txt` is the result to continue from. It keeps a stock
when trading stops. `results/legacy/summary.txt` and `results/legacy/picks.csv`
are the earlier pass, which dropped a stock whose price stopped more than 10
days before the January sale. Do not quote them as the latest result.

`scripts/revalue.py` requests a verified refresh of `results/summary-exits.txt`
and the research database. The independent read-only `calculate(through)` lives
in `backtest/engines/reference/revalue.py`; it reads the cache and does not
download. `scripts/run.py` runs the retained downloader and the older report in
`backtest/engines/reference/legacy.py`, which keeps the old exit rule.

## Cache

Do not refetch data that is already here. Keep `raw/` with the Windows runtime.

- `raw/universe.json`: about 11,054 US names, including 5,068 delisted names
  without sector or delisted date.
- `raw/metrics.jsonl`: annual key metrics, one JSON object per line.
- `raw/px/`: dividend-adjusted price history for the screened names.
- `raw/spy-div.json`: SPY total-return prices from 1995.
- `raw/treasury.json`: daily Treasury yields from 1995; `month3` is in percent.

`raw/archive/` holds leftover bulk downloads that no calculation reads.

## FMP limits

A 30-year price or Treasury request returns only the latest rows, so request
short windows. One stock price history is capped at about 5,000 sessions. Bulk
statement files are refused when many run at once. Per-symbol `key-metrics` calls
work at about 16 at a time; `fetch_metrics` turns off the pace gate in
`backtest/inputs/legacy_downloads.py`.

## How to continue

Recompute exits from the cache with `python scripts/revalue.py`. Add a
bankruptcy by putting `(year, "SYMBOL")` in `BANKRUPT`, then run it again. Run
`scripts/run.py` only when the cache is missing data. Merge any new exit rule
into `backtest/engines/reference/revalue.py` before treating the legacy report as
current. `scripts/classify_stops.py` and `results/stops/stops-class.json` record
SEC form types for the 37 stops. Their merger flag is broad; check a name before
calling it a bankruptcy.

## Project layout

Documented commands live in `scripts/`. Financial policy, screening, calendars
and portfolio results live in `backtest/`; `backtest/paths.py` resolves paths.
Operational tools are in `tools/ops/`; `tools/experiments/` keeps the FMP API
probes. Current reports are in `results/`, older reports in
`results/legacy/`, stop analyses in `results/stops/` and small cited experiment
summaries in `results/experiments/`. The website source lives in `website/`.

Builds, startup and data-panel rebuilds write ignored `website/local/`, which the
server serves. Build with `python3 website/build.py`.
`python3 website/build.py --snapshot` writes an untracked portable export to
`website/dist/`. Browser parity and range checks use local output by default;
pass `website/dist` to check an export. Verify paths with
`python3 tests/check_paths.py` and website calculations with
`node tests/check-range.cjs`.

## Keep the architecture guide current

Before every commit, compare the full diff with
`docs/architecture-guide/dist/index.html`, the human-facing guide to how the
program works. Update affected explanations, diagrams, setting examples, cache
rules and file maps in the same commit. Check changes to preparation, selection,
metrics, exits, schedules, random trials, startup, website controls, cache
schemas and file locations. If nothing is affected, leave its content and checked
date unchanged and say so in the completion report.

Use ASD-STE100 principles: short sentences, one idea per sentence, consistent
terms. Explain user-visible behavior before implementation. Distinguish current
source, a running server and benchmark-only prototypes. Tie each timing to its
original settings and engine. Change the checked date only after checking the
claims against the code. When the guide changes, run
`node docs/architecture-guide/check.cjs` and update that check when guide
controls change. Keep the guide self-contained. Report unverified browser checks.

## Feature contracts

Each paragraph lists invariants that are easy to break and the checks to run.
The linked documents hold the detail.

**Research database and baseline.** `scripts/research.py prepare` builds
`data/research.sqlite` (research schema 12) from the raw cache. It compares the
prepared baseline with `revalue.calculate(through)` at full precision. Both
engines must agree on all years, ranks, symbols, dates, prices, valuations,
returns and exit basis. Never bypass disagreement or relax the tolerance.
Reused company units must equal a full rebuild; a changed scope or
historical unit reruns the comparison.
`backtest/inputs/baseline.py` owns the report cutoff, rendering, revision
evidence and recoverable report/database publication. Verified changes update the
canonical report without advancing its Through date. Previous reports stay
verbatim under ignored `results/baseline-history/`. First-run unavailable prices
stay null. An unfinished `data/research.sqlite.publication.json` blocks readers.
Use `scripts/research.py screen` flags for experiments instead of editing `HOLD`.
The `legacy` pool keeps the original 250-candidate pre-price screen with the
current exit rule. The `cached` pool covers cached-price companies only; report
missing coverage and unreviewed early stops. Checks: `tests/test_baseline.py`
(also native Windows), `tests/test_research.py` and
`tests/test_prepared_reuse.py`. See
[docs/research-workflow.md](docs/research-workflow.md).

**Website screening.** `website/rendering/data.py` embeds both prepared pools.
`website/browser/screener.js` must match SQL selection in
`backtest/inputs/research.py` in both modes and pools. Latest mode uses the
latest cached SPY session, an exact-session adjusted price and cached
`listed=True`. It never reuses stopped prices and stores no future return.
`screening.latest()` and `StockScreener.latestScreen()` must agree. Historical
preparation is bounded by the canonical report's Through date; latest
preparation can advance independently. Keep the static top-50 fallback and the
baseline exports. Show short or empty years. Do not calculate a full-period CAGR
when any selected year is empty. Top contributors are the first
`min(10, selected count)` stocks by signed contribution, ties by symbol. Gain and
loss pies are normalized separately and never show negative slices. Checks:
`python3 tests/check_screener.py` after building, `node tests/check-range.cjs`,
`node tests/check-contributions.cjs` and `python3 tests/test_attribution.py`.

**Selection order.** `filter_first` is the default. `rank_first` takes the
inclusive rank range from the prepared pool before user filters, keeps original
ranks and adds no replacements. Equal weights use the survivor count. Each
historical year ranks independently. Preserve the order through jobs, the queue,
saved results and replay. Older records omit it and mean filter-first; never
rewrite or recalculate them. Check `python3 tests/test_selection_order.py`.

**Metrics and threshold filters.** `backtest/financial/metrics.py` owns the
catalog, the calculators and every formula. Consumers read prepared pairs and
filter values without interpreting formulas. Current EV/EBITDA is the default
ranking. The three-year metric divides current EV by mean EBITDA from three
consecutive annual reports. Conditions use `field`, strict `lt` or `gt` and a
finite value in display units. A missing value fails only conditions that need
it. Use the selected fiscal report only; never fill a field from a newer report.
Trailing returns use adjusted prices on or before the screen date and its
anniversary, within seven days; leap days clamp to 28 February. Ratio
denominators must be positive. A calculation change needs offline preparation,
a rebuild, and temporal and SQL/browser parity checks. Check
`python3 tests/test_financial_inputs.py`.

**Data panel and raw cache.** `/data.html` checks and rebuilds from saved files.
Downloads start only from an explicit button and fill only missing data.
`backtest/inputs/cache_assets.py` owns normalized records, validation, atomic
publication and content-bound receipts in `raw/download-coverage.json`. Publish
the receipt before replacing an asset. A missing, replaced or unbound file never
inherits completion evidence. Keep every returned field and row in
`raw/financial-inputs/`; conflicting inputs stay absent. Finite non-positive
adjusted prices are excluded and recorded as `skipped_dates`.
`backtest/runtime/cache_access.py` owns coordination: process lock, then project
file lock, then database connections and worker pools. Hold ownership through
worker completion and database closure. Do not replace it with a thread lock.
Keep the key and provider URLs out of status responses. Checks:
`tests/test_data_manager.py` and `tests/test_cache_access.py` (also native
Windows), and `node tests/check-data-panel.cjs`.

**FMP downloads.** `backtest/inputs/fmp_download.py` owns transport: 32 workers,
reusable gzip connections and a shared cap of 45 starts per second. At most
`client.workers` tasks are in flight. Only the publishing owner writes raw files
or receipts. Use ten-year windows for stock and SPY history and monthly Treasury
windows. Respect Retry-After, slow down on 429, try at most three times and keep
waits cancellable. The socket timeout is 15 seconds; the read deadline is 30
seconds. Measurements are in `results/experiments/fmp-download-benchmark.json`
and `results/experiments/fmp-throughput-2026-10-23.json`. Do not present old
timings as new measurements. Check `python3 tests/test_fmp_download.py`.

**Custom dated schedules.** `scripts/schedules.py prepare` builds the ignored
daily SQLite cache (version 5) after research preparation. It prepares only the
requested pool and records completion in `period_pools` in the same transaction
as the rows. Dates anchor to the starting day, clamp month ends and roll forward
to SPY sessions; end marks roll back. Intervals are 1, 3, 6, 12 and 24 months.
Reuse `screening.select` and `metrics.evaluate`; never duplicate formulas. Label
dated period returns, not annual returns. Daily inputs bind accepted research
content, policy and price inventory; older caches rebuild and refreshes keep
only unaffected books. A root in a recorded
January or latest scope reads that scope's stored owner lanes. Check
`python3 tests/test_schedules.py`. See
[docs/schedule-calendar.md](docs/schedule-calendar.md).

**Random-date sensitivity and book batches.**
`backtest/engines/original/robustness.py` samples one SPY session in each
frequency block for each seeded trial, with 1–100 trials and 24 by default. All
trial CAGRs share a window with zero-return cash before the first trade, for the
strategy and SPY. Keep incomplete trials visible and exclude them from both
distributions. Average trial CAGR is not one portfolio return; percentiles are
not confidence intervals. Commit per trial so a retry reuses books. An omitted
seed is generated server-side and recorded. `book_batch.py` plans unique missing
books. Read-only workers calculate and only the parent stores, with one read
transaction per book. Use up to eight workers for 16 or more missing books; small
batches stay serial. Workers watch the parent's lifetime. Checks:
`tests/test_robustness.py`, `node tests/check-robustness.cjs` and
`tests/test_book_batch.py` (also native Windows spawn).

**Launcher and automatic updates.** `website/server/launcher.py` owns identity
publication, control requests, the per-port startup lock and the lifetime lock.
Never stop an unknown port owner. An unreachable endpoint does not prove the
old server has finished; replacement waits up to 30 seconds. The default
listener is `0.0.0.0:3000`. Open the browser only after preparation and binding.
`tools/deploy.py --start` serves the installed revision. At 01:00 it resolves a
changed `refs/heads/main` tip to one commit, stages source before stopping the
child and completes pending publication first. Never force-kill a server or replace source on
timeout. `backtest/runtime/diagnostics.py` writes per-process logs in
`data/logs/`. Never log exception text, keys, provider URLs or response bodies.
Checks: `tests/test_startup.py`, `tests/test_auto_update.py`,
`tests/test_deployment.py` and `tests/test_diagnostics.py`, on WSL and
native Windows. Use private repositories and runtimes.

**Saved library and queue.** `data/saved-backtests.sqlite`
(`backtest/application/library.py`) and `data/backtest-queue.sqlite`
(`backtest/application/queue.py`) are durable user records, not caches. Preserve
them through preparation, cleanup and deployment. Each holds up to 100 visible
records and never evicts one automatically. Delete only what the user selects.
Rename changes only the name. Opening, copying or comparing a stored result never
calculates. `data/backtest-queue.lock` elects one consumer; only it recovers
interrupted rows. End queue transactions before requesting cache ownership.
Cache contention defers work and never fails it. A completed result moves to the
library after the library copy commits; a failed import stays visible for retry.
Record a random seed at admission and the date plan before execution. Held edits
do not execute, and only waiting tests can change. Shutdown requeues interrupted
work; an explicit Stop stays cancelled. `StrategyDraft` in
`website/browser/range.js` owns form restoration and refuses to overwrite a held
draft. Checks: `tests/test_saved_backtests.py`, `tests/test_queue.py` and
`tests/test_queue_transfer.py` (also native Windows), and the
`node tests/check-*.cjs` checks for saved backtests, queue, comparison and result
artifacts.

**Engines.** `backtest.application.original_calculations.Original` is the only
live calculation owner. The server, jobs and the queue use it directly.
`Original.preflight` admits new work. It refuses an `options.engine` other than
`original` with `UNSUPPORTED_CAPABILITY` at `/engine`. In requests and records,
`options.engine` is `original` or `experimental`; omission means Original.
Preserve the recorded value in jobs, queue receipts, held edits, recovery and
replay, outside financial plans. Never rewrite it to Original. The queue claims
only rows of `Original.engine`; a waiting row that names another engine stays
waiting until the user edits or deletes it. A restored draft keeps its recorded
engine and shows the engine choice. Opening, copying or comparing a stored
experimental result never calculates. New results record `result.producer`;
never infer a producer for older results. `backtest/calendar_requests.py` owns
request and plan policy; preserve legacy planner hashes. Normal startup needs
no numerical packages. Checks: `tests/test_calculations.py`,
`tests/test_backtest_jobs.py` and `tests/test_package_structure.py`.

Existing `data/numerical/` and `data/numerical-preparation.json` stay on the
runtime; no source reads them.

**Result access.** `backtest/application/result_access.py` owns acquired results,
with 16 display readers and 32 request pins. Stored operations never prepare or
calculate results and never consult the current catalog. In the browser,
`ResultArtifacts.use` scopes every opening, comparison and parameter read and
releases unaccepted acquisitions. Views, downloads and saving read the immutable
published artifact, not the live form. Decode older saved records without
rewriting them. Shutdown closes admission, drains readers and joins requests
before source ownership ends. See [docs/evidence-views.md](docs/evidence-views.md).

**Custom variables.** Reference evaluation covers definition versions 1–3 and
catalogs `/1`–`/3`. New formulas use version 3 and catalog `/3`; old formulas
need an explicit upgrade. `backtest/variables/selection.py` holds the single
qualified scalar gate. Reference or provider support alone grants no application
qualification. Eager scalar execution and numerical sample preview are
unsupported. Derived `at` and `lookback` contexts use dated owner policy, even at
an equal date. Preserve the 32-definition closure ceiling. Original scalar
operations hold inputs through `backtest/inputs/operation_inputs.py`: one daily
fingerprint at entry, one file status per step, no row rescans. Checks:
`tests/test_operation_inputs.py` and heavy `tests/test_original_long_window.py`.
See
[variable design](docs/plans/custom-variables/variable-design.md) and the
[parameter catalog](docs/plans/custom-variables/parameter-catalog.md).
