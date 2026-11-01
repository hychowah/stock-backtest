# CB-19F complete-request comparison

Select Rust with compiled candidate assembly and a measured 2×2 starting layout
for CB-19G. Original remains default. The application default is unchanged until
G integrates and qualifies the selection. Read the
[decision and concrete G gates](../../../docs/plans/parallel-backtest/phases/CB-19F.decision.md).

The balanced R–C–C–R long-request observations are Rust 52.233278 seconds,
compiled Numba 59.770244, compiled Numba 59.271960 and Rust 51.735349.
Balanced medians are 51.984314 and 59.521102 seconds. The 12.66% saving comes
from fresh-worker initialization and verified build reuse. Warm diagnostics are
nearly equal. It is not a claim that Rust arithmetic is faster. The earlier
compiled 61.463091-second result remains in the evidence.

The long request uses 24 seed-42 annual trials from 4 January 2010 through
31 December 2019. It keeps the complete qualified cached pool and ranks 1–50.
All 240 periods and 12,000 holdings remain. Its 53,084,160-byte eager estimate
fits the unchanged 268,435,456-byte bound. The short request uses eight trials
from 2 January 2018 through 31 December 2020, with 24 periods and 1,200 holdings.
Both use current EV/EBITDA, filter-first and no threshold cohort reduction.

Twenty successful observations have complete ordered financial agreement with
their Original references. Maximum numeric difference is zero at the existing
1e-12 tolerance. Categories, nulls, ranks, dates, symbols and order stay exact.
The reference financial gzip files contain every financial field and holding.
Only explicit timing/execution telemetry is removed. Raw result hashes and
private complete-result paths remain in each observation.

Primary times start before the existing Candidate/Original adapter and end after
complete holdings and confirmed operation closure. They include ordinary status,
source/input checks, worker setup, calculation, checkpoint saving and delivery.
They exclude separate input materialization/preparation and final archival JSON
serialization. Initialized-runtime work and new-runtime checkpoint hits are
separate states. Original book reuse is separate again. Host caches are not
flushed. Native Windows observations do not qualify installed-runtime latency.

Current-source preparation used a fresh private materialization of completed
inputs2 with manifest hash
920453aba4fe10efb9dc6b81e189bf50ed711d6eb9d71e8b199a0610510cf819.
Materialization took 305.116744 seconds. Ordinary preparation took 406.796663
seconds. The canonical captured Through date and report hash stayed unchanged.
The new numerical generation is
e083abec0de70bfbf40a4ebf7863926caa48d3b00cdceaae675ec706857c67ec.
Historical CB-17 source, derived caches and measurements were not reused.
The 281-file measured source digest is
aa77911f5520ec06dede6c8bbfb8319ce2ded49b2af9f48466fea5daea910ad5,
based on E commit 675a29aad94fdd9fa1d833783bfccd43bbb845be plus exact F tools/tests.

The native process had 16 eligible logical CPUs without an observed job CPU or
memory quota. The 2×4 probe used eight lanes and showed no established gain over
2×2 raw variation. Four-worker serial readiness was slower. No historical
four-lane/four-worker/25%-CPU/2-GiB limit was imposed. Resources were sampled,
not guaranteed. Summed working sets include shared mappings. Actual scratch,
provisional artifacts, checkpoint bytes and configured reservations stay distinct.

One long Rust 2×2 operation committed all 24 trials but failed shared statistics
publication with PermissionError. It has no successful latency. Its owner and
native handles closed. Its full calculated payload separately agrees financially,
but is excluded from completed-comparison evidence. The valid payload and
complete stats.pending are consistent with a stats replacement failure. Exact
inner stack/Windows error code and external cause are unavailable. Rust causation
is unproven. All failed files and checkpoints remain. The fresh retry used a new
checkpoint. G must reproduce and qualify a shared publication repair.

Rust installation time was not measured. Qualification used an existing compiler.
G must supply normal optional compiler/build availability outside benchmark tmp
paths and retain Original without optional dependencies. G must also confirm
bounded concurrent startup and the backend/layout tradeoff on its final source.
This record does not close the program or authorize deployment or downloads.

Files:

- `decision.json`, `short-comparison.json`, `long-comparison.json` and
  `observations.json`: decision, full validators, raw timing groups and readable
  observation summaries. The full three-run compiled median differs from the
  explicitly labelled balanced two-run median.
- `*.json.gz`: exact raw observations, preparation/source declarations, final
  synthetic receipts, retained failures and complete reference financial payloads.
  Gzip timestamps are fixed to zero. Decode with standard-library gzip/JSON.
- `manifest.json`: content hashes and byte counts for this evidence bundle.
- `launch-history.json`: unstarted approval delay and repaired extraction-wrapper
  error, separated from financial latency and the failed operation.
