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

Done on this branch: T1 writes typed facts into `research.sqlite`, read by
`columns.py` through `facts.View`; T2 takes explanations from the column
evaluator's detail mode (D1); T3 deletes the JSON observation tables, the
provider and the reference evaluator; P1 is below.

## Measurements

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

## Decisions

These are binding (2026-11-05/06).

- Kept: Explain keeps values, dates, reasons, the source file and its digest.
  Random-date results keep formula values and reasons, not step traces.
  Readers compare an accepted raw-file signature. The Numba engine is deleted.
  No parallel trials; 8 book workers.
- **D1 = delete.** Done in T2 and T3.
- **January books are removed.** "you can remove january book … it is useless
  and that why we add random seed to avoid extreme case by picking one date".
  On four points, "i agree with 1-4":
  1. A January-only test is a 12-month dated schedule anchored on 1 January.
     The January mode goes. Saved January results still open, and opening
     never calculates. A queued or held January row is refused at execution
     with a clear error; it is never converted silently.
  2. `backtest/engines/reference/revalue.py` stays as a bench development
     check of the book code, run with the harness when book code changes,
     against a 12-month dated schedule from 1996. No build or startup runs it.
  3. `results/summary-exits.txt`, `results/baseline-history/` and
     `results/legacy/` stay as a frozen record of the original study. Nothing
     regenerates them.
  4. The browser's January screener mode goes: its top contributors, gain/loss
     pies, static top-50 fallback, January exports and their parity checks.
     The latest screener stays.

  Kept: latest and dated books, both pools (dated books apply the 250-name
  buffer), saved library and queue records.
- **D2 replaced**, mostly superseded: no report is published. Still in force:
  one temporary file and one atomic replace, no publication journal; a
  leftover journal means a full build from raw, then its removal.
- **No numeric targets.** "i want the speed is reasonable. seting a number does
  not make sense before we even work on that. stop when gain become marginal".
  After each speed phase the orchestrator shows the user the gain and the next
  largest cost. The user decides whether to continue.
- **The nightly update may be slow.** "even longer wait is good we can schedule
  it in mid night". The in-place one-minute daily update (old T4) is dropped.
- **Approved outline** ("go ahead"): (1) one fact store, (2) faster backtests.
- **Validation verdicts.** Keep the raw-file signature. Merge the four "is the
  database current" layers into one. Remove the reuse digests if the nightly
  full rebuild is chosen. Keep one formula gate. Keep the size check before a
  run. Remove per-date re-admission and owner-value recomputation. The parity
  harness is a bench development tool. (Point 2 above supersedes the
  January-engine verdicts.)

## Open questions and future decisions

- Before P3: after P3, a data-panel rebuild after a manual download is a full
  rebuild (about 8 min at P1). Is that acceptable? P2 does not depend on it.
- Not decided here: automatic nightly downloads (they would end the
  explicit-button rule), and running a nightly update after the 01:00
  supervisor (`tools/deploy.py --start`) or in the same step.

## Phase protocol

- One fresh agent runs one phase in this worktree. It stops hard at the exit.
- Inside a phase: build the new path, switch the readers, gather the real-copy
  evidence, then delete the old path.
- A phase owns every reader of a contract that it deletes.
- Real-copy evidence comes before any deletion: harness parity against the
  previous phase; the whole-result digests equal; cold build time by stage;
  database sizes; user-test times with books computed and saved. From P2 a
  12-month schedule from 1996-01-01 replaces the January digest run.
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

### P1. Cleanup (done, 6367bef and the review follow-up)

- One formula gate: the language check, `definitions.require_program`.
  Deleted: `variables/selection.py`; after the P1 review also
  `columns.require_program` (it could refuse nothing) and the always-true
  catalog support flags. A guard test evaluates every operation, statistic and
  /3 parameter through `columns.Formulas`.
- `research.signature()` leaves out `raw/download-coverage.json`.
- The named leftovers and stale docs are removed or fixed.

### P2. Remove January books

It comes first because it deletes what P3 would otherwise merge. Re-check
every dependency by grep. If one agent cannot hold P2, split it at "readers
removed / writer removed".

Scope, in this order:

1. Measure first: on P1 code, record the digest of a 12-month dated schedule
   from 1996-01-01, and compare `revalue.calculate` with it. Dated end marks
   roll back to the session on or before; the January exit is the session on
   or after 1 January of the next year. If the two differ, define what the
   bench dev check compares (for example `revalue` adapted to the dated rule,
   or a documented difference). Never change dated results to match.
