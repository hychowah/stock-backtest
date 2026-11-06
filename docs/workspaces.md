# WSL source and native Windows runtime

Edit and commit source in WSL. Run the server, saved-data preparation and full-data checks with native Windows Python. The source checkout is `<wsl-checkout>`. The runtime is `<windows-runtime>`.

The original legacy folder is retained as a fallback. It is not the active development checkout. The WSL repository preserves its saved history in `.git-local`. A `.git` pointer enables ordinary Git commands. The Windows runtime has no separate Git repository.

Read [AGENTS.md](../AGENTS.md#current-state-and-authorization) before changing
shared calculation, cache, worker, API or startup contracts. A feature branch or
linked worktree does not replace the registered deployment source.

## Daily commands

From the WSL source checkout:

```bash
git status
# Edit, test and commit source through the phase workflow.
python3 tools/deploy.py
python3 tools/deploy.py --start
```

Deployment exports one selected Git commit. It does not copy working-tree edits.
Running `backtest-web.cmd` or `python3 tools/deploy.py --start` serves the
installed revision. A restart never installs a newer commit, so it never causes a
database rebuild. Once a day at 01:00 local time the watcher reads committed
`main`. If the tip differs from the installed commit, it stages source, gracefully
stops the current native server, publishes the commit and starts its replacement
in the same terminal. Any number of commits in one day cause one restart. Add
`--latest` (`backtest-web.cmd --latest`) to install the current `main` tip at
launch. A runtime with nothing installed installs the tip. Refresh an open
browser page to load the new HTML. Restarts do not open another browser tab.

The daily check follows `refs/heads/main`, including a deliberate change of its tip.
It does not follow other branches, a checked-out feature branch, remote
repositories or uncommitted edits. It does not fetch or pull history.

Use `python3 tools/deploy.py --revision <commit> --start` to run one fixed revision
without automatic updates. `--revision HEAD` also freezes that resolved commit
for this launch. With an older installed launcher, use this explicit command from
WSL. Direct native startup below also stays fixed.

Plain `python3 tools/deploy.py` and `--check` retain the installed commit from
`data/deployment.json` unless an explicit revision is supplied. A fresh standalone
publication requires an explicit revision. Automatic `--start` selects main only with `--latest`, at the daily check or on a fresh runtime.
An invalid installation record still stops publication. An unfinished publication
is completed at its recorded commit before automatic startup selects newer main.
A conflicting explicit revision is rejected until recovery completes.

From Windows Terminal, run `backtest-web.cmd`. The installed command delegates to
the current WSL deployment tool. WSL must be available. The source launcher also
works from its WSL network path and finds its helper relative to the command file.
Ctrl+C stops this launch's server and watcher. A normal child exit ends its old
watcher, so a replacement terminal cannot be undone by the previous terminal.

The source archive is ready before the old child receives its private stop
marker. `website/serve.py` observes the marker even during startup preparation.
It performs normal Ctrl+C cleanup. Publication waits for complete process exit,
then uses the existing source-before-financial lock order. A timeout preserves
ownership and retries. No forced process kill bypasses cleanup. Active manual
runs stop. Interrupted queued tests return to waiting and retain their recorded
dates. Saved results and user data survive. A missing Git observation keeps the
current server. A failed update retries automatically; pending journals stay in
place for recovery. A staging failure leaves the old server serving.

The source has no experimental engine. The website neither prepares nor runs
it.

For an already-installed revision without contacting WSL, run native Python directly:

```powershell
cd <windows-runtime>
py -3 website\serve.py --managed
```

Source publication and native server execution share a lock. A deployment stops only authenticated servers from this runtime, including instances on alternate ports. It waits for their processes and request cleanup. An unresponsive listener is not proof of exit. An unrelated listener is not stopped. If the source is still owned, deployment fails with a retry instruction.

## What belongs in each folder

| Content | Owner |
|---|---|
| Git history, code, tests, user documentation | WSL source checkout |
| Reviewed report and experiment records in Git | WSL source checkout |
| Saved provider data and download receipts under `raw/` | Windows runtime |
| SQLite databases, process identities, locks and logs under `data/` | Windows runtime |
| Current verified `results/summary-exits.txt` and baseline history | Windows runtime |
| Built local page under `website/local/` | Windows runtime |
| Native environments and leftover experimental-engine caches | Windows runtime; create them for Windows |
| Deployment hashes and commit identity | Windows `data/deployment.json` |

Tracked README files inside data folders remain source-owned documentation. Other tracked analysis reports can be deployed from reviewed commits. The canonical report is special: after initial installation, deployment never replaces it. Its exact content must remain bound to the prepared research database.

A missing report in an established runtime stays missing. Restore its verified
database-bound version from baseline revision evidence or backup. Deployment
does not substitute the Git report for it. Initial seeding is allowed only when
there is no previous deployment and no prepared research database.

There is no automatic reverse source sync. Do not edit installed Windows code. Deployment detects unexpected edits and unowned-file collisions before replacing source. It removes only source files owned by the preceding deployment manifest. A case-only rename must be deployed through an intermediate committed filename so Windows can distinguish the versions.

## Verify the installed revision

```bash
python3 tools/deploy.py --check
```

This republishes the retained revision (or an explicitly selected revision), runs native Windows deployment, launcher, startup, cache-access and saved-path checks, ensures prepared data, builds local output, and checks SQL/browser parity. It also runs the range check with Node.js from WSL against the Windows output. No market-data download starts.

The WSL checkout contains source and synthetic test fixtures, not another full raw cache. For example, `python3 tests/test_deployment.py` runs there. The saved-data `tests/check_paths.py` belongs in the Windows runtime and is included in `--check`. Linux and Windows environments and native binaries are separate.

## The canonical report

The tracked `results/summary-exits.txt` is a frozen record. Nothing collects a
runtime report into source. Ordinary deployment leaves the active Windows report
alone, and a fresh runtime receives a copy of the tracked report.

Raw data remains outside Git. Back it up separately. Baseline revision history remains in the Windows runtime.

## Interrupted deployment

The automatic launcher retries unfinished updates. You can also run `python3 tools/deploy.py` again. A pending publication retains its verified staging payload and completion journal. Default retry selects that transaction's commit, even if the final manifest still records the older commit. An explicit different revision is rejected before staging. Finish recovery first, then deliberately select another revision if needed. Native publication still verifies the retained payload under its existing locks. The server refuses to import application modules while a pending publication exists. Do not delete the journal, edit the manifest, or copy individual source files to bypass recovery.

The lock is acquired before the application module is imported. `website/serve.py` is the small entry point; `website/server/app.py` holds the HTTP application. The ownership implementation is `website/runtime_access.py`.

## Local registration and fallback

The ignored `data/workspace.json` records `source` (the WSL path), `distro`, `runtime` (the Windows path) and `python` (the native interpreter path). The source checkout and runtime each have this machine-local registration. The deployment tool does not copy it from Git.

The original folder keeps its source, history and saved data. Its old `backtest-web.cmd` can launch that retained copy explicitly. Its code predates deployment ownership. Use it as a separate fallback; do not point the new deployment target at that source repository. A rollback to another deployed revision requires that revision to contain the workspace deployment tools.

The user architecture guide describes the current split.

## Private input copies

`tools/ops/offline_input_copy.py` copies the saved raw inputs and the canonical
report into a new private root. It has no command entry. It defers while a
server, data job or pending publication holds ownership. A copy without its
completion marker is unusable. The
[faster engine summary](plans/compiled-backtest/master-plan.md) records the
engine decisions and measured results.
