# Master plan for a faster stock backtest engine

Created: 23 October 2026.

Implementation workflow and comparative research updated: 24 October 2026.

Wave5 measurement expansion: 25 October 2026.

Program direction revised after the full matrix: 25 October 2026.

Status: workspace preparation CB-00 and baseline measurement CB-01 are complete.
CB-01 recorded all 18 native Windows cases with exact replay agreement.
No production calculation engine has been replaced. CB-02 has completed the
broad method comparison. Numba is the working direction for the next bounded
experiment. Production integration remains gated. CB-03 remains conditional.

The second CB-02 pilot tested indexed report selection and unused threshold
omission. It matched all 24 trials exactly but took 58.13 seconds, versus
99.72/179.84-second controls. The descriptive conservative ratio is 1.72×.
The retained freshness check took 44.10 seconds. No 5× gate passed. See the
[second-wave record](phases/CB-02/wave2/README.md) for the control drift and
the next validation/report-factor decision. Later production phases stay gated.

The [six-method candidate/factor comparison](phases/CB-02/wave3/README.md) is
complete. Numba and Rust took 17.55 and 17.65 seconds. Persistent workers, bulk
Python, Polars and DuckDB took 21.58, 25.94, 29.06 and 101.81 seconds. All
financial and intermediate comparisons matched exactly. The best conservative
paired ratio was 3.34×; no 5× gate passed. Full freshness consumed about 60% of
the two fastest requests. All named alternatives have now been attempted.
The next bounded experiment must address shared validation/work costs before
expanding unchanged candidates. No production backend is selected.

The [fourth-wave pilot](phases/CB-02/wave4/README.md) retains immediate
request-time manual-edit detection through an equivalent fresh inventory scan.
It adds prepared attachment provenance and policy-derived request planning.
Numba took 12.33 seconds and Rust 13.41 seconds. Faster-adjacent-control ratios
were 10.49× and 9.58×, with exact agreement. Setup took about 146 seconds
separately. This one original-pool F0 seed-42 case is promising, not full
qualification. The [fifth wave](phases/CB-02/wave5/README.md) completed all 17
remaining cases with unchanged measured code. The full matrix has exact
financial agreement. Five of six median gates pass for each method. Broader-pool
F2 fails: Numba 4.66× and Rust 4.53×. No primary cases remain. No production
backend is selected. Shared request costs need another bounded experiment before
integration. Operational qualification and the freshness policy remain unchanged.

The [sixth-wave bounded pilot](phases/CB-02/wave6/README.md) tested only
requested-metric SQL staging in Numba on frozen `cached-F2-20261022`.
Complete staging took 54.17 seconds; projection took 52.04 seconds.
The observed 3.92% reduction and 4.87× conservative production ratio
fail its prospectively declared 10% / 5× criteria. All financial comparisons
remain exact. The intervention stops without expansion. The next bounded
question concerns source-derived candidate guards and assembly. No full matrix
or production integration follows this failed pilot.

The [seventh-wave bounded attempt](phases/CB-02/wave7/README.md) implemented
source-derived candidate decisions and a common encoder. It passed 93 WSL tests
and 92 native tests with one optional skip. The native pair stopped at its
2,700-second whole-experiment bound during the compiled variant's first
production control. The compiled candidate never started. Source guards took
120.20 seconds, with exact evidence, against 691.08/598.52-second controls.
Prepared production inputs match wave6. The timing drift has no established
cause. There is no paired speed conclusion and no expansion. Revise measurement
orchestration or resource planning from those costs before a new bounded pilot.
The guard/assembly hypothesis and all qualification gates remain unresolved.

The decisions below supersede earlier instructions to expand both candidates
or continue the broad method search. Historical phase records retain their
original conclusions and measurements.

## Objective

Make random-date stock-screen research at least **5× faster**, with **10× or more as the target**, compared with the current production engine on the same machine, inputs, sampled dates and strategy settings.

The main workload is at least 24 random-date trials over **1997–2025**, usually with **12-month** rebalancing. The user changes filter settings between experiments. The intended interval range is **one week through two years**. Fresh random dates must benefit. Reusing a fixed seed must not be necessary for a speed claim.

Preserve holdings, ranks, valuations, returns, coverage, exit treatment and random-date experiment meaning. Keep the website, data panel, local launcher and offline research workflow usable. A complete engine replacement is permitted when evidence supports it.

This is a program-level plan. Each phase is scoped for one Codex 6.1-sol session. Each code phase must use `$strategic-design-plan` for its detailed code structure, then implement and verify the change, then use `$smart-commit`. The phase agent carries this sequence through automatically. It asks the user only for a critical blocker or a decision that cannot be resolved within the authorized scope. This document does not prescribe every module or function.

The [research findings and primary sources](research.md) explain the options and their limits. They are part of this plan.

### Adjust the plan when new evidence changes the direction

This is a living plan. Implementation experience, benchmark results and user
workflow findings can justify changes to priorities, phase scope, sequence,
dependencies and the chosen method. Update this master plan when those findings
change the remaining work. Do not keep an obsolete phase sequence merely because
it was written first. The 25 October revision is an example of this process.

Record the evidence, the decision, affected phases and checks, and the next
unresolved question. Preserve earlier measurement records. Distinguish a proposed
change from implemented or qualified behavior. Recheck dependent phase briefs,
the status ledger, research guidance and affected user documentation together.

Make routine adjustments within the authorized objective autonomously. Ask for
a user decision before changing the investment rules, correctness tolerance,
performance acceptance criteria, promised interval scope or freshness guarantee.
A failed gate is evidence for changing the work, not evidence that the gate passed.

## Decisions and open gates

| Subject | Program direction | Evidence still required |
|---|---|---|
| Calculation model | Retain the Numba source-derived guard/assembly prototype. Obtain a complete bounded paired measurement; the broad comparison is complete. | A changed implementation passing the full primary gate, followed by operational qualification. |
| Data model | Immutable numeric inputs, sparse price histories, bounded entry-date factor batches. | Sparse versus dense access, measured memory and Windows mapping lifecycle. |
| Method choice | Numba is the experimental working direction. Retain Rust and the other methods as comparison evidence. | Reopen an alternative only for a concrete measured limitation or operational blocker. |
| Policy ownership | All six candidate executors use source-derived financial expressions. Guard policy remains source-owned, including the optional compiled Numba decisions. SQL selection and portfolio assembly remain common. | Exact intermediate, holding and replay agreement. |
| Database role | Keep verified research data and compact job/result storage. Remove per-candidate SQL traffic from calculation. | Publication and recovery measurements. |
| Analytical alternatives | DuckDB and Polars have been attempted. No further library search is scheduled by default. | A specific unresolved question and a bounded comparison at the same request boundary. |
| Deployment | Persistent local runtime with bounded native parallelism. | Shutdown, generation replacement and memory tests on native Windows. |
| Weekly intervals | Add an explicit calendar extension. Proposed week means seven calendar days, with session rolling. | Freeze exact rules in CB-08 before exposing controls. |
| Freshness | Retain immediate request-time detection under the existing path/size/mtime rule. | Equivalent scan evidence and stale-generation checks; no startup-only substitution. |
| User experience | Set absolute time budgets for startup, fresh research, changed filters and saved-result reopening. | Prospective budgets and native measurements; annual relative speed alone is insufficient. |

The [24 October comparative research](method-research-2026-10-24.md) led to
attempts of all six named methods in the [third wave](phases/CB-02/wave3/README.md).
The full Numba/Rust matrix now supports focusing the next experiment on Numba.
Numba has the lower median request duration in all six cases. The differences
are small; neither method passes the entire speed gate. This is a choice of
development focus, not production approval or a claim of general superiority.

