import { useEffect, useRef, useState } from "preact/hooks";
import type { RunRow } from "../api/RunRow.ts";
import { client } from "../client.ts";
import { formatTime, percent } from "../format.ts";
import { useRuns } from "../live.ts";
import { useRead } from "../read.ts";
import { go } from "../route.ts";
import { FIRST_SORTING, type SortKey, type Sorting, choiceWords, inMarket, kindWords, resorted, savedAt, savedCagr, savedRuns, sortSaved, windowWords } from "../runs.ts";
import { Compare, readDescribed } from "./Compare.tsx";
import { useMarket } from "./market.ts";
import { type Perform, type SetNote, useActions } from "./note.ts";
import { tuneRun } from "./load.ts";
import { StatusLine } from "./QueuePanel.tsx";
import { RunDetails } from "./RunDetails.tsx";

const HEADINGS: Record<SortKey, string> = { name: "Name", cagr: "CAGR", saved: "Saved" };

const savedCount = (n: number) => (n > 1 ? `${n} saved backtests` : "1 saved backtest");

/** The saved table: every complete run of the market chosen in the switch,
 *  with the sticky band on top (the heading, the status line, the bar of the
 *  ticked tests and the sort headings) and the comparison of the ticked
 *  tests. A tick reads nothing; Details and Compare read the stored results
 *  of the runs they show. */
