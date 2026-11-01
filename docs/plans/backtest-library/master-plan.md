# Backtest library usability

### Design

**Goal:** Make completed tests easy to retain, find, rename and compare. Provide 100 saved slots, automatic queue-to-library transfer, stable identifiers, performance sorting and bounded lists. Preserve stored results and all calculation, request, cancellation and ownership contracts.

**Options:**

1. **One execution-and-results database.** A single record moves from waiting to completed; queue and library become filtered views. Common interface: submit, list by state, rename, open and delete. This is a clean design for a new system, but here it changes existing durable-store ownership and result-reader contracts.
2. **Library owns completed results; queue owns execution.** Keep both databases. Add one recoverable transfer operation between them. Common interfaces: `library.rename(id, name)`, `library.accept_queue_result(source_id, ...)`, and `queue.archive_completed(id, saved_id)`. Existing result readers continue to own artifact compatibility.

**Chosen:** Option 2. Existing durable databases and protected engine boundaries are real constraints. A reliable transfer establishes the desired ownership without changing execution.

- `saved_backtests.Store` owns capacity, names, stable IDs and import receipts. Existing records already have UUID primary keys; expose these instead of inventing another identifier.
- Queue completion commits its original artifact first. Transfer then saves a complete independent library record and acknowledges archival in the queue. Only afterward may queue-held result bytes be removed.
- A durable import receipt keyed by queue ID makes retries safe. Keep the receipt after library deletion so interrupted transfer cannot recreate an explicitly deleted result. Renaming an imported record must survive retries.
- Archived queue records retain submission receipts but leave the visible queue and its capacity count. Existing completed records follow the same transfer path.
- At capacity or after a transfer failure, retain the complete queue result and show “Completed — waiting for saved slot” or a retry notice. Retry without recalculation. Failed and stopped tests remain in the queue.
- `BacktestComparison` describes stored artifacts and compares their parameters. It owns display normalization, including legacy calendar representations and documented defaults. It never mutates artifacts or submits calculations.
- Comparison uses exactly two saved records, highlights changed parameter rows, and shows unchanged rows too. Performance remains explicitly labeled: CAGR for fixed/January tests; mean trial CAGR for random tests. Different windows or test types receive a comparability notice.
- Queue and library lists use bounded, labeled scroll regions. Headers and controls remain outside them.

### Plan

1. **Deliver the manageable library.** Raise capacity atomically to 100 and have the browser read the returned limit. Expose full UUIDs, add inline Rename with Save/Cancel, and provide performance ascending/descending sorting with missing values last and deterministic ties. Rename changes only metadata. Bound both lists without changing queue behavior. Deliver interface comments and tests for capacity races, unchanged artifact bytes, rename validation, sorting and acknowledged mutations after failed refreshes.

2. **Deliver recoverable completion transfer.** Implement the library’s idempotent import interface and queue archival acknowledgment. The queue consumer reconciles completed results after completion and during recovery, including while execution is paused. Later UI work consumes transfer status instead of knowing transaction details. Test interruption before and after each commit, concurrent instances, full capacity, deletion and rename during recovery, older completed jobs, and eager/version-3 evidence. Preserve existing lock order and financial-resource lifetimes.

3. **Deliver stored-result comparison.** Add a pure parameter-description/comparison module and two-record selection in the library. Acquire records through existing artifact readers without publishing them into the main result view. Keep compact descriptions and release temporary readers. Highlight differences with text as well as color. Test legacy defaults, calendars, filters, random seeds, requested engines versus recorded producers, missing performance and selection changes.

Each slice updates the architecture guide, runs focused synthetic Python/browser checks and relevant regression checks, then receives its own smart commit. Exclude unrelated dirty files. Do not build a new result store, recalculate saved results, add charts, or introduce automatic eviction.

### Unknowns

- **Transfer representation:** Verify how eager blobs and version-3 evidence can enter the same idempotent import operation. Probe both with temporary databases before implementing transfer.
- **Historical parameter variation:** Inspect synthetic legacy/current fixtures to identify comparison defaults and unknown fields. Preserve unfamiliar settings visibly rather than silently dropping them.
- **Scrolling usability:** Preview 100 fictional records on desktop and mobile. Check keyboard access, focus retention, rename controls and comparison width before committing.
- **Native compatibility:** Run durable-store and queue checks with native Windows fixtures when available; report any checks that remain unverified.

## Phase record

- Phase 1: complete after independent smart-commit audit and focused verification.
- Phase 2: pending.
- Phase 3: pending.

The work is committed on `ui/backtest-library`. An existing automatic publication
supervisor watches `main`. That branch stays at `f7e320d81761f4a9ee4f1c119e03285b0609efb9`
while these slices are implemented. The task branch avoids automatic publication.
No supervisor stop, deployment or installed-server restart is part of this work.

Phase 1 keeps existing UUID primary keys and adds `POST /api/backtests/<id>` with
`{"name":"New name"}`. The response is the updated list metadata. Invalid names
return 400; a missing ID returns 404. The body is limited to 4 KiB. The operation
changes only the name. No financial access or result decoding is needed.

The browser reads library capacity from the existing collection response. Sort
order uses stored CAGR, or stored mean trial CAGR for random tests. Missing
performance stays last in both directions. Saved date descending, then UUID
ascending, breaks ties. The default is newest saved.

Phase 1 verification on 1 November 2026:

- `python3 tests/test_saved_backtests.py`: 13 tests passed in WSL.
- Native Windows Python, source UNC path, `tests/test_saved_backtests.py`: 13 tests passed.
- `node tests/check-saved-backtests.cjs`: passed. Includes 100 slots, server-advertised capacity, rename validation/cancel/failed-refresh acknowledgment, full IDs and signed/missing/tied performance sorting.
- `node tests/check-queue.cjs`: passed.
- `node tests/check-result-artifacts.cjs`: passed.
- `node tests/check-backtest-runs.cjs`: passed.
- `node docs/architecture-guide/check.cjs`: passed.
- Root's browser preview used 100 fictional records per list. At 1440×1000 the queue height was 560 px and library height was 480 px. At 390×844 the page had no horizontal overflow. Both lists remained bounded. Inline Rename focused its input and stayed within the viewport. Focusing the queue and pressing PageDown scrolled it by 480 px. Preview screenshots are kept under ignored `tmp/library-ui-preview/`.

The independent smart-commit audit found a rename keyboard guard regression and
two root-level preview screenshots. The guard now requires an active matching
rename input. Regression checks cover ordinary Enter/Escape events and rename
input Save/Cancel keys. The screenshots were moved into ignored preview storage.

The ordinary range check needs generated local output. This checkout has no
`website/local/index.html`; no real-cache build was requested for this slice. No live data,
installed user stores, downloads, deployment or snapshot refresh is part of this
work. Unrelated snapshot and market-scope files stay excluded.
