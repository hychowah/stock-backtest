# Completed-trial calculation checkpoints

CB-10 added offline numerical random recovery. Current application requests use
the calculation owner's `calculate` method for legacy requests. Captured scalar
requests use its bounded `calculate_into` method. Original uses ordinary schedules and `book_batch`.
Opt-in experimental random requests use the CB-19D parallel coordinator. The
existing queue and saved library own user records. Both engines support the
current week/month calendars. Original remains the default. Source changes do
not deploy or restart an installed server.

## Interface and ownership

`backtest/engines/numerical/checkpoints.py` uses only the standard library. The caller supplies
one disposable SQLite path. It does not discover a default cache or user store.

```python
binding = numerical_random.checkpoint_binding(portfolio, configuration)
with trial_checkpoints.Store(private_path) as store:
    experiment = store.open(binding)
    result = numerical_random.run(portfolio, configuration, experiment,
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

CB-14 adds `experiment.save_from(number, trial_view)` and
`experiment.replay_into(number, emit_period)`. The first accepts a sealed
`result_evidence.TrialView` and returns the same retention outcome. The second
returns original scalar metadata without `periods`, or `None` for a missing row.
It validates all evidence before forwarding periods. Forwarded output is still
provisional until the call returns. Corruption raises; it never becomes a miss.
These methods retain one complete period and bounded encoded buffers.

## Calculation identity

`backtest/engines/numerical/random.py` owns the builder. Callers import this
owner directly. For legacy contract-1 calculations, the builder binds:

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

Store version 2 retains existing version-1 canonical JSON TEXT rows verbatim.
New bounded saves store a BLOB in the same `trials.payload` column. The BLOB
starts with `CBTRIAL`, bytes `00 02`, a four-byte big-endian envelope length,
and canonical finite JSON. Its legacy envelope contains `format=1` for the sealed codec
trial, experiment identity, original trial number, range hash, piece limit and
record limit. The remaining bytes are the original sealed trial range. No
second user-result store or staging directory is added.

SQLite incremental BLOB access reads both representations in bounded buffers.
The private `backtest/engines/numerical/legacy_checkpoints.py` decoder checks canonical version-1 JSON
spelling and ordered keys. It splits periods and individual holdings. Metadata
and each holding must fit the codec's 8 MiB maximum record bound and 64-level
nesting limit. A record beyond these limits fails explicitly on bounded replay;
eager legacy reading retains
its previous contract. Complete periods can exceed that record bound.

All recovery paths verify stored byte length, SHA-256, exact experiment identity,
trial numbering, recorded dates and financial arithmetic. Streamed financial
validation reuses `portfolio_results.evaluate_into`. It does not calculate books
or collect the trial. Eager `load/read` can explicitly collect new BLOB rows.
The bounded driver never invokes those collecting adapters.

Saving validates the result and recorded dates. One SQLite transaction owns the
whole row and any retention eviction. SQLite uses full synchronous rollback
journaling. Cancellation is checked before the transaction and before commit.
An interruption before commit leaves no completed row. An interruption after
commit leaves evidence available for retry. Progress or capture failure after
commit does not erase it.

Streamed saving validates its sealed source before retention. It reserves an
exact-size SQLite BLOB, copies bounded buffers and validates the copied evidence
inside that same transaction. The BLOB handle closes before commit. No partial
BLOB is visible as a completed trial. Failed copies and cancelled evictions
roll back together. A failed final output callback does not erase an earlier
committed trial. Equal evidence is idempotent across representations, excluding
only root seconds. Canonical per-field and per-holding hashes preserve number
types, missing fields and extensions without serializing the whole trial.

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
`data/backtest-queue.sqlite`. Completed eager version-1/2 snapshots retain their original
settings, labels, presentation, dates and full holdings. Existing ResultArtifacts
readers reopen and export them without calculation after input replacement or
checkpoint eviction. Their existing limits and explicit deletion rules remain.
Explicit [version-3 durable copies](durable-evidence.md) retain independent codec
evidence inside the same user stores. Their explicit readers need no checkpoints;
[acquired browser readers](evidence-views.md) are additive in CB-14 capacity
increment 5. Legacy submissions and queue execution remain eager. Captured scalar
jobs retain bounded evidence through the same application owner. Phase 7 admits
supported bounded numerical scalar execution in Latest, January, fixed and
random modes. Standalone built-in Latest/January views keep their shared prepared
data. Original remains default. Sample preview uses Original reference execution;
eager scalar execution is unsupported. The Phase 7 record retains the closed
independent audit and final source-bound verification receipts.

## Verification scope

Focused checks are `tests/test_trial_checkpoints.py` and
`tests/test_numerical_trials.py`. They use private stores and fictional inputs.
They cover atomic process exit, independent-reader visibility, retention,
corruption, binding changes, full recovery, full capture and ordinary numerical
agreement across both pools, metrics, ranks, filters and all five month settings.
These checks supply no financial capacity or performance claim. Native and
durable consumer checks belong to the phase verification record.

## Persistent runtime boundary

The explicit CB-11 runtime opens this derived store inside its child-owned
financial session. It validates current inputs and loaded calculation source
before checkpoint-only recovery. A changed generation rejects the active child
before another provider is constructed. A fresh explicit runtime uses a new
generation binding and misses those checkpoints. It closes the store before its SQL workspace,
provider and input attachment. Source and financial OS handles stay held until
terminal process exit ends native teams. Current queue and library ownership
and durable snapshots retain their existing behavior.

The compiler signature adds the catalog, bankruptcy set and source-owned
compiler boundary. Execution versions and thread limits remain in the checkpoint
binding. Changed binding fields open a new experiment. This safely misses older
CB-10 calculations; it does not rewrite or invalidate durable user snapshots.
Read [numerical-generations.md](numerical-generations.md) for the compiler fields,
result/IPC limits and closure contract. Eager runtime random results include ordered
`trial_results` for the application-adapter shape; the borrowed diagnostic
`run` function keeps its existing summary-only result and optional capture.


The explicit bounded runtime operation uses the same checkpoint binding and
`run_into` path. Its child spool remains readable through sealed-trial retention.
A later receiver, callback or transfer failure does not erase committed trials.
Jobs owns a separate complete temporary copy after verified transfer. Checkpoint
eviction cannot invalidate that copy. This explicit operation does not reroute
legacy jobs or queues. See [temporary ownership](result-evidence.md).


## Parallel ordered coordination (CB-19D)

The experimental Session predicts its compiler and configured pool identity
before checkpoint lookup. Full recovery creates no provider and starts no
workers. Each recorded trial is validated before any lookup. Recovery checks one
trial at a time with bounded replay; it does not collect the experiment.

The parent alone calls `save_from`. Completion progress follows successful
saves, even when fresh trials finish out of order. Retained artifacts release
promptly and replay from this active experiment. Unretained artifacts retain
bounded pool reservations until their turn in recorded output. The earliest
missing trial is admitted first. Result rows, capture and eager/streaming evidence
remain ordered. One parent writer owns this operation. It does not interleave
another experiment's writes. Own-experiment retention preserves earlier rows.
An unexpectedly missing retained row or corruption fails the request.

Cancellation and callback/output failures preserve prior commits and close the
active pool batch before the runtime releases financial ownership. Configured
capacity, threads, provider bounds and compiler identity bind reuse. Actual
started worker counts and sampled resources are diagnostics. Historical TEXT
and BLOB rows keep their bindings and bytes. The new binding intentionally misses
incompatible previous experiments. Durable user snapshots are independent.

## Scalar complete evidence (Phase 7)

Phase 7 uses scalar trial dispatch through the same checkpoint store for supported
bounded numerical random execution. Latest, January and fixed scalar execution
use the same pinned application boundary. Original remains default. No ordinary
request, queued record or saved result is rewritten. Sample preview remains
Original-only, and eager scalar execution is unsupported.

Scalar bindings declare selected-book `result_contract=2`. They retain the exact
generation, implementation, compiler environment and execution policy. They keep
the complete current submitted capture separately from the recorded ordered date
plan. A presentation-only edit can keep its dates while creating a different
derived experiment for its captured names and provenance.

The SQLite store version and `CBTRIAL` BLOB prefix remain unchanged. A scalar BLOB
uses the explicitly checked inner `format=2` envelope. It includes the existing
identity, trial number, range hash and piece/record limits, plus the original
scalar metadata. The sealed range uses evidence codec 2. These allocations are
separate from application artifact 4 and durable container 3. Legacy TEXT rows
and format-1 BLOBs retain their original dispatch and bytes.

`save_from()` validates complete scalar evidence before and during publication.
`replay_evidence(number, writer)` validates recorded dates, contract-2 financial
reduction and the full explanation graph, then copies every original record.
Trial-qualified scope IDs keep recovered trials linked to their own explanations.
Reframing does not recalculate or replace observations, operations, selections or
captured labels. Duplicate comparisons include explanations and financial values.
The checkpoint read scope and BLOB close before replay returns.

Scalar `load()` and `save()` collecting adapters fail explicitly. Use sealed
`save_from()` and complete `replay_evidence()` instead. The collecting `read()`
adapter also cannot collect completed scalar rows. Period-only replay is not
complete scalar recovery. Missing rows remain misses; corrupt or incomplete
evidence remains an error. Resource exhaustion publishes no partial completion.

The existing ordered coordinator inspects checkpoints before constructing book
providers, formula evaluators or workers. A full hit constructs none. A partial
hit calculates only missing trials. The parent remains the sole checkpoint
writer and retains source/financial ownership through worker and attachment
closure. Completed application evidence stays independent of this disposable
derived store, the current compiler, library and financial inputs.
