# Typed storage: one fact store and faster backtests

Status: active

## Goal

Make preparation and backtests fast and simple for the user's workflow. The
user picks variables as filters or ranking metrics, queues backtests and tunes
them. Later a reinforcement-learning loop runs fixed date plans, and the data
is updated every night. Prefer changes that delete code.

Financial results stay identical. Saved library and queue records open
unchanged. There are no numeric targets. Each speed phase measures before and
after on the real-data bench and removes the largest measured cost.

## Starting point

T1–T3 are complete on this branch:

- T1 writes typed facts (`stock_days`, `market_days`, `annual_facts`,
  `fact_sources`, `latest_admission`) into `research.sqlite`; `columns.py`
  reads them through `facts.View`.
- T2 takes explanations from the column evaluator's detail mode (D1).
- T3 deletes the JSON observation tables, the provider and the reference
  evaluator.

## Measurements

Bench, research schema 13, daily cache 6. T3 code:

- Cold build 490 s. Research 396 s: inputs 3, companies 172, dated facts 192,
  independent verification 21, publication 6. Daily 93 s: copy 1, prices 90.
- `research.sqlite` 2.24 GB (`stock_days` 1.86 GB). `schedules.sqlite`
  1.10 GB before books and 10.8 GB with 1,346 books (`filter_values` 4.1 GB
  plus a 3.9 GB index; `prices` 1.0 GB).
- User test 508.5 s with books computed and 183.0 s with books saved: about
  140 ms per date over 1,326 dates. The formula arithmetic is well under 1 ms
  of it.
- The four whole-result digests equal T2.

P1 code (6367bef), cold build:

- Four digests equal T3. Cold build 462 s. Research 377 s: inputs 3,
  companies 163, dated facts 184, verification 19, publication 5. Daily
  84 s: prices 82. Sizes unchanged. P1 changed no preparation step.
- User test 474.3 s with books computed (1,326 books) and 180.8 s saved.

## Decisions

These are binding (2026-11-05/06).

- Kept: Explain keeps values, dates, reasons, the source file and its digest.
  Random-date results keep formula values and reasons, not step traces.
  Readers compare an accepted raw-file signature. The Numba engine is deleted.
  No parallel trials; 8 book workers.
- **D1 = delete.** Done in T2 and T3.
- **D2 replaced.** "yes, you need to do that. it is a bit different from common
  database usage." The research database is the only source of truth.
  `results/summary-exits.txt` is rendered from it. Remove the report/database
  publication journal (`data/research.sqlite.publication.json`), its pending
  files, `Baseline.recover`, the three full-database SHA-256 hashes and the
  per-connect report check. The historical cutoff 2026-10-21 is a fixed
  setting. A leftover journal means: do a full build from raw, then remove the
  journal. Keep the previous report and the changed-years audit in
  `results/baseline-history/`. `data/deployment.pending.json` stays.
- **No numeric targets.** "i want the speed is reasonable. seting a number does
  not make sense before we even work on that. stop when gain become marginal".
  After each speed phase the orchestrator shows the user the gain and the next
  largest cost. The user decides whether to continue.
- **The nightly update may be slow.** "even longer wait is good we can schedule
  it in mid night". The in-place one-minute daily update (old T4) is dropped.
- **Approved outline** ("go ahead"): (1) one fact store, (2) faster backtests.
- **Validation verdicts.** Keep the independent January engine; run it only
  when the new January result differs from the stored verified one. Remove the
  journal and its hashes. Keep the raw-file signature. Merge the four "is the
  database current" layers into one. Remove the reuse digests if the nightly
  full rebuild is chosen. Keep one formula gate. Keep the size check before a
  run. Remove per-date re-admission and owner-value recomputation. The parity
  harness is a development tool on the bench, not part of the app.

## Future decisions (not decided here)

- Automatic nightly downloads would change the rule that downloads start only
  from an explicit data-panel button.
- A nightly update must run after the 01:00 publication supervisor
  (`tools/deploy.py --start`) or in the same step.

## Phase protocol

- One fresh agent runs one phase in this worktree. It stops hard at the exit.
- Inside a phase: build the new path, switch the readers, gather the real-copy
  evidence, then delete the old path.
- A phase owns every reader of a contract that it deletes.
- Real-copy evidence comes before any deletion: harness parity against the
  previous phase; the four whole-result digests equal; cold build time by
  stage; database sizes; user-test times with books computed and saved.
- Exit checks:
  - `TMPDIR=~/.cache/ebitda-ev-spread-tests/<name> python3 tests/run.py`, then
    empty that folder;
  - `--tier heavy` as well when the phase changes Original scalar operations;
  - `python3 tests/check_records.py`;
  - the architecture guide updated (or reported as unaffected), and
    `node docs/architecture-guide/check.cjs`;
  - AGENTS feature contracts and `docs/` current;
  - the evidence and audit dispositions in the commit message.