Do not develop both methods on every iteration by default. Reopen Rust for a
demonstrated Numba installation, startup, invalidation or execution limitation.
Give any alternative comparison one question, a budget and a stop condition.
Timed Windows jobs remain serial. Keep one shared financial policy and one
measurement contract. Experimental dependencies remain isolated. Retain one
production engine after qualification.

## Scope and boundaries

### Required outcomes

- Faster fixed-date and random-date calculations through one financial path.
- Both the original `legacy` pool and the broader `cached` pool.
- All current ranking metrics, threshold filters, rank ranges and metadata filters.
- Fresh dates, repeated filters, saved-result replay and completed-trial recovery.
- Explicit weekly and intermediate week/month intervals through two years.
- Correct selected-stock inspection, CSV downloads, progress and error behavior.
- Automatic preparation and dependency handling through the existing launcher.
- Native Windows qualification. Linux/WSL correctness remains required, but its timings are not the Windows baseline.

### Scope held outside this program

Do not change the investment strategy, annual availability assumption, universe coverage, bankruptcy classification or canonical report cutoff to obtain speed. Do not refetch available market data. Do not add brokerage execution, intraday simulation, transaction costs, cloud services or distributed computing.

January and latest website modes can keep their prepared database and standalone browser path. Replacing those paths is not a prerequisite for accelerating dated schedules. Their calculations and exports must continue to agree with the common policy and catalog.

Keep `scripts/revalue.py:calculate` independent. Do not make the reference call the replacement numerical engine. Keep canonical report/database publication under `scripts/baseline.py`.

## Candidate behavior and data flow

The following architecture is provisional. CB-02 may revise the input format,
calculation boundary and later phase interfaces before production design.


Preparation validates saved inputs and produces one immutable numerical generation. The local runtime attaches that generation. A job calculates the required entry-date inputs, applies filters and ranks stocks. It then calculates returns for the selected holdings and publishes completed trial evidence.

```mermaid
flowchart TD
    A[Saved raw cache] --> B[Existing validation and baseline agreement]
    B --> C[Immutable numerical generation]
    C --> D[Persistent local runtime]
    D --> E[Entry-date factors in bounded batches]
    E --> F[Eligibility filters and deterministic ranking]
    F --> G[Selected-holding returns]
    G --> H[Atomic completed-trial results]
    H --> I[Website results inspection and exports]
    E --> J[Byte-limited reusable factor cache]
    J --> E
```

### Units of reuse

| Data or result | Identity | Lifetime |
|---|---|---|
| Base numerical inputs | Verified source and report generation, format version and policy dependencies | Until a new generation is published |
| Report-level inputs | Symbol, selected report, applicable history and policy version | Within that input generation |
| Entry-date factors | Generation, entry date, pool and available factor fields | Bounded memory cache; optional disk persistence only if measured |
| Selected portfolio result | Generation, exact entry/exit dates and complete selection configuration | Reusable completed result |
| Random experiment | Generation, policy version, exact sampled dates, settings and trial count | Durable completed-trial checkpoints |

Entry-date factors must not depend on a future exit. However, the current code has period-specific eligibility checks, including the actual entry date being before the exit. Apply these checks before ranking. Deferring return arithmetic must not defer eligibility until after selection.

Avoid a complete daily factor cube at startup and avoid a table of every possible entry/exit return. See the memory estimates in the research findings.

## Financial correctness contract

Treat the current source as the executable reference. Root `AGENTS.md` remains binding. Resolve discrepancies between old prose and code explicitly; do not quietly change results.

| Area | Required behavior |
|---|---|
| Reports | Fiscal year-end plus 90 days; strict `known < entry`; drop reports older than 800 days. Preserve eligible USD fields and conflict handling. |
| Original pool | Apply reported-size eligibility before selecting its annual report. Preserve the original single-year 250-candidate pre-price buffer and its stable tie order. |
| Broader pool | Use cached-price coverage. Do not label it the full historical universe or imply a complete manual early-stop review. |
| Valuation | Keep the existing selected valuation series and its fiscal/entry price tolerances. Preserve formula operation order and current rounding behavior. |
| Entry | Preserve forward valuation-price and adjusted-price searches, missing-price exclusion and actual entry-date checks. |
| Exit | Preserve the normal 10-day backward search, long last-price fallback, dates, status labels and `(entry year, symbol)` bankruptcy override. |
| Thresholds | Strict `lt` and `gt`; all conditions pass; display units; missing values fail only conditions needing them. Preserve signed cash flow and margins. |
| Financial ratios | Selected report only; current denominator rules; four positive EPS years for PEG; mean positive current/prior equity for ROE. |
| Ranking | Metric yield descending, candidate rank ascending with the current SQL null behavior, then symbol ascending. Preserve arbitrary supported rank ranges. |
| Returns | Equal weights use actual selected count. Keep stopped proceeds in cash until the next rebalance. Preserve calculation and aggregation order. |
| Experiments | Same random samples for an explicit seed; common-window cash before the first trade for both strategy and SPY; paired incomplete-trial exclusion. |
| Coverage | Keep short and empty periods visible. No full-period strategy CAGR when a selected period is empty. |

Use float64. Do not weaken `baseline.REL_TOL` or `ABS_TOL`, currently both `1e-12`. Symbols, ranks, dates, statuses, membership and missingness must match exactly. Compare unrounded numeric fields at the existing full-precision tolerance and report maximum differences. Preserve bitwise identity where current formulas already provide it.

Keep financial calculations under one owned policy/catalog path. Consumers must remain generic. A compiled backend is not permission to hand-code a different P/E, PEG or EBITDA formula in each runtime. A bounded extraction of numeric policy functions is permitted when the same functions remain callable by the scalar and compiled paths. The independent January reference must remain independent.

## Interval contract

Current fixed and random schedule controls support 1, 3, 6, 12 and 24 months. Weekly and other intermediate intervals are new behavior in this program.

The proposed extension uses explicit **week** or **month** units. One week is seven calendar days. Targets stay anchored to the original starting date. Monthly targets clamp month ends. Targets roll forward to saved SPY sessions; the final mark rolls backward. A month is not a fixed number of days. A week is not silently interpreted as five sessions.

CB-08 must freeze the accepted count ranges and compatibility mapping. The intended range includes one to 104 weeks and one to 24 months. Keep existing `months` requests and explicit-date inspection working. Introduce a versioned interval representation for new requests and saved configurations.

Random trials continue to sample one available SPY session independently from each nominal interval block. Preserve one final partial block and common-window cash. Deduplicate rolled fixed targets. Test holiday-heavy weeks, leap dates, month ends, very short adjacent random holding periods and empty session blocks. Do not present new weekly sampling as behavior already supported by the old planner.

## Performance acceptance

### Primary comparison

Use native Windows on the user's machine. Use 24 trials, 1997-01-01 through 2025-12-31, and a 12-month interval. If the saved SPY cache does not cover these endpoints, stop and report that condition rather than silently changing the window.

CB-01 freezes a manifest with explicit sampled date lists, not only seeds. Suggested reproducible seeds are 42, 20261022 and 20261023. Record all request defaults explicitly. Use both pools and three filter profiles:

| Profile | Purpose | Initial fixture settings |
|---|---|---|
| F0 | Ordinary selection | Current EV/EBITDA, ranks 1–50, current default cap/EV limits, no added thresholds |
| F1 | Annual financial filters | F0 plus P/B `< 3` and ROE `> 10` in display units |
| F2 | Trailing-price filters | F0 plus one-year and three-year trailing returns `> 0` |

These thresholds are engineering fixtures, not investment recommendations. Add a mixed-filter, three-year-ranking and top-100 case to qualification. Add a deliberately empty selection to correctness checks. Preserve concrete user strategy settings in supplementary manifests without changing the frozen primary manifest.

