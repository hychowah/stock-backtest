import assert from "node:assert/strict";
import { test } from "node:test";
import type { Market } from "./api/Market.ts";
import type { RunRow } from "./api/RunRow.ts";
import type { State } from "./api/State.ts";
import type { TrialsReply } from "./api/TrialsReply.ts";
import type { RunSettings } from "./describe.ts";
import { type Described, FIRST_SORTING, compareRuns, failureNote, inMarket, inProgress, marketButtons, marketCounts, queuePlaces, resorted, savedRuns, sortSaved } from "./runs.ts";

const run = (id: number, state: State, more: Partial<RunRow> = {}): RunRow => ({
  id,
  name: `Run ${id}`,
  market: "us",
  schedule: { start: "2021-07-01", end: "2023-06-28", every: "6m" },
  state,
  locked: false,
  created: "2026-11-15T06:00:00Z",
  ...more,
});
const ids = (runs: readonly RunRow[]) => runs.map((row) => row.id);

test("the queue panel holds the runs that are not complete; each waiting or held run has its place in the whole queue", () => {
  const list = [run(1, "running"), run(2, "waiting", { market: "hk" }), run(3, "held"), run(4, "waiting", { market: "hk" }), run(5, "failed"), run(6, "complete"), run(7, "stopped")];
  assert.deepEqual(ids(inProgress(list)), [1, 2, 3, 4, 5, 7]);
  assert.deepEqual(ids(savedRuns(list)), [6]);
  assert.deepEqual([...queuePlaces(list)], [
    [2, { place: 1, last: false }],
    [3, { place: 2, last: false }],
    [4, { place: 3, last: true }],
  ]);
  // A market's rows keep the places of the whole queue: HK run 4 is still in place 3.
  assert.deepEqual(ids(inMarket(list, "hk")), [2, 4]);
});

test("the market switch counts every state, shows the markets with data or runs, and keeps the chosen one", () => {
  const list = [run(1, "complete"), run(2, "waiting", { market: "hk" }), run(3, "failed", { market: "hk" }), run(4, "complete", { market: "jp" })];
  const counts = marketCounts(list);
  assert.deepEqual(counts, { "": 4, us: 1, hk: 2, jp: 1 });
  assert.deepEqual(marketButtons(counts, ["us", "hk"], ""), ["", "us", "hk", "jp"]);
  const none = marketCounts([run(1, "complete")]);
  assert.deepEqual(marketButtons(none, ["us", "hk"], ""), ["", "us", "hk"]);
  assert.deepEqual(marketButtons(none, ["us"], "jp"), ["", "us", "jp"]);
  assert.deepEqual(inMarket(list, ""), list);
});

const saved = (id: number, name: string, median: number | null, finished: string): RunRow =>
  run(id, "complete", {
    name,
    finished,
    outcome: { headline: { cagr: [], median: median as number, worst: 0, best: 0, spy_median: 0, beat_spy: 0, min_holdings: 0 }, generation: 1, as_of: "", program: "bt" },
  });

/** Four saved runs: Low is the oldest and Missing has no CAGR; Tie and High have the same CAGR and time. */
const table = [
  saved(1, "Low", -0.2, "2026-10-01T00:00:00Z"),
  saved(2, "High", 0.5, "2026-10-03T00:00:00Z"),
  saved(3, "Missing", null, "2026-10-02T00:00:00Z"),
  saved(4, "Tie", 0.5, "2026-10-03T00:00:00Z"),
];
const names = (runs: readonly RunRow[]) => runs.map((row) => row.name).join(" ");

test("a heading sorts the saved rows, and a second click reverses it", () => {
  let sorting = FIRST_SORTING;
  assert.equal(names(sortSaved(table, sorting)), "High Tie Missing Low");
  sorting = resorted(sorting, "cagr");
  assert.deepEqual(sorting, { key: "cagr", direction: -1 });
  assert.equal(names(sortSaved(table, sorting)), "High Tie Low Missing");
  sorting = resorted(sorting, "cagr");
  assert.equal(names(sortSaved(table, sorting)), "Low High Tie Missing", "a missing CAGR stays last");
  sorting = resorted(sorting, "name");
  assert.deepEqual(sorting, { key: "name", direction: 1 });
  assert.equal(names(sortSaved(table, sorting)), "High Low Missing Tie");
  assert.equal(names(sortSaved(table, resorted(sorting, "name"))), "Tie Missing Low High");
  assert.equal(names(sortSaved(table, resorted(FIRST_SORTING, "saved"))), "Low Missing High Tie");
});