2. Remove the readers:
   - `mode == 'january'` in `scalar_runs.prepared`, `strategy_requests` and
     `website/browser/range.js`. `Original.preflight` refuses a January row
     with a clear error and never rewrites it. The readers that open saved January results stay
     (`artifacts.py`, `durable_evidence.py`, `scalar_result_evidence.py`,
     `result-artifacts.js`, `evidence-results.js`, `saved-backtests.js`,
     `backtest-comparison.js`, and the `range.js` code that opening needs).
   - The browser January screener: `screener.js` historical selection, the
     January contributor panel and pies, `website/rendering/attribution.py`,
     the static top-50 fallback in `page.py`, the January pools in
     `website/rendering/data.py`, and the January exports and provenance in
     `build.py` (`holdings.csv`, `valuations.json`, `returns.csv`, the report
     digest). Dated results keep their top-10 contributors.
   - The January `research.py screen` and `status` output, the data panel's
     baseline audit, `tools/ops/deploy.py --collect-report` and the January
     and report parts of `tools/ops/prepared_input_coverage.py`.
   - The `historical_through` cutoff and every reader, including
     `facts.View.bounds` and `View.admit`. Historical preview roots are
     bounded by the saved SPY sessions.
3. Remove the writer: the January loop in `research.prepare` (January
   `snapshots`, `baseline_prices`, `periods`, `baseline_periods`, January
   `filter_values` and `screening_metrics`); `verify_reference`,
   `prepared_baseline`, `screening.historical`; `backtest/inputs/baseline.py`;
   the report in `signature()`; the January parts of `_PriorUnits`
   (`copy_history`, `_bounded_digest`, the horizon). Preparation writes a
   temporary file and replaces `research.sqlite` atomically. A leftover journal
   forces a full build; then remove it and its `*.pending` files.
4. Study-only tools: delete what only regenerated the frozen record
   (`scripts/revalue.py`; the old report in `scripts/run.py`). Keep the
   `legacy.py` helpers that `revalue` imports. Ask the user before deleting
   the stop tools (`scripts/list_stops.py`, `classify_stops.py`).
5. Rewrite the AGENTS study sections ("What the test does" to "How to
   continue", "Research database and baseline", "Website screening",
   "Selection order", `--collect-report`) for the app as it now is. Keep the
   financial rules that dated and latest books use. Update the guide.

Owns: every file named above, plus `screening.py`, `daily.py` (schema),
`original_calculations.py` (refusal), `website/rendering/*`,
`contributions.js`, `tools/ops/offline_input_copy.py`, `scripts/*.py`, their
tests (among them `check_screener.py`, `check-range.cjs`,
`check-contributions.cjs`, `test_attribution.py`, `test_baseline.py`,
`test_research*.py`, `test_prepared_reuse.py`, `check_paths.py`), AGENTS,
the guide, `docs/research-workflow.md` and `data/README.md`.

Risks:

- `daily.SCHEMA` reuses `research.SCHEMA` for its book tables. Give the daily
  file its own book schema when research drops the January tables.
- Opening a saved January result may use January rendering code. Keep what
  opening needs. If that includes the pies, ask the user.
- `rules.ASOF`, `FIRST_YEAR` and `LAST_YEAR` stay only where dated, latest or
  `revalue` code needs them.

Exit: the protocol checks, heavy tier included; tests that queued and held
January rows fail with the clear error, saved January results open without
calculation, a leftover journal forces a full build, and latest screener
parity holds. Real copy: the random, quarterly, latest and 12-month
digests equal P1; the dev-check result recorded; cold build time and sizes.

### P3. One fact store and one book function

The user answers the open question before P3 starts. If one agent cannot hold
P3, split it at "store written / readers switched", never at the line between
the research and daily files.

Scope, in this order:

1. Measure first on the bench: a one-session append through the current reuse
   path against a forced full build, and the count of duplicate-day rows in
   the px `div` and `light` series, `spy-div.json` and `treasury.json`.
2. Parse each raw file once into every fact column: the observation fields;
   the book `price` and `adjusted` columns of `stock_days`; the book SPY close,
   3-month and 10-year columns of `market_days`; and the legacy annual values
   from `annual_facts` (the legacy fields of `financial_inputs.ENDPOINTS`,
   valid values only). `statements` and `companies` stay once, in research.
3. One book-row function in `books.py` computes the latest rows and the dated
   books through one price-lookup interface over the facts.
   - It is the admission rule. Preview roots call it too.
   - It is the only reader of legacy annual values and the 10-year yield. The
     View's derived-context readers call the same readers.
   - One writer and one row shape (with `ebitda`): latest books in research,
     dated books in `schedules.sqlite`.
4. Switch the readers. `daily`, `View`, `compute_period` and the book workers
   attach research read-only. `research.sqlite` holds facts and latest books;
   `schedules.sqlite` holds only dated books and one binding record.
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

