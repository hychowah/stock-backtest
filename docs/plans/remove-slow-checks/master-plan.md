# Remove unjustified computing time

Status: active

## Goal

Make repeated backtests, cancellation, preparation and daily updates fast enough
for an interactive tuning loop and a later automatic search. Remove work whose
cost the exclusive cache lock or another step already covers. Two things stay
fixed: financial results stay identical, and saved library and queue records
still open.

## Decisions

- Prepared rows are not rescanned on any read path. The exclusive cache lock
  keeps them unchanged during an operation; preparation is their only writer.
- The observation content identity hashes the inputs that determine the rows
  (raw signature, price-file digests, reuse scope, scopes and policy), not the
  rows.
- Source self-hash checks return the hash taken at import. Deployment restarts
  the server when source changes.
- New custom-variable results keep explanations for selected rows only. The
  scope receipt keeps complete-population counts.
- The reference-engine comparison stays in preparation. It costs about 20
  seconds on the real cache and is the only check of the main engine against
  real data.
- A custom-variable run has no run-wide task, inspected-row or scope ceiling.
  Those ceilings failed the user's real 24-trial test in trial 11, after the
  work was done. Each scope keeps a 256 MiB retained-metadata bound.
- The three database hashes in baseline publication stay for now. Changing them
  changes the recovery journal format.

## Phases

1. Run-path re-hashes removed. Done (5c1fedf).
2. Preparation identity and SQL copy. Done (6dbaa85).
3. Calculation speed (fast-engine plan P0-P2, approved in the user's fork
   session and handed to this one). Done: a per-row parity harness in the
   ignored scratch folder; the values-only column evaluator
   (`backtest/variables/columns.py`, f59bd73) with the reference explaining
   selected rows only and cross-checking their values; chunk splitting for
   refused explanations (e5f3d39); financial inputs decoded once per
   operation and 8 book workers (1b1959c); the accepted raw-file signature
   (3234c3f); the single-pass evidence encoder (de5927e). Open: admission
   candidates per date (about 0.1 s per scope), the reference explanation
   (about 0.13 s per scope), P3 typed storage and the in-place daily update,
   P4 deletion of the frozen engine and the old reference evaluator. P4 needs
   the user's direct confirmation in this session.
4. Result storage. Selected-row explanations, slim explanation records and a
   size check before the run are done (10da620, 6308c6a). Open: one
   compressed record per result, a one-transaction queue-to-library transfer,
   and no reader pins, temporary copies or byte budgets.

## Measurements

All on 5 November 2026, WSL.

- Private 150-company fixture, main 255d138 against phase 2: unchanged startup
  2.52 s to 0.02 s; daily append to every price file 28.0 s to 14.4 s.
- Private 200-company fixture, ranks 1-10: annual custom-variable run 32.8 s
  and 27.1 MB to 11.2 s and 2.4 MB.
- Copy of the real raw cache, phase 4a code: cold research and daily build
  1,192 s. Research took 983 s, of which dated observations took 676 s and
  publication 82 s.
- Same copy, two quarterly scopes of the user's random test strategy under
  cProfile: 31 s before efe63cc, 9.0 s after. Before efe63cc the full test
  failed on its first scope at the 16 MiB retained-lane ceiling.
- Private 200-company fixture with a built-in ranking, a built-in and a
  formula condition: annual run 32.2 s on main, 4.2 s at efe63cc and 1.7 s
  at f59bd73, with identical holdings and summaries.
- P0 harness, full fixture sweep against the column evaluator: 2,752 pairs,
  95,546 roots, 1,835,372 outputs, 0 mismatches (reference 842.5 s, columns
  155.9 s).
- Copied real cache, the user's 24-trial quarterly test at 6308c6a: first
  complete run. With 110 of 1,326 books missing it took 425.8 s; with all
  books saved 396.7 s. Result: 1,344 periods, 40,320 holdings, 206 MB. Stop
  pressed after 20 s took effect in 0.0 s. Cold research and daily build at
  3234c3f: 1,363 s. At de5927e with all books saved: 367.2 s. A profiled
  20-scope run puts the reference explanation of selected rows at about 28%
  of a scope, admission candidates at 21%, scope-row byte checks at 13% and
  column evaluation at 12%.

## Known limits

- Dated observation evidence stores file row positions. A daily download that
  adds rows at the top of a file rewrites every stored day of that company.
- The first deployment of this work rebuilds the prepared caches once.
- Frozen numerical source still names removed observation functions.

## Next

The user decides whether random-date runs keep step-by-step formula traces
(the largest remaining per-scope cost). Then admission candidates per date,
and P3 typed storage with the in-place daily update.
