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
- The three database hashes in baseline publication stay for now. Changing them
  changes the recovery journal format.

## Phases

1. Run-path re-hashes removed. Done (5c1fedf).
2. Preparation identity and SQL copy. Done (6dbaa85).
3. Calculation speed. The C JSON encoder, cached candidates per view and one
   built-in query per scope are done (884983a, 0b0d749). Open: evaluate
   formulas only for rows that can still be selected; decide on a values-only
   evaluator over prepared inputs.
4. Result storage. Selected-row explanations are done (10da620). Open: one
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

## Known limits

- Dated observation evidence stores file row positions. A daily download that
  adds rows at the top of a file rewrites every stored day of that company.
- The first deployment of this work rebuilds the prepared caches once.
- Frozen numerical source still names removed observation functions.

## Next

Measure the user's random custom-variable test on the copied real cache. Then
decide on phase 3's open items from its time breakdown.