Every frozen F2 trial has an empty period and a null full-period CAGR. Keep F2
unchanged as a primary performance and incomplete-coverage test. Add a separate
trailing-filter workload that produces complete trials and usable paired CAGRs
on the declared saved inputs. Establish its coverage before timing, then freeze
its settings and dates. Never replace the failed primary F2 case with this
supplement. Include mixed filters and repeated filter changes in workflow
qualification. Report complete and incomplete trials separately.

Require **at least 5× median end-to-end speedup in each of the six primary pool/profile cases**, with no numerical or membership disagreement. Target 10× or more. Report per-seed ratios and absolute times; do not hide a slow case in an overall average. If a case fails, keep the new engine opt-in and revise the design.

### Measurement rules

1. Freeze source identities, input generation, report hash, versions, CPU/thread counts and settings.
2. Run against isolated derived data under ignored `tmp/`. Never clear the user's real books to make a test fresh.
3. Give both engines identical base data and date samples. Each timed primary run starts without completed date-pair results or reusable entry-factor results. A loaded immutable base dataset is allowed for both.
4. Include validation performed during the request, selection, return calculations, staging, completed-trial saving, response encoding and local transport. Use the same HTTP harness or equivalent isolated adapter for both engines.
5. Separate first installation, source preparation, compiler-cold startup, restart with a compiled cache, and an already-running request. They are different measurements.
6. Alternate engine order across the three seed runs per case. Use the same power settings and avoid simultaneous benchmark jobs. Do not claim the OS cache was cold unless it was actually controlled.
7. Report fresh-date runs, same-date filter changes and exact-result replay separately. No replay-only speed claim satisfies the objective.
8. Record wall time, stage times, private memory, working set, peak thread/process counts, artifact size and written bytes. Explain any timing exclusions.

The six primary cases require 18 paired runs across the three seeds. Capture one baseline run per case first to check cost. Run the full matrix in resumable batches if needed. Do not silently reduce the protocol when a session ends.

### User workflow budgets

The relative annual speed gate is necessary. It does not establish acceptable
startup time or an interactive research workflow. Before qualification timing,
record an absolute time budget and a measurement boundary for each workflow:

| Workflow | Required measurement | Budget status |
|---|---|---|
| First installation and first ready result | Dependency installation, preparation, attachment and compilation, with each cost separate | To be resolved before operational qualification |
| Normal restart | Launcher start to ready service, then the first completed result | To be resolved before operational qualification |
| Fresh-date research | Request to completed 24-trial result with no saved-book or factor-result reuse | To be resolved before workflow qualification; retain the six-case 5× gate |
| Changed filters | Same dates with new settings; report permitted factor reuse and completion time | To be resolved before workflow qualification |
| Saved-result reopening | Request to visible inspection and export-ready evidence | To be resolved before workflow qualification |
| Weekly research | Short-window pilot, then the declared full-window workload, with resource caps | To be resolved before weekly capacity qualification |

Choose budgets from the intended user workflow. Do not select thresholds merely
to match an observed timing. Proposed acceptance budgets require a user decision;
missing budgets remain unresolved and block the relevant release qualification.
Wave5 attachment/setup took 52.73–152.03 seconds for its new cases. Those are
historical setup observations, not acceptable-latency targets or full launcher
measurements. No first-use or compiled-cache restart speed claim exists yet.

### Capacity and operational checks

Qualify 100 annual trials, the existing month intervals, intermediate intervals, top-100/rank slices and the weekly extension. Use bounded old-engine explicit-date comparisons for new weekly numeric returns. Use independent calendar fixtures for weekly sampling. The old random planner cannot serve as the weekly sampling reference.

A 24-trial full-window weekly workload has roughly 36,000 holding periods. It must use bounded buffers and cancellation checkpoints. A 100-trial weekly workload is a capacity test; it is not necessary to generate an enormous old candidate database to claim annual speedup. Start with a short-window pilot and record an explicit runtime/disk cap before running it.

Target at most **4 GiB peak process working set** for the default 24-trial broader-pool job on the inspected dataset. Track private bytes and mapped residency separately. Bound the factor cache by bytes. Repeated filter runs must not cause unbounded growth. If the target is infeasible, document a measured memory budget before enabling the engine by default.

## Preparation and runtime safety

### Generation publication

Build numerical generations under an ignored local data directory. A generation has an explicit schema, source identity, policy/catalog signature, buffer hashes, dtype/shape information and stable ordering metadata. Export from already validated prepared inputs. Do not create a second raw-data validation policy.

Publish a new directory only after validation completes. Switch a small current-generation pointer atomically under `cache_access`. Keep the previous valid generation through failed or interrupted preparation. Never overwrite mapped buffers in place. Test interrupted writes and Windows access/sharing failures.

Bind to immutable base inputs, not the whole mutable daily database. Capture fingerprints after research preparation because preparation can update the canonical report. Unfinished baseline publication must continue to block readers.

### Freshness

Validate raw inputs fully during preparation and startup. A normal job checks
the compact prepared-generation identity and the current raw inventory under
the existing project coordinator. Downloads and repair operations must mark
prepared inputs stale before releasing ownership, including cancellation after
partial successful publication.

Retain immediate request-time detection of direct edits under the existing
path/size/mtime rule. Wave4 demonstrated a faster equivalent inventory scan;
Wave5 retained it throughout the full matrix. Use the prepared identity together
with equivalent current inventory evidence. Do not replace it with startup-only
validation. A same-size edit with a restored timestamp remains outside the
existing metadata guarantee. Any future proposal to change that guarantee needs
separate evidence and a user decision. Removing scans is not a planned shortcut.

### Resource ownership

Retain lock order: process-local reentrant lock, project file lock, then database handles, mappings and worker resources. Retain ownership through native work and final closure. Keep current cross-server serialization while changing the engine; independent concurrent jobs are not a prerequisite.

Use one native parallelism layer with a measured cap. Do not create a new process pool for every trial or a full data copy per worker. Use bounded chunks so progress and cancellation can occur between native calls. Closing the terminal must stop native work before releasing lifetime ownership.

Treat the numerical generation signature and compiled-code signature separately. The compiled signature covers imported policy code, catalog, relevant constants, bankruptcy inputs, runtime/compiler versions and target platform. Numba's own cache invalidation is insufficient by itself; see the research findings.

### Recovery and compatibility

Commit completed trial evidence atomically. Configuration identity includes exact dates, generation, policy version, pool, metric, filters, limits, interval and rank range. Preserve distinct trial identities when schedules happen to repeat. Never reuse a result from another generation.

Keep the old cache and reference calculation path available during rollout. Do not delete existing books to create the new store. Inspection of old saved experiments must either route to the compatible old path or require an explicit recomputation. Do not silently show current data as the old experiment's evidence.

## Phase map

CB-00 is the preparatory WSL/native-Windows workspace migration. Its design and
handoff are filed in `phases/CB-00.design.md` and `phases/CB-00.md`. It does not
implement the compiled calculation engine. Read that handoff before CB-01.

CB-01 measurement is complete. Its [phase record](phases/CB-01/README.md) contains
the frozen workload, all 18 accepted cases and operational limits. CB-02 is in
progress: the comparison is complete, but its full speed gate failed. CB-03 is
conditional. CB-04 through CB-15 describe remaining capabilities. Reconcile
these briefs with demonstrated work before implementing them. Phase identifiers
are stable references, not a fixed session count or a demand to rebuild prototypes.
Split or merge remaining work when the evidence warrants it and record the change.

### Delivery milestones and evidence gates

