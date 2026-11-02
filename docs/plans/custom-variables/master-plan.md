# Custom ranking and filtering variables

Date: 2026-10-30

Parameter-list revision: 2026-11-02. The user requested a longer list of valuation
inputs, limited to fields supplied by the existing FMP routes or calculations
from those fields. This documentation update does not resume implementation.

Status: **Phase 3 complete in source on `feature/custom-variables` in the second audited implementation commit.**
Phase 1 contract documentation and Phase 2 provider implementation are complete.
Phase 2 verification and independent audits remain in its [record](phases/phase-02/README.md).
The user authorizes the reference formula evaluator from `9e5d97d`.
Its [current execution plan](phases/phase-03/execution-plan-2026-11-02.md) separates
immutable validated programs from bounded provider-backed execution. Both source
abstractions are now implemented. The [Phase 4 handoff](phases/phase-03/handoffs/phase-04.md)
describes the usable scalar evidence boundary without authorizing selection.
Phases 4–7 remain held, including scalar selection, the editor and library.
No download, deployment, integration or default change is authorized.

## Hold and resume

The latest 2 November instruction resumes Phase 3 implementation and audited
commits in this feature worktree. It supersedes the evaluator hold below.
The evaluator consumes the completed four-parameter provider. It changes no
financial rule, engine contract, root membership/rank, source/input freshness,
cancellation or attachment lifetime. Phases 4–7 remain held. See the
[Phase 3 record](phases/phase-03/README.md) for current source capability.
The following Phase 2 resumption and older inspections remain dated context.

The 30 October hold deferred Phases 2–7 until engine completion and an ownership
decision. CB-14 and CB-15 now record complete supported opt-in readiness and
normal-app selection. Their revised scope keeps Original as default. The older
default-cutover assumption is superseded; it is not a current prerequisite.

On 2 November the user requested Phase 2 planning, implementation and audited
commits until completion in this feature worktree. That instruction assigns
the narrow financial-input, prepared-admission, generation and provider scope
here. The engine worktree is clean at `8850e77`; this branch and main started at
`9455b6c`. Current package owners and completed CB-19 work were rechecked.
`books.entry_valuation` and its numerical normalizer already exist and are reused.

Phase 2 covers revenue, operating income, operating margin and enterprise value.
Later field admission, expression arithmetic, scalar selection, durable variables,
the editor and numerical formulas remain outside this resumption. The original
Phase 1 contract and dated Phase 2 proposals remain review records; use the new
execution plan for current ownership, interfaces and implementation sequence.

The [engine-owner handoff](engine-handoff.md) records what to communicate to
that worktree. It identifies reusable implementation, later contract changes and
existing main integration obligations. It adds no engine task or readiness gate.
Preparing a main-side record does not notify a separate engine session.

The website keeps its existing built-in metrics and filters. Phase 2 adds
prepared evidence, admitted roots and four dated parameter observations. It
enables no custom strategy or formula runtime behavior.

Phase 1 rechecked engine HEAD `a8cbb69` and its active working tree. Persistent
isolated preview integration is present. CB-13 is recorded complete. CB-14
capacity increments 1–4 are committed; increment 5 is partial, uncommitted and
not verified for use. CB-15 remains blocked. The fixed policy catalog and
pair-valued factor interface still require an explicit scalar-variable change.
See [ownership and inspected interfaces](phases/phase-01/ownership.md) for source
evidence and the distinction between existing agreements and proposed ownership.

Phase 2 rechecked engine HEAD `3856d02`. That commit adds a hardware decision
and stopped-session handoff; capacity5 source remains uncommitted. The engine
working tree is actively changing. The earlier fixture failure is historical:
the current source supplies its missing metadata, but this phase has not tested
the repair. See the [current inspection](phases/phase-02/inspection.md) and
[provider design and ownership scope](phases/phase-02/ownership.md), and
[provider validation plan](phases/phase-02/validation-plan.md). No provider or
custom-variable capability is implemented by these records.

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

The target input list is limited to documented fields from the FMP routes the
project already downloads. The [FMP source map](parameter-catalog.md) gives the
exact field, unit and preparation status for every admitted input. It also lists
calculations and exclusions. Endpoint support does not prove company/date
coverage or mean that the current app exposes a field.

| Group | Target inputs |
|---|---|
| Income and expenses | Revenue, cost of revenue, selling/general/administrative expense, research and development expense, operating income, interest income, interest expense, pretax income, income tax expense, net income |
| Share counts | Weighted-average basic shares and weighted-average diluted shares |
| Noncash and operating cash inputs | Combined depreciation and amortization, stock-based compensation, operating cash flow, capital-expenditure cash flow, net acquisition cash flow, cash taxes paid, cash interest paid |
| Financing cash inputs | Net debt issuance, common dividends paid, preferred dividends paid, common-share repurchase cash flow, common-share issuance cash flow |
| Cash and investments | Cash and cash equivalents, short-term investments, long-term investments |
| Operating assets | Net receivables, accounts receivable, inventory, prepaid expenses, total current assets, net property/plant/equipment, goodwill, intangible assets excluding goodwill, total assets |
| Operating liabilities | Accounts payable, accrued expenses, current deferred revenue, noncurrent deferred revenue, total current liabilities, total liabilities |
| Debt and ownership claims | FMP short-term debt, FMP long-term debt, FMP lease obligations, book shareholders' equity, book preferred stock, noncontrolling interests |
| Market observations | Dividend-adjusted close and trading volume |
| Reference rates | US 3-month and 10-year Treasury yields |