- Between phases: an independent design review and an implementation audit.
  Then the orchestrator shows the user the measured gain and the next cost.
- Merging to `main` needs the user's authorization each time.

## Phases

### P1. Cleanup (done, 6367bef)

- One formula gate: `columns.require_program` with the fixed namespace list.
  `variables/selection.py` is deleted. The gate runs
  `definitions.require_program` once. Tests cover the full catalog, every
  operation and every statistic.
- `research.signature()` leaves out `raw/download-coverage.json`.
- The named leftovers and stale docs are removed or fixed.
- Deviation: the three always-equal catalog support flags became one
  `original` flag from the gate's inventory.
- Left for P4: `columns.Formulas` and `variable_coverage` check the program
  again after the gate.

### P2. Single-source baseline (D2)

Scope:

- Research preparation builds a temporary file, verifies it, writes
  `baseline_result` and `baseline_revision` into it and publishes it with one
  atomic replace. No journal.
- Every preparation, including the "already current" path, renders
  `results/summary-exits.txt` from the database's verified result. It writes
  the file atomically only when the bytes differ.
- The historical cutoff is the fixed setting `rules.ASOF`. The report leaves
  `signature()`. Every reader takes that setting or the database value written
  from it.
- The independent engine runs only when the new January result differs from
  the verified result in the current database, or when none exists. Equal
  means exact equality at full precision.
- History keeps today's rule: when the January result changes at full precision
  or the report bytes change, write the previous report and the changed-years
  audit to `results/baseline-history/<generation>/` before the replace, and
  record `baseline_revision`. Existing history folders stay verbatim.
- A leftover journal forces a full build from raw. After publication, remove
  the journal and its `*.pending` files. Add no other reader of the old format.
- `--collect-report` exports the report rendered from the verified result in
  the same database read.

Deletes: the journal, `report.pending`, `research.pending`, the three
full-database hashes, `Baseline.recover`, `check_ready` and
`baseline_report_sha` on every connect, `cutoff(text)` as an input, the
`_PriorUnits` baseline-reuse condition, and the `Baseline.previous` code that
rebuilds a result for a database without `baseline_result` (with one atomic
file, that means a first run).

Owns: `backtest/inputs/baseline.py`; the Baseline call sites in `research.py`;
`facts.py` (`View.bounds` and its `historical_through` reader only);
`website/rendering/data.py` and `build.py` (cutoff);
`tools/ops/prepared_input_coverage.py` (cutoff); `tools/ops/deploy.py`
(`export_runtime_report`); `tools/ops/offline_input_copy.py`;
`tests/test_baseline.py`, `test_offline_preparation.py`,
`test_offline_input_copy.py`, `test_research_inventory.py`, the export part of
`test_deployment.py`; the AGENTS research-database paragraph;
`docs/research-workflow.md`; `data/README.md`.

Risks:

- A stop between the database replace and the report write leaves an old
  report. The next preparation renders it again. No reader treats the report
  text as a source.
- Fixtures set the cutoff through the report text today. They must patch the
  setting instead.
- Keep the first-run rule: unavailable prices stay null.

Exit: the protocol checks; tests for a leftover journal, a stop before and
after the replace, and a report re-render. Real copy: the rendered report
equals the current report byte for byte; four digests equal; a rebuild with
unchanged inputs skips the independent engine; publication time measured.

### P3. One fact store and one book function

Before P3 starts, the user answers the open question: after P3, a data-panel
rebuild after a manual download is a full rebuild (about 8 min at T3). Is that
acceptable? P1 and P2 do not depend on it.

If one agent cannot hold P3, split it at "store written / readers switched",
never at the line between the research and daily files.

Scope, in this order:

1. Measure first on the bench: a one-session append through the current reuse
   path against a forced full build, and the count of duplicate-day rows in
   the px `div` and `light` series, `spy-div.json` and `treasury.json`.
2. Parse each raw file once into every fact column: the observation fields;
   the book `price` and `adjusted` columns of `stock_days`; the book SPY close,
   3-month and 10-year columns of `market_days`; and the legacy annual values
   from `annual_facts` (the legacy fields of `financial_inputs.ENDPOINTS`,
   valid values only). `statements` and `companies` stay once, in research.