| Milestone | Result and exit evidence | Related phases |
|---|---|---|
| Close the request-performance gap | Revise measurement orchestration after the wave7 budget stop; obtain a promising guard/assembly pair, then the unchanged full primary gate on one source identity | CB-02; CB-03 only for a concrete blocker |
| Prove operational feasibility | Isolated installation, startup/restart, invalidation, cancellation and recovery proofs; agreed workflow budgets | Early bounded proofs, then CB-04/CB-11/CB-12 hardening |
| Deliver faster existing workflows | Opt-in support for the existing month intervals, filters, trial inspection, exports and rollback | CB-04–CB-07 and CB-09–CB-13 |
| Add weekly research | Frozen calendar, correct explicit-date returns, useful latency and bounded resources | CB-08 and weekly extensions in CB-09–CB-14 |
| Qualify and enable the default | Full primary, supplementary, workflow, weekly and operational gates pass | CB-14 and CB-15 |

The first three milestones can expose risks before weekly capacity work. Existing
month workflows can be delivered opt-in before weekly controls. Weekly support
remains required for program completion. Annual speedup does not qualify weekly
latency. Default cutover waits for all promised capabilities and gates.

Development-focus selection permits bounded isolated feasibility proofs before
the primary speed gate passes. It does not authorize production integration.
Production integration requires the full primary speed gate and no known
operational blocker. Final release qualification also requires the agreed
workflow budgets, full correctness coverage and operational checks.

Before each implementation phase, classify relevant evidence as **demonstrated
and reusable**, **demonstrated but needs production hardening**, or **unknown and
needs an experiment**. Link the proof and its limits. Prepared attachment,
source-derived numerical factors, exact selection and completed-trial replay
already have benchmark evidence. Production publication, launcher lifecycle,
full filter-change performance and weekly capacity still need qualification.
Reuse sound work; implement only the missing capability or hardening.

| Phase | Scoped result | Depends on |
|---|---|---|
| CB-00 | WSL source and native Windows deployment workflow | User's split-workspace request |
| CB-01 | Reproducible current-engine baseline and frozen workloads | CB-00 and this plan |
| CB-02 | Numba shared-request experiment and full primary speed-gate decision | CB-01; completed comparison evidence |
| CB-03 | Conditional Rust or bulk alternative comparison | A documented CB-02 limitation |
| CB-04 | Production hardening of immutable numerical preparation/publication | Full primary speed gate passed; early isolated feasibility proofs allowed |
| CB-05 | Correct compiled date, report and price primitives | CB-04 |
| CB-06 | Complete metric and threshold calculations | CB-05 |
| CB-07 | Deterministic generic filtering and ranking | CB-06 |
| CB-08 | Weekly and intermediate interval contract and planner | CB-01; can precede CB-04; optional for existing-month opt-in delivery |
| CB-09 | Fixed/explicit-date portfolio evaluation with full parity | CB-07; CB-08 for new interval planning |
| CB-10 | Random trials and atomic recovery evidence | CB-09 |
| CB-11 | Persistent runtime, bounded parallelism and lifecycle | CB-10 |
| CB-12 | Launcher, preparation and data-panel integration | CB-11 |
| CB-13 | Existing-month opt-in UI/API, inspection and exports; weekly controls when qualified | CB-12; CB-08 and weekly evaluator checks for new controls |
| CB-14 | Full numerical, operational and speed qualification | CB-13 |
| CB-15 | Default cutover, documentation and retained fallback | CB-14 passed |

### CB-01 Capture the baseline

**Recorded:** Complete on 24 October 2026. See the [phase report](phases/CB-01/README.md),
[frozen workloads](phases/CB-01/workloads.json) and [compact evidence](phases/CB-01/baseline.json).
All primary runs are complete. Every F2 trial retains one empty period and a null
full-period CAGR. Timings vary materially. Later speed claims require the paired
comparison protocol in this plan; archived timing ratios alone do not qualify an engine.

**Outcome:** A later session can reproduce the current behavior and timing without using this conversation as evidence.

**Work:** Freeze sampled dates and primary settings. Capture source hashes, data generation and report hash. Extend the benchmark harness to use isolated derived caches and compare full holding evidence. Measure current request stages, source scanning, worker initialization, calculation, selection, publication and response delivery. Start with one pilot before the full matrix.

**Deliverables:** A tracked workload manifest, a compact baseline report, a benchmark command and a correctness-case inventory. Store bulky outputs and disposable databases in ignored `tmp/`. Record any skipped runs as pending.

**Verification:** Repeated explicit samples return the same selections and values. Production raw files, report/database pair and real completed books stay unchanged. Native Windows execution is recorded. The comparison has no hidden saved-book reuse.

**Handoff:** Exact commands, fixture identities, baseline timing matrix and the identified serial costs. Do not implement the replacement engine in this phase.

### CB-02 Compare optimization methods

**Outcome:** Evidence for choosing, revising or rejecting an optimization method
before production integration. No backend is selected from library reputation.

**Completed comparison:** Independent method experiments covered sparse
Python arrays, NumPy/Numba batched searches and DuckDB ASOF lookup. The initial
experiments share scalar financial policy, in-memory SQL selection and durable
selected-trial publication. Their results compare price resolution and common
publication changes; they do not compare fully rewritten financial engines.
Keep the original pools and all production code unchanged. Use the CB-01
24-trial dates, both pools and F0/F1/F2. Run a first-seed pilot, then expand
promising methods to all three seeds. Preserve mixed-filter, three-year,
top-100 and weekly-explicit-date checks as additional qualification work.

**Deliverables:** Updated research, one shared experimental contract, disjoint
method modules, complete holding comparisons, native timings, stage and memory
evidence, dependency versions and a decision table. Record pending or failed
methods explicitly. Files stay separate from production paths.

**Verification:** Compare every selected holding, aggregate and supported
intermediate input. Include current full freshness scans, result saving and
local response delivery in headline times. Keep loading and cold compilation
separate. Use contemporary fresh controls and show timing drift. Disable
compiler-cache reuse for the initial Numba lookup experiment; production
invalidation proof remains required before integration. Test interruption and
committed-trial recovery. A pilot remains unqualified.

**Recorded experiment sequence:** The following pilot scopes and decisions are
historical. The next-experiment brief below defines the remaining work.

**Initial pilot result:** The original-pool F0 seed-42 lookup/publication
comparison measured arrays at 52.62 s and Numba lookup at 53.10 s. Contemporary
controls took 78.98 s and 115.31 s. DuckDB per-book ASOF exceeded its declared
180 s request budget with five complete trials. No method qualified. See the
[full pilot record](phases/CB-02/README.md). Do not expand unchanged lookup
adapters until the shared scalar report/factor bottleneck is addressed.
The [report-index follow-up](phases/CB-02/wave2/README.md) completed the same
case in 58.13 s with exact financial agreement. Controls took 99.72/179.84 s.
The faster-control ratio was 1.72×, with 80% control drift. The full freshness
check took 44.10 s. All 1,832 distinct frozen sample dates passed complete
ordered report/rank comparisons; that is not full financial qualification.
Do not expand the unchanged method across the matrix. The next bounded decision
must address validation cost and remaining report/factor work. Any changed
freshness policy needs an explicit accepted contract and verification before
headline comparisons omit the current scan. Whole-batch analytical execution
and persistent bounded execution remain alternatives. These pilots do not
reject complete compiled or SQL financial engines.

**Third-wave scope:** The [third wave](phases/CB-02/wave3/README.md) tested all six
candidate/factor approaches. Each executor owns temporal report selection,
sparse price searches and source-derived numerical arithmetic. Final SQL
selection and financial aggregation remain shared. It starts with Numba, then
bulk Python, DuckDB, persistent workers, Polars and Rust. Current full freshness
stays in primary timing. Each method also gets real intermediate proof and
both-pool financial, trailing and mixed-filter checks. Failure of one method
does not stop the comparison. These tests bring the previously reserved Rust
and Polars alternatives into CB-02; CB-03 needs a further concrete question.