test("names sort with their numbers in number order", () => {
  const numbered = ["Ranks 1–10", "Ranks 1–6", "Ranks 1–20"].map((name, i) => saved(i + 1, name, 0.1, "2026-10-01T00:00:00Z"));
  assert.equal(names(sortSaved(numbered, { key: "name", direction: 1 })), "Ranks 1–6 Ranks 1–10 Ranks 1–20");
});

test("a failed run's note is the server's message and its place in words", () => {
  const error = { message: "the strategy ranks nothing", place: "strategy: sleeves[1].steps[2]" };
  assert.equal(failureNote(run(1, "failed", { error })), "the strategy ranks nothing (Sleeve 1, step 2)");
  assert.equal(failureNote(run(1, "failed", { error: { ...error, place: "" } })), "the strategy ranks nothing");
  assert.equal(failureNote(run(1, "waiting")), "");
});

const settings = (market: Market, schedule: RunSettings["schedule"], to: number): RunSettings => ({
  market,
  schedule,
  strategy: { sleeves: [{ steps: [{ rank: "EBITDA yield", order: "highest", from: 1, to }] }] },
  steps: [[{ source: { kind: "built-in", name: "EBITDA yield" }, display: "percent" }]],
});
const trialsOf = (cagr: number): TrialsReply => ({
  trials: [{ trial: 1, dates: "2021-07-02", start: "2021-07-01", first_trade: "2021-07-02", end: "2023-06-28", cash_days: 1, periods: 4, cagr, spy_cagr: 0.05, excess_cagr: cagr - 0.05, total_return: 0, growth: 1.1, spy_growth: 1, empty_periods: 0, short_periods: 0 }],
  statistics: [{ statistic: "cagr.median", value: cagr }],
});
const described = (name: string, s: RunSettings, cagr: number): Described => ({ name, schedule: s.schedule, settings: s, trials: trialsOf(cagr) });

test("a comparison lists the settings that differ first, the others as the same, and the headline of each run", () => {
  const fixed = { start: "2021-07-01", end: "2023-06-28", every: "6m" };
  const result = compareRuns([described("A", settings("us", fixed, 5), 0.1), described("B", settings("hk", fixed, 3), 0.2)]);
  assert.deepEqual(result.differ.map((row) => [row.label, ...row.cells]), [
    ["Stock market", "US", "Hong Kong"],
    ["Step 1 · Rank", "EBITDA yield · highest first · ranks 1–5", "EBITDA yield · highest first · ranks 1–3"],
  ]);
  assert.deepEqual(result.same.map((row) => row.label), ["Test type", "Return currency", "Requested start", "Requested end", "Rebalance interval"]);
  assert.deepEqual(result.headline.map((row) => [row.label, ...row.cells]).slice(0, 3), [
    ["Strategy CAGR", "10.00%", "20.00%"],
    ["SPY CAGR", "5.00%", "5.00%"],
    ["Difference vs SPY", "+5.00 pp", "+15.00 pp"],
  ]);
  assert.deepEqual(result.measures, []);
  assert.deepEqual(result.notices, []);
});

test("a run that lacks a line differs from one that has it; tests of different types are said", () => {
  const fixed = { start: "2021-07-01", end: "2023-06-28", every: "6m" };
  const random = { ...fixed, trials: 3, seed: 7 };
  const result = compareRuns([described("A", settings("us", fixed, 5), 0.1), described("B", settings("us", random, 5), 0.2)]);
  assert.deepEqual(result.differ.map((row) => [row.label, ...row.cells]), [
    ["Test type", "Fixed dates", "Random dates"],
    ["Trials", "—", "3"],
  ]);
  assert.deepEqual(result.seed.map((row) => [row.label, ...row.cells]), [["Random date set", "—", "7"]]);
  assert.equal(result.notices.length, 2);
  assert.match(result.notices[1]!, /different test types/);
  assert.deepEqual(result.measures.map((row) => [row.label, row.cells[0]]).slice(0, 1), [["Mean strategy CAGR", "—"]]);
});

test("the random date set never makes two runs differ; its row stands apart, with each run's value", () => {
  const base = { start: "2021-07-01", end: "2023-06-28", every: "6m", trials: 3 };
  const result = compareRuns([described("A", settings("us", { ...base, seed: 7 }, 5), 0.1), described("B", settings("us", { ...base, seed: 8 }, 5), 0.2)]);
  assert.deepEqual(result.differ, []);
  assert.ok(result.same.length > 0);
  assert.ok(result.same.every((row) => row.label !== "Random date set"));
  assert.deepEqual(result.seed.map((row) => [row.label, ...row.cells]), [["Random date set", "7", "8"]]);
  const fixed = { start: "2021-07-01", end: "2023-06-28", every: "6m" };
  assert.deepEqual(compareRuns([described("A", settings("us", fixed, 5), 0.1), described("B", settings("us", fixed, 3), 0.2)]).seed, []);
});
