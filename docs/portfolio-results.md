# Dated financial result contract

Financial result contract version 1 describes complete fixed and explicit-date
results. It is separate from calendar, database, numerical artifact and browser
ResultArtifacts versions. Existing application results have no new version key.
The offline diagnostic envelope is `{"contract_version": 1, "result": result}`.
It does not rewrite jobs, queued tests or saved results.

## Shared evaluator

`scripts/portfolio_results.py` uses only the standard library. Its interface is:

```text
evaluate(periods, select_period, common_start=None, checkpoint=None) -> result
select_period(entry, exit) -> {entry, exit, holdings, spy}
```

`periods` is a nonempty list or tuple of date pairs. Both dates are
`datetime.date` objects. Each entry precedes its exit. Each exit is the next
entry, so boundaries are contiguous and strictly increase. `common_start`, when
supplied, is a date on or before the first entry. The whole sequence is checked
before provider work. Invalid requests raise `ValueError`.

`SessionCalendar` checks session membership and requested windows. The evaluator
does not reconstruct a nominal interval. The provider returns matching canonical
ISO `entry` and `exit` strings, a list of holding dictionaries in SQL rank order,
and finite fractional SPY total return. Missing required fields, changed book
identities, duplicate symbols, unordered ranks and malformed values fail. Empty
holdings are valid. Checkpoint and provider errors propagate unchanged.

The evaluator opens no files or databases. It starts no workers and acquires no
locks. Its caller retains source and financial ownership. The ordinary schedule
adapter keeps missing-book preparation and evaluation inside its transaction.
Cancellation still occurs before provider work and between periods. Result rows
are detached copies. They remain usable after provider and database closure.

## Result fields

All dates below are canonical `YYYY-MM-DD` strings. Numbers use full precision.
No intermediate return, weight or contribution is rounded.

| Field | Type and meaning |
|---|---|
| `periods` | Ordered list of complete period objects. It has one object per input pair. |
| `start`, `end` | Common start and final mark dates. Without a common start, start is the first trade. |
| `growth`, `spy_growth` | Compounded wealth multiples, starting at 1. Strategy growth is null if any period is empty. |
| `cagr`, `spy_cagr` | Fractional annual growth over `(end - start).days / 365.25`. Strategy CAGR is null when growth is null. |
| `coverage` | Existing coverage text. Cached-price companies are not the full universe. Additional early stops lack the original manual review. |
| `first_trade`, `cash_days` | Present only for explicit-date/common-start results. Date of first trade and integer calendar days in zero-return cash before it. |
| `months` | Existing adapter metadata. Fixed and explicit application wrappers retain their submitted legacy month count. |
| `options` | Complete submitted screening options, with their existing omissions and nulls. |
| `seconds` | Adapter runtime diagnostic. It is the only field excluded from full-result agreement. |

The reducer returns financial fields. The ordinary and diagnostic wrappers add
`months`, `options` and `seconds`. Weekly dates supplied explicitly retain the
existing default `months=12` metadata. This is compatibility with the current
explicit-date envelope. It is not a weekly website label or control.

Each period has exactly the existing fields:

| Field | Type and meaning |
|---|---|
| `entry`, `exit` | Requested holding boundaries. |
| `holdings` | Ordered list of complete stock rows. Selection order remains unchanged. |
| `names` | Actual integer holding count, including a short or empty selection. |
| `portfolio` | Arithmetic mean of selected fractional returns. Null for an empty selection. |
| `spy` | Fractional SPY total return for the same holding boundaries. |
| `is_final_period` | Boolean. True only for the final period. |

Each holding retains every selected field. The internal SQL `year` period ID is
removed. Existing fields are listed below; additional provider fields are copied
without projection.

| Fields | Types, nullability and units |
|---|---|
| `pool`, `symbol` | Strings. Pool is `legacy` or `cached`. Symbols are unique within the book. |
| `rank` | Positive integer, in increasing selection order. It retains arbitrary requested rank slices. |
| `candidate_rank` | Positive integer or null. This is original pre-price buffer rank, not selected rank. |
| `name`, `sector`, `exchange` | Strings or null. Null metadata stays null. |
| `fiscal`, `entry`, `exit` | Fiscal date and actual stock holding dates. Actual entry must be before requested exit. Actual exit can precede that requested mark. |
| `market_cap`, `enterprise_value`, `ebitda` | Finite USD amounts. |
| `ebitda_yield`, `spread`, `metric_yield` | Finite fractional yields. Spread subtracts the entry Treasury yield. |
| `ev_ebitda`, `metric_multiple` | Finite multiples. The selected metric pair stays distinct from current EV/EBITDA. |
| `return_value` | Finite fractional total return, including stopped exits and −1 for bankruptcy. |
| `status` | Exactly `Scheduled exit`, `Marked to date`, `Last available price` or `Bankruptcy`. |
| `weight` | `1 / actual selected count`. The weights reset each period. |
| `contribution_pp` | `return_value / actual selected count * 100`, in percentage points. Signed values remain signed. |

The reducer preserves the original Python summation order and arithmetic
expressions. It compounds periods in their supplied order. Stopped proceeds
remain cash until the next rebalance. Cash before the first trade has zero
return for both portfolios. Empty periods keep SPY growth available but make
full-window strategy growth and CAGR unavailable. A total loss remains zero
wealth and −100% CAGR.

Holding rows stay in SQL rank order. Attribution consumers retain their own
existing signed-contribution order, with symbol ties. This module adds no
second attribution calculator. January baseline price evidence remains in
the existing baseline helpers. Dated holdings gain no invented price fields.

## Offline numerical adapter

`tools/numerical_portfolios.py` supplies `NumericalPortfolio(inputs, provider)`.
Inputs and the accepted complete-book provider are explicit borrowed objects.
The caller owns source before imports and cache ownership before attachment.
An attached input's existing `validate()` runs before requests. The adapter
does not discover a runtime, default database or historical benchmark runner.

Its methods are `backtest(start=, end=, months=12, **options)`,
`backtest_dates(dates=, start=, end=, months=12, **options)` and
`backtest_periods(periods, months=12, common_start=None, **options)`. They return
the versioned diagnostic envelope. Explicit periods need no nominal interval.

The adapter owns one private in-memory SQL workspace. It requests one complete
eligible book at a time, checks count and identity, stages snapshots, ranking
pairs and requested thresholds, and calls unchanged `research._select`.
`tools/portfolio_workspace.py` retains the existing staging operation for both
the diagnostic adapter and historical runner. Every staging replaces derived
rows, including empty books and alternating pools. No price history or annual
statement cache is copied into this workspace.

Complete-book construction retains original-buffer membership and actual
adjusted-entry-before-exit eligibility before SQL ranking. Entry factors alone
do not establish this eligibility. Selected-only returns remain unimplemented.
The existing candidate row bound remains in force. Close the diagnostic adapter
and provider before closing the input attachment. Closing the adapter closes
only its workspace. Errors and cancellation unwind its transaction; the caller
retains ownership and controls the borrowed objects' lifetimes.

`compare_results(reference, observed)` inspects complete results recursively.
Only root `seconds` is excluded. Schemas, types, integer identities, strings,
nulls and ordered lists must agree exactly. Float comparison uses the existing
`1e-12` relative and absolute tolerances. The report separates structural and
categorical mismatch paths from numeric mismatch paths. It records maximum
absolute and relative float differences. It never sorts arrays or drops fields
to obtain agreement.

The ordinary application continues to use prepared SQL books through schedules.
This diagnostic adds no application route, persistent runtime, random recovery,
job service, user store, weekly control or capacity qualification. Historical
benchmark admission stays closed.