export function SavedPanel() {
  const runs = useRuns();
  const { note, setNote, busy, perform } = useActions();
  const [chosen] = useMarket();
  const [sorting, setSorting] = useState<Sorting>(FIRST_SORTING);
  const [ticked, setTicked] = useState<ReadonlySet<number>>(new Set());
  const [comparing, setComparing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const all = savedRuns(runs.value?.runs ?? []);
  const shown = sortSaved(inMarket(all, chosen), sorting);
  const ticks = shown.filter((run) => ticked.has(run.id));
  const ids = ticks.map((run) => run.id);
  const active = comparing && ids.length > 1;
  const described = useRead(() => (active ? readDescribed(ticks) : Promise.resolve(null)), [active, ids.join(",")]);

  // No tick closes the comparison.
  useEffect(() => {
    if (!ticks.length) setComparing(false);
  }, [ticks.length]);

  // Another market clears every tick.
  useEffect(() => {
    setTicked(new Set());
    setConfirming(false);
  }, [chosen]);

  const tick = (changed: readonly number[], on: boolean) => {
    const next = new Set(ticked);
    for (const id of changed) on ? next.add(id) : next.delete(id);
    setTicked(next);
    setConfirming(false);
  };
  const deletable = ticks.filter((run) => !run.locked);
  const locking = deletable.length > 0;

  const lockTicked = () => {
    const changed = ticks.filter((run) => run.locked !== locking);
    return perform(async () => {
      for (const run of changed) await client.editRun(run.id, { locked: locking });
    }, `${changed.length > 1 ? savedCount(changed.length) : "Saved backtest"} ${locking ? "locked." : "unlocked."}`);
  };
  const deleteTicked = async () => {
    setConfirming(false);
    const removed = deletable.map((run) => run.id);
    await perform(async () => {
      for (const id of removed) await client.deleteRun(id);
    }, `${removed.length > 1 ? savedCount(removed.length) : "Saved backtest"} deleted.`);
  };
  const compare = () => {
    setComparing(!comparing);
    const top = panel.current?.getBoundingClientRect().top ?? 0;
    if (!comparing && top < 0) panel.current?.scrollIntoView();
  };

  const reading = active && described.state === "loading" ? ids.length : 0;
  const barNote = ticks.length === 1 ? "Tick another to compare." : reading ? `Reading ${reading > 1 ? reading + " stored results" : "1 stored result"}…` : "";
  return (
    <section id="saved-panel" class="panel saved-backtests" aria-labelledby="saved-heading" ref={panel}>
      <div class="saved-top">
        <h3 id="saved-heading" class="run-group">
          Saved backtests
        </h3>
        <p class="hint">A test that finishes is saved here automatically.</p>
        <StatusLine id="saved-status" note={note} />
        <div id="saved-bar" class="comparison-bar" hidden={!ticks.length}>
          {ticks.length > 0 && (
            <>
              <strong>{ticks.length > 1 ? `${ticks.length} tests ticked` : "1 test ticked."}</strong>
              <span role="status">{barNote}</span>
              {confirming ? (
                <>
                  <span>
                    Delete {savedCount(deletable.length)}?{deletable.length < ticks.length && " Locked tests stay."}
                  </span>
                  <button type="button" id="saved-confirm-ticked" disabled={busy} onClick={deleteTicked}>
                    Delete {savedCount(deletable.length)}
                  </button>
                  <button type="button" id="saved-keep-ticked" disabled={busy} onClick={() => setConfirming(false)}>
                    Keep
                  </button>
                </>
              ) : (
                <>
                  <button type="button" id="saved-compare" disabled={ticks.length < 2 || busy} onClick={compare}>
                    {active ? "Hide comparison" : "Compare"}
                  </button>
                  <button type="button" id="saved-lock-ticked" disabled={busy} onClick={lockTicked}>
                    {locking ? "Lock ticked" : "Unlock ticked"}
                  </button>
                  <button type="button" id="saved-delete-ticked" disabled={!deletable.length || busy} onClick={() => setConfirming(true)}>
                    Delete ticked
                  </button>
                  <button type="button" id="saved-clear" disabled={busy} onClick={() => tick(ids, false)}>
                    Clear
                  </button>
                </>
              )}
            </>
          )}
        </div>
        <div id="saved-head" class="run-row run-head">
          <input
            type="checkbox"
            id="saved-tick-all"
            aria-label="Tick every saved backtest shown"
            checked={shown.length > 0 && shown.every((run) => ticked.has(run.id))}
            onChange={(event) => tick(shown.map((run) => run.id), event.currentTarget.checked)}
          />
          <button type="button" id="saved-sort-name" onClick={() => setSorting(resorted(sorting, "name"))} aria-current={sorting.key === "name" ? "true" : undefined}>
            {HEADINGS.name + (sorting.key === "name" ? (sorting.direction > 0 ? " ↑" : " ↓") : "")}
          </button>
          <span>Status</span>
          <span>Type</span>
          <span>Window</span>
          <button type="button" id="saved-sort-cagr" class="run-cagr" onClick={() => setSorting(resorted(sorting, "cagr"))} aria-current={sorting.key === "cagr" ? "true" : undefined}>
            {HEADINGS.cagr + (sorting.key === "cagr" ? (sorting.direction > 0 ? " ↑" : " ↓") : "")}
          </button>
          <button type="button" id="saved-sort-saved" onClick={() => setSorting(resorted(sorting, "saved"))} aria-current={sorting.key === "saved" ? "true" : undefined}>
            {HEADINGS.saved + (sorting.key === "saved" ? (sorting.direction > 0 ? " ↑" : " ↓") : "")}
          </button>
        </div>
      </div>
      <div id="saved-comparison" class="saved-comparison" hidden={!(active && described.state !== "loading")}>
        {active && described.state === "failed" && (
          <p class="backtest-failed" role="alert">
            {described.failure.message}
          </p>
        )}
        {active && described.state === "done" && described.value && <Compare runs={described.value} />}
      </div>
      <ul id="saved-list" aria-label="Saved backtests">
        {shown.length ? (
          shown.map((run) => <SavedRow key={run.id} run={run} ticked={ticked.has(run.id)} onTick={(on) => tick([run.id], on)} busy={busy} perform={perform} setNote={setNote} />)
        ) : (
          <li class="run-empty">{chosen && all.length ? `No saved ${choiceWords(chosen)} backtests.` : "No saved backtests yet."}</li>
        )}
      </ul>
    </section>
  );
}

/** One saved run: one line, and its settings and other actions in Details. The
 *  name opens the result. */
function SavedRow({ run, ticked, onTick, busy, perform, setNote }: { run: RunRow; ticked: boolean; onTick: (on: boolean) => void; busy: boolean; perform: Perform; setNote: SetNote }) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (renaming !== null) input.current?.focus();
  }, [renaming === null]);
  const cagr = savedCagr(run);
  const button = (label: string, onClick: () => void) => (
    <button type="button" disabled={busy} onClick={onClick}>
      {label}
    </button>
  );
  async function rename(name: string) {
    const text = name.trim();
    if (!text) return setNote({ text: "Use a backtest name with 1–120 characters.", error: true });
    if (await perform(() => client.editRun(run.id, { name: text }), `Renamed to “${text}”. Its ID and stored results are unchanged.`)) setRenaming(null);
  }
  return (
    <li class="run-row" data-state={run.locked ? "locked" : undefined}>
      <input type="checkbox" id={`saved-tick-${run.id}`} aria-label={`Tick ${run.name}`} checked={ticked} onChange={(event) => onTick(event.currentTarget.checked)} />
      <button type="button" class="run-name" id={`saved-open-${run.id}`} title={`Open the result of ${run.name}`} onClick={() => go({ view: "review", id: run.id })}>
        <span>{run.name}</span>
      </button>
      <span class="run-status">
        <span class="queue-state">{run.locked ? "Locked" : "Saved"}</span>
      </span>
      <span class="run-type">{kindWords(run.schedule)}</span>
      <span class="run-window">{windowWords(run.schedule)}</span>
      <span class="run-cagr" title={run.schedule.trials === undefined ? undefined : "Median trial CAGR"}>
        {cagr === null ? "—" : percent(cagr)}
      </span>
      <span class="run-time" title={new Date(savedAt(run)).toLocaleString()}>
        {formatTime(savedAt(run))}
      </span>
      <details class="run-menu" onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary id={`saved-menu-${run.id}`} aria-label={`Details of ${run.name}`}>
          Details
        </summary>
        {open && <RunDetails id={run.id} saved />}
        <div class="run-actions">
          {renaming !== null ? (
            <>
              <label class="saved-rename">
                New name
                <input
                  ref={input}
                  id={`saved-rename-${run.id}`}
                  value={renaming}
                  maxlength={120}
                  onInput={(event) => setRenaming(event.currentTarget.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void rename(renaming);
                    }
                    if (event.key === "Escape") {
                      event.preventDefault();
                      setRenaming(null);
                    }
                  }}
                />
              </label>
              {button("Save name", () => void rename(renaming))}
              {button("Cancel", () => setRenaming(null))}
            </>
          ) : confirming ? (
            <>
              <span>Delete this saved backtest?</span>
              {button("Delete record", () => void perform(() => client.deleteRun(run.id), "Saved backtest deleted."))}
              {button("Keep", () => setConfirming(false))}
            </>
          ) : (
            <>
              {button("Tune", () => tuneRun(run.id, perform, setNote))}
              {button("Rename", () => {
                setRenaming(run.name);
                setConfirming(false);
              })}
              {!run.locked && button("Delete", () => setConfirming(true))}
            </>
          )}
        </div>
      </details>
    </li>
  );
}
