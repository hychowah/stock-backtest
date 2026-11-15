import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import type { Market } from "./api/Market.ts";
import type { RunRow } from "./api/RunRow.ts";
import type { Schedule } from "./api/Schedule.ts";
import type { StrategyFile } from "./api/StrategyFile.ts";
import type { Variable } from "./api/Variable.ts";
import {
  addStep,
  commitRanks,
  copySleeve,
  defaultDraft,
  type Draft,
  editStep,
  formOf,
  fromRun,
  moveStep,
  readDraft,
  removeSleeve,
  removeStep,
  renameSleeve,
  resetStrategy,
  scheduleOf,
  setMarket,
  setSource,
  sleeveName,
  strategyFile,
} from "./draft.ts";
import { requestVariables } from "./variables.ts";

const shape = (draft: Draft, sleeve = 0) => draft.sleeves[sleeve]!.steps.map(({ id: _id, ...step }) => step);
const ids = (draft: Draft, sleeve = 0) => draft.sleeves[sleeve]!.steps.map((step) => step.id);

const run = (market: Market, schedule: Schedule, strategy: StrategyFile): RunRow => ({
  id: 1,
  name: "Run",
  market,
  schedule,
  state: "complete",
  locked: false,
  created: "2026-11-15T06:00:00Z",
  strategy,
});

test("a new filter goes before the last Rank, a new Rank goes last", () => {
  const [withFilter, filterId] = addStep(defaultDraft(), 0, "filter", "P/E", false);
  assert.deepEqual(shape(withFilter).map((step) => ("rank" in step ? step.rank : step.filter)), ["Market cap", "Enterprise value", "P/E", "EBITDA yield"]);
  assert.deepEqual(shape(withFilter)[2], { filter: "P/E", op: ">", value: "" });
  assert.equal(new Set(ids(withFilter)).size, 4);
  assert.ok(ids(withFilter).includes(filterId));

  const [withRank] = addStep(withFilter, 0, "rank", "ROE", false);
  assert.deepEqual(shape(withRank).at(-1), { rank: "ROE", order: "highest", from: 1, to: 50 });

  // A text source takes is with no value; with no Rank a filter goes last.
  const [text] = addStep(removeStep(defaultDraft(), 0, 3), 0, "filter", "Sector", true);
  assert.deepEqual(shape(text).at(-1), { filter: "Sector", op: "is", value: "" });
});

test("a filter's new source keeps a typed number, and text sources compare with is", () => {
  let draft = editStep(defaultDraft(), 0, 1, { op: "<", value: "250" });
  draft = setSource(draft, 0, 1, "Market cap in dollars", false);
  assert.deepEqual(shape(draft)[0], { filter: "Market cap in dollars", op: "<", value: "250" });
  draft = setSource(draft, 0, 1, "Exchange", true);
  assert.deepEqual(shape(draft)[0], { filter: "Exchange", op: "is", value: "" });
  draft = editStep(draft, 0, 1, { op: "is not", value: "NASDAQ" });
  draft = setSource(draft, 0, 1, "P/E", false);
  assert.deepEqual(shape(draft)[0], { filter: "P/E", op: ">", value: "" }, "is not becomes a number comparison");
  draft = setSource(draft, 0, 3, "ROE", false);
  assert.deepEqual(shape(draft)[2], { rank: "ROE", order: "highest", from: 1, to: 50 });
});

test("moving and removing steps keeps their ids; ranks stay in order", () => {
  const draft = defaultDraft();
  const moved = moveStep(draft, 0, 3, -1);
  assert.deepEqual(ids(moved), [1, 3, 2]);
  assert.deepEqual(ids(removeStep(moved, 0, 3)), [1, 2]);

  const typed = editStep(draft, 0, 3, { from: 60 });
  assert.deepEqual(shape(commitRanks(typed, 0, 3, "from"))[2], { rank: "EBITDA yield", order: "highest", from: 60, to: 60 });
  assert.deepEqual(shape(commitRanks(editStep(draft, 0, 3, { from: 20, to: 10 }), 0, 3, "to"))[2], { rank: "EBITDA yield", order: "highest", from: 10, to: 10 });
});

