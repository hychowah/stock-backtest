# Current source owners

Updated during Phase 7 Slice 3 qualification. This map describes source after the structure refactor.
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
| Strategy draft, saved restoration, held queue edits and immutable browser views | `website/browser/range.js`, `result-artifacts.js`, `evidence-results.js`, `saved-backtests.js`, `queue.js` |
| Shared variable editor/picker, detached readable traces and financial-free authoring | `website/browser/variable-workspace.js`, `variable-evidence.js`, `backtest/application/variable_authoring.py`, `website/server/variables.py` |
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
  boundary. The authorized Phase 6 editor belongs at that boundary and the ordinary
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
source policy. Phases 4–6 are complete. Phase 7 adds qualified bounded numerical
scalar execution through existing application owners. Its final audit and broad
verification remain pending. Original remains default.
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
selection policy. Numerical capability admission accepts supported captured
scalar programs for bounded Latest, January, fixed and random execution. Raw
formula aliases and unsupported intent fail before readiness or financial work.
The four observation parameters remain unchanged. See the [Phase 5 handoff](../custom-variables/phases/phase-04/handoffs/phase-05.md).
`backtest/variables/library.py` now owns the separate durable variable repository
in `data/variable-library.sqlite`. It stores authored immutable revisions and
independent entry metadata versions. Its exact-reference resolver delegates to
`definitions.resolve()`. The definition owner keeps all language/graph/identity
policy. Old and deleted revisions remain retained. Complete detached programs
need no later store state. `Store.capture()` also captures presentation in the
same read snapshot. `VariableCapture` and `require_capture()` own complete
detached capture/restore. The checked program accessor uses the existing
definition restore boundary. Captured presentation does not affect formula
or bundle identity. No durable schema or application result format changes.
Phase 6 is now authorized. Its first slice adds
`backtest/application/strategy_requests.py` for complete immutable strategy intent.
It combines exact formula sources with captured stored-pair/filter descriptors,
canonical thresholds and separate submission/calculation comparisons. Checked
restore uses no current library or display catalog. Admission checks capability
separately. `library.capture_submitted()` reuses the existing envelope policy
without opening a durable file. Slice 1 changed no ordinary route, job/queue or
result format. Slice 2 adds the execution/evidence integration described below.
Slice 3 supplies the shared editor described below. Phase 7 adds opt-in bounded
compiled execution through those owners. See the
[Phase 6 execution plan](../custom-variables/phases/phase-06/execution-plan-2026-11-02.md).


Phase 6 Slice 2 adds `backtest/inputs/sqlite_observations.py` for a borrowed
SQLite-backed observation view, sharing `daily.prepared_report()` decoding and
existing financial pool policy. `backtest/application/scalar_execution.py` owns
complete prepared scopes, reference chunk planning and one global scalar select.
`scalar_runs.py` uses existing Original schedule/batch/portfolio owners through
a selected-book seam. `backtest/scalar_result_evidence.py` owns codec 2 on the
existing bounded framing. Application artifact 4 dispatches explicitly through
temporary/durable evidence, acquired readers, pages and complete exports. Stored
artifact 1/2/3 and codec 1 retain their meanings.

Phase 6 Slice 3 keeps exact raw authoring snapshots in the existing library owner.
The definition owner converts checked detached programs back to bounded raw edits
with exact decimal compaction and revision verification. `variable_authoring.py`
combines these operations without financial work. `website/server/variables.py`
adapts the grouped same-origin routes. The browser workspace shares one tree and
one picker across ranking, conditions and exact saved references. StrategyDraft
owns held sessions, revision-fenced patches and asynchronous submission capture.
`evidence-results.js` presents bounded retained results for all modes;
`variable-evidence.js` explains captured values, dates, reasons and operation traces
without calculating or reading a current library/catalog. Numerical formula
application admission is explicitly bounded and uses the same captured contract.

The workspace shares opaque authored/label packing with StrategyDraft. The
language owner supplies exact editable projections. Both authoring paths send
each exact dependency once through the existing submitted/labels contract.
Checked immutable restoration stays separate from deliberate editing.


Phase 7 is authorized from `5cded92` on `feature/custom-variables`. Shared
`backtest/variables/evaluation.py` owns checked task/context planning, provider
observation, bounds and detached evidence lifecycle. `reference.py` retains
independent Python arithmetic. `backtest/engines/numerical/formulas.py` owns
bounded typed lowering and independent Numba arithmetic. Both use the existing
checked program and provider; neither changes financial decisions. Public
experimental scalar admission stays closed in Slice 1. The
[current execution plan](../custom-variables/phases/phase-07/execution-plan-2026-11-02.md)
supersedes dated Phase 7 hold statements above. Original remains default.


Phase 7 Slice 2 kept public numerical scalar admission closed.
`backtest/engines/numerical/scalar.py` owns one bounded compiled arithmetic and
observation lifetime, genuine complete numerical books and staging for fixed or
random dates. It injects arithmetic below the existing complete-scope selector.
`scalar_runs.py` shares prepared scopes and the calendar/reduction seam with
Original. Original retains its missing-book batch preparation and imports no
numerical stack. The numerical generation owns a checked current research reader
for authoritative latest and January scopes, with explicit SQLite closure.

The existing numerical session, trial, pool, worker, checkpoint and runtime owners
explicitly dispatch scalar contract 2 / codec 2 alongside legacy contract 1 /
codec 1. A scalar single-trial seal retains every original explanation and a
trial-qualified scope namespace. Checkpoints copy those records unchanged. Full
hits create no evaluator, book provider or worker. Scalar errors use the existing
safe projection across child transport. `Selectable.calculate_into()` now has
supported bounded Candidate routing behind checked capability admission; no new application
route, queue pipeline, durable container or artifact integer is allocated.

The Slice 3 worker-control amendment keeps private cancellation transport in
`trial_worker.py`. Its existing parent-lifetime observer checks the terminal
marker at approximately 50 ms intervals. Calculation checkpoints read latched
memory state and surface observation failures. Parent-loss protection continues
after marker cancellation. Source remains held through observer join and
terminal process exit. Shared evaluator checkpoints, financial owners and
runtime-child controls retain their contracts. Matched private WSL/native
qualification precedes supported public admission.

`backtest/engines/numerical/formula_capabilities.py` declares the existing
operation/parameter subset without optional numerical imports or financial work.
Application intent and direct numerical entries check that same owner before
readiness or new financial work. Scalar eager execution and numerical sample
preview fail explicitly. Original remains default and owns reference sample
preview. One shared EngineControls selector supplies every scalar mode;
StrategyDraft captures and restores that pin. Result comparison defaults omitted
old scalar Latest/January engine settings to Original without rewriting evidence
or inventing producer identity. Independent audit and final broad verification
remain pending.

EvidenceResults also owns the common completed-producer projection. Its direct
Latest/January entry and ScheduleView's legacy/custom/random entry show only the
artifact's recorded producer. Scalar panels have their own visible destination;
the redundant custom destination is hidden. Missing historical producer content
retains the unknown label. The current selector supplies no provenance.
