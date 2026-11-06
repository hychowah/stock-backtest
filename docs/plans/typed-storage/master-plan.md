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
evaluator deleted), P1, P2a and P2b.

Bench, research schema 13, daily cache 6, P1 code (6367bef; the four digests
equal T3, which equal T2):

- Cold build 462 s. Research 377 s: inputs 3, companies 163, dated facts 184,
  verification 19, publication 5. Daily 84 s: prices 82.
- `research.sqlite` 2.24 GB (`stock_days` 1.86 GB). `schedules.sqlite`
  1.10 GB before books and 10.8 GB with 1,346 books (`filter_values` 4.1 GB
  plus a 3.9 GB index; `prices` 1.0 GB).
- User test 474.3 s with books computed and 180.8 s with books saved: about
  140 ms per date over 1,326 dates. The formula arithmetic is well under 1 ms
  of it.

P2a (67e0e5f, idle bench): the dev check finds 0 differences from
`revalue.calculate(2026-10-21)` over 31 books and 1,550 holdings (also on P1
code); the frozen report differs only in its 2026 row (marked 2026-10-20), and
with `--through 2026-10-20` nothing differs. Random, custom and latest
digests equal P1; the fixed-run digest equals e48c97a. Evidence is 4.8 KB
smaller (2 recorded scopes, not 64). Cold build 483 s: research 394 s
(companies 171, dated facts 190, verification 21), daily 89 s. Sizes as P1.
User test 484.2 s computed, 181.7 s saved. e48c97a ran beside test jobs
(508 s; 540/209 s), so P1 is the timing baseline: no measurable change.

P2b (4d66c8e, research schema 14, daily 7, cold build): the four digests equal
P2a; evidence of random and custom runs is 2 bytes larger (header only). The
dev check finds 0 differences; the frozen report differs only in 2026. Fixture
harness parity (`results.py`, oracle 8dc5c72): 16 runs equal. The real-data
build, `check_screener.py` (26 screens), range and contribution checks pass.
Cold build 335 s: research 249 s (inputs 1.5, companies 65, dated facts 182,
publication 0.003), daily 86 s (prices 83). `research.sqlite` 2.06 GB
(`stock_days` 1.86 GB; −172 MB); `schedules.sqlite` 1.10 GB before books,
10.80 GB after. User test 483.1 s computed, 180.6 s saved: no change.

## Decisions

These are binding (2026-11-05/06).

- Kept: Explain keeps values, dates, reasons, the source file and its digest.
  Random-date results keep values and reasons, not step traces. Readers
  compare an accepted raw-file signature. No parallel trials; 8 book workers.
  D1 = delete (done in T2 and T3).
- **January books are removed.** "you can remove january book … it is useless
  and that why we add random seed to avoid extreme case by picking one date".
  On four points, "i agree with 1-4":
  1. A January test is a 12-month dated schedule from 1 January. The January
     mode goes. Saved January results open without calculating. A January
     request is refused clearly, never converted.
  2. `revalue.py` stays as a development check of the book code, run on the
     bench. No build or startup runs it.
  3. `results/summary-exits.txt`, `results/baseline-history/` and
     `results/legacy/` are a frozen record. Nothing regenerates or touches
     them.
  4. The browser's January screener mode goes, with its contributors, pies,
     static top-50 fallback, exports and parity checks. Latest stays.

  Kept: latest and dated books, both pools, saved library and queue records.
- **Follow-up answers** ("use your recommendation"):
  (a) every rebuild is a full rebuild (about 8 min), data-panel rebuilds
  included, and all research reuse goes; (b) the default download covers the
  companies with cached prices up to the latest available day; (c) the tracked
  report is the frozen record, and `--collect-report` goes without collecting;
  (d) delete the stop tools, `results/stops/` stays; (e) old saved January
  results open in the dated result view.
- **D2 replaced**, now superseded: no report is published. Research writes a
  temporary file and replaces it atomically. No journal.
- **No numeric targets.** "i want the speed is reasonable. seting a number does
  not make sense before we even work on that. stop when gain become marginal".
  The user decides after each speed phase whether to continue.
- **The nightly update may be slow.** "even longer wait is good we can schedule
  it in mid night". The in-place one-minute daily update (old T4) is dropped.
- **Approved outline** ("go ahead"): (1) one fact store, (2) faster backtests.
  Verdicts: keep the raw-file signature, one formula gate and the size check
  before a run; merge the four "is the database current" layers; remove
  per-date re-admission and owner-value recomputation. The harness is a bench
  tool.

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
  from P2a the dev-check run (12-month fixed schedule 1996-01-01 → 2026-10-21,
  legacy pool, `ev_ebitda` ranks 1–50, default size floors). It replaces the
  January run.
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

One formula gate, the language check `definitions.require_program`;
`variables/selection.py`, `columns.require_program` and the always-true
support flags are deleted. A guard test runs every operation, statistic and /3
parameter through `columns.Formulas`. The signature leaves out the coverage
ledger. Leftovers and stale docs are fixed.

