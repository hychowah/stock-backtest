# Reusable data cache

Keep this directory with the project. Normal runs read these files without fetching data.

| Path | Contents |
| --- | --- |
| `universe.json` | US stock universe, including delisted names |
| `metrics.jsonl` | Annual financial metrics, one record per symbol |
| `px/*.json` | Stock price histories, one file per symbol |
| `spy-div.json` | Dividend-adjusted SPY history |
| `treasury.json` | Treasury yields; `month3` is in percent |
| `download-coverage.json` | Content-bound receipts: SHA-256, completed windows, original base span and one previous generation, including empty provider responses |
| `archive/` | Old bulk CSV files, delisted-list pages, and unused SPY light history |

`archive/` also preserves corrupt originals as `*.before-data-repair` when the data panel repairs a file. Other archive files are retained for provenance; the backtest does not read it. Cache files are historical snapshots and do not refresh automatically. The data panel checks actual date spans and prior requested windows. It does not guarantee a price on every session. Use Manage backtest data to inspect coverage, fill missing ranges and rebuild prepared outputs. Back up this directory rather than downloading it again.

Price responses keep usable rows and skip zero or negative adjusted prices. The receipt records these exclusions as `skipped_dates`. The data panel warns about them, and exported check reports list each date. Exclusions apply only to the exact saved file. A response containing only these excluded prices is recorded as checked but unavailable. It stores no invented prices and does not stop the batch. Malformed records and missing or nonfinite values still fail. A checked window can contain unavailable dates.

`financial-inputs/<endpoint>/<symbol>.json` holds complete annual income, balance-sheet, cash-flow, key-metrics and ratios responses. All returned fields, nulls, currencies and filing metadata are retained. Calculations select their own eligible USD inputs. New `metrics.jsonl` records also keep full key-metric responses; older trimmed records can be backfilled in the separate full-data cache. Download these through the data panel, then rebuild. The original metrics cache remains unchanged. Completion receipts in `download-coverage.json` bind each endpoint asset, including empty responses, to its content hash. Existing valid fields are preserved. Missing fields are not filled from newer fiscal reports.

Repeated fiscal dates are valid in full-data assets. Keep all response rows and retain distinct saved variants on repair. Prepared inputs use agreed nonmissing USD values; conflicting inputs stay unavailable.
