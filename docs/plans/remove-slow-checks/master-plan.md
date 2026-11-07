# Remove unjustified computing time

Status: complete

Superseded: typed-storage deleted the observation identity, the JSON observation
evidence, the reference formula evaluator and its parity harness, the
reference-engine comparison in preparation and the baseline publication hashes.
See the [typed-storage summary](../typed-storage/master-plan.md).

## Outcome

Repeated custom-variable backtests, cancellation and preparation no longer pay
for work that the exclusive cache lock or an earlier step already covers.
Financial results are unchanged, and saved library and queue records open
unchanged. Typed storage and the in-place daily update continue in the
`typed-storage` initiative.

On the copied real cache, the user's random-date test (24 quarterly trials,
2013–2026, ranks 1–30, cached pool, three built-in conditions and one custom
variable) went from impossible to complete:

| Measure | Before | After |
|---|---|---|
| Run start | about 20 min of row hashing, not cancellable | under 1 s |
| Full run, all books saved | failed at a ceiling | 200 s |
| First run, 1,326 books computed | failed at a ceiling | about 11–12 min |
| Stop after 20 s | waited for the hash | 0.0 s |
| Result | over 256 MiB | 78 MB |
| Cold research and daily build | 10,229 s on the Windows runtime | 1,363 s in WSL |

The full fixture sweep of the per-row parity harness compared 1,835,372
formula outputs of the column evaluator with the reference: 0 mismatches.

## Key decisions

- Prepared rows are never rescanned on a read path. The observation content
  identity hashes what determines the rows (raw signature, price-file digests,
  reuse scope, scopes, policy), not the rows.
- Readers compare an accepted raw-file signature. Preparation and every
  data-panel action take a new one, so a hand edit to `raw/` needs a data-panel
  check before readers see it.
- Source self-hash checks return the hash taken at import; deployment restarts
  the server when source changes.
- Custom-variable formulas are evaluated values-only by
  `backtest/variables/columns.py`, only for rows that can still be selected.
  Dated scopes admit book rows with the view's admission rules and the book's
  valuation.
- Fixed-date and latest runs explain selected rows with the reference
  evaluator, which must agree with the column values bit for bit. Random-date
  runs keep each selected row's formula values and reasons without a step
  trace (user decision).
- Explanations keep values, dates, reasons and the source file and digest. They
  drop raw row positions and row hashes (user decision).
- A run has no run-wide work ceiling; a size check refuses a result that cannot
  fit before any work. Book batches use up to eight workers from 16 missing
  books, and each worker decodes financial inputs once.
- The reference-engine comparison stays in preparation (about 20 s on the real
  cache). The three database hashes in baseline publication stay; changing them
  changes the recovery journal format.
- The frozen experimental (Numba) engine, its tests and its comparison runner
  are deleted (user decision).

## Where the contracts live

`AGENTS.md` (Custom variables, Random-date sensitivity, Engines),
`docs/research-workflow.md` (observation identity and signature),
`docs/evidence-views.md` (retained explanations) and the architecture guide.

## Known limits

- Dated observation evidence stores raw-file row positions. A daily download
  that adds rows at the top of a file rewrites every stored day of that company.
- Prepared data takes about 51 GB on the real cache: JSON observation evidence
  (`observation_dated` 31.1 GB in research, 14.3 GB in the daily cache) and
  row-per-field books (75 million `filter_values` rows for 1,326 books).
- A scope still costs about 0.15 s on the real cache: admission candidates per
  date, scope-row reads, column evaluation of company facts, selection and
  writing.
- Random-date runs no longer cross-check the column evaluator against the
  reference at run time; the parity harness and fixed-date runs do.
- The first deployment of this work rebuilds the prepared caches once.
