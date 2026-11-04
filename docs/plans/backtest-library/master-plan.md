# Backtest library usability

Status: complete

## Outcome

The saved-backtest library keeps completed tests so that users can find, rename,
inspect and compare them. All four phases are complete.

- The library holds up to 100 records. Each record shows its existing UUID.
  Users can rename a record and sort by stored performance. Queue and library
  lists are bounded, labeled scroll regions with keyboard access.
- Each completed queue result moves to the library through a recoverable
  transfer. It is not calculated again. A full library or a failed transfer
  keeps the complete result visible in the queue for retry.
- Users can compare exactly two saved records. The comparison shows recorded
  performance and aligned parameter rows. Changed rows are marked.
- Each saved row has a lazy All parameters disclosure.

Opening, comparing or inspecting a stored record never calculates, prepares
data or reads a current catalog. The work changed no financial calculation,
request shape, cancellation rule or resource ownership.

## Key decisions

- **Two databases, one transfer.** The queue owns execution in
  `data/backtest-queue.sqlite`. The library owns completed results in
  `data/saved-backtests.sqlite`. Two alternatives were rejected. One combined
  execution-and-results database would change durable-store ownership and
  reader contracts. An attached-database transaction would couple both schemas,
  publication internals and transaction ownership.
- **Use the existing UUID primary keys.** No second identifier was added.
- **Rename is metadata only.** `POST /api/backtests/<id>` takes
  `{"name": "..."}`. The body limit is 4 KiB. Names have 1–120 characters.
  An invalid name returns 400. A missing ID returns 404. Result bytes, creation
  dates and IDs do not change. Rename needs no financial access or decoding.
- **Capacity is 100, atomic across instances.** The browser reads the limit from
  the collection response. Nothing is evicted automatically.
- **Sorting uses stored values only.** Performance means stored CAGR, or stored
  mean trial CAGR for random tests. Missing values are last in both directions.
  Ties sort by saved date descending, then UUID ascending. The default is newest
  saved.
- **Idempotent library admission.** `Store.accept_queue_result(source_id, name,
  open_source)` writes a `queue_imports` receipt keyed by queue ID. The receipt,
  the record and its complete evidence commit in one transaction. The receipt
  survives deletion of the saved record. A retry returns the first outcome. It
  cannot recreate a deleted record, take another slot or undo a rename. A short
  preflight checks receipts before capacity and opens no source. The final write
  transaction repeats both checks.
- **Queue reservation and archival.** The queue `transfers` table stores the
  reservation, saved ID, a safe retry reason and the completion fingerprint.
  The fingerprint survives archival, so a completion retry cannot replace the
  original result. Deletion wins before reservation. During a reservation,
  deletion returns a conflict that asks the user to refresh and retry. Archived
  rows keep submission and completion receipts, but leave the visible list and
  its capacity count. Their duplicate result bytes are removed after the library
  receipt commits. Open detached readers keep their bytes.
- **One reconciler.** Only the elected queue consumer transfers results. It does
  this before readiness and pause checks, so paused or engine-unavailable queues
  still transfer. The queue read transaction ends before library publication.
  A transfer failure never enters calculation-failure handling.
- **Browser refresh by revision.** Queue collection responses carry
  `library_revision`, the archived-result count. A changed value refreshes the
  library. An active rename or library mutation defers that refresh until Save,
  Cancel or Escape.
- **Comparison is a pure browser module.** A server comparison endpoint was
  rejected, because it would add presentation policy beside the browser artifact
  owner. `website/browser/backtest-comparison.js` describes stored artifacts and
  aligns their rows. Its normalization rules:
  - Calendars normalize through `CalendarSettings`.
  - AND-filter order and repeated identical conditions do not change meaning.
  - Strict operators and exact values stay exact.
  - Only documented omission defaults apply, such as filter-first and Original.
  - Unfamiliar settings stay visible with their field names.
  - Stored labels are used.
  - Requested engine and recorded producer stay separate. A missing producer is
    unidentified.
  - Seed policy and recorded seed stay separate.
  - Random results are trial distributions. Mean trial CAGR is never presented
    as one portfolio return.
  - Different test types or windows produce a comparability notice.
  - Changed rows use color and the word "Different".
- **Comparison loading is independent of the main view.** It uses the shared
  result-acquisition scope, projects each artifact at once and releases its
  reader. Its own generation token discards stale replies. It never opens,
  publishes or restores the main result or form.
- **All parameters loads lazily.** Embedding settings in every list response was
  rejected, because it changes server metadata and loads settings for all
  records. A native `<details>` element loads one compact description on first
  expansion. Native `toggle` events do not bubble, so a capture listener handles
  them. State is keyed by record ID and pruned on deletion. A failure shows an
  inline retry.
- **Layout check.** A preview with 100 fictional records per list kept both
  lists bounded. At 1440×1000 the queue was 560 px high and the library 480 px.
  At 390×844 the page had no horizontal overflow.

## Where the current contracts live

- Root [AGENTS.md](../../../AGENTS.md#feature-contracts): the Saved library
  and queue, and Result access contracts.
- [Durable evidence snapshots](../../durable-evidence.md), for version-3
  results inside the queue and library databases.
- [Acquired result readers](../../evidence-views.md).
- [Architecture guide](../../architecture-guide/dist/index.html).
- Source owners: `backtest/application/library.py`,
  `backtest/application/queue.py`, `website/browser/saved-backtests.js`,
  `website/browser/backtest-comparison.js` and `website/browser/queue.js`.
- Checks: `tests/test_saved_backtests.py`, `tests/test_queue_transfer.py`,
  `tests/test_queue.py`, `tests/check-saved-backtests.cjs`,
  `tests/check-backtest-comparison.cjs` and `tests/check-saved-comparison.cjs`.

## Known limits and open items

- Comparison covers exactly two records. It adds no charts.
- Saved results are never recalculated, and the library never evicts a record.
  At capacity, completed queue results wait for a free slot.
- Browser reader release is best effort. A server that cannot be reached cannot
  acknowledge a release. Server-side limits still bound retained readers.
- Verification used fictional fixtures in WSL and native Windows. No installed
  user stores, real-cache build or deployment were part of this work.
