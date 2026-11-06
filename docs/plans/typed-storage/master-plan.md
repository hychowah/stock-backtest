# Typed storage: one fact store and faster backtests

Status: active

## Goal

Make preparation and backtests fast and simple for the user's workflow. The
user picks variables as filters or ranking metrics, queues backtests and tunes
them. Later a reinforcement-learning loop runs fixed date plans, and
the data is updated every night. Prefer changes that delete code.

Financial results stay identical. Saved library and queue records open
unchanged. There are no numeric targets. Each speed phase measures before and
after on the real-data bench and removes the largest measured cost.

## Starting point

T1–T3 are complete on this branch:

- T1 writes typed facts (`stock_days`, `market_days`, `annual_facts`,
  `fact_sources`, `latest_admission`) into `research.sqlite`.
  `backtest/variables/columns.py` reads them through `facts.View`.
- T2 takes explanations from the column evaluator's detail mode (D1).
- T3 deletes the JSON observation tables, the provider and the reference
  evaluator.

Measured on the bench at the T3 code (research schema 13, daily cache 6):

- Cold build 490 s. Research 396 s: inputs 3, companies 172, dated facts 192,
  independent verification 21, publication 6. Daily 93 s: copy 1, prices 90.
- `research.sqlite` 2.24 GB (`stock_days` 1.86 GB). `schedules.sqlite`
  1.10 GB before books and 10.8 GB with 1,346 books (`filter_values` 4.1 GB
  plus a 3.9 GB index; `prices` 1.0 GB).
- User test 508.5 s with books computed and 183.0 s with books saved: about
  140 ms per date over 1,326 dates. The formula arithmetic is well under 1 ms
  of it. A T0 profile put most of the per-date time in admission candidates,
  scope-row reads, company facts, selection and writing.
- The four whole-result digests equal T2.

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
  setting, not text read from the report. A leftover journal means: do a full
  build from raw, then remove the journal. Keep the independent `revalue`
  agreement when January results change. Keep the previous report and the
  changed-years audit in `results/baseline-history/` when the report text
  changes. `data/deployment.pending.json` is separate and stays.
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
- Real-copy evidence comes before any deletion: harness parity against the
  previous phase; the four whole-result digests equal; cold build time by
  stage; database sizes; user-test times with books computed and saved.
- Exit checks:
  - `TMPDIR=~/.cache/ebitda-ev-spread-tests/<name> python3 tests/run.py`, then
    empty that folder;
  - `--tier heavy` as well when the phase changes Original scalar operations
    (`test_original_long_window.py`);
  - `python3 tests/check_records.py`;
  - the architecture guide updated (or reported as unaffected), and
    `node docs/architecture-guide/check.cjs`;
  - AGENTS feature contracts and `docs/` current;
  - the evidence and audit dispositions in the commit message.
- Between phases: an independent design review and an implementation audit.
  Then the orchestrator shows the user the measured gain and the next cost.
- Merging to `main` needs the user's authorization each time.

## Phases

### P1. Cleanup

Scope:

- One formula gate. `variables/selection.py` and `columns.require_program`
  hold the same inventory (77 parameters). Keep one gate with the namespace
  check. Run `definitions.require_program` once per check. Derive the catalog
  support flags that `variable-workspace.js` shows from that gate.
- Remove `raw/download-coverage.json` from `research.signature()`. No
  preparation reads it.
- Stale docs: `docs/plans/project-structure/source-map.md` (six deleted
  modules); "Original reference execution" in
  `website/browser/variable-workspace.html`; the guide's "Both backends
  support…", "Phase 7 adds callable compiled arithmetic", "observation_identity
  stage" and coverage-ledger freshness sentence; the AGENTS sentence that calls
  the bench harness the oracle (it is a development tool outside the
  repository).
- Dead and test-only leftovers: `measure_observations.policy_fingerprint` and
  `_LOADED`, the test-only `scalar_execution.preview`, `facts.TABLES`, the
  `facts.prepared_view` pass-through, the `_Trace` note about the deleted
  reference evaluator's numbering.

Deletes: the second gate, the ledger signature entry, the leftovers.

Owns: `backtest/variables/selection.py`, the gate in `columns.py`,
`variable_authoring.py`, the gate call in `strategy_requests.py`,
`research.signature`, the named leftovers and docs, the AGENTS Custom
variables paragraph and the tests of removed helpers.

Risks: the gate must refuse every parameter and operation that the column
evaluator lacks; test the full catalog. The signature change rebuilds prepared
data once.

