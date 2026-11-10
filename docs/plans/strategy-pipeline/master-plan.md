# Strategy pipeline

Status: active

Approved by the user on 2026-11-10 ("agree all"). Next phase: P1.
Source baseline: `main` at `89fe1d6`.

## Goal

Let users build a linear stock-selection workflow from visible blocks.
Support Rank A → Filter B → Rank C → Filter D and consecutive ranks or filters.
Use one selection path.

## Agreed decisions

- Universe is fixed first and holds only market and pool. There is no branching.
- Size floors (minimum/maximum cap, minimum EV), sector, exchange and the old
  minimum-yield/maximum-multiple limits are ordinary Filter blocks. New chains
  place them right after Universe by default. Filters may use the inclusive
  comparisons and metadata equality that the selection specification already
  supports (`le`, `ge`, `eq`), so old `rank_first` maps exactly.
- Every Rank keeps an inclusive range `rank_from`–`rank_to`. "Top N" means 1–N.
  A chain needs at least one Rank. At most 50 blocks, the existing condition ceiling.
- Speed has no numeric gate. Claude measures baseline and candidate on the bench
  and reports the result to the user.
- Step evidence is recorded for selected holdings only, not every candidate.
- The offline latest-picks screen stays as it is. Latest chains run on the
  local service. Deleting the offline path is a separate decision.
- Each Rank selects from its incoming survivors. It accepts any current source
  and highest/lowest direction. Filters accept the same sources: `metric:*`,
  `filter:*`, financial parameters, measures and exact saved formula revisions.
- Final order, ranks and ranking value come from the last Rank. Later filters
  keep those ranks, add no replacements and equal-weight the survivors.
- Existing `filter_first` means Filters → Rank(a–b).
  Existing `rank_first` means Rank(a–b) → Filters. Each period ranks independently.
- Preserve prepared-pool admission, calendars, returns, rounding, cash periods,
  missing-value rules and deterministic ties: candidate rank, null first, then symbol.
- Read existing stored lanes once per scope. Formula values are per company
  (annual statistics only, nothing cross-sectional), so evaluate each distinct
  formula once per row, only for rows still alive at the first step that uses
  it. This generalises today's filter-first survivor evaluation and is exact.
- No data rebuild. Keep pipeline work outside `books.py`, `metrics.py`,
  `rules.py`, `book_store.py` and `facts.py`. Leave `research.code_sources`
  unchanged. Preserve freshness, cancellation, ownership and output ceilings.

Why floors are Filter blocks: current `rank_first` applies size, sector,
exchange and yield/multiple bounds after ranking (`screening.select`,
`selection.select`). Keeping them in Universe would change old results.

## Request and record contract

Introduce `strategy-intent/2` and `strategy-capture/2` under `options.strategy`.
Capture Universe pool/bounds and an ordered `steps` list. Keep market in
`options.market`, displayed inside Universe, without a duplicate field.
A Rank records source, direction and inclusive range. A source Filter records
source, comparison and threshold with its units and exact comparison scale.
Universe-field filters retain their original field semantics.
Capture ordered source roles, built-in descriptors and complete formula closures.
Parameters and measures remain formula captures.

Old flat requests and capture/1 retain their accepted shapes and canonical bytes.
Translate them only in memory for execution or explicit copying into the builder.
Preserve their complete-pair eligibility, stored comparison scales and defaults.
Do not add pair requirements to general scalar ranks.
Remove missing values only when the active step needs them.

Reuse artifact 4, scalar codec 2, financial contract 2 and durable database schemas.
For capture/2, extend existing detached evidence with one entry per step: its
rank, or null for a Filter. Values stay in the step lanes; a Universe field step
reads the holding's own field. P1 records these;
P3 displays them.
Existing eager artifacts 1–2, artifact 3/codec 1 and artifact 4/codec 2 keep opening.
Old results without step evidence show it as unavailable; never reconstruct it.
Do not rewrite library records, queue requests, receipts, recorded plans or hashes.
Opening, comparing and exporting stay independent of current inputs and catalogs.
Unchanged queued edits retain their original payload. Explicit changes create a
new checked capture. Keep recorded engines and seeds. Add no speculative readers.

