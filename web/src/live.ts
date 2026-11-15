import { useEffect, useState } from "preact/hooks";
import type { RunsReply } from "./api/RunsReply.ts";
import type { Variable } from "./api/Variable.ts";
import { ApiFailure, client } from "./client.ts";
import { asFailure } from "./read.ts";

/** The server state that several workspaces share.
 *  useRuns(): the run list for the status bar, the queue tray and Runs & saved.
 *  It reads GET /api/runs every 2 s while a run waits or runs, every 15 s
 *  otherwise, and at once after a change or when the page becomes visible.
 *  act(change) sends one change, then reads the list again. A list asked for
 *  before the latest change is dropped, so a row never steps back. act() gives
 *  a failure back to its caller, which shows it beside the control.
 *  useLibrary(): the variable library, read at start and after each change
 *  sent with changeLibrary(change), which works as act() does.
 *  lastResult: the result last opened, the target of the nav's Result review.
 *
 *  Both lists are read while at least one view watches them; a failed read
 *  keeps the last list and sets `failure` (status 0: the server does not
 *  answer) until a read succeeds. */

/** What a view sees of a shared list: the last list read (null before the
 *  first answer) and the failure of the last read, if it failed. */
export type Shared<T> = { value: T | null; failure: ApiFailure | null };

class SharedList<T> {
  #state: Shared<T> = { value: null, failure: null };
  #listeners = new Set<(state: Shared<T>) => void>();
  #read: () => Promise<T>;
  /** The delay in ms before the next read after one, or null for none. */
  #interval: (value: T | null) => number | null;
  #sequence = 0;
  #applied = 0;
  /** Changes when a change starts and when it ends: a reply to a read asked
   *  at another epoch may not hold that change, so it is dropped. */
  #epoch = 0;
  #timer: ReturnType<typeof setTimeout> | undefined;

  constructor(read: () => Promise<T>, interval: (value: T | null) => number | null) {
    this.#read = read;
    this.#interval = interval;
  }

  watch(listener: (state: Shared<T>) => void): () => void {
    this.#listeners.add(listener);
    listener(this.#state);
    if (this.#listeners.size === 1) void this.refresh();
    return () => {
      this.#listeners.delete(listener);
      if (!this.#listeners.size) clearTimeout(this.#timer);
    };
  }

  async refresh(): Promise<void> {
    const sequence = ++this.#sequence;
    const epoch = this.#epoch;
    clearTimeout(this.#timer);
    let next: Shared<T>;
    try {
      next = { value: await this.#read(), failure: null };
    } catch (thrown) {
      next = { value: this.#state.value, failure: asFailure(thrown) };
    }
    if (sequence > this.#applied && epoch === this.#epoch) {
      this.#applied = sequence;
      this.#state = next;
      for (const listener of this.#listeners) listener(next);
    }
    if (sequence === this.#sequence && this.#listeners.size) {
      const delay = this.#interval(this.#state.value);
      if (delay !== null) this.#timer = setTimeout(() => void this.refresh(), delay);
    }
  }

  async change<R>(send: () => Promise<R>): Promise<R> {
    this.#epoch++;
    try {
      return await send();
    } finally {
      this.#epoch++;
      void this.refresh();
    }
  }
}

const busy = (reply: RunsReply | null) => reply?.runs.some((run) => run.state === "waiting" || run.state === "running") ?? false;
const runs = new SharedList<RunsReply>(client.runs, (reply) => (busy(reply) ? 2000 : 15000));
const library = new SharedList<Variable[]>(client.variables, () => null);

globalThis.document?.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") void runs.refresh();
});

/** Calls `listener` with the run list now and after each read; returns the
 *  function that stops it. It is the run list outside a view, where hooks
 *  cannot run, such as a test with a fake fetch. */
export function watchRuns(listener: (state: Shared<RunsReply>) => void): () => void {
  return runs.watch(listener);
}

/** The run list, kept current as the comment at the top says. */
export function useRuns(): Shared<RunsReply> {
  return useShared(runs);
}

/** Sends one change of a run or the queue, such as
 *  `act(() => client.stop(id))`, then reads the list again. It returns the
 *  change's reply or throws its ApiFailure. */
export function act<R>(change: () => Promise<R>): Promise<R> {
  return runs.change(change);
}

/** The variable library, in dependency order. */
export function useLibrary(): Shared<Variable[]> {
  return useShared(library);
}

/** Sends one change of the library, such as
 *  `changeLibrary(() => client.addVariable(entry))`, then reads it again. */
export function changeLibrary<R>(change: () => Promise<R>): Promise<R> {
  return library.change(change);
}

/** The id of the result last opened in this page, or null. The shell sets it
 *  when the address names a result. */
export const lastResult: { id: number | null } = { id: null };

/** The time now in ms, renewed every second while `ticking`: for the time
 *  since a run started. */
export function useNow(ticking: boolean): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!ticking) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [ticking]);
  return now;
}

function useShared<T>(list: SharedList<T>): Shared<T> {
  const [state, setState] = useState<Shared<T>>({ value: null, failure: null });
  useEffect(() => list.watch(setState), [list]);
  return state;
}
