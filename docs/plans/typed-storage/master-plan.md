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
(P2a, P2b, P2c) and P3 (P3a with its follow-up, P3b, P3c1, P3c2, P3c3).

Bench, P1 code (6367bef, research schema 13, daily 6): cold build 462 s
(research 377, daily 84). `research.sqlite` 2.24 GB; `schedules.sqlite` 1.10 GB
before books and 10.8 GB with 1,346 books. User test 474.3 s with books
computed and 180.8 s with books saved: about 140 ms per date over 1,326 dates;
the formula arithmetic is well under 1 ms of it.

P2 (digests equal P1; dev check 0 differences, 31 books, 1,550 holdings): P2b
cold build 335 s, user test 483/181 s (computed/saved); P2c 360 s, 514/191 s
on a busier machine. P2c relabels `Marked to date` as `Scheduled exit`.

P3a (f3312b7) and its follow-up (e62f012; research schema 16, daily 8): digests
equal P2c; row parity, 0 mismatches (24,489,611 price days, 1,378 dated books,
75,346,082 filter values). Latest reasons, old to new: legacy `MISSING_PRICE`
to `OUTSIDE_LEGACY_BUFFER` 2,775, `POOL_INELIGIBLE` to `INELIGIBLE_VALUATION`
9. Cold build 305 s; `research.sqlite` 1.32 GB; user test 533.1/200.4 s.

P3b (3af5a28; research schema 17, daily 9): the four digests equal 62b912d
(bytes differ in `prepared_period` and selection indices, P3b deviations). Dev
check 0 differences; latest roots and the book store equal the old snapshots;
harness 16 runs. Cold build 264 s (research 158, daily 106);
`schedules.sqlite` 0.80 GB before books, 5.27 GB with 1,378; user test
398.3/166.0 s.

P3c2 (007c5e3; research schema 19, daily 11): cold build 143 s;
`schedules.sqlite` 3.2 MB before books, 4.47 GB with 1,378; user test
368.4/147.0 s. A one-session nightly update takes 157 s and keeps 1,376 of
1,378 dated books; recomputing every book instead costs 210 s more (P3c2).

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

### P3. One fact store and one book function (done: f3312b7, e62f012, 3af5a28, 56d9483, 007c5e3)

P3a wrote the store (each raw file parsed once into the facts; one admission
rule `books.Screen.decide` and one book function `books.book` over
`facts.BookFacts`; `book_store.store`). P3b switched the readers. P3c1 gave
each code role one identity, the book store every read of its tables and
scopes their book ids. P3c2 keeps unaffected books and updates the book
cache in place.

Owns: `research.py`, `daily.py`, `facts.py`, `fact_view.py`, `books.py`,
`book_store.py`, `schedules.py`, `book_batch.py`, `screening.py`, the
`cache_assets` replace helper, the `sessions` readers, `operation_inputs.py`,
the scope readers (`scalar_execution`, `measure_observations`, `columns`,
`variable_coverage.py`), `prepared_input_coverage.py`, the `data_manager.py`
status, the website build (`rendering/data.py`, `rendering/state.py`), their
tests and docs.

Risks: row order (`selection.select` breaks ties by symbol; no result may
depend on rowid order); shared table names (name the schema in SQL); a worker
attaches the research file that the parent admitted (`PRAGMA cache_size` is
per schema).

#### P3a. Store written (done, f3312b7 and the follow-up e62f012)

- Measured on bench raw: 24,489,611 px `div` rows in 7,231 files, 0 duplicate
  days, 0 non-USD rows, 0 string or Boolean values, 0 `light` rows.
- `facts.observe` is the one value rule; a saved price, SPY or Treasury file
  that cannot be read stops research preparation.
- Deviations: `FORWARD_REACH` is `ENTRY_SLACK` days; explanation lookups keep
  their stored `column` labels.

#### P3b. Readers switched (done, 3af5a28)

- `View.admit` is `Screen.decide` for every root; dated books through
  `books.book` and `book_store.store`; `screening.select(db, book=None)` takes
  one book; `company_facts` merged into `companies`.
- Deviations: dated scope rows are in symbol order, so receipts'
  `prepared_period` is the book-store id and selection indices change
  (holdings, ranks and traces do not); a latest `INELIGIBLE_VALUATION` root
  (9) carries no valuation.

#### P3c1. One identity per role, the store's reads, scopes by id (done, 56d9483)

