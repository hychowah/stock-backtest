# Parallel work on the website and backtest engine

## Custom-variable continuation planning — 3 November 2026

The user requested and authorized committing the
[parameter expansion and integration plan](plans/custom-variables/parameter-expansion-plan-2026-11-03.md).
Phases 1–7 are complete only for the initial four-observation scope. Planned
Phases 8–12 cover the 52 direct inputs, named measures, authoring/coverage and
integration qualification. This is a documentation-only task on
`feature/custom-variables`. It authorizes no protected implementation, main
advance, engine-worktree edit, deployment, restart, download or live data change.
At implementation resumption, record the phase's narrow financial, preparation,
provider, application and numerical ownership before editing affected contracts.
Recheck branch state and the automatic main supervisor before any later merge.

The website can continue to develop while a separate worktree finishes the new
backtest engine. Keep financial behavior and engine interfaces stable on main.
Keep frontend and unrelated backend changes small at shared boundaries.

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

This dated hold is superseded for Phases 2–4 by their 2 November agreements below.

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

## Custom-variable Phase 2 resumption — 2 November 2026

The user assigns Phase 2 to the linked `feature/custom-variables` worktree.
Its protected scope is annual field evidence, prepared latest-root admission,
the research/daily/immutable-generation adapters, and the initial point-in-time
provider. The provider covers only revenue, operating income, operating margin
and enterprise value. The [current execution plan](plans/custom-variables/phases/phase-02/execution-plan-2026-11-02.md)
supersedes the old proposed engine-branch assignment for this phase.

CB-14/CB-15 now record complete supported opt-in readiness and selection.
Original remains default. Default replacement is no longer a resumption gate.
The user requests an independent planner, implementation and independent
smart-commit for each of two substantial slices. Existing entry valuation and
its numerical source adapter are reused. Financial rules, ranking pairs,
selection defaults, saved evidence and ownership ordering remain unchanged.

Slice 1 is committed as `cc60a0c`. Slice 2 adds the four-parameter provider and
source-owned historical root admission. It uses the complete immutable
population before cached membership. The user also permits implementation-plan
adjustments while preserving the core function. The current slice record
explains the bounded company-read adjustment and its tests. This second audited
implementation commit completes Phase 2 in source. The current phase record
contains its verification and independent audit outcomes.

Phases 3–7 remain held. No branch integration, publication, restart, download,
installed-cache preparation or durable-store mutation is authorized. Preserve
main and engine worktree files and indexes. This branch is not a deployment
source. Its current source and fixture checks do not change the running server.


## Custom-variable Phase 3 resumption — 2 November 2026

The user authorizes Phase 3 implementation and audited commits in the linked
`feature/custom-variables` worktree, starting at `9e5d97d`. Phase 2 is complete.
This task owns `backtest/variables/`, evaluator tests and affected current records
and architecture-guide explanations. The [execution plan](plans/custom-variables/phases/phase-03/execution-plan-2026-11-02.md)
uses two substantial slices: immutable validated formula programs, then bounded
provider-backed reference execution. Each receives independent design,
implementation and a separate smart-commit audit. Material adjustments are
recorded in the phase.

The evaluator consumes the existing four-parameter observation provider. It must
not read raw assets/SQL or reproduce root admission, report selection, annual
alignment or enterprise value. Financial rules, root membership/ranks, existing
engines, freshness, cancellation, attachment lifetime and detached evidence stay
with their current owners. Original remains default. Phases 4–7 remain held.

Private source exports and synthetic WSL/native verification are authorized.
No merge, push, deployment, server restart, market-data request or live-runtime/
cache mutation is authorized. Native-cache coverage remains unknown. Preserve
main and the engine worktree, including their files, indexes and histories.

