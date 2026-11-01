# Project structure and modularity

Recorded: 1 November 2026. Source owner: `main` in the WSL checkout.
Status: Phase 1 complete at `07b34d1`. Phase 2 complete at `ccc5d4f`. Phase 3 complete in this commit. Phase 4 pending.

The independent GPT-6.1 Sol high planner's report follows verbatim.

### Design

**Goal:** Give the project a clear source structure with importable backtest modules, thin command entry points, and a website that contains presentation and HTTP concerns. A reader should be able to find the owner of financial rules, prepared inputs, execution, durable results, and runtime resources without knowing the project’s development history. Preserve financial behavior, full precision, existing command lines, stored evidence, and runtime ownership.

**Options:**

1. **Organize by workflow:** `january/`, `latest/`, `scheduled/`, and `random/`, each exposing preparation, execution, and results. This makes one workflow easy to find. Its common interface would be `workflow.prepare()`, `workflow.run(request)`, and `workflow.open_result(id)`. However, shared ranking, dated books, calendars, numerical execution, and evidence would cross these directories repeatedly. The split would hide existing dependencies behind more adapters.

2. **Organize by knowledge ownership:** One `backtest` package owns financial policy, inputs, engines, application operations, and runtime support. The website consumes application operations and detached results. Command scripts compose these modules. Common interfaces are selection, calendar planning, calculation, and acquired result access. Workflow differences remain parameters or existing engine operations where they already share the same policy.

**Chosen:** Option 2. The project already has valuable shared abstractions: financial books, metric calculations, calendar requests, portfolio reduction, engine selection, and immutable evidence. Give these abstractions proper owners and repair their weak boundaries. Do not replace them with a framework.

The target structure is:

```text
backtest/
    financial/          authoritative production rules, books and metrics
    inputs/             raw assets, annual inputs, prepared databases, baseline publication
    engines/
        original/       dated books, ordinary batches and random execution
        numerical/      generation, compilation, providers, trials and child protocol
        reference/      independent January calculation and retained original arithmetic
    application/        calculation selection, jobs, queue, library and result access
    runtime/            cache coordination, cancellation, diagnostics and process support
    paths.py
    screening.py
    calendar.py
    calendar_requests.py
    portfolio_results.py

website/
    browser/            JavaScript, CSS and browser fragments
    rendering/          prepared dataset export and static HTML generation
    server/             HTTP handlers and server composition
    serve.py            source-owning native bootstrap
    runtime_access.py   bootstrap-safe source ownership
    build.py            documented build entry
    local/              existing ignored output
    dist/               existing portable snapshot

scripts/                documented commands
tools/
    ops/                maintained offline and operational commands
    experiments/        retained research and benchmark machinery
tests/
docs/
```

Do not split each directory into another layer of tiny packages. Existing numerical modules can remain a flat set inside `engines/numerical`; their names already describe substantial responsibilities.

Key boundaries:

- **Financial policy** owns production eligibility, valuation, metrics, and filters. It opens no databases and imports no command scripts, application modules, or numerical dependencies.
- **Screening** owns selection validation and SQL ranking over prepared tables. Callers validate requests directly; they never execute an empty query as a validation trick.
- **Inputs** own schemas, freshness, publication, and saved asset validation. They preserve existing on-disk paths and publication journals.
- **Engines** consume validated requests and acquired inputs. They return detached results or emit the existing bounded evidence contract. Original remains the default. The independent reference keeps its own valuation and return arithmetic.
- **Application** owns admission, submitted engine identity, jobs, queue recovery, user records, and result acquisition. It closes execution resources before publishing outcomes.
- **Website** owns HTTP and presentation. A browser view acquires a stored artifact through one result-access operation and releases it through the same owner.
- **Runtime** provides the existing resource mechanisms. Source ownership remains in the minimal native bootstrap before application imports. This refactor must preserve the current source/cache/database/worker ordering.

