# Parallel work on the website and backtest engine

The website can continue to develop while a separate worktree finishes the new
backtest engine. Keep financial behavior and engine interfaces stable on main.
Keep frontend and unrelated backend changes small at shared boundaries.

## Custom-variable branch

The linked `feature/custom-variables` worktree owns the custom-variable work. Its
scope, authorization and status are in `AGENTS.md`, section "Custom-variable work:
current state". The [engine-owner handoff](plans/custom-variables/engine-handoff.md)
states the notice needed at the next coordination point. It requests no engine
change.

To list every shared file this branch changes, run
`git diff --stat main...feature/custom-variables`. Treat each file that already
exists on `main` as a shared boundary. Keep those edits narrow, and agree the
owning branch before changing a calculation rule, engine interface, prepared
schema, freshness check or worker/lock ownership. Do not record per-phase
history here. The phase READMEs and git history hold it.

## Worktree ownership

For CB-19 and the project-structure program, the dated exceptions below assign
the specified engine work to `main`. The general ownership table governs other
tasks.

| Worktree | Branch | Work |
|---|---|---|
| `<wsl-checkout>` | `main` | Frontend presentation and backend features that preserve engine contracts |
| `<wsl-checkout>-cb02-input-ownership` | `cb02/input-ownership` | New backtest engine, input ownership, financial policy adapters, execution resources and qualification |

These paths identify the current machine. If a folder moves, use its registered
Git worktree and branch. Both worktrees share Git history. They have separate
working files and indexes. Use the index for the worktree that owns the change.

The engine branch's compiled-backtest plan and phase handoffs describe its
current work. Main's copy can lag that branch. Read the feature worktree's
records when checking an overlap. Do not copy its engine sources or rewrite its
plan on main to make the two trees appear synchronized.

## Choose the boundary before editing

The behavior being changed determines ownership. A filename alone does not.
The following map identifies the main areas to check.

| Area | Main-side boundary |
|---|---|
| Presentation: `website/browser/template.html`, CSS, `responsive.js`, labels, layout and result display | Continue UI work using existing request and result contracts. Preserve financial meaning, coverage warnings, missing values and exports. |
| Financial policy: `backtest/financial/rules.py`, `books.py`, `metrics.py`; `scripts/run.py`, `revalue.py`, `financial_inputs.py`; browser screening/return formulas | Coordinate before changing formulas, eligibility, ranking, dates, returns, exits, metrics, filters or numerical tolerances. Presentation edits in the same browser files can continue. |
| Execution: `backtest/engines/original/schedules.py`, `backtest/engines/original/book_batch.py`, `backtest/engines/original/robustness.py` | Engine-owned. Coordinate changes to planning, calculation, result saving, worker startup, cancellation or progress semantics. |
| Prepared inputs and evidence: `backtest/inputs/research.py`, `backtest/inputs/baseline.py`, `backtest/inputs/cache_assets.py`, `backtest/runtime/cache_access.py`; `backtest/paths.py` | Engine-related contracts are protected. Coordinate changes to schemas, report binding, freshness, paths, cache publication, locking or prepared-input semantics. |
| Shared service/build edges: `website/server/app.py`, `website/server/data_manager.py`, `website/rendering/data.py`, `website/build.py`, `website/rendering/state.py`; `backtest/inputs/fmp_download.py` | Unrelated backend work can continue with narrow edits. Coordinate changes to engine calls, preparation, data publication, embedded datasets, configuration, response fields or error/progress contracts. |
| Startup and deployment: `website/serve.py`, `website/server/launcher.py`, `website/runtime_access.py`, `tools/deploy.py`, Windows launch scripts | Coordinate changes to source/cache ownership, dependency setup, process lifetime, publication recovery, revision selection or default engine selection. |
| Browser/API edges: `website/browser/schedule.js`, `robustness.js`, `range.js`, `screener.js`, holdings and export adapters | UI work can continue. Keep request fields, defaults, units, sampled dates, result shapes, selected-stock evidence and saved-result compatibility stable. |
| Benchmark engine: `tools/experiments/bench_*.py`, `tests/test_bench_*.py`, `docs/plans/compiled-backtest/` | Develop on the engine branch. Preserve its admission gates, evidence and historical measurements. Future engine modules fall under the same boundary. |
| Tests and documentation for the areas above | Follow the contract being tested or described. Do not weaken tests or alter engine documentation on main to bypass an overlap. |

