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

Done: T1 (typed facts in `research.sqlite`, read through `facts.View`), T2
(detail-mode explanations, D1), T3 (JSON observation tables and reference
evaluator deleted), P1, P2 (P2a, P2b, P2c) and P3a with its follow-up.

Bench, P1 code (6367bef, research schema 13, daily 6): cold build 462 s
(research 377, daily 84). `research.sqlite` 2.24 GB; `schedules.sqlite` 1.10 GB
before books and 10.8 GB with 1,346 books (`filter_values` 4.1 GB plus a
3.9 GB index; `prices` 1.0 GB). User test 474.3 s with books computed and
180.8 s with books saved: about 140 ms per date over 1,326 dates; the formula
arithmetic is well under 1 ms of it.

P2 (digests equal P1; dev check 0 differences, 31 books, 1,550 holdings): P2b
(research schema 14, daily 7) cold build 335 s, `research.sqlite` 2.06 GB, user
test 483/181 s (computed/saved); P2c 360 s, 514/191 s on a busier machine. P2c
relabels `Marked to date` as `Scheduled exit` (random 30,091, custom 450
holdings).

P3a (f3312b7, schema 15, facts 2): digests and result bytes equal P2c; row
parity against fd043e3, 0 mismatches (24,489,611 price days, 1,378 dated books,
75,346,082 filter values). Cold build 365 s (research 260, daily 104);
`research.sqlite` 1.81 GB; user test 512.8/193.9 s.

P3a follow-up (e62f012; facts 3, research schema 16, daily 8): the four
digests equal 42ad9f8 (result bytes differ by 9 and 2 bytes of embedded
timings; the two user-test runs of one code differ by 59); dev check 0
differences. Parity against the 42ad9f8 databases, 0 mismatches: every research
table; the observation fields and the valid values against the old book
columns (24,489,611 price days, SPY 8,004, both yields 7,955, no signed zero);
daily prices, sessions and yields; `company_facts` (11,054, 5,986 listed);
the latest book in the book store (3,409 rows, 6,129 pairs, 58,890 filters,
`candidates` 3,366); `books.book` through `book_store.store` for all 1,378
dated books (75,346,082 filter values; 233 s, 8 workers). Reasons, old to new,
with equal values: latest (22,108 decisions) legacy `MISSING_PRICE` to
`OUTSIDE_LEGACY_BUFFER` 2,775 and to `MISSING_PRICE` 8, `POOL_INELIGIBLE` to
`INELIGIBLE_VALUATION` 9, the rest unchanged; dated (5,705,115 candidates)
every denial equals the old admission reason, with no exit denial. Cold build
305 s: research 188 (companies 185), daily 117 (prices 111, latest book 1.9).
`research.sqlite` 1.32 GB (`stock_days` 1.11 GB, 0.49 GB less);
`schedules.sqlite` 0.86 GB before books, 10.55 GB after. User test 533.1 s
computed, 200.4 s saved (a quiet rerun saved 188.5 s; P3a 512.8/193.9).

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
  ("we can schedule it in mid night"); the in-place daily update is dropped.
- **Approved outline** ("go ahead"): (1) one fact store, (2) faster backtests.
  Keep the raw-file signature, one formula gate and the size check before a
  run; merge the four "is the database current" layers; remove per-date
  re-admission and owner-value recomputation. The harness is a bench tool.
- **P3a follow-up** (2026-11-06, "agree"): (1) one value rule per day: the
  observation rule; a conflicting, non-USD or invalid row gives no value and a
  reason; the book price columns are gone. (2) No `light` series: valuation
  and returns read the dividend-adjusted closes; lookups take no column.
  (3) One denial vocabulary: the dated codes plus `NOT_LISTED` and
  `UNKNOWN_COMPANY` (`POOL_INELIGIBLE` becomes `INELIGIBLE_VALUATION`),
  written once as `books.REASONS`; P3b makes it visible. (4, orchestrator)
  One book store: latest and dated books share one writer, tables and book-id
  space in `schedules.sqlite`; research keeps facts only (and the old latest
  tables until P3b).
- **Date rule owner:** `books.Screen` requires a saved SPY session on or after
  `rules.FIRST_DAY` for every book and formula root; the calendar keeps its
  request validation.

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

