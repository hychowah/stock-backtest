# Current source owners

Updated for Phase 4. This map describes source after the structure refactor.
Historical designs, measurements and captured artifacts retain their original
paths and source hashes. The engine worktree has not been synchronized.

| Concern | Current owner |
|---|---|
| Financial rules, dated entry valuation, holding outcomes and built-in metric calculations | `backtest/financial/` |
| Validation and SQL selection over prepared built-in pairs | `backtest/screening.py` |
| Shared calendar requests and portfolio result reduction | `backtest/calendar.py`, `calendar_requests.py`, `portfolio_results.py` |
| Full annual responses, fiscal histories, cache receipts and prepared inputs | `backtest/inputs/` |
| Original dated calculations and retained independent reference | `backtest/engines/original/`, `backtest/engines/reference/` |
| Source-derived numerical calculation and immutable input attachments | `backtest/engines/numerical/` |
| Cache access, process ownership, cancellation and diagnostics | `backtest/runtime/` |
| Calculation requests, captured settings, jobs, queue, library and immutable result acquisition | `backtest/application/` |
| Strategy draft, saved restoration, held queue edits and immutable browser views | `website/browser/range.js`, `result-artifacts.js`, `saved-backtests.js`, `queue.js` |
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

## Held custom-variable handoff

Phase 2 resumed on 2 November in `feature/custom-variables`. The dated structure
refactor did not implement it. See the [current Phase 2 record](../custom-variables/phases/phase-02/README.md).
The owners relevant to that feature are:

- `backtest/financial/books.py` for dated entry observations without an exit.
  `backtest/inputs/` keeps complete saved responses and fiscal histories.
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

Reconcile future observation, scalar selection, editor and artifact contracts
against this source before implementation. This map allocates no schema, format
version, formula language or implementation phase.