test("sleeves: copy, rename, remove and their default names", () => {
  let draft = copySleeve(defaultDraft(), 0);
  assert.equal(draft.sleeves.length, 2);
  assert.deepEqual(shape(draft, 1), shape(draft, 0));
  assert.equal(new Set([...ids(draft, 0), ...ids(draft, 1)]).size, 6, "the copy has new ids");
  assert.deepEqual(draft.sleeves.map(sleeveName), ["Sleeve 1", "Sleeve 2"]);

  // A sleeve takes the value of its sector Is filter as its name until one is typed.
  const [sector, id] = addStep(draft, 1, "filter", "Sector", true);
  draft = editStep(sector, 1, id, { value: "Technology" });
  assert.equal(sleeveName(draft.sleeves[1]!, 1), "Technology");
  draft = renameSleeve(draft, 1, "Tech");
  assert.equal(sleeveName(draft.sleeves[1]!, 1), "Tech");
  assert.deepEqual(
    strategyFile(draft, []).sleeves.map((sleeve) => sleeve.name),
    ["Sleeve 1", "Tech"],
  );

  draft = removeSleeve(draft, 0);
  assert.deepEqual(draft.sleeves.map(sleeveName), ["Tech"]);
  assert.equal(removeSleeve(draft, 0), draft, "the last sleeve stays");
  assert.equal(strategyFile(renameSleeve(draft, 0, ""), []).sleeves[0]!.name, undefined, "one sleeve with no typed name has none");
});

test("reset keeps the mode, market, dates and name; another market moves the window", () => {
  const draft = { ...copySleeve(defaultDraft(), 0), mode: "backtest" as const, market: "hk" as const, name: "Mine", variables: { A: { formula: "ROE", display: "percent" } } };
  const reset = resetStrategy(draft);
  assert.deepEqual(reset.sleeves, defaultDraft().sleeves);
  assert.deepEqual(reset.variables, {});
  assert.deepEqual([reset.mode, reset.market, reset.name, reset.schedule], [draft.mode, draft.market, draft.name, draft.schedule]);

  const ended = { ...draft, schedule: { ...draft.schedule, start: "2010-01-01", end: "2020-01-01" } };
  const moved = setMarket(ended, "jp", { first: "2015-12-01", last: "2023-06-30" });
  assert.deepEqual([moved.market, moved.schedule.start, moved.schedule.end], ["jp", "2015-12-01", ""]);
});

test("a stored draft reads back, and one that does not read is the default", () => {
  const draft = copySleeve({ ...defaultDraft(), mode: "backtest" }, 0);
  assert.deepEqual(readDraft(JSON.stringify(draft)), draft);
  assert.deepEqual(readDraft(null), defaultDraft());
  assert.deepEqual(readDraft("{"), defaultDraft());
  assert.deepEqual(readDraft(JSON.stringify({ ...draft, extra: 1 })), defaultDraft());
  assert.deepEqual(readDraft(JSON.stringify({ ...draft, sleeves: [] })), defaultDraft());
  const badStep = { ...draft, sleeves: [{ name: "", steps: [{ rank: "P/E", order: "up", from: 1, to: 2, id: 1 }] }] };
  assert.deepEqual(readDraft(JSON.stringify(badStep)), defaultDraft());
  for (const below of [{ count: -1 }, { count: 0 }, { trials: 0 }, { seed: -1 }]) {
    assert.deepEqual(readDraft(JSON.stringify({ ...draft, schedule: { ...draft.schedule, ...below } })), defaultDraft(), JSON.stringify(below));
  }
});

