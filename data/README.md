# Prepared research database

`research.sqlite` is generated locally from the saved JSON cache. It is excluded from Git and can be rebuilt without an API key or downloads:

```bash
python3 scripts/research.py prepare
```

Preparation reads each cached company price history once, writes compact January snapshots, and compares the original top-50 priced holdings and annual returns with the independent engine before publishing the report/database pair. Running preparation again without input changes only checks file metadata and returns immediately.

The database contains company metadata, cleaned annual financial observations with availability dates, January holding periods, entry valuations/holding returns for both original-screen candidates and the wider set with cached prices, and separate latest-session valuations for cached currently-listed companies with an exact-date price. It does not duplicate daily histories: those stay in `raw/px/`. Changes to rebalance frequency require additional preparation.

The original-screen pool retains the original reported-value thresholds and 250-name pre-price buffer. The broader pool covers only companies with cached prices, not all names in the universe. Missing prices are not downloaded automatically. Run `python3 scripts/research.py status` to inspect annual coverage.

Queries use read-only connections and check core input files, calculation code, and the price-directory timestamp without scanning every price file. Preparation checks the full per-price-file size/timestamp manifest. After editing an existing price file, run preparation to incorporate and validate the change; queries are reads of the last prepared snapshot. The `.building` database is temporary; a failed preparation preserves the previous completed database. Fingerprints are local freshness checks, not cryptographic verification of downloaded data.

`latest_snapshots` stores prospective picks with no holding return. Latest-date metadata records the actual cached session and coverage. The canonical report's saved Through date constrains historical snapshots independently of newer latest-session prices. After extending price data, run preparation then rebuild the website; an open HTML file is a saved snapshot, not a live data feed.

Schema 4 stores `screening_metrics`: ready-to-rank multiple/yield pairs keyed
by mode, pool, year, symbol and catalog metric ID. Latest observations use year
0. Preparation computes all formulas, including screening-date EV divided by
three-year average EBITDA, and preserves the default metric's exact existing
values. Missing history omits a pair. Consumers join or export these values;
they never reconstruct formulas. Catalog and calculator code in
`scripts/metrics.py` participates in freshness checks.

`schedules.sqlite` is the separate rebuildable daily-price index and dated-book
cache, prepared by `python3 scripts/schedules.py prepare`. It stores only existing
cached price histories plus research financials, SPY sessions, Treasury yields
and reusable entry/exit books. The local website service computes missing books
and persists them here; original `research.sqlite` remains read-only. Daily-cache
freshness includes the schedule engine and research calculation fingerprints.

Daily cache version 3 retains `period_pools(period_id,pool)` from version 2. A completed period can
contain one or both pools. The service prepares only the requested pool, and
fills the other on demand while retaining the same period ID. Completion markers
also cover empty pools; do not infer readiness from the presence of snapshots.
Markers, snapshots and metrics commit together, once per schedule/trial.

Random batches plan unique missing books upfront. Read-only worker processes
calculate ahead; one parent writes complete trials in order. Calculations do not
hold a write transaction. Price lookups share one short read transaction per
book, released before the result returns to the writer. The parent stages large trials in a temporary local
file before their atomic save. Replays start no workers when all books are saved.

The launcher upgrades compatible version-1/2 caches in place. Version-1 books
mark both pools complete; version-2 books retain individual completion markers.
Prices, financials and dated results are retained. Changed research inputs or financial calculation code still trigger an
offline rebuild. No market data is downloaded during either path.

`logs/website-<pid>.log` holds development diagnostics for one server process. Startup and the data panel show the active file. It uses UTC timestamps and keeps error types, OS codes and stack locations without exception messages or source lines. Provider URLs, keys and response bodies are excluded. The log rotates at 5 MiB and retains two backups per process. The folder is ignored by Git.

Schema 6 adds `baseline_prices` and `baseline_periods` for holding-level agreement.
Metadata stores the priced result, last historical revision and exact report
hash. The report cutoff is a source input; generated report contents are a
publication identity. An unfinished `research.sqlite.publication.json` blocks
readers. Preparation completes that verified publication before checking cache
freshness. Keep its referenced `results/baseline-history/` files for recovery.

## Saved backtests

`saved-backtests.sqlite` contains user-saved backtests. It is separate from the
rebuildable research and schedule databases. Keep this file during cache cleanup,
rebuilds and source deployment. Back it up with your local user data.

The website stores at most 20 complete records. Each record keeps the submitted
settings, traded stocks, holding-period returns, result summaries and display
labels. Opening a record reads its stored results without running a calculation.
Changed data does not rewrite a saved record. Delete individual records in the
website to free slots. Reaching the limit never removes an older record.

`website/saved_backtests.py` owns this database. SQLite transactions enforce the
limit across server instances. Each complete snapshot is compressed inside its
record. A failed save keeps existing records. This database does not participate
in financial-cache freshness or rebuilds.

Saved snapshots support versions 1 and 2 within the same database table. Version 2
uses semantic presentation fields instead of DOM IDs and CSS classes. The browser
converts version-1 records when opening them. Reading old records never rewrites
their stored contents. Both formats preserve the original stock rows and returns.

## Overnight backtest queue

`backtest-queue.sqlite` is durable user data. Keep it during preparation, cleanup
and source deployment. It stores up to 100 fixed or random-date test records,
including completed results. Results are compressed version-2 snapshots with
their submitted settings and display labels. They stay until explicit deletion.
The 20-slot saved library remains independent.

The queue also stores order, pause state, held edits, revisions, progress and
random seeds. A started random test records its full date plan for interruption
recovery. Changing waiting calculation parameters discards that old plan.
Renaming a test keeps its dates. The queue does not participate in research
freshness and never downloads market data.

`backtest-queue.lock` elects one consumer across server instances. Keep ownership
through worker completion and financial database closure. Queue transactions
end before the consumer requests financial ownership. A stopped consumer leaves
unfinished work waiting. An abrupt exit releases the OS lock; its successor
recovers running items only after acquiring that lock. Pending Stop requests
remain stopped. Deleted items keep only a small submission receipt to prevent
an acknowledgement retry from recreating them.
