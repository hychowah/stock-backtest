import type { RunsReply } from "../api/RunsReply.ts";
import { NO_ANSWER } from "../client.ts";
import { since } from "../format.ts";
import { type Shared, useNow } from "../live.ts";

/** The bar at the foot of the page, which speaks for the queue: the running
 *  test's name and the time since it started, or Idle; the waiting count and
 *  whether the queue is paused; and the button that opens the queue tray.
 *  The dot before the state is green while a test runs, and amber while the
 *  queue is paused or the server does not answer. */
export function StatusBar({ runs, onOpenRuns, onOpenTray }: { runs: Shared<RunsReply>; onOpenRuns: () => void; onOpenTray: () => void }) {
  const reply = runs.value;
  const running = reply?.runs.find((run) => run.state === "running");
  const now = useNow(running !== undefined);
  const waiting = reply?.runs.filter((run) => run.state === "waiting" || run.state === "held").length ?? 0;

  let title = "Idle";
  let state = reply?.paused ? "attention" : "idle";
  let detail = reply ? "No active backtest." : "Connecting to the queue…";
  if (running) {
    title = "Running · " + running.name;
    state = "running";
    detail = running.started ? "Running for " + since(running.started, now) : "Backtest is running on the server.";
  }
  if (runs.failure) {
    state = "attention";
    detail = runs.failure.status === 0 ? NO_ANSWER : runs.failure.message;
  }

  return (
    <div id="workspace-statusbar" role="region" aria-label="Run and queue status">
      <button type="button" id="workspace-run-open" onClick={onOpenRuns}>
        <span id="workspace-run-state" data-state={state}>
          {title}
        </span>
        <small id="workspace-run-detail">{detail}</small>
      </button>
      <span id="workspace-waiting">{reply ? (reply.paused ? "Queue paused · " : "") + waiting + " waiting" : ""}</span>
      <button type="button" id="workspace-queue-open" aria-haspopup="dialog" onClick={onOpenTray}>
        Queue & runs
      </button>
    </div>
  );
}
