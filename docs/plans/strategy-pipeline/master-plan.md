# Strategy pipeline

Status: complete

Closed on 2026-11-10.

## Outcome

A strategy is a linear chain of blocks. A fixed Universe block (market and pool)
comes first. Filter and Rank blocks follow in any order. The user adds, removes and
moves blocks on the strategy page. The old "filter first" and "rank first" modes
are now ordinary chains.

- P1 (a848646): one step loop (`selection.execute`) runs the chain.
  strategy-intent/capture version 2 records it.
- P2 (c50d868): the strategy page is a block builder.
- P3: each selected holding shows a step trail. Latest picks run any chain.

## Decisions

- **Universe and blocks.** Universe holds market and pool. Size floors, sector,
  exchange and the old yield/multiple limits are ordinary Filter blocks, because
  the old `rank_first` applied them after ranking.
- **Filters.** A Filter takes any source with `lt`, `gt`, `le`, `ge` or `eq`.
  Flat requests keep strict `lt`/`gt`.
- **Ranks.** A Rank takes any source, highest or lowest, and an inclusive range.
  "Top N" means 1–N. A chain needs at least one Rank and holds at most 50 blocks.
  The last Rank sets the final order and ranks, and later Filters add no
  replacements.
- **Old formats.** Flat requests keep the SQL adapter (`screening.select`).
  capture/1 translates in memory to the equivalent chain. Copying an old result
  builds that chain. A held queue edit keeps its original payload unless it changes.
- **Formulas.** Formula values are per company: their statistics are annual and
  within one company. So each formula runs once per row, only for rows still alive
  at its first step. This is exact. It made rank-first runs with a custom variable
  about 3.7 times faster.
- **Exact equivalence.** A minimum of zero adds no block, and a metric ranks on its
  yield lane alone. Admitted cap, EV and EBITDA are positive, so ranked yields are
  positive. The yield and multiple of a pair are both present or both absent.
- **Evidence.** Each selected holding stores one rank or null per step. Values come
  from its lanes. Field steps use the holding's own fields. A chain formula
  reference also records the value its step used.
- **Latest picks.** Chains the flat options can express keep the offline browser
  screen. Every other chain runs through Original on the local service.
- **Logging.** `backtest.run` logs `market`, `ranking_source_kind` and `step_count`.
- **No rebuild.** No edits to `books.py`, `metrics.py`, `rules.py`, `book_store.py`
  or `facts.py`, so cache identities did not change.

## Evidence

Bench `~/bench` used the real US and HK files. The baseline was main `89fe1d6`.
Inputs and seeds were the same.

- **Five old-format cases** gave identical trial, period and holding records in
  P1, P2 and P3. Only the code fingerprints in scope records differ. The cases:
  - the user's 24-trial test with a custom variable
  - rank-first
  - ranks 20–40
  - built-in only
  - a seeded HK run
- **Timings** (main → P3):

  | Case | Main | P3 |
  |---|---|---|
  | User test | 47.9 s | 46.3 s |
  | Rank-first | 99.5 s | 26.9 s |
  | Ranks 20–40 | 42.3 s | 45.5 s |
  | Built-in only | 28.4 s | 30.1 s |
  | HK | 21.2 s | 22.0 s |

  The P3 run shared the machine with a test suite.
- **Default chain.** Through intent version 2, the default-shape chain matched the
  capture/1 baseline in all 41,664 period and holding records. It took 29.9 s
  against 28.4 s, with 69 MB of evidence against 67 MB.
- **Latest picks.** Server latest chains equalled `screening.latest` for US and HK,
  default and with P/B < 1.5: 50 picks each, 0.15–1.3 s.
- **Reviews.** Independent reviews of P1, P2 and P3 found no blocker. Their findings
  were fixed or recorded in the commit messages.

## Limits

- The step trail exists only for results made after P3. Older results say it was
  not recorded.
- The page, latest routing and step trail were checked with node harnesses and
  headless Chromium screenshots in WSL. No native Windows browser or Tailscale
  preview was used, because WSL interop was unavailable.

Contracts live in `AGENTS.md` (Selection order, Metrics and threshold filters),
`docs/evidence-views.md` and the architecture guide.