The error model remains deliberately small:

- Invalid requests fail with the existing validation errors before preparation or calculation.
- Unavailable inputs and contention retain existing admission behavior.
- Cancellation propagates through existing checkpoints and cleanup.
- Source or generation mismatch rejects reuse.
- Unknown compiler syntax fails explicitly; it never silently substitutes another calculation.
- Corrupt stored evidence fails inspection without recalculation.
- Unexpected implementation errors propagate to the existing safe diagnostics boundary.

Moving source changes derived identities. That should invalidate rebuildable preparation and checkpoints where their contracts require it. It must not rewrite durable library records, queue evidence, or historical measurements.

This program is owned by `main` under the user’s new authorization. Record that narrow ownership exception in `docs/worktree-coordination.md`. The engine worktree remains untouched. Custom-variable implementation stays on hold.

### Plan

**Phase 1 — Deliver the shared policy and selection core.**

This is the first substantial implementation phase. It includes the master record and working code.

Create:

```text
backtest/__init__.py
backtest/paths.py
backtest/financial/__init__.py
backtest/financial/rules.py
backtest/financial/books.py
backtest/financial/metrics.py
backtest/screening.py
backtest/calendar.py
backtest/calendar_requests.py
backtest/portfolio_results.py
```

The package initializers must not eagerly import engines, databases, or optional dependencies.

Move the existing shared book, metric, calendar, calendar-request, and portfolio-result implementations to these owners. Remove their former library modules after migrating callers. Remove the existing `numerical_calendar` compatibility alias; consumers use the actual shared calendar-request owner.

`financial.rules` removes the production policy dependency on `scripts/run.py`. Move the existing strategy constants, scalar/date decoding, and annual-report availability helpers needed by `books` there without changing their behavior. The retained original calculation can import shared configuration and decoding where it already shared those functions. Its valuation, selection arithmetic, price arithmetic, and return calculation remain independent. Do not make the reference call production `books.snapshot`, SQL selection, or numerical policy.

`backtest.paths` resolves the existing project root and runtime assets from its own location. Moving code must not move `raw`, databases, reports, logs, numerical stores, or user records.

Extract the validation and SQL selection currently combined in `research._select` into the screening owner. Its interface comments must establish:

```python
validate_selection(**options)
select(db, *, period=None, **options)
historical(db, *, first=1996, last=2026, **options)
latest(db, **options)
```

Use the existing selection defaults and accepted keyword names. `validate_selection` performs no SQL and does not mutate submitted settings. `period=None` selects latest snapshots; an inclusive period range selects prepared historical or dated rows. Historical year validation belongs to `historical`, not to the common selector.

Preserve both selection orders, original ranks, deterministic ties, missing metric behavior, threshold units, and survivor weighting. Preserve validation precedence where callers depend on it.

Migrate the current validation-only calls in:

- `scripts/robustness.py`
- `scripts/book_batch.py`
- `scripts/schedules.py`
- `website/original_calculations.py`

They must call the validator instead of `research._select(..., period=(-1, -1))`. Actual dated selection calls use the public selector.

Update the numerical adapters to reach financial policy through its actual owner. This phase changes import and source bindings, not the compiler’s supported language or financial formulas. Keep the larger extraction of policy from orchestration for Phase 2.

Repair source tracking in the same phase:

- The numerical transitive-source resolver must understand package-qualified and relative local imports without importing providers.
- Source keys must use repository-relative POSIX paths where moved modules make basename keys ambiguous.
- Research freshness must include the moved financial sources.
- Changes to any consumed policy source must invalidate the appropriate derived identity.
- Unrelated files must not disappear from existing conservative identity coverage.

Update all internal callers and test imports to canonical owners. Keep executable compatibility only for documented commands. Do not create a permanent forwarding module for each old import name.

