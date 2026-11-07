# Typed storage: one fact store and faster backtests

Status: active

## Goal

Make preparation and backtests fast and simple. The user picks variables as
filters or rankings, queues backtests and tunes them; later a
reinforcement-learning loop runs fixed date plans on nightly updated data.
Prefer changes that delete code.

Financial results stay identical. Saved library and queue records open
unchanged. Each speed phase measures before and after on the real-data bench
and removes the largest measured cost.

## Starting point and measurements

Done: T1 (typed facts in `research.sqlite`), T2 (detail-mode explanations,
D1), T3 (JSON observation tables and reference evaluator deleted), P1, P2
(P2a, P2b, P2c), P3 (P3a with its follow-up, P3b, P3c1, P3c2, P3c3), P4,
the P4 review cleanup (P4c) and P5, the last speed phase.

Bench, P1 code (6367bef, research schema 13, daily 6): cold build 462 s
(research 377, daily 84). `research.sqlite` 2.24 GB; `schedules.sqlite` 1.10 GB
before books and 10.8 GB with 1,346 books. User test 474.3 s with books
computed and 180.8 s with books saved: about 140 ms per date over 1,326 dates;
the formula arithmetic is well under 1 ms of it.

Cold build, then the user test with books computed/saved: P2b 335 s,
483/181 s; P2c 360 s, 514/191 s (busier machine); P3a follow-up 305 s,
533.1/200.4 s; P3b 264 s, 398.3/166.0 s; P3c1 251 s, 381.1/153.0 s; P3c2
143 s, 368.4/147.0 s; P3c3 157 s, 365.7/149.5 s. Since P3c2 (research schema
19, daily 11): `research.sqlite` 1.26 GB; `schedules.sqlite` 3.2 MB before
books and 4.47 GB with 1,378. A one-session nightly update takes 157 s and
keeps 1,376 of 1,378 dated books.

P4 (688602e; every book recomputes once): cold build 168 s; user test
301.0/85.0 s; with books saved 107 → 63 ms per date over 1,344 dates. P4c
(a6095e6; research rebuilds and every book recomputes once): cold build 160 s
(research 157); user test 299.4 s (book writes 145.0, calculation wait 54.1,
selection 75.0) and 84.6 s (selection 80.7). Its profile (books saved, ms per
date, overlapping): formulas 11.1 (`columns._anchor` 4.5), `selection.select`
11.5, stored-condition checks 11.7, `book_store.lanes` 7.9, Executor loops
7.4, scope rows 7.1, writing 2.2.

P5 (50125bf; schemas unchanged; every book recomputes once; research does not
rebuild; all timings under user load, the user gaming on the machine): cold
build 176 s (research 172); user test 326.6 s with books computed (book
writes 180.8, calculation wait 57.1, selection 54.6) and 62.7 s with books
saved (selection 57.5; 47 ms per date).

The speed work stops after P5 (user, 2026-11-07: later gains would be
marginal). Left with books saved (P5 profile, ms per date): formulas 8.5,
`book_store.lanes` 7.8 (mostly the SQLite read), Executor loops 6.6, scope
rows 4.1, stored-condition checks 3.9, the lane rule 3.0, writing 3.0.

Not done: compact book rows (old T5). They would cut first-run book writes
(P4c: 145 s, about 84 million rows, 86% in `book_filters`), but they change
the book store format, `screening.select`'s SQL and the daily version and
help first runs only; the user's reruns and the planned RL loop reuse saved
books (user, 2026-11-07).

## Decisions

These are binding (2026-11-05/06).

- Kept: Explain keeps values, dates, reasons, the source file and its digest.
  Random-date results keep values and reasons, not step traces. Readers
  compare an accepted raw-file signature. No parallel trials; 8 book workers.
  D1 = delete (done in T2 and T3).