Deletes: `prepare_metrics`, `latest_snapshot`, `bars`, `before`, `after` and
`ten_year_yield`; the rest of `_PriorUnits` and the reuse digests
(`_rows_digest`, `_reuse_scope`, `REUSE_MARGIN`, `facts.copy_stock`); daily
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

- Duplicate days: the latest-row series takes a day's max value backward;
  `_price_rows` takes the max adjusted and the last light value in file order;
  Treasury uses `asof_yield` on a sorted list against `INSERT OR REPLACE` in
  file order. If duplicates exist and the latest and dated rules disagree on
  real data, keep one function with two price adapters and document the
  difference next to it. Never two loops.
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
mismatches); harness parity; digests equal. Then: cold build time; sizes; kept
books after a one-session append (T0: 1,343 of 1,346) and after a nightly
update that adds some annual reports.

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
- One formula check per operation. `Formulas` takes the projection from the
  capture restore instead of calling `definitions.require_program` again;
  `variable_coverage.inspect` drops its extra calls; `Original.preview`
  restores the capture once (today `check_options` and `check_preview` both
  call `require_strategy`). `Executor.__init__` keeps its restore, the
  execution boundary for queued rows.
- Then profile 20 scopes and the user test, and list what is left:
  scope-row reads, report dates parsed again per root, `filter_values` reads,
  first-run book computation, result encoding (78 MB). Compact book rows (old
  T5) only if the profile shows that the book tables cost.

Deletes: dated re-admission in `Executor._admit`; the admission chain in
`View.admit` for scope roots; evidence building in values-only owner lanes;
`_OWNER_BYTES`, the `budget=` parameters and the JSON byte counting in
`broad_reports`, `legacy_financial_history` and `measure_observations.dated`;
the `View` members that only served them; the repeated formula checks.

Owns: `scalar_execution.py`, `columns.py`, `facts.py` (`View`),
`original_calculations.py` (`preview`),
`measure_observations.py`, `financial/metrics.py` (operating margin),
`scalar_runs.py`, `variable_coverage.py` (admission), their tests.

Risks:

- Signed zero: stored `filter_values` are REAL and lose -0.0. Dated owner
  lanes keep it today. The harness shows any change; latest lanes already read
  stored values.
- Explained dated owner lanes change their evidence source. List the changed
  fields and compare the rest.

Exit: the protocol checks, heavy tier included. Real copy: harness parity of
values and reasons against P3, with the owner formula set on 64 rows per
scope; digests equal; user-test time with books saved; the 20-scope profile.
Then stop. The user decides about P5.

### P5 and later (only if the user continues)

One measured cost per phase, with the same protocol. Stop when the gain
becomes marginal.

## Review candidates

From the reviews of 8de87fb (A design, B implementation) and of this plan at
227cdd1.

- Adopted: A.1 in part (P4 is required; gates before deletions). A.2, A.4,
  B.2, B.6, B.8: P3. A.3, B.9: P3 and P4. A.5, B.3, B.5, B.7, B.11 (wording):
  P1. B.4: P4. B.10: a bound goes with the code it guards. 227cdd1: one
  fact-store phase, one change-day rule, a phase owns every reader it breaks.
- Rejected: numeric targets and cost-first ordering (user); the in-place
  update and its unit algorithm (user dropped it); deleting
  `View.broad_reports`, `legacy_financial_history` and `legacy_treasury`
  (derived contexts keep the dated owner policy; P4 removes their budgets and
  evidence cost); rewriting history (only on the user's request).
- Deferred: compact book rows (A.3, old T5), decided by P4's profile.
- Resolved: B.1.

## Bench and tools

`~/bench/README.md` has the details.

- Copy: `~/bench/ebitda-real`, about 17 GB at T3. Never write the Windows
  runtime or copy anything back.
- Update the code: `WT=<worktree> bash ~/bench/scripts/update_bench.sh`
  (changed files, preparation, the user test twice). Run long jobs detached.
- User test: `python3 ~/bench/scripts/run_user_test.py full` from the bench
  folder (`~/bench/user-test.json`: 24 random quarterly trials, 2013–2026).
- Digests: `python3 ~/bench/out/result_digest.py OUT.json` from the bench
  folder (random, quarterly 2013–2018, January, latest).
- Harness: `~/bench/harness/` with `WT=` and a private `TMPDIR`, emptied
  afterwards. Each phase extends the comparison it needs; P2 adds the
  `revalue` dev check.

## Risks

- Deployment: each schema change bumps its version and rebuilds the prepared
  caches once. The 01:00 supervisor deploys `main`. A leftover baseline journal
  on the runtime forces a full build (P2).
- Native Windows: attach, file replace and spawn workers need the native checks
  that AGENTS names before a merge.
- Scope creep: each phase stops at its exit. A new idea goes to the user first.

## Next

P2 (Remove January books) after an independent review of the revised plan.
