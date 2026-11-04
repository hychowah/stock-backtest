# CB-19G qualification summary

CB-19G selected compiled Numba with two workers × two numerical threads.
Original remains the application default. The final source passed complete
financial and recovery qualification through the normal `Selectable` router. No
deployment, installed restart, live cache write or download occurred. The source
archives, logs and checkpoint copies were removed under the
[records policy](../../../docs/records-policy.md). See the
[parallel backtest summary](../../../docs/plans/parallel-backtest/master-plan.md)
for the final outcome.

## Backend decision

Ten completed observations matched current Original exactly: 24 trials, 240
periods, 12,000 holdings, zero differences at the unchanged `1e-12` tolerance.
The times are calculation-adapter clocks on native Windows.

| Layout | Compiled Numba median seconds | Rust median seconds |
|---|---:|---:|
| 2×2 | 117.43 | 123.55 |
| 4×1 | 122.02 | 125.46 |

Numba won on the final source, so the normal engine needs no Rust capability.
The earlier CB-19F Rust advantage applied to its own source. `profiles-decision.json`
keeps the order, resources and rationale.

## Final normal application

`final-comparison.json` and `final-qualification.json` bind the final source,
the financial, report and plan identity, and the counters. All four successful
outputs agree with current Original at zero error.

| Case | Seconds | Outcome |
|---|---:|---|
| Original, prepared books | 7.60 | Warm reference; 240 books reused |
| Fresh experimental request | 120.69 | 24 trials calculated, two workers |
| New runtime, all trials saved | 51.41 | 24 recovered, none calculated |
| Qualified interruption | 100.33 | Closed after three committed trials |
| Partial recovery | 123.27 | Three recovered, 21 calculated |

Full recovery still pays startup, freshness validation, replay and delivery.
Zero numerical work is not zero latency. No ratio against Original's warm
replay is claimed.

## Preparation

The input copy took 240.0 seconds and initial preparation 885.6 seconds. Final
selected preparation took 38.8 seconds. These are separate from request times.
The report Through date stayed 20 October 2026. The copier used about 5.2 GB of
charged memory. The 256 MiB readiness default covers cold private worker samples
near 152.5 MB; it is not a full-run memory limit.
