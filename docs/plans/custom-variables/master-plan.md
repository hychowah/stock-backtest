# Custom ranking and filtering variables

Date: 2026-10-30

Status: Proposed master plan. Saved at the user's request. Phase 1 has not
started. This document does not authorize changes to engine-owned contracts,
market-data downloads, benchmark admission, deployment, or production cutover.
Engine observations below describe the planning session; recheck the owning
worktree before implementation.

## Design

**Goal**

Create one variable system for both ranking and filtering. Users can combine financial parameters, choose how each parameter is measured over time, and save useful formulas. The website should make simple choices easy while allowing advanced formulas without requiring programming.

**Options considered**

| Option | Common interface | Consequence |
|---|---|---|
| Extend the existing metric and filter catalogs | Register each new formula as another metric/filter and prepare its values | Preserves today's shape, but arbitrary combinations create an expanding catalog. Ranking still assumes every value has a reciprocal yield. |
| Introduce reusable variable definitions | Define a formula once; evaluate it for a company and date; use its scalar value anywhere | Separates financial meaning from ranking, filters, presentation, and execution. Both built-in and custom variables can use the same interface. |

**Choose reusable variable definitions.** The current multiple/yield pair is suitable for EV/EBITDA, but unsuitable for profit margin, market cap, or arbitrary formulas. A variable should return one value with a unit and availability status. Ranking direction belongs to the strategy.

The current code confirms this boundary: `metrics.py` prepares ranking pairs and separate filter values; SQL and browser selection rank by yield. The new system must generalize that boundary while preserving old calculations through compatibility adapters.

**1. A parameter catalog with explicit meanings**

Each parameter needs a stable identifier, description, unit, source requirements, supported time operations, and numerical rules.

Initial groups:

| Group | Examples |
|---|---|
| Valuation | P/E, P/S, P/B, EV/EBITDA, FCF yield |
| Profitability | Operating margin, net profit margin, ROE |
| Financial strength | Debt/assets, debt/equity, current ratio, interest coverage |
| Financial amounts | Revenue, operating income, EBITDA, net income, free cash flow |
| Market values | Market cap, enterprise value, adjusted price |
| Market history | Trailing returns; supported price statistics |

Avoid ambiguous names such as "debt ratio." Show the actual definition, such as **Total debt / total assets**.

Catalog entries must distinguish **supported**, **missing required data**, and **not yet supported**. A parameter must not appear usable merely because a raw provider response might contain a similarly named field.

**2. Time is part of the variable definition**

The interface must distinguish these operations:

| Choice | Meaning |
|---|---|
| Value at screen date | Value available when the stock is selected |
| Value 3 months earlier | Reconstruct the value available at that earlier date |
| Value on a specific date | Use that date only when it does not exceed the screen date |
| Average/minimum/maximum of 3 annual observations | Operate on three consecutive eligible fiscal years |
| Average/minimum/maximum over 3 calendar months | Operate on a defined dated series, using its declared sampling rule |

A three-month lookback is not a quarterly financial statement. The existing financial cache accepts annual reports only. Quarterly and TTM financial measures need a separate data capability.

Recommended defaults:

- Annual financial averages use equally weighted, consecutive fiscal observations.
- Require the complete requested annual history. Do not silently average two years when three were requested.
- Calendar-window statistics use an explicitly defined observation schedule and coverage rule.
- At every historical observation date, apply the existing report-availability and age rules.
- Never use a later report to fill an earlier missing input.
- Preserve the current 90-day annual lag, strict availability-before-date rule, and 800-day age limit.
- Keep the distinction between the current backtest availability model and a true historical filing-vintage dataset.

For the example, the builder would express:

```text
A1 =
  Revenue [latest eligible annual report]
  × Average [Operating margin, 3 consecutive fiscal years]
  ÷ Enterprise value [screen date]
```

The average applies to each year's operating margin. It is not the ratio of average operating income to average revenue.

**3. One formula definition, several execution implementations**

Use a restricted expression tree as the saved definition. The visual builder and optional text editor produce the same tree.

Start with parameters, constants, `+`, `−`, `×`, `÷`, parentheses, supported time operations, and references to saved variables. References resolve to immutable revisions. Reject cycles.

The core interface is:

```text
validate(definition, capabilities)
    → normalized definition, unit, requirements, errors

evaluate(definitions, companies, screen dates, input generation)
    → values, validity, reason codes, evidence
```

The evaluator owns temporal alignment, units, dependency reuse, and missing-data propagation. Ranking and filtering consume its results without understanding formulas.

Use canonical calculation units internally; convert only at the display boundary. A margin displayed as 12% must participate in multiplication as 0.12. Threshold entry must display its unit.

Malformed formulas fail validation before a run. Missing inputs, zero denominators, and nonfinite results produce an unavailable value with a reason. Built-in ratios retain their existing positive-denominator rules. General arithmetic can retain meaningful signed values.

Bound formula size and evaluation work. "Unlimited combinations" means combinations of supported operations, not arbitrary executable Python or JavaScript.

**4. Ranking and filtering share variables**

A strategy specifies:

```text
Ranking: variable revision + highest/lowest first + rank range
Filters: variable revision + comparison + threshold
Selection order: filter first / rank first
```

Allow any supported scalar variable in either position. Keep existing deterministic ties, original ranks, survivor weighting, and no-replacement behavior.

Do not fabricate a reciprocal yield for a general formula. Results show **Ranking value**, its unit, and direction. Existing built-in valuation results can retain their familiar multiple/yield columns.

Translate legacy requests at one boundary. Preserve existing default selections and saved records. Custom ranking must not inherit an invisible "minimum metric yield = 0" condition.

**5. A focused user interface**

Keep the main strategy form small:

```text
Rank by    [A1 — Operating yield ▾]  [Highest first ▾]
Ranks      [1] to [50]

Filters
[Current ratio ▾]  [greater than ▾]  [1.5 ×]
[A1 ▾]             [greater than ▾]  [8 %]

[+ Add filter]       [Create variable]
```

The variable picker contains **Favourites**, **My variables**, and **Built-ins**, with search and category labels.

"Create variable" opens a side panel on desktop and a full-screen editor on small screens:

1. Choose a parameter.
2. Choose its time basis and statistic.
3. Add an operator and another term.
4. Name the variable.
5. Preview, then apply or save.

Show the formula as editable blocks with explicit grouping. Provide a synchronized text editor under **Advanced**. Both views edit the same definition.

The preview shows:

- A plain-language explanation.
- Output unit.
- Required data.
- Available-company count and missing-data reasons for a selected date.
- Several sample calculations with input dates.

Editing a formula must not automatically launch a full backtest. Apply changes through the existing strategy draft boundary, including its queue-edit protections.

**6. Saved variables and reproducibility**

Use a durable variable library, separate from rebuildable financial caches. A variable has a stable ID, name, immutable revisions, and favourite status.

Saving and favouriting are distinct: every saved variable appears in **My variables**; stars make commonly used ones easier to find. Unsaved formulas can still be used in a draft.

Runs and queued tests capture the complete resolved formula bundle, its revision identity, and display metadata. Editing or deleting a library entry cannot change an already submitted test.

Completed artifacts preserve submitted definitions, selected values, labels, and results. Opening an old result requires no evaluation and no current library entry.

**7. Future engine compatibility**

The engine worktree is already developing a persistent numerical preview. Its current policy adapter explicitly accepts a fixed metric/filter catalog, and its factor interface emits ranking pairs. Arbitrary variables are therefore a contract change, not an automatic extension.

The stable boundary should be **validated variable requirements → scalar values and validity**. The numerical engine can compile supported expressions behind that boundary. The reference evaluator remains the correctness authority.

Each backend declares supported definition versions, parameters, and temporal operations. Unsupported work fails clearly before execution; it must not silently change meaning or switch engines.

Initially, custom formulas can use the local service in every website mode. Existing standalone January/latest functionality remains available. Offline custom-formula support should follow a measured input-size and browser-performance probe.

## Plan

| Phase | Abstraction delivered | Completion evidence and handoff |
|---|---|---|
| **1. Variable contract and ownership** | Versioned definitions, temporal meanings, units, errors, and backend capability contract | Worked examples cover the user's formula, negative values, missing years, historical dates, and percentage conversion. Agree ownership of financial and prepared-data changes before editing shared contracts. |
| **2. Parameter and history provider** | One point-in-time source for supported financial and market observations | Tests cover availability boundaries, stale reports, conflicting annual inputs, fiscal gaps, calendar boundaries, and missing prices. Later work asks for observations without interpreting raw files. |
| **3. Formula evaluator** | Validation, expression evaluation, dependency resolution, and explanation | Reference tests cover arithmetic, units, nested expressions, saved dependencies, invalid denominators, cycles, and bounded work. Cache identities include definitions, policy, and input generation. |
| **4. General scalar selection** | Ranking/filtering over the same variable values, plus legacy request adapters | Preserve baseline selections and returns. Verify both pools, both selection orders, both directions, ties, signed values, and empty periods. Legacy and browser parity remain explicit acceptance gates. |
| **5. Durable variable library** | Immutable revisions, favourites, and resolved formula bundles | Verify concurrent edits, restart persistence, deletion independence, and queue/result reopening after a variable changes. Preserve existing durable library and queue files. |
| **6. Variable editor and strategy integration** | One editor and picker used by ranking and filters | Test keyboard operation, narrow screens, visual/text round trips, preview explanations, pending edits, and queue-held drafts. Result tables and downloads use original submitted definitions. |
| **7. Numerical backend qualification** | Compiled execution behind the same variable contract | Compare values, validity, selected rows, ranks, returns, and artifacts against the reference. Measure realistic repeated formulas, long windows, random schedules, memory, and cancellation on WSL and native Windows. |

Each phase includes interface comments, focused tests, compatibility notes, and affected architecture-guide updates. Financial phases must have one agreed owning branch. Main can continue independent UI and library work against fixtures while engine-owned interfaces are settled.

Do not build automatic strategy search, arbitrary user code, cross-sectional ranking inside formulas, or silent missing-value substitution in the first release. These add separate semantics beyond the requested formula system.

Quarterly/TTM support is a later extension of the history provider. It requires explicit download controls, availability policy, preparation, and validation; the formula language should not need redesign.

## Unknowns

| Question | Cheapest useful probe |
|---|---|
| How much historical data exists for each proposed parameter? | Audit prepared-field coverage and a permitted native cache sample. Produce a parameter/date coverage matrix without downloading. |
| Does "three-month average" mean daily observed valuations, quarterly accounts, or both? | Show those choices separately in a small editor prototype. Keep their definitions distinct regardless of the preference. |
| Which additional fields require preparation changes? | Map each catalog entry to validated annual inputs. For example, P/S can reuse revenue, while debt/assets needs a validated assets input. |
| Can custom formulas remain usable in a standalone HTML export? | Measure a representative formula bundle and its required historical input payload. Decide browser support from that evidence. |
| How will the numerical engine expose variable requirements? | Review the proposed scalar contract against its current policy, factor, generation, and workspace interfaces before either branch implements it. |
| Does the builder remain understandable for longer formulas? | Test three tasks: a simple P/E filter, the example formula, and a formula using a saved variable. Observe grouping and time-basis mistakes before finalizing the editor. |

This is a planning proposal. No source, runtime data, or existing snapshots were changed.
