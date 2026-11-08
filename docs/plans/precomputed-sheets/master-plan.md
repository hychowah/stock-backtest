# Precomputed sheets: reuse entry work across random seeds

Status: active

## Goal and authority

Plan based on main `f8a6217`; S0 measured source `e1ae7c7`. The user
normally chooses a fresh seed. Once prepared, a new cached-pool seed
should cost about the same as a rerun. Holdings, returns, statuses and stored
rounding must stay identical. Saved library and queue records open unchanged.
Custom formula edits never rebuild sheets.

Measure the largest cost and stop when gains become marginal; no numerical
speed target. Nightly preparation may be slow. The authorized bench measurements
and runtime-log reads are complete. S1 is authorized on `plan/precomputed-sheets`;
product edits follow Claude's design review.

## Verified starting point

`book_store.py` and `book_batch.plan` use entry/exit pairs; random exits prevent
most reuse. The [typed-storage summary](../typed-storage/master-plan.md) reports
326.6 s with 1,326 books computed versus 62.7 s saved: 24 quarterly trials,
2013–2026, cached pool, ranks 1–30, three built-in conditions and one variable,
under user load. These are prior measurements, not sheet timings.

`books.admit` values cap as report cap × (entry adjusted price / fiscal adjusted
price); `books.close` uses exit / entry − 1. Admission has exit-dependent gates.

## Proposed behavior

Persist historical sheets keyed logically by **entry session and pool** in the
daily store. Precompute `cached` for every saved SPY session from
`rules.FIRST_DAY` through the latest cached session, including empty sheets.
Build missing sheets on demand with the same builder, as today's runs build
missing books. Sheets remain a cache.

Keep the existing latest open book and its policy. Historical sheets include
delisted companies and allow entry up to four calendar days later. Calling
`books.book(entry, None, ...)` today would instead apply currently-listed and
exact-session latest rules; it cannot implement historical sheets unchanged.

For each period, restrict the sheet to rows admitted by the current dated
policy **before** either ranking order or formula-scope evaluation. In
particular, actual entry must precede exit. With a valid stored entry before
exit, the unlimited backward lookup can find at least that entry price.
Verify that reasoning against `MISSING_EXIT_PRICE` and short/gapped periods.
Dropping failed closes after selection would change ranks and weights.

Select with today's metrics, filters, ties and scalar executor. Then call the
same `books.close` rule for selected rows only, and compute period SPY from
the admitted research facts. Preserve the 10-day backward lookup, last-price
fallback, bankruptcy window and final-mark relabelling. No exit pairs persist.

Legacy uses the same builder on demand: its controls and development check remain
callers. Precomputing both pools adds cost outside the usual workflow. Delete
unused pair-keyed preparation and staging; add no engine, mode or fact store.

## Nightly freshness: decided

`data_refresh.refresh_series` replaces complete adjusted histories when recent
overlap changes. `research._Diff` records earliest changes; `books.change_day`
takes the global minimum. Both measured real refreshes dropped every stored book.

| Policy | Benefit | Decision |
| --- | --- | --- |
| (a) Rebuild after each changed research generation | Exact results; deletes invalidation machinery | Chosen from S0. Rebuild every cached sheet. Unchanged generations reuse sheets. |
| (b) Keep conservative change-day reuse | Avoids some rebuilding | Rejected: measured real refreshes retained no books. |
| (c) Ignore rescales within rounding tolerance | Could retain historical sheets | User rejected: exact results are required. |

S1 implements policy (a) and deletes `books.change_day`, `books.kept`, `research.changes`/`_Diff`
and the drop logic in `daily.prepare`, plus helpers used only by (b).

Provider rounding can change ratios, filters, ties or formula conditions. Keep
entry and exit prices in the same admitted generation, including SPY. No rescale
classification, tolerance policy or value-difference investigation is needed.

## Storage: compact confirmed

The user confirmed compact rows from S1: one row per stock per sheet, with columns
for current metric pairs and filters. S0 replaces the draft's size/time estimates.
Postponing compaction builds a large cache twice. Preserve missing values and
numerical storage semantics. Bump the disposable cache version; no migration
reader, binary format, compression layer or duplicate layout.

## Fit the unified update

Keep `checking → annual → statements → prices → research → daily → website →
verify` in `data_refresh.STAGES`. Sheet work belongs inside **daily**, after
research admission and before website publication, under existing cache
ownership. Manual update, offline preparation, startup and 07:00 Hong Kong
maintenance share that chain. The user confirmed 07:00 stays unchanged.
Add no scheduler, update record or readiness state.