**Six-method result:** All methods completed the original-pool F0 seed-42
primary case and all six real filter requests. Complete candidates, holdings,
summaries and replay matched exactly. Numba and Rust were effectively tied near
17.6 seconds. The other requests took 21.58–101.81 seconds. No 5× gate passed.
The full freshness check took 10.16–10.95 seconds. Attachment cost 40.87–50.56
seconds separately. Do not infer first-use or full-matrix speed from warm pilots.
See the [collected evidence](phases/CB-02/wave3/results.json). Deferred work is
explicit: the other 17 primary cases, capacity and production qualification.
No remaining named method is silently reserved or untested. CB-03 now requires
a further concrete unresolved question.

**Fourth-wave result and split:** The benchmark-only prepared attachment checks
its captured numerical generation, policy-source provenance, current research
metadata and full report binding. It rejects unfinished publication and stale
reuse. Every request still enumerates the same current annual inventory and
compares the current path/size/mtime evidence. Attachments prove exact equality
with the authoritative scanner. This is an equivalent scan implementation,
not the then-proposed CB-12 startup-only manual-edit policy. That proposal is
retired by this revision.

Numba/Rust completed all 88 primary and correctness trials exactly. The frozen
`legacy-F0-42` requests took 12.33/13.41 seconds, with conservative ratios
10.49×/9.58×. Controls were 149.29/129.40/128.46 seconds. Initial attachment
and compilation took 146.10/145.48 seconds separately. Native and WSL generation
invalidation and recovery checks pass. See [wave4 evidence](phases/CB-02/wave4/results.json).

Wave4 is a bounded pilot. [Wave5](phases/CB-02/wave5/README.md) completed all
17 remaining primary cases. It ran both methods serially with fresh adjacent
production controls: Numba/Rust for seed 42, Rust/Numba for 20261022 and
Numba/Rust for 20261023. Its [ledger](phases/CB-02/wave5/results.json) preserves
all per-seed times and ratios, complete per-case medians and an empty remaining
primary-case list. All intermediate, holding, summary and replay comparisons
are exact. Full request validation, saving and delivery remain timed.

The 5× gate fails for both methods in broader-pool F2: medians 4.66×/4.53×.
All other median gates pass, with limited margin in broader-pool F1. Keep
production unchanged. The next bounded CB-02 experiment must address shared
candidate guards/assembly, price lookup and SQL staging/selection. The record
retains original counters; no component ablation or new fix is claimed. Re-run
the full primary gate after a changed implementation. Do not substitute an
overall average or begin production integration from this failed gate.

**Sixth-wave result:** The requested-metric staging intervention omitted
1,412,574 ranking rows while retaining complete candidate books and unchanged
SQL policy. Contemporary complete/projected requests took 54.17/52.04 seconds.
Projection reduced request time by 3.92% and reached 4.87× against its faster
adjacent production control. Both prospective criteria fail. Both variants have
exact intermediate, holding, summary and replay agreement. Source and full
input identities match. See [wave6](phases/CB-02/wave6/README.md). No full matrix
ran. Keep this failed hypothesis visible; do not expand it unchanged.

**Seventh-wave result:** The source-derived candidate-decision prototype and
common encoder passed focused WSL/native checks, including mutations, tolerance
boundaries, nopython signatures, SQL selection, interruption and replay. The
runner now makes failed financial or measured-bound evidence terminal. Its
source variant matched complete intermediate and trial evidence exactly. The
request took 120.20 seconds; separate setup took 148.33. Controls took
691.08/598.52 seconds. These inputs match wave6's production identity, but the
controls and source request are slower. No cause is established.

The outer watchdog stopped at 2,700 seconds during the compiled variant's first
production control. The compiled candidate did not start. Its performance and
real-cache financial evidence are absent. The 10% paired-reduction and 5×
production criteria cannot be evaluated. Expansion is rejected. All owned
processes closed; native post-run identity checks confirm preserved production
inputs and frozen sources. See [wave7](phases/CB-02/wave7/README.md).

**Next bounded experiment:** Retain Numba and the unresolved source-derived
guard/assembly question. First design measurement orchestration or resource
planning that accounts for the observed control and preparation costs. Do not
rerun this unchanged orchestration for a favorable result. Declare the revised
scope, timing/resource budget and stop condition before timing. Preserve
contemporary controls, complete candidate evidence, one financial policy, SQL
parity, immediate freshness, saving and delivery. Do not infer compiled saving
from source-only counters. Do not lower the financial or speed gates to fit a
measurement budget. A promising paired pilot must precede the full unchanged
primary gate on one implementation identity. Production integration stays blocked.

Add the complete trailing-filter supplement and workflow measurements under
separately frozen settings. Isolated lifecycle proofs may proceed to expose an
operational blocker early. They do not authorize production integration.

**Gate:** Development focus is Numba. Production integration requires at least
5× median end-to-end improvement in every one of the six primary cases across
three seeds on one changed source identity. Require exact categorical agreement,
the existing numeric tolerance and a stated budget for integration overhead.
Repeat the gate on the integrated engine at CB-14. Keep the old failed result
visible until the changed implementation passes. Trigger CB-03 only for a
concrete unresolved limitation.

**Handoff:** Record the focus decision, passed and failed gates, reusable proofs,
hardening needs and unknowns. Freeze the measured typed-input/result boundary
before integration. Keep prototype shortcuts out of production rules.

### CB-03 Investigate the alternative only if needed

**Outcome:** A backend decision supported by the same workload and numerical contract.

**Work:** Reimplement only the limiting numerical slice in Rust, or run a truly batched Polars/DuckDB comparison if the issue is analytical processing. Reuse CB-02 inputs and output checks. Measure Python/native transfer and build/restart behavior. Resolve financial formula ownership if the implementation language changes.

All named methods have already been attempted. This phase is dormant unless a
new measured limitation justifies it. Record that trigger, its decision question,
budget and stop condition. Do not repeat the broad comparison by default.

**Deliverables:** A bounded comparison and an accepted backend decision. Update later phase assumptions and dependency requirements. If this phase is unnecessary, record a reasoned skip in the program ledger.

**Verification:** No gain from changed data, float32, relaxed arithmetic, altered filters or omitted saving. Verify native Windows packaging. A faster microbenchmark is insufficient if transfer or deployment removes the advantage.

**Handoff:** One selected backend. Do not retain two production implementations by accident.

### CB-04 Prepare immutable numerical generations

**Outcome:** The runtime can open validated, versioned inputs without rebuilding Python object graphs.

**Work:** Define the artifact contract. Export prices, sessions, Treasury inputs, annual reports, financial inputs and company metadata in bounded streams. Preserve stable original-buffer order and symbol sort order separately. Store the selected valuation series and adjusted series without changing their missingness. Add atomic publication, manifest verification and previous-generation recovery.

**Deliverables:** Offline preparation and read-only attachment commands, ignored artifact paths, a documented format and corruption/publication checks. Use existing cache validation and baseline readiness checks.

**Verification:** Compare exported values, dates and order against prepared source tables. Test no-input-change reuse, damaged/truncated buffers, interrupted publication, moved project paths and Windows readers holding an old generation. No raw download and no canonical report change solely from export.

**Handoff:** Format version, generation identity rules, ownership/closure contract and measured artifact size/load cost. Leave automatic startup integration to CB-12.

### CB-05 Implement date report and price primitives

**Outcome:** Native lookups reproduce the financial engine's temporal behavior.