Reported amounts and share counts are the formula ingredients. Familiar
calculated measures remain reusable built-in variables: gross profit, EBIT,
EBITDA, free cash flow, net debt, working capital, market cap, enterprise value,
reported EPS, margins, growth rates, yields and valuation ratios. Keep their
definitions visible. Preserve the existing calculations and immutable Phase 1
examples. The source map separates established adapters from proposed formulas.

Use one revenue parameter with a chosen date, lookback or averaging operation.
Do not create separate input entries for current revenue, prior-year revenue and
three-year average revenue. Apply the same rule to the other inputs.

Do not add an item merely because a broader accounting category contains it.
The admitted list uses combined depreciation/amortization, net debt issuance and
net acquisition cash flow. Separate depreciation/amortization, gross borrowing
and repayment, gross acquisition spending, restricted cash, separate lease
types and other unverified splits are excluded. The source map records the full
exclusion list and the limits of this documentation check.

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
| **1. Variable contract and ownership** | Contract documentation delivered | [Versioned contract and examples](phases/phase-01/design.md), [compatibility](phases/phase-01/compatibility.md), historical [ownership map](phases/phase-01/ownership.md), and [Phase 2 handoff](phases/phase-01/handoffs/phase-02.md). Current Phase 2 ownership is assigned above. |
| **2. Parameter and history provider** | **Complete in source; both slices independently audited.** | [Phase record](phases/phase-02/README.md), [Slice 1](phases/phase-02/slice-01.md) and [Slice 2](phases/phase-02/slice-02.md). The provider supports revenue, operating income, operating margin and EV. The broader [FMP target inventory](parameter-catalog.md) does not expand this scope. Required WSL/native verification and both independent smart-commit passes are complete. |
| **3. Formula evaluator** | **Complete in source; both slices independently audited.** Strict immutable programs and bounded provider-backed scalar execution. | [Current record](phases/phase-03/README.md), [Slice 1](phases/phase-03/slice-01.md), [Slice 2](phases/phase-03/slice-02.md) and [Phase 4 handoff](phases/phase-03/handoffs/phase-04.md). Slice 1 is `d23cfa2`; Slice 2's malformed-plan finding is fixed. All 173 post-audit WSL/private native tests pass. |
| **4. General scalar selection** | **On hold; not started.** Ranking/filtering over the same variable values, plus legacy request adapters | Preserve baseline selections and returns. Verify both pools, both selection orders, both directions, ties, signed values, and empty periods. Legacy and browser parity remain explicit acceptance gates. |
| **5. Durable variable library** | **On hold; not started.** Immutable revisions, favourites, and resolved formula bundles | Verify concurrent edits, restart persistence, deletion independence, and queue/result reopening after a variable changes. Preserve existing durable library and queue files. |
| **6. Variable editor and strategy integration** | **On hold; not started.** One editor and picker used by ranking and filters | Test keyboard operation, narrow screens, visual/text round trips, preview explanations, pending edits, and queue-held drafts. Result tables and downloads use original submitted definitions. |
| **7. Numerical backend qualification** | **On hold; not started.** Compiled execution behind the same variable contract | Compare values, validity, selected rows, ranks, returns, and artifacts against the reference. Measure realistic repeated formulas, long windows, random schedules, memory, and cancellation on WSL and native Windows. |

Each phase includes interface comments, focused tests, compatibility notes, and affected architecture-guide updates. Financial phases must have one agreed owning branch. Custom-variable UI and library work are also on hold. Unrelated website and engine development can continue under the existing worktree boundaries.

Do not build automatic strategy search, arbitrary user code, cross-sectional ranking inside formulas, or silent missing-value substitution in the first release. These add separate semantics beyond the requested formula system.

Quarterly/TTM support is a later extension of the history provider. It requires explicit download controls, availability policy, preparation, and validation; the formula language should not need redesign.

## Unknowns

| Question | Cheapest useful probe |
|---|---|
| How much historical data exists for each proposed parameter? | Audit prepared-field coverage and a permitted native cache sample. Produce a parameter/date coverage matrix without downloading. |
| Does "three-month average" mean daily observed valuations, quarterly accounts, or both? | Show those choices separately in a small editor prototype. Keep their definitions distinct regardless of the preference. |
| Which documented FMP fields can preparation expose? | Use the [source map](parameter-catalog.md) to extend validation and evidence on the agreed branch after resumption. Most new fields are preserved in full raw responses but are not prepared. For example, debt/assets needs the documented `totalAssets` field added to validated inputs. Measure coverage before advertising support. |
| Can custom formulas remain usable in a standalone HTML export? | Measure a representative formula bundle and its required historical input payload. Decide browser support from that evidence. |
| How will the numerical engine expose variable requirements? | Review the proposed scalar contract against its current policy, factor, generation, and workspace interfaces before either branch implements it. |
| Does the builder remain understandable for longer formulas? | Test three tasks: a simple P/E filter, the example formula, and a formula using a saved variable. Observe grouping and time-basis mistakes before finalizing the editor. |

Phase 2 completes under the scoped 2 November authorization in this second
audited implementation commit. Both slices change source and synthetic fixtures.
They do not change installed runtime data or portable snapshots. The current
phase record contains required verification and independent audit outcomes.

Phase 3 source now consumes four supported observations through an immutable
validated program and a bounded reference evaluator. It changes no financial,
prepared-input, selection, application or numerical-engine contract. Current
verification and independent audit evidence live in its phase record. Phases 4–7
remain held; source completion authorizes no runtime publication or integration.
