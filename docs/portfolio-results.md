# Dated financial result contract

Financial result contract version 1 describes complete fixed and explicit-date
results. It is separate from calendar, database and browser ResultArtifacts
versions. Legacy application results have no new version key. The contract does
not rewrite jobs, queued tests or saved results.

## Market and currency

A captured request may include top-level `options.market` (`us`, `hk`, `jp`). Omission on existing records means US; opening never rewrites the record. A run contains one market. Comparisons can display different markets because new monetary values and returns use USD.

Foreign holding prices use FX from their actual price-observation dates. Returns include unhedged FX changes. Stopped holdings become USD cash at the observed exit, with 0% return until rebalance. SPY remains the S&P 500 total-return proxy; Asian dates use the previous completed US close. Annual valuation uses context-date FX and annual basic weighted-average shares. US calculations and saved original totals retain their meaning.

## Shared evaluator

`backtest/portfolio_results.py` uses only the standard library. Its interface is:

```text
evaluate(periods, select_period, common_start=None, checkpoint=None, final_mark=False) -> result
evaluate_into(periods, select_period, emit_period, common_start=None, checkpoint=None, final_mark=False) -> summary
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

`evaluate_into` emits one detached complete period at a time. It returns the
same scalar result fields without `periods`. It retains aggregation state and
the current book, plus the validated input date sequence. `evaluate` collects
these emitted periods to preserve the existing result contract. Both use the
same summation expressions and compounding order. A sink error propagates and
prevents a completion summary. Sink mutation cannot change computed finances.

The separate [evidence codec](result-evidence.md) stores complete results in
bounded pieces. Preview calculation requests retain their existing eager path
and limits. Additive [version-3 readers](evidence-views.md) inspect and export
original stored evidence without changing financial arithmetic or tolerance.

## Result fields

`mean_return(values)` and `reduce_returns(periods, start=..., end=...)` own the
shared return arithmetic. The first consumes ordered holding returns once. The
second consumes ordered `(strategy, SPY)` period returns once. Neither keeps
the input rows or opens resources. Calculation and saved-result exploration
use these functions. Python's existing summation and compounding order stay
unchanged. Empty selections return zero. Unavailable returns still propagate
as unavailable; a known empty book is distinct from missing evidence. Unknown
dates in older saved January records allow growth but no CAGR. Original calculation still requires complete validated dates.

All dates below are canonical `YYYY-MM-DD` strings. Numbers use full precision.
No intermediate return, weight or contribution is rounded.

| Field | Type and meaning |
|---|---|
| `periods` | Ordered list of complete period objects. It has one object per input pair. |
| `start`, `end` | Common start and final mark dates. Without a common start, start is the first trade. |
| `growth`, `spy_growth` | Compounded wealth multiples, starting at 1. An empty selection contributes 0% strategy return. |
| `cagr`, `spy_cagr` | Fractional annual growth over `(end - start).days / 365.25`. Strategy CAGR is null when growth is null. |
| `coverage` | Existing coverage text. Cached-price companies are not the full universe. Additional early stops lack the original manual review. |
| `first_trade`, `cash_days` | Present only for explicit-date/common-start results. Date of first trade and integer calendar days in zero-return cash before it. |
| `months` | Existing adapter metadata. Fixed and explicit application wrappers retain their submitted legacy month count. |
| `options` | Complete submitted screening options, with their existing omissions and nulls. |
| `seconds` | Adapter runtime diagnostic. It is the only field excluded from full-result agreement. |

The reducer returns financial fields. Ordinary wrappers add `months`, `options`
and `seconds`. Ordinary explicit-date calls retain their existing default
`months=12`. Calendar wrappers add `calendar` instead of `months`. Its requested
bounds and versioned week/month interval remain separate from resolved result
dates. Snapshot versions and financial contract version remain unchanged. See
[calendar compatibility](schedule-calendar.md).

Each period has exactly the existing fields:

| Field | Type and meaning |
|---|---|
| `entry`, `exit` | Requested holding boundaries. |
| `holdings` | Ordered list of complete stock rows. Selection order remains unchanged. |
| `names` | Actual integer holding count, including a short or empty selection. |
| `portfolio` | Arithmetic mean of selected fractional returns. Zero for an empty selection held in cash. |
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
| `status` | Exactly `Scheduled exit`, `Marked to date`, `Last available price` or `Bankruptcy`. A stored book row records only how a holding exited, with `Scheduled exit` for a normal exit. With `final_mark`, the last period's normal exits show `Marked to date`. The schedule passes `final_mark` when its last period ends on a mark, not on a scheduled exit: always for explicit trades, and for a fixed schedule when no nominal target rolls forward to the final session (`SessionCalendar.scheduled_final`). Saved results keep their stored labels. |
| `weight` | `1 / actual selected count`. The weights reset each period. |
| `contribution_pp` | `return_value / actual selected count * 100`, in percentage points. Signed values remain signed. |

The reducer preserves the original Python summation order and arithmetic
expressions. It compounds periods in their supplied order. Stopped proceeds
remain cash until the next rebalance. Cash before the first trade has zero
return for both portfolios. Empty periods hold cash at 0% until rebalance.
SPY keeps its period return. CAGR includes the full elapsed window. A total
loss remains zero wealth and −100% CAGR.

Older saved originals can contain null returns for empty periods and null
strategy totals. Opening, exporting or saving preserves those values. Apply in
the result explorer derives a temporary cash-based summary from complete saved
evidence. Reset restores the recorded totals. A missing return for a nonempty
period or incomplete holdings still fails explicitly.

Holding rows stay in SQL rank order. Attribution consumers retain their own
existing signed-contribution order, with symbol ties. This module adds no
second attribution calculator. Dated holdings gain no invented price fields.

## Completed random trials

`robustness.consume_trials` owns the completed-trial consumption loop. The
driver prepares books and emits its existing progress through `book_batch`.
The stream retains `summarize`, `summarize_trials`, paired coverage and
distribution arithmetic. A stream with missing or unordered trial numbers fails.
Duplicate schedules retain separate trial numbers and capture entries.

## Explicit scalar selected-book contract 2

Phase 6 Slice 2 adds `contract=2` to `evaluate` and `evaluate_into`. Omission
retains contract 1 and all legacy arithmetic. Contract 2 uses the same reducer,
period validation, survivor weights, compounding and CAGR calculation. Only the
selected-holding schema differs. It replaces required `metric_yield` and
`metric_multiple` fields with finite `ranking_value`, `ranking_unit`,
`ranking_display`, `ranking_direction` and qualified `scalar_evidence`. Actual
prepared financial fields remain. No reciprocal metric is invented.

This contract number is independent of application artifact 4 and bounded
evidence codec 2. The [Phase 6 compatibility record](plans/custom-variables/master-plan.md)
describes their explicit dispatch. Legacy callers keep contract 1. No saved
record or financial result is rewritten on reading.