**Work:** Implement sparse price searches, missingness masks, report availability and pool-specific eligible-report selection. Prepare report-level reusable values where safe. Preserve calendar-day tolerances and both forward and backward searches. Keep native inputs numeric and read-only.

**Deliverables:** Tested primitives and an adapter usable by later factor calculations. Explain any scalar policy extraction needed to share behavior.

**Verification:** Compare with existing `price`, `latest_statement` and snapshot inputs across real symbols and adversarial fixtures. Cover exact availability dates, age boundaries, unavailable prices, non-SPY dates, gaps, different valuation/adjusted availability and very short holding intervals. Run on Windows and Linux.

**Handoff:** Lookup semantics and measured cost. No website change and no new investment rule.

### CB-06 Implement the complete metric catalog

**Outcome:** Entry-date factor batches reproduce every current ranking pair and threshold value.

**Work:** Keep a single owned registry for current and three-year EV/EBITDA and all 18 threshold fields. Separate report-only work from entry-price-dependent work. Prepare report histories once. Use generic field IDs and explicit validity. Calculate requested factor dependencies in bounded batches; measure whether eager calculation of the small catalog is faster before optimizing further.

**Deliverables:** Full-catalog factor calculation, display metadata compatibility, dependency/version evidence and bounded factor-cache identity.

**Verification:** Differential tests against `metrics.evaluate` and `metrics.filter_values`. Include missing annual years, repeated report variants, USD conflicts, negative cash flow/margins, positive-denominator rules, PEG, ROE and leap-day trailing returns. Confirm that unneeded missing fields do not exclude a stock. Preserve current mean rounding and unrounded comparisons.

**Handoff:** Catalog coverage table, maximum numerical differences and factor-memory measurements. Consumers must not reconstruct formulas.

### CB-07 Implement generic filtering and ranking

**Outcome:** The compiled screener selects the same ordered stocks as SQL.

**Work:** Apply pool and period eligibility, limits, metadata filters, all threshold conditions and ranking through generic prepared fields. Reproduce the original pre-price buffer and its ties. Implement the exact final total ordering and requested rank slice. Begin with a correct deterministic sort; add partial selection only with measured need and tie proofs.

**Deliverables:** A selector with the existing request-validation semantics and SQL/browser comparison support.

**Verification:** Compare both pools, both ranking metrics, ranks 1–50, 1–100 and 51–100. Test null candidate ranks, tied cutoff values, duplicate scores, strict threshold boundaries, short/empty selections and invalid requests. Include near-exit entry eligibility before selection. Existing SQL and browser parity checks remain valid.

**Handoff:** A selector that consumes values without knowing their formulas. Record any deliberate validator-interface change.

### CB-08 Add weekly and intermediate intervals

**Outcome:** Fixed and random planners share an explicit calendar contract over the requested interval range.

**Work:** Freeze the week/month representation and accepted counts. Extend anchored boundaries and random blocks without changing existing month samples for existing requests. Keep explicit-date evaluation independent of how dates were generated. Version saved configuration conversion and reject ambiguous requests.

**Deliverables:** Calendar implementation, fixtures for all supported interval units and documented old-request mapping. Do not expose incomplete website controls yet.

**Verification:** Existing seeds and month configurations retain exact samples. Check one/two-week blocks, intermediate months, 24 months, leap days, holidays, duplicate rolled targets, partial final blocks and missing-session blocks. Verify common window bounds independently. Use deterministic calendars rather than financial engines to verify sampling rules.

**Handoff:** Frozen interval contract, configuration version and sample fixtures. This phase does not claim that the old planner supported weekly trials.

### CB-09 Evaluate fixed and explicit-date portfolios

**Outcome:** One numerical path turns selected stocks into complete dated portfolio results.

**Work:** Calculate selected returns, stopped exits, weights, contributions, period coverage, compounded growth and SPY comparison. Preserve current output evidence needed for inspection. Keep period eligibility separate from deferred return arithmetic. Support old month schedules and new explicit weekly date lists.

**Deliverables:** Fixed and explicit-date evaluator plus a diagnostic adapter. Retain the existing reference route for comparison.

**Verification:** Full holding/date/value/status parity against current schedules on isolated inputs. Check January books against the verified baseline, all existing frequencies, week-length explicit periods, bankruptcy fixtures, empty/short books, common-window cash, final marks and contribution order. Preserve `1e-12` tolerances.

**Handoff:** Complete financial result schema and evidence that selected-only returns preserve membership. Do not add random-job persistence in this phase.

### CB-10 Run random trials with durable recovery

**Outcome:** Random experiments use the new evaluator and preserve completed work after interruption.

**Work:** Retain deterministic sample generation and server-generated default seeds. Plan unique requested entry dates and factor dependencies. Store summaries, exact sampled dates and selected holding evidence atomically per completed trial. Keep configuration and input-generation identities explicit. Reuse shared calculations without collapsing duplicate trial identities.

**Deliverables:** Random experiment driver, compact result/checkpoint storage, saved-trial inspection and replay support. Add retention controls or a documented bounded policy for result growth.

**Verification:** Same seeds and existing settings match current experiments. Incomplete trials remain visible and paired distributions agree. Simulate interruption before/during/after commit, duplicate sampled schedules, filter changes and input-generation changes. Retry reuses only matching completed work. A new seed remains the default.

**Handoff:** Recovery contract, storage-size measurements and real progress units. Remove candidate-row writes from this path; do not remove old user books.

### CB-11 Add the persistent bounded runtime

**Outcome:** One server reuses open numeric inputs and native code without unbounded memory or orphan work.

**Work:** Attach a generation once, prewarm required signatures and select one measured native parallelism strategy. Bound factor caches, task queues and batch sizes. Add cancellation between chunks, deterministic per-portfolio reductions, safe generation handoff and explicit closure. Preserve project-level cache ownership and terminal lifecycle.

**Deliverables:** Runtime resource owner, worker/thread cap, cache limits, stage diagnostics and shutdown protocol.

**Verification:** Serial and parallel results agree. Stress repeated filter changes, invalidation, aborted requests, Ctrl+C, launcher replacement and two local servers. Test Windows mapping release before deletion. Confirm no nested thread multiplication, stale compiled globals or cross-generation cache reuse. Measure peak working set and memory after repeated jobs.

**Handoff:** Chosen parallel policy, cancellation bound, memory budget and compiler-cache signature. Do not rely on garbage collection alone to release mapped files.

### CB-12 Integrate preparation startup and data control

**Outcome:** The normal launcher brings the new engine to a ready state automatically.

**Work:** Extend dependency preparation in order: recover/verify research publication, prepare compatible base data, publish the numerical generation, prepare native runtime and rebuild stale website output. Add a pinned tested dependency environment. Preserve panel recovery when raw inputs are missing. Integrate stale-generation evidence with every relevant successful or partial coordinated download/repair. Preserve immediate direct-edit detection with equivalent current inventory checks.

**Deliverables:** Launcher/data-panel integration, runtime/dependency instructions, compact generation checks and preparation status. Existing standard-library reference commands remain available without installing the new numerical stack.

**Verification:** Unchanged restart avoids re-export. Changed inputs trigger correct preparation. Baseline publication recovery still precedes readers. Test missing dependencies, supported/unsupported Python versions, unavailable package network, offline installed operation, moved paths, invalid raw data, partial downloads, rebuild failure and simultaneous local launches. Keep all existing lock and secret-safe logging behavior.

**Handoff:** Tested Windows launch command and offline behavior. Initial package installation is separate from market-data downloading; running a strategy must not fetch market data.

### CB-13 Integrate the website and API

**Outcome:** Users can run the replacement through the existing website. Existing
month workflows can ship opt-in before the weekly extension is ready.

