# Precomputed sheets: reuse entry work across random seeds

Status: complete

## Outcome

Historical entry work is saved once per entry session and pool. A new random
seed reuses those sheets even when holding exits differ. The run filters actual
entry before exit, selects stocks, then closes only the selected holdings.
Holdings, returns, statuses and stored rounding remain identical. Saved library
and queue records open unchanged. Formula edits require no sheet rebuild.

## Key decisions

1. **Entry/pool sheets.** Historical sheets contain entry information only,
   with no exit or future return. Latest keeps its separate listed-company and
   exact-session policy. Historical entries retain four calendar days of slack.
2. **Compact layout.** Each stock occupies one row with its existing metric
   pairs and filter values. Missing values remain unavailable. Stored owner
   numbers keep REAL rounding and zero normalization; typed facts and formula
   outputs retain signed zero. The disposable cache rebuilds without a migration
   reader or duplicate layout.
3. **Exact freshness.** A changed research content identity or book identity
   drops every sheet. Unchanged identities retain them. Change-day reuse and
   its supporting code are deleted. Rounding tolerances and approximate reuse
   were rejected because exact results are required.
4. **Coverage and continuation.** Unified Update data and 07:00 Hong Kong
   maintenance precompute historical `cached` sheets for every saved SPY session
   from `rules.FIRST_DAY` through the latest session. The `sheets` stage follows
   website publication and precedes verification. Each sheet and its completion
   marker commit together, including empty sheets. Interruption retains prior
   commits; Continue builds only missing completions. Up to eight read-only
   workers calculate, and only the parent writes.
5. **One builder, on demand.** Legacy and missing sheets use the same builder
   on demand. Plain startup, CLI preparation and ordinary runs do not precompute
   full history. Historical coverage adds no readiness gate. The website embeds
   latest only, so historical precomputation follows its publication.

## Measured results

The private WSL bench used a copy of the runtime's raw cache. The Original
new-seed test had 24 quarterly trials over 2013–2026, the cached pool, ranks 1–30, three
built-in conditions and one custom variable.

- Before entry sheets, the test took 311.9 s (about 312 s). Entry sheets built
  on demand reduced it to 163.5 s. With history precomputed, two new seeds took
  92.8 s and 78.2 s, with zero books built.
- Eight workers precomputed 6,526 missing sheets in 615 s. The completed store
  held 7,752 historical sessions through 2026-10-21 and occupied 5.9 GB.
- Whole-result digests matched for the random test, quarterly fixed dates
  2013–2018, latest and the development-check run. `scripts/check.py` found zero
  differences. Checks used exact results, not a rounding tolerance for reuse.

The Windows runtime's first update on 2026-11-08 took 78.3 minutes in total.
Its sheets stage took 24.8 minutes for 7,764 sheets. The store occupied 5.9 GB.
This is a separate native update measurement, not a new-seed backtest timing.
These observed timings are not guarantees.

## Where the current contracts live

- [Research and daily storage](../../research-workflow.md#prepare-once), for
  identities, compact rows, freshness and selected-only closes.
- [Unified updates](../../research-workflow.md#data-control-panel), for the
  sheets stage, ownership, progress and continuation.
- [Architecture guide](../../architecture-guide/dist/index.html), for the
  user-visible flow and cache behavior.
- [Feature contracts](../../../AGENTS.md#feature-contracts), for financial,
  worker, freshness, cancellation and durable-record invariants.

## Known limits

- A changed generation requires a full historical rebuild. This can occupy
  cache ownership and disk for a long time.
- Windows runtime duration of a new-seed test has not been measured.
- Strategy formulas still evaluate at run time. Sheets do not cache formula
  results or establish full-universe price coverage.
