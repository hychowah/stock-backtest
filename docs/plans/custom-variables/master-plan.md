# Custom ranking and filtering variables

Status: complete

The experimental engine was deleted on 2026-11-05. The website runs only Original.

## Outcome

Users can define a scalar variable once and use it to rank or filter stocks.
The shared editor offers 52 direct FMP inputs, existing-policy adapters and 33
exact named measures. A formula can use annual mean, minimum, maximum, growth and
CAGR, and fixed-date or lookback contexts. Saved variables live in a durable
library with immutable revisions and favourites. Runs, queued tests and saved
results capture the complete formula bundle. They reopen without evaluation.

Original runs custom strategies in Latest, January, fixed and random modes, and
owns sample preview. The experimental engine that also ran these modes was
deleted on 2026-11-05. Coverage inspection reports complete counts and
missing reasons for a recorded January or latest scope. The source is integrated
into `main`. The program did not publish it or qualify an installed runtime.

The design contract is in [variable design](variable-design.md).

## Key decisions

- **Reusable definitions, not a larger metric catalog.** A variable returns one
  value with a unit and a status. Ranking direction belongs to the strategy. The
  multiple/yield pair suits EV/EBITDA only. Adding each formula to the catalog
  would grow it with every combination.
- **Annual data only.** The financial cache holds annual reports. Quarterly, TTM
  and calendar-window statistics need a separate data capability. The formula
  language does not need redesign for them.
- **Strict time and missing-data rules.** The 90-day lag, strict
  availability-before-date and 800-day anchor limit apply at every observation.
  The full requested history is required. A newer report never fills a missing
  value. Missing, conflicting and nonfinite facts are unavailable with a reason.
- **Context ownership.** A root in a recorded January or latest scope reads
  stored owner lanes. Derived `at` and `lookback` contexts use dated owner
  policy, even at an equal date. A missing prepared company or lane never falls
  back to another calculation.
- **Legacy settings keep stored comparison scale (Phase 4).** The Phase 1
  proposal converted old thresholds to canonical units. It was rejected because
  binary64 division by 100 merges distinct stored values. Example:
  `13.501116090704034` and `13.501116090704036` both become
  `0.13501116090704035`. Canonical conversion applies only to new thresholds.
- **Versioned meaning; no rewrites.** Definition versions 1–3 and catalogs
  `/1`–`/3` keep their recorded meaning. New formulas use version 3 and catalog
  `/3`. Old formulas need an explicit upgrade. Stored rounding, old immutable
  bytes, queue records and durable formats are unchanged.
- **One correctness authority.** The Python reference evaluator defines results.
  The deleted numerical engine compiled supported programs behind the same
  scalar boundary. Unsupported work fails before execution, with no fallback.
- **One qualification gate.** `backtest/variables/selection.py` admits a fixed
  77-ID inventory. Catalog recognition, provider support or compiler support
  alone grants no application qualification.
- **Conservative library retention (Phase 5).** Delete hides an entry. Revisions
  stay. There is no eviction. A damaged store is preserved and reported.
- **Exact authoring content.** Owners produce the editor descriptors. One
  resolution boundary serves Save, reopening and capture. See
  [decision 0001](phases/phase-11/decisions/0001-exact-authoring-content.md).
- **Complete recorded-scope coverage.** A separate owner counts every snapshot
  row in a recorded scope. It does not extend preview, which stays at 1–16
  roots. See [decision 0002](phases/phase-11/decisions/0002-complete-recorded-scope-coverage.md).
- **Compatibility at existing owners (Phase 12).** Historical definitions,
  queue plans and saved evidence are checked through their current owners. No
  compatibility gateway was added. See
  [compatibility boundaries](phases/phase-12/decisions/0001-compatibility-boundaries.md).
- **Cache versions.** Observation projection 4, research schema 11 and daily
  cache 5 carry the new evidence. Older derived caches must rebuild.
- **Unchanged ceilings.** The 32-definition closure ceiling, 50 conditions,
  ranks 1–5000 and existing resource, freshness, worker and lock rules stay.
- **Excluded from the first release.** Automatic strategy search, arbitrary
  code, cross-sectional ranking inside formulas and silent missing-value
  substitution.

## Where the current contracts live

- [Variable design contract](variable-design.md): parameters, units, time
  operations, formula language, measures, strategy intent, library, execution
  and editor.
- [FMP source map](parameter-catalog.md): provider fields and excluded items.
- Decision records: [exact authoring content](phases/phase-11/decisions/0001-exact-authoring-content.md),
  [complete recorded-scope coverage](phases/phase-11/decisions/0002-complete-recorded-scope-coverage.md)
  and [compatibility boundaries](phases/phase-12/decisions/0001-compatibility-boundaries.md).
- [Source map](../project-structure/source-map.md) and the
  [architecture guide](../../architecture-guide/dist/index.html).
- Root [AGENTS.md](../../../AGENTS.md#feature-contracts): the Custom variables
  contract and the standing engineering rules.
- Code owners: `backtest/variables/`, `backtest/observations.py` and
  `backtest/measure_observations.py`, plus `strategy_requests.py`,
  `variable_authoring.py`, `variable_coverage.py` and `scalar_execution.py` in
  `backtest/application/`.

## Known limits and open items

- Installed readiness is not established by source work.
- Real-cache coverage is not established. All checks used private synthetic
  fixtures. Field coverage for real companies and dates is unknown.
- Publication, deployment and installed restart need separate authorization.
  Each future `main` advance must recheck that no publication supervisor runs.
- Native HTTP and browser operation, literal native production launches and
  larger random workloads are not qualified.
- New durable containers were created by current code. Migration from older
  container schemas is not tested.
- Numerical sample preview and eager scalar execution are unsupported.
- Original is the only engine the website runs.
- Offline standalone formula execution needs a measured input-size and
  browser-performance decision. Custom formulas use the local service.
- No speedup or capacity claim follows from the recorded workloads.