Phase 3 Slice 1 is committed as `d23cfa2`. Slice 2 implements bounded reference
execution over its public program projection and the unchanged provider.
The narrow definition-owner addition binds loaded language source. Plans and
blocks have separate namespaced formats; no strategy, artifact, prepared schema
or engine interface changes. The [Phase 4 handoff](plans/custom-variables/phases/phase-03/handoffs/phase-04.md)
records the actual scalar block and leaves selection held. Final Slice 2 native
verification and independent audit remain in its phase record. This source
capability does not change the running server or establish native-cache coverage.


## Custom-variable Phase 4 resumption — 2 November 2026

The user authorizes Phase 4 implementation and audited commits on
`feature/custom-variables`, starting at `6f39f0e`. This branch owns the narrow
selection and legacy-adapter changes. The [execution plan](plans/custom-variables/phases/phase-04/execution-plan-2026-11-02.md)
reconciles the Phase 1 proposal with current SQL/browser/application interfaces.

Slice 1 adds `backtest/selection.py` and `backtest/variables/selection.py`, plus a
public language-owner threshold conversion helper. It consumes public evaluator
and provider evidence. The provider keeps complete-population admission and
legacy's top-250 buffer. This slice changes no SQL/browser caller or financial
policy. Slice 2 owns narrow explicit adapters in current selection boundaries
and explicit unsupported experimental-formula rejection. Original remains default.

No prepared schema, dates, prices, exits, returns, financial/cache ownership,
attachment lifetime, durable user record or engine default changes. The callable
selection formats are namespaced independently of application artifacts.
Phases 5–7 remain held. No merge, push, deployment, restart, market-data request
or live-runtime/cache mutation is authorized. Private synthetic Windows checks
are permitted. Native-cache coverage remains unknown.

Phase 4 Slice 2 starts from audited `6561a56`. Its narrow overlap also includes
adding `backtest/selection.py` to existing research and numerical source
fingerprints. This preserves freshness after selection delegates to that source.
The numerical policy owner rejects formula-bearing requests explicitly; it adds
no formula execution, schema or application-artifact change. The current
execution plan records affected owners before implementation.


## Custom-variable Phase 5 resumption — 2 November 2026

The user authorizes implementation and audited commits from `f893bd4` on
`feature/custom-variables`. This branch owns a separate durable variable library
in `backtest/variables/library.py`, narrow lookup resolution in the existing
definition owner, and supporting tests/docs. The
[execution plan](plans/custom-variables/phases/phase-05/execution-plan-2026-11-02.md)
records the two independently planned and audited slices.

The new `data/variable-library.sqlite` is durable user data. It is separate from
financial caches, the queue and saved results. Existing files and records stay
unchanged. No financial/provider/selection policy, prepared schema, application
request/result, source/cache ownership, cancellation or attachment contract changes.
No editor, strategy integration or numerical formula execution is authorized.
Original remains default. Phases 6–7 stay held.

Use private synthetic WSL and Windows fixtures only. No merge, push, deployment,
server restart, market-data request or live-runtime/cache/durable-store mutation.
Native-cache coverage remains unknown. Main and engine worktrees stay untouched.

Phase 5 Slice 2 starts from audited `5892a55`. Its narrow library-owner change
captures a complete checked program and presentation in one existing read
transaction. It adds no durable schema, application request/result, financial,
source/cache ownership or attachment-lifetime change. Formula integration with
jobs, queue, StrategyDraft and saved results remains Phase 6 work on hold.


## Custom-variable Phase 6 resumption — 2 November 2026

The user authorizes Phase 6 implementation and independently audited commits
from `f877c0c` on `feature/custom-variables`. This branch owns the narrow
application/UI/persistence integration recorded in its
[execution plan](plans/custom-variables/phases/phase-06/execution-plan-2026-11-02.md).
Current package owners and Phase 5 handoffs supersede Phase 1 payload proposals.

Slice 1 owns callable captured strategy intent in
`backtest/application/strategy_requests.py` and a narrow submitted-only capture
entry in the existing library owner. It changes no ordinary route, job, queue,
calculation, result format or financial policy. Legacy options remain unchanged.
Later slices need fresh independent designs against preceding committed source
before execution/evidence and editor contracts change. This assignment covers
those narrow application/UI/persistence edges; it does not broaden financial
rules, provider capabilities, freshness, cancellation, ownership ordering,
attachment lifetimes or execution resources. Original remains default.

