# Running the program

This page is for the person who runs Stock Backtest every day on one Linux
computer. The [command-line guide](command-line.md) gives the details of each
command.

## The runtime folder

`install.sh` installs the program in `~/runtime/stock-backtest`:

| Part | What it is |
|---|---|
| `bin/bt` | The program. Without `--home`, it uses the folder above `bin/`. |
| `web/` | The website that `bin/bt serve` serves. |
| `logs/update.log` | The output of the nightly update and of the updates that the site starts. |
| `installed-commit` | The Git commit that was installed. |
| `raw/` | The raw provider files. `install.sh` does not make or change it. |
| `data/` | The prepared data (`data/prepared/`), the list of runs (`data/app.sqlite`), the result files (`data/runs/`) and the update record (`data/update.json`). |

## Install and update the program

From the source checkout, with no tracked changes, run:

```bash
./install.sh
```

It builds the program and the website, copies them to the runtime folder and
writes the user units `bt-update.service` and `bt-update.timer`. It does not
change `raw/` or `data/`, and it restarts nothing. An update of the program
is the same command. Then do these steps in this order:

1. Restart the site (see below). A running site keeps the old program, and
   its Update data button fails until the restart.
2. When no update is running (`~/runtime/stock-backtest/bin/bt data status`
   shows it), prepare the data again. A new program can need a new
   preparation.

```bash
~/runtime/stock-backtest/bin/bt data prepare
```

## The nightly update

Turn the nightly update on once:

```bash
loginctl enable-linger
systemctl --user enable --now bt-update.timer
```

Linger lets the timer run when you are not logged in. The timer runs
`bin/bt data update` every day at 23:00 UTC. If the computer was off at that
time, it runs at the next start. Its output goes to `logs/update.log`. To
turn it off, run `systemctl --user disable --now bt-update.timer`.

To see the last update, run `bin/bt data status`, or open the data page of
the site (**Data & preparation**).

## Start and stop the site

```bash
~/runtime/stock-backtest/bin/bt serve
```

The site is at `http://127.0.0.1:3000`, on this computer only. Use a
forward to reach it from another device. Keep the terminal open. Press
Ctrl+C to stop the site. A run in progress then waits in the queue again,
and an update in progress continues.

## The data page

- **Update data** starts `bt data update` as a process of its own. You can
  close the page while it runs.
- **Stop update** stops it safely and keeps the saved files. A stop before
  preparation leaves the data unprepared; a stop during preparation lets it
  finish.
- **Continue update** shows after an update that stopped, was interrupted or
  failed, and starts it again.

The page names the outcome: **Data updated**, **Updated, with failed items**,
**Update stopped**, **Update interrupted** or **Update failed**.
[Updating the data](command-line.md#updating-the-data) gives the rules for
stopping, continuing and each outcome.

## One writer of raw/

Only one update runs on a runtime folder at a time. A second one stops with
"an update is already running". While an update runs, do not copy files into
`raw/` and do not run `bin/bt data prepare`: the update prepares the data
itself when it ends.

## Back up

Back up `raw/`. Do not plan to download it again: a full history takes many
thousands of requests, and the report values that the provider showed first
cannot be downloaded again. Back up `data/app.sqlite` and `data/runs/`
together: they hold the list of runs, the queue, the variable library and
the result files. Stop the site before you copy them. `data/prepared/` needs
no backup: `bin/bt data prepare` makes it again from `raw/`.
