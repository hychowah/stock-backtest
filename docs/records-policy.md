# Records policy

Git history is the activity log. Documents hold only what a reader needs to
understand the system or to continue the work. Write each fact in one place.
This policy applies to every initiative under `docs/plans/`.

## Where each record goes

| Record | Home | Rule |
| --- | --- | --- |
| Standing rules and permissions | `AGENTS.md` | Edit in place. Add no dates, no "resumes" paragraphs and no phase chronology. Each initiative has one status section. Replace it. Never append to it. |
| System contract: catalog, language, formats, compatibility | `docs/plans/<initiative>/*.md` | Edit in place so it describes the current system. State each format version change. Limit: 3,000 words. |
| Decision | `docs/plans/<initiative>/phases/phase-NN/decisions/NNNN-title.md` | One decision per file. Limit: 700 words. Give the context, the options, the choice, the protected contracts and the consequences. After commit, change it only to mark it superseded by a later number. |
| Phase record | `docs/plans/<initiative>/phases/phase-NN/README.md` | One file per phase. Limit: 900 words. Give the scope, the entry commit, each exit with its evidence, the known limits, links to decisions and a **Next** section. Overwrite **Next** at each pause or handoff. |
| Slice evidence | Commit message body | Limit: 30 lines. Give the scope, the checks run with counts, the source commit, deviations, each audit finding with its disposition, and one line per agent with its model and effort. |
| Logs, timings, failed attempts | Ignored `tmp/` only | Do not commit them. If a claim depends on a log, quote the number and its settings in the commit message. |

## Agent reports

A planner's design, a writer's report and an auditor's findings are printed in
the session. They are not filed. The orchestrator moves each decision from a
design into a decision record. It moves findings and dispositions into the
commit message. It passes the printed design to the writer in the brief.

## Do not create

- A separate execution plan, handoff, addendum, clarification or audit file.
- A per-slice file of any kind.
- A link from a tracked record to `tmp/` or `/tmp/`. Nobody else can open it.

An addendum that changes a decision becomes a new decision record. A plan that
changes belongs in the phase README.

## Enforcement

Run `python3 tests/check_records.py` in the WSL source checkout before every
commit. Do not commit if it fails. The check applies the limits above and
rejects files outside the table. It also rejects broken relative links.

`tests/records_baseline.txt` lists the files that existed when this policy began.
Those files are exempt. Shorten or delete them as you work. Do not extend them
with new process records, and never add an entry to the baseline.
