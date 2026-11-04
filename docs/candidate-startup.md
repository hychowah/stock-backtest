# Experimental engine preparation

**Frozen.** The website does not offer or run the experimental engine. The
server refuses a request that names it, and no live module imports its source
(AGENTS.md, Engines). This document describes the frozen source and its last
qualified behavior. Unfreezing starts with its frozen tests in
`tmp/numerical-venv` (AGENTS.md, Tests).

## Selected backend

Experimental calculation uses compiled Numba. The measured preference is two
workers with two numerical threads each. Current CPU and memory observations can
reduce it. Backend and worker controls are not user settings. Read the
[final measured decision](plans/parallel-backtest/master-plan.md). Stored
results open without the numerical packages.

<a id="current-selected-preparation-cb-19g"></a>
<a id="current-optional-native-setup-cb-19g"></a>
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

Then call `Preparation` (next section) with the exact environment interpreter
path. Do not resolve a venv redirector or symlink to another Python executable.
`python3 scripts/numerical_generation.py prepare` publishes only the immutable
numerical inputs. It does not verify the runtime. Its `attach`, `retire` and
`recover` commands inspect, remove or restore generations.

`Preparation` never invokes pip, an installer or package networking. Missing
wheels, packages or compatible Python make preparation fail with a category.
Original and the reference commands do not need the numerical stack. Strategy
execution never downloads market data.

## Preparation and lifetime

`backtest/application/preparation.py` supplies one `Preparation` capability:

```python
owner = Preparation(private_source_root, python=exact_environment_python,
                    ensure_presentation=rebuild_html)
report = owner.prepare(progress=report_stage, cancelled=is_cancelled)
status = owner.status()
owner.invalidate()  # Within coordinated download or repair ownership.
owner.close()       # Retry if closure remains unconfirmed.
```

Acquire shared source ownership before importing this module. Keep it through
confirmed closure. The numerical child redirects `backtest.inputs.fmp_download.KEY_PATH`
to a private nonexistent path.

Preparation follows this order:

1. Check installed dependency metadata without importing native packages.
2. Recover verified research publication before prepared readers or input checks.
3. Validate saved inputs and prepare the research and daily databases.
4. Recover and publish the numerical generation under financial ownership.
5. Release parent financial ownership. Start the genuine numerical child. It
   attaches inputs and prewarms code under its own financial ownership.
6. Close the child. Prove terminal process, descendant, pipe and handle closure.
7. Reacquire financial ownership. Confirm current inputs. Run the
   `ensure_presentation` callback when the caller gave one.
8. Publish a detached preparation report to `data/numerical-preparation.json`.

`data/numerical-preparation.lock` serializes this operation across processes.
Source ownership comes first. Preparation serialization comes before financial
ownership. Child dispatch never occurs inside parent financial ownership.
Ordinary cache contention can defer or fail preparation safely.

The successful report describes a closed verification operation. It is not a
resident runtime or numerical calculation capability. Prewarmed compiler memory
ends with the child. No ordinary queue or data owner shares that child.
Each verification keeps its bounded runtime request, statistics and diagnostic
files in a unique private `tmp/candidate-runtime-*` directory. Successful and
failed attempts retain these files for diagnosis. Repeated runs can therefore
grow disk use. These per-operation bounds are not a disk quota. Remove retained
private evidence only after its owners have closed and required review is done.

## Capacity and checkpoints

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
checkpoint commitment is retried by this file-publication policy.

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

An unchanged preparation verifies and reuses the generation without export.
A changed one prepares current inputs and publishes a generation when needed.
`invalidate()` marks readiness stale. Call it only within coordinated mutation
ownership, including after partial download writes. Prepare again after repairs.

Unconfirmed child closure retains the strong runtime owner until `close()`
proves closure. Preparation never clears or replaces the durable library or
queue databases.

## Calculation owner

`backtest/application/candidate_calculations.py` holds `Candidate`, the
experimental implementation of the shared calculation contract in
`calculation_contract.py`. `backtest/application/calculations.py` holds
`Selectable`, which composes `Original` and `Candidate`. Submitted
`options.engine` is `original` or `experimental`. Omission means Original.
Execution removes the engine before financial planning, so a random plan keeps
its financial representation.

`Candidate` gives each accepted call its own runtime. It serializes numerical
calls with parent data operations. The child holds source ownership, then
financial ownership, during the call and all random trials. Confirmed closure
precedes publication of every outcome. No idle child retains financial
ownership. A later call starts a new compiler process. Disk checkpoints remain
reusable. Each calculation checks the preparation inventory again before it
reuses a numerical result or checkpoint. A busy status is advisory and does not
claim fresh inputs.

Stop and callback failures retire the child before a terminal outcome. Uncertain
closure retains the owner and blocks data operations until a retry proves
closure. Cross-process owners are never preempted. Interactive contention has a
bounded wait. Queue admission waits cancellably.

## Selection policy

Both selection orders use the shared SQL selector. Rank-first retains original
ranks and adds no replacements. The experimental catalog supports all current
thresholds, including `operating_yield_spread_3y`. Annual specialization
executes Original's spread calculator. The prepared generation includes the
saved 10-year Treasury series. Each entry uses the latest yield on or before
that date. Missing annual inputs or a missing preceding yield omit this
threshold. Other fields stay available. Unknown future catalogs fail numerical
preparation.

Both engines support fixed and random week and month schedules, both stock pools
and the complete current metric catalog. `calendar_requests.py` validates
recorded plans without resampling. See [calendar compatibility](schedule-calendar.md).
Existing eager workspace, transport and storage limits remain. Large weekly and
100-trial cases keep their admission failures. New completed results record
`result.producer`. Older results do not.