- **January books are removed** ("i agree with 1-4"): a January test is a
  12-month dated schedule from 1 January, and a January request is refused,
  never converted; `revalue.py` stays as a bench development check;
  `results/summary-exits.txt`, `results/baseline-history/` and
  `results/legacy/` are a frozen record; the January screener mode goes, latest
  stays. Kept: latest and dated books, both pools, saved library and queue
  records. Follow-ups ("use your recommendation"): every rebuild is a full
  rebuild; the default download covers the cached-price companies to the
  latest day; `--collect-report` and the stop tools go (`results/stops/`
  stays); old January results open in the dated view. D2 (journal) is
  superseded: research replaces a temporary file atomically.
- **No numeric targets** ("stop when gain become marginal"). The user decides
  after each speed phase whether to continue. The nightly update may be slow
  ("we can schedule it in mid night"). The in-place daily update was dropped;
  "Yes" below reverses that for the book cache only.
- **Approved outline** ("go ahead"): (1) one fact store, (2) faster backtests.
  Keep the raw-file signature, one formula gate and the size check before a
  run; merge the four "is the database current" layers; remove per-date
  re-admission and owner-value recomputation. The harness is a bench tool.
- **P3a follow-up** (2026-11-06, "agree"): (1) one value rule per day: the
  observation rule; a conflicting, non-USD or invalid row gives no value and a
  reason. (2) No `light` series. (3) One denial vocabulary, `books.REASONS`.
  (4, orchestrator) One book store: latest and dated books share one writer,
  tables and book-id space in `schedules.sqlite`; research keeps facts only.
- **Date rule owner:** `books.Screen` requires a saved SPY session on or after
  `rules.FIRST_DAY` for every book and formula root; the calendar keeps its
  request validation.
- **Kept books and the in-place book cache** (2026-11-06, "1. A 2. Yes"). (A)
  Unaffected saved books stay across nightly updates, by a change-day rule
  that the book code owns (`books.py`, next to `FORWARD_REACH`). Recomputing
  every stored book each night (about 4 min at 1,378 books, growing as the RL
  loop stores more) is measured for comparison only. (Yes) The book cache
  (`schedules.sqlite`) updates in place in one transaction: delete the dropped
  books and the old open book, rebind, then write the new open book. No
  temporary file, no `old` attach and no copy of kept books. Research facts
  stay a full rebuild. Both are P3c2.
- **Owner scope ids** (orchestrator, P3c1): new results record the real book
  id in a prepared `owner_scope`, not 0. Saved results keep theirs and are
  never rewritten. An id is a handle: it names one book only while the cache
  keeps it, and the in-place delete lets SQLite reuse the highest ids. A
  recorded `owner_scope.book` is a label, never a lookup key outside the
  operation or coverage generation that produced it.

## Future decisions (not decided here)

Automatic nightly downloads would end the explicit-button rule. A nightly
update must run after the 01:00 supervisor (`tools/deploy.py --start`) or in
the same step.

## Phase protocol

- One fresh agent runs one phase or slice in this worktree and stops hard at
  the exit. Order: build the new path, switch the readers, gather the
  real-copy evidence, then delete the old path.
- A phase owns every reader of a contract that it deletes. It updates the docs
  and the guide for its own changes in the same commit.
- Real-copy evidence comes before any deletion: harness parity against the
  previous phase; the whole-result digests equal; cold build time by stage;
  database sizes; user-test times with books computed and saved.
- Digest runs: the random test, quarterly fixed dates 2013–2018, latest, and
  the dev-check run (12-month fixed schedule 1996-01-01 → 2026-10-21, legacy
  pool, `ev_ebitda` ranks 1–50, default size floors).
- Exit checks: `TMPDIR=~/.cache/ebitda-ev-spread-tests/<name> python3
  tests/run.py`, then empty that folder; `--tier heavy` when Original scalar
  operations change; `python3 tests/check_records.py`; the guide updated (or
  reported as unaffected) and `node docs/architecture-guide/check.cjs`; AGENTS
  and `docs/` current; evidence and audit dispositions in the commit message.
- Between phases: an independent design review and an implementation audit;
  then the orchestrator shows the user the measured gain and the next cost.
- Merging to `main` needs the user's authorization each time.

## Phases

### P1. Cleanup (done, 6367bef and the review follow-up)