### P2. Remove January books

It precedes P3 because it deletes what P3 would merge. Two slices, one fresh
agent each. Re-check every dependency by grep first.

#### P2a. Dev check and readers (done, e48c97a and 67e0e5f)

- Dev check: `backtest/engines/reference/check.py`, one Original custom run
  (12 months from 1 January 1996, legacy pool, `ev_ebitda` ranks 1–50, default
  floors) in the `revalue.calculate` shape. `books.py` names it.
- Readers removed: the January mode (`require_mode` refuses it at `/mode` in
  the run route), `scalar_runs.prepared`, the browser January view, pools,
  exports and historical selection, `attribution.py`, the January prepared
  scopes and `historical_through` readers, the report recovery and row, the
  baseline audit and data scope, `--collect-report`, `research.py screen` and
  the January parts of the coverage tool (version 2). `ResultArtifacts.decode`
  projects saved January results (versions 1–2) into dated periods.
- Deviations (code over plan): deploy kept its REPORT special cases for P2b,
  because the writer still rewrote the runtime report; an owner-less latest
  root keeps stored latest lanes; sector and exchange choices come from all
  companies; Historical backtest opens without a run; `check.py` stayed out of
  `calculation_sources`.
- Unlisted readers: the bench harness January scope; the report copy in
  `offline_input_copy.py` and the `research.connect` binding (P2b).
- Visible changes: coverage lists latest scopes only until P3; previews on
  January sessions use the dated owner policy; the data panel defaults to
  cached-price stocks through today; the build writes no `returns.csv`,
  `holdings.csv` or `valuations.json`.

#### P2b. Writer, reuse and study constants (done)

- P2a follow-up (5b67b71): one January refusal, at the run route; stale docs
  and CSS; the local default end date; three latest parity cases.
- Removed: the January writer (loop, tables, `verify_reference`,
  `prepared_baseline`, `screening.historical`, `baseline.py`, the report in
  `signature()` and in `research.connect`), all research reuse (`_PriorUnits`,
  the scope and digests, `facts.copy_stock`), the deploy REPORT seed, the
  offline-copy report, `scripts/revalue.py`, `run.py` and the stop tools.
  Research schema 14 is a full build that replaces the file atomically and
  deletes the old publication journal.
- `daily.DATED_SCHEMA` holds the daily-only tables with the same DDL (daily 7);
  `research.SHARED_SCHEMA` holds the one definition of the shared tables.
- Study constants live in `engines/reference/legacy.py`; `rules.FIRST_DAY` is
  the one 1996 floor.
- The dev check is a leaf: `differences` and the dated field lists stay,
  `scripts/check.py` runs it, `calculation_sources()` lists only row and book
  code, and nothing outside `engines/reference/` imports that package.
- Bench harness: the `january:*` scopes are gone.
- Deviations (code over plan): `calculation_sources` also drops `screening`,
  `selection` and `measure_observations`, which only select or read stored
  rows. `legacy_downloads.py` goes with `legacy.main`, its only caller; the
  data panel downloads every dataset. Deploy keeps REPORT unmanaged, because a
  managed REPORT stops the first deployment wherever the runtime copy differs;
  only the seed, extraction and warning go. The offline-copy manifest is
  version 2 and refuses version 1. `facts.resolve` loses `days`;
  `paths.LEGACY` and `STOPS` go.
- Unlisted readers: `tests/check_paths.py` (imported the deleted scripts), the
  fictional workspace's bootstrap report, `test_offline_preparation`,
  `results/README.md`; `test_phase09_legacy` compares its frozen expectations
  without the baseline, report and January rows.

### P3. One fact store and one book function

If one agent cannot hold P3, split it at "store written / readers switched",
never at the line between the research and daily files.

Scope, in this order:

1. Measure first: the count of duplicate-day rows in the px `div` and `light`
   series, `spy-div.json` and `treasury.json`.
2. Parse each raw file once into every fact column: observation fields; the
   book `price` and `adjusted` columns of `stock_days`; the book SPY close,
   3-month and 10-year columns of `market_days`; legacy annual values from
   `annual_facts` (the `financial_inputs.ENDPOINTS` legacy fields, valid values
   only). `statements` and `companies` stay once, in research.
3. One book-row function in `books.py` computes the latest rows and the dated
   books through one price-lookup interface over the facts.
   - It is the admission rule, with the 1996 floor from `rules.py`. Preview
     roots call it too.
   - It is the only reader of legacy annual values and the 10-year yield. The
     View's derived-context readers call the same readers.
   - One writer and one row shape (with `ebitda`): latest books in research,
     dated books in `schedules.sqlite`.
