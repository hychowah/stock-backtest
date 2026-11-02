# Offline numerical generations

## Current execution ownership (CB-19G)

Python owns recorded plans, shared SQL selection, the financial reducer,
checkpoints and application lifetime. The selected complete-book provider stays
behind that boundary. Compiled Numba is the sole production provider; Original
remains the default application engine. Read
[candidate startup](candidate-startup.md#current-optional-native-setup-cb-19g)
for genuine selected preparation and separately labelled comparison-only Rust setup.
Normal preparation and calculation import no Rust capability or native resource.
The forwarding comparison factory and multiple Preparation profiles are removed.
Historical app configurations require their exact retained source, not current dispatch.

Runtime and Session use `ExecutionPolicy.from_configuration`. It preserves old
per-provider workspace/cache allowances while resolving aggregate capacity once.
The parent's resolved identity and its original observation/provenance reach
Session together. A second observation cannot silently change workers or threads
after checkpoint lookup. Admission observations stay outside stable identity.

The first actual worker verifies readiness and supplies its cold private-memory
sample. Remaining required workers can then initialize concurrently. Startup
transport reserves four source-owned messages per configured worker. Each worker
keeps its own launch deadline. Other workers' traffic cannot extend that deadline.
No financial task reaches a partially ready pool. Identity, launch, timeout or
cancellation failure poisons the pool and closes every adopted worker.
Windows memory observations use
[job information queries](https://learn.microsoft.com/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject).
The current-usage layout follows
[Microsoft's hcsshim definition](https://github.com/microsoft/hcsshim/blob/main/internal/winapi/jobobject.go).

Protocol writes share one atomic, bounded, cancellable publication operation.
Windows pending writes preserve the genuine native error code. Only recognized
sharing/access classes get bounded retries. Payload and required statistics must
publish before a completion frame. Failed statistics cannot prevent error or
cancellation reporting. The earlier F statistics-replacement hypothesis remains
historical. Its exact external locking cause is unproven.

Complete recovery validates the generation, source and configured compiler/layout
before reuse. It starts no trial workers, constructs no provider and compiles no
factor kernel. Actual constructor and factor-compilation counters have positive
fresh controls and remain zero on a new-runtime full recovery. Durable queue and saved-result readers remain engine-neutral. No input
format, financial formula, historical report cutoff or immutable result shape
changes in this integration.

## Historical generation interfaces

CB-04 adds an offline input artifact. It does not route website requests to
Numba. CB-12 adds separate closed candidate preparation; see
[candidate startup](candidate-startup.md). The installed website
and the independent reference calculator keep their existing financial behavior.
The calculator now lives in `backtest/engines/reference/revalue.py`.

Use the tested NumPy environment. From the project folder, run:

```
python scripts/numerical_generation.py prepare
python scripts/numerical_generation.py attach
python scripts/numerical_generation.py retire
```

`prepare` requires current research and daily preparation. It checks the full
saved-price inventory, the existing research readiness rules and the canonical
report binding. It rejects pending deployment or baseline publication. It does
not prepare raw inputs, download data or change the canonical report. A stale
cache requires the ordinary offline preparation before numerical export.

CB-14 also binds daily inputs to the price inventory accepted by the prepared
research database. Editing an existing raw price file need not change its parent
directory timestamp. Research preparation accepts the new file inventory first.
The prior daily cache then fails validation until daily preparation rebuilds it.
Numerical export rejects that mismatch. A new generation cannot bind new inventory
evidence to old daily prices. The binding preserves filename/size/mtime semantics;
it does not add raw content hashing or per-book raw-inventory scans.
The explicit-root offline-capture and current prepared-generation adapters compare
the same accepted inventory digest. Missing or mismatched evidence fails closed.
Existing historical receipts are not rewritten. Benchmark admission stays closed.

The CB-08 calendar adapter and CB-09 portfolio reducer change the whole-source
hash of `schedules.py`. The daily engine fingerprint includes
`backtest/calendar.py` and `backtest/portfolio_results.py`. Existing
daily caches need ordinary offline preparation, followed by numerical export.
Older artifacts cannot validate as current. Financial formulas stay the same.
Format 1, temporal interface 1 and factor interface 1 stay the same. This source
change does not create a new financial policy version or rewrite old evidence.

CB-09 adds an offline complete-result diagnostic. `NumericalPortfolio` in
`backtest/engines/numerical/portfolio.py` borrows an explicitly owned attachment and the
accepted complete-book provider. It stages one complete eligible book at a time
in private memory, calls the existing SQL selector and uses the same portfolio
reducer as ordinary schedules. It opens no default application database and
does not invoke the historical measurement runner. Close its private workspace
and the provider before closing the attachment. Keep source-before-import and
source-before-cache ownership throughout. The existing attachment validator
still checks current inputs before a diagnostic request.

CB-14 removes unused annual-history reads from source-derived ranking
execution. The current-metric adapter executes the authoritative calculator
body from `metrics.py`. The three-year adapter keeps its source guards and uses
the prepared average and source-derived numeric outputs. It accepts the known
`annual_average(history, observation['fiscal'], 3)` dependency only when that
callback is the calculator used during export. Neither adapted interface takes
an unused history argument. Selected-report reads remain unchanged.

Construction rejects remaining history dependencies, dynamic namespace access,
unsupported scopes and ambiguous or unrecognized substitutions before candidate
results can be returned. Supported observation and average guards still execute
and bind source identity. A valid ordinary formula outside this candidate subset
remains available through ordinary calculation. There is no automatic fallback,
new history cache or relaxed freshness check. The adapter source participates
in normal generation binding; use ordinary numerical preparation to decide
whether a new generation is needed. Research and daily preparation remain current
when their own input fingerprints have not changed.

The [financial result contract](portfolio-results.md) defines version 1 outside
existing job payloads. Complete holding rows, status strings, nulls and array
order stay intact. Fixed monthly requests and explicit weekly dates use the
same reducer. Explicit dates retain their existing monthly envelope. This adds
no website control, selected-only optimization or production routing.
CB-11 adds the explicit runtime described below. Historical benchmark admission stays closed.

CB-10 adds an offline random adapter in `backtest/engines/numerical/random.py`. It composes
the complete-result diagnostic with generation-bound completed-trial checkpoints.
The shared robustness consumer preserves summaries and ordered full capture.
Whole-plan and current-input checks precede checkpoint lookup. Recovery uses the
recorded dates and never samples replacements. Full hits bypass provider work
and SQL staging. The borrowed provider remains owned by its caller.

Checkpoint payload retention defaults to 256 MiB and 32 experiments. SQLite
overhead, free pages and journals are separate from that payload budget. Only
derived experiments can be evicted. Ordinary books and durable queue/library
snapshots remain independent and readable after generation changes. See the
[checkpoint contract](trial-checkpoints.md). This source change adds no routing
or numerical-generation format change. The new completed-result validator changes
the reducer source fingerprint; prepare and export current private inputs before
attachment reuse.

`attach` verifies the current artifact, opens its buffers and records read-only,
prints its identity and load observations, then closes it. It still checks
current input metadata. An artifact hash alone does not prove current inputs.
The existing path, size and modification-time freshness guarantee stays in use.
A same-size edit with a restored timestamp remains outside that guarantee.

`retire` keeps the current and previous generations. It removes older verified
generations only when they have no live or uncertain reader lease or gate. It never
waits for a reader. Damaged or unknown directories require explicit review.

`python scripts/numerical_generation.py recover` restores the verified previous
pointer. This is an explicit recovery operation. It preserves the damaged files.
The previous artifact can be valid but stale. Attachment still rejects stale
inputs. Run export to make a current artifact after such recovery. A corrupt
pointer that cannot identify its previous generation fails closed.

All command paths resolve from the source file. A moved project can reuse its
artifact if the prepared relative input inventory and source contents still
match. The command takes shared source ownership before application imports.
It then takes the ordinary project cache coordinator.

## Operating yield spread support — 31 October 2026

The experimental engine now supports `operating_yield_spread_3y`. `metrics.py`
remains the formula owner. `PolicyProgram` executes that calculator during annual
specialization with symbolic current EV and dated 10-year Treasury yield. It
retains source arithmetic order and the source-selected annual constants.
Factors and complete books consume the same numerical output. They do not
implement a second financial formula.

The generation includes `treasury10(day, yield_percent)` in `records.sqlite`.
`DatedYields` returns the latest saved observation on or before entry. An empty
series or no preceding observation returns no value. Zero and negative yields
stay valid. The three-month series retains its separate existing policy.
Missing annual inputs or a missing 10-year yield leave only this threshold
unavailable. A stock fails that condition only when it is requested.

The expanded parameter width, field schema, policy and source hashes invalidate
older generations and trial checkpoints for new calculations. Prepare a current
experimental generation. Durable saved results remain readable. Format 1 and
temporal/factor interface versions remain unchanged. Unknown future catalogs
still fail preparation. This source extension makes no performance or real-data
capacity claim. See the [implementation record](plans/compiled-backtest/phases/CB-16.operating-spread.md).

## Format 1

The ignored store is `data/numerical/`. Each published directory name is a
SHA-256 identity. `manifest.json` contains the format, prepared binding, array
schema and complete file inventory. Identity is SHA-256 of canonical JSON for
these four fields. JSON has sorted keys, compact separators and no NaN values.
Each inventory entry binds the file's exact byte count and SHA-256.

The binding contains daily base-input metadata, current raw price-file metadata,
the canonical report content hash, the source-derived policy signature and
relevant source-content hashes. Mutable dated books, saved trial results,
database sizes, absolute project paths and observation times are excluded.
There is no persisted executable state or pickle. Compiler and runtime identity
belong to evaluator execution identity and stay outside the persisted input format.

Each numerical buffer is a non-object, little-endian NPY file. The manifest
records its dtype and shape. `raw_*` names retain compatibility with the tested
input interface: these buffers hold the selected **valuation** series from the
daily cache. They do not imply that every value is an unadjusted market price.
`adjusted_*` contains the separately saved dividend-adjusted series.

| Buffers | Meaning |
|---|---|
| `raw_offsets`, `raw_days`, `raw_values` | Sparse valuation histories by original symbol ID |
| `adjusted_offsets`, `adjusted_days`, `adjusted_values` | Independent sparse dividend-adjusted histories |
| `symbol_sort` | Symbol IDs in alphabetical order |
| `cached_mask` | Membership in the prepared cached-price set |
| `report_symbol`, `report_fiscal`, `report_known` | Stable report identity and ordinal dates |
| `report_cap`, `report_enterprise`, `report_yield` | Prepared annual valuation inputs |
| `average_3y`, `financial_parameters` | Source-calculated annual specialization; missing values stay NaN |
| `cached_*`, `legacy_*` | Pool offsets, report IDs, known dates and fiscal dates |

Offsets use signed 64-bit integers. Other IDs and ordinal days use signed 32-bit
integers. Values use 64-bit floats. The cached mask uses Boolean values.
Sparse missing prices have no entry. The two price series never fill each
other's missing dates. The original symbol order is the first statement
occurrence in source row order, followed by alphabetical price-only symbols.
Reports within a symbol use fiscal date and original row order. This retains
the original buffer tie order independently of `symbol_sort`.

`records.sqlite` contains `symbols`, `reports`, `companies`, `financial_inputs`,
`sessions`, `treasuries` and `treasury10`. The three-month and 10-year series
remain separate. It contains no backtest or saved-trial tables.
Financial JSON is copied verbatim from prepared inputs. It is not a second raw
cache. `owner.json` identifies store-owned exports and abandoned staging trees.

## Memory and resource ownership

Export writes directly into mapped buffers. Price cursor batches have at most
4,096 rows. Record batches have at most 4,096 rows and a 1 MiB target. A single
record may use up to 4 MiB. Annual specialization holds one symbol's history,
with at most 16,384 annual or financial records. Larger inputs fail export.
It never creates the complete Python price or annual-history graph.
Mapping address space and OS-managed resident pages still grow with artifact
size. These bounds do not claim a hard resident-memory limit or a disk quota.

Attachment maps arrays read-only. It loads symbol IDs, sessions and Treasury
rows once. `report_rows[index]`, `histories[symbol]` and `financials[symbol]`
read records on demand. They retain no history cache. Company rows load only
when requested. An attachment reads these immutable records by default.
Phase 7 adds optional coordinator-owned prepared readers
through `inputs.prepared_scopes()`. Each reader borrows the current research
database under the caller's existing source and financial ownership. It checks
the accepted input, price, observation and report bindings against that exact
attachment. Latest and January keep their authoritative prepared populations.
Delegated workers cannot open these current-research readers.

For library use, construct `GenerationStore(schedules)`, call `prepare()`, then
use `with store.open_current() as inputs:`. Library callers own source before
imports. Calculations retain ordinary project cache ownership through native
work and final resource closure. Call `inputs.validate()` before each job inside
that ownership scope. It rechecks current prepared metadata, raw inventory and
source policy. An old attachment can stay open but cannot validate after its
inputs change. Close evaluators and all borrowed array views
before closing the attachment. Close optional prepared readers before mappings
and the attachment lease. The attachment adopts each reader before construction;
failed validation and failed SQLite closure retain that owner for retry.
Borrowed views expire when attachment closes. Public numerical scalar admission
remains closed pending Phase 7 qualification. This source capability changes no
running server or installed data.

Each ordinary attachment holds an OS-locked lease outside its immutable directory.
An attachment stays inside its caller's financial ownership scope, including
idle reuse. Coordinated publication waits for that scope to end. An old
attachment can remain leased during a private low-level publication test, but
that test does not permit an application to release financial ownership early.
Close releases SQLite and mappings before the lease. Failed close retains a
strong owner and the lease for explicit retry. Process death releases its OS
lock. Retirement can then reclaim its abandoned lease.

## Exact-generation worker attachment (CB-19A)

Current source can delegate an immutable generation to a trusted worker. This
capability does not start processes or change application routing. Original
remains the default. CB-19C supplies worker containment, parent monitoring
and shutdown through the explicit pool described below. CB-19A alone does not guarantee that an arbitrary worker stops when
its parent dies.

The coordinator keeps source and financial ownership and calls
`inputs.worker_reference()`. This rechecks current input freshness before it
returns a small JSON-compatible record. Its fields are integer `version=1`,
canonical absolute `store` and exact generation `identity`. The reference
contains no arrays or executable objects. It authorizes no preparation,
publication or recovery. A worker cannot issue another reference.

The worker owns source before importing calculation modules. It calls
`open_delegated(reference, schedules, checkpoint=ownership_checkpoint)`. The
checkpoint is required. It raises when ownership ends or work must stop. The
worker opens the exact generation, regardless of `current.json`. It verifies
all artifact content and reconstructs the source policy. Policy signature,
field schema, parameter width and generation-source hashes must match. It
does not inspect current raw inventory or prepared databases. It does not
recover publication or acquire financial ownership.

The returned `DelegatedInputs` has the existing numerical-input interface.
Its `validate()` checks that it remains open and calls the checkpoint.
Current-input freshness remains the coordinator's responsibility. Ordinary
`AttachedInputs.validate()` keeps its complete current-input check.

The coordinator creates one stable `gates/<identity>.lock` outside the
generation directory. It never replaces or unlinks this gate. Workers take
its shared OS lock before verification or mappings. Retirement and damaged
generation replacement require its exclusive lock without waiting. A held
or uncertain gate retains the generation. Existing UUID leases still protect
ordinary readers. The exclusive gate stays held through deletion or replacement.
Windows uses the existing source owner's shared/exclusive byte-lock helper;
POSIX uses `flock`. This gate is neither source nor financial ownership.

Ownership order stays source, financial ownership, generation gate, then
input handles for the coordinator. Workers use source, generation gate, then
input handles. Close private evaluators first. Attachment close releases the
records connection and mappings before its pin. Failed closure retains a
strong owner for explicit retry. Temporary verifier handles receive the same
protection. Reader process death releases its OS pin. A worker that pins first
blocks retirement. If retirement wins first, attachment fails without opening
generation files. Stable gate files prevent a second lock inode after deletion.

Private synthetic checks run on WSL and native Windows. They cover exact
read-only data, stale coordinator rejection, delegated source mismatch,
cancellation, closure retry, both race orderings, independent reader pins,
parent-process loss and abrupt reader death. Complete file release is checked
by native rename and removal after closure. These checks qualify attachment
ownership. They do not qualify a trial pool, real-cache capacity or speed.

## Publication and recovery

One coordinator owns export, pointer transitions and retirement. Export writes
to a uniquely named staging directory. It closes writers and verifies file
hashes, headers, shapes, sparse order and record relationships before rename.
Published buffers are never overwritten in place.

`publication.json` records the candidate and prior pointer before the atomic
`current.json` replacement. The pointer contains current and previous IDs.
Retry verifies the candidate and finishes the transition. An invalid candidate
restores a verified prior pointer. With no prior pointer, an incomplete first
publication is discarded and export can retry. Conflicting intent fails closed.
Readers still perform current freshness checks after recovery.

Owned abandoned staging trees are removed under coordination. Unknown trees
are preserved. A damaged generation can be rebuilt only when no reader holds
it; the damaged directory is preserved under a separate name before replacement.
Windows access and sharing failures receive the existing eight-attempt retry
policy, with less than two seconds of retry waits. Other file errors propagate.
These operations cover process interruption and atomic file replacement. They
do not claim durability through arbitrary hardware or filesystem failure.

CB-04 verification uses private synthetic inputs. It does not qualify real-data
capacity or make a new speed comparison. See the
[phase record](plans/compiled-backtest/phases/CB-04.md) for exact observations.

## Temporal interface 1

CB-05 adds `backtest/engines/numerical/temporal.py`. Its `TemporalEvaluator(inputs)`
borrows an open attachment. It does not compile factors or open another database.
The caller still owns source and cache through job validation and closure.
Close the evaluator before closing the attachment.

`select_reports(entries)` accepts a one-dimensional integer array of date
ordinals. It returns cached and legacy report-ID matrices, in that order.
Columns use original symbol IDs. An unavailable report has ID `-1`.
The known date must be strictly before entry. The source maximum report age
is inclusive. Equal-date variants retain their prepared order.

`resolve(symbols, days, columns, forwards)` accepts four equal-length vectors.
Symbol IDs use original order; `-1` means missing. Series `0` is valuation.
Series `1` is dividend-adjusted. Directions must be Boolean. Days must be valid
date ordinals. Empty batches use typed arrays. Invalid dimensions, IDs, dates
or lengths raise `ValueError` before native indexing. Closed evaluators and
closed inputs also raise `ValueError`.

Search includes an exact target date in either direction. Results retain
request order. Missing prices have day `0` and value `NaN`. The two series
never fill each other. Search returns the nearest observation without a time
limit. The existing source snapshot policy applies calendar-day tolerances,
short-holding exclusions and stopped-price exits. Financial policy is unchanged.

The existing sparse Numba kernels now have one implementation in this source
module. The benchmark adapter retains compatibility names and delegates to it.
The Python differential path stays separate. SQL selection, aggregation and
independent `revalue` remain unchanged. This does not change website routing.

Format 1 now requires `binding.temporal_version` equal to integer `1`.
The binding also hashes the temporal source. An older artifact without that
contract must be exported again. Unsupported versions fail verification.
The file layout and publication protocol stay at format 1. Temporal semantics,
financial policy and compiler versions remain separate identities.

## Factor interface 1

CB-06 adds `backtest/engines/numerical/factors.py`. `FactorEvaluator(inputs)` borrows an
open attachment. It calculates entry-date valuations, both ranking pairs and
requested threshold fields. It does not need an exit date or future returns.
It does not apply the original candidate buffer, financial thresholds, ranking
or portfolio selection. The website still uses its existing engine.

```python
with FactorEvaluator(inputs) as factors:
    batches = factors.evaluate(entry_days, pool='cached', threshold_fields=None)
```

Entry days are a one-dimensional integer array of date ordinals. The pool is
`cached` or `legacy`. `None` requests all 18 threshold fields. An empty collection
requests neither threshold values nor trailing price lookups. Both ranking pairs
are always present. Results keep entry request order, including repetitions.
Rows use original symbol IDs and selected report IDs. Reports absent at entry
produce no row. A row with unavailable valuation prices has invalid valuation.
Each ranking pair and threshold has a separate validity array. A missing PEG,
ROE, trailing return or three-year history does not invalidate other fields.

`EntryFactors.valuation` contains market cap, enterprise value and EBITDA in
USD. Each ranking pair contains multiple and yield. Thresholds use the existing
display units. Invalid values are NaN. Validity arrays define availability.
`PolicyProgram.fields` binds display descriptors, outputs and validity rules to
the authoritative metric catalog. `field_schema` identifies that binding and
the source-derived entry and trailing projections. Consumers need no formulas.
The policy module still imports without NumPy or Numba.

Source-guard execution, entry factors and generation preparation do not translate
compiled guards. `PolicyProgram.decisions` constructs that optional capability
only when explicitly requested. Unsupported compiled guard syntax fails that
request. It does not prevent the source-guard path from preparing or calculating.
Numerical expression and catalog validation still apply to both paths.

The base policy signature binds source files and numerical expressions without
generated guard code. A compiled guard program has a separate signature for its
base policy, generated code and status labels. Only compiled-guard execution adds
that signature to its compiler identity. Conservative source hashes remain in
generation and calculation identities. This identity change requires a fresh
offline numerical export; existing artifacts and derived checkpoints cannot be
reused as current. Durable saved results remain independent.

Entry guards and trailing dates come from the existing source. Fiscal and entry
price tolerances are not new factor settings. Trailing anniversaries still
clamp leap days. Prepared annual averages preserve `statistics.mean` rounding.
The strict Numba compiler is shared with the retained candidate executor. Full
candidate output remains unchanged. Factor projections omit exit, bankruptcy
and Treasury dependencies. Current source policy and `1e-12` tolerance remain.

The generation binding now requires integer `factor_version=1` and a field
schema hash. It also hashes the factor module. Older artifacts require ordinary
offline export again. Format 1, the arrays and publication protocol do not
change. Compiler versions and execution identity stay outside persisted format.

Each evaluator retains results in memory with deterministic LRU eviction. The
default retention budget is 16 MiB. It counts retained result buffers and Python
indexing metadata. Oversized entries are returned without retention. The default
request workspace bound is 64 MiB, using conservative row accounting before
factor allocations. These are workload bounds, not process-memory limits.
Caller-held results and compiler memory are separate. Returned arrays have
detached, immutable bytes owners. Results survive evaluator and input closure.

Reuse binds the input generation, policy and field schema, factor and temporal
versions, compiler execution identity, entry day, pool and normalized fields.
No disk cache or cross-process factor store is added. Close the evaluator before
the attachment. Its close clears retained results and compiled callables.
Callers still own source and financial access through freshness validation,
calculation and final closure. See the [CB-06 record](plans/compiled-backtest/phases/CB-06.md)
for verification scope and memory observations.

## Explicit persistent runtime (CB-11)

`backtest/engines/numerical/runtime.py` supplies `NumericalRuntime`. Current website
calculations, jobs and the queue still use the ordinary engine. The separate
CB-12 candidate preparation entry verifies and closes this runtime before
ordinary application owners start. Normal startup does not select it.
This source capability has no job IDs, queue service or user-result store.
An authorized caller must explicitly construct or inject it. The shared
application entry is the calculation owner’s `calculate` method.
`backtest/application/calculations.py` owns selectable dispatch.

Construct the runtime with an explicit source root, new private scratch folder,
numerical generation path, derived checkpoint path and Python interpreter.
`with NumericalRuntime(...) as runtime:` starts one owned child. Call
`runtime.calculate(mode, options, progress=None, configuration=None,
planned=None, capture=None, cancelled=None)`. `custom` returns the ordinary fixed
result. `random` returns the ordinary summary and ordered `trial_results`, as
the shared application adapter does. Optional capture observes complete trials.
Settings and IPC values are detached. Full result schemas and order stay intact.
The `planned` argument reuses recorded dates. Omitted random seeds still come
from `robustness.plan`; there is no second planner.

Public startup and calculation share one operation lock. A second caller
receives a busy error immediately. There is no pending submission queue.
The lock covers process construction, owner adoption, readiness and calculation.
Closure first requests Stop, then waits for that operation to settle. A late
constructor must adopt its owner and close it; it cannot publish readiness after
Stop. A close deadline during construction retains the runtime even when its
process owner has not yet been returned. It never reports successful closure. Reject dispatch if the calling thread
already holds the supplied or current financial coordinator. CB-13A removes
caller preholding from jobs, queue and legacy routes. One server-owned
`backtest.application.original_calculations.Original` owns ordinary financial
admission and cleanup.
Numerical dispatch remains unavailable. CB-13B must coordinate resident child
ownership, status and parent data operations before selecting that runtime.

The child takes shared source ownership before calculation imports. It disables
credential access by setting the existing key path to a private nonexistent file.
It then takes financial ownership. One financial session spans attachment,
prewarming, every job and idle reuse. The child validates current inputs before
result or checkpoint lookup. It also checks the loaded calculation source.
Changed source requires a new process. Each child also attaches at most one
input generation. A different current pointer fails before creating another
provider or dispatcher. Existing error cleanup closes that runtime. A new
explicit runtime can attach the replacement; no automatic restart occurs.
This process boundary prevents repeated generation changes from accumulating
unqualified compiler allocations. `attached_generations` is zero during setup
and one after attachment. There is no same-process replacement counter.
Coordinated publication normally waits for the runtime to close. The replacement
fixture models a private pointer change. Random work constructs zero coordinator
providers. It verifies complete old-resource closure, then uses a fresh child. Its checkpoint binding
misses the old generation. It does not bypass production financial ownership.

`backtest/engines/numerical/books.py`, `numba.py`, `portfolio.py`,
`workspace.py` and `random.py` own the promoted calculation code in the same
package. Callers import these owners directly. The former workspace, portfolio
and random tool aliases have been removed. Complete eligible
books still precede the existing SQL selector. No selected-only return path or
ordinary `book_batch` workers run inside the runtime. `backtest/engines/numerical/matrix.py`
prewarms the accepted writable contiguous float64 signature without fast math
or a disk compiler cache. Random workers calculate missing trials concurrently.
The parent saves completion order and presents recorded order.
CB-19D routes experimental random requests through the persistent trial pool.
`backtest/engines/numerical/execution.py` resolves threads from effective observed CPUs and
internal settings. Four threads remain an initial comparison default. They are
not a hardware ceiling. A selected larger layout needs no source edit. Numba's
initialization environment must permit the selected count before native imports.
An already initialized smaller team rejects a larger request without truncation.

Reuse has distinct accounting. Defaults are:

| Resource | Bound and behavior |
| --- | --- |
| Compiled matrix LRU | 16 MiB of exact numerical input keys, output buffers and Python metadata. Oversized entries finish without retention. |
| Detached fixed-result LRU | Separate 16 MiB. Exact generation and submitted options. Oversized results finish without retention. |
| Complete-book and matrix workspace | Separate conservative 64 MiB checks. One complete book at a time. |
| Complete result graph | 256 MiB. Conservative planned-period/holding admission, then incremental selected-period and completed-trial accounting. Oversized work fails without truncation. |
| IPC | 1 MiB request, 1 MiB stats, 64 MiB payload file, 16 KiB control frame and 16 pending parent events. Each callback is acknowledged before another payload is written. |
| Runtime diagnostics | Last 128 small events and the latest detached statistics. |
| Completed random trials | CB-10's independent 256 MiB serialized payload / 32-experiment defaults. |

The fixed-result cache is separate from numerical reuse. It is not a book-cache
hit counter. The complete-book path actually calls the matrix LRU. Repeated
threshold values can reuse identical numerical matrices while SQL runs again.
Disable fixed-result retention to measure this separately. FactorEvaluator uses
the same strict matrix abstraction with zero matrix retention; its existing
16 MiB entry-factor cache remains separate.

These numbers account owned work. They are not allocator, whole-process memory,
resident-memory or disk limits. Compiler memory, mapped residency, Python/IPC
copies and caller-held detached results are additional. `last_stats` reports
retained bytes, conservative workspace values, current sampled working set and
OS peak working set separately. OS peak includes cold compilation. A sample
is not a hard limit or full-universe capacity qualification.

`numerical_identity.compiler_identity` exposes a reproducible compiler signature
and its complete fields. It binds transitive local source content, policy,
field schema, catalog, bankruptcy set, Python/NumPy/Numba/llvmlite, platform,
byte order, target triple/CPU/features, configured CPU, thread count, threading
layer and strict/cache settings. Generation identity also participates in each
matrix key. Hashing edited source cannot update already loaded code.

Windows reads GO and later commands through one bounded raw UTF-8 frame parser.
It normalizes CRLF and preserves commands read alongside GO. The control reader
polls `PeekNamedPipe`. Binary `os.read` reads only bytes reported available.
It never blocks a Windows CRT/text stdin read while native DLLs load. The reader
still runs during cold imports, so cancellation and parent-death EOF remain
observable. POSIX retains its ordinary text reader. A truncated or oversized
Windows frame fails closed. The native import regression uses this actual
parser with a live reader and NumPy/Numba imports in one contained process.

Cancellation uses `backtest_control.Cancelled`, the caller predicate and explicit
runtime shutdown. Cold startup observes the same policy. Native arithmetic runs
in chunks of at most 1,024 rows by default. Price queries use chunks of 2,048.
Python row stages check at least every 128 rows, plus calendar, book, SQL and
trial boundaries. Input validation, a cold compiler call, one bounded report
search, SQL operations and serialization can still delay a checkpoint. There is
no hard cooperative cancellation deadline. The parent polls every 50 ms and
allows up to 30 seconds for the operation's cooperative drain by default.
Owner closure then has a separate grace period of up to 30 seconds before
termination. Process and descendant confirmation follows. These are separate
stages, not a total cancellation deadline. A test with each grace period set
to 0.5 seconds can therefore take about one second before confirmed forced
closure. Smaller fixture settings exercise that fallback; they are not a
measured real-data cancellation guarantee.

Startup records source-owned, financial-owned, session-import and
session-construct-prewarm stages before readiness. A timeout identifies the last
safe stage. The private diagnostics.json file keeps the bounded parent history.
A cancelled or failed call closes its runtime before its primary outcome is
raised. After confirmed cleanup, an observed `backtest_control.Cancelled` stays
`Cancelled`, including when cooperative drain times out or transport fails.
The original callback exception also remains the primary exception. Cleanup
mechanisms must not turn Stop into an ordinary job failure. Up to eight secondary
exceptions attach as `runtime_secondary_errors`; diagnostics contain their types
only. Diagnostic publication errors cannot replace the primary outcome.

Unconfirmed cleanup raises `ClosureError`, which retains `numerical_runtime`,
`primary_error` and `cleanup_error`. It does not raise a completed `Cancelled`
outcome. Retry `close()` after the active constructor or callback settles. The
caller can resolve the stored primary outcome only after closure is confirmed.
A stalled callback can outlive forced process termination; the runtime remains
explicitly uncertain until that caller drains. Closure states
are new, starting, ready, running, stopping, closed and failed-closure. No call
is accepted after shutdown begins. Partial or uncertain closure keeps a strong
retryable owner. A terminal message alone never establishes completion of close.

Cleanup closes checkpoint and private SQL connections, providers, retained
buffers, borrowed views, mappings and the generation lease. Both OS source and
financial lock handles remain open until terminal process exit. The child uses
`os._exit` only after explicit resource closure, inside both ownership scopes.
Process exit ends compiler state, native teams and the control reader, and the
OS releases those lock handles. The parent confirms process exit, EOF, reader
closure and descendant emptiness before reporting closed. Windows uses a Job
Object assigned before a suspended venv redirector resumes. Linux confirms a
cooperative session and known descendants; it does not prevent hostile session
escape. EOF cancels idle and active children after parent death. The Windows
Job also closes on owner death.

Private synthetic checks are `tests/test_numerical_runtime.py` and
`tests/test_numerical_matrix.py`. They cover serial/parallel full results,
ordered recovery/capture, actual matrix reuse, bounded rejection, stale inputs,
changed loaded source, startup/callback/cancel failures, parent death, owned
descendants and file release. OS/platform observations and any approved sample
results belong to the CB-11 phase record. This contract claims no installed
runtime change, new speed comparison or production routing qualification.


## Dormant bounded result operation

`Session.calculate_into` composes existing incremental numerical producers, the
codec and checkpoint owner. `NumericalRuntime.calculate_into(mode, options,
destination, ..., max_bytes=...)` receives that complete evidence into an empty,
readable, seekable binary stream. It returns a verified transfer receipt, manifest
and original metadata. The stream remains caller-owned and provisional until
the call succeeds. No complete-trial capture argument exists on this operation.

`Candidate.calculate_into` uses the same admission, operation lock, freshness,
parent handoff and confirmed-retirement paths as eager calculation. Existing Jobs
can explicitly start evidence jobs and pin completed readers. No calculation submission route or
queue execution adapter selects this operation. Additive HTTP reader operations
can inspect, save and export its completed bytes through ResultArtifacts.
These read operations neither calculate nor check current financial readiness. Explicit durable-store
methods can copy pinned Jobs evidence without acquiring financial ownership.
Their version-3 snapshots remain independent of current generations. See
[durable evidence](durable-evidence.md). The ordinary and
preview eager limits remain in force. Source/cache ordering, compiler ownership
and daily-price/root validation adapters retain their existing contracts.

The [evidence contract](result-evidence.md) specifies the acknowledged 64 KiB
slot, separate 16 MiB staged-plan ceiling, complete-plan validation, Jobs storage
reservation and reader lifetimes. These encoded-byte limits do not establish
process-memory or disk quotas. Full-path capacity and operational qualification
remain CB-14 work. CB-15 and default selection remain blocked.


## Current website alignment

The numerical generation, financial policy and result formats do not change in
CB-18. `backtest/calendar_requests.py` owns request representation and recorded-plan
validation shared with Original. Both engines import this canonical owner. Calculation source fingerprints include the shared owner. Prepare a new
numerical generation after upgrading changed calculation source; old immutable
results remain readable without preparation.

The Original adapter owns ordinary database/worker access. The experimental
adapter owns its numerical child. `backtest.application.calculations.Selectable` coordinates
admission, routing and confirmed cleanup before publication. Neither adapter
owns jobs, queue or library records. Shared prepared Latest/January views keep
their exact eligibility rules and offline browser calculation.


## Complete recorded trial operation

CB-19B adds `backtest/engines/numerical/trial.py`. `specification(binding, number)` detaches
one trial from the validated recorded plan. Its calculation identity uses the
existing canonical checkpoint binding. Its digest also binds the actual trial
number, exact dates, requested calendar, resolved window and selection settings.
The full batch is not sent with each trial.

`TrialEvaluator(portfolio, calculation_identity=...)` borrows an existing
`NumericalPortfolio`. `evaluate_into(spec, sink)` validates the specification,
saved-session calendar and selection before provider work. It emits complete
periods and returns the existing scalar summary. It never samples dates, changes
settings or writes checkpoints. Both fresh random adapters now use this operation.
The eager adapter collects periods under the existing planned-result and retained
graph budget. The streaming adapter retains one complete period. Session's
batch admission and existing recovery/commit/callback order stay unchanged.

`produce(spec, stream, limits=...)` seals one provisional artifact through
`result_evidence.SingleTrialWriter`. The actual recorded number is preserved,
including trial 37. `open_artifact(stream, descriptor, expected_spec=..., limits=...,
checkpoint=...)` verifies the trusted task envelope, complete sealed bytes and
financial evidence through the existing reducer. It exposes the original summary,
period replay and checkpoint-compatible `TrialView`. Extra fields remain intact.
Streams and immutable-byte lifetime belong to the caller. No path is accepted.

An artifact is calculated evidence. It is not a committed checkpoint, completion
event, application result or independently authenticated worker. CB-19C owns
worker readiness, task-owned scratch, containment and total resource admission.
CB-19D supplies concurrent commitment and ordered presentation. CB-19B creates no pool
or application route. Transitive calculation-source identity includes the new
module and codec. Old checkpoint rows are preserved with their original bindings.

## Persistent trial workers (CB-19C)

Current experimental random requests use this pool through CB-19D. Original
stays the application default. The parent owns checkpoint recovery/publication,
committed progress and recorded-order output.

`Session.pool()` creates its pool lazily. It shares the session's input attachment. The parent request workspace needs no
provider. A custom calculation can retain its separate lazy provider. The session closes workers before checkpoints,
portfolio, provider and input mappings. Financial and source ownership remain
with the existing runtime. Its Windows Job or POSIX process session contains
ordinary worker descendants. The pool creates no separate ownership domain.

`numerical_execution.ExecutionPolicy` owns internal settings. Its stable identity
records configured worker capacity, threads per worker, numerical-lane budget,
live-provider count, divided provider limits, task slots and artifact limits.
`TrialPool.execution_identity` adds the selected backend and compiler signature.
These fields are available before workers start. D can bind checkpoints, discover
missing trials, then start only the needed workers. Actual starts, free RAM,
timestamps, lifecycle allowances and memory-admission samples are diagnostics.
They do not change otherwise identical checkpoint identity. Fewer missing trials
do not redistribute spare numerical threads.

The initial default is one worker and up to four numerical threads, bounded by
observed effective CPU entitlement. Four is an initial comparison point, not a
ceiling. Explicit internal settings can select larger layouts. Validate
`workers * threads_per_worker <= numerical_lane_budget`. Effective observations
include affinity, applicable cgroup CPU quota or current native Job CPU rate,
memory/commit availability and relevant constraints. Unknown restrictions stay
unknown. CPU entitlement is a throughput observation, not a ban on thread creation.

Managed totals cover every declared provider, including the retained coordinator.
By default, resolve each complete-book/matrix check to the existing 64 MiB
per-provider allowance and each matrix cache to 16 MiB per provider. Record the
aggregate before division. The complete-book and matrix checks are separate
conservative estimates; their accounting is not a disjoint physical-memory sum.
Explicit totals can change these allowances. Legacy top-level Session workspace
and cache options keep their per-provider units; the internal `execution` section
uses aggregate units. A tiny configured total can still reject a complete book.
Nothing truncates or silently replaces it.

Start the first worker as a cold-cost probe. Readiness reports attachment and
initialization times, compiler identity, thread count, private-memory samples,
mapped/provider/SQL instance tokens and managed high-water counters. Check the
sampled cost of additional workers against observed available memory, commit or
container headroom and any explicit internal experiment allowance. This admission
estimate is not a future RSS guarantee. Compiler memory, Python objects and shared
mapped pages remain separate. Summed working sets do not prove unique physical
memory. CB-19F selects the final measured operating layout.

The fixed stdlib-only worker bootstrap starts an actual parent-lifetime observer
before application imports. POSIX uses an inherited pipe. Windows uses a duplicated
synchronization handle for the actual parent process. It then owns source, disables
credential access, verifies source identity, opens A's delegated generation and
constructs its selected private provider and portfolio. Readiness must match the
expected generation, source, backend, compiler and numerical threads. Native stdout
and stderr go to the null device; a separate descriptor carries bounded JSON.
The worker acquires no financial lock and opens no checkpoint, queue or library.

Use the pool through one active batch:

```python
with session.pool().batch(recorded_specifications) as batch:
    for completion in batch.completed():
        # D owns checkpoint publication through completion.artifact.view.
        completion.release()
```

The pool returns validated artifacts in observed completion order. Each submitted
or completed-but-unreleased trial reserves one fixed pool-owned slot and its full
maximum encoded-byte allowance. Default slots equal declared worker capacity;
default evidence allows 64 MiB per slot. These are program budgets, not disk quotas.
Filesystem free space is sampled before admission. Writes still enforce the
artifact's byte bound. Worker messages cannot choose artifact paths. Release closes
the read stream and removes task-owned files before freeing its reservation.
If every slot is held by unreleased completions, requesting more work fails
explicitly. Context exit releases remaining completed artifacts. Abandoning a
running batch or an observer failure poisons and closes the pool. No task is retried
silently and no backend fallback occurs.

Cancellation stops admission and reaches delegated attachment, initialization and
trial checkpoints. Parent death requests the same stop. A configurable finite
orphan/close allowance exists for ownership cleanup. The existing 120-second cold
startup and 30-second cleanup defaults are lifecycle allowances; C removes their
former arbitrary maximum values. There is no calculation-duration watchdog.
Stuck owned workers can be terminated inside the runtime's existing containment.
Close verifies child exit, EOF, reader termination, stream closure and native
handle release before removing reservations. Unconfirmed cleanup retains a strong
owner and raises the existing retryable `ClosureError`. Cleanup success is required
before cancellation is a completed outcome.


## Ordered random coordinator (CB-19D)

Experimental random requests now use one coordinator for eager and bounded
streaming operations. `numerical_workspace.RequestWorkspace` owns calendar and
shared SQL selection validation without creating a numerical provider.
`Session.validate()` attaches current inputs and predicts the complete compiler
identity without JIT compilation. Custom calculations construct their coordinator
provider on first use. Random calculations use delegated persistent workers.

Before opening a worker batch, the parent validates every recorded trial and
checks each checkpoint with bounded replay. It retains only availability and
scalar state. A complete recovery creates no provider or trial pool. Current
source, generation, settings and execution identity still participate in lookup.
Changed capacity or thread/provider settings select a different experiment. Old
rows are preserved. Runtime measurements record configured capacity separately
from the workers actually started for missing trials. Defaults remain provisional
until the CB-19F comparison.

Missing trials enter in recorded order. The parent validates and saves each
completed artifact immediately at its next service opportunity. A successful save
precedes completion progress. Retained artifacts release their reservations
immediately. Their checkpoints supply later ordered output. An unretained
artifact keeps its reservation until ordered output accepts it. This bounds
reordering even when the earliest trial is slow and retention is zero. The
earliest missing trial already owns a reservation, so it can finish without an
extra slot. Capture, trial rows and evidence always follow recorded order.

One parent writer owns the active experiment. Saves to that experiment preserve
its previous rows. No checkpoint read transaction remains open while waiting for
workers or writing another trial. If an expected retained row disappears or is
corrupt, the request fails explicitly. It never silently recalculates it.
Callback, output, cancellation and worker failures close the active batch and
preserve committed trials. Streaming output remains incomplete on failure.

Existing `numerical_random.run` and `run_into` diagnostic signatures retain a
local single-trial capability. It uses the same evaluator, sealed artifacts,
coordinator and financial checks. Eager result admission and cumulative result
accounting remain in force. Manual jobs and queue retries keep their submitted
engine and recorded plan. Saved readers still reopen immutable results without
calculation. No application request fields or tuning controls are added.

Focused synthetic checks are `tests/test_numerical_random.py`, the runtime,
bounded-trial and application adapter checks. They qualify correctness and
lifetime behavior, not real-input performance or large-result capacity.

## Complete period comparison (CB-19E)

CB-19E adds two internal comparison configurations beside the current source-guard
Numba baseline. `ExecutionPolicy` accepts `backend='numba_compiled'` or `'rust'`
only through trusted internal configuration. These are comparison configurations,
not application engine choices. Original remains the application default. The
experimental application's current source-guard Numba default is unchanged.
CB-19F must separate the gain from compiling guards from the language comparison.
CB-19G will retain the selected path after that decision.

Both compiled configurations consume the same `PolicyProgram` arithmetic and the
same validated `CandidateDecisionProgram` trees. Unsupported source syntax fails
attachment. Neither compiled identity can fall back to Python source guards.
`backtest/engines/numerical/candidates.py` owns the typed candidate layout and its mechanical
encoder. Each input row retains its original identity. Native output supplies
acceptance, fiscal/buy/sell ordinals, status tag, snapshot values, ranking-pair
values and validity, and requested threshold values and validity. Signed finite
thresholds stay signed. The encoder maps symbols, ordinals and tags to the
existing complete-book tuples. It makes no financial missing-value decision.

Rust and compiled Numba decide eligibility, source snapshot guards, exit status,
ranking-pair availability and finite requested threshold emission. Python still
plans reports and adjusted-price requests, derives calendar targets, builds the
numerical input matrix and mechanically encodes objects. Existing shared SQL
selects stocks. The existing reducer computes complete portfolios. Measure this
whole operation through the ordinary portfolio/trial boundary; kernel timing is
not a complete-period result. The same bounded factor cache serves both compiled
paths. Shared request planning and SQL are deliberate parts of this boundary.

`backtest/engines/numerical/rust_kernel.rs` defines a versioned synchronous C ABI. Buffers carry
addresses and element capacities. The Python bridge checks native dtype,
alignment, contiguity, dimensions, lengths, scalar/index ranges and writable
non-overlap. Native entry points check dimensions, size arithmetic and structural
ranges before using slices. Empty buffers need no valid null pointer. Calls
return finite error codes and publish no partial book after failure. The ABI
trusts caller-owned allocations and their lifetimes. It cannot validate arbitrary
hostile addresses. No pointer survives a call. Rust explicitly joins every numerical thread, including its thread-local
destructors, before the ABI returns. Automatic scope joining is insufficient for
that lifetime guarantee. A provider lock excludes close until all synchronous
calls return. Close drops callables, unloads the library,
then permits mapping closure. Bounded row/query calls retain cancellation checks.
Numerical threads come from C's attributed execution policy; Rust has no four-thread
clamp. Compiler children inherit the existing runtime containment.

`numerical_provider.py` predicts identities without building a provider. Rust's
identity binds policy and decision signatures, typed layout, generated source,
fixed native resource, compiler version/target and executable hash, strict flags,
linker identity, platform and ABI layout. Binary hashes are separate verified
build evidence. Temporary names, timings and resource telemetry do not change
execution identity. A full checkpoint hit performs no JIT or native build. It still requires the
selected compiler and performs a cancellable version/hash probe for exact identity.
Readiness still verifies the selected actual backend and compiler identity.

Rust compilation requires an explicit native compiler on PATH or
`BACKTEST_RUSTC`. An optional `BACKTEST_RUST_LINKER` selects a task-local linker.
`BACKTEST_RUST_BUILDS` selects task-owned build storage; the default is ignored
`tmp/numerical-rust`. Completed builds have unique immutable library paths and a
content-bound manifest. Workers share and verify a completed build. Changed
source or library bytes fail attachment; they are not silently rebuilt under an
existing receipt. Saved and actual source hashes must also equal the expected
generated-source hash. Fresh publication checks that equality too. Generated
source uses exact UTF-8 bytes on both platforms. Build time, reuse, library attachment and artifact bytes are
reported separately from deterministic identity. No global compiler installation,
provider download, live-cache benchmark admission or deployment is performed.

`tests/test_numerical_rust.py` uses private fictional assets. It checks complete
books and trials, supported fields and calendars, both orders/pools, source
mutations, malformed buffers, build binding, cancellation, library closure,
persistent native workers and complete recovery without compilation. Required native
Windows runs must supply a Windows compiler. A skipped native test is not
portability evidence. Correctness checks do not establish a speed improvement.
