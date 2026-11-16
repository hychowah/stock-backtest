# Development notes

For someone who works on the code. [The README](../README.md) describes the
product, and [Running the program](running.md) the installed site.

## How the parts work

- **Raw files.** `bt data update` downloads prices, annual reports, FX rates,
  SPY and Treasury yields from Financial Modeling Prep (FMP) into `raw/`. It
  asks for new prices on each run and checks reports once a week.
- **The prepared store.** `bt data prepare` reads `raw/` and writes typed
  column files for each market, in about 21 seconds for the owner's US and
  Hong Kong data. It publishes them as a whole new generation. A reader keeps the
  generation it opened, so a preparation never changes a run in progress.
- **The engine.** On each trade date, the engine calculates that day's
  candidates from the prepared store, runs the strategy's steps and values the
  portfolio. Strategy calculations never download data.
- **Result files.** A run writes one SQLite file for each strategy. A result
  file never changes. The website's charts and tables and the command-line
  exports read the same rows.
- **Two faces of the same commands.** The website (`bt serve`) and the command
  line call the same commands, so a test gives the same numbers in both.
- **The nightly update.** A user timer runs `bt data update` every night.
  It downloads, then prepares every market.

## Project layout

| Path | Contents |
|---|---|
| `crates/` | The Rust program `bt`: `numbers`, `market-data` (raw files and the prepared store), `engine` (strategies, formulas, schedules, results), `tables`, `app` (the run list and the HTTP server), `fetch` (the data update) and `bt` (the commands) |
| `web/` | The TypeScript website that `bt serve` serves ([web/README.md](../web/README.md)) |
| `fixtures/` | The frozen test data ([fixtures/README.md](../fixtures/README.md)) |
| `results/` | The frozen January study record ([results/README.md](../results/README.md)) |
| `docs/` | The [command-line guide](command-line.md), [methodology](methodology.md), [parameter catalog](parameter-catalog.md) and [running the program](running.md) |
| `install.sh` | Builds and installs the program and the website |

## Testing

```bash
cargo test --locked                      # Rust tests, from the root
cd web && npm ci && npm run check && npm test && npm run build
npx playwright test                      # browser checks, in web/
```

The Rust tests compare whole runs, prepared data and data updates with the
frozen fixtures. They also write the website's API types into `web/src/api/`.
The browser checks need `cargo build -p bt` and, once,
`npx playwright install chromium`. Each worker starts `bt serve` on a private
home made from the fictional data, with a stand-in for the provider
([web/README.md](../web/README.md#browser-checks)). GitHub Actions runs all of
these on every push, and fails when the committed API types differ from the
ones the tests write.

## Engineering notes

- **The replacement was shown equal.** The program replaced an earlier Python
  product with equal results. Prepared data and results were
  compared with the Python product's on real data: 75.3 million prepared rows
  and 5.3 million result rows, with no difference. The data update was
  replayed on recorded provider replies at full scale, and every raw file was
  byte-equal (48,165 and 63,334 files). One real update ran beside the Python
  updater. The files were equal except where the provider's data changed
  between the two downloads. The owner's 66 saved tests were converted and
  run again in the new program.
- **Frozen fixtures are the specification.** The number vectors, formula
  vectors, fictional data set, expected tables and data-update cases were
  taken from the Python product and do not change
  ([fixtures](../fixtures/README.md)). The Python source remains at the Git tag
  `python-oracle`.
- **Faster and smaller.** On the owner's computer, a nightly update takes
  about 7 and a half minutes, where the Python one took 24. A 3.8 GB research
  database and an 11 GB store of precomputed sheets became one prepared store,
  with candidates calculated on demand.
- **Safe writes.** A raw file, a generation or a result file is written whole
  and then published, so an interrupted write keeps the old one. A stopped
  update keeps what it saved and continues from there.
- **No secrets in output.** The provider key stays in the client. Logs,
  status and records never hold the key, a request URL or a reply.
