# Current source owners

Updated for Phase 5 Slice 1. This map describes source after the structure refactor.
Historical designs, measurements and captured artifacts retain their original
paths and source hashes. The engine worktree has not been synchronized.

| Concern | Current owner |
|---|---|
| Financial rules, dated entry valuation, holding outcomes and built-in metric calculations | `backtest/financial/` |
| Validation, explicit legacy translation and SQL selection over stored built-in pairs/filter values | `backtest/screening.py` |
| Shared calendar requests and portfolio result reduction | `backtest/calendar.py`, `calendar_requests.py`, `portfolio_results.py` |
| Full annual responses, fiscal histories, cache receipts and prepared inputs | `backtest/inputs/` |
| Original dated calculations and retained independent reference | `backtest/engines/original/`, `backtest/engines/reference/` |
| Source-derived numerical calculation and immutable input attachments | `backtest/engines/numerical/` |
| Cache access, process ownership, cancellation and diagnostics | `backtest/runtime/` |
| Calculation requests, captured settings, jobs, queue, saved-backtest library and immutable result acquisition | `backtest/application/` |
| Strategy draft, saved restoration, held queue edits and immutable browser views | `website/browser/range.js`, `result-artifacts.js`, `saved-backtests.js`, `queue.js` |
| Durable variable revisions, metadata and exact formula resolution | `backtest/variables/library.py`, `backtest/variables/definitions.py` |
| Plain browser assets and standalone HTML fragments | `website/browser/` |
| Detached database projections, static rendering, assets, exports and freshness | `website/rendering/` |
| Server lifetime and grouped calculation, stored-result and data HTTP adapters | `website/server/` |
| Stable build command and source-owning startup entries | `website/build.py`, `serve.py`, `serve_candidate.py`, `runtime_access.py` |
| Maintained operational implementations | `tools/ops/` |
| Retained benchmarks, API probes and historical experiments | `tools/experiments/` |
| Documented executable commands | `scripts/`, retained thin `tools/*.py` entries, Windows command files |

No production backtest library imports website or tools. Website code calls the
actual application and input owners. Package initializers execute no operations.
Remaining old executable paths do not serve as library import aliases.

## Custom-variable provider and reference evaluator

Phase 2 resumed on 2 November in `feature/custom-variables`. The dated structure
refactor did not implement it. See the [current Phase 2 record](../custom-variables/phases/phase-02/README.md).
The owners relevant to that feature are:

- `backtest/observations.py` owns the four-parameter catalog, immutable plans,
  temporal observations and detached evidence. It imports no numerical compiler.
- `backtest/inputs/observation_inputs.py` owns prepared evidence and root
  admission. The generation owner supplies complete ordered lazy populations
  and borrowed prices. `backtest/financial/books.py` remains the valuation and
  candidate-policy authority. `backtest/inputs/` keeps saved fiscal histories.
- `backtest/financial/metrics.py` and `backtest/screening.py` for today's built-in
  pair and display-unit threshold contracts. These are not a general scalar
  variable abstraction.
- `backtest/application/` for captured calculation intent and original immutable
  evidence. Stored-result access does not reconstruct old meaning from current
  catalogs or financial preparation.
- `website/browser/range.js` for the existing strategy draft and restoration
  boundary. A future approved editor belongs at that boundary and the ordinary
  application request boundary. It does not need separate queue-edit machinery.
- `website/rendering/` and `website/browser/` for current built-in labels,
  standalone January/latest views, captured comparison and complete downloads.

`backtest/variables/definitions.py` now owns immutable formula validation,
normalization, identities, unit inference and resolved dependency programs.
Phase 3 resumed from `9e5d97d`; see its [current record](../custom-variables/phases/phase-03/README.md).
`backtest/variables/reference.py` owns bounded context plans, provider-backed
binary64 scalar execution, calculation identity and detached operation evidence.
It consumes the checked program and public observation provider without raw/SQL
access or financial reconstruction. The definition owner also binds its loaded
source policy. Phase 4 is complete. Phase 5 resumes from `f893bd4`; Phases 6–7 remain held.
The evaluator consumes the implemented observation interface. Reconcile
future scalar selection, editor and artifact contracts against this source. This map allocates no schema, format
version, formula language or implementation phase.


`backtest/selection.py` owns pure finite-scalar ranking and numeric/metadata
conditions. `backtest/variables/selection.py` owns bounded reference-backed
selection over explicit scopes and detached complete scalar evidence.
`definitions.normalize_quantity()` normalizes custom thresholds in canonical
units while retaining submitted display input. Legacy comparisons keep their
stored arithmetic scale in `backtest/screening.py` and the browser screener.
SQL keeps predicate pushdown. The browser consumes value lanes without formula
interpretation. Research and numerical source bindings include the delegated
selection policy. Numerical capability admission explicitly rejects formula
intent before readiness or execution. No new observation parameter is advertised. See the [Phase 5 handoff](../custom-variables/phases/phase-04/handoffs/phase-05.md).
`backtest/variables/library.py` now owns the separate durable variable repository
in `data/variable-library.sqlite`. It stores authored immutable revisions and
independent entry metadata versions. Its exact-reference resolver delegates to
`definitions.resolve()`. The definition owner keeps all language/graph/identity
policy. Old and deleted revisions remain retained. Complete detached programs
need no later store state. The next slice adds checked presentation capture.
Ordinary strategy/UI integration and numerical formulas remain held work.
See the [Phase 5 execution plan](../custom-variables/phases/phase-05/execution-plan-2026-11-02.md).