One formula gate (`definitions.require_program`); the always-true support
flags are deleted; a guard test runs every operation, statistic and /3
parameter through `columns.Formulas`.

### P2. Remove January books (done: e48c97a, 67e0e5f, 5b67b71, 4d66c8e, 83a40dc)

Dev check `scripts/check.py`. Removed the January mode with its readers,
writer, tables and report binding, all research reuse, `baseline.py`,
`revalue.py` script, `run.py` and the stop tools. `rules.FIRST_DAY` is the
1996 floor; a stored book row records only how a holding exited;
`rules.BANKRUPT` holds `(symbol, day of loss)`.

### P3. One fact store and one book function (done: f3312b7, e62f012, 3af5a28, 56d9483, 007c5e3, 10a6b35)

P3a wrote the store, P3b switched the readers, P3c1 gave each code role one
identity and the book store every read of its tables, P3c2 keeps unaffected
books and updates the book cache in place, and P3c3 fixed the review findings.

- Facts: `facts.observe` is the one value rule; a saved price, SPY or Treasury
  file that cannot be read stops research preparation. Bench raw: 24,489,611
  price rows in 7,231 files, 0 duplicate days, 0 non-USD, string, Boolean or
  `light` rows. One admission rule, `books.Screen.decide`, and one book
  function, `books.book` over `facts.BookFacts`; `book_store.store` writes
  latest and dated books.
- Identities (`research.code_sources(role)`, content digests): research
  (`facts`): `research.py`, `facts.py`, `books.py`, `rules.py`,
  `financial_inputs.py`, `parameters.py`, `cache_assets.py`, `market.py`;
  book (`books`): `books.py`, `metrics.py`, `rules.py`, `facts.py`
  (`BookFacts`, `facts.LEGACY`), `book_store.py`. Readers bind none. One
  research record; the daily binding {version, research content, book
  identity} has one reader, `daily.binding`. The view reads research through
  the attached schema of one connection.
- `book_store` reads: `record`, `open_book`, `completed`, `find`, `rows`
  (shape by the book), `lanes`, `valuations` (P4), `require_scope` (the one
  scope check) and `counts`.
- Kept books (`books.py`): `horizon`, `VISIBLE` (prices and market: the day;
  statements and annual: fiscal + `LAG`), `change_day`, `kept` (the open book
  never). Research schema 19 records `changes` = {base, rows}. Daily 11
  updates in one transaction: delete the dropped books and the old open book,
  rebind, write the new open book. Another version or book identity, or a
  full drop, starts from an empty file; so does a non-database, damaged or
  unbound file, while lock and I/O errors propagate. The diff kinds are
  exactly the `BookFacts` reads.
- Deviations: `FORWARD_REACH` is `ENTRY_SLACK` days; explanation lookups keep
  their stored `column` labels; dated scope rows are in symbol order
  (`prepared_period` is the book id; selection indices changed, holdings did
  not); a latest `INELIGIBLE_VALUATION` root carries no valuation; latest
  receipts keep `prepared_period` null; coverage report version 4 drops
  `price_binding`; the `MAX_HISTORY` reader bounds stay; a diff from another
  base keeps no book; equal values compare equal (0.0 = -0.0).
- Evidence (bench): each step kept the four digests and the dev check (0
  differences); row parity 0 mismatches (P3a: 75,346,082 filter values; P3c2:
  1,380 book pools); harness 16 runs, 0 different. A one-session nightly
  update keeps 1,376 of 1,378 books. With FY2026 reports for 5 companies,
  1,342 of 1,378 stay and all 1,342 recomputed equal (4,261,192 rows);
  recomputing them costs 139 s (8 workers) against 3–4 s to keep them. A
  forced full drop takes 0.15 s (71.6 s in place). Each restore matched the
  43,392-file raw manifest.

### P4. Book rows read in place (done, 688602e)

- A stored row is its root's admission: `books.book` stored only the
  companies that `Screen.decide` admitted. `scalar_execution._scope` returns
  the rows and `admission(i)`: the root and a decision with the stored
  candidate rank and valuation, built only for the rows that formulas or
  explanations need. A latest decision also names its report; its EBITDA
  comes from `book_store.valuations`. `Executor._admit`, the dated re-screen
  and the latest `View.admit` call are gone; coverage inspect uses the same
  admission. `View.admit` (`Screen.decide`) stays for explicit preview roots.
