# Parallel experimental backtest program

Recorded: 1 November 2026. Source owner: `main` in the WSL checkout.
Status: CB-19A–CB-19E are complete in audited commits. CB-19F–CB-19G are pending.

The independent planner's report follows verbatim. Administrative tracking starts
after its Unknowns section.

### Design

**Goal:** Deliver parallel random-trial execution in the experimental application engine. Independent trials run in persistent processes over one immutable numerical generation. Preserve financial results, seeded plans, recovery, cancellation, saved evidence and Original as the default. Measure useful process/thread layouts and compare the complete Python/Numba period path with a complete Rust candidate before choosing the native core.

**Options:**

1. **Trial execution service.** The coordinator submits an immutable trial specification and receives a complete trial artifact. Each process owns its provider, factor cache and private SQL workspace. The coordinator alone owns checkpoints, application progress and final evidence.
2. **Shared book execution graph.** A central scheduler deduplicates all requested date-pair books, distributes books to processes and reassembles trials afterward. Its interface exposes book identities, dependencies and shared cache state. It can avoid repeated books, but introduces cross-trial planning, intermediate publication and another recovery model.

**Chosen:** Trial execution service. A trial is already the unit of checkpointing and financial aggregation. Its interface hides process scheduling and mutable calculation state. It permits CPU parallelism around the current source guards and assembly without creating another book store or job system.

The boundaries should be:

- **Generation attachment:** The session validates and owns an exact generation. It delegates read-only attachments to workers without transferring financial-cache ownership.
- **Trial evaluator:** `evaluate(trial_spec, period_sink) -> trial_summary` computes one recorded trial. It owns private SQL/provider state and publishes nothing.
- **Trial pool:** Starts bounded workers, sends recorded trial specifications and returns bounded provisional artifacts. Scheduling does not generate dates or interpret financial settings.
- **Trial coordinator:** Validates the plan and binding, recovers checkpoints, admits missing trials, commits completed results and presents trials in recorded order.
- **Period backend:** A complete-book implementation behind the existing portfolio boundary. Python/Numba and Rust must produce equivalent candidate books before shared SQL selection and the financial reducer. Timing includes that entire period operation.

Keep the existing application runtime as the lifetime owner. Workers live inside its process containment and close before its source/cache ownership ends. No new application queue, library, selector or user-facing tuning controls are needed.

A failed worker fails the operation explicitly. Prior committed trials remain recoverable. Cancellation stops admissions and drains or closes owned workers before reporting completion. Malformed identities, changed source/generation, contract differences and financial disagreements fail before publication. A slow earlier trial must not cause unbounded buffering of later trials.

### Plan

**CB-19A — Exact-generation worker attachment**

Deliver a worker attachment capability describing one verified, immutable generation. Its interface comment states who owns source, cache coordination, mappings and retirement protection.

`GenerationStore.open_current()` currently reacquires financial coordination and performs recovery. A worker must not call it while its coordinator holds that lock. Provide a delegated exact-generation attachment operation that performs no recovery, preparation or financial-lock acquisition. Preserve source-before-import and mapping closure order.

Finish with WSL and private native Windows tests for read-only mappings, rejected identity changes, attachment failure, parent death and complete file release. Record available private fixtures, interpreters and Rust toolchains now. Do not open the installed runtime as scratch.

**CB-19B — Complete trial evaluator**

Deliver one reusable trial evaluator composed from the existing `NumericalPortfolio`, provider and reducer. Both eager and streaming random operations use it. Its interface accepts recorded dates and validated selection settings; it never samples dates or writes checkpoints.

Define a bounded provisional trial artifact suitable for transfer and replay. Reuse the current evidence/checkpoint contracts rather than inventing a second financial schema. Support complete holdings without retaining an entire batch in memory.

Finish with complete Original/experimental agreement on financial fixtures, both selection orders, supported metrics and filters, week/month calendars, empty periods and early exits. No application routing changes yet.

