# Acquired result readers

Source contract. Automatic producers remain eager. The CB-14 record gives the
verification scope and remaining operational gates.

The [30 October performance direction](plans/compiled-backtest/master-plan.md)
sets no absolute user waiting-time limit. It seeks about 4× over the original
ordinary method, or close, with effort proportionate to the gain. Resource and
experiment limits remain unchanged. Candidate eager/bounded observations do not
measure that original-method speedup. Older budget questions are historical.

Version-3 results use the same `ResultArtifacts` boundary for fresh Jobs,
saved-library and queue opening. They preserve original settings, labels,
summaries and complete evidence. Inspection and downloads need no current
financial generation, calculation readiness or calculation. Automatic submission
and queue execution remain eager. Current eager limits are unchanged.

## Ownership

`backtest.application.result_access.ResultAccess` owns a finite collection of
acquired read lifetimes. It is separate from Jobs and its four calculation-run slots.
Acquisition reserves one of 16 display slots before opening outside the state
lock. A client supplies an unguessable 32-character hexadecimal identity.
An exact retry returns the same acquisition. Conflicting reuse fails.

Fresh acquisition pins the original Jobs file. Durable acquisition adopts the
existing charged detached `Opened` lifetime. Source expiry or deletion ends new
acquisition. It cannot invalidate an acquired display. Each request opens an
independent stream through its owner, so concurrent requests share no seek
position. At most 32 requests can hold pins at once. Excess admission fails
explicitly; it never evicts a displayed result or user record.

Release ends new requests. Active request pins retain the bytes until closure.
Shutdown closes admission, drains acquisitions and requests, then releases the
display lifetimes before temporary Jobs storage. Failed cleanup retains an owner
and its charge for retry. Jobs and durable storage keep their separate existing
byte budgets. Reader counts are admission limits, not memory or disk quotas.

`ResultArtifacts` releases the old display and aborts its outstanding detail
requests on replacement. Page departure sends a release too. An unsuccessful
departure notification can retain an orphan until service shutdown. There is no
automatic crash reclamation or display eviction. Durable temporary-file cleanup
after abrupt process death retains its separate documented limitation.

## Additive HTTP operations

All paths below start with `/api/backtest-runs/<reader-id>/reader`.

| Method and suffix | Operation |
| --- | --- |
| `POST` | Acquire from `{source: {kind: "run" / "saved" / "queue", id: source_id}, display: context}`. Fresh Jobs need the original catalog, presentation and capture time in `display`. Durable sources keep stored context. |
| `GET /page/trial/<trial>/0` | Read one trial summary, period count and short/empty counts. |
| `GET /page/periods/<trial>/<cursor>` | Read bounded period rows in original order. |
| `GET /page/holdings/<trial>/<period>/<cursor>` | Read bounded stock rows in original rank order. |
| `GET /export/<kind>/<trial>` | Download complete `holdings`, `returns` or `random` CSV. |
| `DELETE` | Release the display. Existing request pins remain valid. |

Trials and periods are one-based integers. Cursors are immutable zero-based row
offsets. Pages return identity, rows, cursor, next offset and total count. A null
next offset means completion. Normal pages target 256 KiB and at most 64 rows.
One codec-valid record can exceed the target, up to the codec's existing 8 MiB
ceiling. Responses have a separate 32 MiB bound. Page sizing, response admission and
HTTP output use one UTF-8 JSON serializer. Lone surrogates remain JSON escapes.
Byte checks measure the bytes sent, so ASCII expansion cannot reject an otherwise
valid maximum-size Unicode record. A page never drops stored rows.
Following every next cursor visits each matching row exactly once.

`backtest/application/evidence_views.py` scans validated immutable evidence. It has no index,
financial input, database path or scheduler. It retains bounded rows rather than
assembling complete trials or periods. An index or other performance layer needs
a measured requirement before implementation.

The old eager GET routes retain version-1/2 responses. A version-3 record returns
an explicit `requires_reader` error. The library accepts `{name, reader}` on its
existing POST route. It pins complete server evidence through `save_evidence`;
it never trusts a browser descriptor as a complete result. Existing library caps,
queue receipts, held edits, exact plans and Stop/shutdown rules stay with their
original owners. Old records reopen without rewriting their stored bytes.

## Browser composition and exports

`backtest/application/result_access.py` owns acquisition for run, saved and
queue sources. It preserves the complete request as retry identity. Durable
metadata stays with its stored source. A valid release remembers its ID even
before acquisition registers. The bounded history retains 128 released IDs.
Failed cleanup retains its source owners and byte charge for retry.

