import { useEffect, useState } from "preact/hooks";
import type { Market } from "../api/Market.ts";
import type { RunRow } from "../api/RunRow.ts";
import { client } from "../client.ts";
import { formatTime, since } from "../format.ts";
import { useNow, useRuns } from "../live.ts";
import { useRead } from "../read.ts";
import { go } from "../route.ts";
import { choiceWords, failureNote, inMarket, inProgress, kindWords, marketButtons, marketCounts, queuePlaces, rowState, savedRuns, stateWords, windowWords } from "../runs.ts";
import { useMarket } from "./market.ts";
import { editRun, tuneRun } from "./load.ts";
import { type Note, type Perform, type SetNote, useActions } from "./note.ts";
import { RunDetails } from "./RunDetails.tsx";

/** The queue panel: the runs that are not complete, with the controls of the
 *  queue and of each run. It is drawn in the tray while the tray is open and
 *  otherwise first in Runs & saved, and it is drawn anew each time it moves:
 *  what must survive the move (the market choice) lives in market.ts. The
 *  panel's line `#queue-status` says what the last action did, or the
 *  server's refusal. */
export function QueuePanel() {
  const runs = useRuns();
  const { note, setNote, busy, perform } = useActions();
  const list = runs.value?.runs ?? [];
  const places = queuePlaces(list);
  const [chosen] = useMarket();
  const rows = inMarket(inProgress(list), chosen);
  const now = useNow(rows.some((run) => run.state === "running"));
  const paused = runs.value?.paused ?? false;
  return (
    <section id="queue-panel" class="panel backtest-queue" aria-labelledby="queue-heading">
      <div class="toolbar">
        <div class="section-heading">
          <h2 id="queue-heading">Runs and saved backtests</h2>
          <span class="run-counts">
            In progress <span id="queue-count">{inProgress(list).length}</span> · Saved <span id="saved-count">{savedRuns(list).length}</span>
          </span>
        </div>
        <div>
          <button
            id="queue-pause"
            type="button"
            disabled={busy || !runs.value}
            onClick={() => perform(() => client.setQueue({ paused: !paused }), paused ? "Queue resumed." : "Queue paused. The active test can finish.")}
          >
            {paused ? "Resume queue" : "Pause queue"}
          </button>
        </div>
      </div>
      <MarketSwitch list={list} />
      <p class="hint">Tests run one at a time on the server. You can close this page. Keep the server computer awake and its terminal open.</p>
      <StatusLine id="queue-status" note={runs.failure ? { text: runs.failure.message, error: true } : note ?? { text: runs.value ? "Queue ready. Tests and results are saved on the server." : "Connecting to the server queue…", error: false }} />
      <details class="how-it-works">
        <summary>How this works</summary>
        <p class="hint">
          To add a test, select <strong>Historical backtest</strong> in Build strategy, set the steps and dates, then select <strong>Add to queue</strong>. Change the settings to add the next test.
        </p>
        <p class="hint">
          <strong>Pause queue</strong> prevents the next test from starting; the active test can finish. A finished test moves to Saved backtests. Failed and stopped tests remain here. After a server restart, an interrupted test runs again
          with the same random date set. If the server stopped without warning, the test it was running is held until you select <strong>Release hold</strong> or delete it.
        </p>
        <p class="hint">
          Select the name of a saved backtest to open its result. <strong>Details</strong> in a row shows the settings of that test and its other actions; <strong>Tune</strong> copies the
          settings to Build strategy. Tick saved backtests, then select <strong>Compare</strong>,{" "}
          <strong>Lock ticked</strong> or <strong>Delete ticked</strong>; the box in the heading ticks every row shown. A locked test cannot be deleted until you unlock it. Details and the comparison read stored results and run no test.
        </p>
        <p class="hint">
          CAGR is the median trial CAGR for random dates. Select the <strong>Name</strong>, <strong>CAGR</strong> or <strong>Saved</strong> heading to sort the saved backtests.
        </p>
      </details>
      <h3 class="run-group">In progress</h3>
      <div class="run-row run-head">
        <span>Name</span>
        <span>Status</span>
        <span>Type</span>
        <span>Window</span>
        <span class="run-cagr">CAGR</span>
        <span>Added</span>
      </div>
      <ol id="queue-list" aria-label="Tests in progress">
        {rows.length ? (
          rows.map((run) => <QueueRow key={run.id} run={run} place={places.get(run.id)} now={now} busy={busy} perform={perform} setNote={setNote} />)
        ) : (
          <li class="run-empty">No {chosen && choiceWords(chosen) + " "}test is waiting or running. Select Add to queue in Build strategy.</li>
        )}
      </ol>
    </section>
  );
}