**CB-19C — Persistent bounded trial pool**

Deliver a spawn-compatible process pool whose workers attach once and retain private provider/SQL state. Integrate it with the existing runtime containment.

The common operation submits a trial specification and receives its provisional artifact. Bound active trials, per-worker workspace, total retained results and provisional disk use. Include process count, numerical thread count and backend identity in explicit execution configuration and checkpoint compatibility. Avoid multiplying an existing per-process allowance without a total bound.

Finish with out-of-order completion, bounded transport, worker failure, cancellation, callback failure, shutdown, orphan prevention and source/generation retirement checks on WSL and native Windows. Reuse lessons from the historical persistent executor; do not import its benchmark-only pickle/export protocol into the application.

**CB-19D — Ordered checkpoint coordinator and application integration**

Deliver one coordinator used by both `numerical_random.run` and `run_into`. It loads recoverable trials before starting workers, commits fresh completed trials through the parent and exposes deterministic recorded order to consumers.

Checkpoint completed trials promptly even when an earlier trial is still running. Keep progress counts tied to committed or recovered trials. Bound the waiting reorder buffer through admission and provisional artifacts. A fully recovered request starts no calculation workers.

Wire this coordinator into the experimental `Session` and existing application adapter. Preserve manual jobs, queue retries, submitted engine identity, saved snapshots and Original behavior.

Finish with complete parallel/sequential parity, interrupted recovery, replay, full-hit recovery, manual/queued requests and eager/streaming evidence checks. This slice delivers a functioning parallel experimental application path.

**CB-19E — Complete Rust period candidate**

Deliver a Rust complete-book provider through the same portfolio/trial boundary. Reuse existing Rust temporal-search and factor work where valid. Extend coverage through candidate eligibility, source-derived guards, financial field validity and candidate assembly.

The current `RustExecutor` explicitly retains common Python guards and assembly. Merely replacing its arithmetic does not satisfy this slice. The timed operation must include complete book production, SQL staging/selection and the shared financial reducer. Shared SQL is retained deliberately; Rust does not require a new independent ranking implementation.

Keep source-derived financial policy authoritative. Bind generated/native code, compiler and ABI identity to execution evidence. Do not build a general plugin framework or a new policy language.

Finish with complete-period and complete-trial parity, malformed-input/boundary checks, cancellation between bounded work units and private Windows portability verification. This remains a comparison candidate until the decision slice.

**CB-19F — Scoped comparison and native-core decision**

Deliver reproducible evidence using private synthetic or already qualified copied inputs. Establish the exact asset scope and resource envelope before execution. Historical live-cache benchmark admission remains closed.

Compare:

- Current sequential experimental execution.
- One worker with four numerical threads.
- Two workers with two threads each.
- Four workers with one thread each.
- The complete Rust period path under comparable layouts.
- Original on the same recorded financial workload where qualified inputs support it.

Respect actual CPU availability. Separate cold startup, compilation/attachment, fresh calculation, transfer/publication and recovered-request costs. Record wall time, process/thread use, memory, provisional disk, parity and cleanup. Start with enough trials to exercise every worker and the smallest representative period window. Expand only to resolve a material uncertainty.

Choose Rust only if complete parity and operational verification pass and measured end-to-end benefit justifies the additional native boundary. Otherwise retain Python/Numba and document why. No invented minimum speed ratio, historical timing reuse or endless benchmark matrix.

**CB-19G — Selected engine qualification and closure**

Integrate the selected backend and measured resource layout into the experimental path. Keep backend selection internal; preserve Original as the application default. Remove temporary dispatch branches that the decision makes unnecessary. Retain comparison evidence without creating two permanently supported production implementations.

Finish with native Windows and WSL lifecycle/recovery checks, the affected application tests, complete financial parity and representative private application workflows. Update the architecture guide in the same commit and verify its controls and applicable diagrams.