- Identities (`research.code_sources(role)`, the one role rule): content
  digests. Research (`facts`): `research.py`, `facts.py`, `books.py`,
  `rules.py`, `financial_inputs.py`, `parameters.py`, `cache_assets.py`,
  `market.py`. Book (`books`): `books.py`, `metrics.py`, `rules.py`,
  `facts.py` (`BookFacts`), `book_store.py`. Readers bind none. The raw
  signature has no code stamps; `research.identity` checks the code by
  content.
- One research record (`metadata`: version, inputs, prices, identity with
  version, latest date, code and content). The content identity hashes the
  code, the `fact_sources` digests and the universe and metrics bytes. The
  daily binding is {version, research content, book identity};
  `daily.binding` is its one reader (`connect`, `book_batch`, the view,
  `state.latest_book`, the coverage tool). One connection: the view reads
  research through the attached schema. Research schema 18, daily 10.
- `book_store`: `record`, `open_book` (one open book, also enforced by
  `store`), `completed`, `find`, `rows` (shape by the book), `lanes`,
  `require_scope` (the one scope check), `counts`. `screening` takes table
  names and `columns()` from it.
- Deleted: the facts metadata and its readers, the policy and price
  bindings, `calculation_sources`, `fingerprint`, the scope and metadata
  ceilings, `cache_access.daily()` and the old book-store readers.
- Deviations: coverage discovery lists the open book's pools only (dated
  books need P4's stored owner lanes); `_keep_books` keeps its SQL (P3c2
  deletes it); a book-code change also re-parses the daily price rows (the
  book identity binds `facts.observe`); latest receipts keep
  `prepared_period` null; coverage report version 4 drops `price_binding`.
- Evidence (56d9483, cold build): the four digests equal 1e3596d; records
  differ only in the listed fields (latest `owner_scope.book` names the open
  book, `input`, `projection`, receipt policy, block generation, timings).
  Dev check 0 differences; harness 16 runs, 0 different. Cold build 251 s;
  user test 381.1/153.0 s.

#### P3c2. Kept books, the in-place cache and the deletes (done, 007c5e3)

- Rule (`books.py`): `horizon(entry, exit)` = max(exit, entry +
  `FORWARD_REACH`); `VISIBLE` maps a diff kind's key to its visible day
  (`prices`, `market`: the day; `statements`, `annual`: fiscal + `LAG`);
  `change_day(diff)`; `kept(entry, exit, day)` (open book never).
- Research schema 19 records `changes` = {base, rows}: per kind and company
  the earliest changed row key against the replaced file (attached `old`).
  Price and annual files with an equal sha256 and fact-row code are skipped;
  statements and SPY/Treasury rows are always compared.
- Daily 11, one transaction in place: `book_store.delete` of the dropped books
  and the old open book, rebind, the new open book. Another VERSION or book
  identity empties the file first.