- Every scope root carries a prepared owner scope with its book id, and its
  owner lanes read that book (`View.prepared`, one book pool at a time).
  Explicit historical preview roots and derived contexts keep the dated owner
  policy through `books.owner_values`, which `books.book` also calls.
  `metrics.operating_margin` is the one margin formula.
- Values-only evaluation builds no evidence: no detach, JSON byte counts or
  budgets. Stored lanes and annual members build evidence for explained rows
  only. `Formulas` takes the restored projection; `Executor.__init__` keeps
  `require_strategy`. (P4 claimed one restore for coverage and preview; it
  took 6 and 3 compiles until P4c.)
- Decisions: coverage discovery stays the open book's pools (no caller needs
  a dated scope). A request names no book (P4c: a preview root is exactly
  company, pool, mode and date; coverage names only a discovered open-book
  scope), so no (entry, exit, pool) check was added.
- Deviations: explained owner lanes at latest roots now show their report
  dates, as dated roots do ("Explain keeps dates"); the dated owner policy
  reads legacy annual values through `BookFacts`, as books do, without the
  post-read `MAX_HISTORY` count; stored-lane evidence for every row, 16% of
  the before profile, went with the values-only rule.
- Signed zero: a stored REAL lane cannot hold -0.0, so a -0.0 owner value
  would read as 0.0. No formula output changed (below).
- Evidence: P4's bench files were lost; P4c re-ran the comparison against
  21843d0, with P4's code included (below).

### P4c. Review cleanup (done)

From an independent design review and an audit of P4 at 1f32292; both found
no wrong results.

- Preview roots name no book: `columns.require_roots` takes exactly {symbol,
  pool, mode, date}; the preview owner-scope loop, `_require`, the `_root`
  copies and the `kind` test are gone. Only `scalar_execution._scope`
  creates owner scopes, on its decisions; `prepared_scope` reads the decision.
- Coverage drops the constant `provider_admitted`, `provider_unavailable` and
  `provider_reasons` and their browser text; the recorded receipt key
  `provider_admitted_in_prepared_scope` stays (it equals `rows`).
- One stored-lane rule, `scalar_execution._canonical`: the canonical value or
  None. The row check converts only at a positive scale (equivalent).
- One compile per preview or coverage request: `from_wire` compiles once (its
  trailing restore repeated an idempotent compile); `check_options` returns
  the decoded capture; `inspect` takes the checked strategy. Before: 3
  (preview) and 6 (coverage). The user test still compiles 17 times per run
  (30 before; about 3 ms each): preflight, `execution_options`, `scalar_runs`
  and the recorded-plan checks, and `Executor.__init__`.
- `facts.legacy_annual` has a LIMIT bound (`MAX_HISTORY` × endpoints).
- Evidence (bench, a6095e6 against an exported 21843d0 copy; files kept in
  `~/bench/out/p4c-*`): the four digests equal. The 34 differing record
  fields are identities (input, projection, policy and executor
  fingerprints), hashes, timings, transfer bytes and, in 600 explained dated
  roots (requests, contexts, roots), `owner_scope` `dated` → `prepared` with
  the book id (+27,000 bytes). Dev check 0 differences. Fixture harness: 16
  runs, 15 equal; `owner-legacy/latest` differs only in 32 report-date
  fields (8 roots × 4; P4's deviation). Real copy: 22 scopes (per pool, 10
  evenly spaced stored dated books and the open book) × 64 rows, 43 programs
  with 826 outputs per root, less one 18-output program that both sides
  refuse in the 1997 legacy scope (FUTURE_DATE): 1,161,856 values, 37,605
  admission rows (every stored row) and 47,872 explained owner results equal;
  0 signed-zero changes. The website build and its four checks pass.

### P5. Four local speed fixes (done, 50125bf)

