# Bounded financial evidence format 1

This format preserves complete evidence without collecting all output in memory.
It is a building block for CB-14 capacity work. The preview still uses its eager
result protocol and existing limits. Offline numerical production and version-2
derived checkpoints now use the codec. No application route changes. Explicit dormant durable operations now support
[snapshot version 3](durable-evidence.md); eager snapshots remain versions 1/2.

`scripts/result_evidence.py` uses the standard library. It owns no database, job,
file path, financial lock or publication. Existing resource owners must supply
private files and control their lifetime. It does not add a user-result store.
Reading completed evidence requires no current inputs or financial calculation.

## Writing and reading

```python
writer = Writer(stream, trials=1, metadata=original_metadata,
                max_bytes=declared_output_ceiling)
writer.start_trial(1)
summary = portfolio_results.evaluate_into(pairs, select_period, writer.period)
# A numerical adapter can add its original options/calendar/seconds here.
writer.end_trial(summary)
manifest = writer.finish(original_batch_summary)

reader = Reader(stream, max_bytes=declared_output_ceiling)
metadata = reader.metadata
for record in reader.records():
    consume(record)
```

The binary stream is caller-owned. Writing requires an empty seekable stream.
The writer does not flush, synchronize, publish or close it. A failed writer is
unusable. An owner must discard its incomplete output. It must never replace a
previous completed result with that output. A successful `finish` only completes
the codec; resource retirement and durable publication still belong to owners.

The reader verifies the entire stream before exposing completed metadata. It
reads records sequentially without collecting trials or periods. The owner must
pin immutable bytes through reading. Use one active iterator per stream. Keeping
all yielded records is an explicit eager caller choice, outside codec bounds.
Random access indexes and read pins remain work for existing application stores.

## Sealed trial views

`writer.end_trial(summary)` returns a `TrialView` before batch completion.
It binds the original trial number, byte range, physical SHA-256, period counts
and scalar summary. Later appends do not change its range. `Reader.trials()`
provides the same views over an already completed batch. A view owns no file.
The caller must preserve its bytes through each operation. Use one traversal
at a time for each stream. Writer appends restore their own stream position.
Writing alone still supports write-only files. View traversal requires readable
pinned bytes.

`view.records()` validates the sealed range and yields bounded records.
`view.periods()` assembles one complete period at a time. A period can exceed a
record limit because its holdings have separate records. `view.copy_into(sink)`
forwards complete periods and returns the original scalar summary. These methods
do not retain earlier periods. They do not validate financial arithmetic.
Checkpoint recovery additionally uses the shared financial reducer.

Sealing a trial does not complete its batch. A cancelled or failed batch has no
final manifest. Existing owners control publication after successful completion
and required resource closure. A checkpoint can retain a sealed completed trial
even when a later output callback fails. Its trial is separate from the failed
batch. See the [checkpoint contract](trial-checkpoints.md).

## Records and completeness

| Record type | Contents and order |
|---|---|
| `header` | `format_version=1`, `result_contract=1`, declared `trials`, and original `metadata`. Exactly one header starts the stream. |
| `trial` | One-based contiguous trial `number`. |
| `period` | One-based contiguous period `number` and `value` with every original period field except `holdings`. |
| `holding` | `value` is one original complete holding dictionary, including provider extensions. Preserve rank order. |
| `end_period` | All `names` holdings must precede this marker. Empty periods have zero holding records. |
| `end_trial` | Complete `summary` without `periods`, plus its period count. The last period must have its original final-period flag. |
| `complete` | Batch `summary` without `trial_results`; total trials, periods, holdings, prior record count and ordered `sha256`. |

Period dates must be contiguous. Trial boundaries, declared counts, required
holding fields, completion and final flags are checked. Financial arithmetic is
not reinterpreted by the codec. Its source is the shared portfolio reducer.
An unsupported version, missing record, wrong ordering, checksum failure,
duplicate JSON key, invalid date or mismatched completion fails closed.
Trailing bytes also fail. An incomplete file is never an empty financial result.

Metadata, summary and holding values must be detached finite JSON values. Object
keys are strings. Nulls, omitted fields, number types, signed zero, diagnostics,
Unicode, labels and extension fields survive. No rounding or projection occurs.
Financial contract 1 and saved snapshot versions 1/2 retain their meanings. This
codec neither converts nor replaces those saved snapshots.

## Physical framing and limits

Each piece starts with an unsigned four-byte big-endian payload length and a
one-byte final-piece flag (`0` or `1`). A nonempty payload follows. Then 32 bytes
contain SHA-256 of `flag_byte + payload`. The maximum payload is 1 MiB. Records
use finite JSON with compact separators. Writer output uses ASCII JSON escapes.
The reader also accepts valid UTF-8 JSON. A JSON record can span many pieces.

For each record before `complete`, compute SHA-256 over its exact JSON bytes.
Feed those 32-byte digests, in order, into one SHA-256. Its hex digest is the
completion record's `sha256`. The completion record has its own piece checksums.
These checks detect corruption and ordering changes. They do not authenticate a
hostile writer that replaces both content and hashes.