**Work:** Route dated schedule and robustness requests through an explicit opt-in engine selection. Adapt NDJSON events and progress text to actual work units. Add versioned saved settings, trial inspection, exports and errors. Expose week/month controls only after their calendar and evaluator checks pass. Ensure old saved requests have a defined route. Keep January/latest/static fallback behavior intact.

**Deliverables:** Working local UI/API flow, browser checks and a documented rollback setting. Update the guide to distinguish opt-in source from the default running engine.

**Verification:** Exercise a complete 24-trial run, changing filters, seed replay, weekly settings, cancellation/disconnection, saved trial inspection, CSVs and empty selections. Check desktop/mobile presentation when browser tools are available. Run existing range, screener, robustness, contributions and data-panel checks as affected. Build local output only.

For an existing-month milestone, mark weekly checks pending and keep weekly
controls unavailable. Run those checks before delivering the extension. Do not
mark the whole phase or program complete from the earlier milestone.

**Handoff:** API compatibility notes and browser evidence. Do not refresh or stage `website/dist/` as an incidental build action.

### CB-14 Qualify correctness speed and operations

**Outcome:** A reproducible decision to cut over or continue optimization.

**Work:** Run the complete primary paired benchmark matrix and report the per-case speed gates. Run catalog/rank/interval differential coverage, 100-trial annual stress and bounded weekly reference cases. Run candidate weekly capacity tests only after a safe pilot. Check cold/restart performance, repeated filters, recovery, memory and file growth. Repeat a measurement only when a failure or changed implementation justifies it.

**Deliverables:** Tracked qualification report with settings, hashes, versions, maximum numeric differences, raw-output locations, per-case timings and explicit gate verdicts. Update experiment documentation with the new evidence while retaining historical results.

**Verification:** All required correctness and operational checks pass on Windows. Primary cases each reach 5×. The complete trailing-filter supplement passes parity and coverage checks. Startup, fresh research, changed filters, saved-result reopening and weekly research meet the agreed absolute budgets. No speedup relies on warm selected-result caches, relaxed precision, missing filters or omitted persistence. Unverified cases remain explicit and cannot support a broad claim.

**Handoff:** Pass/fail table. If a gate fails, leave the engine opt-in and write the smallest evidence-led follow-up phase. Do not label the program complete.

### CB-15 Cut over and close the program

**Outcome:** The qualified engine is the default for dated backtests, with clear recovery and fallback instructions.

**Work:** Change the default only after CB-14 passes. Remove temporary prototype integration and obsolete default routing. Retain the reference/rollback path and old caches through a documented migration period. Update README, workflow, data documentation, root instructions and the architecture guide to the implemented state. Document adding metrics, extending data, rebuilding generations, inspecting saved trials and rolling back.

**Deliverables:** Default route, final user guide and program completion record. Record actual 5×/10× results by workload. Keep unachieved targets explicit.

**Verification:** Native Windows launcher smoke test, representative browser flow, offline operation and the required regression checks. Confirm the canonical report is unchanged unless a separately verified data revision explains it. Confirm old books and raw data remain available. Compare the complete commit diff with the architecture guide.

**Handoff:** Final commands, qualified dependency versions, measured operating limits, rollback procedure and remaining limitations. No automatic hosted publication or portable snapshot refresh is part of this phase.

## Automatic agent implementation protocol

This protocol applies to every phase, including benchmark and preparation tooling. Once the user requests a phase, that request authorizes its complete **design → implement → verify → smart-commit** sequence. Do not stop after presenting a design, proposing edits, passing tests or offering to commit. Do not ask for approval between these steps when the work remains within the phase and the program's constraints.

Updating this plan alone does not start a benchmark or implementation phase.

### Start each session

Read root `AGENTS.md`, this plan, the research findings and the preceding phase record. Inspect current Git status using `.git-local`. Preserve unrelated work, including existing portable-snapshot changes. Read only the files needed for that phase. Do not open the parent harness.

Confirm the prerequisite gates passed and record the phase's intended file scope. If scope no longer fits one session, split it in this master plan before starting a partial integration. An agent can make a routine split that preserves the objective, ordering and acceptance criteria without asking the user. Do not infer completion from a phase heading or from a prototype's existence.

Reassess the remaining plan against new evidence at each phase boundary. Update
it during a phase when a finding invalidates an assumption or dependency. Record
why the change is needed, its evidence, affected work and the next decision.
Apply the living-plan rules above. A local implementation detail does not need
a roadmap rewrite; a changed program direction does.

### Step 1 Run the detailed design skill

For code changes, invoke `$strategic-design-plan` with the selected phase as the brief. Supply its outcome, constraints, relevant current code, preceding decisions and verification requirements. Use the skill's independent planner and read-only workflow. Do not substitute the implementing agent's own design for the required planner report.

Print the returned report exactly as the skill requires. Once that read-only skill stage returns, the phase coordinator files the report verbatim at `docs/plans/compiled-backtest/phases/CB-xx.design.md`. This is the caller recording the report; the planner does not edit repository files. Record resolved requirements and routine choices separately in the phase record. Do not rewrite the planner's report to make it look accepted.

Proceed directly to implementation when the design fits the authorized phase. If a material code-structure change becomes necessary, rerun the design skill with the revised brief and preserve the superseded report as evidence. A routine repair that does not change the agreed structure does not need a new design cycle.

For a phase or subtask that changes only prose, captures measurements with existing tools, or records a backend decision without code changes, the design skill is outside scope. Record why that step does not apply and continue the remaining sequence automatically. Do not invent code work to force a design report.

### Step 2 Implement the phase

Implement the agreed structure and the scoped outcome. Make ordinary implementation choices autonomously. Use measured evidence to select a backend, trigger or skip CB-03, choose bounded buffers, and adjust task order within the dependency graph. Record these decisions and their reasons; they do not require a user approval round.

Preserve the financial correctness contract, benchmark gates, source data, canonical report integrity and unrelated changes. Keep all introduced helpers and API consumers consistent. Update affected documentation and the architecture guide with the implementation, not in a later cleanup phase.

### Step 3 Verify and repair

Run the phase's required checks, including native Windows checks where specified. Read failures, apply clear repairs and rerun affected checks until they pass. Dependency repair and bounded isolated experiments are part of the phase. Do not ask the user to run a routine preparation command or approve each test repair.

A failed speed gate is engineering evidence. Investigate its cause, improve the authorized design or run the planned alternative comparison automatically. Keep the gate failed until the evidence passes. Ask the user only when progress requires a critical scope, correctness, resource or acceptance decision. Do not lower the speed target, weaken tolerance, omit a filter or claim an unrun check passed.

Complete the phase record and status evidence before the commit audit. If required verification cannot finish, record the unfinished checks and their cause. Do not commit a phase as complete or start a dependent phase while a required gate remains unresolved.

### Step 4 Run smart-commit

Invoke `$smart-commit` after implementation and verification. Give its independent auditor the phase scope, baseline dirty-file list, design report, changed documentation and required checks. Follow its audit, finding review, clear-fix and verification steps. Do not use a self-audit as a substitute for the required auditor.

Resolve findings supported by existing authorization without another user approval. For example, the root snapshot rule already resolves exclusion of unrelated `website/dist/` changes. If a finding needs a genuine user decision and remains unresolved, obey the skill's confirmation gate and do not stage or commit. Do not reclassify a critical policy choice merely to force automation.

When the gate is clear, commit the coherent phase automatically. Include the filed design report, phase record, ledger change, code, tests and relevant documentation in that phase's commit. Use a subject containing the phase ID. Keep unrelated changes unstaged. Do not push, publish, amend previous commits, bypass hooks or stage a portable snapshot unless the user separately authorizes that action.

