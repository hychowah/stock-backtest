# Current source owners

This map lists the current source owners. Rows marked frozen belong to the
frozen experimental engine (AGENTS.md, Engines).

| Concern | Current owner |
|---|---|
| Financial rules, dated entry valuation, holding outcomes and built-in metric calculations | `backtest/financial/` |
| Validation, explicit legacy translation and SQL selection over stored built-in pairs/filter values | `backtest/screening.py` |
| Shared calendar requests and portfolio result reduction | `backtest/calendar.py`, `calendar_requests.py`, `portfolio_results.py` |
| Full annual responses, fiscal histories, cache receipts and prepared inputs | `backtest/inputs/` |
| Original dated calculations and retained independent reference | `backtest/engines/original/`, `backtest/engines/reference/` |
| Frozen: numerical calculation, immutable input attachments and their preparation | `backtest/engines/numerical/`, `backtest/application/calculations.py`, `candidate_calculations.py`, `preparation.py`, `scripts/numerical_generation.py` |
| Cache access, process ownership, cancellation and diagnostics | `backtest/runtime/` |
| Calculation requests, captured settings, jobs, queue, saved-backtest library and immutable result acquisition | `backtest/application/` |
| Strategy draft, the single filter list, saved restoration, held queue edits and immutable browser views | `website/browser/range.js`, `filter-picker.js`, `result-artifacts.js`, `evidence-results.js`, `saved-backtests.js`, `queue.js` |
| Shared variable editor/picker, detached readable traces and financial-free authoring | `website/browser/variable-workspace.js`, `variable-evidence.js`, `backtest/application/variable_authoring.py`, `website/server/variables.py` |
| Durable variable revisions, metadata and exact formula resolution | `backtest/variables/library.py`, `backtest/variables/definitions.py` |
| Plain browser assets and standalone HTML fragments | `website/browser/` |
| Detached database projections, static rendering, assets, exports and freshness | `website/rendering/` |
| Server lifetime and grouped calculation, stored-result and data HTTP adapters | `website/server/` |
| Stable build command and source-owning startup entries | `website/build.py`, `serve.py`, `runtime_access.py` |
| Maintained operational implementations | `tools/ops/` |
| Retained comparison runner and API probes | `tools/experiments/` |
| Documented executable commands | `scripts/`, retained thin `tools/*.py` entries, Windows command files |

No production backtest library imports website or tools. Website code calls the
application and input owners. Package initializers execute no operations.
No live module imports frozen source.

## Custom variables

See the [custom-variable summary](../custom-variables/master-plan.md) for the
contracts. These modules own the feature.

- `backtest/observations.py`: direct observation capabilities, immutable plans,
  temporal observations and detached evidence. It imports no compiler.
- `backtest/inputs/observation_inputs.py`: prepared evidence, owner scopes and
  root admission. Semantic source, policy and content bindings reject stale reuse.
- `backtest/inputs/dated_observation_inputs.py`: saved stock, Treasury and SPY
  calendar evidence. It never repairs or downloads. Shared sources use the empty
  symbol.
- `backtest/inputs/sqlite_observations.py`: a borrowed SQLite-backed observation
  view over the prepared database.
- `backtest/inputs/operation_inputs.py`: one Original scalar operation's daily
  and research connections.
- `backtest/measure_observations.py` and `backtest/variables/measures.py`:
  bounded financial-owner evidence and exact-reference measure bundles.
- `backtest/variables/definitions.py`: formula validation, normalization,
  identities, unit inference and resolved dependency programs.
- `backtest/variables/reference.py` and `evaluation.py`: bounded context plans,
  independent Python binary64 arithmetic and detached operation evidence.
- `backtest/selection.py`: pure finite-scalar ranking and conditions.
  `backtest/variables/selection.py`: the qualified reference-backed selection gate.
- `backtest/variables/library.py`: the durable variable repository in
  `data/variable-library.sqlite`, with capture and checked restore.
- `backtest/application/strategy_requests.py`: complete immutable strategy intent.
  `scalar_execution.py` plans prepared scopes. `scalar_runs.py` shares the
  Original schedule seam. `backtest/scalar_result_evidence.py` encodes scalar
  evidence. `variable_coverage.py` reduces recorded-scope coverage.
  `variable_authoring.py` serves authoring without financial work.
- `website/server/variables.py` adapts the HTTP routes. `website/browser/range.js`
  (`StrategyDraft`) owns the draft and the filter rows. `filter-picker.js` searches
  and chooses filter sources. `variable-workspace.js` is the shared editor.
  `evidence-results.js` and `variable-evidence.js` present stored results and
  readable traces without calculating.
- Frozen: `backtest/engines/numerical/formulas.py`, `scalar.py` and
  `formula_capabilities.py` hold the numerical lowering and admission subset.

`backtest/financial/metrics.py` and `backtest/screening.py` keep the built-in
pair and threshold contracts. They are not a general variable abstraction.
`definitions.normalize_quantity()` normalizes custom thresholds to canonical
units. Legacy comparisons keep their stored scale.