3. One book-row function in `books.py` computes the January books (31 years ×
   2 pools), the latest rows and the dated books through one price-lookup
   interface over the facts.
   - It is the admission rule. Preview roots call it too.
   - It is the only reader of legacy annual values and the 10-year yield. The
     View's derived-context readers call the same readers.
   - One writer and one row shape (with `ebitda`): January and latest books in
     research, dated books in `schedules.sqlite`.
   - `prepared_baseline` reads the baseline prices from the facts, not from a
     separate `baseline_prices` pass.
4. Switch the readers. `daily`, `View`, `compute_period` and the book workers
   attach research read-only. `schedules.sqlite` holds only dated books and
   one binding record.
   - One identity record in research: schema version, accepted raw signature
     (including each price file), the content identity of the code that
     computes rows, and the latest date. The daily binding names it and the
     book code. Editing a reader must not invalidate books.
   - A prepared scope is a stored book (period row and pool), named by book id
     instead of a threaded `owner_scope`. One check in the book store; coverage
     discovery lists stored books.
   - The kept-book rule below.
5. Delete in one step (list below).

Kept books, one change-day rule for every input that a book reads:

- Visible day: a price, SPY or Treasury row, its own day; a statement or legacy
  annual value, its known day (fiscal + 90); an added or removed price file,
  its first row day; an added or removed company, its earliest known statement.
- The first change day is the minimum over changed rows. Preparation compares
  the new facts with the previous research file before the replace, and
  records that day with the previous identity.
- A book bound to that identity stays when max(exit, entry + FORWARD_REACH) is
  before the change day. Write this read horizon once, next to
  `FORWARD_REACH` in `books.py`. Only a change in book code drops every book.
- If the measurement shows that recomputing the dropped books costs little,
  delete the kept-book rule instead.

Deletes: the January loop in `research.prepare`, `prepare_metrics`,
`snapshot`, `latest_snapshot`, `bars`, `before`, `after`, `ten_year_yield` and
`baseline_prices`; `_PriorUnits` and the reuse digests (`_bounded_digest`,
`_rows_digest`, `_reuse_scope`, `REUSE_MARGIN`, `facts.copy_stock`); daily
`prices`, `sessions`, `treasuries` and the copied tables; research `treasury10`
and `financial_inputs`; `daily._prices`, `_copy_research`,
`_first_difference`, `_dated_change`; `fact_metadata`, `facts.require`,
`policy_binding`, `prepared_bindings`, `prepared_price_binding`, the daily
engine stats and `_code` digests; `latest_admission`; the scope list with
`MAX_SCOPES` and `MAX_METADATA_BYTES`; the `MAX_HISTORY` checks in the
replaced readers; the three owner-scope checks.

Owns: `research.py`, `daily.py`, `facts.py`, `financial/books.py`,
`engines/original/schedules.py`, `book_batch.py`, the `sessions` readers
(`robustness.py`, `calendar_requests.py`, `scalar_runs.py`,
`original_calculations.py`), `operation_inputs.py`; the scope readers
(`scalar_execution._scope` and `evaluate_preview`,
`measure_observations.prepared_scope`, `columns.require_roots`,
`scalar_runs.prepared`, `variable_coverage.py`);
`tools/ops/prepared_input_coverage.py`, `website/server/data_manager.py`
(status); their tests; the AGENTS dated-schedule, data-panel and research
paragraphs; `docs/schedule-calendar.md`, `docs/research-workflow.md`.

Risks:

- Duplicate days. The January series takes the max (backward) or min (forward)
  value of a day; `_price_rows` takes the max adjusted value and the last light
  value in file order; Treasury uses `asof_yield` on a sorted list, the daily
  tables `INSERT OR REPLACE` in file order. If the count is not zero and the
  January and dated rules disagree on real data, keep one function with two
  price adapters and document the difference next to it. Never keep two loops.
- Row order: `selection.select` breaks ties by symbol; verify that no result
  depends on rowid order.
- The derived legacy annual values must equal the JSON values bit for bit.
- Shared table names in both files: name the schema in SQL.
- A worker must attach the research file that the parent admitted. `PRAGMA
  cache_size` applies per schema; measure book computation through the attach.
- Results record `input` and `projection`. Keep the fields; fill them from the
  one identity. Old results open unchanged.

Exit: the protocol checks, heavy tier included. Real copy, before deletion:
every new fact column and book row equals the old table or JSON input (0
mismatches); harness parity; four digests equal. Then: cold build time; sizes;
kept books after a one-session append (T0: 1,343 of 1,346) and after a nightly
update that adds some annual reports.

### P4. Book rows read in place

Scope:

- A stored book row is its root's admission: present means admitted, with its
  candidate rank and valuation. `Executor` stops calling `view.candidates`
  (`books.candidates` over every company) per dated date, and `View.admit` for
  January and latest scopes.