Exit: the protocol checks. Real copy: four digests equal; cold build time.

### P2. Single-source baseline (D2)

Scope:

- Research preparation builds a temporary file, verifies it, writes
  `baseline_result` and `baseline_revision` into it and publishes it with one
  atomic replace. No journal.
- Every preparation, including the "already current" path, renders
  `results/summary-exits.txt` from the database's verified result. It writes
  the file atomically only when the bytes differ. Unchanged results keep
  identical bytes.
- The historical cutoff is the fixed setting `rules.ASOF`. The report leaves
  `signature()`. `website/rendering/data.py` takes the cutoff from the
  database.
- The independent engine runs only when the new January result differs from
  the verified result in the current database, or when none exists. Equal
  means exact equality at full precision.
- When the report text changes, write the previous report and the
  changed-years audit to `results/baseline-history/<generation>/` before the
  replace, and record `baseline_revision`. Existing history folders stay
  verbatim.
- A leftover journal forces a full build from raw. After publication, remove
  the journal and its `*.pending` files. Add no other reader of the old format.
- `--collect-report` exports the report rendered from the verified result in
  the same database read.

Deletes: the journal, `report.pending`, `research.pending`, the three
full-database hashes, `Baseline.recover`, `check_ready` and
`baseline_report_sha` on every connect, `cutoff(text)` as an input, and the
`_PriorUnits` baseline-reuse condition.

Owns: `backtest/inputs/baseline.py`; the Baseline call sites in `research.py`
(recover, through, publish, connect, the prior check); `website/rendering/data.py`
(cutoff only); `tools/ops/deploy.py` (`export_runtime_report`);
`tools/ops/offline_input_copy.py`; `tests/test_baseline.py`,
`test_offline_preparation.py`, `test_offline_input_copy.py`,
`test_research_inventory.py`, the export part of `test_deployment.py`; the
AGENTS research-database paragraph; `docs/research-workflow.md`;
`data/README.md`.

Risks:

- A stop between the database replace and the report write leaves an old
  report. The next preparation renders it again. Readers of the report text
  must not treat it as a source.
- Fixtures set the cutoff through the report text today. They must patch the
  setting instead.
- Keep the first-run rule: unavailable prices stay null.

Exit: the protocol checks; tests for a leftover journal, a stop before and
after the replace, and a report re-render. Real copy: the rendered report
equals the current report byte for byte; four digests equal; a rebuild with
unchanged inputs skips the independent engine; publication time measured.

### P3. One build: parse once, full rebuild

Scope:

- Measure first. On the bench, run a one-session append (the T0 procedure)
  through the current reuse path, and a forced full build. Show both times to
  the user. The default is the nightly full rebuild.
- Research preparation reads, hashes and parses each raw file once. From one
  price payload it derives the January series, the latest snapshot, the typed
  stock days and the source digest and disposition (the `SeriesAsset`
  validity rule applied to the same payload). The shared SPY and Treasury
  files are parsed once too. Drop the per-file re-hash checks that cache
  ownership already covers.
- With the full rebuild, delete the reuse machinery. Split
  `research.prepare` into builders only where that deletes code.
- The daily cache keeps its own price copy and kept-book rule in this phase.

Deletes: `_PriorUnits` (rowid spans, `copy_history`, `copy_dated`,
`prepended`, `ATTACH prior`), `facts.copy_stock`, the `days` filter of
`facts.resolve`, `_bounded_digest`, `_rows_digest`, `_reuse_scope`,
`REUSE_MARGIN` and the `reuse` metadata.

Owns: `backtest/inputs/research.py` (build), `facts.py` (resolve and store),
`cache_assets.py` (only to share the validity rule),
`tests/test_prepared_reuse.py`, `test_research.py`, `test_prepared_facts.py`.

Risks:

- Row order: verify that no result depends on rowid order (`scope_rows`
  orders by `s.rowid`).
- The one-parse disposition must equal `SeriesAsset` labels; compare
  `fact_sources`.
- If the measurement shows that reuse pays, keep only that part and say why
  here.

Exit: the protocol checks. Real copy: the new research database equals the
previous cold build table by table, except identity metadata; four digests
equal; cold build and one-session append times by stage.

### P4. One fact store and one identity

Scope:

- `research.sqlite` holds each fact once:
  - `stock_days` gains the valuation `price` and the book `adjusted` columns
    (the `daily._price_rows` rules). Days that only the light series supplies
    become rows without observation fields.
  - `market_days` gains the book SPY close (`market.load_bars`), the book
    3-month yield and the 10-year yield (today `sessions`, `treasuries`,
    `treasury10`).
  - `statements` stays once. The legacy annual values that
    `metrics.filter_values` reads come from `annual_facts` (the legacy fields
    of `financial_inputs.ENDPOINTS`, valid values only).
- `schedules.sqlite` holds only dated books (`periods`, `period_pools`,
  `snapshots`, `filter_values`, `screening_metrics`) and one binding record.
  Its connections, including the read-only book workers, attach research
  read-only.
- One identity record in research: the schema version, the accepted raw
  signature (including each price file) and the content identity of the code
  that computes rows. The daily binding names that research identity and the
  code that computes books. Editing a reader must not invalidate books;
  split the `facts.py` writer from its reader if needed.
- Kept books. Before the replace, preparation compares the new rows that
  books read with the previous research file, only for changed files and
  market rows. It records the first changed day and the previous identity. A
  changed statement, annual fact, company list, cached set or book code drops
  every book. The daily step keeps a book only when it is bound to that
  previous identity and reads nothing on or after that day (the existing
  `_keep_books` rule). Otherwise it drops the book, which is computed again on
  demand.

Deletes: daily `prices`, `sessions`, `treasuries` and the copied `companies`,
`statements`, `financial_inputs`, `treasury10`; research `treasury10` and
`financial_inputs`; `_copy_research` and its every-row digest; `daily._prices`,
`_first_difference`, `_dated_change`; `fact_metadata`, `facts.require` and its
per-scope calls, `facts.policy_binding`, `prepared_bindings`,
`prepared_price_binding`, the daily engine stats and the `_code` digests.

Owns: `research.py` (schema, identity, change day), `daily.py`, `facts.py`,
`engines/original/schedules.py`, `book_batch.py`, the `sessions` readers
(`robustness.py`, `calendar_requests.py`, `scalar_runs.py`,
`original_calculations.py`), `operation_inputs.py`,
`tools/ops/prepared_input_coverage.py`, `website/server/data_manager.py`
(status), their tests, the AGENTS dated-schedule and data-panel paragraphs,
`docs/schedule-calendar.md`, `docs/research-workflow.md`.

Risks:

- One fact, two rules. The book rules (positive bars, last value per day, the
  light series) differ from the observation rules (conflicts unavailable).
  Keep separate columns where they can differ.
- The derived legacy annual values must equal the JSON values bit for bit.
- `periods`, `snapshots`, `filter_values` and `screening_metrics` exist in both
  files. Name the schema in SQL.
- A worker must attach the research file that the parent admitted. `PRAGMA
  cache_size` applies per schema; measure book computation through the attach.
- Native Windows: attach, file replace and spawn workers
  (`tests/test_book_batch.py` on native Windows before merge).
- Results record `input` and `projection` from the view. Keep the fields and
  fill them from the one identity. Old results open unchanged.

Exit: the protocol checks. Real copy, before deletion: every moved column
equals the old daily table or JSON input (0 mismatches); harness parity; four
digests equal. Then: cold build time; sizes, including `schedules.sqlite`
before books; a one-session append keeps the same books as the old rule (T0:
1,343 of 1,346).

### P5. Book rows are admission and owner lanes

Scope:

- A stored book row is its root's admission decision, for January, latest and
  dated books: present means admitted, with its candidate rank and valuation.
  `Executor` stops calling `view.candidates` (`books.candidates` over every
  company) per dated date and `View.admit` for January and latest scopes.
  Latest rows gain `ebitda`.
- One admission function in `books.py` serves `compute_period`, the research
  January and latest rows and explicit preview roots. Keep the reason codes
  that saved results can contain. Delete `latest_admission` if that function
  serves latest preview roots.
- Owner lanes at a stored-book root of every kind read the book's stored
  lanes, named by the book id instead of a threaded `owner_scope`. Derived
  `at` and `lookback` contexts keep the dated owner policy (AGENTS).
- Values-only evaluation builds no evidence: no JSON encoding and no detach.
  Detail mode builds evidence for selected rows only. Keep the explanation
  block shape. Scope the owner byte ceiling to detail mode.
- One owner-scope check (today three) and one operating-margin formula in
  `metrics.py` (today also in `columns.py`).
- Then profile 20 scopes and the user test, and list what is left:
  scope-row reads, report dates parsed again per root, `filter_values` reads,
  first-run book computation, result encoding (78 MB). Compact book rows (old
  T5) only if the profile shows that the book tables cost.

