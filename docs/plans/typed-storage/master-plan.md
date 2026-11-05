# Typed prepared storage and in-place daily update

Status: active

## Goal

Make the daily data update take about a minute, cut prepared data from about
51 GB to a few GB, and make repeated custom-variable backtests faster, so the
user can tune strategies interactively and later run an automatic search loop.
Financial results stay identical. Saved library and queue records open
unchanged.

The user's workflow: choose parameters or custom variables as filters or the
ranking, queue the test, tune, repeat; later a reinforcement-learning loop runs
this automatically on fixed date plans; the database is updated every day.

## Starting point (main a7b13ac, 5 November 2026)

The `remove-slow-checks` initiative is complete; read its summary first. The
current custom-variable path:

- `backtest/variables/columns.py` evaluates formulas values-only. It reuses
  the provider helpers in `backtest/observations.py` (`_anchor`, `_periods`,
  `_annual`, `_report_ebitda`), `backtest/measure_observations.py` and the
  borrowed `ReadView` from `backtest/inputs/sqlite_observations.py`. It reads
  company facts from the JSON `observation_annual` rows and dated facts from
  `observation_dated` and `observation_sessions`.
- `backtest/application/scalar_execution.py` `Executor.select` admits dated
  book rows with the view's admission rules and the book's valuation, reads
  stored lanes with one query per table, evaluates formulas only for rows that
  can still be selected, and (except in random-date runs) explains the
  selected rows with the reference evaluator (`backtest/variables/reference.py`
  over `observations.observe`), which must agree bit for bit.
- Research preparation (`backtest/inputs/research.py`) builds a new
  `research.sqlite` file each time and publishes it through
  `backtest/inputs/baseline.py` (journal, three database hashes). Daily
  preparation (`backtest/inputs/daily.py`) builds a new `schedules.sqlite` file,
  copies research tables into it with `INSERT … SELECT` and keeps unaffected
  books.

Measured on the copied real cache (`~/bench/ebitda-real`, WSL):

| Table | Database | Rows | Size |
|---|---|---|---|
| `observation_dated` | research | 24,497,566 | 31.1 GB |
| `observation_dated` (copy) | daily | 24,497,566 | 14.3 GB |
| `observation_annual` | research and daily | 380,833 | 1.9 GB each |
| `observation_measure_contexts` | research and daily | — | 0.38 GB each |
| `filter_values` + index (1,326 books) | daily | 75,342,237 | 8.0 GB |
| `snapshots` (1,326 books) | daily | 4,371,248 | 0.58 GB |
| `prices` | daily | 24,489,611 | 1.0 GB |

- Cold research and daily build: 1,363 s (research 983 s, of which the dated
  observation stage was about 676 s; publication about 80 s).
- The user's test (below) with all books saved: 200 s; first run with all
  1,326 books computed: about 11–12 min; Stop: 0.0 s; result 78 MB.
- A scope (one screen date) costs about 0.15 s. A profile of 20 real scopes
  attributes most of it to admission candidates per date, scope-row reads,
  column evaluation of company facts, selection and writing.
- A daily append has not been measured on the real copy. The dated evidence
  stores each price row's position in its raw file, so a download that adds
  rows at the top rewrites every stored day of that company.

## User decisions

Made (keep them):

- Explain keeps values, dates (fiscal, known, observation), reasons, the source
  file and its digest. It drops raw row positions and row hashes.
- Random-date results keep each selected row's formula values and reasons, not
  step traces. Fixed-date, January and latest results keep traces.
- Readers compare an accepted raw-file signature; a hand edit to `raw/` needs a
  data-panel check.
- The frozen Numba engine is deleted.
- The reference-engine comparison of the January baseline stays in
  preparation.
- No parallel trials for now; 8 book workers.

Pending (ask the user before the phase that needs it):

- **D1 (before T2).** The old reference evaluator reads the JSON observation
  tables. Either delete it after parity, so the column evaluator produces the
  fixed-date traces itself and the live cross-check ends (the earlier approved
  plan), or port it to the typed tables to keep an independent check (more
  code). Recommend delete after parity, keeping the parity harness as the
  oracle for the change.
- **D2 (before T4).** Whether a latest-only daily update may skip the canonical
  report publication journal when no historical unit changes (recommended: yes;
  the report cannot change then).