Dev check `scripts/check.py` (one Original custom run in the
`revalue.calculate` shape). Removed the January mode with its readers, writer,
tables and report binding, all research reuse, `baseline.py`, `revalue.py`
script, `run.py` and the stop tools. `rules.FIRST_DAY` is the 1996 floor; a
stored book row records only how a holding exited; `rules.BANKRUPT` holds
`(symbol, day of loss)`. Deviations (owner-less latest roots, sector and
exchange choices, the offline-copy manifest version 2) are in the P2 commits.

### P3. One fact store and one book function

P3a (steps 1–3) writes the store; P3b (steps 4–5 and the kept-book rule)
switches the readers and deletes.

1. Measure the duplicate-day rows (done in P3a).
2. Parse each raw file once into the facts (done).
3. One admission rule and one book function over the facts port (done):
   `books.Screen(day, facts, open_book)` with `decide(symbol, pool,
   exit_day=None) -> (holding, None) | (None, reason)`; `books.admit` (entry
   valuation) and `books.close` (exit); `books.book(entry, exit, pool, facts)`;
   `facts.BookFacts` (reports, cached, companies, price, spy, treasury,
   ten_year, legacy_annual); `book_store.store` writes the one row shape.
4. Switch the readers. `daily`, `View` (admission and preview roots through
   `Screen.decide`), `compute_period` and the book workers read the research
   facts read-only and the book store.
   - One identity record in research: schema version, accepted raw signature
     (with each price file), the content identity of the row code, and the
     latest date. The daily binding names it and the book code. Editing a
     reader must not invalidate books.
   - A prepared scope is a stored book (period row and pool), named by book id
     instead of a threaded `owner_scope`. One check in the book store; coverage
     discovery lists stored books.
   - One `book` id replaces `periods.year`, `snapshots.year`,
     `screening_metrics.year`, `filter_values.year` and `period_pools.period_id`;
     the constant `mode` column goes. `screening.select(db, book=None)` and
     `scalar_execution.scope_rows` take one book: no inclusive range, no
     `PARTITION BY s.year`, no `historical` flag. Tests stop building one
     database from `research.SCHEMA + daily.DATED_SCHEMA`.
   - One atomic-replace helper in `cache_assets`, with the Windows sharing
     retry, serves `publish_bytes`, `research.prepare` and `daily.prepare`.
   - The kept-book rule below.
5. Delete in one step (list below).

Kept books, one change-day rule for every input that a book reads:

- Visible day: a price, SPY or Treasury row, its own day; a statement or legacy
  annual value, its known day (fiscal + 90); an added or removed price file,
  its first row day; an added or removed company, its earliest known statement.
- The first change day is the minimum over changed rows. Before the replace,
  preparation compares the new facts with the previous research file and
  records that day with the previous identity.
- A book bound to that identity stays when max(exit, entry + FORWARD_REACH) is
  before the change day. Write this read horizon once, next to
  `FORWARD_REACH` in `books.py`. Only a change in book code drops every book.
  The open (latest) book is never kept.
- If a measurement shows that recomputing the dropped books costs little,
  delete the kept-book rule instead.

Deletes: `prepare_metrics`, `latest_snapshot`, `before`, `after`,
`ten_year_yield`, `books.snapshot`; daily `prices`, `sessions`, `treasuries`,
`periods`, `snapshots`, `period_pools` and the copied tables;
`daily._price_rows`, `_prices`, `_copy_research`, `_first_difference`,
`_dated_change`, `histories`; research `latest_snapshots`, `treasury10`,
`financial_inputs` and the year-0 latest rows; `fact_metadata`,
`facts.require`, `policy_binding`, `prepared_bindings`,
`prepared_price_binding`, the daily engine stats and `_code` digests;
`latest_admission`; the scope list with `MAX_SCOPES` and
`MAX_METADATA_BYTES`; the `MAX_HISTORY` checks in the replaced readers; the
three owner-scope checks; `research._replace`; the `mode` columns.

Owns: `research.py`, `daily.py`, `facts.py`, `books.py`, `book_store.py`,
`schedules.py`, `book_batch.py`, `screening.py`, the `cache_assets` replace
helper, the `sessions` readers (`robustness.py`, `calendar_requests.py`,
`scalar_runs.py`, `original_calculations.py`), `operation_inputs.py`, the
scope readers (`scalar_execution`, `measure_observations.prepared_scope`,
`columns.require_roots`, `variable_coverage.py`),
`prepared_input_coverage.py`, the `data_manager.py` status, the website build
(`rendering/data.py`, `rendering/state.py`), their tests and docs.

Risks:

- Row order: `selection.select` breaks ties by symbol; verify that no result
  depends on rowid order.
