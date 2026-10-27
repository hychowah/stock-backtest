# Completed-trial calculation checkpoints

CB-10 adds offline numerical random recovery. Current application requests still
use `backtest_jobs.calculate`, ordinary schedules and `book_batch`. The existing
queue and saved library own user records. No application route selects this
diagnostic. No numerical startup, persistent runtime or weekly control is added.

## Interface and ownership

`scripts/trial_checkpoints.py` uses only the standard library. The caller supplies
one disposable SQLite path. It does not discover a default cache or user store.

```python
binding = numerical_trials.checkpoint_binding(portfolio, configuration)
with trial_checkpoints.Store(private_path) as store:
    experiment = store.open(binding)
    result = numerical_trials.run(portfolio, configuration, experiment,
                                  capture=observe_completed_trial)
```

This example assumes the caller already owns source and financial cache access.
Acquire source before importing application modules. Retain source and cache
ownership through checkpoint closure, provider closure and attachment closure.
The diagnostic borrows an owned `NumericalPortfolio`. Close its SQL workspace
and provider before closing its inputs. Checkpoints acquire no financial lock
and start no worker. They do not own ordinary saved candidate books.

`experiment.load(number)` returns a detached complete result or `None`.
`experiment.read()` returns completed `(number, result)` pairs in trial order.
`experiment.save(number, result)` returns `retained`, `payload_bytes` and
`evicted_experiments`. Callers do not manage the store's transactions.

## Calculation identity

One source-owned builder binds these values:

- Exact numerical generation, source-derived policy and field schema.
- Financial result contract version 1.
- Content hashes of the transitive local calculation source imports.
- Python implementation/version, architecture, byte order, SQLite, NumPy,
  Numba and llvmlite versions, provider class, limits and compiler settings.
- Complete submitted calculation configuration, including requested bounds,
  interval, seed, trial count, screening options and ordered sampled dates.

The binding uses canonical finite JSON. Object keys are strings. The store saves
and verifies that JSON as well as its SHA256 index. Absolute paths, process IDs,
timings, queue IDs, display labels and storage sizes do not define this identity.
The import closure is conservative. An unrelated edit to a local dependency can
reject safe reuse. Changed calculation source cannot inherit the earlier entry.

A changed generation or calculation binding opens a different experiment and
misses its completed rows. A stored binding that contradicts its identity fails.
Current input validation runs before lookup. A once-valid artifact hash does not
prove that current raw inputs remain fresh.

Recovery validates every recorded schedule against the current saved sessions.
It rejects unsupported dates. It never resamples the plan. Queue callers retain
their recorded plan and independent settings versions and edit/retry receipts.
Fresh unseeded plans still use the existing `robustness.plan` seed policy.

## Atomic publication and replay

Trial identity is the experiment identity and its positive trial number.
Duplicate schedules remain distinct trials. Each row stores the complete
original financial result, including ordered periods and holdings, nulls,
statuses, options and timing. No candidate rows or borrowed views are persisted.

Saving validates the result and recorded dates. One SQLite transaction owns the
whole row and any retention eviction. SQLite uses full synchronous rollback
journaling. Cancellation is checked before the transaction and before commit.
An interruption before commit leaves no completed row. An interruption after
commit leaves evidence available for retry. Progress or capture failure after
commit does not erase it.

Re-saving identical financial evidence is idempotent. Root `seconds` can differ.
The first committed result remains original evidence. Conflicting financial
results fail. Hash, byte-length, JSON or financial-contract corruption fails
without yielding the row. Corruption is not an incomplete trial.

Numerical recovery initializes no provider. A full hit calls no provider
`begin`, candidate evaluation or SQL staging. The borrowed CB-09 provider may
already be compiled by its owner. This is not a cold-start or persistent-runtime
claim. Fresh misses use CB-09 complete eligible books and unchanged SQL selection.
CB-06 retains its own bounded in-memory factor cache. This adapter does not use
that cache automatically or introduce a cross-process factor store.

`robustness.consume_trials` preserves ordered summaries and capture on both
paths. Its result stays summary-only by default. Incomplete financial trials
remain visible and are excluded from both paired distributions. Numerical
execution reports recovered, calculated, retained and unretained trial counts.
Those counts are separate from ordinary book-preparation worker diagnostics.

## Derived retention and storage

The defaults are **256 MiB of serialized trial payload** and **32 experiments**
per explicit store. Store construction accepts smaller bounds for tests or
private diagnostics. A new retained row evicts the oldest published other
experiments until both bounds fit. Eviction removes whole derived experiments.
The current experiment keeps its earlier trials. A trial that cannot fit
completes without retention. Its result and capture remain complete. A handle
does not pin an experiment against another writer's eviction.

The payload budget is not a filesystem quota. SQLite pages, indexes and binding
metadata add overhead. Deleted pages remain free pages in the file. Rollback
journals can temporarily add more bytes. The store does not run automatic
`VACUUM`. A caller may remove its disposable store after all users close it.
`Store.measurements()` reports payload bytes, experiment/trial counts, page
bytes, free-page bytes, current file bytes and current journal bytes. Sample
during writes to observe a journal high-water value. A post-commit zero does
not establish that high-water size.

Retention affects reuse only. It never opens, clears, migrates or deletes
ordinary saved books, `data/saved-backtests.sqlite` or
`data/backtest-queue.sqlite`. Completed durable snapshots retain their original
settings, labels, presentation, dates and full holdings. Existing ResultArtifacts
readers reopen and export them without calculation after input replacement or
checkpoint eviction. Their existing limits and explicit deletion rules remain.

## Verification scope

Focused checks are `tests/test_trial_checkpoints.py` and
`tests/test_numerical_trials.py`. They use private stores and fictional inputs.
They cover atomic process exit, independent-reader visibility, retention,
corruption, binding changes, full recovery, full capture and ordinary numerical
agreement across both pools, metrics, ranks, filters and all five month settings.
These checks supply no financial capacity or performance claim. Native and
durable consumer checks belong to the phase verification record.
