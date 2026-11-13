# Prepared research database

`research.sqlite` is generated locally from the saved JSON cache. It is excluded from Git and can be rebuilt without an API key or downloads:

```bash
python3 scripts/research.py prepare
```

Compatible preparation updates changed typed rows in one transaction. [The research workflow](../docs/research-workflow.md#prepare-once) states the current research schema and daily cache versions. Cold, schema or fact-code builds use a temporary file and atomic replacement. Failure keeps the previous committed data. Running preparation again without input changes only checks file metadata and returns immediately. It runs no second engine and publishes no report.

The database contains company metadata and listing, cleaned annual financial observations with availability dates, and typed facts for custom variables and books. Its last preparation stage derives `valuation_sums` from these facts: each company's running sums of daily E/P, S/P and B/P and their day counts, one row per priced day with a yield. Books read them for the valuation averages. It holds no book: the latest and dated books live in the book store of `schedules.sqlite`. It does not duplicate daily histories as JSON: those stay in `raw/px/`.

The original-screen pool retains the original reported-value thresholds and 250-name pre-price buffer. The broader pool covers only companies with cached prices, not all names in the universe. Preparation never downloads missing prices. The unified Update data operation adds newly discovered or newly eligible companies; see the [data workflow](../docs/research-workflow.md#data-control-panel). Run `python3 scripts/research.py status` to inspect annual coverage.

Queries use read-only connections and check the research record: core input file stamps, the price-directory timestamp and the content identity of the fact-row code, without scanning every price file. Preparation checks the full per-price-file size/timestamp manifest. After editing an existing price file, run preparation to incorporate and validate the change; queries are reads of the last prepared snapshot. The `.building` database and the `.building.<n>` range files of a parallel cold build are temporary; a failed preparation preserves the previous completed database. Fingerprints are local freshness checks, not cryptographic verification of downloaded data.

`schedules.sqlite` is a rebuildable compact entry-sheet store, prepared by
`python3 scripts/schedules.py prepare`. Its version is stated in the research
workflow. `books` identifies an entry and latest/historical policy; `book_pools`
marks complete pools, including empty ones. `book_rows` stores one row per stock,
with report dates, actual entry/price, valuation and catalog-mapped metric/filter
columns. NULL means unavailable. REAL owner values retain existing rounding and
zero normalization. Typed research facts and formula outputs still preserve
signed zero. There are no separate metric/filter tables or stored holding exits.

A daily connection attaches research read-only. Latest requires listed companies
and an exact-session price. Historical sheets allow four days of entry slack;
one entry/pool sheet serves every later exit. Runs build missing sheets on demand.
Actual entry must precede exit before ranking, scalar limits and formulas.
Only selected holdings read exit prices through `books.close`. Results retain
complete return/status rows. The website embeds latest only; historical sheet
coverage adds no readiness gate. Unified updates precompute cached history in
the `sheets` stage, after website output and before verification. Plain startup,
CLI preparation and runs keep on-demand behavior; legacy stays on demand.

Catalog code in `backtest/financial/metrics.py` owns formulas; consumers read
prepared columns without reconstructing them. Pool rows and completion commit
atomically under the existing single writer. Switching pools fills only the
missing pool. See [the schedule calendar](../docs/schedule-calendar.md).

Random batches plan unique missing books upfront. Read-only worker processes
calculate ahead; one parent writes complete trials in order. Calculations do not
hold a write transaction. Price lookups share one short read transaction per
book, released before the result returns to the writer. The parent stages large trials in a temporary local
file before their atomic save. Replays start no workers when all books are saved.

See [sheet repair and cache reuse](../docs/research-workflow.md#custom-trade-dates-and-rebalance-intervals).

`logs/website-<namespace>-<pid>.log` holds development diagnostics for one server process. Startup and the data panel show the active file. It uses UTC timestamps and keeps error types, OS codes and stack locations without exception messages or source lines. Provider URLs, keys and response bodies are excluded. The log rotates at 5 MiB and retains two backups per process. The folder is ignored by Git.

`data-refresh.json` is the update status and pending-addition record. The
existing financial cache owner writes it atomically. It stores the saved scope,
target date, stage counts and successful stage prefix, verified running time,
last success and matching-scope successful stage durations. Continue reruns
unfinished stages; an incomplete report stage is refreshed again. A foreign
busy cache leaves its running status unconfirmed. Status reads never resume it.
The `sheets` stage counts existing historical cached completions plus each
new committed sheet. Rows and completion commit together, one sheet at a time;
Continue builds only missing completions under the current binding. It reuses
the existing bounded read-only workers and parent writer. There is no new
checkpoint format or VACUUM. The [data workflow](../docs/research-workflow.md#data-control-panel) owns the
full behavior. This status is separate from research freshness and saved results.

## Saved backtests

`saved-backtests.sqlite` contains user-saved backtests. It is separate from the
rebuildable research and schedule databases. Keep this file during cache cleanup,
rebuilds and source deployment. Back it up with your local user data.

The website stores at most 100 complete records. Each record keeps the submitted
settings, traded stocks, holding-period returns, result summaries and display
labels. Opening a record reads its stored results without running a calculation.
Changed data does not rewrite a saved record. Delete individual records in the
website to free slots. Reaching the limit never removes an older record. A
locked record cannot be deleted until it is unlocked; the lock is a separate
table and does not change the record.

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
