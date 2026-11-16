#!/usr/bin/env bash
# Builds the program and the website from this checkout and installs them in
# $HOME/runtime/stock-backtest: bin/bt, web/, logs/ and installed-commit, plus
# the user units bt-update.service and bt-update.timer in
# $HOME/.config/systemd/user.
# Safe to run again: an update of the program is the same command. A running
# server or update keeps its old bin/bt file until it is restarted.
# It leaves raw/ and data/ alone, and it does not enable the timer or restart
# anything.
# Order: install, restart the site, then (when no update is running: see
# bin/bt data status) run bin/bt data prepare.
# To turn on the nightly update, once: loginctl enable-linger, then
# systemctl --user enable --now bt-update.timer.
set -euo pipefail

runtime="$HOME/runtime/stock-backtest"
units="$HOME/.config/systemd/user"
cd "$(dirname "$0")"

commit=$(git rev-parse HEAD)
changes=$(git status --porcelain --untracked-files=no)
if [ -n "$changes" ]; then
    echo "install.sh: this checkout has tracked changes: commit or discard them first" >&2
    exit 1
fi

cargo build --release --locked -p bt
(cd web && npm ci && npm run build)

mkdir -p "$runtime/bin" "$runtime/web" "$runtime/logs" "$units"
cp target/release/bt "$runtime/bin/bt.new"
mv -f "$runtime/bin/bt.new" "$runtime/bin/bt"
rsync -a --delete web/dist/ "$runtime/web/"
echo "$commit" > "$runtime/installed-commit"

cat > "$units/bt-update.service" <<UNIT
[Unit]
Description=Update the stock data

[Service]
Type=oneshot
ExecStart=$runtime/bin/bt data update
StandardOutput=append:$runtime/logs/update.log
StandardError=append:$runtime/logs/update.log
SendSIGKILL=no
UNIT

cat > "$units/bt-update.timer" <<UNIT
[Unit]
Description=Update the stock data every day

[Timer]
OnCalendar=*-*-* 23:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload || echo "install.sh: no user manager answered: run 'systemctl --user daemon-reload' later"

echo "Installed $commit in $runtime. Next: restart the site; then, when no update is running ($runtime/bin/bt data status shows it), run $runtime/bin/bt data prepare"
