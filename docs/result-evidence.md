# Bounded financial evidence format 1

This format preserves complete evidence without collecting all output in memory.
Captured scalar strategies use codec 2 through Jobs and the queue. Existing
codec-1 evidence remains readable. The [reader contract](evidence-views.md) owns
submission and replay behavior.
The [version-3 durable container](durable-evidence.md) stores complete evidence.
[Acquired readers](evidence-views.md) supply inspection and attachments.

`backtest/result_evidence.py` uses the standard library. It owns no database, job,
file path, financial lock or publication. Existing resource owners must supply
private files and control their lifetime. It does not add a user-result store.
Reading completed evidence requires no current inputs or financial calculation.

## Writing and reading

```python
writer = Writer(stream, trials=1, metadata=original_metadata,
                max_bytes=declared_output_ceiling)
writer.start_trial(1)
summary = portfolio_results.evaluate_into(pairs, select_period, writer.period)
# The caller can add its original options/calendar/seconds here.
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
records each trial summary's byte range and counts periods by their stock count.
This compact directory retains no holding or period rows. It stays with the
reader and is shared by its independent request streams. Stored bytes do not
change. The owner must pin immutable bytes through reading. Use one active
iterator per stream.

`reader.trial_summary(number)` checks the complete physical identity, then
decodes only that trial's original summary. It also returns immutable pairs of
stock count and period count. The presentation layer applies the summary's
requested ranks to those counts. Period and holding traversal stays sequential.

`reader.reopen(other_stream)` opens an independent reader of those exact validated
contents. Initial validation records the physical length and SHA-256 of the bytes
it actually decodes. Reopening hashes the complete other stream in buffers of at
most 64 KiB. Changed content, truncation and trailing bytes fail before metadata
or rows are exposed, including changes outside a requested prefix. Cancellation
checks continue between buffers. The owner must keep both streams immutable.
Each stream has its own seek position. Ordinary `records()` keeps its existing
checks, including after reopening.

The proof and trial directory end with the validated reader. Initial Jobs
publication, acquisition and durable destination validation still check the
complete codec. No persistent cache or stored index is added.

`reader.verified_records()` traverses an exact validated snapshot. It verifies
the complete physical length/hash again immediately before yielding any record.
This includes a suffix that the consumer will not visit. It then decodes bounded
records with the same framing, piece checksums, limits, duplicate-key handling
and cancellation checks. The complete proof supplies semantic value and order
validation, so those checks are not repeated. Fields, insertion order, numeric
types and signed zero are unchanged. The caller must preserve immutable bytes
throughout traversal. This is not protection against a concurrent hostile writer.
`evidence_views` selects this operation for pages and CSV traversal. Initial
construction and ordinary `records()` stay unchanged.

The caller declares the total ceiling. Piece and record ceilings retain the
format's existing 1 MiB and 8 MiB maxima. These codec limits bound decoding and
encoded records. They are not hardware recommendations or total process-memory
limits.

Ending a trial does not complete its batch. A cancelled or failed batch has no
final manifest. Existing owners control publication after successful completion
and required resource closure.

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

## Temporary Jobs evidence

`Jobs.start` selects bounded evidence when options contain a captured strategy.
Original's `calculate_into` writes scalar codec 2 in process. The
[submission contract](evidence-views.md#dated-submissions-and-replay) owns request
limits and legacy execution compatibility.
Application artifact 4 describes scalar results; the durable container remains
version 3. Existing application-artifact-3/codec-1 readers remain available.

`backtest/application/evidence_transfer.py` stages recorded plans in a fixed
runtime-owned file. Its versioned reference contains
length, hash and file identity; it accepts no path. Serialization uses bounded
buffers. Reading rejects links, replacement, duplicate keys, nonfinite numbers,
truncation and changed content. Staged plans have a separate 16 MiB encoded bound.
The complete decoded plan remains in memory for existing calendar/binding APIs.
The 8 MiB codec metadata-record bound still applies independently. These are
finite limits, not arbitrary-size plan support. Complete plan and submitted
settings validation precede calculation. Dates are never
resampled. Application request and eager-payload limits stay with their owners.
Original configuration callbacks still receive the complete plan.

Existing Jobs owns its private temporary workspace through `backtest.application.temporary_evidence`.
It reserves twice the evidence ceiling, two staged-plan ceilings when a plan is
supplied, and two 64 KiB buffers. The aggregate default is
1 GiB of charged temporary evidence/input storage. This is admission accounting,
not a filesystem quota or a process-memory limit.

While Original writes, the whole reservation remains charged. On success, Jobs
checks the written bytes and codec again, then publishes its own immutable completed
file. It removes staged inputs and charges actual surviving bytes. Failed input
cleanup remains charged. Completed results have the existing four-run and
24-hour retention. Admission exhaustion preserves earlier completed results.
Retries bind operation kind, settings and a canonical hash of the complete plan.
Eager result graphs retain their existing policy; they do not use this byte budget.

`Jobs.open_evidence(id)` supplies a pinned Reader without financial ownership.
Expiry or four-run retirement ends new access first. Existing readers keep their
original bytes and charge until they close. Data operations do not invalidate
the Jobs copy. Shutdown joins calculations and drains readers. Failed file
cleanup retains ownership and charge for a later `Jobs.close()` retry. Unknown files are never removed.
This workspace has no independent job registry, scheduler or durable user store.

Captured jobs publish an evidence descriptor instead of an eager result graph.
`ResultArtifacts` opens it through the acquired-reader path. It does not invent
an eager `trial_results` array. [Queue/library copies](durable-evidence.md) use
bounded validation and atomic chunk publication inside their existing databases.
Opening detaches a charged temporary reader. Deleting the source cannot
invalidate that reader. Inspection and exports read the original evidence.

## Additive scalar codec 2

`backtest/scalar_result_evidence.py` uses the same bounded physical framing.
`result_evidence.Reader` keeps format-1 meaning.
`open_reader()` dispatches the explicit header to codec 1 or 2. Codec 2 binds
scalar contract 2 and application artifact 4 through its application owner.
These versions are independently allocated; no formula namespace assigns them.

Codec 2 retains complete captured strategy/input identities, complete scope
receipts, ordered evaluation chunks, admission/built-in lanes, selection receipts
and selected screen or portfolio rows. References qualify scope and chunk. A
selected row cannot precede its complete scope and selection receipts. Latest
is screen-only, with zero trials/periods and no future-return fields. Old codec-1
trial/checkpoint readers are unchanged. See [scalar artifact 4](evidence-views.md#scalar-artifact-4)
for pages and complete offline evidence export.