Phase 7 numerical formulas stay held. Main and the engine worktree retain their
files, indexes and history. The feature worktree is not a deployment source.
Only private synthetic WSL/browser/Windows fixtures are authorized. No merge,
push, deployment, server restart, market-data request or live-runtime/cache/
durable-store mutation is permitted. Native-cache coverage remains unknown.

## Custom-variable Phase 6 Slice 2 integration — 2 November 2026

Phase 6 Slice 2 starts from independently audited `de14704`. The fresh design
assigns this feature branch the narrow Original selected-book seams, borrowed
SQLite observation adapter, scalar executor, additive contract/codec dispatch and
application job/queue/result integration. `daily.prepared_report()` extracts the
existing decoder for lazy observation reads; financial pool policy is unchanged.
The [current compatibility record](plans/custom-variables/phases/phase-06/compatibility.md)
describes application artifact 4 / codec 2 and old-reader preservation. No worker,
financial rule, provider capability, schema, ownership or resource policy changes.
The shared editor is Slice 3. Phase 7 numerical formulas remain held.


## Custom-variable Phase 6 completion — 2 November 2026

Phase 6 completes in source on `feature/custom-variables` in three independently
planned, implemented and audited slices. Slice 3 starts from audited `9978ea7`.
It adds the shared editor/picker, exact authoring snapshots, StrategyDraft capture
and bounded detached presentation. The definition owner supplies editable raw
projections. Editor and draft share exact authored/label packing; canonical
restoration remains checked through its existing owners. All six audit findings
and the shared-dependency follow-up are fixed. The
[current phase record](plans/custom-variables/phases/phase-06/README.md) retains
536 WSL tests, 446 private native tests, 18 source-bound browser checks, actual
keyboard/mobile/held-draft/export review and complete cleanup receipts.

No financial/provider, prepared-schema, freshness, cancellation, worker,
ownership-ordering, attachment-lifetime or execution-resource contract changes.
Original remains default. Existing requests, queue records and saved results are
not rewritten. Phase 7 numerical formula execution remains held. Main, the engine
worktree and installed runtime/cache are untouched. This source completion grants
no merge, push, deployment, restart, download or live durable-store mutation.
Native-cache coverage remains unknown.


## Custom-variable Phase 7 resumption — 2 November 2026

The user assigns `feature/custom-variables` narrow Phase 7 implementation and
integration from `5cded92`. The engine worktree is read-only and clean at
`8850e77`; its older scripts layout is not copied. Current feature packages,
CB-19 execution and Phase 2 observation contracts govern implementation.
The [execution plan](plans/custom-variables/phases/phase-07/execution-plan-2026-11-02.md)
records three independently designed, implemented and audited slices.

Slice 1 owns shared evaluator planning/evidence, independent reference arithmetic
and bounded Numba formula arithmetic. Its narrow overlaps are the existing
reference public interface and compiler-environment identity. Variable selection,
scalar application execution/preview and numerical sessions/workers are the
affected callers. Financial/provider, prepared-schema, application routing,
worker/lock/attachment, durable-format and default contracts stay fixed. Both
public numerical scalar guards remain closed until later qualification. Later
slices need fresh designs against committed source before protected edits.

This dated assignment supersedes the Phase 7 hold on this branch. Original stays
default. Main, the engine worktree and installed runtime/cache/stores remain
untouched. Private synthetic verification grants no merge, push, publication,
restart, download or live durable mutation. Native-cache coverage is unknown.

## Custom-variable Phase 7 Slice 2 — 2 November 2026

The authorized feature branch starts from audited `0c75df8`. Its fresh independent
design owns narrow candidate scalar scope/execution integration, typed codec-2
trial/checkpoint recovery and explicit runtime dispatch. The current Phase 7
execution and compatibility records identify protected callers before edits.
Public numerical scalar admission remains closed. Original remains default.
Financial/provider rules, prepared schemas, worker/writer ownership, bootstrap
ordering, attachments and resource ceilings remain with their existing owners.
Main and the engine worktree remain untouched. No publication or live asset change
is authorized. Private synthetic verification does not establish native-cache
coverage.

