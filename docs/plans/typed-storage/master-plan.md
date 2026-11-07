# Typed storage: one fact store and faster backtests

Status: complete

## Outcome

Research preparation writes typed facts only, and one book store in
`schedules.sqlite` holds the latest and the dated books. Books and formulas
read the facts through one daily connection. The January mode is gone; a
January study is a 12-month dated schedule. Latest and dated returns,
holdings, labels, reasons and formula values stayed identical through every
phase. Saved library and queue records open unchanged and never recalculate.

Bench copy of the runtime's raw cache, in WSL. The user test: 24 quarterly
random-date trials, 2013–2026, 1,344 periods, ranks 1–30, cached pool, three
built-in conditions and one custom variable.

| Measure | main a7b13ac | End state, P5 50125bf |
|---|---|---|
| Cold research and daily build | 1,363 s | 176 s (research 172 s), under user load |
| User test, books computed | 558 s | 326.6 s, under user load |
| User test, books saved | 211 s | 62.7 s (47 ms per date), under user load |
| `research.sqlite` | 33.7 GB | 1.26 GB |
| Daily cache | about 27 GB | 3.2 MB before books; 4.47 GB with about 1,380 books |

A quiet-machine rerun may update the end-state timings. With books saved, the
time per date (P5 profile) is formulas 8.5 ms, `book_store.lanes` 7.8 ms
(mostly SQLite), Executor loops 6.6 ms, scope rows 4.1 ms, stored conditions
3.9 ms, the lane rule 3.0 ms and writing 3.0 ms.

Every phase kept the four whole-result digests equal (the user test,
quarterly fixed dates 2013–2018, latest, and the development-check run) and
the development check at 0 differences. The development check is the 12-month
fixed schedule from 1996-01-01 to 2026-10-20, legacy pool, `ev_ebitda` ranks
1–50 and the default size floors.

## Key decisions

- **D1 = delete.** The JSON observation tables and the reference formula
  evaluator are deleted. Explanations keep values, dates, reasons, the source
  file and its digest; random-date results keep values and reasons, not step
  traces. Readers compare an accepted raw-file signature. No parallel trials;
  up to 8 book workers.
- **D2 superseded.** No publication journal: research replaces a temporary
  file atomically; a failure keeps the previous database.
- **January books removed** (user: "i agree with 1-4"). A January test is a
  12-month dated schedule from 1 January. A January request is refused at
  `/mode`, never converted. `revalue.calculate` stays as the bench
  development check, `scripts/check.py`. `results/summary-exits.txt`,
  `results/baseline-history/`, `results/legacy/` and `results/stops/` are a
  frozen record. No January screener mode; latest stays.
- **January follow-ups** (user: "use your recommendation"). Every rebuild is
  a full rebuild. The data panel's default download covers the cached-price
  companies through the latest day. `--collect-report` and the stop tools are
  deleted. Saved January results (versions 1–2) open in the dated view and are
  never rewritten. A stored book row records only how a holding exited:
  `Scheduled exit`, `Last available price` or `Bankruptcy`; the run shows
  `Marked to date` when its last book ends on a mark. `rules.BANKRUPT` holds
  `(symbol, day of loss)`. `rules.FIRST_DAY` (1996-01-01) is the first usable
  day, and `books.Screen` requires a saved SPY session from it.
- **One value rule** (user: "agree"). `facts.observe` gives each saved day one
  value: a conflicting, non-USD or invalid row gives no value and a reason.
  No `light` series. One denial vocabulary, `books.REASONS`.
- **One book store.** Latest and dated books share one writer, tables and
  book-id space in `schedules.sqlite` (`backtest/inputs/book_store.py`). The
  latest book is its open book. Research holds facts only.
- **One identity per code role.** `research.code_sources(role)`: the research
  identity binds fact-row code, the book identity binds book code, readers
  bind nothing.
- **Kept books and the in-place book cache** (user: "1. A 2. Yes"). The
  change-day rule in `books.py`, next to `FORWARD_REACH`, keeps every stored
  dated book that a fact change cannot reach. The book cache updates in place
  in one transaction: delete the dropped books and the old open book, rebind,
  write the new open book. Research stays a full rebuild.
- **`owner_scope.book` is a label.** New results record the real book id; a
  book id names a book only while the cache keeps it, and SQLite can reuse a
  deleted id. Saved results keep theirs and are never rewritten.
- **No numeric targets** (user: "stop when gain become marginal"). Each speed
  phase removed the largest measured cost; the user stopped after P5.
- **Compact book rows not done** (user). They would cut first-run book writes
  (P4c: 145 s of a 299 s run, about 84 million rows, 86% in `book_filters`),
  but they change the book store format, `screening.select`'s SQL and the
  daily version, and they help first runs only. The user's reruns and the
  planned reinforcement-learning loop reuse saved books.

## Where the current contracts live

`AGENTS.md` (Research database, Website screening, Custom dated schedules,
Custom variables); `docs/research-workflow.md` (the current research schema
and daily cache versions, code identities, kept books, measured performance
and the development check); `docs/schedule-calendar.md`; `data/README.md`;
and the architecture guide.

## Known limits

- Compact book rows are not done; book writes dominate a first run.
- A stored REAL lane cannot hold -0.0, so a -0.0 owner value reads as 0.0. No
  formula output changed on the bench copy.
- Explained owner lanes at latest roots show their report dates, as dated
  roots do.
- Coverage discovery covers only the open book's pools.
- Automatic nightly downloads are an open future decision. They would end the
  explicit-button rule and must run after the 01:00 supervisor or in its step.
- The native Windows checks (attach, file replace, spawned workers) are
  pending.
- The first deployment rebuilds research and recomputes every saved book once.
- A new company's first price day widens the change day, so a nightly update
  can drop more books than the new prices reach.
- Can wait: variable coverage checks one scope three times;
  `cache_assets.checked_series` has one caller; `facts.encoded` duplicates
  `definitions.canonical`; the prepared-input coverage tool keeps a
  `histories=None` path; a run compiles its formula program four times.