test("the schedule form and a schedule convert both ways", () => {
  const base = defaultDraft().schedule;
  const schedules: Schedule[] = [
    { start: "2021-07-01", end: "2023-06-28", every: "6m" },
    { start: "2021-07-01", end: "2023-06-28", every: "3m", trials: 24, seed: 7 },
    { start: "2021-07-01", end: "2023-06-28", every: "2w", trials: 1000, seed: 0 },
    { start: "2023-01-02", end: "2023-03-31", every: "2w" },
    { start: "2021-07-01", end: "2023-06-28", every: "5m" },
    { start: "2021-07-01", end: "2023-06-28", dates: ["2021-09-24", "2022-01-13"] },
  ];
  for (const schedule of schedules) assert.deepEqual(scheduleOf(formOf(schedule, base), "2023-06-30"), schedule);

  assert.deepEqual(formOf(schedules[0]!, base), { ...base, start: "2021-07-01", end: "2023-06-28", months: 6, custom: false, testing: "single" });
  assert.deepEqual(formOf(schedules[3]!, base), { ...base, start: "2023-01-02", end: "2023-03-31", custom: true, count: 2, unit: "week", testing: "single" });

  // The default form: random trials every 12 months to the last session, with a seed drawn by the server.
  assert.deepEqual(scheduleOf(base, "2023-06-30"), { start: "2015-01-01", end: "2023-06-30", every: "12m", trials: 24 });
  assert.deepEqual(scheduleOf({ ...base, repeat: true, custom: true, count: 3, unit: "month" }, "2023-06-30"), { start: "2015-01-01", end: "2023-06-30", every: "3m", trials: 24, seed: 42 });
});

test("a run's strategy file comes back from its draft unchanged, for each fictional case", () => {
  // The cases' strategy files: those of the built-in cases are in canonical
  // form; those of the formula cases differ from it only by the variables'
  // displays, which a draft copies as it gets them.
  const root = new URL("../../fixtures/fictional/cases/", import.meta.url);
  let checked = 0;
  for (const group of readdirSync(root)) {
    for (const name of readdirSync(new URL(group + "/", root))) {
      const folder = new URL(`${group}/${name}/`, root);
      const strategy = JSON.parse(readFileSync(new URL("strategy.json", folder), "utf8")) as StrategyFile;
      const settings = JSON.parse(readFileSync(new URL("run.json", folder), "utf8")) as { market: Market; interval?: string } & Schedule;
      const { market, interval, ...schedule } = settings;
      const row = run(market, { ...schedule, ...(interval ? { every: interval } : {}) }, strategy);
      const draft = fromRun(row);
      assert.deepEqual(strategyFile(draft, []), strategy, `${group}/${name}`);
      assert.deepEqual(scheduleOf(draft.schedule, ""), row.schedule, `${group}/${name}`);
      assert.deepEqual([draft.mode, draft.market, draft.name], ["backtest", market, ""]);
      checked++;
    }
  }
  assert.ok(checked > 0, "the cases were read");
});

test("a sleeve name equal to its default follows the sector filter again; a typed one stays", () => {
  const strategy: StrategyFile = {
    sleeves: [
      { name: "Technology", steps: [{ filter: "Sector", op: "is", value: "Technology" }, { rank: "ROE", order: "highest", from: 1, to: 3 }] },
      { name: "Sleeve 2", steps: [{ rank: "P/E", order: "lowest", from: 1, to: 3 }] },
      { name: "Own", steps: [{ rank: "P/B", order: "lowest", from: 1, to: 3 }] },
    ],
  };
  const draft = fromRun(run("us", { start: "2021-07-01", end: "2023-06-28", every: "12m" }, strategy));
  assert.deepEqual(draft.sleeves.map((sleeve) => sleeve.name), ["", "", "Own"]);
  assert.deepEqual(strategyFile(draft, []), strategy);
  const one: StrategyFile = { sleeves: [{ name: "Sleeve 1", steps: [{ rank: "P/E", order: "lowest", from: 1, to: 3 }] }] };
  assert.deepEqual(strategyFile(fromRun(run("us", { start: "2021-07-01", end: "2023-06-28", every: "12m" }, one)), []), one, "one sleeve keeps its stored name");
});

test("a strategy file carries the variables of the request, and none when there are none", () => {
  const library: Variable[] = [{ id: 1, name: "Cheap", formula: "1 / P/E", display: "percent", favourite: false, uses: [] }];
  const draft = { ...defaultDraft(), variables: { Quality: { formula: "ROE", display: "percent" } } };
  assert.deepEqual(strategyFile(draft, library).variables, requestVariables(draft.variables, library));
  assert.equal("variables" in strategyFile(defaultDraft(), []), false);
});