The phase record need not contain its own commit hash. It belongs to the same commit as the implementation. Report the actual hash after the commit and let the next session verify it from Git. Do not create a second bookkeeping commit just to insert that hash.

### Critical blockers and user decisions

An agent should ask the user when it cannot safely continue without one of the following:

- A change to financial meaning, universe coverage, freshness guarantees, numerical tolerance or an acceptance target.
- A material expansion of scope, paid service, destructive data action or unresolved ownership of changes.
- A tradeoff with materially different user outcomes that the program and evidence do not settle.
- Missing access, required independent delegation, a required verification environment or another external dependency with no authorized workaround.

Ordinary naming, file placement, implementation alternatives within the chosen design, test repairs, backend choices settled by the gates and phase splits are agent decisions. Uncertainty alone is not a reason to stop. Inspect the available evidence first.

If a critical blocker remains, preserve the completed work and recovery evidence. Ask a concise question that identifies the exact decision, its consequences and the recommended choice. Name and link any skill or repository rule that requires approval. Continue useful independent work while awaiting the answer. Do not perform work that depends on an unanswered decision or commit through an unresolved confirmation gate.

### Close each session

Write a short phase record under `docs/plans/compiled-backtest/phases/CB-xx.md`. Include objective, the design-report path or scope exception, autonomous decisions, changes, exact commands, results, numerical differences, audit findings and dispositions, evidence paths, unresolved risks and next-phase inputs. Mark completed, failed, blocked or deliberately skipped work precisely. Update the phase status ledger below. A stopped session must leave an exact resume point; incomplete work is not a completed phase.

Every completed implementation phase ends with its successful smart-commit. Follow the repository's guide rule: update affected guide explanations in the same commit; leave its checked date unchanged when no current claim changes. Run `node docs/architecture-guide/check.cjs` when the guide changes. Run relevant checks on native Windows where the root instructions require it. Report browser checks that remain unverified.

Report the outcome, verification, commit hash and any remaining critical issue. A request for one phase ends at that phase boundary without asking whether to commit. If the user requests multiple phases or the whole program, continue through the next ready phases automatically within the available session capacity. Preserve a resumable handoff when capacity ends. Do not require an approval at each phase boundary. These execution instructions do not create a background scheduler or guarantee a future session will start itself.

### Suggested session request

> Execute phase CB-xx from docs/plans/compiled-backtest/master-plan.md in one Codex 6.1-sol session. Read the repository instructions and preceding handoff. Use $strategic-design-plan for the detailed code structure, file its report, implement and verify the scoped outcome, then run $smart-commit and commit. Complete the process automatically. Ask me only about a critical blocker or a decision requiring my judgment. Preserve financial rules, raw inputs, canonical report integrity and unrelated changes. Update the phase record and status, then report the result and commit hash at the phase boundary.

For a program run, replace the first sentence with: "Execute the remaining ready phases in dependency order, using one phase record and smart-commit per phase, and leave a resumable handoff if the session ends."

## Phase status ledger

| Phase | Status | Evidence |
|---|---|---|
| CB-00 | Complete | `phases/CB-00.md`; WSL source and native Windows deployment |
| CB-01 | Complete | [Phase record](phases/CB-01/README.md); 18 native cases, exact replay and fresh-repeat agreement |
| CB-02 | In progress; Numba focus; 5× gate failed | [Wave5](phases/CB-02/wave5/README.md): all 18 cases exact; cached-F2 medians 4.66× / 4.53×. [Wave6](phases/CB-02/wave6/README.md): exact staging pilot rejected at 3.92% / 4.87×. [Wave7](phases/CB-02/wave7/README.md): 2,700-second budget stop before compiled candidate; paired performance unresolved; no production backend selected |
| CB-03 | Dormant, conditional | All named alternatives attempted; reopen for a concrete measured blocker |
| CB-04 | Planned | — |
| CB-05 | Planned | — |
| CB-06 | Planned | — |
| CB-07 | Planned | — |
| CB-08 | Planned | Weekly rules proposed, not implemented |
| CB-09 | Planned | — |
| CB-10 | Planned | — |
| CB-11 | Planned | — |
| CB-12 | Planned | Preserve immediate detection; operational and latency-budget checks pending |
| CB-13 | Planned | — |
| CB-14 | Planned | Final 5× gate pending |
| CB-15 | Planned | Default unchanged |

## Completion definition

The program is complete when the qualified dated engine is the default, all required financial and operational checks pass, every primary workload meets the 5× threshold, the agreed workflow budgets pass, weekly-to-two-year controls and saved-trial workflows work, and current user documentation describes the actual implementation. A kernel benchmark, a replay speedup or a partial catalog does not satisfy completion.

The immediate next step remains **CB-02**, now a focused Numba experiment.
All six named approaches have been tested. Wave4 preserves immediate manual-edit
detection. Wave5 completed the full primary comparison for Numba and Rust, with
exact financial agreement. Both fail the broader-pool F2 median gate. No primary
cases remain for wave5. Wave6 rejected requested-metric SQL staging alone:
3.92% observed request reduction and 4.87× production ratio. Do not expand
that unchanged intervention. Wave7 implemented the guard/assembly prototype but
its pair hit the 2,700-second whole budget before compiled candidate execution.
The next bounded design must account for the observed measurement costs before
another paired pilot. Do not expand this incomplete attempt. Preserve the
financial, freshness and acceptance contracts. A promising pair must precede the
full gate after implementation changes. Do not start production integration
before the required gate passes.

## Program decision record

| Date | Evidence and insight | Plan adjustment | Remaining decision |
|---|---|---|---|
| 25 October 2026 | Six methods attempted; full Numba/Rust matrix exact, but cached-F2 fails at 4.66×/4.53×. Numba median duration is lower in all six cases by a small margin. | Focus CB-02 on Numba and shared request costs. Keep alternatives dormant and all primary gates intact. | Does a bounded intervention close the gap without weakening contracts? |
| 25 October 2026 | All frozen F2 trials are incomplete. Setup is separate and startup/restart, filter changes and weekly capacity remain unqualified. | Retain F2; add complete trailing-filter coverage. Define workflow budgets before qualification. Separate existing-month delivery from weekly delivery. Allow early isolated operational proofs. | User acceptance budgets and full operational evidence remain unresolved. |
| 25 October 2026 | Equivalent fresh scanning preserved immediate manual-edit detection across the full matrix. | Remove startup-only detection from the planned direction. Reuse demonstrated work and harden only missing capabilities. | Production publisher and lifecycle proofs remain required. |
| 25 October 2026 | User explicitly permits plan changes when implementation yields new insight. | Reassess and update the roadmap from evidence, preserving history and acceptance criteria. | Raise material scope or acceptance changes for a user decision. |
| 25 October 2026 | Wave6 metric projection preserved exact results and removed 1,412,574 unused rows, but its 3.92% request reduction and 4.87× ratio failed the declared pilot criteria. | Stop this intervention without a full matrix. Retain Numba; focus the next bounded question on source-derived candidate guards/assembly. | Can one shared-policy intervention close the request gap? Full primary and operational gates remain required. |
| 25 October 2026 | Wave7 source-derived guard/assembly code passed 93 WSL and 92 native tests plus one skip. Source request and controls were 120.20 and 691.08/598.52 seconds on wave6's prepared-input identity. The 2,700-second watchdog stopped before compiled candidate execution. | Reject expansion of this incomplete pair. Revisit measurement orchestration/resource planning with a new prospective bounded protocol; retain the prototype and unchanged financial/speed gates. | Real-cache compiled correctness and paired performance remain unmeasured. A promising pair must precede the full primary matrix. |
