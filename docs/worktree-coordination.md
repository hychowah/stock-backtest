# Parallel work on the website and backtest engine

The website can continue to develop while a separate worktree finishes the new
backtest engine. Keep financial behavior and engine interfaces stable on main.
Keep frontend and unrelated backend changes small at shared boundaries.

## Worktree ownership

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
| Presentation: `website/template.html`, CSS, `responsive.js`, labels, layout and result display | Continue UI work using existing request and result contracts. Preserve financial meaning, coverage warnings, missing values and exports. |
| Financial policy: `scripts/books.py`, `metrics.py`, `run.py`, `revalue.py`, `financial_inputs.py`; browser screening/return formulas | Coordinate before changing formulas, eligibility, ranking, dates, returns, exits, metrics, filters or numerical tolerances. Presentation edits in the same browser files can continue. |
| Execution: `scripts/schedules.py`, `book_batch.py`, `robustness.py` | Engine-owned. Coordinate changes to planning, calculation, result saving, worker startup, cancellation or progress semantics. |
| Prepared inputs and evidence: `scripts/research.py`, `baseline.py`, `cache_assets.py`, `cache_access.py`, `paths.py` | Engine-related contracts are protected. Coordinate changes to schemas, report binding, freshness, paths, cache publication, locking or prepared-input semantics. |
| Shared service/build edges: `website/serve_app.py`, `data_manager.py`, `dataset.py`, `build.py`, `build_state.py`; `scripts/fmp_download.py` | Unrelated backend work can continue with narrow edits. Coordinate changes to engine calls, preparation, data publication, embedded datasets, configuration, response fields or error/progress contracts. |
| Startup and deployment: `website/serve.py`, `launcher.py`, `runtime_access.py`, `tools/deploy.py`, Windows launch scripts | Coordinate changes to source/cache ownership, dependency setup, process lifetime, publication recovery, revision selection or default engine selection. |
| Browser/API edges: `website/schedule.js`, `robustness.js`, `range.js`, `screener.js`, holdings and export adapters | UI work can continue. Keep request fields, defaults, units, sampled dates, result shapes, selected-stock evidence and saved-result compatibility stable. |
| Benchmark engine: `tools/bench_*.py`, `tests/test_bench_*.py`, `docs/plans/compiled-backtest/` | Develop on the engine branch. Preserve its admission gates, evidence and historical measurements. Future engine modules fall under the same boundary. |
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

## Agreed exception: saved backtest results (26 October 2026)

The user assigned main the narrow adapter for saving random-trial stock details.
`scripts/robustness.py` adds an optional `capture(number, result)` observer after
an ordinary completed trial. Calculations, dates, progress and saved-book
transactions stay unchanged. Existing callers keep the summary-only result.
The website requests `X-Backtest-Details: holdings`; only that opt-in adds ordered
`trial_results` to the completed HTTP result. Each entry is the full original
trial result, including all holding periods and selected stock rows. The browser
can inspect these stocks without another calculation. The engine branch can
integrate this observer deliberately; no engine implementation is copied here.

The independent library uses `data/saved-backtests.sqlite`. It stores complete
user snapshots, capped atomically at 20 records. This durable file stays outside
financial-cache freshness and rebuilds. Source deployment preserves it.