- Shared table names in both files: name the schema in SQL.
- A worker attaches the research file that the parent admitted. `PRAGMA
  cache_size` is per schema; measure book computation through the attach.
- Results record `input` and `projection`; fill them from the one identity.

Exit: the protocol checks, heavy tier included. Real copy, before deletion:
every new fact column and book row equals the old table or JSON input (0
mismatches); harness parity; digests equal; the dev check passes. Then: cold
build time; sizes; kept books after a one-session append (T0: 1,343 of 1,346)
and after a nightly update that adds some annual reports.

#### P3a. Store written (done, f3312b7 and the follow-up)

- Measured on bench raw: 24,489,611 px `div` rows in 7,231 files, 0 duplicate
  days, 0 non-USD rows, 0 string or Boolean values, 0 `light` rows;
  `spy-div.json` 8,004 and `treasury.json` 7,955 rows, 0 duplicate days.
- `facts.resolve` reads and parses each price, SPY and Treasury file once;
  `facts.observe` is the one value rule (daily prices use it too).
  `cache_assets.valid_series` checks validity without building rows. Facts
  version 3 (`company_facts` added; book columns gone), research schema 16,
  daily 8 (book store added; `prices` keeps `adjusted` only).
- A saved price, SPY or Treasury file that cannot be read stops research
  preparation; a stock file must be a mapping with a `div` list.
- Book store `backtest/inputs/book_store.py`: `books(book, entry, exit, spy,
  candidates)`, `book_pools`, `book_rows` (with `known`, entry price and
  `ebitda`), `book_metrics`, `book_filters`, WITHOUT ROWID. Daily preparation
  writes the latest book (no exit, research's latest date). `candidates` is
  the latest metadata's eligible financials; `treasury` and
  `legacy_candidates` went (no reader).
- Deviations: `FORWARD_REACH` is `ENTRY_SLACK` days (the second forward lookup
  went with `light`); explanation lookups keep their stored `column` labels
  (`price` for valuation, `adjusted` for returns); the old-rule test oracle
  and the unused `tests/daily_fixture.py` are deleted now; the reference
  engine reads `div` only and `fetch_bulk.py` no longer fetches SPY `light`;
  daily `sessions` and `treasuries` keep their own parse until P3b.

#### P3b. Readers switched, then deletions

Steps 4–5 and the kept-book rule. `View.admit` and `latest_admission` switch to
`Screen.decide`, so the visible reasons change (old `MISSING_PRICE` splits into
`OUTSIDE_LEGACY_BUFFER`, `MISSING_CACHED_PRICES` and `MISSING_PRICE`; an
unknown historical root becomes `UNKNOWN_COMPANY`). View evidence records its
lookups through a recording facts port. Dated books move into the book store.
The website build reads the latest book from the book store (asof = entry,
eligible financials = `candidates`) and binds the latest book's identity, not
the `schedules.sqlite` file stamp; `website/build.py` alone then needs the
daily cache. `research.py status` reads the latest book too.

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
- Then profile 20 scopes and the user test, and list what is left (scope-row
  reads, report dates parsed per root, `filter_values` reads, first-run books,
  result encoding). Compact book rows (old T5) only if the profile says so.

Deletes: dated re-admission in `Executor._admit`; the `View.admit` chain for
scope roots; evidence building in values-only owner lanes; `_OWNER_BYTES`,
the `budget=` parameters and the JSON byte counting in `broad_reports`,
`legacy_financial_history` and `measure_observations.dated`; the repeated
formula checks.

Owns: `scalar_execution.py`, `columns.py`, `facts.py` (`View`),
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

Reviews of 8de87fb (A design, B implementation), 227cdd1, 4db98dc and the P3a
review (M1, M2, S1–S3 and the small items: adopted in the follow-up).

- Adopted: A.1 in part; A.2, A.4, B.2, B.6, B.8 (P3); A.3, B.9 (P3, P4);
  A.5, B.3, B.5, B.7, B.11 wording (P1); B.4 (P4); B.10. 227cdd1: one
  fact-store phase, one change-day rule, each phase owns its readers. 4db98dc:
  open January results from the artifact; P2 owns every reader; one repo dev
  check; no impossible special cases.
- Rejected: numeric targets and cost-first ordering (user); the in-place
  update (user); deleting the dated-owner readers (derived contexts keep that
  policy; P4 removes their budgets and evidence cost); rewriting history.
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

P3b, after the review of the P3a follow-up.