Close the program only when the parallel application path works, scoped measured evidence is filed, the native-core decision is explicit, required verification passes and every completed slice has its audited commit. Deployment, downloads, stable-cache mutation, default replacement and custom-variable work remain outside this program.

For each slice, the orchestrator supplies the preceding abstraction’s interface, scope and finish criteria. A `6.1-sol-high` implementation agent performs detailed design, implementation and verification. A separate `6.1-sol-high` commit agent performs the required independent smart-commit audit and commits the coherent slice. The existing detailed-design protocol applies; documentation-only records need no artificial code-design stage.

### Unknowns

- **Worker attachment cost:** Generation verification may dominate startup. Probe delegated attachment on a private generation. Keep validation centralized while workers verify the exact delegated identity.
- **Per-worker mutable memory:** Providers retain caches, SQL rows and compiler state. Measure one and two workers early, then derive a bounded total allocation policy before four-worker admission.
- **Native Windows spawning and containment:** Existing containment must include grandchildren and native redirectors. Prove this with private lifecycle fixtures before application integration.
- **Result transfer cost:** Large holdings may erase calculation gains. Probe sealed trial artifacts and ordered replay using representative complete results; do not test arithmetic alone.
- **Rust coverage:** Existing Rust code lacks the suspected dominant guards/assembly work. Inspect source-policy translation and implement a representative complete period before broad native work.
- **Representative private assets:** Current copied assets may have historical qualification limits or incompatible source bindings. Inventory first; use synthetic evidence immediately and report any precise remaining asset restriction.
- **Actual scaling:** Shared mapped pages reduce input duplication, but private caches, compilation and memory bandwidth may limit gains. Compare the three layouts under the same recorded plan.
- **Checkpoint compatibility:** Current bindings include provider limits and thread/compiler identity. Specify the new execution binding once, preserve old records and test incompatible configurations cannot silently reuse them.

## Administrative tracking

### Authority, source and runtime