## Constraints

- AGENTS.md standing rules and feature contracts apply, except where the user
  has decided otherwise above. Prepared schemas, freshness checks and the
  daily cache are shared contracts: keep edits narrow and describe each schema
  change in the docs and guide.
- Python standard library only. New tests are fast.
- Every change that alters stored rows needs a parity gate on the copied real
  cache before any old table or code is dropped.
- Each schema change rebuilds the prepared caches once at deployment. The
  supervisor deploys `main` at 01:00; merging to `main` needs the user's
  authorization each time.
- Disk: keep one real-data bench copy; a rebuild needs about 34 GB of temporary
  space until P3 shrinks the files.

## Design

### Typed facts

- `stock_days(symbol, day, adjusted, price, volume, reason)` — one row per
  company and session that the raw price file supplies, keyed by date, never
  by file row. `reason` carries the existing provider reason when a field is
  unavailable (non-positive price, conflicting rows, non-USD route).
- `market_days(day, spy, month3, year10, …)` — SPY sessions and Treasury
  fields keyed by date.
- `annual_facts(symbol, endpoint, fiscal, <one REAL column per catalog field>,
  <one reason column per field>)` — the selected annual states, with the
  existing validity rules. Column names follow `backtest/variables/parameters.py`.
- `annual_sources(symbol, endpoint, file, sha256)` — the source file and digest
  that Explain keeps.
- Keep `observation_latest` semantics (latest-root admission) as typed rows.
- Owner measures in prepared scopes stay as stored lanes (today
  `observation_measure_contexts`); store their values typed.
- One new module, `backtest/inputs/facts.py`, owns writing and reading these
  tables and replaces `observation_inputs.py`, `sqlite_observations.py`,
  `dated_observation_inputs.py` and the storage half of
  `measure_observations.py`. Financial policy stays in `backtest/financial/`.

### In-place daily update

- A download that adds only days after the canonical report's Through date
  changes only latest and dated units. Update `research.sqlite` and
  `schedules.sqlite` in place in one transaction each: insert the new
  `stock_days`/`market_days`, recompute latest snapshots and admission, delete
  only books that read a changed day (the existing `_keep_books` rule), and
  record the new identity.
- A change to historical inputs keeps today's full build and baseline
  publication.

### Compact books

- One row per (book, pool, symbol) with the snapshot fields and every filter
  and metric value as columns, instead of one `filter_values` row per field.
  `screening.select`, `website/rendering/data.py`, `website/browser/screener.js`
  and `Executor.select` read it.

## Phases

Each phase is its own branch-sized slice: tests pass, the guide and docs are
current, real-copy parity holds, then ask the user to merge.

### T0. Baseline measurements (no product change)

- Update `~/bench/ebitda-real` to the starting commit (see Bench).
- Measure a realistic daily update on the copy: append one session to every
  price file in the copy's `raw/` (copy only; never the runtime), add the SPY
  and Treasury rows, then time `daily.prepare()`. Record each stage from
  `data/logs/`.
- Record the user test time with saved books and a 20-scope profile.
- Exit: numbers in this plan's Measurements section.

### T1. Write typed facts beside the JSON tables

- Research preparation also writes `stock_days`, `market_days`,
  `annual_facts`, `annual_sources` and typed latest/owner rows. The daily cache
  reads them from research (attach or `INSERT … SELECT`), not a second copy if
  avoidable.
- `facts.py` read API with the operations `columns.py` needs: company reports
  per pool, annual states at a fiscal date, session on or before a day within
  seven days, own-stock row at a day, Treasury as of a day, latest admission,
  prepared owner lanes.
- `columns.py` reads through `facts.py`.
- Parity: extend the harness so the column evaluator over typed facts equals
  the reference over JSON for every row (fixtures, then real copy: the user
  strategy on 20 scopes and the formula set on 64 rows per scope).
- Exit: harness 0 mismatches; tests pass; scope time measured.

### T2. Explanations from the column evaluator (needs D1)

- Add a detail mode to `columns.py` that records, for selected rows only, the
  inputs, dates, reasons, source file and digest, and the operations, in the
  `evaluation` block shape that `website/browser/variable-evidence.js` reads
  (`requests`, `program.nodes`, `observations.results/roots/contexts`,
  `operations`, `results`).
