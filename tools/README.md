# Operational commands and retained experiments

Maintained workspace operations live in `tools/ops`. Retained benchmark and API
experiments live in `tools/experiments`. Their package initializers do no work.
Library callers import these canonical owners. Historical evidence keeps its
original command paths and measurements.

| Owner | Purpose |
| --- | --- |
| `tools.ops.deploy` | Verified committed-source publication and native update supervision |
| `tools.ops.offline_input_copy` | Exact-byte private input materialization; no command entry |
| `tools.ops.prepared_input_coverage` | Read-only prepared-input coverage; no command entry |
| `tools.ops.setup_numerical_native` | Explicit offline native toolchain setup |
| `tools.ops.repair_market` | Explicit SPY and Treasury repair |
| `tools.ops.list_stops`, `tools.ops.classify_stops` | Retained stop inspection commands |
| `tools.experiments.bench_*` | Retained source-bound benchmark and fixture machinery |
| `tools.experiments.parallel_comparison` | Scoped private comparison and its fixed child |
| `tools.experiments.probe*`, `download_one`, `fetch_bulk` | Retained API acquisition experiments |

The existing documented deployment, setup, repair, benchmark, probe and download
command paths remain thin entries. `scripts/list_stops.py` and
`scripts/classify_stops.py` also remain commands. Private workers and library
modules have no forwarding entries. Numerical policy, decisions, process
ownership and Numba implementation belong to `backtest`, not to tools.

The deployment entry also supports an old running controller. That controller
extracts only `tools/deploy.py` from its selected commit. The entry verifies the
request-bound archive hash. It extracts only the bounded regular
`tools/ops/deploy.py` helper. The helper loads support from the verified selected
payload before it publishes source. Source ownership still precedes cache
ownership. Interrupted publication still uses the existing journal.

Importing tool packages does not read credentials or make requests. Explicit
acquisition generally requires `~/.grok/secrets/fmp_api_key`. Offline fixtures
need neither credentials nor network access. Do not run acquisition to recompute
saved results or rebuild the website. Use `scripts/revalue.py` and
`website/build.py`. Real benchmark admission remains closed.

## Benchmark admission

Benchmark orchestration and timed request adapters are closed.
`tools/experiments/bench_admission.py` raises `BenchmarkAdmissionError` before
financial access or output work. No flag, environment variable, marker or copied
database admits a run. Synthetic tests patch the policy only inside disposable
fixture scopes. Source-only attachment and numerical fixture helpers remain
available. `tools/experiments/parallel_comparison.py` is the only scoped runner
that can still compare Original with the experimental engine, on a private copy.

The historical protocols (the end-to-end benchmark, the frozen production
baseline and the six-method comparison) are recorded as decisions and measured
results in the [faster engine summary](../docs/plans/compiled-backtest/master-plan.md)
and [results/experiments](../results/experiments/README.md). Do not run the
retained live-cache-locking protocols against the stable runtime.

## WSL deployment

`deploy.py` publishes a committed source revision from the WSL checkout to the
registered native Windows runtime. It also starts that runtime, dispatches
saved-data checks, and explicitly collects a verified report revision. It does
not download market data. See [workspace commands](../docs/workspaces.md).


## Offline database capture

`bench_capture_offline.py` is separate from the closed benchmark entry points.
Use it only in a user-authorized stopped-server window. It acquires exclusive
source ownership before financial ownership with no wait. SQLite backup preserves
the research/daily/report set and all saved books. It rejects pending publications,
sidecars and WAL source format; no original normalization or preparation runs.
A source or data owner makes capture fail. A new server start can wait until
capture completes. The tool never stops or starts a server.

Keep output in a dedicated ignored native Windows experiment directory. Captured
freshness metadata is retained, not rebased. The output confers no execution
admission. See [wave11](../docs/plans/compiled-backtest/master-plan.md)
for source/receipt validation, limits, actual capture evidence and attachment gaps.


## Captured input workspace

