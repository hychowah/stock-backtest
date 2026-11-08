# Unified data update

Status: complete

## Outcome and scope

One **Update data** action fills missing inputs, checks newer reports and prices,
and prepares the data and website automatically. The main card shows elapsed
time, estimated remaining time and overall completion. Details holds technical
messages. More options supplies selected stocks and older history. Saved results,
queue records, financial formulas and old fiscal-date valuations retain their
policies and formats.

The user authorized source implementation and a feature-branch commit. Work
stays on `feature/unified-data-update` in its linked worktree, based on
`aa1516bdb9e268b0fc8fc91c21ebea37246b0d7f`. Main integration, push, deployment,
installed restart, live downloads and real-cache qualification are excluded.

## Agreed smaller design

The existing financial cache ownership is the only owner. It protects inputs
and one atomic `data/data-refresh.json` status record. This record contains
scope, target date, state, current stage, counts, a successful stage prefix,
verified active seconds, pending additions, last success and that successful
scope's stage durations. There is no update database, separate lease or per-unit
work record.

Continue restores saved coverage and date and reruns unfinished stages. An
unfinished annual-report stage is checked again: existing receipts cannot prove
that a provider has no newer report. A completed stage can be reused while its
ordinary content-bound asset receipts still apply. A preparation-only continuation
makes no download request. Stop retains cache ownership through worker cleanup.
Readiness is separate from update success. Reloads retain server-owned progress.
A saved running state is interrupted only when ownership is free; a foreign busy
cache leaves status unconfirmed because its owner could be a backtest.

Estimates use the matching-scope stage durations of the last successful update
and live counts in the current stage. They include preparation. Unknown stays
explicit, with elapsed time and verified counts visible. There is no throughput
or retry/cooldown estimator. Completion reaches 100 only when ready and successful.

Financial appends end with a newline and flush their contents. Only an incomplete,
unparseable tail is trimmed before owned appends or preparation. A complete valid
JSON tail without a newline stays. Earlier bytes are not rewritten by tail cleanup.
Read-only inspectors keep the ordinary reader. Main's existing complete-record
repair and archive behavior stays. No append journal or new quarantine is added.

Website rebuilds durably invalidate the old completion marker before changing
output, flush outputs and publish completion last. The builder runs in process:
a child using its dead parent's cache ownership could otherwise publish unowned.
Cache replacement retains file fsync before rename and POSIX directory fsync.

## Dispositions from design review

- Removed the pre-release SQLite store, extra operation lease and per-unit proofs.
- Removed the work-class throughput and retry/cooldown models.
- Removed append intent, journal recovery and newly added quarantine logic.
- Removed output hashes and per-file atomic website publication; retained durable
  marker invalidation, output flushing and the in-process build.
- Removed the broad process-kill matrix. HEAVY is unchanged.
- Kept focused behavior coverage for tail cleanup, valid tails, marker failure,
  continuation, stop, known/unknown estimates and unconfirmed ownership.

These removals discard only unreleased source. They require no data migration.
No addition outside this agreed design is intended.

## Qualification and limits

The source implementation is complete. The fast tier, existing heavy tier,
seven affected native Windows suites, records check and guide check pass.
Private browser fixtures verify desktop and narrow-screen layout, elapsed time,
remaining time, completion, reloads and keyboard access to Details. Independent
audit findings were fixed and rechecked. Exact counts and dispositions are in the
feature commit message. No addition outside the agreed design remains.

Current contracts are in the [data workflow](../../research-workflow.md#data-control-panel),
[workspace rules](../../workspaces.md), [local data](../../../data/README.md) and
[architecture guide](../../architecture-guide/dist/index.html). Physical power-cut
behavior and real-provider coverage remain unverified. Python provides no portable
Windows directory-fsync equivalent. Estimates are approximate; a first run can
lack an overall estimate while still showing step counts and running time.
