# Data acquisition and diagnostics

These are retained API experiments and maintenance tools, not the normal workflow. They make network requests and generally require `~/.grok/secrets/fmp_api_key`.

| Script | Purpose |
| --- | --- |
| `bench_metrics.py` | Time per-symbol metrics requests |
| `download_one.py` | Download one exploratory bulk file into `raw/archive/` |
| `fetch_bulk.py` | Legacy bulk downloader; outputs to `raw/archive/` |
| `probe.py` | Inspect bulk response shapes |
| `probe_list.py` | Inspect stock-list pagination |
| `probe_span.py` | Check history request date windows |
| `repair_market.py` | Replace active SPY and Treasury caches using short request windows |

Do not run these just to recompute results or rebuild the website. Use `scripts/revalue.py` and `website/build.py` instead. Bulk downloads can be refused by the provider, and long histories can be truncated. The main missing-data workflow lives in `scripts/run.py` and retains its older exit rule.
