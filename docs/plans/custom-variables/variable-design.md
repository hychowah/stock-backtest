# Custom variable design contract

This document states the design of the custom-variable system and the contracts
that the source keeps. The [close-out summary](master-plan.md) states the outcome
and limits. The [FMP source map](parameter-catalog.md) maps each direct input to
its provider field and lists the excluded items. The code is the final authority.
When this text and the code disagree, fix the text.

## Goal and model

One variable system serves both ranking and filtering. A user combines financial
parameters, chooses how each parameter is measured over time, and saves useful
formulas. Simple choices stay easy. Advanced formulas need no programming.

Two models were considered:

| Option | Consequence |
|---|---|
| Add each formula to the metric and filter catalogs | Keeps the old shape, but the catalog grows with every combination. Ranking still assumes a reciprocal yield. |
| Reusable variable definitions | A formula is defined once and evaluated for a company and date. Its scalar value can be used anywhere. |

The system uses reusable variable definitions. A variable returns one value with
a unit and an availability status. Ranking direction belongs to the strategy, not
to the variable. The old multiple/yield pair suits EV/EBITDA but not a margin,
a market cap or an arbitrary formula. Old calculations stay behind adapters.

## Parameters

### Catalogs

A parameter catalog gives each input a stable ID, description, unit, source
requirements, supported time operations and numerical rules. Each definition
records its catalog. Catalogs never change meaning after release.

| Catalog | Content |
|---|---|
| `financial-parameters/1` | Revenue, operating income, operating margin and enterprise value |
| `financial-parameters/2` | All 52 direct inputs plus the operating-margin and enterprise-value adapters; adds the `share` unit |
| `financial-parameters/3` | The `/2` content, plus six reported or report-derived fields (EBIT, basic and diluted EPS, total debt, free cash flow, report EBITDA) and 17 `owner.*` lanes that read existing owner policy |

The 52 direct inputs are 12 income-statement fields, 24 balance-sheet fields,
12 cash-flow fields, adjusted close, trading volume and the 3-month and 10-year
Treasury yields. Stable IDs use the forms `annual.<name>`, `market.adjusted_price`,
`market.volume`, `treasury.us_3m` and `treasury.us_10y`. The exact list is in
`backtest/variables/parameters.py`. Its independent test oracle is
`tests/test_parameter_contract.py`.

Use one parameter per input, with a time operation. Do not add separate entries
for current revenue, prior-year revenue and average revenue. Do not add an item
only because a broad accounting category contains it. Show the definition, such
as **Total debt / total assets**, not an ambiguous name such as "debt ratio".

Keep these states separate: recognized by the catalog, supported by the provider,
qualified for an engine, ready in an installation and observed for a company and
date. A raw provider field never becomes usable only because the downloader saved it.

### Units

Canonical units are `scalar`, `USD`, `USD/share` and `share`. `share` is a share
count; session volume uses it with session sampling. Displays are number,
multiple, percent, percentage points, USD, millions of USD, USD per share and
shares. Calculation uses canonical units. Conversion happens only at the display
boundary. A margin shown as 12% takes part in multiplication as 0.12. Treasury
percent values are divided by 100.

Addition and subtraction need identical dimensions. Multiplication and division
combine dimensions, so USD/share × share gives USD. Intermediate dimensions can
cancel. A definition uses its own recorded vocabulary for constants and output.

### Observation rules

Annual facts use the selected fiscal period. A report is available 90 days after
fiscal year-end, strictly before the context date. The anchor report is at most
800 days old. Mean, minimum and maximum need 1–10 complete consecutive annual
members. A missing selected-period fact never comes from a newer report, another
endpoint or a differently named aggregate. Null, conflicting, nonfinite and absent
facts are unavailable, with a reason. Zero never fills a missing fact.

Endpoint identity is part of meaning. Combined depreciation and amortization
comes from the cash-flow statement. Net receivables and accounts receivable
differ. Equity is total stockholders' equity. Debt and lease fields can overlap.
Net acquisition and net debt-issuance flows do not reveal gross flows. Annual
basic and diluted shares are weighted period averages, not screen-date counts.
Cash-flow fields keep their signed provider values.

Market and rate inputs support dated root, `at` and `lookback` contexts. They do
not use annual reporting timing. Price and volume come from actual session rows.
A saved price does not supply an absent volume. Treasury values use the latest
saved observation on or before the context date.

This is the current backtest availability model. It is not a filing-vintage
dataset. Restated reports are not reconstructed.

## Time operations

| Operation | Meaning |
|---|---|
| Parameter | Value available at the context date |
| `at(date, …)` | Value at a fixed date that does not exceed the screen date |
| `lookback(months, …)` | Value at the screen date minus 1–120 months |
| `annual(mean/min/max, count, …)` | Statistic over 1–10 consecutive eligible fiscal years |
| `annual(growth/cagr, count, …)` | Growth over `count − 1` annual intervals, with `count` ≥ 2; result is a scalar fraction |

The complete requested history is required. Two years are never averaged when
three were requested. Every historical observation applies the same availability
and age rules. Calendar-window statistics, quarterly data and TTM data are not
supported. A three-month lookback is not a quarterly statement.