/** A panel's status line: the note, in the failure colour for a refusal. */
export function StatusLine({ id, note }: { id: string; note: Note }) {
  return (
    <p id={id} class={note?.error ? "backtest-failed" : "hint"} role="status" aria-live="polite">
      {note?.text}
    </p>
  );
}

/** The market switch: All and each market with its number of runs. */
function MarketSwitch({ list }: { list: RunRow[] }) {
  const [chosen, choose] = useMarket();
  const status = useRead(() => client.dataStatus(), []);
  const prepared: Market[] = status.state === "done" ? status.value.markets.filter((market) => market.prepared).map((market) => market.market) : [];
  const counts = marketCounts(list);
  return (
    <div id="run-markets" class="run-markets" role="group" aria-label="Market of the tests shown">
      {marketButtons(counts, prepared, chosen).map((choice) => (
        <button key={choice} type="button" data-market={choice} aria-pressed={choice === chosen} onClick={() => choose(choice)}>
          {choiceWords(choice)} <span>{counts[choice]}</span>
        </button>
      ))}
    </div>
  );
}

/** One run of the queue panel: one line, and its other actions and settings
 *  in Details. A running run shows the time since it started; a failed run the
 *  server's message and place. */
function QueueRow({ run, place, now, busy, perform, setNote }: { run: RunRow; place: { place: number; last: boolean } | undefined; now: number; busy: boolean; perform: Perform; setNote: SetNote }) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  // A pending Delete ends when the run changes state.
  useEffect(() => setConfirming(false), [run.state]);
  const queued = run.state === "waiting" || run.state === "held";
  const button = (label: string, onClick: () => void, disabled = false) => (
    <button type="button" disabled={busy || disabled} onClick={onClick}>
      {label}
    </button>
  );
  const move = (to: number) => perform(() => client.move(run.id, { to }), "Queue updated.");
  const note = run.state === "running" && run.started ? "Running for " + since(run.started, now) : failureNote(run);
  return (
    <li class="run-row" data-queue-id={run.id} data-state={rowState(run.state)}>
      <span class="run-name" title={run.name}>
        <span>{run.name}</span>
      </span>
      <span class="run-status">
        <span class="queue-state">{stateWords(run.state)}</span>
        <span class="queue-progress">{note}</span>
      </span>
      <span class="run-type">{kindWords(run.schedule)}</span>
      <span class="run-window">{windowWords(run.schedule)}</span>
      <span class="run-cagr" />
      <span class="run-time">{formatTime(run.created)}</span>
      <details class="run-menu" onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary aria-label={`Details of ${run.name}`}>Details</summary>
        <div class="run-actions">
          {queued && button("Edit settings", () => editRun(run.id, perform, setNote))}
          {queued && place && button("Move up", () => move(place.place - 1), place.place === 1)}
          {queued && place && button("Move down", () => move(place.place + 1), place.last)}
          {run.state === "held" && button("Release hold", () => perform(() => client.release(run.id), "Hold released. The test waits in its place."))}
          {run.state === "running" && button("Stop test", () => perform(() => client.stop(run.id), "Stop requested. The next test starts after cleanup."))}
          {(run.state === "waiting" || run.state === "running" || run.state === "failed") && button("Open result", () => go({ view: "review", id: run.id }))}
          {button("Tune", () => tuneRun(run.id, perform, setNote))}
          {run.state !== "running" &&
            (confirming ? (
              <>
                <span>Delete this test and its result?</span>
                {button("Delete test", () => void perform(() => client.deleteRun(run.id), "Selected test deleted."))}
                {button("Keep", () => setConfirming(false))}
              </>
            ) : (
              button("Delete", () => setConfirming(true))
            ))}
        </div>
        {open && <RunDetails id={run.id} saved={false} />}
      </details>
    </li>
  );
}