`bench_execution_inputs.CapturedWorkspace` consumes an explicit wave11 capture,
an explicit matching source tree and a fresh experiment directory. It validates
the fixed research/daily/report artifacts and captured financial coherence.
It copies actual source bytes into private storage and checks their captured
hashes. It opens the captured databases read-only. `writable_daily()` creates a
fresh SQLite backup under that workspace. Saved books are retained initially.
All borrowed handles and derivatives close before workspace ownership ends.
Completed and failed workspace evidence remains available.

This bounded input abstraction does not import financial engines, construct a
PolicyProgram, discover installed paths or attach either runner. Its freshness
evidence describes capture time. It does not substitute for current request-time
raw checks. Metadata is never rewritten to make a different root look current.
The owner takes no stable financial lock. Synthetic cooperative caps do not
admit the existing real capture or qualify resources. Do not create real
workspaces or derivatives before later resource/cancellation admission.

See [wave12](../docs/plans/compiled-backtest/master-plan.md).
The next engine facade must consume this owner, bind both engines and actual
policy to its generation, and preserve immediate edit detection with live
priority. Benchmark admission stays closed.

## Isolated captured policy

`bench_execution_policy.CapturedPolicy` consumes an active CapturedWorkspace.
It owns one source-only child and its verified benchmark tools beneath the
workspace. The child imports actual application modules from private source and
constructs the actual PolicyProgram. Its immutable binding joins policy/source
evidence to the captured financial generation. It does not rewrite application
paths or captured metadata. It exposes no financial command or application
module. Parent imports and logging stay separate. Outer workspace closure also
closes an escaped policy scope before releasing ownership. Stop-signal and
evidence-write errors cannot bypass child/reader/handle cleanup. If cleanup
cannot be confirmed, the workspace retains its owned resources and lock. Retry
its context exit after resolving the cleanup failure. Retain the workspace object
and call `inputs.__exit__(None, None, None)` to finish that suspended outer exit.
Closing only the policy does not finish the outer exit. A caller exception keeps
its original identity; it does not grant early ownership release.

The source-derived program belongs to
`backtest.engines.numerical.policy.PolicyProgram`. Financial formulas and signatures stay unchanged. Construction
needs no NumPy. Existing numerical methods import NumPy when called. The retained
candidate runner's source inventory also hashes the extracted implementation.
A changed implementation rejects attachment before database or executor access.

Only bounded synthetic fixtures are qualified here. Existing workspace caps stay
unchanged. The child has a ten-second attachment deadline and a sampled 128 MiB
memory limit. These checks do not establish hard CPU/disk isolation or transient
peaks. See [wave13](../docs/plans/compiled-backtest/master-plan.md).
Reference controls, NumericInputs, current request-time freshness and general
execution lifecycle still need the isolated engine facade. No real capture,
derivative, request or benchmark is admitted.


## Measured-execution hardening (source only)

`bench_execution.MeasurementExecution` owns the actual private reference and
Numba adapters, current observations, private derivatives, compiler files,
results and confirmed closure. `bench_execution_observation.CurrentObservation`
shares fixture and coordinated checks. Coordinated mode requires verified
participating cache-access source. It takes source ownership before short cache
ownership and yields to live-intent leases. It releases both before calculation.
This is cooperative priority, not zero-delay access or installed compatibility.

`backtest.runtime.process_owner.OwnedProcess` bounds transport and records separate
closure facts. Native Job Objects limit committed memory, processes and CPU
share. Resident-memory, thread and disk enforcement remain incomplete. Linux
sessions do not prevent escape. Full resource qualification stays open.

Validate the prospective declaration without reading runtime assets:

```text
python3 tools/bench_comparison.py < tests/fixtures/prospective-comparison.json
```

This validates arithmetic and protocol shape only. It cannot verify caller
qualification claims, discover the runtime, admit execution or resume a stopped
pair. The declaration retains pending real bindings. No real pilot is authorized.
See the [hardening record](../docs/plans/compiled-backtest/master-plan.md).