## Phases

### P1 — Engine, format, exact parity and diagnostics

**Scope:** Extend admission and
the scalar selector to execute ordered steps. Replace selection-order branches
with boundary translation. Read each required stored lane once. Reuse evaluated
sources across steps. Preserve the SQL adapter's bounded reads and pushdown where
they are needed for parity and speed; add no general query compiler.
Record step evidence without changing financial reduction order.
Add `market`, `ranking_source_kind` and `step_count` to both `backtest.run`
paths through diagnostics. Source kind means the last Rank's `builtin`/`formula`;
step count excludes Universe. Translate legacy settings for comparable counts.
Log controlled enums and numbers only.

**Exit evidence:** Private synthetic checks cover both pools and orders, ranks
20–40, ties, signed zero, missing lanes, inclusive bounds, repeated ranks,
empty selections and fixed/seeded-random schedules across three markets.
Frozen main-era requests and evidence pass through queue/library reopen,
retry, held edit, transfer and export. Claude's bench proves exact financial
parity and unchanged cache identities, and reports measured speed.

**Main risk:** A compatibility translation changes ranking membership or binary64 comparisons.

### P2 — Strategy-page block builder

**Scope:** After P1 passes, give `StrategyDraft` one ordered draft with fixed
Universe and add/remove/move controls for Rank and Filter. Reuse the current
source picker, units and formula editor. Provide buttons and keyboard operation;
no canvas framework. Preserve held-edit protection and asynchronous revision checks.
Replace selection-order and single-rank controls. Support fixed/random submissions.
Keep general latest-chain submission unavailable until P3.

**Exit evidence:** Browser checks build both example chains, move repeated ranks,
restore ranks 20–40, copy old settings and save/cancel held queue edits without
running them. Verify source round trips and draft/result separation.
Review a synthetic Windows preview through Tailscale before integration.

**Main risk:** Reordering or delayed source loading silently changes captured intent.

**P2 notes:** Stored EV/EBITDA pairs are both present or both absent (admission
requires EBITDA > 0 and EV > 0; the 3-year metric returns neither component when
its average is not positive), so copying an old strategy to a chain that ranks
the yield lane alone is exact and needs no compatibility mechanism. For the same
reason, and because admitted market cap and EV are positive, a zero minimum adds
no step. A copy that needs more than 50 steps is refused; a held queue edit
loads every step. Only an unchanged held
queue edit keeps its original payload; other submissions capture a chain.

### P3 — Results and server latest screens

**Scope:** Display each selected holding's recorded value, unit, rank/pass
outcome and source for each step. Reuse bounded evidence readers for tables and
exports. Run latest chains through the server selector. Preserve exact-session
prices, listed status, market date and absence of future returns. Keep the
offline latest-picks path unchanged.

**Exit evidence:** Detached saved results display/export without preparation.
Server latest chains match equivalent built-in screens. Test repeated-source
steps, old evidence and all markets.
Repeat the bench with evidence display/export costs separated from calculation.

**Main risk:** Evidence growth exceeds existing limits or latest admission changes.

## Bench, deletion and completion

Claude runs `~/bench/inc-p3c`; this planning task accesses no real cache.
Compare baseline and candidate on identical prepared inputs, dates and seeds.
Include built-in/formula ranks, both pools/orders, ranks 20–40 and longer chains.
Compare every financial field,
holding order and rank exactly, including signed zero. New evidence metadata is
separate from financial parity; old stored bytes remain unchanged.

Delete obsolete selection-order execution branches and split built-in/scalar
draft transitions as their replacements pass.
Keep only compatibility readers and boundary adapters required by main-era data.
Run fast tests and records checks before each implementation commit; run relevant
heavy tests before integration. Update affected standing docs and the architecture
guide in each phase. Bench output stays in ignored scratch; summarize evidence
in commit messages. Integration and publication need separate authorization.

## Next

P1 starts with a fresh Codex session: a short design, Claude's review, then
implementation. Source completion does not establish installed readiness.