- If D1 = delete: fixed-date, January and latest runs use the detail mode; the
  reference evaluator leaves the run path. If D1 = port: keep the reference as
  the cross-check over typed facts.
- Exit: viewer checks pass; on fixtures and the real copy the detail traces
  carry the same values, dates and reasons as the reference traces.

### T3. Remove the JSON observation tables

- Gate: storage parity on the real copy (typed facts reproduce every value and
  reason the JSON tables give).
- Drop `observation_*` tables from both databases; delete
  `observation_inputs.py`, `sqlite_observations.py`,
  `dated_observation_inputs.py`, the storage parts of
  `measure_observations.py` and, if D1 = delete, `observations.py`,
  `variables/evaluation.py` and `variables/reference.py`. Move preview and
  coverage (`scalar_execution.preview`, `variable_coverage.py`) to the column
  evaluator. Keep small arithmetic golden tests.
- Exit: database sizes measured; cold build time measured; tests pass.

### T4. In-place daily update (needs D2)

- Implement the latest-only path above in `research.py` and `daily.py`, inside
  the existing cache ownership. Keep the full-build path for historical
  changes. Keep crash safety: one transaction per database; a failed update
  leaves the previous state.
- Exit: on the real copy a one-session append completes in about a minute and
  equals a full rebuild of the same inputs (table-by-table comparison of
  everything except identities); `tests/test_prepared_reuse.py` and
  `tests/test_schedules.py` cover the path.

### T5. Compact books

- New book table shape; update the SQL screener, website embedding and browser
  screener together. Keep `period_pools` completion semantics.
- Exit: `python3 tests/check_screener.py` after a build, `node
  tests/check-range.cjs`, `node tests/check-contributions.cjs` and the
  selection-order tests pass; holdings identical on the real copy; book size
  measured.

### T6. Remaining per-scope cost (optional)

- Admission candidates per date (`books.candidates` over every company) and
  scope-row reads. Measure first; change only with identical results.

## Bench and tools

- Real-data copy: `~/bench/ebitda-real` (raw 4.2 GB, research 33.7 GB, daily
  about 18–28 GB). It is a copy of the Windows runtime's `raw/` and `results/`
  plus `data/variable-library.sqlite`, with code exported from a commit. Never
  write the Windows runtime; never copy assets back.
- Update its code: `WT=<worktree> bash ~/bench/scripts/update_bench.sh`. It
  copies only changed files (unchanged files keep their times, so the raw
  signature does not force a rebuild), prepares, and runs the user test twice.
  Run long jobs detached: `setsid nohup bash … > log 2>&1 < /dev/null &`.
- The user test: `~/bench/user-test.json` (24 random quarterly trials,
  2013-01-01 → 2026-10-21, seed 2607948532, ranks 1–30, cached pool,
  EV/EBITDA yield ranking, three built-in conditions and `debt/EV` < 50%).
  Run from the bench folder: `python3 ~/bench/scripts/run_user_test.py full`,
  or `stop 20` to time cancellation.
- Profiles: `~/bench/scripts/profile_real_scope.py` (20 quarterly scopes,
  cProfile into `~/bench/out/`), `evidence_sizes.py`, `table_sizes.py`.
- Parity harness: `~/bench/harness/` (`parity.py` fixtures, `real.py` real
  copy, `results.py` whole results). Point it at a checkout with `WT=`; use
  `TMPDIR=~/.cache/ebitda-ev-spread-tests/p0` and empty it afterwards.
- Fixture comparisons against `main`: `~/bench/scripts/bench_shape.py` and
  `parity.py` (run each with `REPO=<checkout>`).
- Only one operation holds the bench's cache lock at a time; a second run
  waits.

## Risks

- Hidden consumers of the JSON evidence (stored results never read it; check
  `website/` and tests before T3).
- Reason-code drift between JSON states and typed columns: the harness compares
  reasons, not only values.
- In-place updates and crashes: keep one transaction per database and test an
  interrupted update.
- Disk during migration: dual tables (T1–T3) temporarily add a few GB.

## Next

Start T0: update the bench to this branch, measure a daily append and record
the numbers here. Ask the user for D1 before starting T2.