Callers must declare a total encoded byte ceiling. This includes piece headers
and checksums. The record ceiling defaults to 8 MiB. It cannot exceed 8 MiB.
Piece and record limits can be smaller for tests. Nesting is limited to 64
levels. A period can exceed both limits because its holdings are separate
records. One holding or metadata value can span pieces, but its record must fit
the declared record ceiling. Exceeding a limit fails; evidence is never omitted.

These are encoded-byte bounds. They are not process-memory, filesystem-block or
disk-space quotas. Readers retain bounded records and header/final metadata.
JSON scalar temporaries and decoded objects also occupy memory. The financial
evaluator retains its current complete candidate book separately. Checks run
before each record and physical piece. The caller can use those checks for
cancellation and prospective safety limits. Partial writes stay incomplete.

## Remaining integration

The [capacity design](plans/compiled-backtest/phases/CB-14.capacity-design.md)
now has an explicit dormant runtime transfer and temporary Jobs owner. It
adds dormant queue/library persistence in increment 4. ResultArtifacts, browser
inspection and streamed exports remain separate work. Full application capacity is not qualified by these private operations. Existing Session preflight, 64 MiB IPC
and snapshot limits remain. G03 and G06 remain failed. No default-engine or launcher change follows.

## Explicit runtime and temporary Jobs evidence

CB-14 increment 3 adds a dormant `calculate_into` operation to Session, runtime
and Candidate. `Jobs.start_evidence` calls this operation. Existing `start`,
eager calculations, queue calls, legacy endpoints and browser routes keep their
complete-result contracts and admission limits. The new operation has no capture
parameter. Complete-trial observers still receive original complete trials.

The child first writes one bounded readable spool. Sealed trial views remain
available for checkpoint retention. After completion, `numerical_transfer` copies
its exact bytes through one 64 KiB binary slot. Each transfer has a fresh identity,
length and SHA-256. Each piece binds sequence, offset, length and hash. The parent
acknowledges that identity and sequence after a successful write and slot closure.
The child waits before replacing the slot. Final acknowledgement follows exact
saved-byte verification and complete codec validation. Missing, corrupt, duplicate,
reordered or interrupted transfers cannot publish a job result. Stop and callback
failures retain the existing runtime retirement proof and original error.

Recorded plans use a fixed runtime-owned file. Its versioned reference contains
length, hash and file identity; it accepts no path. Serialization uses bounded
buffers. Reading rejects links, replacement, duplicate keys, nonfinite numbers,
truncation and changed content. Staged plans have a separate 16 MiB encoded bound.
The complete decoded plan remains in memory for existing calendar/binding APIs.
The 8 MiB codec metadata-record bound still applies independently. These are
finite limits, not arbitrary-size plan support. Complete plan and submitted
settings validation precede checkpoint lookup and calculation. Dates are never
resampled. Eager requests retain their 1 MiB bound; eager payloads retain 64 MiB.
Original configuration callbacks still receive the complete plan.

Existing Jobs owns its private temporary workspace through `job_evidence`.
It reserves both producer and receiver evidence ceilings, two staged-plan ceilings
when a plan is supplied, and two 64 KiB slot buffers. The aggregate default is
1 GiB of charged temporary evidence/input storage. It is a private dormant
accounting policy, not a filesystem quota or accepted workflow budget. Runtime
request, statistics and bounded callback files remain separate. SQLite checkpoint
pages and journals remain under the checkpoint owner's separate accounting.

While receiving, the whole reservation remains charged. On success, Jobs checks
the copied bytes and codec again, then publishes its own immutable completed
file. It removes staged inputs and charges actual surviving bytes. Failed input
cleanup remains charged. Completed results have the existing four-run and
24-hour retention. Admission exhaustion preserves earlier completed results.
Retries bind operation kind, settings and a canonical hash of the complete plan.
Eager result graphs retain their existing policy; they do not use this byte budget.

`Jobs.open_evidence(id)` supplies a pinned Reader without financial ownership.
Expiry or four-run retirement ends new access first. Existing readers keep their
original bytes and charge until they close. Parent data operations retire the
child before financial access; they do not invalidate the Jobs copy. Shutdown
joins calculations and drains readers. Failed file cleanup retains ownership
and charge for a later `Jobs.close()` retry. Unknown files are never removed.
This workspace has no independent job registry, scheduler or durable user store.

The new descriptor appears only in explicit evidence jobs. It is not a browser
snapshot and cannot replace an eager `trial_results` value. [Queue/library copies](durable-evidence.md) now use shared bounded validation
and atomic chunk publication inside their existing databases. Explicit opening
detaches a charged temporary reader before releasing it to the caller. Deleting
the source cannot invalidate that reader. ResultArtifacts readers and streamed
exports remain increment 5. Application routing stays eager until those consumers
preserve complete evidence.
