import { useEffect, useState } from "preact/hooks";
import type { RunRow } from "../api/RunRow.ts";
import { defaultName, settingsOf } from "../describe.ts";
import { type Draft, defaultDraft, fromRun, readDraft, setMarket } from "../draft.ts";
import { go } from "../route.ts";

/** What Build strategy shows, kept in this module so that the other
 *  workspaces can load a run into it: the live draft (kept in localStorage)
 *  and the held run being edited, whose draft is separate and is not kept. */

/** A held run being edited: the run as GET /api/runs/{id} gave it, and the
 *  draft of its new settings. */
type Held = { run: RunRow; draft: Draft };

type BuildState = {
  live: Draft;
  held: Held | null;
  /** Counts the drafts loaded from a run, so the view starts each one on its
   *  first sleeve. */
  loads: number;
  /** The line under the builder's buttons: what the last load, add or edit
   *  did, or why it failed. */
  message: { text: string; failed: boolean } | null;
  /** Whether the live draft is the default one that the page started with,
   *  whose start the market's first session may still move. */
  fresh: boolean;
};

const KEY = "stock-backtest-draft";

function stored(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

const initial = readDraft(stored());
let state: BuildState = { live: initial, held: null, loads: 0, message: null, fresh: JSON.stringify(initial) === JSON.stringify(defaultDraft()) };
const listeners = new Set<(state: BuildState) => void>();

/** Changes the state; a new live draft is stored. */
export function update(change: Partial<BuildState>): void {
  if (change.live && change.live !== state.live) {
    try {
      localStorage.setItem(KEY, JSON.stringify(change.live));
    } catch {
      // A browser that keeps no storage keeps the draft until the page closes.
    }
  }
  state = { ...state, ...change };
  for (const listener of listeners) listener(state);
}

/** Changes the draft shown: the held run's while it is edited, else the live
 *  one. `edit` gets the current draft, so a change made meanwhile is kept. */
export function changeDraft(edit: (draft: Draft) => Draft): void {
  if (state.held) update({ held: { ...state.held, draft: edit(state.held.draft) } });
  else update({ live: edit(state.live), fresh: false });
}

/** Moves the start of the default draft inside the market's sessions, once,
 *  as a change of market does. A typed or copied start stays as it is. */
export function placeDefaultStart(sessions: { first: string; last: string }): void {
  if (state.fresh) update({ live: setMarket(state.live, state.live.market, sessions), fresh: false });
}

/** Whether a held run's edit is open in Build strategy. While it is, tune and
 *  editHeld are refused: hold no other run for an edit. */
export function heldEditOpen(): boolean {
  return state.held !== null;
}

const OPEN_EDIT = "Save or cancel the queued edit before replacing the strategy settings.";

/** Shows Build strategy with the refusal of a load while an edit is open. */
function refuseLoad(): void {
  update({ message: { text: OPEN_EDIT, failed: true } });
  go({ view: "build" });
}

export function useBuildState(): BuildState {
  const [current, setCurrent] = useState(state);
  useEffect(() => {
    listeners.add(setCurrent);
    setCurrent(state);
    return () => void listeners.delete(setCurrent);
  }, []);
  return current;
}

/** Puts a run's market, strategy and schedule into the live draft as a dated
 *  test with no name, and shows Build strategy. `run` is a reply of
 *  GET /api/runs/{id}. While a held edit is open, the live draft stays as it
 *  is and Build strategy says why. */
export function tune(run: RunRow): void {
  if (state.held) return refuseLoad();
  update({
    live: fromRun(run, state.live),
    loads: state.loads + 1,
    fresh: false,
    message: { text: "Settings copied to the strategy controls. Change them and add a new test.", failed: false },
  });
  go({ view: "build" });
}

/** Opens a held run's settings in Build strategy, with Save changes and
 *  Cancel edit, and shows it. The live draft stays as it is. `run` is a reply
 *  of GET /api/runs/{id} for a held run; the caller holds it first, after
 *  heldEditOpen() said no edit is open. While one is open, the new edit is
 *  refused and Build strategy says why. A name that is the default of the
 *  run's settings follows the edited settings. */
export function editHeld(run: RunRow): void {
  if (state.held) return refuseLoad();
  const draft = fromRun(run, state.live);
  draft.name = run.name === defaultName(settingsOf(run)) ? "" : run.name;
  update({ held: { run, draft }, loads: state.loads + 1, message: null });
  go({ view: "build" });
}