Deliver interface comments before finalizing implementation. File the verbatim master plan at `docs/plans/project-structure/master-plan.md`, with the phase record under `docs/plans/project-structure/phases/phase-01.md`. Record the new ownership exception and affected architecture-guide paths.

Phase 1 is complete when:

- Production core imports no `scripts`, `tools`, or `website` modules.
- No caller uses a private selector or an empty selection query for validation.
- Shared calendar/result modules have one owner.
- Source identities cover moved dependencies and reject changed policy.
- Existing documented CLI argument shapes still work from another working directory.
- Financial, selection, calendar, result, and relevant numerical checks pass.
- The guide, independent audit, verification record, and coherent commit are complete.

Required verification includes the existing research, selection-order, schedules, robustness, batch, portfolio-result, calendar, baseline, financial-input, operating-spread, numerical-policy/decision, generation, and source-binding checks affected by the change. Add meaningful checks that validation performs no database access and package dependencies participate in identity. Run relevant spawn/import and synthetic financial checks with native Windows Python in a private source export. Run `node docs/architecture-guide/check.cjs`. Record actual commands and outcomes only after execution.

**Phase 2 — Deliver prepared-input and execution ownership.**

Move prepared-input implementations into `backtest.inputs`; split daily preparation/storage out of the mixed `schedules` module. Move Original, numerical, and reference implementations into their engine packages. Move existing cancellation, financial coordination, diagnostics, and process support into runtime owners. Keep bootstrap source ownership minimal and separate.

The important design improvement is a financial-source boundary for compilation. Today `numerical_policy` reads local assignments named `cap`, `ev`, and `ret`, finds a `spy_return` assignment inside `compute_period`, and reads a positional `snapshots.append` expression. Replace these orchestration dependencies with explicit authoritative policy functions or projections. Both ordinary execution and source-derived compilation must consume those actual functions. Preserve source-derived guards, arithmetic order, fail-closed behavior, and independent reference arithmetic. Do not build a second handwritten formula registry.

The detailed phase design must choose these interfaces after probing the current snapshot translator and both code generators. It must also define the daily-store interface used by ordinary workers and the generation exporter.

Retain documented `scripts/research.py`, `scripts/schedules.py`, `scripts/revalue.py`, and numerical command paths as thin executable entry points. Library imports use package owners. Update child entry, source closure, prepared inventories, optional dependency loading, compiler assets, and native spawn targets together.

Later phases use engine and input interfaces; they do not reach through `schedules.r` or borrow orchestration internals.

Completion requires complete financial parity, preparation/publication recovery, worker cancellation and closure, fresh/full/interrupted numerical recovery, source identity, and WSL/native Windows checks. Do not run real-cache preparation, downloads, deployment, or new performance qualification.

**Phase 3 — Deliver application-owned calculations and result access.**

Move calculation contracts, engine selection, Original and candidate application adapters, jobs, queue, library, and evidence services into `backtest.application`.

Keep the existing durable databases separate. Preserve completed-result transfer receipts, capacity, stored bytes, engine pinning, and queue recovery.

Introduce one application result-access boundary for job, queue, and saved evidence. It owns acquisition, pinning, eager-versus-evidence handling, bounded views, exports, and release. HTTP handlers should not reconstruct evidence ownership. Browser opening, comparison, and parameter inspection should use one acquisition helper that also handles lost responses and stale selections.

Keep existing route and payload shapes. This phase does not add a new database, result representation, engine plugin system, or automatic recalculation.

Later website work calls application operations and consumes immutable artifacts. It does not know transaction or financial-resource details.

Completion requires application lifecycle, jobs, queue/library transfer, durable and temporary evidence, reader cleanup, comparison, and browser recovery checks in WSL and native synthetic fixtures.

**Phase 4 — Deliver the presentation and command shell.**

Move browser sources into `website/browser`, static build implementation into `website/rendering`, and HTTP composition into `website/server`. Keep `serve.py`, bootstrap-safe `runtime_access.py`, `build.py`, local output, and portable output at their documented locations.

