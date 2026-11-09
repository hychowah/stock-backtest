# US, Hong Kong and Japan backtests

Status: complete

Original and the website support one market per run: US, Hong Kong Main Board
and GEM, or Japan's Tokyo market and historical predecessors. The existing
research database, daily cache, evaluator and ownership model remain in use.

## Key decisions

1. New strategies use the broad cached-price pool. Recorded US legacy work and
   the independent reference keep their original meaning.
2. Monetary inputs, thresholds, holding returns and CAGR use USD. Quote and
   report currencies remain distinct. Annual money uses context-date FX;
   holding prices use their own observation-date FX. Foreign valuation combines
   converted components rather than consuming mixed-currency vendor EV.
3. Local sessions govern fixed and random schedules. Every market compares with
   SPY total return. Asian dates use the previous completed US close. Cash stays
   in USD at 0%; reference yields remain US Treasury yields.
4. US reporting keeps its 90-day lag. HK and Japan use reliable publication
   dates where available, otherwise four and three calendar months.
5. New formulas use catalog `/4` and policy `market-annual/1`, with definition
   syntax version 3 and the existing evaluator. Old catalogs and captures keep
   their meanings; foreign use requires explicit upgrade.
6. The development check fails on calculation differences using identical
   inputs. Frozen-report differences remain informational and never rewrite
   the historical record.

## Current contracts and limits

The [market rules](../../research-workflow.md#market-data-and-calculations)
describe inputs, currencies and preparation. The
[variable contract](../custom-variables/variable-design.md) describes formula
meaning. [Schedules](../../schedule-calendar.md) and
[portfolio results](../../portfolio-results.md) describe timing and returns.
The implementation commit holds validation evidence and review dispositions.

FMP remains the only provider. Incomplete listing history, later revisions,
zero-heavy fields and dividend-adjustment defects remain limitations. The
implementation adds no corporate-action repair or company certification system.
US real-data parity and private Windows checks passed. These checks do not
establish complete foreign-market coverage or installed-runtime readiness.
