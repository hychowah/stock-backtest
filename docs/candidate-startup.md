# Experimental engine preparation

**Frozen.** The website does not offer or run the experimental engine. The
server refuses a request that names it, and no live module imports its source
(AGENTS.md, Engines). This document describes the frozen source and its last
qualified behavior. Unfreezing starts with its frozen tests in
`tmp/numerical-venv` (AGENTS.md, Tests).

<a id="current-optional-native-setup-cb-19g"></a>
## Current selected preparation (CB-19G)

Original remains the application default. Stored results open without the
numerical packages. Experimental calculation uses compiled Numba with the
measured 2×2 preference, reduced by current CPU and memory observations. Backend
and worker controls are not application settings. Read the
[final measured decision](plans/parallel-backtest/master-plan.md).

Install `requirements-numerical.txt` in the chosen supported Python environment,
then select **Prepare experimental engine**. This checks saved inputs, performs
ordinary research/daily preparation and publishes or verifies immutable numerical
inputs. It constructs the genuine compiled provider and checks all five nopython
kernel groups before closing the runtime. Only confirmed closure permits a
current readiness receipt. Status binds the pinned environment, whole-source
inventory, saved inputs, report and numerical pointer. Pending publication still
blocks readiness. Normal startup, status and preparation never install packages
or contact a package service.

Complete checkpoint recovery validates source, inputs, configured capacity and
compiler identity. It constructs no calculation provider, starts no trial worker
and compiles no factor kernel. Actual construction and factor-compilation counters
have fresh positive controls; zero books alone does not prove zero construction.

Capacity resolves before checkpoint lookup. Defaults use the measured preference
and current CPU entitlement and memory headroom. Known Windows job/process limits
and applicable container headroom participate. Unknown useful headroom selects a
single worker unless an internal qualification supplies an explicit allowance.
The conservative rounded 256 MiB readiness estimate comes from selected Windows
cold private samples near 152.3–152.7 MB. It is not an RSS limit or complete-run
budget. Managed workspace/cache totals and generation storage remain separate.
The first actual worker supplies the cold private-memory sample. Only after that
admission can remaining required workers initialize concurrently. Each worker has
its own readiness identity and deadline. A late failure closes every adopted
worker. Startup never changes the resolved checkpoint identity. There is no
historical four-worker, CPU-percentage or 2 GiB machine ceiling.

Runtime protocol publication preserves encoded limits and atomic replacement.
Recognized Windows sharing/access errors get at most eight attempts and 1.95
seconds of retry waits. Cancellation is checked during those waits. Previous
published content remains intact until replacement succeeds. Terminal failure
retains pending evidence. Payload and required statistics precede a result frame.
Cancellation and errors remain reportable if statistics publication fails. Logs
name a controlled file role, publication phase, exception type and OS codes.
They omit exception text and arbitrary paths. No financial calculation or
checkpoint commitment is retried by this file-publication policy. F's historical
external locking cause remains unproved.

## Environment and command

The pinned stack is NumPy 2.5.4, Numba 0.68.0 and llvmlite 0.50.0.
Tested interpreters are CPython 3.12.1 on Windows and CPython 3.14.4 on WSL.
The compatibility check accepts these CPython minor versions and exact package
versions. Other Python minor versions require qualification first.

Create a separate environment for the target operating system. Package setup
is an explicit operation. With previously obtained matching wheels, use:

```powershell
<private-python> -m pip install --no-index --find-links <owned-wheel-directory> -r requirements-numerical.txt
```

Then select **Prepare experimental engine** in Manage backtest data. Preserve the
exact environment interpreter path. Do not resolve a venv redirector or symlink
to another Python executable.

Startup never invokes pip, an installer or package networking. Missing wheels,
packages or compatible Python leave Original available. Reference commands and
normal `website/serve.py` do not need the numerical stack. Package setup and
market-data downloads are separate. Strategy execution never downloads market
data.

## Preparation and lifetime

`backtest/application/preparation.py` supplies one `Preparation` capability:

```python
owner = Preparation(private_source_root, python=exact_environment_python,
                    ensure_presentation=ensure_website_build)
report = owner.prepare(progress=report_stage, cancelled=is_cancelled)
status = owner.status()
owner.invalidate()  # Within coordinated download or repair ownership.
owner.close()       # Retry if closure remains unconfirmed.
```

Acquire shared source ownership before application imports. Keep it through
application shutdown and confirmed preparation closure. Redirect `backtest.inputs.fmp_download.KEY_PATH`
to a private nonexistent path before full application imports, as the entry does.

Preparation follows this order:

1. Check installed dependency metadata without importing native packages.
2. Recover verified research publication before prepared readers or input checks.
3. Validate saved inputs and prepare the research and compatible daily databases.
4. Recover and publish the numerical generation under financial ownership.
5. Release parent financial ownership. Start the genuine numerical child. It
   attaches inputs and prewarms code under its own financial ownership.
6. Close the child. Prove terminal process, descendant, pipe and handle closure.
7. Reacquire financial ownership. Confirm current inputs and rebuild stale HTML.
8. Publish a detached preparation report. Start ordinary application owners.

A separate preparation lock serializes this operation across candidate ports.
Source ownership comes first. Preparation serialization comes before financial
ownership. Child dispatch never occurs inside parent financial ownership.
Ordinary cache contention can defer or fail preparation safely.

The successful report describes a closed verification operation. It is not a
resident runtime or numerical calculation capability. Prewarmed compiler memory
ends with the child. No ordinary queue or data owner shares that child.
CB-11's budgets, strict arithmetic and closure proof still apply.

Each verification keeps its bounded runtime request, statistics and diagnostic
files in a unique private `tmp/candidate-runtime-*` directory. Successful and
failed attempts retain these files for diagnosis. Repeated starts can therefore
grow disk use. These per-operation bounds are not a disk quota. Remove retained
private evidence only after its owners have closed and required review is done.

## Freshness and recovery

`data/numerical-preparation.json` is rebuildable evidence. Its compact digest
binds current research metadata, the complete current price-file inventory,
full report content, local source contents and numerical pointer. Status reads
the inventory again. Direct edits, additions and removals remain detectable
under the existing path/size/mtime rule. A same-size raw edit with restored
modification time remains outside that rule. Publication journals block
readiness. Existing preparation and attachment retain full artifact and report
verification. A busy status means cache ownership is unavailable, not that a
freshness check passed.

An unchanged restart verifies and reuses the generation without export.
A changed restart prepares current inputs and publishes a generation when
needed. Successful, failed and cancelled coordinated download attempts mark
readiness stale inside financial ownership. Completed partial writes remain
saved. Retry preparation after repairs.

The panel shows candidate status. Candidate rebuild uses the startup operation.
Dependency, saved-input, publication and build failures keep the source data
panel and durable result readers available. New runs, legacy schedule requests
and queue submissions stay blocked until recovery. The queue does not claim
new work while candidate status is stale. Held edits, settings versions,
receipts and completed snapshots remain in their existing stores. Opening or
exporting a stored result does not calculate.

Unconfirmed child closure retains the strong runtime owner. No recovery
listener or completed data-job status is published while closure is uncertain.
Shutdown joins data, job, queue and HTTP owners, closes retained runtime
resources, then releases source ownership. Preparation never clears or replaces
the durable library or queue databases.
Data shutdown first closes admission under the same lock used to start jobs.
An accepted HTTP request that finishes reading its body later cannot clear
cancellation or start a new rebuild after the data owner has joined.

Normal publication still retains its recorded installed revision. Candidate
source cannot change that selection. Operational checks use private fixtures.
They do not act on the installed website.

## Application calculation admission

CB-13A adds `backtest_jobs.Calculations`. Each server gives one owner to its
background jobs, queue and legacy schedule/random routes. All enter through
`backtest_jobs.calculate`. Callers do not prehold financial ownership. The owner
acquires it, checks current readiness, opens the daily database and closes that
database before releasing ownership. Earlier status responses are advisory.

