# Nightly data refresh

Status: complete

## Outcome

Source implementation starts from `ceb6cd4`. Qualification below covers source
behavior with private fixtures. Deployment and live-data qualification are
separate operations.

The supervisor schedules maintenance at 07:00 Hong Kong time. It stages any
changed main revision, gracefully stops its child, completes source publication,
and starts the installed application with an explicit refresh request. The
replacement refreshes FMP inputs and runs ordinary preparation before admitting
requests or queue work. Data refresh runs with no new commit too. A missed
scheduled minute waits until the next day; launch and resume do not catch up.

The same operation is available as Refresh data + website on the local data
panel. It refreshes existing companies and new annual reports. It adds newly
discovered or newly eligible companies, preserves historical companies, and
retains incomplete additions for retry. Recent prices and yields are rechecked.
Known unfinished windows resume. Checked empty histories reuse old windows.
A changed adjusted price requires a consistent complete saved history, including
newly returned dates and unchanged recent values, before publication. Unchanged assets keep their bytes and timestamps. Annual variants
and their duplicate counts survive refresh without accumulating identical
copies each night. Stored results and financial policies retain their behavior.

## Key decisions

1. Schedule: 07:00 Hong Kong time, independent of the host timezone. Missed
   nights wait for the next scheduled date. The supervisor must be running.
2. Coverage: maintain saved-price stocks and add new listings or companies that
   first acquire eligible financials. New price histories start in 1995. Annual
   key metrics refresh across the universe; statement inputs refresh for managed
   stocks. Preserve existing fiscal-date valuations and annual conflict rules.
3. Publication: reuse bounded FMP transport, validation, atomic asset writes,
   content-bound receipts, source ownership and financial-cache ownership.
   Scheduled refresh intent uses the child environment; older main revisions
   can ignore it and still start. Worker cancellation and repeated startup interrupts retain ownership through
   worker completion. No calculation route downloads data.
4. Failures: retain completed downloads. One failed company or history does not
   stop unrelated assets. Publication I/O failure stops further downloads. A partial provider failure prepares
   valid saved inputs and remains visible. Preparation failure prevents service
   startup. Last refresh success and actual latest SPY session remain separate.
5. Precomputed sheets: the nightly scheduler owns no sheet logic. That later
   initiative must extend ordinary preparation to build missing and affected
   sheets from the existing fact changes, including historical changes.

## Current contracts

The [data workflow](../../research-workflow.md#data-control-panel) owns refresh
behavior and status. [Workspace commands](../../workspaces.md) own supervisor
and publication behavior. [Local data](../../../data/README.md) describes the
pending-addition file. The [architecture guide](../../architecture-guide/dist/index.html)
explains the current source and its limits.

## Validation and limits

The WSL fast tier passed all 90 files. The heavy tier passed its one
Original long-window file. The new refresh file passed 27 tests,
including real private research/daily preparation and selection before and after
report eligibility. Native Windows Python passed refresh, data-manager,
financial-input, automatic-update, startup, deployment and cache-access checks
with private fixtures. Architecture-guide checks, records checks and diff
whitespace checks passed.

No live FMP request, live-cache operation, installed application restart,
or deployment was performed. Maintenance duration and real-provider
coverage remain unmeasured. Annual requests keep the existing 40-report limit.
A recent overlap does not audit arbitrary corrections across old history.
Browser behavior has Node checks; no interactive browser check was performed.
Deployment and real-data qualification remain separate authorized work.
