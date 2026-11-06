# Records policy

Git history and commit messages are the activity log. Tracked documents hold
what a reader needs to understand the current system, or what the next session
needs to continue an active plan. Write each fact in one place.

## Three kinds of record

| Kind | Home | Lifetime |
| --- | --- | --- |
| Standing | `AGENTS.md`, `README.md`, `docs/*.md`, the architecture guide | Permanent. Edit in place. No dates, no phase chronology. |
| Plan workspace | `docs/plans/<initiative>/` while its status is `active` | Until close-out. |
| Scratch | Ignored `tmp/` | Never committed. |

`AGENTS.md` holds standing rules and permissions only. It holds no change log,
no "resumes" paragraphs and no feature description that another document owns.
Each standing document describes the current system and states each format
version change.

## Plan workspace

```
docs/plans/<initiative>/
  master-plan.md                  Status line, goal, phases, exits, Next. 3,000 words.
  <contract>.md                   Optional initiative contract. 3,000 words.
  phases/phase-NN/
    README.md                     Phase record. 900 words.
    decisions/NNNN-title.md       One decision. 700 words.
    working/                      Multi-session working notes.
```

- The first non-empty line after the `master-plan.md` title is `Status: active`
  or `Status: complete`.
- A phase README gives the scope, the entry commit, each exit with its evidence,
  the known limits, links to decisions and a **Next** section. Overwrite **Next**
  at each pause or handoff.
- A decision record gives the context, the options, the choice, the protected
  contracts and the consequences. After commit, change it only to mark it
  superseded by a later number.
- `working/` holds what a later session or another worktree needs to continue:
  designs, reviews, handoffs and slice notes. Use `.md` files of at most 3,000
  words and `.json` files of at most 64 KB. A phase skill that files `design.md`,
  `review.md` or `handoffs/*.md` writes them here. Replace a stale working file.
  Do not add attempt, retry, addendum or clarification copies.

## Close-out

When the last phase of an initiative is complete, close it out in the same
commit or the next one:

1. Move lasting knowledge to standing documents: contracts to `docs/`, rules to
   `AGENTS.md`.
2. Rewrite `master-plan.md` as a summary of at most 1,000 words: `Status:
   complete`, the outcome, key decisions with their numbers and settings, where
   the current contracts live, and the known limits. Anything not in the summary
   is lost after deletion.
3. Delete every phase README and every `working/` directory. Keep decision
   records that are still in force. Delete superseded decisions.
4. Delete the initiative's probes and experiment code. One that must survive
   becomes a phase of an active plan.

A complete initiative holds only `master-plan.md`, contract documents and
decision records. An initiative contract document may stay when it describes
the current system.

## Commit messages and agent reports

The commit message holds slice evidence, in at most 30 lines: the scope, the
checks run with counts, the source commit, deviations, each audit finding with
its disposition, and one line per agent with its model and effort.

Planner, writer and auditor reports are printed in the session. While an
initiative is active, file a report in `working/` only when a later session
needs it. Move each decision from a design into a decision record.

## Experiment results and generated output

- Raw logs, timings, benchmark output, archives, databases, screenshots and
  failed attempts stay in ignored `tmp/`. If a claim depends on them, quote the
  number and its settings in the commit message.
- `results/experiments/` holds only small text summaries that a standing
  document cites: `.md`, `.json`, `.csv` or `.txt` files of at most 64 KB.
- Generated website output stays untracked. `website/local/` and the portable
  `website/dist/` export are both ignored.

## Do not create

- A file under `docs/plans/` outside the layout above.
- A `.gz`, `.zip`, `.sqlite`, `.log`, image or other binary file under
  `docs/plans/` or `results/experiments/`.
- A link from a tracked record to `tmp/` or `/tmp/`. Nobody else can open it.

## Enforcement

Run `python3 tests/check_records.py` in the WSL source checkout before every
commit. Do not commit if it fails. The check applies the layout, the limits,
the status rules and the file rules above. It also rejects broken relative
links in every tracked Markdown file. There is no exemption list. After changing the check, run `python3 tests/test_records_check.py`.
