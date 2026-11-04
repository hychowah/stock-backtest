# Durable evidence snapshots, version 3

The queue and saved library have additive evidence operations. They store complete
results inside their existing databases. Opening needs no calculation, candidate
readiness, financial generation or checkpoint. The additive acquired-reader path connects
version 3 through ResultArtifacts for inspection, saving and complete attachments.
Automatic submission and queue execution still use eager version-1/2 results.
Read the [reader contract](evidence-views.md) for acquisition and browser lifetime.

## Operations and ownership

`backtest/application/durable_evidence.py` owns one representation and copy implementation.
It owns no database path, financial lock, scheduler or job registry. Queue and
library owners keep their existing transactions, limits, receipts and mutations.

```
with jobs.open_evidence(job_id) as source:
    metadata = {
        'version': 3, 'kind': 'random',
        'settings': original_submitted_settings,
        'catalog': original_catalog, 'presentation': original_presentation,
        'captured_at': original_capture_time,
        'result': source.manifest['summary'],
    }
    record = library.save_evidence(name, metadata, source)

with library.open_evidence(record['id']) as opened:
    original_metadata = opened.metadata
    for record in opened.reader.records():
        consume(record)
```

`Store.save_evidence(name, metadata, reader)` creates a complete independent
library record. The library cap remains atomic at 20 across connections. It never
evicts a record. As with eager `save`, a repeated call creates another record.

`backtest.application.queue.Store.finish_evidence(id, metadata, reader)` completes an already
running queue record. It verifies the submitted settings, original labels and
exact stored plan. An acknowledged Stop wins over later completion. Exact
completion retries keep the first bytes and revision. Conflicting retries fail.
The queue cap remains 100 visible records. Deletion keeps its deleted-ID receipt.
Held edits, settings versions, ordering, shutdown/requeue and eager execution
remain in the queue owner. This operation does not calculate or schedule work.

Both stores expose context-managed `open_evidence(id)`. Opening uses a dedicated
consistent read transaction to copy into a charged private temporary stream.
The transaction and connection close before the reader is yielded. Deleting
its source then removes visibility and durable chunks, while the opened reader
remains usable. Opening can briefly delay a competing writer while acquiring
the copy. No WAL mode change or lifetime-long database read lock is added.
Same-database copies use the same independent reader lifetime.

Each request from an acquired display opens a separate file handle and uses
`opened.reader.reopen(stream)`. It hashes the complete file before exposing rows.
The exact bytes must match the acquired reader's complete codec-validation proof.
It does not repeat complete semantic decoding for each request. Consumer traversal
uses `verified_records()`, which checks the complete physical identity again before
yielding. It retains framing, piece, limit and decoding checks. The original proof
supplies semantic validation. Ordinary `records()` keeps all its checks.
The proof retains no rows or offsets and
ends with the acquired lifetime. Initial durable copying and opening still
validate complete destination evidence. No persistent cache or index is added.

The caller pins a Jobs source through the entire save. Job expiry ends new
access. Existing pins keep their bytes and Jobs charge until closure. Durable
copies contain no source path or reference to another record. They remain
independent after Jobs closure, child retirement, generation replacement and
checkpoint eviction. Read the [temporary evidence contract](result-evidence.md).

## Representation and atomic completion

Each database gains `evidence_chunks(record_id, ordinal, payload)`. Ordinals are
zero-based and contiguous. Payloads are 64 KiB, except the final shorter chunk.
Each record owns its own chunks; no cross-record deduplication is used.

The existing `snapshot` BLOB contains `CBDSNAPSHOT`, bytes `00 03`, then finite
JSON. Its envelope holds version 3, owning record ID, the complete encoded
application metadata, and an evidence descriptor. The descriptor holds exact
byte length, physical SHA-256, chunk count/size, codec limits and the original
completion manifest. An envelope SHA-256 binds the exact encoded metadata and
descriptor together. JSON object keys must be unique. Hashes detect corruption;
they do not authenticate a hostile writer that replaces data and hashes.

Application metadata contains version, kind, submitted settings, scalar result
summary, catalog, presentation, captured time and any original extension fields.
The current producer supports custom and random dated evidence. January results
retain their eager snapshots. Metadata settings agree with the original evidence
header. Omitted random seeds retain their submitted meaning; the full recorded
plan preserves the generated seed. Metadata result agrees exactly with the
original footer. No empty `periods` or `trial_results` array is fabricated.

