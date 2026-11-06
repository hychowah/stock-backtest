# Prepared research database

`research.sqlite` is generated locally from the saved JSON cache. It is excluded from Git and can be rebuilt without an API key or downloads:

```bash
python3 scripts/research.py prepare
```

Every preparation is a full build (research schema 19). It writes a temporary file and replaces the database in one step; a failure keeps the previous database. The build also records its fact diff against the database it replaces: the earliest changed row of each kind and company. Files whose bytes and fact-row code are unchanged are not compared. Running preparation again without input changes only checks file metadata and returns immediately. It runs no second engine and publishes no report.

The database contains company metadata and listing, cleaned annual financial observations with availability dates, and typed facts for custom variables and books. It holds no book: the latest and dated books live in the book store of `schedules.sqlite`. It does not duplicate daily histories as JSON: those stay in `raw/px/`.

The original-screen pool retains the original reported-value thresholds and 250-name pre-price buffer. The broader pool covers only companies with cached prices, not all names in the universe. Missing prices are not downloaded automatically. Run `python3 scripts/research.py status` to inspect annual coverage.

Queries use read-only connections and check the research record: core input file stamps, the price-directory timestamp and the content identity of the fact-row code, without scanning every price file. Preparation checks the full per-price-file size/timestamp manifest. After editing an existing price file, run preparation to incorporate and validate the change; queries are reads of the last prepared snapshot. The `.building` database is temporary; a failed preparation preserves the previous completed database. Fingerprints are local freshness checks, not cryptographic verification of downloaded data.

`schedules.sqlite` (version 11) is the separate rebuildable book store, prepared by
`python3 scripts/schedules.py prepare`. Its tables (`books`, `book_pools`,
`book_rows`, `book_metrics`, `book_filters`) hold the latest book and the
reusable entry/exit books in one row shape and one book-id space. The latest
book stores prospective picks at the latest cached session with no holding
return; after extending price data, run preparation then rebuild the website; an
open HTML file is a saved snapshot, not a live data feed. A daily connection
attaches `research.sqlite` read-only; books read the research facts there, and
the cache copies no research table: it holds the book store and its binding
only. The local website
service computes missing dated books and persists them here; `research.sqlite`
remains read-only. Daily-cache freshness is its binding: the research content
identity and the content identity of the book code (`research.code_sources`
names the files); editing a reader such as the schedule engine changes neither.

`book_metrics` stores ready-to-rank multiple/yield pairs keyed by book, pool,
symbol and catalog metric ID; `book_filters` stores the threshold values.
`books.book` computes all formulas, including screening-date EV divided by
three-year average EBITDA, and preserves the default metric's exact existing
values. Missing history omits a pair. Consumers join or export these values;
they never reconstruct formulas. Catalog and calculator code in
`backtest/financial/metrics.py` is book code: an edit drops the saved books.

`book_pools(book,pool)` records which pools a book completed. A completed book can
contain one or both pools. The service prepares only the requested pool, and
fills the other on demand while retaining the same book ID. Completion markers
also cover empty pools; do not infer readiness from the presence of rows.
Markers, rows and metrics commit together, once per schedule/trial. See
[the schedule calendar](../docs/schedule-calendar.md) for the date rules.

Random batches plan unique missing books upfront. Read-only worker processes
calculate ahead; one parent writes complete trials in order. Calculations do not
hold a write transaction. Price lookups share one short read transaction per
book, released before the result returns to the writer. The parent stages large trials in a temporary local
file before their atomic save. Replays start no workers when all books are saved.

A daily cache from an older version, or one whose research content or book code
changed, fails the freshness check. `python3 scripts/schedules.py prepare`
then updates it from the saved files, in place and in one transaction. A new
research content keeps each dated book whose last read day (its exit, or its
entry plus four days if later) is before the first day that research's fact
diff can show to a book; the other books and the old latest book go, and the
new latest book is written. A failure rolls the transaction back. An older
version or changed book code empties the store first. No market data is
downloaded.

`logs/website-<namespace>-<pid>.log` holds development diagnostics for one server process. Startup and the data panel show the active file. It uses UTC timestamps and keeps error types, OS codes and stack locations without exception messages or source lines. Provider URLs, keys and response bodies are excluded. The log rotates at 5 MiB and retains two backups per process. The folder is ignored by Git.

## Saved backtests

`saved-backtests.sqlite` contains user-saved backtests. It is separate from the
rebuildable research and schedule databases. Keep this file during cache cleanup,
rebuilds and source deployment. Back it up with your local user data.

The website stores at most 100 complete records. Each record keeps the submitted
settings, traded stocks, holding-period returns, result summaries and display
labels. Opening a record reads its stored results without running a calculation.
Changed data does not rewrite a saved record. Delete individual records in the
website to free slots. Reaching the limit never removes an older record.

`backtest/application/library.py` owns this database. SQLite transactions enforce the
limit across server instances. Each complete snapshot is compressed inside its
record. A failed save keeps existing records. This database does not participate
in financial-cache freshness or rebuilds.

Reading an older record never rewrites its stored contents. See
[durable evidence](../docs/durable-evidence.md) for the snapshot versions.

## Overnight backtest queue

`backtest-queue.sqlite` is durable user data. Keep it during preparation, cleanup
and source deployment. It stores up to 100 fixed or random-date test records,
including completed results. Results are compressed version-2 snapshots with
their submitted settings and display labels. They stay until explicit deletion.
The saved library remains independent.

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


## Durable variable library

`variable-library.sqlite` contains reusable user variables. It is separate from
financial caches, `saved-backtests.sqlite` and `backtest-queue.sqlite`. Preserve
all three durable files during rebuilds, cleanup and source publication.
`backtest/variables/library.py` owns the callable repository.

A stable variable ID has immutable authored content revisions. Names and
favourites use an independent mutable entry version. Formula edits must supply
the expected entry version. Renaming or changing a favourite does not alter the
formula revision. Deletion hides the active entry and retains all revisions.
Exact references can still resolve retained revisions. No automatic eviction or
garbage collection is implemented.

SQLite commit publishes a change. Restart retains committed data. Unsupported or
damaged files are reported and preserved, never replaced with a financial-cache
rebuild. Construction and imports do not create the file. Private test stores
cover persistence; the installed store is not a test fixture.

Atomic capture reads complete exact programs and presentation from one snapshot.
The returned `VariableCapture` needs no later database state. Its checked restore
remains usable after entry deletion or removal of the file. Capturing local
definitions does not save them. A strategy request carries its capture, so the
queue and the saved-backtest library store the exact formulas with the result.