The P4c profile's selection, `_anchor`, lane and scope-row costs (user,
2026-11-07). Gains: user test with books saved, warm page cache, mean of two
interleaved rounds (97.3 s before; under user load).

1. Stored conditions once per row: with a stored ranking and filter-first
   order, the Executor checks the stored conditions and bounds;
   `selection.select` gets the remaining rows with the formula conditions;
   recorded indexes map back to the scope's rows. `selection.passes` lost its
   per-condition checkpoint and lambda table. −16.0 s.
2. `View.reports` returns date-typed reports; `columns._anchor` and
   `_report_ebitda` parse no dates. −4.2 s.
3. `book_store.lanes` returns one {symbol: value} map per lane (per pair
   component for a metric), used as they are.
4. `book_store.scope` reads the selection fields of every row in one read
   bounded by `MAX_CANDIDATES` + 1; `book_store.rows(symbols)` reads full rows
   for the selected rows only; `scalar_execution.scope_rows` is gone. Fixes 3
   and 4: −14.4 s (warm runs 61.7 and 63.6 s).

- Deviation: the plan named two `lanes` readers; the code had three (the
  Executor, `View.prepared`, `data.py`), and all three changed. The embedded
  page data stays byte-identical.
- Evidence (bench, 50125bf against the P4c outputs of a6095e6; files in
  `~/bench/out/p5-*`): the four digests equal; 26 record fields differ, all
  identities (daily binding, executor, selection and evaluator), hashes,
  timings and transfer bytes; dev check 0 differences; fixture harness 16
  runs equal; real copy, 22 scopes × 64 rows: 1,161,856 values, 37,605
  admission rows and 47,872 explained owner results equal, 0 signed-zero
  changes; the website build and its four checks pass. Interleaved pair,
  books saved, under user load: a6095e6 118.2/115.2 s, P5 78.2/76.5 s
  (−34% in each round; `~/bench/out/p5_ab.sh` reruns it).

## Review candidates

Reviews of 8de87fb (A design, B implementation), 227cdd1, 4db98dc, the P3a
review and the P3 review at 1e3596d (P3c1 scope items 1–6).

- Adopted: A.1 in part; A.2, A.4, B.2, B.6, B.8 (P3); A.3, B.9 (P3, P4);
  A.5, B.3, B.5, B.7, B.11 wording (P1); B.4 (P4); B.10. 227cdd1: one
  fact-store phase, one change-day rule, each phase owns its readers. 4db98dc:
  open January results from the artifact; P2 owns every reader; one repo dev
  check; no impossible special cases.
- Rejected: numeric targets and cost-first ordering (user); deleting the
  dated-owner readers (derived contexts keep that policy; P4 removes their
  budgets and evidence cost); rewriting history.
- Compact book rows (A.3, old T5): not done (user, 2026-11-07; see the
  measurements).

## Bench and tools

`~/bench/README.md` has the details.

- Copy: `~/bench/ebitda-real`. Never write the Windows runtime or copy back.
- Update the code: `WT=<worktree> bash ~/bench/scripts/update_bench.sh`
  (changed files, preparation, the user test twice). Run long jobs detached.
- User test: `python3 ~/bench/scripts/run_user_test.py full` from the bench
  folder (`~/bench/user-test.json`: 24 random quarterly trials, 2013–2026).
- Digests: `python3 ~/bench/out/result_digest.py OUT.json` from the bench
  folder.
- Harness: `~/bench/harness/` with `WT=` and a private `TMPDIR`, emptied
  afterwards; `results.py compare --oracle <export> --candidate <WT>` runs;
  `results.py files` compares saved worker outputs. `~/bench/out/p4c_scopes.py`
  (real-copy formula set) and `p4c_records.py` (record diff) keep an oracle.

## Risks

- Deployment: a schema change bumps its version and rebuilds once. The 01:00
  supervisor deploys `main`.
- Native Windows: attach, file replace and spawn workers need the native checks
  that AGENTS names before a merge.
- Scope creep: each phase stops at its exit. A new idea goes to the user first.

## Next

Pre-merge: heavy tier, independent over-engineering and leftover audit, plan
close-out, then the user's authorization for merge and deployment.
