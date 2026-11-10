# CB-19F complete-request comparison

This summary compares Original with the experimental engine on complete
requests. The raw observation archives, source declarations and failure
payloads were removed. The retained JSON files hold the decision, the validators
and the timing groups.

## Settings

- Long request: 24 seed-42 annual trials from 4 January 2010 through
  31 December 2019. Complete qualified cached pool, ranks 1–50, current
  EV/EBITDA, filter-first, no threshold. 240 periods and 12,000 holdings.
- Short request: eight trials from 2 January 2018 through 31 December 2020,
  with 24 periods and 1,200 holdings.
- Native Windows, 16 logical CPUs, no job CPU or memory quota. Host caches were
  not flushed.
- Times start before the calculation adapter and end after complete holdings
  and confirmed closure. They exclude input materialization (305.1 seconds) and
  ordinary preparation (406.8 seconds).

## Results

Twenty successful observations matched their Original references exactly at the
existing `1e-12` tolerance.

| Long request, fresh application | Median seconds |
|---|---:|
| Original 1×1 | 71.0 |
| Compiled Numba 2×2 | 59.8 |
| Rust 2×2 | 52.0 |
| Compiled Numba 4×1 | 71.5 |

The 12.66% Rust saving over Numba came from fresh-worker initialization and
build reuse. Warm diagnostics were nearly equal. CB-19F proposed Rust 2×2 for
CB-19G. CB-19G then selected compiled Numba on its final source; see the
[qualification summary](../parallel-qualification-2026-11-01/README.md).

One long Rust 2×2 run committed all 24 trials but failed statistics
publication with a Windows `PermissionError`. It is excluded from the
comparison. These results do not qualify installed-runtime latency.

## Files

- `decision.json`: the CB-19F decision and the gates it set for CB-19G.
- `long-comparison.json` and `short-comparison.json`: validators and timing
  groups.
- `long-workload.json`: the long request settings.
