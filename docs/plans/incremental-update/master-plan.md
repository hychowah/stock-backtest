# Incremental updates

Status: complete

## Outcome

A data update no longer rebuilds everything. Results stay exactly equal to a
full rebuild.

- Before: every research build was a full build. Its new identity dropped every
  stored sheet, and the sheets stage rebuilt all of them. On 2026-11-09 the
  Windows update with US and Hong Kong ran over 3.5 hours in that stage without
  finishing.
- Now: research updates changed rows in place and records which companies and
  shared inputs changed. Daily preparation repairs only the affected company
  rows of stored sheets. Precompute fills new sessions.

## Decisions

- Foreign price lookups check the session with an indexed `EXISTS` probe. The
  old `IN (subquery)` rebuilt the full calendar on every lookup. On real Hong
  Kong data, sheets became 14–21 times faster (9.9–17.0 s to 0.47–1.04 s), with
  identical rows.
- The research change list (`metadata.changes`) holds one base identity. It
  also holds each company's first changed price day, its old and new known
  dates for statements and annual facts, and company-level changes. Shared
  changes are sessions per market, the Treasury day and FX per currency.
- A company-level change means added, removed, or a changed market or
  currency. Name, exchange, sector and listed changes do not touch historical
  sheets. Latest sheets are always rebuilt.
- `books.affected_entries` maps changes to entry dates. Prices, local sessions
  and FX reach entries four days earlier, because entries roll forward. Reports
  apply after their known date. US Treasury applies on or after its day;
  foreign Treasury strictly after.
- Any US statement change refreshes candidate ranks and counts from statements
  only. It also drops affected legacy pools, which rebuild on demand.
- Each repaired sheet commits alone. The daily binding is written last, so
  readers refuse a partial repair and a retry repeats it. A changed book code
  or a research base that does not match resets the cache, as before.
- `research.prepare` first opens the database read-write, so SQLite recovers a
  transaction that a hard kill interrupted.

## Evidence

Bench with real US and Hong Kong files, on 16 cores. Old files were from
2026-10-21; the new files were the runtime copy from 2026-11-09.

- Full builds with the new code equal main's builds in every table.
- Updating from the old files to the new equals a full build exactly: every
  research table and every sheet row.
- That update took 323 s for research, about 78 s to repair 7,752 US sheets
  and 401 s to fill 7,642 new sheets. A full build of the new files took 430 s
  and 977 s. The two builds ran at the same time.

## Limits

- Research still reads and hashes every raw file, and still parses each changed
  price file. A normal morning changes almost every price file.
- Native Windows checks did not run, because WSL interop failed on 2026-11-09.

Contracts live in `AGENTS.md`, `docs/research-workflow.md` and the architecture
guide.
