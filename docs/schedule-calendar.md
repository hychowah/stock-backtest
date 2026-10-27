# Saved-session schedule calendar

The source can plan fixed and random dates for 1–104 calendar weeks or 1–24
calendar months. `scripts/schedule_calendar.py` owns these rules. It uses only
the Python standard library. It reads no files and calculates no portfolios.

The website and financial-facing planners still accept 1, 3, 6, 12 and 24 months.
This change adds no website control, weekly result label or execution route.
It does not update the installed server. SQL selection and financial rules
remain in their existing owners.

## Configuration version 1

```json
{
  "version": 1,
  "start": "2020-01-31",
  "end": "2021-12-31",
  "interval": {"unit": "week", "count": 2}
}
```

`decode_configuration(value)` accepts exactly these fields. It returns an
immutable `Configuration` with an immutable `Interval`. `to_dict()` returns
the canonical representation. The configuration version does not describe a
database schema, financial policy or ResultArtifacts format.

Units are exactly `week` and `month`. Week counts are integers from 1 through
104. Month counts are integers from 1 through 24. Booleans, floats, strings and
null counts fail. Unknown fields, aliases, unsupported versions and combined
`months`/`interval` forms fail. Dates must use `YYYY-MM-DD`. Start must be on or
after 1996-01-01 and strictly before end. Invalid inputs raise `ValueError`.

`legacy_configuration({"start": ..., "end": ..., "months": ...})` explicitly
maps an existing request to version 1 with `unit="month"`. It accepts only
1, 3, 6, 12 and 24. An omitted `months` means 12. An explicit null fails.
Intermediate counts require the versioned representation. The decoder rejects
new fields in a legacy request, even when both representations seem equivalent.
Conversion creates an in-memory value. It never rewrites stored records.

## Calendar API

Construct `SessionCalendar(sessions)` from increasing, unique `datetime.date`
objects. The sequence must be nonempty. Strings, datetime objects, duplicate
sessions and descending sessions fail with `ValueError`. The caller supplies
the sessions. The calendar does not infer exchange holidays or repair gaps.

The public operations are:

| Operation | Return value |
|---|---|
| `window(start, end)` | `(first, final)` as date objects |
| `fixed(configuration)` | A list of `(entry, exit)` date pairs |
| `sample(configuration, trials, seed)` | A calendar-only plan, described below |
| `explicit(dates, start, end)` | `(first, final, periods)` as date objects and date pairs |

`fixed` and `sample` accept a decoded configuration or its canonical dictionary.
`explicit` accepts an ordered sequence of canonical date strings. It has no
interval argument. Optional `checkpoint=` callbacks on fixed, sample and
explicit operations let adapters apply cancellation at each target, random
draw and explicit trade. Callback exceptions propagate. Resource ownership
and cleanup remain the caller's responsibility.

The common start is the first saved session on or after start. The final mark
is the last saved session on or before the inclusive end. End must not be after
the last saved session. At least two sessions must exist in the requested
window. The first must be strictly before the final mark. Unavailable windows
raise `ValueError`, including windows before the first saved session or windows
that contain only one session.

Every nominal target uses the original requested start. A week is seven
calendar days. A weekly target adds a whole multiple of `7 * count` days.
A monthly target adds whole months and clamps the original day to the last
day of the destination month. A February clamp does not change later targets.
104 weeks and 24 months remain different intervals.

Fixed targets roll forward to saved sessions. Distinct rolled entries strictly
before the final mark remain. Several targets can roll to one entry in a sparse
calendar. Duplicate entries merge. Each entry exits at the next entry. The last
entry exits at the final mark.

Random blocks use nominal boundaries before rolling. Each block is half-open:
`[left, right)`. The final block is clipped at the final mark, which is never a
sampled entry. Nonempty final partial blocks remain. Empty blocks are skipped
and consume no random draw. Each retained block contains its own ascending
saved sessions. Sampling uses `random.Random(seed).choice`, in trial-major then
block-major order. Trials are integers from 1 through 100. Seed is an explicit
integer from 0 through 4294967295. Null and boolean seeds fail. The financial
adapter still generates a fresh seed when its existing seed argument is omitted.

The calendar plan contains `configuration`, `seed`, `requested`, `window_start`,
`window_end`, `blocks` and `samples`. Each block has `start`, `end` and
`available`. Dates in the plan are strings. Samples retain trial order. This
plan is a calendar handoff, not a website result or durable user-record format.

Explicit trades must be increasing, unique saved sessions within the common
window and strictly before final. At least one trade is required. They need
not match fixed targets or random blocks. Each trade exits at the next trade,
and the last trade exits at final. Validation resolves the window directly.
It does not reconstruct a nominal schedule.

## Monthly compatibility and freshness

`schedules.schedule` and `robustness.plan` adapt their existing monthly requests
to the calendar. Their monthly envelopes, defaults and sampled draw order stay
the same. In particular, random configurations retain `months`, `options`,
the original requested bounds and every complete sample. `schedules.dated_periods`
still validates the legacy monthly argument before independent explicit-date
validation. Jobs, queues, saved results and batch workers keep their interfaces.

Weekly calendar dates can be supplied to the existing explicit-date evaluator.
That evaluator still returns legacy monthly metadata, including its default
`months=12`. CB-09 shares its portfolio reducer with an offline numerical
diagnostic. The separate [financial result contract](portfolio-results.md)
keeps complete holdings and financial fields without adding a version to
existing application payloads. This verifies date/financial separation. It
adds no weekly presentation or website control.

The daily-cache engine fingerprint includes `schedule_calendar.py` and the
CB-09 `portfolio_results.py` reducer. Its existing
capture and generation validators include the same dependency. A changed source
requires ordinary offline preparation. There is no new identity mechanism or
database schema version. Private source exports already include Python modules.
The existing policy identity hashes the complete `schedules.py` source. Its
hash changes with these adapters even though financial expressions do not.
Existing numerical artifacts therefore need ordinary offline preparation and
export. Artifact, temporal and factor versions stay unchanged.

`tests/fixtures/schedule-calendar-legacy-v1.json` contains compact expectations
derived from the unchanged pre-change capture. It records the capture's base
commit and SHA256. The matrix has four anchors, five legacy month counts,
three seeds and 24 trials per case. Canonical JSON hashes check all fixed pairs,
all complete configuration fields and every sampled date. Explicit 24-month
examples make representative dates readable. The synthetic calendar includes
weekends, holidays, leap dates, month ends and a final partial block.

Run `tests/test_schedule_calendar.py` for independent calendar rules. Run
`tests/test_schedule_calendar_compat.py` for exact old monthly expectations.
The schedule, robustness and book-batch suites check financial evaluation,
reuse, interruption and completed-trial recovery. Native and WSL qualification
results belong to the CB-08 phase record. This document makes no new speed or
production-capacity claim.


CB-11's explicit runtime also uses `robustness.plan` over the immutable sessions
in its private SQL workspace. It adds no calendar planner or website control.
The recorded-plan, default-seed, explicit-date and result-envelope contracts stay
the same. Runtime use retains financial ownership across all reused jobs.
