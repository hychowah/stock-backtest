# Operational commands and retained experiments

Maintained workspace operations live in `tools/ops`. Retained experiments live
in `tools/experiments`. Their package initializers do no work. Library callers
import these canonical owners.

| Owner | Purpose |
| --- | --- |
| `tools.ops.deploy` | Verified committed-source publication and native update supervision |
| `tools.ops.offline_input_copy` | Exact-byte private input materialization; no command entry |
| `tools.ops.prepared_input_coverage` | Read-only prepared-input coverage (version 2: no January book counts); no command entry |
| `tools.ops.list_stops`, `tools.ops.classify_stops` | Retained stop inspection commands |
| `tools.ops.log_summary` | Read-only summary of unfinished operations, operation times, slow requests and failures; run as a module |
| `tools.experiments.probe*`, `download_one`, `fetch_bulk` | Retained API acquisition experiments |

The thin entries in `tools/` are `deploy.py`, `probe.py`, `download_one.py` and
`fetch_bulk.py`. Each forwards to its owner in the table. Run
`tools/experiments/probe_list.py` and `probe_span.py` as modules, for example
`python3 -m tools.experiments.probe_list`. `scripts/list_stops.py` and
`scripts/classify_stops.py` also remain commands. Private workers and library modules have no forwarding
entries.

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
`website/build.py`. SPY and Treasury downloads belong to the data panel.

## WSL deployment

`deploy.py` publishes a committed source revision from the WSL checkout to the
registered native Windows runtime. It also starts that runtime and dispatches
saved-data checks. It does not download market data. See [workspace commands](../docs/workspaces.md).