Slice 2 implementation uses generation-owned checked current research borrowing
for latest/January and genuine numerical complete-book staging for dated scopes.
Compiled arithmetic sits below shared scalar selection. The existing typed
trial/pool/worker/checkpoint/runtime pipeline dispatches complete scalar codec 2
without a second recovery path. Recorded trial numbers qualify explanation IDs.
A complete checkpoint hit precedes formula/book/worker constructors. Existing
resource ceilings are split conservatively; financial/provider/schema/default
contracts stay unchanged. The feature branch owns these narrow source changes.
Other worktrees remain read-only. All six independent audit findings are closed.
Final source-bound verification passes 780 WSL tests plus one expected
Windows-only skip, 590 guarded native tests and 18 browser checks. The
[slice record](plans/custom-variables/phases/phase-07/slice-02.md) binds receipts
to the unchanged 394-file product/test inventory and complete private cleanup.
Public numerical scalar admission remains closed. Native-cache coverage is unknown.

The Slice 2 independent audit also assigns this feature branch a narrow queue
Stop-poll correction. `Store.stopped()` must read committed intent without
acquiring a second writer inside complete-evidence publication. Its callers are
the existing manual queue cancellation callback and publication checkpoint.
Publication uses the shutdown event as its scoped cancellation predicate. Its
transaction already owns the checked committed Stop row, and a cache spill can
block even a second read-only connection. Ordinary execution retains Stop polls.
The existing transactional stopping-row check, atomic completion precedence and
shutdown requeue retain their owners and behavior. The regression uses private
synthetic persistence only. No schema or durable-record rewrite is authorized.

## Custom-variable Phase 7 Slice 3 — 3 November 2026

The authorized feature branch starts from audited `719a724`. Its
[fresh independent design](plans/custom-variables/phases/phase-07/slice-03-design.md)
owns financial-free scalar capability admission, bounded-only numerical routing,
the explicit Original reference preview, shared engine controls and all-mode
draft intent. Existing routes, jobs, queue, runtime and browser restoration are
the protected callers. Qualification uses their current lifetimes and complete
evidence; it adds no parallel application route. Numerical execution is opt-in.
Original remains default. The initial guarded native containment probe precedes
public admission changes.

Test-only entry translation retains the unchanged native guard. It qualifies
real private entry logic under translated launch syntax, not literal production
commands or native HTTP/browser operation. Financial/provider rules, prepared
schemas, resources, worker/writer ownership, source/cache order and durable
formats are unchanged. Other worktrees remain read-only. No publication or live
asset mutation is authorized. Native-cache coverage remains unknown.

Slice 3 qualification demonstrates dense worker cancellation-file polling.
The [fresh independent amendment](plans/custom-variables/phases/phase-07/slice-03-cancellation-design.md)
assigns only the worker control observer to this feature branch. The existing
approximately 50 ms parent wait also observes the terminal marker. Calculation
checkpoints read latched memory state and surface observer failures. Marker
cancellation keeps parent-loss terminal protection; observer join remains inside
source ownership. The pool marker/close protocol, shared checkpoints, financial
owners, resources, runtime-child controls and native guard remain unchanged.
The corrected-source gate passes 24 WSL and 17 guarded native cases. Supported
bounded numerical scalar execution is now exposed in Latest, January, fixed
and random modes. A financial-free declaration, the shared selector and existing
StrategyDraft preserve checked intent and the explicit engine choice. Eager
scalar execution and numerical sample preview remain unsupported. Preview names
Original explicitly. Independent audit, actual desktop/mobile browser and guide
review, final source-bound verification and private workload qualification pass.
Phase 7 is complete in source. Other worktrees remain untouched. Native-cache
coverage remains unknown.