The user requests autonomous execution of all seven slices. The user authorizes
working and committing directly on `main` and says, “you have full permission”.
The [dated ownership exception](../../worktree-coordination.md#cb-19-parallel-engine-ownership-exception--1-november-2026)
assigns this program to the WSL source checkout. It supersedes the earlier
engine-worktree-only rule for this scope. Preserve other worktree history and
unrelated working files.

The user expressly reopens native comparison for this program. This supersedes
the earlier instruction not to reopen method comparison without new direction.
It does not reopen the historical matrix or `bench_admission` live-cache route.
Private synthetic experiments and task-specific comparisons on qualified copied
inputs are authorized. Before each experiment, record exact input/source bindings,
resource limits, cleanup owner and verification scope. Use the existing
application lifetime owner. Do not patch closed historical admission guards.
Qualify a copied asset's current binding before using it; its path alone is
insufficient. Start with synthetic fixtures while checking available copies.
This scope needs no routine permission round between slices or bounded probes.

`main` source is distinct from the installed native Windows runtime at
`<windows-runtime>` and from a running server. No deployment is part of
CB-19. Native checks use private fixtures and source exports. Preserve stable raw
inputs, prepared databases, reports, history, environments, saved library and
queue. Do not use the installed runtime as a scratch tree. Downloads, stable-cache
mutation, default replacement and custom-variable work stay outside scope.

Before each main commit, recheck whether an automatic publication supervisor is
active. A supervisor could install a new main commit. The 1 November entry probes
observed none through native Windows process inspection and the WSL host
namespace. That is a point-in-time observation, not a lifetime guarantee.

### Complete-period comparison clarification — 1 November 2026

Independent CB-19E planning found that the existing Numba provider with
`candidate_assembly="compiled"` already compiles snapshot, eligibility and pair
guards. The old Rust candidate replaces arithmetic while keeping Python guards
and assembly. CB-19E must qualify both equivalent compiled Numba and complete
Rust against the current source-guard Numba baseline through the same typed
candidate boundary and encoder. CB-19F must separate the source-to-compiled gain
from the Numba-versus-Rust gain. This avoids crediting Rust merely for moving
Python guards into compiled code. Shared source policy, SQL and reducer remain
authoritative. This is a narrow clarification of the existing period/backend
scope, not a broad method matrix or three permanent production engine choices.
The verbatim original design above remains unchanged. CB-19B implements no
CB-19E provider work.

### Per-slice execution protocol

User clarification — 1 November 2026: the user says that some original hardware
limits have no established basis and must not be followed blindly. The user
reaffirms full permission for this program. Audit the provenance of each limit
before treating it as a requirement. Historical four-worker/thread caps,
25-percent CPU quotas, memory ceilings and watchdog settings are evidence of
their original experiments, not mandatory CB-19 settings. Derive execution
budgets from the available machine and current measurements. The 1×4, 2×2 and
4×1 layouts are initial comparison points, not maximum capacity. Preserve
financial correctness, data ownership, bounded work and verified lifecycle
cleanup. Do not rewrite historical measurements or silently remove necessary
operational safeguards. CB-19A's reader gate has no capacity cap to change.

Apply the [existing automatic protocol](../compiled-backtest/master-plan.md#automatic-agent-implementation-protocol)
with the CB-19 ownership and native-comparison authority above. Each slice uses
this sequence:

1. The orchestrator supplies the preceding interface, narrow scope, finish
   criteria and unresolved evidence to a GPT-6.1-sol implementation agent at high
   reasoning effort.
2. For code changes, that agent invokes `strategic-design-plan`. Its independent
   read-only planner authors the detailed structure. Print and file the returned
   report verbatim. Record routine decisions separately. Do not replace this step
   with the implementer's own design. Documentation-only records and an unchanged
   measurement/decision tool need no artificial code-design stage.
3. Implement and verify the scoped capability. Repair routine failures, preserve
   failed attempts and record exact checks and limits. Update affected guide
   claims in the same implementation commit. Required unfinished checks prevent
   completion and dependent work.
4. A separate GPT-6.1-sol agent at high reasoning effort invokes `smart-commit`.
   Its required independent auditor reviews the full intended diff, design,
   evidence and guide impact. Resolve authorized findings and repeat affected
   checks. Commit only the coherent slice. The implementation agent does not
   commit or substitute a self-audit.
5. Record status and hand off the interface, evidence and actual commit to the
   next slice. Continue automatically when gates pass. Replan from new evidence
   without weakening financial, ownership or completion criteria.

Use `docs/plans/parallel-backtest/phases/CB-19A.md` through `CB-19G.md` for slice
records. Use matching `.design.md`, `.verify.md` and `.audit.md` records as needed.
Each record states its objective, file scope, preceding interface, decisions,
changes, exact commands/results, numerical agreement, retained failures, audit
dispositions, remaining limits and next input. A record need not contain its own
commit hash; report the actual commit after it is made. Preserve superseded
reports when a material design change needs a new independent planner.

### Ledger and completion criteria

| Slice | Status | Required outcome before completion |
|---|---|---|
| CB-19A | Complete (`84e2287`) | Delegated immutable generation attachment and WSL/native identity, lifetime and release checks pass; [phase](phases/CB-19A.md), [verification](phases/CB-19A.verify.md), [handoff](phases/CB-19A.implement.md), [design review](phases/CB-19A.review.md) and [audit](phases/CB-19A.audit.md) filed. |
| CB-19B | Complete (`4382a6e`) | One complete recorded-trial evaluator and actual-number sealed artifact implemented. Required WSL/native financial, artifact, recovery and source-binding checks pass. Independent audit has no findings. See [phase](phases/CB-19B.md), [verification](phases/CB-19B.verify.md), [handoff](phases/CB-19B.implement.md), [design review](phases/CB-19B.review.md) and [audit](phases/CB-19B.audit.md). |
| CB-19C | Complete (`8d73129`) | Persistent contained workers, stable capacity identity, total managed allowances and completion leases. All 16 pool tests pass on WSL and native Windows; required regression, source/lifetime/cancellation/retirement and pending-publication checks pass. Retained transient and interrupted attempts remain explicit. See [phase](phases/CB-19C.md), [verification](phases/CB-19C.verify.md), [handoff](phases/CB-19C.implement.md), [limit provenance](phases/CB-19C.limits.md) and [design review](phases/CB-19C.review.md) and [audit](phases/CB-19C.audit.md). |
| CB-19D | Complete (`3ea71cd`) | One parent coordinator serves eager and streaming experimental random execution. WSL/private native parity, recovery, lifecycle, manual/queue/evidence and repaired diagnostic compatibility checks pass. Full recovery creates no provider or workers. All private native exports are removed. Original stays default. Failed attempts remain explicit. See [phase](phases/CB-19D.md), [design](phases/CB-19D.design.md), [identity resolution](phases/CB-19D.identity-resolution.md), [design review](phases/CB-19D.review.md), [handoff](phases/CB-19D.implement.md), [verification](phases/CB-19D.verify.md) and [audit](phases/CB-19D.audit.md). |
| CB-19E | Complete (this audited commit) | Shared typed compiled Numba/Rust candidate boundary, source-derived native financial decisions and materialization, trusted internal factory and lazy recovery identity. Final WSL/native Rust suites pass 30 tests each; 96 complete artifacts agree at zero error. Native TLS cleanup, repeated DLL closure, actual Runtime closure, build integrity and repaired lifecycle gates pass. Private exports are removed. Original and experimental defaults stay unchanged. See [phase](phases/CB-19E.md), [design](phases/CB-19E.design.md), [review](phases/CB-19E.review.md), [handoff](phases/CB-19E.implement.md), [improvement](phases/CB-19E.improve.md), [verification](phases/CB-19E.verify.md) and [audit](phases/CB-19E.audit.md). |
| CB-19F | Pending | Scoped reproducible end-to-end layout evidence, actual resource/cleanup observations and an explicit justified native-core decision |
| CB-19G | Pending | Selected backend/layout integrated internally; WSL/native application qualification, complete parity, current guide and audited slice commits |

The program is complete only when all seven finish criteria above and in the
verbatim report pass. The parallel experimental application path must work.
Scoped measured evidence and an explicit backend decision must be filed. All
required verification must pass. Each completed slice must have its independent
audit and coherent commit. A plan commit, arithmetic microbenchmark, prototype,
historical timing or partial recovery run cannot close the program.

### Environment note — 1 November 2026

The entry probes found a working WSL numerical interpreter at
`tmp/cb02-all-methods/venv/bin/python`: Python 3.14.4, NumPy 2.5.4, Numba 0.68 and
llvmlite 0.50. A native Windows probe through `cmd.exe` verified Python 3.12.1 and
the same numerical package versions at
`<windows-runtime>\tmp\cb02-methods\venv\Scripts\python.exe`.
Native `rustc.exe` is present under the runtime's
`tmp\cb02-all-methods\rust\toolchain\bin`. These are available tool locations;
they do not qualify compilation, ABI compatibility, spawning or application
execution for CB-19. Preserve existing environments and record private execution
locations in CB-19A.

Existing private paths under `D:/cb14-offline-1db085cbdb36/` include `inputs1`,
`inputs2` and `cb17-comparison1/source`. Their presence is not proof of current
generation/source binding or complete comparison qualification. CB-19A records
usable fixture scope; CB-19F prospectively binds any accepted copies to its exact
workload and bounds. No complete asset inventory or installed financial files
were read for this plan record.

The plan record changes no current behavior. No architecture-guide update is
needed; leave its content and checked date unchanged. Later slices must apply the
guide rule to their actual changes, including the mandatory CB-19G update.