The original [format-1 codec](result-evidence.md) bytes are copied unchanged.
This preserves every trial, period, holding, date, diagnostic, extension, status,
null, number type and signed zero. The common helper validates the stored bytes
again through `result_evidence.Reader`, including order, counts and completion.
It adds no financial formulas or tolerance. Validated source objects alone do
not prove that copied destination bytes are intact.

Publication holds `BEGIN IMMEDIATE` through copy, destination validation, envelope
insertion, record completion and commit. Uncommitted chunks are staging. There
is no incomplete visible record, staging registry or recovery scheduler. All
copy failures roll back. Independent readers see the old state or the complete
new state. A process interruption before commit cannot expose partial completion.
The source and earlier records remain intact. SQLite keeps its existing full
synchronous rollback-journal behavior. No automatic vacuum or eviction is added.

## Limits, storage and cleanup

The explicit operation has a 256 MiB per-copy evidence ceiling. Application
metadata is at most 8 MiB encoded. Incremental encoding rejects oversized
metadata before constructing its complete encoded value. The envelope is at most 32 MiB. Codec piece
and record limits retain their separate 1 MiB and 8 MiB maxima. Copies read and
write at most 64 KiB at a time. Codec decoding retains bounded records and
header/footer metadata. Decoded JSON and encoder temporaries are additional
memory; these encoded limits are not process-memory limits.

All default Store instances share one process-local 4 GiB reservation budget.
Tests and private owners can pass a shared smaller `durable_evidence.Budget` as
`evidence_budget`. Copy admission charges existing database/sidecar files twice,
four times evidence plus estimated envelope bytes, and 1 MiB of fixed allowance.
The envelope estimate includes twice encoded metadata, the manifest and 4 KiB.
This conservative charge covers destination staging, page/index overhead and
rollback journals. It remains held through commit or rollback. SQLite serializes
writers in one database. Concurrent copies in other databases share the process
budget. Source Jobs or detached-reader copies retain their own charges too.

Available storage must cover the reservation. Other processes and applications
can still consume free space afterward. SQLite errors therefore still roll back.
This is conservative admission accounting, not a machine-wide reservation,
filesystem quota or bound on allocated blocks. Existing eager operations retain
their prior policies. `durable_evidence.files(db)` reports current file, journal,
WAL/SHM, page and free-page bytes for measurement. Post-commit zero journal bytes
do not establish a journal high-water value. Deletion can leave free SQLite pages.

Opened readers charge their full temporary evidence length until cleanup.
Temporary files use private `.evidence-reader-*` names beside the store. Closing
first closes the handle, then removes the file. Failed cleanup retains a strong
owner and its charge. `budget.collect()` retries those failures; admission also
retries pending cleanup. Unknown files are never deleted. Abrupt-process reader
file scavenging is not implemented. Such reclamation remains operational work.

## Compatibility and verification

Eager `save`, `get`, validators, HTTP routes, complete-trial capture and browser
ResultArtifacts keep their eager contracts. Old version-1/2 compressed BLOBs
are read without rewriting them. Explicit `open_evidence` accepts version 3;
legacy records continue through eager `get`. Eager `get` rejects version 3 with
an explicit reader-required error and preserves the record. Additive browser readers, bounded inspection and streamed attachments are
provided by [capacity increment 5](evidence-views.md). Automatic producers remain eager.

Focused checks are `tests/test_durable_evidence.py`, existing library, queue,
Jobs, codec, runtime and candidate checks. They use private fictional assets on
WSL and native Windows. The shared store remains independent of browser and HTTP transport.
`tests/test_evidence_views.py` covers acquired lifetimes and HTTP attachments. G03/G06 remain failed. CB-14
is incomplete and CB-15 remains blocked. Operational gates are not waived.

## Scalar application metadata dispatch

Phase 6 Slice 2 reuses this version-3 durable container and chunk storage for
explicit application artifact 4 / evidence codec 2. Artifact 3 / codec 1 retains
its existing meaning. Metadata validation rejects mismatched application/codec
pairs. The container version does not determine either version. No durable rows
are migrated or rewritten. Existing reservations, publication/transfer receipts,
acquired-reader lifetimes and deletion precedence remain the same. Latest
artifact-4 screens are readable temporary results but cannot enter the historical
saved-backtest library. See the [Phase 6 compatibility record](plans/custom-variables/master-plan.md).
