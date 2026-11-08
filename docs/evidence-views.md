# Acquired result readers

Built-in submissions use eager results. Captured scalar strategies use bounded
evidence through `Jobs.start` and the queue. The application artifact and evidence
codec versions are separate from the version-3 durable container. Stored formats
keep their recorded meaning.

Evidence-backed results use the same `ResultArtifacts` boundary for fresh Jobs,
saved-library and queue opening. They preserve original settings, labels,
summaries and complete evidence. Inspection and downloads need no current
financial generation, calculation readiness or calculation.

## Explore a completed result

The dated result has an **Explore this result** panel. Choose saved holding
periods and an inclusive rank range within the original request. Apply summarizes
saved returns without screening, formulas, preparation or market inputs.

Random results open **Explore all trials** above the combined summary. One
selection updates every trial, combined statistics and the distribution chart.
Selectors name saved entry and exit blocks. The actual shared window runs from
the earliest selected entry to the latest selected exit. A selection beginning
with the first period keeps the original common start. Strategy and paired SPY
hold cash before each first selected trade and after each last selected exit.
Incomplete trials stay listed and are excluded from both distributions. Mean
CAGR remains an average of trial CAGRs, not one portfolio return.

`backtest/application/result_exploration.py` checks selections and uses the shared
Python mean, compounding and CAGR in `backtest/portfolio_results.py`. Ranks keep
their original meaning at each rebalance. Surviving holdings have equal weight;
missing ranks receive no replacements. A complete empty selection holds cash
at 0% until rebalance. SPY keeps its saved period return, and CAGR includes the
full elapsed window. Missing holdings or returns still fail explicitly. Apply
also supports older empty periods stored with null returns, without changing
the original artifact. Unchanged ranges without old empty-period nulls use
recorded totals to preserve rounding. Older January year labels allow total return but no CAGR
when exact boundary dates are absent.

`ResultArtifacts.reader(...).explore(...)` serves both representations. Eager
results use `POST /api/backtest-exploration`, with the original trial or whole
random batch and the existing byte limit. The stateless request reserves one of
the same 32 slots before decoding and participates in shutdown drain.
Codec-backed results use the existing reader pin:
`GET /api/backtest-runs/<reader-id>/reader/explore/<trial>/<first-period>/<last-period>/<first-rank>/<last-rank>`.
`trial` is a number or `all`. Batch aggregation takes two sequential evidence
scans, retaining compact trial boundaries between them, never full holdings.

`website/browser/result-explorer.js` owns the controls. Date labels come from
period pages for fixed tests and original trial metadata for random tests.
Edits cancel pending requests; replacement and selection checks discard late
replies. Reset restores the original summary. Holding details, downloads,
comparisons, replay and saving use the immutable original artifact. Exploration
creates no saved format or durable preference.

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
ceiling. Paged evidence responses have a separate 32 MiB bound. Page sizing, response admission and
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

Inline saved and queue GET responses have one 128 MiB encoded JSON limit,
including the record metadata around the snapshot. The browser uses that same
limit for these opens. Library saves and queue-to-library copies check the complete
saved response before publication. An oversized inline result is refused with
“This inline backtest exceeds the 128 MiB save and open limit.” The queue keeps
the completed source visible as **Completed — waiting to save**, displays the
limit reason and does not retry that transfer automatically. It never deletes or
recalculates that source. Existing stored bytes are never rewritten. Evidence pages retain their
32 MiB response bound. Eager exploration retains its 512 MiB request ceiling.

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
contracts for complete evidence and byte ownership.

Initial reader construction validates the complete codec. `Reader.reopen` checks
the complete physical length and hash for each independent request stream.
Changed content fails before rows are returned, including an unread suffix.
`verified_records()` checks that physical identity again before traversal. It
retains bounded decoding, framing, checksums and cancellation. The acquired
proof supplies semantic value and order validation for those exact bytes.
Ordinary `records()` retains all its checks. The proof holds no rows or offsets
and ends with the acquired reader. No index or persistent cache is added.

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

New scalar results explain the selected rows only. In latest and fixed-date
runs the column evaluator's detail mode traces those rows: the same
code that computed the values that ranked them. A trace keeps values, validity,
reasons, fiscal, known and observation dates, the session day, lookups and the
source file and its digest. It drops raw row positions, per-row hashes and
repeated report statements. A trace block larger than one evidence record is
split in half. Older results keep their reference-evaluator explanations, which
open unchanged in the same viewer. Random-date runs keep
each selected row's formula value, unit and reason without a step trace. Each
holding carries its stored lane values; no separate `lanes` or `admission`
record repeats them. The scope receipt still counts the complete prepared
population. Older results keep their explanations and open unchanged.

With a built-in ranking and filter-first order, formulas are evaluated only for
rows that are admitted, have a ranking value and pass every built-in condition
and bound. These conditions are checked once per row; the global selection
then applies the formula conditions to the remaining rows, and its recorded
indexes still address the scope's rows. No other row can be selected, so
holdings do not change. Admission and built-in lanes still cover every row.

The complete `evidence` attachment streams the original checksummed framed file,
including its captured strategy and every explanation. Scalar `holdings`/`screen`
CSV includes original values, units, direction and qualified links; retain its
companion evidence file for full offline explanation. Counted attachment lengths
and existing independent request pins remain unchanged. Old codec-1 exports
retain their original bytes. See [custom-variable compatibility](plans/custom-variables/master-plan.md).
