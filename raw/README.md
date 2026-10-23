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

`archive/` also preserves corrupt originals as `*.before-data-repair` when the data panel repairs a file. Other archive files are retained for provenance; the backtest does not read it. Cache files are historical snapshots and do not refresh automatically. The legacy downloader checks price-file existence. The data panel checks actual date spans and prior requested windows. Neither guarantees a price on every session. Use Manage backtest data to inspect coverage, fill missing ranges and rebuild prepared outputs. Back up this directory rather than downloading it again.

Price responses keep usable rows and skip zero or negative adjusted prices. The receipt records these exclusions as `skipped_dates`. The data panel warns about them, and exported check reports list each date. Exclusions apply only to the exact saved file. A response containing only these excluded prices is recorded as checked but unavailable. It stores no invented prices and does not stop the batch. Malformed records and missing or nonfinite values still fail. A checked window can contain unavailable dates.
