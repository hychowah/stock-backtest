# Offline numerical generations

CB-04 adds an offline input artifact. It does not route website requests to
Numba. Automatic startup integration belongs to CB-12. The installed website
and the independent `scripts/revalue.py` stay on their existing paths.

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

The CB-08 calendar adapter and CB-09 portfolio reducer change the whole-source
hash of `schedules.py`. The daily engine fingerprint includes
`schedule_calendar.py` and `portfolio_results.py`. Existing
daily caches need ordinary offline preparation, followed by numerical export.
Older artifacts cannot validate as current. Financial formulas stay the same.
Format 1, temporal interface 1 and factor interface 1 stay the same. This source
change does not create a new financial policy version or rewrite old evidence.

CB-09 adds an offline complete-result diagnostic. `NumericalPortfolio` in
`tools/numerical_portfolios.py` borrows an explicitly owned attachment and the
accepted complete-book provider. It stages one complete eligible book at a time
in private memory, calls the existing SQL selector and uses the same portfolio
reducer as ordinary schedules. It opens no default application database and
does not invoke the historical measurement runner. Close its private workspace
and the provider before closing the attachment. Keep source-before-import and
source-before-cache ownership throughout. The existing attachment validator
still checks current inputs before a diagnostic request.

The [financial result contract](portfolio-results.md) defines version 1 outside
existing job payloads. Complete holding rows, status strings, nulls and array
order stay intact. Fixed monthly requests and explicit weekly dates use the
same reducer. Explicit dates retain their existing monthly envelope. This adds
no website control, selected-only optimization, production routing or persistent
runtime. Historical benchmark admission stays closed.

CB-10 adds an offline random adapter in `tools/numerical_trials.py`. It composes
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
generations only when they have no live or uncertain reader lease. It never
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
`sessions` and `treasuries`. It contains no backtest or saved-trial tables.
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
when requested. An attachment does not borrow a prepared database connection.

For library use, construct `GenerationStore(schedules)`, call `prepare()`, then
use `with store.open_current() as inputs:`. Library callers own source before
imports. Calculations retain ordinary project cache ownership through native
work and final resource closure. Call `inputs.validate()` before each job inside
that ownership scope. It rechecks current prepared metadata, raw inventory and
source policy. An old attachment can stay open but cannot validate after its
inputs change. Close evaluators and all borrowed array views
before closing the attachment. Borrowed views expire when attachment closes.

Each attachment holds an OS-locked lease outside its immutable directory.
Idle attachments can keep old mappings while publication selects new inputs.
Close releases SQLite and mappings before the lease. Failed close retains a
strong owner and the lease for explicit retry. Process death releases its OS
lock. Retirement can then reclaim its abandoned lease.

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

CB-05 adds `scripts/numerical_temporal.py`. Its `TemporalEvaluator(inputs)`
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

CB-06 adds `scripts/numerical_factors.py`. `FactorEvaluator(inputs)` borrows an
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