Do not freeze every backend file. A new endpoint or helper that is independent
of engine contracts can be developed on main. Avoid moving existing engine code
to support it. In a shared file, edit the relevant function or route. Do not
reformat the file, reorder unrelated code or rename shared symbols as cleanup.

Examples:

- A new chart layout can use existing holding returns and contribution values.
- An unrelated settings endpoint can preserve the calculation routes and payloads.
- A new ranking metric, changed rebalance rule or prepared-table migration needs
  coordination with the engine worktree.
- A progress-label edit can keep the existing event fields and completion units.

## Handle an overlap

1. Read both worktrees' relevant files and the engine branch's current handoff.
   Compare the actual branch changes. Do not rely only on this file map.
2. State which contract must change. Include affected files, callers, tests and
   the old/new request, result or data shape when applicable.
3. Agree one owning branch and a narrow scope before editing the overlapping
   part. Use an existing task or handoff agreement when it covers the change.
   Ask the user only when the ownership or interface decision is unresolved.
4. Keep the implementation and its tests/docs together on that branch. Give the
   other branch the commit and compatibility notes. Integrate deliberately when
   needed; this note does not authorize an automatic merge or cherry-pick.
5. Continue work that does not depend on the unresolved overlap. Before eventual
   integration, check contract compatibility as well as textual merge conflicts.

This process applies to bug fixes too. A small diff can still change a financial
rule or invalidate prepared inputs. Do not silently duplicate a fix on both
branches or change the investment rules to resolve a merge.

## Keep the normal runtime separate

The native Windows runtime remains `<windows-runtime>`. Main is the
registered deployment source. The engine worktree is not a deployment source.
Follow [workspaces.md](workspaces.md) for publication and recovery. A source
commit does not change the installed revision or start a server.

Keep stable raw files, prepared databases, report/history, saved books/settings,
environments and local builds under their existing ownership. Engine experiments
use their own qualified assets. Do not repoint registration or the normal
launcher to the feature worktree. Do not clear stable books for a test.

Benchmark admission remains closed. This coordination note grants no execution,
deployment, server stop/restart, market-data download or production cutover.
Existing unrelated working-tree edits remain outside each task's commit.

## Custom-variable plan on hold — 30 October 2026

The user put the custom-variable plan on hold until the new engine is finished.
Phase 1 delivered contracts only. Phase 2 has inspection and preliminary design,
with no provider implementation. Phases 2–7 must wait. This feature adds no new
prerequisite to the current engine swap. Its proposed engine-branch assignment
remains unapproved and is deferred during the hold.