Deletes: dated re-admission in `Executor._admit`, the admission chains in
`View.admit` and `_admit`, evidence building in values-only owner lanes, and
the `View` members that only served them.

Owns: `scalar_execution.py`, `columns.py`, `facts.py` (`View`),
`measure_observations.py`, `financial/books.py`, `financial/metrics.py`
(operating margin), `engines/original/schedules.py` (admission), `research.py`
(latest rows), `scalar_runs.py`, their tests.

Risks:

- Signed zero: stored `filter_values` are REAL and lose -0.0. Dated owner
  lanes keep it today. The harness shows any change; January and latest lanes
  already read stored values.
- Every stored row must pass the one admission function; assert it in a test
  and on the bench.
- Explained dated owner lanes change their evidence source. List the changed
  fields and compare the rest.

Exit: the protocol checks, heavy tier included. Real copy: harness parity of
values and reasons against P4, with the owner formula set on 64 rows per
scope; four digests equal; user-test time with books saved; the 20-scope
profile. Then stop. The user decides about P6.

### P6 and later (only if the user continues)

One measured cost per phase, with the same protocol. Stop when the gain
becomes marginal.

## Review candidates

Reviews of 8de87fb: A is the design review, B is the implementation audit.

Adopted:

- A.1 in part: the per-scope work is a required phase (P5), and real-copy
  gates come before deletions.
- A.2: P3 (one parse, delete `_PriorUnits`, builders, row-order check) and P4
  (one fact store, attach).
- A.3: P5. A.4: P4. A.5: P1.
- B.2: P3. B.3: P1. B.4: P5. B.5: P1. B.6: P4. B.7: P1. B.8: P4. B.9: P5.
- B.11 in part: P1 fixes the AGENTS harness wording.

Rejected:

- Numeric targets (A.1): the user rejected them.
- Ordering by measured cost before storage (A.1): the user approved the
  outline that puts the fact store first.
- The in-place update and its unit algorithm (from-scratch design, A.2): the
  user dropped the in-place update. A full rebuild is one path.
- Deleting `View.broad_reports`, `legacy_financial_history` and
  `legacy_treasury` (A.3): derived contexts keep the dated owner policy, so
  these readers stay. P5 removes only their evidence cost.
- Rewriting history for B.11: only on the user's request.

Deferred:

- Compact book rows (A.3, old T5): decided by P5's profile.
- Provider-era bounds (B.10: `MAX_HISTORY`, `MAX_METADATA_BYTES`,
  `MAX_SCOPES`): AGENTS keeps resource ceilings. Remove a bound only with the
  code that it guards.

Resolved: B.1 (real-copy parity at T2 and the T3 digests).

## Bench and tools

`~/bench/README.md` has the details.

- Copy: `~/bench/ebitda-real`, about 17 GB at T3. Never write the Windows
  runtime or copy anything back.
- Update the code: `WT=<worktree> bash ~/bench/scripts/update_bench.sh`
  (changed files, preparation, the user test twice). Run long jobs detached.
- User test: `~/bench/user-test.json` (24 random quarterly trials,
  2013-01-01 → 2026-10-21, seed 2607948532, ranks 1–30, cached pool, EV/EBITDA
  yield ranking, three built-in conditions and debt/EV < 50%). Run
  `python3 ~/bench/scripts/run_user_test.py full` from the bench folder.
- Digests: `python3 ~/bench/out/result_digest.py OUT.json` from the bench
  folder (random test, quarterly fixed dates 2013–2018, January 1996–2026,
  latest). T3 digests: `~/bench/out/t3-digest.json`.
- Harness: `~/bench/harness/`. Set `WT=` and
  `TMPDIR=~/.cache/ebitda-ev-spread-tests/<name>`; empty it afterwards. Each
  phase extends the storage comparison it needs.
- Profiles: `~/bench/scripts/profile_real_scope.py`, `table_sizes.py`.

## Risks

- Deployment: each schema change bumps its version and rebuilds the prepared
  caches once. The 01:00 supervisor deploys `main`. A leftover baseline journal on the runtime forces
  a full build (P2).
- Native Windows: attach, file replace and spawn workers need the native checks
  that AGENTS names before a merge.
- Scope creep: each phase stops at its exit. A new idea goes to the user first.

## Next

An independent design review checks this plan before code starts. Then a fresh
agent runs P1.