Split the current build function around substantive renderers and build assembly. Split the HTTP module around application-facing route groups and server lifetime. Avoid a helper file for each route or fragment.

Make website source inventories recursive over explicit source directories. Exclude generated output. Preserve normalized content hashing, build stamps, inline standalone assets, static fallback, exports, and snapshot rules.

Group maintained operational commands under `tools/ops` and retained benchmark/research machinery under `tools/experiments`. Preserve historically documented executable commands with thin launchers where needed. Retained benchmarks stay outside production imports and keep closed admission. Update current documentation; historical evidence retains its original paths and measurements.

Finish the repository map and architecture diagrams. Check that documented commands work from another directory and that production imports do not depend on experimental tools or path injection into sibling library directories.

Completion requires synthetic build/browser checks, offline startup and launcher checks, deployment-manifest tests against disposable runtimes, package/source dependency checks, and native Windows spawn/bootstrap checks. Preserve the two unrelated portable-snapshot edits and all market-qualification files byte for byte.

Every phase receives its own detailed independent design, implementation, independent smart-commit audit, and commit. Check for active automatic publication supervisors immediately before each commit. No phase is complete merely because its files have moved or its plan has been written.

The program is complete only when all four abstractions exist, internal imports use their owners, documented commands remain usable, required verification passes, and every phase is audited and committed. No distribution packaging, dependency-injection framework, new backend, database migration, website publication, or custom-variable implementation is required.

### Unknowns

- **Package-aware source closure:** The current resolver searches flat directories and misses package imports. Probe absolute imports, relative imports, package initializers, and a changed transitive policy dependency with tiny synthetic files before moving sources.
- **Compiler extraction boundary:** Snapshot guards and both native generators constrain useful policy functions. Inspect and test a representative valuation and SPY-return extraction before finalizing Phase 2. Unsupported shapes must fail explicitly.
- **Entrypoint assumptions:** Workers, toolchain probes, fixture exports, and tests use file-relative paths and top-level imports. Inventory those paths per phase, then exercise real spawn/import behavior in private WSL and Windows source copies.
- **Historical command compatibility:** Documentation names more operational tools than the normal workflow uses. Inventory executable references before Phase 4. Preserve documented commands, while migrating internal imports instead of preserving every historical module name.
- **Standalone build coverage:** This checkout lacks the full runtime cache and may lack generated local output. Establish synthetic rendering fixtures early. Report any browser or real-cache checks that remain unavailable; do not refresh the unrelated portable snapshot to obtain test inputs.
- **Other worktree coordination:** CB-19 A–G are complete on current main, while the engine worktree retains an earlier source state. Record this program’s main ownership and final handoff explicitly; do not synchronize that worktree or its plan as part of the refactor.
- **Automatic publication:** Supervisor absence is temporary. Inspect both relevant WSL and native process namespaces immediately before every commit. An active supervisor requires an isolated task branch so a source-structure commit cannot publish itself.
- **Freshness and durable evidence:** Source moves will invalidate derived identities. Test that existing durable artifacts remain readable without current numerical preparation and that stale checkpoints are rejected rather than silently accepted or rewritten.

## Execution ledger

The user's future-compatibility reminder is addressed by the independent
[custom-variable clarification](custom-variable-compatibility.md). It applies
to all four phases. It does not resume the held feature.

User authorization: implement the master plan autonomously, with an independent
Sol high planner and auditor, a Sol medium implementer, and an audited commit
for each substantial phase. The goal is active until all phases are complete.

| Phase | Status | Record |
|---|---|---|
| 1: Shared policy and selection | Complete at `07b34d1` | phases/phase-01.md |
| 2: Inputs, engines and runtime | Complete at `ccc5d4f` | phases/phase-02.md |
| 3: Application and result access | Complete in this commit | phases/phase-03.md |
| 4: Presentation and command shell | Pending | phases/phase-04.md |
