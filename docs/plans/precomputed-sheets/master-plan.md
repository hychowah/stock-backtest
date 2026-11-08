# Precomputed sheets: reuse entry work across random seeds

Status: active

## Goal and authority

Proposal against main `f8a6217`; implementation decisions remain open. The user
normally chooses a new random seed. Once prepared, a new cached-pool seed
should cost about the same as a rerun. Holdings, returns, statuses and stored
rounding must stay identical. Saved library and queue records open unchanged.
Custom formula edits never rebuild sheets.

Measure the largest cost and stop when gains become marginal; no numerical
speed target. Nightly preparation may be slow. Only documentation is authorized;
bench execution, implementation and runtime access require separate authorization.

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

## Nightly freshness: decision after measurement

`data_refresh.refresh_series` replaces complete adjusted histories when recent
overlap changes. `research._Diff` records earliest changed rows, including price
volume/reasons; `books.change_day` takes the global minimum. One old change can
drop almost every book. That outcome is inferred, not measured.

| Policy | Benefit | Cost and recommendation |
| --- | --- | --- |
| (a) Rebuild after each changed research generation | Exact results; deletes invalidation machinery | Choose if S0 shows (b) keeps few sheets. Unchanged generations need no rebuild. |
| (b) Keep conservative change-day reuse | Exact results; avoids some rebuilding | Horizon becomes entry + `FORWARD_REACH`. Keep only if measured savings justify the code. |
| (c) Ignore whole-history rescales when sheet values agree within rounding tolerance | Could retain most sheets | Changes financial policy: fresh builds can differ. Requires explicit acceptance and additional measurements. |

Choosing (a) deletes `books.change_day`, `books.kept`, `research.changes`/`_Diff`
and the drop logic in `daily.prepare`, plus helpers used only by (b).

First ask whether the user wants to investigate (c); recommend no while exact
results are required. Only then measure rescale residuals, changed dates/validity,
derived-value differences, selection effects and certification cost. Provider
rounding can change ratios and cross filters, ties or formula conditions.
Retained entry prices cannot mix with newly adjusted exits: both must use the
same current generation, including SPY. Other corrections still invalidate sheets.

## Storage recommendation

Measure both today's normalized rows and one SQLite row per stock per sheet,
with columns for the current metric pairs and filter values. Recommend compact
rows in the first code phase. `book_filters` dominates current writes; estimates
of 3.2 MB × 7,750 sessions imply about 25 GB per pool before journal headroom.
The old 0.15 s/book on eight workers is also an estimate, not a build forecast.

Retain normalized storage only if S0 shows acceptable disk/build cost. Otherwise
postponing compaction builds a large cache twice. Preserve missing values and
numerical storage semantics. Bump the disposable cache version; no migration
reader, binary format, compression layer or duplicate layout.

## Fit the unified update

Keep `checking → annual → statements → prices → research → daily → website →
verify` in `data_refresh.STAGES`. Sheet work belongs inside **daily**, after
research admission and before website publication, under existing cache
ownership. Manual update, offline preparation, startup and 07:00 Hong Kong
maintenance share that chain. Add no scheduler, update record or readiness state.

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

### S0 — measure only

First resolve whether to investigate (c). Obtain bench authorization; use disposable
copies and ignored scratch probes, with no product change or live mutation.

- Sample entry sessions across history, including sparse and recent dates.
  Build identical entry-only sheets in both layouts; lead with cached and use
  legacy as a control. Separate calculation, write and read costs. Record rows,
  database/index bytes, peak memory and temporary/journal disk. Count actual SPY
  sessions and estimate full coverage with uncertainty.
- With explicit authorization to read runtime logs, first inspect existing
  `books_previous` and `books_kept` diagnostics from a real 07:00 update.
  Record dropped count/fraction and update context. These count books, not
  entry-only sheets. Only if the fields are missing, obtain authorization to
  capture before/after snapshots of a real update and replay on disposable copies.
- Omit (c)-only measurements unless the user chooses that investigation.

Exit: summarize settings, revisions, identities, environment/load and findings
here; raw output stays ignored. User chooses policy, layout and scope before S1.

### S1 — separate entries from exits

Requires S0 decisions and implementation authorization. Implement the chosen
layout, store identity and historical sheet policy; adapt both SQL selection and
scalar prepared scopes. Close only selected rows. Keep formulas outside the book
identity (`research.code_sources`); owner lanes remain stored, without fallback.

Exit: fast tier and affected existing heavy checks pass on synthetic fixtures.
Verify delayed entries, adjacent sessions, empty/short scopes, stopped stocks,
bankruptcy, both selection orders, legacy and latest. On the authorized bench,
compare the four prior parity cases: user random test, quarterly fixed
2013–2018, latest and development check. Require identical financial fields,
formula values/reasons and statuses; `scripts/check.py` finds zero differences.
Elapsed times, cache handles and new input identities are not financial parity.

### S2 — prepare coverage and qualify the workflow

Requires S1 parity. Implement cached precomputation, the chosen nightly policy,
progress and continuation in the unified chain, preserving existing readiness.

Exit: measure a full build and nightly maintenance. Private fixtures verify
on-demand misses, interrupted precomputation, ordinary readiness, cancellation,
restart and native Windows ownership/spawn. After complete precomputation, bench
new seeds and a repeat: zero sheets computed/written and financial parity. Profile
remaining costs until gains are marginal. Update contracts and the architecture
guide. Source completion does not establish deployed readiness.

## Open decisions for the user

1. **Coverage:** recommend all cached sessions first; legacy stays available on
   demand through the same sheet builder. Reject precomputing both without need.
2. **Freshness:** first ask whether to investigate (c); recommend no. Choose
   (a) versus (b) after S0. Accepting (c) changes tolerance/parity expectations.
3. **Layout:** recommend compact from S1, unless S0 disproves the disk concern.
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
still evaluate at runtime; edits affect no sheet identity. Any relaxation for
(c) is a separate user decision, not implied by this plan.

## Next

Claude reviews and commits. S0 has not run. Ask about (c) first, then obtain bench
and runtime-log authorization. Resolve decisions before authorizing code phases.
No merge, push, deployment or installed restart is authorized.