Interactive callers keep bounded waiting. Queue callers wait cancellably and
report contention. Only a typed admission-contention error is retried. Once
execution begins, its errors are never retried as admission. Unavailable inputs
defer queue work. Explicit Stop still wins. Random jobs and queue results keep
all trial holdings.

Shutdown publishes queue stop intent before closing calculation admission.
An admission waiter therefore requeues on shutdown. A durable explicit Stop
still stays cancelled. Application owners then join.
Accepted calls drain through their existing job/request cleanup. Late request
bodies cannot begin calculation. Stored result reads and queue edits do not
enter calculation admission.

CB-13B added persistent numerical execution. CB-14 now gives each accepted application call its own runtime. `candidate_calculations.Candidate` implements the shared calculation
boundary. It serializes numerical calls with parent data operations. The child
holds source then financial ownership during the call, including all random
trials. Confirmed closure precedes publication of every outcome. Between calls,
status reads the preparation report. No idle application child retains financial
ownership. A later call starts a new compiler process; disk checkpoints remain
reusable. Earlier timings retain their original runtime-lifetime boundary. Each calculation checks the same
preparation inventory again before numerical result or checkpoint reuse.
Busy status is advisory and does not claim fresh inputs.

Data Check, Rebuild and Download first confirm that any retained child is retired. They wait for
confirmed closure before parent financial access. Read-only Check keeps current
preparation valid. Mutation invalidates it, including partial writes. Rebuild
retains publication recovery and closed verification. The next run starts a new
child. Cross-process owners are never preempted. Interactive contention has a
bounded wait; queue admission waits cancellably. Callback failures and Stop
retire the child before a terminal outcome. Uncertain closure retains the owner
and blocks data operations until retry proves closure. Shutdown closes
admission, drains callers and retires the child before releasing source.

Standalone calculations still use the ordinary engine. Normal server
construction now uses the selectable owner described in the CB-15 section. CB-13C adds candidate-only week/month controls and versioned calendar
requests. Legacy month requests keep their original envelopes. Browser replay
submits the full recorded plan. Saved snapshots retain their settings and labels;
opening or exporting them does not calculate. See [calendar compatibility](schedule-calendar.md).
Submission preflight accepts an advisory busy inspection. Queue readiness still
requires current inputs. The child validates freshness before every execution
and reuse. An unavailable status without busy still rejects submission.
The normal launcher and installed revision stay unchanged.

## CB-14 qualification boundary

Daily prices now bind to the inventory accepted by committed research metadata.
An in-place price-file edit can leave the price directory timestamp unchanged.
After research preparation accepts that edit, daily preparation must rebuild
prices and derived dated books before numerical export. Normal daily connections
read the accepted metadata binding without traversing raw price files. The
binding preserves the existing filename/size/mtime rule. It is not a new content
hash of raw prices. Legacy caches without sufficient price evidence rebuild.
Durable library and queue snapshots remain separate from these derived caches.

[The current readiness record](plans/compiled-backtest/master-plan.md)
supersedes the earlier universal release gate. Original remains the default.
CB-15 now implements the normal-app selector in source. Publication remains
a separate authorized operation.

Current source reconciles the current research schema, the operating-yield-spread
filter and selection order. Both experimental selection orders use the shared SQL
selector. Rank-first retains original ranks and adds no replacements. The
experimental catalog supports all current thresholds, including
`operating_yield_spread_3y`. Annual specialization executes Original's spread
calculator. The prepared generation includes the saved 10-year Treasury series.
Each entry uses the latest yield on or before that date. Missing annual inputs
or a missing preceding yield omit this threshold. Other fields stay available.
Unknown future catalogs still fail numerical preparation.

Schema-7 prepared inputs and numerical generations must be rebuilt with current
source. Preparation retains full-precision independent baseline agreement.
Stored results remain readable without preparation or calculation. Numerical
dependencies remain optional for Original. Do not downgrade the compatible
saved-result reader when returning to Original.