4. Switch the readers. `daily`, `View`, `compute_period` and the book workers
   attach research (facts and latest books) read-only. `schedules.sqlite` holds
   only dated books and one binding record.
   - One identity record in research: schema version, accepted raw signature
     (with each price file), the content identity of the row code, and the
     latest date. The daily binding names it and the book code. Editing a
     reader must not invalidate books.
   - A prepared scope is a stored book (period row and pool), named by book id
     instead of a threaded `owner_scope`. One check in the book store; coverage
     discovery lists stored books.
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
- If a measurement shows that recomputing the dropped books costs little,
  delete the kept-book rule instead.

Deletes: `prepare_metrics`, `latest_snapshot`, `bars`, `before`, `after` and
`ten_year_yield`; daily `prices`, `sessions`, `treasuries` and the copied
tables; research `treasury10` and `financial_inputs`; `daily._prices`,
`_copy_research`, `_first_difference`, `_dated_change`; `fact_metadata`,
`facts.require`, `policy_binding`, `prepared_bindings`,
`prepared_price_binding`, the daily engine stats and `_code` digests;
`latest_admission`; the scope list with `MAX_SCOPES` and `MAX_METADATA_BYTES`;
the `MAX_HISTORY` checks in the replaced readers; the three owner-scope checks.

Owns: `research.py`, `daily.py`, `facts.py`, `books.py`, `schedules.py`,
`book_batch.py`, the `sessions` readers (`robustness.py`,
`calendar_requests.py`, `scalar_runs.py`, `original_calculations.py`),
`operation_inputs.py`, the scope readers (`scalar_execution`,
`measure_observations.prepared_scope`, `columns.require_roots`,
`variable_coverage.py`), `prepared_input_coverage.py`, the `data_manager.py`
status, their tests and docs.

Risks:

- Duplicate days: latest rows take a day's max value; `_price_rows` the max
  adjusted and the last light value in file order; Treasury `asof_yield` on a
  sorted list against `INSERT OR REPLACE` in file order. If the rules disagree
  on real data, keep one function with two price adapters and document the
  difference. Never two loops.
- Row order: `selection.select` breaks ties by symbol; verify that no result
  depends on rowid order.
- The derived legacy annual values must equal the JSON values bit for bit.
- Shared table names in both files: name the schema in SQL.
- A worker attaches the research file that the parent admitted. `PRAGMA
  cache_size` is per schema; measure book computation through the attach.
- Results record `input` and `projection`; fill them from the one identity.

Exit: the protocol checks, heavy tier included. Real copy, before deletion:
every new fact column and book row equals the old table or JSON input (0
mismatches); harness parity; digests equal; the dev check passes. Then: cold
build time; sizes; kept books after a one-session append (T0: 1,343 of 1,346)
and after a nightly update that adds some annual reports.

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

Reviews of 8de87fb (A design, B implementation), 227cdd1 and 4db98dc.

- Adopted: A.1 in part; A.2, A.4, B.2, B.6, B.8 (P3); A.3, B.9 (P3, P4);
  A.5, B.3, B.5, B.7, B.11 wording (P1); B.4 (P4); B.10 (a bound goes with
  the code it guards). 227cdd1: one fact-store phase, one change-day rule,
  each phase owns its readers. 4db98dc: open January results from the
  artifact; P2 owns every reader; no in-between design; one repo dev check;
  no impossible special cases.
- Rejected: numeric targets and cost-first ordering (user); the in-place
  update (user); deleting the dated-owner readers (derived contexts keep that
  policy; P4 removes their budgets and evidence cost); rewriting history.
- Deferred: compact book rows (A.3, old T5), decided by P4's profile.
- Resolved: B.1.

## Bench and tools

`~/bench/README.md` has the details.

- Copy: `~/bench/ebitda-real`. Never write the Windows runtime or copy back.
- Update the code: `WT=<worktree> bash ~/bench/scripts/update_bench.sh`
  (changed files, preparation, the user test twice). Run long jobs detached.
- User test: `python3 ~/bench/scripts/run_user_test.py full` from the bench
  folder (`~/bench/user-test.json`: 24 random quarterly trials, 2013–2026).
- Digests: `python3 ~/bench/out/result_digest.py OUT.json` from the bench
  folder. P2a replaces its January run with the dev-check run.
- Harness: `~/bench/harness/` with `WT=` and a private `TMPDIR`, emptied
  afterwards. From P2a it calls the repo dev check. P2b removed its
  `january:*` scopes and its `variables.selection` import (a local copy of the
  77 parameters); `results.py compare --oracle <export> --candidate <WT>` runs.

## Risks

- Deployment: a schema change bumps its version and rebuilds once. The 01:00
  supervisor deploys `main`.
- Saved records: test every January artifact version in the dated view
  before deleting the January view.
- Native Windows: attach, file replace and spawn workers need the native checks
  that AGENTS names before a merge.
- Scope creep: each phase stops at its exit. A new idea goes to the user first.

## Next

P3 after the independent review of P2.
