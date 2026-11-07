# Project structure and modularity

Status: complete

Deleted: the benchmark capture and its protocol-7 tests were deleted on
2026-11-04. Real benchmark admission does not exist.

## Outcome

The program moved the source to owners organized by knowledge, in four phases.
It changed no financial formula, prepared schema, file location, HTTP route,
request shape or durable record format.

- `backtest/` is an importable package. `financial/` owns rules, books and
  metrics. `inputs/` owns raw assets, preparation, daily storage and baseline
  publication. `engines/original` and `engines/reference` own calculation;
  `engines/numerical` was deleted on 2026-11-05. `application/` owns calculation selection, jobs, queue,
  library, preparation and result access. `runtime/` owns cache coordination,
  cancellation, diagnostics and process support. Shared modules at the package
  root own screening, calendars, calendar requests, portfolio results, the
  evidence codec and paths.
- `website/` holds presentation and HTTP only: `browser/` (plain scripts,
  styles, fragments), `rendering/` (detached data, static page, assets, build,
  freshness) and `server/` (lifetime and grouped HTTP adapters).
  `serve.py`, `runtime_access.py` and `build.py` stay as
  stable entries and source-owning bootstraps.
- `tools/ops/` holds maintained operations. `tools/experiments/` holds retained
  benchmarks, probes and download experiments. `scripts/` and thin `tools/*.py`
  files remain the documented executable commands.

No production library imports `scripts`, `tools` or website code. Package
initializers execute no operations. Later custom-variable work added
`backtest/variables/` on top of this layout.

## Key decisions

- **Organize by knowledge ownership, not by workflow.** A `january/`,
  `latest/`, `scheduled/`, `random/` split was rejected. Ranking, dated books,
  calendars, numerical execution and evidence are shared. That split would hide
  these dependencies behind more adapters.
- **No permanent forwarding modules.** Callers and tests moved to canonical
  owners. Only documented executable commands keep their old paths. The
  `numerical_calendar` alias and the tool forwarding aliases were removed.
- **Validation performs no SQL.** `screening.validate_selection` replaced the
  old trick of running `research._select(..., period=(-1, -1))`. `select`,
  `historical` and `latest` keep the existing defaults and keyword names.
- **Production policy does not import `scripts/run.py`.** Strategy constants,
  decoding, report availability and `BANKRUPT` live in
  `backtest/financial/rules.py`. The reference engine keeps its own valuation,
  selection and return arithmetic. It shares only configuration, decoding and
  saved-file readers.
- **Package-aware source identity.** The source closure resolves absolute,
  relative and package-initializer imports statically, without importing
  providers. Keys are repository-relative POSIX paths, because basename keys
  silently lost one of two same-named initializers. `rust_kernel.rs` is an
  exact declared resource, not a module. `website/runtime_access.py` is an
  explicit source root, because it is loaded by file and static closure does
  not see it.
- **Storage is separate from calculation.** `inputs/daily.py` owns the daily
  store; `engines/original/schedules.py` owns calculation. Numerical
  attachments carry inputs, policy, bindings and closure, not the Original
  engine module. A "services facade" over the old module bag was rejected,
  because it kept the same coupling under a new name.
- **Named financial functions for the compiler.** `books.entry_valuation`,
  `benchmark_return` and `yield_spread` replace compiler inspection of
  orchestration locals and `snapshots.append` positions. One narrow normalizer
  expands the agreed helper call. It is not a general inliner. It rejects async
  functions, changed signatures, rebinding and changed lookup forms. Entry
  valuation needs no exit price. A comparison of 512 synthetic snapshot cases
  against the Phase 1 baseline matched exactly, including missing observations,
  stopped exits and bankruptcy.
- **Preparation was an application operation.** The experimental engine's
  preparation ran a website callback after verified child closure, under
  financial ownership. That code was deleted on 2026-11-05.
- **Engine errors are mapped by the adapter.** Numerical `InputsUnavailable`
  becomes application `Unavailable` only after confirmed retirement, including
  after delayed closure. Engines do not import jobs.
- **Children acquire source before package imports.** They launch by exact file
  path and load the bootstrap by file. `python -m`, `PYTHONPATH` and sibling
  path injection were rejected, because package initialization would precede
  the source lock.
- **One acquired-result owner, not one result store.** A universal result store
  was rejected. It would change durable ownership, receipts and migration rules.
  `ResultAccess` dispatches run, saved and queue sources, with 16 display readers
  and 32 request pins. A valid release fences a delayed acquisition. Shutdown
  closes admission, joins the queue, drains readers, closes jobs, joins HTTP
  requests and retires the calculation child, in that order. The browser uses
  one `ResultArtifacts.use` scope and creates the reader ID before the POST.
- **Keep the runtime model.** Separate frontend and API applications, a bundler,
  ES modules, a route framework, mixins and one module per endpoint were
  rejected. A fictional workspace built before and after Phase 4 produced
  byte-identical HTML pages and baseline CSV/JSON exports. Website freshness
  hashes explicit nested roots with normalized newlines.
- **Deployment transition bootstrap.** A running old controller extracts and runs
  only `tools/deploy.py` from the selected commit. That file stays a
  standard-library entry. For `--native-publish`, it checks the request-bound
  archive hash, then runs `tools/ops/deploy.py` from that archive (one regular
  member, at most 1 MiB). It never imports installed packages. Tests ran a
  byte-identical old controller against a new-layout disposable repository.
- **Custom variables were not anticipated in code.** The refactor kept the
  built-in metric-pair contract explicit. It added no scalar interface, formula
  field or reserved version. Result artifact version 3 was already in use.

## Where the current contracts live

- [Current source owners](source-map.md).
- [Project layout and commands](../../../AGENTS.md#project-layout).
- [Architecture guide](../../architecture-guide/dist/index.html), file map.
- [Acquired result readers](../../evidence-views.md).
- [WSL source and native runtime](../../workspaces.md), for deployment.
- [Custom ranking and filtering variables](../custom-variables/master-plan.md).

## Known limits and open items

- Verification used synthetic fixtures and private source exports in WSL and
  native Windows. No real-cache preparation, download, deployment or installed
  restart was part of this program.
- Source moves changed derived identities. Older checkpoints, generations and
  captured source bindings are incompatible and must rebuild. Durable library
  and queue records were not rewritten.
- One native ancestor-lifetime case once failed on a generic limit. It passed on
  an isolated rerun with the same bounds (2,304 MiB committed memory, 16
  processes, 25% CPU rate, 180 user seconds). The trigger is unknown.
- Historical captured artifacts keep their original paths and hashes. The
  engine worktree was not synchronized.