- Deleted: daily `prices`, `sessions`, `treasuries`, `treasury10`, the refresh
  evidence, `BOOK_INPUTS`, `_price_rows`, `_prices`, `_book_inputs`,
  `_first_difference` (now the diff's row comparison), `_dated_change`,
  `_keep_books`; research `treasury10`, `financial_inputs`, `_replace`
  (`cache_assets.replace` serves it and `publish_bytes`).
- Deviations: the `MAX_HISTORY` reader bounds stay (no code they guard went,
  B.10; `test_variable_coverage` requires bounded leaf reads); a diff whose
  base is not the bound research (two research builds before one daily
  update) keeps no book; a build whose tables differ from the replaced
  file's (a schema or catalog change) has no base; equal values compare
  equal (0.0 = -0.0; book tables are REAL).
- Tests: `KeptBookTests` (one per kind just after the horizon, company
  removal, names and listing, one-session append, short reach, interrupted
  update, book identity, older version, another base, current cache).
- Evidence (bench, 007c5e3). (a) Cold build: the four digests equal
  3fe3d50; book store parity with the 3fe3d50 store, 1,380 book pools
  (75,404,972 filter values), 0 mismatches; dev check 0 differences; harness
  16 runs, 0 different. Cold build 142.7 s; `research.sqlite` 1.26 GB. (b)
  One session appended to 3,985 price files, SPY and Treasury: nightly 156.9 s
  (3,246 files skipped; book cache 3.0 s); 1,376 of 1,378 books kept. (c)
  FY2026 reports for 5 companies: nightly 139.9 s; change day 2026-09-28;
  1,342 of 1,376 kept. (d) Recomputing 1,342 book pools took 210.1 s (8
  workers) plus 71.6 s to delete them in place, against 3-4 s to keep them.
  Each restore matched the raw sha256 manifest (43,392 files).

#### P3c3. Review fixes (done, see the commit)

- S1: the book identity also digests `facts.LEGACY`, the legacy annual fields
  that `BookFacts.legacy_annual` reads. Fact-row code defines them
  (`financial_inputs.ENDPOINTS`, the catalog), so an edit there now drops
  every book.
- The diff kinds are exactly the `BookFacts` reads (its docstring): the
  `companies` kind and the removed-company loop went; statements cover both.
- S3: when no stored book stays, `daily.prepare` replaces the cache with an
  empty file before `BEGIN`; a failure then leaves the empty, unbound cache.
  C2: only a non-database, damaged or unbound file starts from empty; lock
  and I/O errors propagate. `_empty` removes an older version's `.building`.
- Deviation: the empty-file path runs whenever every stored book drops, which
  includes a change day on or before `FIRST_DAY`.
- Tests: SPY only, `year10` only, price and annual files added or removed,
  the legacy field list, an interrupted full drop, a foreign file and a lock
  error.

### P4. Book rows read in place

Scope:

- A stored book row is its root's admission: present means admitted, with its
  candidate rank and valuation. `Executor` stops calling `view.candidates`
  (`books.candidates` over every company) per dated date, and `View.admit` for
  latest scopes.
- Owner lanes at a stored-book root of every kind read the book's stored
  lanes. Derived `at` and `lookback` contexts keep the dated owner policy
  (AGENTS).
- Values-only evaluation builds no evidence: no JSON encoding and no detach.
  Detail mode builds evidence for selected rows only. Keep the explanation
  block shape.
- One operating-margin formula in `metrics.py` (today also in `columns.py`).
- One formula check per operation: `Formulas` takes the restored projection;
  `variable_coverage.inspect` drops its extra calls; `Original.preview`
  restores the capture once. `Executor.__init__` keeps its restore, the
  execution boundary for queued rows.
- Book ids are handles (Owner scope ids). If a request may name a dated book
  id, check it by (entry, exit, pool) or reject ids that requests supply.
- Decide whether coverage discovery lists dated books once their owner lanes
  read stored rows.
- Then profile 20 scopes and the user test, and list what is left (scope-row
  reads, report dates parsed per root, `filter_values` reads, first-run books,
  result encoding). Compact book rows (old T5) only if the profile says so.

Deletes: dated re-admission in `Executor._admit`; the `View.admit` chain for
scope roots; evidence building in values-only owner lanes; `_OWNER_BYTES`,
the `budget=` parameters and the JSON byte counting in `broad_reports`,
`legacy_financial_history` and `measure_observations.dated`; the repeated
formula checks.

Owns: `scalar_execution.py`, `columns.py`, `fact_view.py` (`View`),
`original_calculations.py` (`preview`), `measure_observations.py`,
`metrics.py`, `scalar_runs.py`, `variable_coverage.py`, their tests.

Risks:

- Signed zero: stored `filter_values` are REAL and lose -0.0, which dated
  owner lanes keep today. The harness shows any change.
- Explained dated owner lanes change their evidence source. List the changed
  fields and compare the rest.

Exit: the protocol checks, heavy tier included. Real copy: harness parity of
values and reasons against P3 (owner formulas, 64 rows per scope); digests
equal; user-test time with books saved; the profile. Then the user decides
about P5.

### P5 and later (only if the user continues)

One measured cost per phase, with the same protocol. Stop when the gain
becomes marginal.

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
- Deferred: compact book rows (A.3, old T5), decided by P4's profile.

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
  afterwards; `results.py compare --oracle <export> --candidate <WT>` runs.

## Risks

- Deployment: a schema change bumps its version and rebuilds once. The 01:00
  supervisor deploys `main`.
- Saved records: test every January artifact version in the dated view
  before deleting the January view.
- Native Windows: attach, file replace and spawn workers need the native checks
  that AGENTS names before a merge.
- Scope creep: each phase stops at its exit. A new idea goes to the user first.

## Next

P4 after the independent review of P3c.
