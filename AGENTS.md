# EBITDA/EV stock backtest

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

Preserve Windows-owned raw data, databases, logs, environments and local builds.
Do not edit runtime source or copy these assets back into WSL. The WSL checkout
has source and synthetic fixtures, not a second raw cache. Run real-cache
preparation and `tests/check_paths.py` with native Windows Python.

Publication stops only authenticated project servers, owns runtime source
exclusively, then takes financial cache ownership. Native server entry takes
shared source ownership before importing `website/server/app.py` and holds it
through shutdown. Do not change source/bootstrap lock ordering or bypass a
`data/deployment.pending.json` journal. Retry deployment to complete recovery.
Only manifest-owned source can be removed. See
[docs/workspaces.md](docs/workspaces.md). Verify with
`python3 tests/test_deployment.py`, including native Windows.

## What the app does

The app screens US common stocks by EBITDA/EV and other prepared metrics. A
latest screen ranks stocks on the latest cached SPY session. A dated backtest
buys the selected stocks on each date of a fixed or random schedule, holds them
to the next date and compares the result with SPY, dividends included. Equal
weight. No commissions. The 3-month Treasury yield is one number for every stock
that day, so subtracting it does not change the rank. The original study (each
January from 1996, the top 50) is a 12-month fixed schedule from 1 January.

## Financial rules

- Exchanges: NYSE, Nasdaq, NYSE American. ETFs and funds are out. Delisted US
  names are in the universe.
- The annual figure is treated as known 90 days after fiscal year-end. A report
  older than 800 days is dropped.
- Enterprise value at the entry date uses the report's debt and cash and the
  dividend-adjusted entry price.
- Default floors: market cap at least $100 million, enterprise value at least
  $50 million. The `legacy` pool applies them before ranking. Currency USD. A
  stock with no entry price is left out.
- If trading stops before the scheduled exit, the exit is the last price. That
  covers an acquisition, a called note and a SPAC that returns cash. A stock
  that still has a price at the exit keeps it; a later delisting changes nothing.
- A bankruptcy is a total loss. `BANKRUPT` in `backtest/financial/rules.py`
  holds `(symbol, day of loss)` pairs; a holding gets −100% only when its book's
  window (after entry, through exit) contains that day. It is empty. The 37
  early January-study stops were checked: acquisitions, redemptions, SPAC cash
  or warrants.
- A stored book row records only how a holding exited: `Scheduled exit`, `Last
  available price` or `Bankruptcy`. The run shows `Marked to date` when its last
  book ends on a mark, not a scheduled exit (`portfolio_results`).
- The first usable day of a schedule or historical root is `rules.FIRST_DAY`
  (1996-01-01).

## Frozen January record

`results/summary-exits.txt`, `results/baseline-history/`, `results/legacy/` and
`results/stops/` are a frozen record of the January study. Nothing regenerates
or touches them. `summary-exits.txt` keeps a stock when trading stops; its 2026
row is marked through its Through date. `results/legacy/` is an earlier pass
that dropped early stops; do not quote it. `results/stops/stops-class.json`
records SEC form types for the 37 stops; its merger flag is broad. Deployment
never installs or replaces the runtime copy of `summary-exits.txt`.

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
work at about 16 at a time.

## Development check

After a change to book policy, run `python3 scripts/check.py` on the real-data
bench. It must find 0 differences. No app module imports
`backtest/engines/reference`. See
[docs/research-workflow.md](docs/research-workflow.md#development-check).

## Project layout

Documented commands live in `scripts/`. Financial policy, screening, calendars
and portfolio results live in `backtest/`; `backtest/paths.py` resolves paths.
Operational tools are in `tools/ops/`; `tools/experiments/` keeps the FMP API
probes. `results/` holds the frozen January record and small cited experiment
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

**Research database.** `scripts/research.py prepare` builds
`data/research.sqlite` from the raw cache: companies,
annual reports and typed facts, no book. Every build is a full build. It
writes a temporary file and replaces the database atomically; a failure keeps
the previous database. `books.Screen.decide` admits; `books.book` builds books.
`research.code_sources(role)` is the one rule of code roles: the research
identity binds fact-row code, the book identity book code, readers nothing.
The `legacy` pool keeps the original
250-candidate pre-price screen; the `cached` pool covers cached-price companies
only. Checks:
`tests/test_research.py`, `tests/test_prepared_facts.py`, `tests/test_books.py` and
`tests/test_research_inventory.py`. See
[docs/research-workflow.md](docs/research-workflow.md).

**Website screening.** `website/rendering/data.py` embeds the latest screen of
both prepared pools. `website/browser/screener.js` must match
`screening.latest()` in both pools. Latest mode uses the latest cached SPY
session, an exact-session adjusted price and cached `listed=True`. It never
reuses stopped prices and stores no future return. Every other test is a dated
backtest on the local service; there is no January mode. A January request is
refused at `/mode`, never converted. Saved January results (versions 1–2) open
in the dated view: `ResultArtifacts.decode` projects their book years into
periods at read time and never rewrites the record. Show short or empty
periods. Do not calculate a full-period CAGR when any period is empty. Top
contributors are the first `min(10, selected count)` stocks by signed
contribution, ties by symbol. Gain and loss pies are normalized separately and
never show negative slices. Checks: `python3 tests/check_screener.py` after
building, `node tests/check-range.cjs`, `node tests/check-contributions.cjs`
and `node tests/check-result-artifacts.cjs`.

**Selection order.** `filter_first` is the default. `rank_first` takes the
inclusive rank range from the prepared pool before user filters, keeps original
ranks and adds no replacements. Equal weights use the survivor count. Each
dated period ranks independently. Preserve the order through jobs, the queue,
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
daily book store, attaching research read-only. It prepares only the
requested pool and records completion in `book_pools` with the rows. Dates anchor to the starting day, clamp month ends and roll forward
to SPY sessions; end marks roll back. Intervals are 1, 3, 6, 12 and 24 months.
Reuse `screening.select` and `metrics.evaluate`; never duplicate formulas. Label
dated period returns, not annual returns. The daily binding names the research
and book identities; it updates in place in one transaction and `books.kept`
keeps unaffected books. `book_store` owns every read of its tables. Latest and
scope roots read their stored book's owner lanes; other roots use the dated owner policy. Check
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

**Custom variables.** `backtest/variables/columns.py` evaluates formulas of
definition versions 1–3 and catalogs `/1`–`/3`, values only or explained, over the
typed facts of `backtest/inputs/facts.py` (research only; the daily cache does
not copy them). One code path computes the values and their explanations. The
parity harness on the bench is a development tool outside the repository. New
formulas use version 3 and catalog `/3`; old formulas need an explicit upgrade.
The language check, `definitions.require_program`, is the one formula gate. It
runs when a capture is restored, before readiness or financial input. The one
evaluator implements the whole language; a guard test in
`tests/test_parameter_admission.py` evaluates every operation, statistic and /3
parameter. Eager scalar execution and numerical sample preview are
unsupported. Derived `at` and `lookback` contexts use dated owner policy, even
at an equal date. Preserve the 32-definition closure ceiling and signed zero in
typed value columns. Original scalar operations hold inputs through
`backtest/inputs/operation_inputs.py`: one daily binding check at entry, one file
status per step, no row rescans. Checks: `tests/test_columns.py`,
`tests/test_parameter_admission.py`, `tests/test_prepared_facts.py`,
`tests/test_operation_inputs.py` and heavy `tests/test_original_long_window.py`.
See
[variable design](docs/plans/custom-variables/variable-design.md) and the
[parameter catalog](docs/plans/custom-variables/parameter-catalog.md).