Existing eager workspace, transport and storage limits remain. Large weekly and
100-trial cases keep their historical admission failures and stay unavailable
when these guards reject them. They are deferred capacity work, not newly
qualified workflows. This change adds no size allowance, benchmark or speed claim.

## Normal-app selectable engines (CB-15 source)

The normal app now offers Original and New engine — experimental for custom
dated fixed and random runs. Original stays selected initially. January and
latest screens keep their existing calculation paths. This source change has
not been deployed by the CB-15 task.

Normal startup and Rebuild prepared data + website prepare Original only.
They do not need the numerical packages. The data panel exposes a separate
**Prepare experimental engine** button. Install the pinned packages separately
in the exact interpreter used to start the app. Preparation never installs
packages or downloads data. It uses the same closed verification operation
and source, financial, freshness and publication rules described above.
Missing packages or stale preparation block experimental execution only.
Stored evidence and Original remain available. Data mutations invalidate
experimental readiness. Prepare again after a rebuild or repaired inputs.

Startup checks the optional dependencies without importing native libraries.
Missing packages, wrong package versions or unsupported Python produce a
terminal warning and a `candidate.dependencies_unavailable` WARNING entry in
the development log. These identify the required and installed versions and
the exact Python interpreter that needs setup. Preparation and status checks
use the same check. Repeated checks do not repeat an unchanged warning.
Changed failures and failures that return after a successful check are reported.
This check never installs packages, downloads data or blocks Original because
experimental dependencies are unavailable.

`backtest.application.calculations.Selectable` composes the existing Original and candidate
calculation owners. Submitted `options.engine` uses `original` or
`experimental`. Omission always means Original. This implicit default is fixed;
old queue specifications are not rewritten. New browser submissions include
an explicit engine. Jobs, queue receipts, held edits and browser reconnection
retain that setting. Execution removes it before financial planning. A random
plan therefore keeps its existing financial representation. Browser replay
remembers its engine separately from that plan. Changing a waiting test's
engine discards its old plan through the existing edit protocol.

Readiness and calendar preflight use the submitted engine. Both engines support
legacy 1/3/6/12/24-month presets and version-1 week/month calendars. Both engines support operating yield spread. Prepare
a current experimental generation after upgrading. No request drops a condition
or retries through Original.
Existing eager, process, memory, IPC, workspace and storage limits stay fixed.
An unavailable experimental queued test stays waiting. The consumer can run
ready Original tests after it, preserving order among ready tests.

New completed normal-app results contain `result.producer` with the engine ID
and label. Immutable views, saved results and complete CSV exports retain that
identity. A live selector change cannot relabel a completed result. Older
results without producer metadata say that the producer was not recorded.
Compatible version-1/2/3 readers stay independent of preparation. Returning to
Original uses the current compatible code. Do not downgrade to an old reader
that cannot open version-3 evidence.


## Aligned website execution boundary

Original execution now lives in `backtest/application/original_calculations.py`. Experimental
execution lives in `backtest/application/candidate_calculations.py`.
Their shared lifecycle and errors live in `backtest/application/calculation_contract.py`.
Neither adapter owns jobs or queue records. Standalone callers construct Original
and call its `calculate` method directly.
`calendar_requests.py` validates both engines' recorded plans without resampling.
Legacy monthly entry points and their serialized plans are unchanged.

The browser's `engine-controls.js` owns engine choice and capability status.
`calendar-settings.js` owns dates, interval labels and saved-calendar restoration.
Both adapters support fixed/random week/month schedules, both stock pools,
selection orders and the complete current metric/threshold catalog. Queue rows
show requested engine identity. Completed views and CSVs use stored producer
identity. Standalone built-in Latest and January views remain shared offline
prepared-data operations. Captured scalar strategies use the pinned engine for
bounded Latest, January, fixed and random execution. Original remains default.
Sample preview uses Original reference execution; eager scalar execution is
unsupported. No selector value creates provenance for prepared views or old
saved results. The Phase 7 record retains the closed independent audit, final
source-bound verification and measured private qualification limits.