- Owner lanes at a stored-book root of every kind read the book's stored
  lanes. Derived `at` and `lookback` contexts keep the dated owner policy
  (AGENTS).
- Values-only evaluation builds no evidence: no JSON encoding and no detach.
  Detail mode builds evidence for selected rows only. Keep the explanation
  block shape.
- One operating-margin formula in `metrics.py` (today also in `columns.py`).
- Then profile 20 scopes and the user test, and list what is left:
  scope-row reads, report dates parsed again per root, `filter_values` reads,
  first-run book computation, result encoding (78 MB). Compact book rows (old
  T5) only if the profile shows that the book tables cost.

Deletes: dated re-admission in `Executor._admit`; the admission chain in
`View.admit` for scope roots; evidence building in values-only owner lanes;
`_OWNER_BYTES`, the `budget=` parameters and the JSON byte counting in
`broad_reports`, `legacy_financial_history` and `measure_observations.dated`;
the `View` members that only served them.

Owns: `scalar_execution.py`, `columns.py`, `facts.py` (`View`),
`measure_observations.py`, `financial/metrics.py` (operating margin),
`scalar_runs.py`, `variable_coverage.py` (admission), their tests.

Risks:

- Signed zero: stored `filter_values` are REAL and lose -0.0. Dated owner
  lanes keep it today. The harness shows any change; January and latest lanes
  already read stored values.
- Explained dated owner lanes change their evidence source. List the changed
  fields and compare the rest.

Exit: the protocol checks, heavy tier included. Real copy: harness parity of
values and reasons against P3, with the owner formula set on 64 rows per
scope; four digests equal; user-test time with books saved; the 20-scope
profile. Then stop. The user decides about P5.

### P5 and later (only if the user continues)

One measured cost per phase, with the same protocol. Stop when the gain
becomes marginal.

## Review candidates

Reviews of 8de87fb (A design, B implementation) and the design review of this
plan at 227cdd1.

Adopted:

- A.1 in part: the per-scope work is a required phase (P4), and real-copy
  gates come before deletions.
- A.2, A.4, B.2, B.6, B.8: P3. A.3: P3 (one admission function, book ids) and
  P4. A.5, B.3, B.5, B.7: P1. B.4: P4. B.9: P3 (admission chain, owner-scope
  checks) and P4 (operating margin). B.11 in part: P1 fixes the AGENTS harness
  wording.
- B.10: a bound goes with the code it guards (P3 and P4 name them).
- 227cdd1 review: one fact-store phase with one book function; one change-day
  rule; each phase owns every reader of a contract it deletes.

Rejected:

- Numeric targets (A.1): the user rejected them.
- Ordering by measured cost before storage (A.1): the user approved the
  outline that puts the fact store first.
- The in-place update and its unit algorithm (from-scratch design, A.2): the
  user dropped the in-place update. A full rebuild is one path.
- Deleting `View.broad_reports`, `legacy_financial_history` and
  `legacy_treasury` (A.3): derived contexts keep the dated owner policy, so
  these readers stay. P4 removes their budgets and evidence cost.
- Rewriting history for B.11: only on the user's request.

Deferred: compact book rows (A.3, old T5), decided by P4's profile.

Resolved: B.1 (real-copy parity at T2 and the T3 digests).

## Bench and tools

`~/bench/README.md` has the details.

- Copy: `~/bench/ebitda-real`, about 17 GB at T3. Never write the Windows
  runtime or copy anything back.
- Update the code: `WT=<worktree> bash ~/bench/scripts/update_bench.sh`
  (changed files, preparation, the user test twice). Run long jobs detached.
- User test: `~/bench/user-test.json` (24 random quarterly trials,
  2013–2026, ranks 1–30, cached pool, three built-in conditions and debt/EV <
  50%). Run `python3 ~/bench/scripts/run_user_test.py full` from the bench
  folder.
- Digests: `python3 ~/bench/out/result_digest.py OUT.json` from the bench
  folder (random test, quarterly fixed dates 2013–2018, January 1996–2026,
  latest). T3 digests: `~/bench/out/t3-digest.json`.
- Harness: `~/bench/harness/` with `WT=` and a private `TMPDIR`, emptied
  afterwards. Each phase extends the storage comparison it needs.
- Profiles: `~/bench/scripts/profile_real_scope.py`, `table_sizes.py`.

## Risks

- Deployment: each schema change bumps its version and rebuilds the prepared
  caches once. The 01:00 supervisor deploys `main`. A leftover baseline journal
  on the runtime forces a full build (P2).
- Native Windows: attach, file replace and spawn workers need the native checks
  that AGENTS names before a merge.
- Scope creep: each phase stops at its exit. A new idea goes to the user first.

## Next

P2 after the independent review of P1.
