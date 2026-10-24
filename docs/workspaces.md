# WSL source and native Windows runtime

Edit and commit source in WSL. Run the server, saved-data preparation and full-data checks with native Windows Python. The source checkout is `<wsl-checkout>`. The runtime is `<windows-runtime>`.

The original legacy folder is retained as a fallback. It is not the active development checkout. The WSL repository preserves its saved history in `.git-local`. A `.git` pointer enables ordinary Git commands. The Windows runtime has no separate Git repository.

## Daily commands

From the WSL source checkout:

```bash
git status
# Edit, test and commit source through the phase workflow.
python3 tools/deploy.py
python3 tools/deploy.py --start
```

Deployment exports the selected Git commit. It does not copy working-tree edits. The two existing portable-snapshot edits remain in the WSL checkout until separately reviewed. Commit implementation changes before deployment. Use `--revision <commit>` to select another compatible committed revision.

From Windows Terminal, run `backtest-web.cmd`. The installed command calls the Windows runtime launcher. It asks WSL to deploy the source checkout's `HEAD`, then starts native Windows Python in the same terminal. Ctrl+C stops the server. WSL must be available to run this deployment step.

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
| Native environments and compiled caches | Windows runtime; create them for Windows |
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

This deploys committed source, runs native Windows deployment, launcher, startup, cache-access and saved-path checks, ensures prepared data, builds local output, and checks SQL/browser parity. It also runs the range check with Node.js from WSL against the Windows output. No market-data download starts.

The WSL checkout contains source and synthetic test fixtures, not another full raw cache. For example, `python3 tests/test_deployment.py` runs there. The saved-data `tests/check_paths.py` belongs in the Windows runtime and is included in `--check`. Linux and Windows environments and native binaries are separate.

## Collect a verified report revision

After a Windows data-panel rebuild changes the canonical report:

```bash
python3 tools/deploy.py --collect-report
```

This checks the Windows report/database hash binding under source and financial ownership. It exports the report and priced baseline evidence. It then updates the source report and creates a reviewable evidence file under `results/experiments/` when the report differs. Uncommitted source-report edits are preserved and cause collection to stop. Review and smart-commit the collected revision. Ordinary deployment still leaves the active Windows report alone.

Raw data remains outside Git. Back it up separately. Baseline revision history remains in the Windows runtime.

## Interrupted deployment

Run `python3 tools/deploy.py` again. A pending publication retains its verified staging payload and completion journal. Retry completes that publication before starting another. The server refuses to import application modules while a pending publication exists. Do not delete the journal, edit the manifest, or copy individual source files to bypass recovery.

The lock is acquired before the application module is imported. `website/serve.py` is the small entry point; `website/serve_app.py` holds the HTTP application. The ownership implementation is `website/runtime_access.py`.

## Local registration and fallback

The ignored `data/workspace.json` records `source` (the WSL path), `distro`, `runtime` (the Windows path) and `python` (the native interpreter path). The source checkout and runtime each have this machine-local registration. The deployment tool does not copy it from Git.

The original folder keeps its source, history and saved data. Its old `backtest-web.cmd` can launch that retained copy explicitly. Its code predates deployment ownership. Use it as a separate fallback; do not point the new deployment target at that source repository. A rollback to another deployed revision requires that revision to contain the workspace deployment tools.

The user architecture guide describes the current split. The compiled-engine master plan remains a separate program; this workspace migration does not implement its calculation phases.