Context ownership is strict:

- A root in a recorded January or latest scope reads that scope's stored owner
  lanes.
- Derived `at` and `lookback` contexts use dated owner policy, even when their
  date equals the root date.
- A missing prepared company or lane is unavailable. It never falls back to
  another calculation.

Example: revenue from the latest eligible report, multiplied by the mean of three
consecutive annual operating margins, divided by current enterprise value. The
mean applies to each year's margin. It is not average income over average revenue.

## Formula language

A saved definition is a restricted expression tree. The visual builder and the
Advanced text editor produce the same tree. `backtest/variables/definitions.py`
owns validation, normalization, identities and units.

| Item | Contract |
|---|---|
| Operations | `parameter`, `constant`, `neg`, `add`, `sub`, `mul`, `div`, `positive_div`, `ref`, `at`, `lookback`, `annual` |
| Definition versions | 1: base language. 2: adds annual growth and CAGR. 3: adds `positive_div`. Each version keeps its own normalization. |
| Envelopes | Bundle and program envelopes stay at version 1. Temporal policy is `annual-lag90/1`. |
| References | `ref` names an exact variable ID and a `sha256:` revision. "Latest" is invalid. Cycles fail. |
| Ceilings | 256 nodes, depth 32, 32 definitions per closure, dependency depth 8, 256 KiB, 64-character raw decimal literals |

New formulas use version 3 and catalog `/3`. An old definition keeps its namespace
until the user explicitly upgrades it. No definition is rewritten. Immutable
references may cross catalogs. A requested closure larger than 32 definitions fails.

The interface is:

```text
validate(definition, capabilities) → normalized definition, unit, requirements, errors
evaluate(definitions, companies, dates, input generation) → values, validity, reasons, evidence
```

The evaluator owns temporal alignment, units, dependency reuse and missing-data
propagation. Ranking and filtering consume its values without reading formulas.
Malformed formulas fail validation before a run. Missing inputs, zero
denominators and nonfinite results give an unavailable value with a reason.
`positive_div` needs a positive denominator, as built-in ratios do. General
arithmetic keeps meaningful signed values. Arbitrary Python or JavaScript is
never accepted.

## Named measures

The measure registry in `backtest/variables/measures.py` holds 33 immutable
definitions. Each measure keeps its unit and missing-data rule.

- **Calculated:** gross profit, gross margin, operating cash flow plus CapEx, net
  debt, working capital, tangible book equity, P/S and debt/assets.
- **Reported facts:** EBIT, report EBITDA, free cash flow, total debt, basic EPS
  and diluted EPS. These have no substitute calculation.
- **Existing owner values:** operating and net margin, market cap, enterprise
  value, P/E, P/B, FCF yield, price/FCF, PEG, ROE, current ratio, interest
  coverage, debt/equity, 1- and 3-year returns, EV/EBITDA, three-year EV/EBITDA,
  EBITDA yield and operating yield spread.

Owner values keep the existing formulas, denominator rules and stored rounding in
`backtest/financial/metrics.py`. Distinct facts stay distinct. Report EBITDA is
not entry EBITDA. Stored free cash flow is not operating cash flow plus CapEx.

A program captures only its reachable closure. A capture embeds exact measure
definitions. Restoring a capture never reads the registry.

## Ranking and filtering

`backtest/application/strategy_requests.py` owns strategy intent and capture.

| Field | Contract |
|---|---|
| Ranking | One source plus an explicit direction, `highest` or `lowest` |
| Conditions | Up to 50. Each has a source, strict `lt` or `gt`, and a threshold `{value, unit}` with a bounded decimal string |
| Source | `{kind: builtin, id}` or `{kind: formula, variable_id, revision}` |
| Ranks | Default 1–50, bounded 1–5000, inclusive |
| Selection order | Default `filter_first`; `rank_first` keeps original ranks and adds no replacements |
| Pool | Default `legacy`; `cached` also accepted |
| Bounds | Minimum cap $100 million, minimum EV $50 million, no maximum cap, no sector or exchange condition |

Any qualified scalar can rank or filter. A custom ranking gets no hidden
"minimum yield = 0" condition. A multiple or yield condition must be an explicit
condition. Ties use candidate rank ascending, null first, then symbol. Signed
zeros tie. A missing ranking value excludes the stock before either selection
order. Equal weights use the survivor count. Results show **Ranking value**, its
unit and direction. Built-in valuation results keep their multiple/yield columns.
No reciprocal yield is invented for a general formula.

Built-in lanes are `metric:<id>:yield`, `metric:<id>:multiple` and
`filter:<field>`. Each records its stored scale. Money lanes are millions of USD
(scale 6). Percent lanes such as FCF yield, margins, ROE and returns use scale −2.
Multiple lanes use scale 0. A threshold keeps its submitted spelling, its
canonical decimal, one binary64 comparison value and, for a built-in lane, one
storage comparison value at the saved scale. Saved financial values are never
rescaled. For example, 8% is canonical 0.08, and a saved percent lane compares
with 8.