See the [master plan's hold and resume conditions](plans/custom-variables/master-plan.md#hold-and-resume).
After engine completion, recheck the actual interfaces and agree ownership and
narrow scope before protected edits. The earlier provider proposal does not
authorize work during the hold. Unrelated work retains the existing boundaries.

The [engine-owner handoff](plans/custom-variables/engine-handoff.md) records the
code and remaining-plan impact. It is a coordination notice, not a request to
extend the engine now. Committing main-side notes does not update the engine
worktree's local files or notify its session. Have its owner read the handoff
at the next coordination point. Existing main feature integration obligations
remain separate from this held proposal.

## Agreed direction: selectable engines (31 October 2026)

The user approves an opt-in engine choice in the normal app. Original remains
the default. The engine branch owns this integration through the existing
calculation, job, queue and immutable-result boundaries. Submitted runs must
retain their engine through retries and recovery. Unsupported experimental
settings must fail explicitly without changing settings or silently falling back.

Before implementation, reconcile current main's schema-8 preparation,
operating-yield-spread filter and selection order. Preserve Original's existing
behavior. Main's held custom-variable work adds no prerequisite. Inspect both
worktrees and main's automatic deployment/restart behavior before deliberate
integration; do not publish an unfinished selector as a side effect.

The [current release plan](plans/compiled-backtest/phases/CB-14.opt-in-release.md)
replaces the requirement to finish all large stress cases before normal-app
opt-in integration. Those cases keep their historical verdicts and restrictions.
This plan-only update performs no merge, publication, restart or installed write.

## CB-14 readiness reconciliation (31 October 2026)

The engine branch ports the financial/request contract from main `18f40ad`
without moving main or importing its deployment supervisor. Original retains
schema 8, operating yield spread and both selection orders. The experimental
policy rejects operating yield spread explicitly. Both orders use shared SQL.
Candidate application calls now close their runtime before publishing outcomes.
This releases financial ownership between calls. Disk checkpoints remain reusable.
See the [readiness record](plans/compiled-backtest/phases/CB-14.readiness.md).

CB-15 owns the normal-app selector, per-submission identity, producer labels and
release. Main's `29a7e3e` supervisor can publish a newly committed main revision
automatically. Inspect that behavior before future integration. This readiness
work changes no default or installed revision. Main's unrelated working edits
remain untouched.

## Agreed exception: website run controls (26 October 2026)

The user assigned main the narrow cancellation change for manual website runs.
Main owns the auto-run toggle, Stop control and notices for changed settings.
A request-local cancellation check observes a browser disconnect in
`website/serve_app.py`. `scripts/backtest_control.py` supplies optional checks in
`scripts/schedules.py` and `scripts/book_batch.py`. Standalone callers keep their
existing interfaces. Financial formulas, request fields, result shapes, saved
books and lock ordering stay the same. In-flight workers finish under the
existing cleanup before cache ownership ends. The engine branch can integrate
these checks deliberately with its replacement engine.

The user's follow-up assigns main the server-owned run adapter. New
`website/backtest_jobs.py` and `website/backtest-runs.js` separate browser
connections from job lifetime. `/api/backtest-runs/<id>` adds submission,
status/result and explicit Stop actions. Existing `/api/schedule` and
`/api/robustness` contracts remain unchanged. The adapter calls the existing
engine functions and optional cancellation context. It changes no engine
formula, worker, transaction, progress field or cache lock. A narrow
`Server.server_close()` hook stops and joins these threads before existing
lifetime ownership ends. Main owns this adapter, its browser integration and
tests. The engine branch can integrate it deliberately with the earlier checks.
The additive `/api/backtest-runs/<id>/status` route omits holdings while browser
recovery checks current server status across saved run IDs. Full result retrieval
keeps the original run route and payload. Admission and Stop markers stay in the
browser transport module; views do not select the submission operation.

The user's overnight-queue extension is also owned by main's website adapter.
`website/backtest_queue.py` adds durable queue records and consumer ownership;
`website/queue.js` and its HTML/CSS add management controls. The additive
`/api/backtest-queue` routes manage order, held edits, pause, Stop and stored
results. The existing website engine call is extracted into
`backtest_jobs.calculate`; the queue reuses it and may replay a previously
recorded random plan. Engine functions, transaction rules, progress fields and
financial locks are unchanged. A narrow server-start hook resumes durable
work; shutdown joins the queue before existing source lifetime ownership ends.
No engine-branch files, prepared schemas or benchmark contracts change.

## Agreed exception: saved backtest results (26 October 2026)

The user assigned main the narrow adapter for saving random-trial stock details.
`scripts/robustness.py` adds an optional `capture(number, result)` observer after
an ordinary completed trial. Calculations, dates, progress and saved-book
transactions stay unchanged. Existing callers keep the summary-only result.
The original streaming adapter uses `X-Backtest-Details: holdings` to add ordered
`trial_results` to `/api/robustness`. That opt-in remains available to existing
streaming clients. Current background jobs and queued random tests capture full
trial holdings directly through `backtest_jobs.calculate`. Each entry is the full
original trial result, including all holding periods and selected stock rows.
The browser can inspect these stocks without another calculation. The engine branch can
integrate this observer deliberately; no engine implementation is copied here.

The independent library uses `data/saved-backtests.sqlite`. It stores complete
user snapshots, capped atomically at 100 records. This durable file stays outside
financial-cache freshness and rebuilds. Source deployment preserves it.

## Agreed exception: operating-yield spread filter (29 October 2026)

The user assigns main this narrow financial-filter addition. Main owns the new
`operating_yield_spread_3y` threshold field, its input preparation, tests and
website explanations. The formula uses selected annual revenue multiplied by
the simple mean of operating income/revenue for three consecutive fiscal years,
divided by screen-date EV. Subtract the latest cached US 10-year Treasury yield
on or before the screen date. The threshold uses percentage points.

`scripts/financial_inputs.py` adds `operatingIncome` to eligible saved annual
inputs. `scripts/metrics.py` owns the formula and catalog entry. Research schema
8 adds a `treasury10(day, yield_percent)` table from saved `year10` fields.
`scripts/research.py` and `scripts/schedules.py` supply that input to the shared
filter calculator. Both pools and all modes use the same formula. Existing
filter request/result shapes, ranking, 3-month spreads, returns, cache ownership
and benchmark code stay unchanged. Source changes trigger offline preparation
and a website rebuild. Missing inputs omit the new value and exclude a stock
only when that filter is active. There is no automatic market-data download.

The engine branch can integrate this additive policy deliberately. Its numerical
input adapters and qualification evidence must account for the new field before
claiming support. Main does not change that branch or its benchmark contracts.

## Agreed follow-up: selection order (29 October 2026)

The user extends the main-owned filter work with a choice of selection order.
Main owns the additive `selection_order` option and its SQL/browser selection,
website control, saved-record compatibility, tests and documentation. Omission
means `filter_first`. `rank_first` ranks the prepared pool, selects the inclusive
requested range, then applies all user conditions without replacements. It keeps
original ranks and equally weights survivors. Pool eligibility, metric formulas,
tie policy, prepared schemas, worker ownership and cache locks do not change.

`scripts/research.py` owns SQL policy and CLI validation. The only execution-edge
change is accepting the option in `scripts/schedules.py`; existing generic
options carry it through random plans, jobs and queue records. The website
selector, form and immutable-artifact comparison carry the same default. Old
saved records remain unchanged. Queue edit comparison treats an omitted order
as filter-first, so a name-only edit retains an older random plan. An actual
order change discards that waiting plan. The engine branch must integrate this option
deliberately before claiming it supports the new policy. No engine-branch or
benchmark files are changed by this task.

## Agreed follow-up: automatic main updates (29 October 2026)

The user requests automatic server restart and latest-version installation when
an update exists. Main owns this launcher/publication policy change. Ordinary
`--start` watches committed main; an explicit revision remains fixed. Standalone
publication and `--check` retain their installed-revision defaults. This replaces
the earlier fixed default for ordinary server launches. It does not authorize
benchmark admission or an unqualified engine merge into main.

`tools/deploy.py` owns the watch loop, exact revision selection, pending recovery,
staging and native child lifecycle. A narrow pre-publication callback asks only
its child to exit after the archive is ready. `website/serve.py` observes the
launch's private stop marker before preparation. Its existing source ownership
still precedes application imports and lasts through shutdown. Worker/cache
contracts and the engine branch remain unchanged. Tests use disposable Git
repositories and native runtime fixtures. Raw data, databases, reports and the
two unrelated snapshot edits retain their current owners.

## CB-15 normal-app source integration (31 October 2026)

The engine branch implements per-submission selection through the existing
calculation, job, queue and immutable-result boundaries. Original stays default.
Numerical preparation is an explicit optional data-panel action. Main remains
unchanged. This source commit does not authorize integration, publication,
push or restart. Read the [release handoff](plans/compiled-backtest/phases/CB-15.release-handoff.md)
before moving main; its automatic supervisor can deploy a new main commit.

## Authorized CB-15 main integration — 31 October 2026

The user authorized integration after the CB-15 source handoff. Resolution and
verification use the isolated `cb15/main-integration` branch, based on main
`d877cb4`, with engine parent `0cb9a0b`. The four shared code conflicts retain
the qualified engine contracts. Main's automatic supervisor and native source
bootstrap remain. The architecture guide combines both behaviors.

Publication, deployment, push and installed restart remain outside this task.
Before advancing main, check that no automatic publication supervisor is active.
Recheck main's commit and preserve its unrelated snapshot and market-scope files
byte for byte. No installed library or queue inspection is authorized. Custom
variables remain on hold; the integration owner acknowledged their handoff.
See the [integration record](plans/compiled-backtest/phases/CB-15.integration.md).

## Operating-spread support follow-up — 31 October 2026

The user assigns the engine branch the missing experimental
`operating_yield_spread_3y` implementation. Scope includes source-derived annual
specialization, immutable dated Treasury inputs, numerical factors/books,
capability and recovery checks, current documentation and the architecture guide.
Original's formulas, user settings, result formats and ownership stay unchanged.
The earlier CB-14/CB-15 rejection remains historical evidence. Current support
requires a new prepared numerical generation. See the
[implementation record](plans/compiled-backtest/phases/CB-16.operating-spread.md).
This work does not authorize moving main, deployment, restart, downloads or
bypassing closed real-benchmark admission. The exact seeded 100-trial comparison
is recorded separately from synthetic correctness. Custom variables stay held.


## Website alignment follow-up — 31 October 2026

The user assigns the engine branch clear separation and parity across website
workflows. CB-18 owns separate Original/experimental execution adapters, shared
calendar requests, both-engine week/month support, browser engine controls and
workflow parity checks. Latest/January stay shared prepared-data views. Saved
result readers remain engine-neutral and preserve original evidence. Main's
snapshot and market-qualification edits remain outside this work. No main
advance, publication, restart or provider download is part of this task.
See the [alignment record](plans/compiled-backtest/phases/CB-18.website-alignment.md).

## CB-19 parallel engine ownership exception — 1 November 2026

The user explicitly authorizes direct work and coherent audited commits on
`main` for [CB-19A–CB-19G](plans/parallel-backtest/master-plan.md). This task
agreement assigns main the generation attachment, complete trial evaluator,
persistent trial pool, checkpoint coordinator, experimental application wiring,
complete Rust candidate, scoped comparison and selected-backend qualification.
It supersedes the general engine-worktree-only rule for this program. Preserve
the other worktree and its history. Keep shared changes narrow and preserve
financial rules, Original as default and durable evidence.

The user requests autonomous progress with a GPT-6.1-sol high implementation
agent and a separate GPT-6.1-sol high commit agent for each slice. Each code
slice first obtains its detailed design from the skill's independent planner.
The separate commit agent applies the independent smart-commit audit. Scope and
finish criteria are recorded in the new plan. All seven slices are pending in
this documentation record.

The user expressly reopens complete Python/Numba versus Rust comparison within
CB-19. Scoped private synthetic experiments and qualified copied-input
comparisons are authorized. Declare exact assets, source/generation bindings,
resources and cleanup ownership before execution. Use the current application
lifetime owner. Do not modify closed historical benchmark admission or run its
live-cache-locking route. A copied path alone establishes no current binding.

The WSL checkout owns edits and commits. The native Windows runtime remains
separate. No deployment, restart, downloads, stable-cache mutation or default
replacement is part of CB-19. Check for an automatic publication supervisor
immediately before every main commit; do not assume an earlier absent process
stays absent. Preserve unrelated portable-snapshot and market-qualification
files. Custom-variable work remains on hold.

## Saved-library usability follow-up — 1 November 2026

The user assigns main the saved-library and queue presentation improvements.
The three slices cover library management, recoverable completion transfer, and
two-result comparison. Main owns these existing adapters and their additive
library APIs. Preserve calculation, request/result, engine, worker and financial
ownership contracts. The first slice raises the library to 100 slots, exposes
existing UUIDs, adds metadata-only rename and stored-performance sorting, and
bounds queue/library scrolling. The second slice adds recoverable completion
transfer between the existing durable stores. Queue reservations fence deletion.
The saved store commits its import receipt and complete copy before archival
releases duplicate queue evidence. Engine and financial ownership stay unchanged.
The third slice projects stored settings/summaries in a pure browser comparison
module. Existing eager/evidence readers load the two selected saved IDs. No
engine call, result publication, form restoration or financial schema changes.
Saved-row All parameters disclosures reuse this projection and its existing
reader cleanup. They add no server or engine contract.
Existing unrelated snapshot and market-scope
files stay outside these commits. See the [master plan](plans/backtest-library/master-plan.md).


## Project-structure ownership exception — 1 November 2026

The user authorizes `main` to implement the four phases in the
[project-structure plan](plans/project-structure/master-plan.md). This narrow
exception covers package ownership, import migration, source identities and
required application/presentation boundaries. Preserve financial behavior,
Original as default, source-before-import ownership and durable evidence.
The engine worktree remains untouched. No synchronization or automatic merge
is authorized. Custom variables remain on hold.

Phase 1 assigns shared configuration, book policy and metrics to
`backtest/financial/`. `backtest/screening.py` owns validation and SQL selection.
Shared calendars, requests, portfolio results and paths have one package owner.
SQL metric population remains in research preparation until Phase 2. Source
moves invalidate rebuildable identities where required. User records and
historical measurements remain unchanged. Preserve closed benchmark admission.

Each phase receives independent design, implementation, independent audit and
one coherent commit. Check both process namespaces for automatic publication
supervisors immediately before committing. Deployment, server restart,
downloads and real-cache preparation remain outside this program.

Phase 4 places browser sources in `website/browser/`, rendering in
`website/rendering/` and HTTP composition in `website/server/`. Maintained
operations live in `tools/ops/`; retained experiments live in
`tools/experiments/`. Documented executable paths remain. Read the
[current source map](plans/project-structure/source-map.md) when interpreting
historical paths above. No engine-worktree synchronization is authorized.
