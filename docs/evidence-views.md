# Acquired result readers

The [submission contract](#dated-submissions-and-replay) defines new requests,
recorded replay and legacy compatibility. The application artifact and evidence
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

## Workspaces

`website/browser/workspaces.js` changes workspace visibility without replacing
the mounted strategy form. Opening a result publishes its artifact without
restoring draft settings. Copy settings and Edit a copy retain the existing
held-edit protection. Recorded parameter rows reuse `BacktestComparison.describe`.
Desktop review shows them in a side column; phones have a Settings section.
The bottom status bar consumes existing direct-run and queue state. Its dialog
borrows the mounted queue panel, including the same controls and polling owner.

## Sector selections

Selection reads sectors only when opened. `backtest/application/result_sectors.py`
traverses acquired evidence once, retaining sector statistics for each trial.
A selected trial also returns compact period counts. The all-trial mean first
averages entry allocations within a trial, then weights complete trials equally.
Empty books contribute cash. Unknown stays in the denominator. Incomplete trials
remain visible and are excluded from the combined mean. No daily exposure or
synthetic combined portfolio is inferred. Original settings and labels stay pinned.

`SectorView` keeps the current artifact's compact all-trial summary and selected
trial detail. It never fetches every holding page to construct the charts.
Selecting a sector uses bounded holding pages with original ranks and weights.
Stock Details keeps the remaining fields and formula Explain action available.
Stock return contributions load when their disclosure opens and still use the
whole original book. Filtering or paging the stock table does not change them.

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

## HTTP operations

All paths below start with `/api/backtest-runs/<reader-id>/reader`.

| Method and suffix | Operation |
| --- | --- |
| `POST` | Acquire from `{source: {kind: "run" / "saved" / "queue", id: source_id}, display: context}`. Fresh Jobs need the original catalog, presentation and capture time in `display`. Durable sources keep stored context. |
| `GET /page/trial/<trial>/0` | Read one trial summary, period count and short/empty counts. |
| `GET /page/periods/<trial>/<cursor>` | Read bounded period rows in original order. |
| `GET /page/holdings/<trial>/<period>/<cursor>` | Read bounded stock rows in original rank order. |
| `GET /sectors/<trial>` | Read all-trial statistics (`all`) or one trial's statistics and period counts. |
| `GET /sector-holdings/<trial>/<period>/<cursor>/<sector>` | Page one sector. The final path part is URL-encoded JSON: a string or null for Unknown. |
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

`backtest/application/evidence_views.py` reads validated immutable evidence.
Trial summaries use the reader's compact directory, built during initial
validation. A summary request decodes only its original summary record. Short
and empty counts use that trial's recorded ranks and period sizes. Period and
holding pages still scan sequentially and retain bounded rows.

The old eager GET routes retain version-1/2 responses. Evidence-backed records return
an explicit `requires_reader` error. The library accepts `{name, reader}` on its
existing POST route. It pins complete server evidence through `save_evidence`;
it never trusts a browser descriptor as a complete result. Existing library caps,
queue receipts, held edits, exact plans and Stop/shutdown rules stay with their
original owners. Old records reopen without rewriting their stored bytes.

Inline sector views use `POST /api/backtest-sectors` with `{result, selection}`;
selection is `all` or a one-based trial number. This request uses the existing
eager operation admission, body ceiling, cancellation and shutdown drain.
Sector replies use the existing evidence response byte bound. They need no
current financial generation, catalog or calculation.

Inline saved and queue GET responses have one 128 MiB encoded JSON limit,
including the record metadata around the snapshot. The browser uses that same
limit for these opens. Library saves and queue-to-library copies check the complete
saved response before publication. An oversized inline result is refused with
“This inline backtest exceeds the 128 MiB save and open limit.” The queue keeps
the completed source visible as **Completed — waiting to save**, displays the
limit reason and does not retry that transfer automatically. It never deletes or
recalculates that source. Existing stored bytes are never rewritten. Evidence pages retain their
32 MiB response bound. Eager exploration retains its 512 MiB request ceiling.

## Ordered strategy requests

The service accepts `strategy-intent/2` and `strategy-capture/2`. The current
browser form still submits the existing shapes. The block builder and visible
step evidence belong to later work.

A version-2 strategy has `universe: {pool}` and an ordered `steps` list. Market
stays in `options.market`. Universe has no size or metadata bounds. A Rank step
has `kind: "rank"`, `source`, `direction`, `rank_from` and `rank_to`. A Filter step
has `kind: "filter"`, `source`, `op` and `threshold`. A chain needs at least one
Rank and permits at most 50 steps. Each Rank keeps its inclusive range from the
incoming survivors. The last Rank sets final order, ranks and ranking value.
Later Filters keep these ranks and add no replacements.

Sources name built-in IDs or exact formula revisions. Financial parameters and
measures remain formula captures. Stored Universe fields use
`{kind: "field", field: "market_cap"}` or `enterprise_value`, `sector`, `exchange`.
Numeric Filters permit `lt`, `gt`, `le` and `ge`. They keep submitted units,
canonical thresholds and exact stored comparison scales. Sector and exchange
use `eq` and a string threshold. Built-in source descriptors and complete formula
closures stay detached. Formula roots keep step order, including repeated roles.

`selection.execute` owns the ordered loop. `scalar_execution.Executor` loads
stored lanes once for the scope. Consecutive Filters form one group. Stored
checks run together first. The surviving rows then evaluate the needed formula
roots together in one program, sharing dependencies. Each row's formula values
are cached for later steps. Only Rank survivors retain rank outcomes; final
holdings add Filter pass outcomes in captured step order. Cancellation checks
run at step boundaries. Annual statistics are within one company; they do not
depend on other survivors.
Missing values fail only steps that use them. Ties use candidate rank, null
first, then symbol. Signed zero keeps its original value.

Capture/1 translates only for execution. Filter-first becomes Filters then
Rank; rank-first becomes Rank then Filters. Both capture versions use the loop
and read stored lanes through `book_store.lanes`. Metric sources keep its
complete-pair admission. Filter lanes keep their existing independent values.
Legacy flat requests retain contract 1 and the unchanged `screening.select`
SQL path for dated and latest runs, offline screens and parity checks.
No prepared data or financial cache identity changes.

The selection receipt's `matches` counts selected rows for legacy rank-first,
including a request with no Filters. Its `unavailable_ranking` count includes
only evaluated rows with an unavailable final ranking value. For formula
rankings, rows removed before evaluation are excluded from this count.
The `step_count` run-log field replaces the former `conditions` field.

Capture/2 holdings record `scalar_evidence.steps` with zero-based step indexes,
source lane references, canonical values, units and rank/pass outcomes. Only
selected holdings retain this evidence, including random-date holdings. Detailed
formula operation traces keep the existing fixed/latest policy. Old evidence
stays unchanged; missing step evidence is never reconstructed. Artifact 4,
codec 2 and financial contract 2 keep their versions and byte ceilings.
Both `backtest.run` paths log controlled `market`, last-Rank
`ranking_source_kind` (`builtin` or `formula`) and `step_count`, excluding Universe.
Legacy requests log their translated counts.

## Dated submissions and replay

Every new dated browser submission uses a strategy capture and bounded evidence,
including built-in-only forms. `StrategyDraft.captureBuiltins(options)` is the one
browser conversion owner. Fresh fixed, custom-calendar and random forms call it
before request identity allocation. Copies capture only when submitted. Built-in
conditions keep prepared sheet values and display units. Inclusive minimum yield
and maximum multiple remain explicit bounds; they do not become formulas.
New built-in captures reopen in the ordinary controls. Latest built-in screening
stays local; latest formulas use captured execution.

Legacy SQL treats a null minimum cap, EV or yield as an empty selection. Captures
use null to omit a bound. Conversion therefore refuses a legacy request with any
of these null minimums: it cannot replay that selection exactly. Existing captures
retain their null meaning and bytes.

Replay and calculated trial inspection use the same conversion. A legacy replay
converts a detached copy of the recorded plan's selection only. Dates, nominal
blocks, seed, samples and the shared window stay exact. A captured replay keeps
its original capture and plan. Stored results and request records are never
rewritten. Opening and stored trial inspection never calculate.

Existing waiting and held legacy queue rows retain their request format and eager
execution. Saving a held legacy edit reads its actual form mode, independently
of a capture cached by Run backtest. An unchanged selection or name-only edit
keeps the recorded seed and plan. Choosing formula mode explicitly submits a
capture and changes the selection.

The capture ceiling remains 192 KiB. Captured settings, request wrappers and
display metadata together have a 256 KiB encoded limit. A recorded `planned`
value is checked separately against `evidence_transfer.MAX_PLAN_BYTES`, the
existing 16 MiB plan allowance. It does not consume the settings allowance.
The run endpoint retains its 16 MiB whole-body transport limit. Queue submission
retains its 256 KiB whole-body limit. No content is truncated.

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
remains selectable, including incomplete trials. Evidence-backed inspection reads
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
request pin. It reads the original trial summary directly. It retains the
filename, metric and exact content length, with no stock rows or CSV body.
Scheduled attachments traverse holdings twice: once to count, then to stream.
Standalone `csv()` stays lazy. Standalone `filename()` reads no holdings.

The formatter follows JavaScript finite-number spelling, including integral
floats, signed zero and exponent boundaries. Tests compare seeded float64 values
with JavaScript; actual browser downloads supply complete CSV byte comparisons.
Encoded limits do not bound decoded JSON, compiler state, mapped residency or
browser memory. HTTP streaming alone proves no browser-memory limit.

Read the [codec](result-evidence.md) and [durable storage](durable-evidence.md)
contracts for complete evidence and byte ownership.

Initial reader construction validates the complete codec and builds its trial
directory. Each request reopens an independent stream and checks the complete
physical identity. Summary reads and record traversals check it again before
decoding. This detects changes in an unread suffix too. Framing, checksums,
cancellation and ordinary record validation stay in force. The directory ends
with the acquired reader; it changes no saved format or durable record.

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
each selected row's formula value, unit and reason without a formula operation trace. Each
holding carries its stored lane values; no separate `lanes` or `admission`
record repeats them. The scope receipt still counts the complete prepared
population. Older results keep their explanations and open unchanged.

For legacy filter-first captures, stored conditions and bounds run before
formula conditions. Rows without a usable stored ranking are removed first.
The ordered selector generalises this survivor optimisation to every chain.
It evaluates each needed source for surviving rows and reuses cached values.
The recorded indexes still address the complete scope's rows. Stored lane
reads and admission still cover the prepared scope.

The complete `evidence` attachment streams the original checksummed framed file,
including its captured strategy and every explanation. Scalar `holdings`/`screen`
CSV includes original values, units, direction and qualified links; retain its
companion evidence file for full offline explanation. Counted attachment lengths
and existing independent request pins remain unchanged. Old codec-1 exports
retain their original bytes. See [custom-variable compatibility](plans/custom-variables/master-plan.md).