Emit daily completed/total session-pool counts through existing progress. Count
completion only after rows and the empty-or-populated completion marker commit
together. Reuse bounded readers and the single parent writer; retain cancellation
and worker cleanup. Resume only complete sheets valid for the admitted binding.
Commit bounded sheet units, not one transaction spanning all history.

Historical coverage does not gate daily readiness or website publication: the
website embeds only the latest screen. Interrupted builds leave committed sheets
usable; runs fill misses. Essential-input freshness still applies. Keep existing
estimates and outcomes; download success and readiness stay separate.

## Phases and exits

### S0 — complete: measurements and decision

Authorized bench copy `~/bench/ebitda-real`, source `e1ae7c7`, research version 19;
research prepared in 185 s, latest 2026-10-21. An ignored scratch probe
sampled 30 cached entries in one process. Raw output stays
outside the repository. There are **7,752** cached SPY sessions, 1996-01-02 through
2026-10-21.

Dated-book build median **0.337 s**, p90 **0.442 s**; CPU approximately equalled
wall time. `books.close` median **0.014 s**, about 4%. Entry-only work is therefore
approximately **0.32 s/sheet**, not a separately implemented sheet measurement.

| Layout | MB/sheet | Median write seconds/sheet | Projected GB, all sessions |
| --- | --- | --- | --- |
| Normalized | 2.17 | 0.071 | 16.8 |
| Compact | 0.85 | 0.028 | 6.6 |

Normalized rows/sheet: `book_rows` 2,449; `book_metrics` 4,471; `book_filters`
42,124. Compact stores one row per stock. Sizes are vacuumed dated-book proxies,
including exit fields. Ideal eight parallel builders plus a serial writer project
**532 s compact**, **838 s normalized**, excluding research. Eight workers were
not measured. Windows may be slower: runtime research rebuilds took 540–662 s
versus 185 s on this bench.

Windows runtime logs, 2026-11-08:

| Operation | Books kept / previous | First changed day |
| --- | --- | --- |
| Code-only deploy | 2,802 / 2,803 | None |
| Real data refresh | 0 / 2,803 | 1995-01-03 |
| Second real refresh | 0 / 1 | 1985-11-29 |

Runtime daily work besides research took about 5 s. These logs count books, not
entry-only sheets. All books dropped in both observed real refreshes. S0 selects
policy (a), removing change-day machinery. The user requires exact results and
rejects (c). No product change was made in S0.

### S1 — complete (74808c8)

Entry-only compact sheets; the run closes selected rows; change-day code
deleted. Fast tier 92/92, heavy 1/1. Bench parity against main (e1ae7c7 code):
random, quarterly 2013–2018, development-check run and latest digests equal;
`scripts/check.py` 0 differences on both. Random test with books computed:
311.9 s on main, 163.5 s on S1.

### S2 — prepare coverage and qualify the workflow

Requires S1 parity. Implement full cached precomputation, daily-stage sheet
progress and continuation in the unified chain, preserving existing readiness.

Exit: measure a full build and nightly maintenance. Private fixtures verify
on-demand misses, interrupted precomputation, ordinary readiness, cancellation,
restart and native Windows ownership/spawn. After complete precomputation, bench
new seeds and a repeat: zero sheets computed/written and financial parity. Profile
remaining costs until gains are marginal. Update contracts and the architecture
guide. Source completion does not establish deployed readiness.

## Decisions

1. **Coverage:** recommend all cached sessions first; legacy stays available on
   demand through the same sheet builder. Reject precomputing both without need.
2. **Freshness decided:** (a), exact rebuilding after each changed research
   generation; delete change-day machinery. Policy (c) is rejected.
3. **Layout confirmed:** compact from S1: about 2.6× smaller and
   2.4× faster writes in S0.
4. **Missing sheets:** recommend on-demand builds through the same builder.
   This preserves usability after a deploy or interrupted night without a new
   readiness gate; a miss costs preparation time once.

## Risks and protected contracts

Full rebuilding can occupy cache ownership and disk for a long time. Measure
headroom. Agree shared-contract ownership before editing. Preserve freshness
checks, bounded reads, worker ownership, attachment lifetime and resource limits.

Original remains the only engine. Financial policy, calendar sampling, seeds,
captured plans, queue recovery, artifacts, durable formats and frozen January
records remain unchanged. Strategy execution never downloads. Formula programs
still evaluate at runtime; edits affect no sheet identity. Exact results remain
required.

## Next

S2: precompute every cached sheet inside the daily stage, with progress.
No merge, push, deployment or installed restart is authorized.
