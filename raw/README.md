# Reusable data cache

Keep this directory with the project. Normal runs read these files without fetching data.

| Path | Contents |
| --- | --- |
| `universe.json` | US stock universe, including delisted names |
| `metrics.jsonl` | Annual financial metrics, one record per symbol |
| `px/*.json` | Stock price histories, one file per symbol |
| `spy-div.json` | Dividend-adjusted SPY history |
| `treasury.json` | Treasury yields; `month3` is in percent |
| `archive/` | Old bulk CSV files, delisted-list pages, and unused SPY light history |

`archive/` is retained for provenance; the backtest does not read it. Cache files are historical snapshots and do not refresh automatically. Price caching checks file existence; it does not guarantee full date coverage. Back up this directory rather than downloading it again.
