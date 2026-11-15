import type { Market } from "./api/Market.ts";
import type { RunRow } from "./api/RunRow.ts";
import type { Schedule } from "./api/Schedule.ts";
import type { State } from "./api/State.ts";
import type { TrialsReply } from "./api/TrialsReply.ts";
import { type Line, type RunSettings, headlineCells, measureLines, settingsLines } from "./describe.ts";
import { placeInWords } from "./format.ts";

/** The rules of Runs & saved, with no DOM.
 *
 *  The run list is one list: the queue panel shows the runs that are not
 *  complete, and the saved table shows the complete runs. The server gives the
 *  list in queue order (running first, then waiting and held in queue order,
 *  then the others, newest first), and the panel keeps that order. The market
 *  switch filters both tables. Every number shown is written by the server or
 *  by describe.ts; nothing here computes a statistic. */

/** The market switch's choice: one market, or "" for all of them. */
export type MarketChoice = Market | "";

const MARKETS: Market[] = ["us", "hk", "jp"];
const CHOICE_WORDS: Record<MarketChoice, string> = { "": "All", us: "US", hk: "Hong Kong", jp: "Tokyo" };

/** A choice as the switch and the empty lists write it: All, US, Hong Kong, Tokyo. */
export const choiceWords = (choice: MarketChoice) => CHOICE_WORDS[choice];

/** The runs of the choice. */
export const inMarket = (runs: readonly RunRow[], choice: MarketChoice) => (choice ? runs.filter((run) => run.market === choice) : [...runs]);

/** Each choice with its number of runs, all states together. */
export function marketCounts(runs: readonly RunRow[]): Record<MarketChoice, number> {
  const counts: Record<MarketChoice, number> = { "": runs.length, us: 0, hk: 0, jp: 0 };
  for (const run of runs) counts[run.market]++;
  return counts;
}

/** The buttons of the switch: All, then each market that has prepared data or
 *  runs, and the chosen market. */
export function marketButtons(counts: Record<MarketChoice, number>, prepared: readonly Market[], chosen: MarketChoice): MarketChoice[] {
  return ["", ...MARKETS.filter((market) => prepared.includes(market) || counts[market] > 0 || market === chosen)];
}

/** The queue panel's runs: every run that is not complete. */
export const inProgress = (runs: readonly RunRow[]) => runs.filter((run) => run.state !== "complete");

/** The saved table's runs: every complete run. */
export const savedRuns = (runs: readonly RunRow[]) => runs.filter((run) => run.state === "complete");

/** A run's place among the waiting and held runs of the whole list (from 1,
 *  as POST /api/runs/{id}/move counts), and whether it is the last. A run
 *  in another state has none. The market switch never changes a place. */
export function queuePlaces(runs: readonly RunRow[]): Map<number, { place: number; last: boolean }> {
  const queued = runs.filter((run) => run.state === "waiting" || run.state === "held");
  return new Map(queued.map((run, i) => [run.id, { place: i + 1, last: i === queued.length - 1 }]));
}

const STATE_WORDS: Record<State, string> = {
  waiting: "Waiting",
  held: "Held",
  running: "Running",
  complete: "Saved",
  failed: "Failed",
  stopped: "Stopped",
};

/** The words of a run's state in the queue panel. */
export const stateWords = (state: State) => STATE_WORDS[state];

/** The value of a row's `data-state`, which the carried CSS colours: it names
 *  a stopped run `cancelled`. */
export const rowState = (state: State) => (state === "stopped" ? "cancelled" : state);

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

/** A row's test type: `Random · 24 trials` or `Fixed dates`. */
export const kindWords = (schedule: Schedule) => (schedule.trials === undefined ? "Fixed dates" : `Random · ${plural(schedule.trials, "trial")}`);

/** A row's window: `2021-07-01 → 2023-06-28`. */
export const windowWords = (schedule: Schedule) => `${schedule.start} → ${schedule.end}`;

/** The note under a failed run's state: the server's message, then its place
 *  in words. */
export function failureNote(run: RunRow): string {
  if (!run.error) return "";
  return run.error.place ? `${run.error.message} (${placeInWords(run.error.place)})` : run.error.message;
}

/** The time a complete run was saved: when it finished (a result added by
 *  `bt save` has no start, but it has a finish), else when it was created. */
export const savedAt = (run: RunRow) => run.finished ?? run.created;

/** A saved row's CAGR column: the median CAGR of its trials, which for one
 *  trial is its CAGR. Null when the run has none. */
export function savedCagr(run: RunRow): number | null {
  const value = run.outcome?.headline.median;
  return value !== undefined && Number.isFinite(value) ? value : null;
}

