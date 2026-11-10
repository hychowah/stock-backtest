# WSL source and native Windows runtime

Edit and commit source in WSL. Run the server, saved-data preparation and full-data checks with native Windows Python. The source checkout is a WSL clone of this repository. The runtime is a separate folder on the Windows filesystem, exported from a committed revision.

An earlier, pre-deployment checkout may be retained as a fallback; it is not the active development checkout. The WSL repository preserves its saved history in `.git-local`. A `.git` pointer enables ordinary Git commands. The Windows runtime has no separate Git repository.

A feature branch or linked worktree does not replace the registered deployment
source.

## Daily commands

From the WSL source checkout:

```bash
git status
# Edit, test and commit source.
python3 tools/deploy.py
python3 tools/deploy.py --start
```

Deployment exports one selected Git commit. It does not copy working-tree edits.
Running `backtest-web.cmd` or `python3 tools/deploy.py --start` serves the
installed revision. An ordinary restart does not select a newer commit or fetch
data. Once a day at 07:00 Hong Kong time the watcher reads committed
`main`. If the tip differs from the installed commit, it stages source, gracefully
stops the current native server, publishes the commit and starts its replacement
in the same terminal. It refreshes FMP inputs before accepting requests or queue
work, even if main has no new commit. Refresh uses the installed source under
shared source ownership, then exclusive financial-cache ownership. Ordinary
preparation and the website build run after downloading. Saved results remain
unchanged. A missed 07:00 minute waits until the next day, including after launch
or resume. The terminal must stay running. Any number of commits in one day cause
one scheduled maintenance cycle. Existing terminals keep their loaded behavior.
Add
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
installed revision; the scheduled data refresh still runs. A failed source
publication retries automatically; pending journals stay in
place for recovery. A staging failure leaves the old server serving.

The supervisor forwards scheduled refresh intent through `EBITDA_WEB_REFRESH`.
Older source revisions ignore it, so moving main back does not introduce an
unknown startup argument. Ordinary launches clear scheduled refresh intent.
Direct startup without the explicit `--refresh-data` option remains offline.
The same operation is
available as **Update data** on the data panel. Its fixed coverage
and outcome are described in the [data workflow](research-workflow.md#data-control-panel).
One company's provider failure does not stop other stocks or market series.
Provider failures keep completed downloads. Publication I/O failures stop
further downloads. The replacement prepares the valid
saved inputs and reports a partial refresh. Preparation failure prevents service
startup. `data/data-refresh.json` stores the state, scope, target date, stage counts,
verified running time, last success, latest SPY session and pending stocks. The
existing financial owner publishes it atomically. A foreign busy cache leaves
interrupted-versus-running status unconfirmed until the cache is free. It contains no credentials or provider URLs.

The source has no experimental engine. The website neither prepares nor runs
it.

For an already-installed revision without contacting WSL, run native Python directly:

```powershell
cd <runtime folder>
py -3 website\serve.py --managed
```

Source publication and native server execution share a lock. A deployment stops only authenticated servers from this runtime, including instances on alternate ports. It waits for their processes and request cleanup. An unresponsive listener is not proof of exit. An unrelated listener is not stopped. If the source is still owned, deployment fails with a retry instruction.

## What belongs in each folder

| Content | Owner |
|---|---|
| Git history, code, tests, user documentation | WSL source checkout |
| Frozen January record and experiment records in Git | WSL source checkout |
| Saved provider data and download receipts under `raw/` | Windows runtime |
| SQLite databases, process identities, locks and logs under `data/` | Windows runtime |
| Runtime copy of `results/summary-exits.txt` and baseline history | Windows runtime |
| Built local page under `website/local/` | Windows runtime |
| Native environments and leftover experimental-engine caches (`data/numerical/`, `data/numerical-preparation.json`; no source reads them) | Windows runtime; create them for Windows |
| Deployment hashes and commit identity | Windows `data/deployment.json` |

Tracked README files inside data folders remain source-owned documentation. Other tracked analysis reports can be deployed from reviewed commits. `results/summary-exits.txt` is the exception: deployment never installs, replaces or removes it, even in a fresh runtime. Only the development check reads it, on the real-data bench, so a runtime without it works normally.

There is no automatic reverse source sync. Do not edit installed Windows code. Deployment detects unexpected edits and unowned-file collisions before replacing source. It removes only source files owned by the preceding deployment manifest. A case-only rename must be deployed through an intermediate committed filename so Windows can distinguish the versions.

## Verify the installed revision

```bash
python3 tools/deploy.py --check
```

This republishes the retained revision (or an explicitly selected revision), runs native Windows deployment, launcher, startup, cache-access and saved-path checks, ensures prepared data, builds local output, and checks SQL/browser parity. It also runs the range check with Node.js from WSL against the Windows output. No market-data download starts.

The WSL checkout contains source and synthetic test fixtures, not another full raw cache. For example, `python3 tests/test_deployment.py` runs there. The saved-data `tests/check_paths.py` belongs in the Windows runtime and is included in `--check`. Linux and Windows environments and native binaries are separate.

## The frozen report

The tracked `results/summary-exits.txt` is a frozen record of the January study.
Nothing collects a runtime report into source, and no preparation writes or
reads either copy. Deployment leaves the Windows copy alone.

Raw data remains outside Git. Back it up separately. Baseline revision history remains in the Windows runtime.

## Interrupted deployment

The automatic launcher retries unfinished updates. You can also run `python3 tools/deploy.py` again. A pending publication retains its verified staging payload and completion journal. Default retry selects that transaction's commit, even if the final manifest still records the older commit. An explicit different revision is rejected before staging. Finish recovery first, then deliberately select another revision if needed. Native publication still verifies the retained payload under its existing locks. The server refuses to import application modules while a pending publication exists. Do not delete the journal, edit the manifest, or copy individual source files to bypass recovery.

The lock is acquired before the application module is imported. `website/serve.py` is the small entry point; `website/server/app.py` holds the HTTP application. The ownership implementation is `website/runtime_access.py`.

## Local registration and fallback

The ignored `data/workspace.json` records `source` (the WSL path), `distro`, `runtime` (the Windows path) and `python` (the native interpreter path). The source checkout and runtime each have this machine-local registration. The deployment tool does not copy it from Git.

The original folder keeps its source, history and saved data. Its old `backtest-web.cmd` can launch that retained copy explicitly. Its code predates deployment ownership. Use it as a separate fallback; do not point the new deployment target at that source repository. A rollback to another deployed revision requires that revision to contain the workspace deployment tools.

The architecture guide describes the current split.

## Private input copies

`tools/ops/offline_input_copy.py` copies the saved raw inputs into a new private
root (manifest version 2; a version-1 capture with the report is refused). It has no command entry. It defers while a
server, data job or pending publication holds ownership. A copy without its
completion marker is unusable. The
[experiment summaries](../results/experiments/README.md) record the engine
decisions and measured results.