Legacy requests translate at one boundary. They keep stored comparison scale,
because a canonical conversion would change strict binary64 comparisons. For
example, the distinct display values `13.501116090704034` and
`13.501116090704036` both become `0.13501116090704035` after division by 100.
Old requests and saved records are not rewritten.

The single qualified scalar gate is `backtest/variables/selection.py`. It admits
a fixed inventory of 77 IDs: the 52 direct inputs, two adapters, six reported
fields and 17 owner lanes. It admits definition versions 1–3 with catalogs
`/1`–`/3` and temporal policy `annual-lag90/1`. Every
captured definition is checked, including unused and constant-only entries.
Provider recognition or compiler support alone grants no qualification.

## Library and reproducibility

`backtest/variables/library.py` owns `data/variable-library.sqlite`. It is
durable user data, separate from rebuildable caches.

- An entry has a stable ID (`var:` plus 32 hex digits), a name of 1–120
  characters, a favourite flag and an integer entry version. The entry version
  is an optimistic edit token, separate from the content revision.
- Revisions are immutable. Rename and favourite change metadata only. A changed
  display unit is a formula edit and makes a new revision.
- Delete hides the entry. Revision rows stay. There is no eviction or garbage
  collection.
- Writes use `BEGIN IMMEDIATE` and wait at most two seconds for a lock. Commit is
  the publication point. A damaged or unfamiliar store is preserved and
  reported, never reset or migrated.
- Resolution uses submitted content first, then checked archive rows, then a
  matching measure identity and revision. Other absent references fail.

Saving and favouriting are distinct. Every saved variable appears in **My
variables**. A star makes it easier to find. An unsaved formula can still be
used in a draft.

Runs and queued tests capture the complete resolved bundle, revision identities
and display labels. A submission keeps no live lookup into the library. Editing
or deleting a library entry cannot change a submitted test. Completed results
keep definitions, values, labels and results. Opening an old result needs no
evaluation, no library entry and no current catalog.

## Execution

The Python reference evaluator, `backtest/variables/reference.py`, is the
correctness authority. It evaluates in binary64 through the observation provider
`backtest/observations.py`. The provider owns admission, report selection, annual
alignment, EV and reasons. Neither reads raw files or SQL directly.

| Path | Contract |
|---|---|
| Original | Default. Latest, January, fixed and random scalar modes; sample preview |
| Experimental numerical engine | Opt-in. Bounded Latest, January, fixed and random scalar modes through `Selectable.calculate_into` |
| Sample preview | Original only, 1–16 explicit company/date roots |
| Eager scalar `calculate()` | Unsupported |
| Coverage inspection | Original reference over a complete recorded January or latest scope |

Each backend declares its definition versions, parameters and operations.
Unsupported work fails before execution. It never changes meaning or switches
engine. Old Latest and January settings without an engine mean Original. The
producer label comes only from recorded evidence.

`backtest/application/variable_coverage.py` owns coverage. It discovers recorded
January and latest scopes, including empty ones, and requires an exact generation
and scope identity. The denominator is every snapshot row in the scope, before
availability, ranking, filters and rank ranges. An empty scope reports zero and
no percentage. Each output reports valid and unavailable counts and the first
unavailable reason per row. `backtest/application/scalar_execution.py` owns the
shared population reads, chunk planning and work reservations. An over-budget
request fails with `WORK_LIMIT`. Inspection writes nothing and builds no new
fixed or random books.

Observation projection 4, research schema 11 and daily cache 5 carry the
evidence. Older derived caches must rebuild. Durable records and immutable
artifacts keep their formats.

## Editor

The shared workspace keeps the strategy form small. The picker has **Favourites**,
**My variables** and **Built-ins**, with search and category labels.
`backtest/application/variable_authoring.py` supplies the descriptors from the
semantic owners. **Create variable** opens a side panel on desktop and a
full-screen editor on small screens. The user chooses a parameter, its time basis
and statistic, adds terms, names the variable, previews it, then applies or saves.

The formula shows as an editable equation with explicit grouping and stacked
fractions. Select a term to insert a parameter or change its time and statistic
settings. Operation buttons extend the selected term. Undo and Redo restore
equation edits. Only the selected term has settings below the equation.
**Advanced JSON** edits the same expression tree. The preview shows a plain-language explanation, the
unit, required data, available-company counts and missing reasons, and sample
calculations with input dates. Editing, validation, preview, coverage, Save and
Apply start no backtest. Apply goes through `StrategyDraft`, with its held
queue-edit protection. Source insertion changes only the selected term. It keeps
the Apply destination. A rejected Apply shows an error and keeps the editor open.

## Out of scope

The design excludes automatic strategy search, arbitrary user code,
cross-sectional ranking inside a formula and silent missing-value substitution.
Quarterly and TTM data need a separate history-provider capability with download
controls, availability policy and validation. The formula language should not
need redesign for them. Custom formulas run through the local service. Offline
standalone formula execution needs a measured input-size and browser-performance
decision first. Standalone January and latest built-in screening stay available.