/** The heading that sorts the saved table. */
export type SortKey = "name" | "cagr" | "saved";
/** `direction` 1 is ascending, -1 descending. */
export type Sorting = { key: SortKey; direction: 1 | -1 };

/** The first sorting: the newest saved run first. */
export const FIRST_SORTING: Sorting = { key: "saved", direction: -1 };

const FIRST_DIRECTION: Record<SortKey, 1 | -1> = { name: 1, cagr: -1, saved: -1 };

/** The sorting after a click on a heading: another heading starts in its
 *  first direction, the same heading reverses. */
export function resorted(current: Sorting, key: SortKey): Sorting {
  return current.key === key ? { key, direction: current.direction === 1 ? -1 : 1 } : { key, direction: FIRST_DIRECTION[key] };
}

/** The saved rows in order. Names sort with their numbers in number order. A
 *  missing CAGR stays last in both directions. Equal values show the newest
 *  saved first, then the lower id; sorting by Saved keeps the lower id first
 *  in both directions. */
export function sortSaved(runs: readonly RunRow[], { key, direction }: Sorting): RunRow[] {
  const byId = (a: RunRow, b: RunRow) => a.id - b.id;
  const newest = (a: RunRow, b: RunRow) => savedAt(b).localeCompare(savedAt(a)) || byId(a, b);
  return [...runs].sort((a, b) => {
    if (key === "saved") return direction * savedAt(a).localeCompare(savedAt(b)) || byId(a, b);
    if (key === "name") return direction * a.name.localeCompare(b.name, undefined, { numeric: true }) || newest(a, b);
    const [x, y] = [savedCagr(a), savedCagr(b)];
    if (x === null || y === null) return x === y ? newest(a, b) : x === null ? 1 : -1;
    return direction * (x - y) || newest(a, b);
  });
}

/** One complete run as Compare reads it: its name, schedule, settings and
 *  trials reply. */
export type Described = { name: string; schedule: Schedule; settings: RunSettings; trials: TrialsReply };

/** One row of a comparison: a labelled line with one cell for each run. */
export type CompareRow = { key: string; label: string; cells: string[] };

/** The comparison of two or more runs. `differ` holds the settings lines
 *  that are not the same text in every run (a run without the line counts as
 *  different); `same` the others. The random date set is a recorded fact, not
 *  a setting: the server draws it when a run is added, so it never makes two
 *  runs differ, and `seed` holds its row (each run's value) apart from both
 *  lists, or none when no run has random dates. The headline cells and the
 *  other measures are aligned by key. A run lacks a line: a dash. */
export type Comparison = { differ: CompareRow[]; same: CompareRow[]; seed: CompareRow[]; headline: CompareRow[]; measures: CompareRow[]; notices: string[] };

const MISSING = "—";

/** Rows of the runs' lines, aligned by key in the order each key first
 *  appears; a label is the distinct labels of the runs, joined by " / ". */
function align(lists: Line[][]): CompareRow[] {
  const keys = [...new Set(lists.flatMap((lines) => lines.map((line) => line.key)))];
  return keys.map((key) => {
    const found = lists.map((lines) => lines.find((line) => line.key === key));
    const labels = [...new Set(found.flatMap((line) => (line ? [line.label] : [])))];
    return { key, label: labels.join(" / "), cells: found.map((line) => line?.text ?? MISSING) };
  });
}

const differs = (row: CompareRow) => row.cells.some((cell) => cell !== row.cells[0]);

/** Compares runs, in the order given: the settings lines of each
 *  (describe.ts), their headline cells and, for random dates, their other
 *  measures. */
export function compareRuns(runs: readonly Described[]): Comparison {
  const lines = runs.map((run) => settingsLines(run.settings));
  const settings = align(lines.map((own) => own.filter((line) => line.key !== "seed")));
  const seed = align(lines.map((own) => own.filter((line) => line.key === "seed")));
  const random = runs.some((run) => run.schedule.trials !== undefined);
  const notices = [];
  if (random) notices.push("Random dates: the median trial CAGR is not one portfolio return, and percentiles are not confidence intervals.");
  if (new Set(runs.map((run) => run.schedule.trials !== undefined)).size > 1) notices.push("These tests use different test types; their measures can differ.");
  return {
    differ: settings.filter(differs),
    same: settings.filter((row) => !differs(row)),
    seed,
    headline: align(runs.map((run) => headlineCells(run.schedule, run.trials))),
    measures: random ? align(runs.map((run) => (run.schedule.trials !== undefined ? measureLines(run.trials) : []))) : [],
    notices,
  };
}