`ResultArtifacts.use(source, consume, {current, display})` owns browser access.
It tries eager saved and queue reads first. Only `requires_reader` selects the
evidence route. It records its requested ID before POST. Lost, malformed and
rejected responses release that requested ID. The synchronous consumer runs only
while its selection is current. Publication transfers the reader to its view.
A refusal before publication releases it. A later presentation error preserves
the published reader until replacement or page exit. In-flight IDs participate in
page-exit cleanup. Network release remains best effort.

One immutable artifact owns completed metadata. Mutable forms remain separate.
Library opening, queue opening and recovery restore through `StrategyDraft`.
A held draft refuses replacement and releases an unaccepted acquisition. Opening
tickets, artifact identities and selection revisions fence late responses.

The schedule view retains one period page and one stock page. Navigation reaches
every period and stock. Charts identify their displayed range. Every random trial
remains selectable, including incomplete trials. Version-3 inspection always reads
stored evidence; it never falls back to calculation.

Attribution traverses every selected holding in two ordered bounded passes.
It retains aggregates and the top ten rows. The complete stock count supplies
the denominator. Signed ordering, symbol ties, original addition order and
separate gain/loss normalization match eager attribution. Table pages do not
change attribution.

The current selection requests its first holdings page once. The initial table
and both attribution passes share that bounded immutable page. Each pass fetches
any subsequent pages in original order. Moving the table does not change the
attribution input. Period, sequence and artifact fences still reject late replies.
There is no page map, cross-selection reuse or general transport cache.

`backtest/application/result_exports.py` emits complete UTF-8 attachment bytes in chunks of at
most 64 KiB. It preserves eager CSV columns, row order, quoted cells, escaped
quotes, CRLF separators, no final separator, numeric spelling and filenames.
Random schedule exports use the selected trial. Downloads use ordinary attachment
navigation, without whole-result browser flattening or a CSV Blob.

The service acquires the request pin and validates selection before headers.
A bounded counting pass supplies Content-Length, then a second pass streams the
same immutable bytes. Disconnects and read failures close the transport and pin.
They cannot turn a partial file into a complete-length successful attachment.
An active export survives release of its display and deletion of its source.
Shutdown can interrupt it and then drains the request before deleting bytes.

`result_exports.prepare(reader, kind, trial)` prepares one attachment within that
request pin. It resolves the original scalar trial summary once. It retains the
filename, metric and exact content length, with no stock rows or CSV body.
`chunks()` performs a fresh bounded formatting pass. Scheduled attachments use
three prefix traversals: summary selection, counting and streaming. They do not
repeat presentation coverage inspection for filename and CSV passes. Standalone
`csv()` stays lazy, and standalone `filename()` does not count a file. Existing
formatting and the first-chunk-before-headers rule remain unchanged.

The formatter follows JavaScript finite-number spelling, including integral
floats, signed zero and exponent boundaries. Tests compare seeded float64 values
with JavaScript; actual browser downloads supply complete CSV byte comparisons.
Encoded limits do not bound decoded JSON, compiler state, mapped residency or
browser memory. HTTP streaming alone proves no browser-memory limit.

Read the [codec](result-evidence.md) and [durable storage](durable-evidence.md)
contracts for complete evidence and byte ownership. CB-14 remains incomplete.
G03/G06 remain software-admission failures, not proof of hardware RAM exhaustion.
Operational gates remain unresolved; CB-15 is blocked. Increment 6 must use actual
hardware and workflow observations before choosing routing or higher limits.

Initial [increment-6 observations](plans/compiled-backtest/master-plan.md)
retain eager routing and every existing limit. They separate physical RAM,
changing available memory, recursive graph accounting and encoded result bytes.
The small fictional representation probe does not qualify a larger workload.
The native four- and 24-trial eager workflows pass on 64 fictional companies
over a four-month weekly window. Complete inspection, ordinary-reference parity,
saving, ordinary-service reopening and all 116 CSV downloads pass. This supports
the unchanged eager policy for that scope. Broader-input and full-window
capacity, workflow acceptance and final route/limit selection remain open.

A separate [fresh FMP prefix](plans/compiled-backtest/master-plan.md)
uses 192 private symbols and four weekly trials in January–May 2015. It preserves
68 periods and 3,400 holdings. Original API results pass strict ordinary-reference
comparison. Complete browser values, saving, ordinary stored reopening and all
18 CSV downloads pass. The successful rerun reuses preparation and starts with
empty numerical checkpoints. Four unavailable historical Treasury observations
remain explicit input gaps outside this prefix. This diverse cohort has
present-day selection bias. It supplies no full-universe, full-window, cold
workflow or acceptance qualification. Eager routing and all limits stay unchanged.


