# Acquired result readers

Source contract. Automatic producers remain eager. The CB-14 record gives the
verification scope and remaining operational gates.

Version-3 results use the same `ResultArtifacts` boundary for fresh Jobs,
saved-library and queue opening. They preserve original settings, labels,
summaries and complete evidence. Inspection and downloads need no current
financial generation, calculation readiness or calculation. Automatic submission
and queue execution remain eager. Current eager limits are unchanged.

## Ownership

Existing Jobs owns a finite collection of acquired read lifetimes through
`job_evidence.Readers`. It is separate from the four calculation-run slots.
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

`website/evidence_views.py` scans validated immutable evidence. It has no index,
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

`website/result_exports.py` emits complete UTF-8 attachment bytes in chunks of at
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

Initial [increment-6 observations](plans/compiled-backtest/phases/CB-14.capacity6.md)
retain eager routing and every existing limit. They separate physical RAM,
changing available memory, recursive graph accounting and encoded result bytes.
The small fictional representation probe does not qualify a larger workload.
The native four- and 24-trial eager workflows pass on 64 fictional companies
over a four-month weekly window. Complete inspection, ordinary-reference parity,
saving, ordinary-service reopening and all 116 CSV downloads pass. This supports
the unchanged eager policy for that scope. Broader-input and full-window
capacity, workflow acceptance and final route/limit selection remain open.

A separate [fresh FMP prefix](plans/compiled-backtest/phases/CB-14.capacity6.real-inputs.md)
uses 192 private symbols and four weekly trials in January–May 2015. It preserves
68 periods and 3,400 holdings. Original API results pass strict ordinary-reference
comparison. Complete browser values, saving, ordinary stored reopening and all
18 CSV downloads pass. The successful rerun reuses preparation and starts with
empty numerical checkpoints. Four unavailable historical Treasury observations
remain explicit input gaps outside this prefix. This diverse cohort has
present-day selection bias. It supplies no full-universe, full-window, cold
workflow or acceptance qualification. Eager routing and all limits stay unchanged.


The [retained-input twelve-trial continuation](plans/compiled-backtest/phases/CB-14.capacity6.real12.md)
passes on the same cohort and calendar with empty numerical checkpoints. All
204 periods, 10,200 holdings and 50 fresh/reopened CSVs are complete. Strict
original-API comparisons have zero numerical differences. Every CSV cell and
paired byte sequence agrees. Ordinary reopening forbids financial dependencies.
The successful workflow reuses preparation and can reuse ordinary reference books.
Its sampled browser private bytes are 862,760,960; samples are not hard peaks.
Entry and private-orchestration failures remain retained. No larger eager allowance
or routing change follows. The next proposed resource observation uses the
existing bounded interfaces at the same twelve-trial scope, after a new declaration.


The [same-plan bounded real-input observation](plans/compiled-backtest/phases/CB-14.capacity6.bounded12.md)
produces all twelve trials, 204 periods and 10,200 holdings. Original typed codec
trials pass strict ordinary/eager comparisons after a retained private comparison
repair. The actual consumer workflow fails the existing browser session deadline
after 47 fresh periods and five complete CSVs. All completed CSV cells and bytes
agree, but saving, ordinary reopening and the remaining 45 files are not reached.
No complete bounded-workflow or resource-acceptance pass follows.

Each request opens an independent stream and constructs a Reader. Reader
construction validates the complete codec before page scanning. A read-only
probe on this 6,532,415-byte file measures 6,532,415 validation bytes per reader,
plus the requested-prefix scan. A final-period holdings request reads 13,050,888
bytes in that isolated probe. Fresh Jobs also checks the complete physical file
hash; that extra pass is outside those Reader/page counts. The probes do not
isolate the cause of the complete browser delay. Existing validation, routing
and all limits stay unchanged. Any request-lifetime optimization needs its own
independent design. No new index or cache is selected.