The [retained-input twelve-trial continuation](plans/compiled-backtest/master-plan.md)
passes on the same cohort and calendar with empty numerical checkpoints. All
204 periods, 10,200 holdings and 50 fresh/reopened CSVs are complete. Strict
original-API comparisons have zero numerical differences. Every CSV cell and
paired byte sequence agrees. Ordinary reopening forbids financial dependencies.
The successful workflow reuses preparation and can reuse ordinary reference books.
Its sampled browser private bytes are 862,760,960; samples are not hard peaks.
Entry and private-orchestration failures remain retained. No larger eager allowance
or routing change follows. The next proposed resource observation uses the
existing bounded interfaces at the same twelve-trial scope, after a new declaration.


The [same-plan bounded real-input observation](plans/compiled-backtest/master-plan.md)
produces all twelve trials, 204 periods and 10,200 holdings. Original typed codec
trials pass strict ordinary/eager comparisons after a retained private comparison
repair. The actual consumer workflow fails the existing browser session deadline
after 47 fresh periods and five complete CSVs. All completed CSV cells and bytes
agree, but saving, ordinary reopening and the remaining 45 files are not reached.
No complete bounded-workflow or resource-acceptance pass follows.

At the time of that failed observation, each request opened an independent stream
and constructed a Reader. Reader construction validated the complete codec before
page scanning. A read-only
probe on this 6,532,415-byte file measures 6,532,415 validation bytes per reader,
plus the requested-prefix scan. A final-period holdings request reads 13,050,888
bytes in that isolated probe. Fresh Jobs also checks the complete physical file
hash; that extra pass is outside those Reader/page counts. The probes do not
isolate the cause of the complete browser delay. Those historical receipts remain
unchanged.

The subsequent [consumer fix](plans/compiled-backtest/master-plan.md)
profiles the actual service and browser path. Repeated complete semantic decoding
dominates early requests. Prefix decoding is meaningful for late requests. Physical
hashing is a small part of their cost. The independent design keeps complete
validation at initial construction and binds its proof to the exact decoded
physical bytes. Acquired Jobs and durable displays use `Reader.reopen` for each
independent request stream. That operation checks the complete physical length
and hash before returning. Changed unread suffixes fail too. Ordinary record traversal
retains its existing checks. No validation is inferred from file metadata.
This proof has no rows or offsets and lives only with the acquired reader.
Request pins, deletion, expiry, release and shutdown keep their existing owners.
After a retained failed complete rerun, the independent design supplement adds
`verified_records()` at this existing consumer boundary. Each traversal confirms
the whole physical proof before exposing records, including an unvisited suffix.
It then decodes bounded records without repeating semantic value/order validation
already established for those exact bytes. Framing, checksums, limits, JSON
decoding and cancellation remain. Ordinary codec iteration and initial complete
validation keep their existing behavior. Exports use this same traversal boundary;
their counting, output passes and byte formatting remain unchanged.
No index, persistent cache, format, formula, automatic route or limit changes.

## Shutdown ownership

Queue shutdown intent precedes closing calculation and job admission. Result
admission then closes. The server joins the queue, drains acquired readers, joins
jobs and retires their temporary workspace, joins HTTP requests, and retires any
calculation child. This order keeps job bytes alive through acquired request pins.
The native bootstrap holds source ownership through the entire sequence.

## Scalar artifact 4

The same acquired-result owner dispatches codec 2 without current library,
catalog or financial access. New `scopes`, `explanations` and `screen` operations
use the existing bounded cursor pages. Trial/period/holding operations retain
their shape for historical scalar results. Scope/chunk-qualified links identify
the original explanation records. Latest has screen rows and no trial.

New scalar results keep explanations for the selected rows only. Each
evaluation chunk keeps its whole request list, so links stay valid, plus the
results of selected rows and the operations, observations, contexts and roots
they reach. Built-in `lanes` and `admission` records also cover selected rows
only. The scope receipt still counts the complete prepared population. Older
results keep every candidate's explanation and open unchanged.

The complete `evidence` attachment streams the original checksummed framed file,
including its captured strategy and every explanation. Scalar `holdings`/`screen`
CSV includes original values, units, direction and qualified links; retain its
companion evidence file for full offline explanation. Counted attachment lengths
and existing independent request pins remain unchanged. Old codec-1 exports
retain their original bytes. See [Phase 6 compatibility](plans/custom-variables/master-plan.md).
