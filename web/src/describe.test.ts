import assert from "node:assert/strict";
import { test } from "node:test";
import type { TrialRow } from "./api/TrialRow.ts";
import type { TrialsReply } from "./api/TrialsReply.ts";
import type { RunRow } from "./api/RunRow.ts";
import { type Cell, defaultName, headlineCells, measureLines, rankingOf, readEvery, type RunSettings, settingsLines, settingsOf, tradeDays, trailOf, writeEvery } from "./describe.ts";

/** One sleeve: a size floor in $ million, then the Rank. */
const one: RunSettings = {
  market: "us",
  schedule: { start: "2021-07-01", end: "2023-06-28", every: "3m", trials: 24, seed: 7 },
  strategy: {
    sleeves: [
      {
        steps: [
          { filter: "Market cap", op: ">=", value: "100" },
          { filter: "Sector", op: "is not", value: "Utilities" },
          { rank: "EBITDA yield", order: "highest", from: 1, to: 50 },
        ],
      },
    ],
  },
  steps: [
    [
      { source: { kind: "built-in", name: "Market cap" }, display: "usd_million" },
      { source: { kind: "field", name: "Sector" }, display: "text" },
      { source: { kind: "built-in", name: "EBITDA yield" }, display: "percent" },
    ],
  ],
};

/** Two sleeves on fixed dates in Hong Kong, with a variable. */
const two: RunSettings = {
  market: "hk",
  schedule: { start: "2021-01-04", end: "2022-12-30", dates: ["2021-01-04", "2022-01-03"] },
  strategy: {
    variables: { Cheap: { formula: "1 / P/E", display: "percent" } },
    sleeves: [
      { name: "Land", steps: [{ filter: "Enterprise value in dollars", op: "<", value: "13600000000" }, { rank: "Cheap", order: "highest", from: 1, to: 2 }] },
      { name: "Large", steps: [{ rank: "Market cap in dollars", order: "lowest", from: 1, to: 3 }] },
    ],
  },
  steps: [
    [
      { source: { kind: "field", name: "Enterprise value in dollars" }, display: "usd" },
      { source: { kind: "variable", name: "Cheap" }, display: "percent" },
    ],
    [{ source: { kind: "field", name: "Market cap in dollars" }, display: "usd" }],
  ],
};

test("an interval and a trial's dates are read", () => {
  assert.deepEqual(readEvery("3m"), { count: 3, unit: "month" });
  assert.deepEqual(readEvery("104w"), { count: 104, unit: "week" });
  assert.equal(writeEvery({ count: 2, unit: "week" }), "2w");
  assert.deepEqual(readEvery("+3m"), readEvery("03m"));
  assert.deepEqual(readEvery("03m"), { count: 3, unit: "month" });
  assert.throws(() => readEvery("3x"));
  assert.deepEqual(tradeDays("2021-07-02 2021-10-04"), ["2021-07-02", "2021-10-04"]);
});

test("the settings lines name the market, window, interval, trials and each step in its display", () => {
  assert.deepEqual(
    settingsLines(one).map((line) => `${line.label}: ${line.text}`),
    [
      "Test type: Random dates",
      "Stock market: US",
      "Return currency: USD",
      "Requested start: 2021-07-01",
      "Requested end: 2023-06-28",
      "Rebalance interval: 3 months",
      "Trials: 24",
      "Random date set: 7",
      "Step 1 · Filter: Market cap ≥ $100M",
      "Step 2 · Filter: Sector is not Utilities",
      "Step 3 · Rank: EBITDA yield · highest first · ranks 1–50",
    ],
  );
});

test("sleeves name their steps, and fixed dates and variables are listed", () => {
  const lines = settingsLines(two);
  assert.deepEqual(
    lines.map((line) => `${line.key} | ${line.label}: ${line.text}`),
    [
      "type | Test type: Fixed dates",
      "market | Stock market: Hong Kong",
      "currency | Return currency: USD",
      "start | Requested start: 2021-01-04",
      "end | Requested end: 2022-12-30",
      "dates | Trade dates: 2021-01-04, 2022-01-03",
      "variable.Cheap | Variable · Cheap: 1 / P/E",
      "sleeve.1.step.1 | Land · Step 1 · Filter: Enterprise value in dollars < $13,600,000,000",
      "sleeve.1.step.2 | Land · Step 2 · Rank: Cheap · highest first · ranks 1–2",
      "sleeve.2.step.1 | Large · Step 1 · Rank: Market cap in dollars · lowest first · ranks 1–3",
    ],
  );
});

test("a run read alone gives its settings; a list row does not", () => {
  const row: RunRow = { id: 3, name: "x", market: "us", schedule: one.schedule, state: "complete", locked: false, created: "2026-11-15T06:00:00Z" };
  assert.throws(() => settingsOf(row));
  const full: RunRow = {
    ...row,
    strategy: one.strategy,
    description: { variables: [], ranks: [1, 50], sleeves: [{ name: null, steps: one.steps[0]!.map((step) => ({ step: "filter" as const, unit: "USD", ...step })) }] },
  };
  assert.deepEqual(settingsLines(settingsOf(full)), settingsLines(one));
});

/** A trial with these CAGRs, in the shape of the trials reply. */
const trial = (n: number, cagr: number, spy: number): TrialRow => ({
  trial: n, dates: "2021-07-02", start: "2021-07-01", first_trade: "2021-07-02", end: "2023-06-28", cash_days: 1, periods: 8,
  cagr, spy_cagr: spy, excess_cagr: cagr - spy, total_return: 0, growth: 1.1, spy_growth: 1, empty_periods: 0, short_periods: 0,
});
const stats = (rows: Record<string, number>): TrialsReply["statistics"] => Object.entries(rows).map(([statistic, value]) => ({ statistic, value }));

/** CAGRs [0, .20, .21] against SPY [.10, .19, .30]: the medians differ by
 *  +1 pp, but the median trial is 9 pp behind SPY. */
const random: TrialsReply = {
  trials: [trial(1, 0, 0.1), trial(2, 0.2, 0.19), trial(3, 0.21, 0.3)],
  statistics: stats({
    completed: 3, valid: 3, incomplete: 0, beat_spy: 1,
    "cagr.median": 0.2, "cagr.mean": 0.1366667, "cagr.min": 0, "cagr.max": 0.21, "cagr.p10": 0.04, "cagr.p90": 0.208, "cagr.stddev": 0.0966,
    "spy_cagr.median": 0.19, "excess_cagr.median": -0.09, "excess_cagr.mean": -0.06, "excess_cagr.min": -0.1, "excess_cagr.max": 0.01,
  }),
};
const cells = (list: Cell[]) => list.map((cell) => [cell.label, cell.text, cell.tone]);

test("the headline of random dates is the trials' statistics, with the median difference to SPY", () => {
  assert.deepEqual(cells(headlineCells(one.schedule, random)), [
    ["Median strategy CAGR", "20.00%", undefined],
    ["Median SPY CAGR", "19.00%", undefined],
    ["Median difference vs SPY", "-9.00 pp", "down"],
    ["Trials beating SPY", "1/3", undefined],
    ["Worst trial CAGR", "0.00%", undefined],
    ["Best trial CAGR", "21.00%", undefined],
  ]);
  assert.deepEqual(
    measureLines(random).map((line) => `${line.label}: ${line.text}`),
    [
      "Mean strategy CAGR: 13.67%",
      "Strategy CAGR, P10 to P90: 4.00% to 20.80%",
      "Std. dev. of strategy CAGR: 9.66%",
      "Mean difference vs SPY: -6.00 pp",
      "Difference vs SPY, worst to best: -10.00 pp to +1.00 pp",
      "Trials: 3",
    ],
  );
});

test("a missing statistic is a dash, and incomplete trials are said", () => {
  const partial: TrialsReply = { trials: [], statistics: stats({ completed: 4, valid: 3, incomplete: 1, beat_spy: 2, "cagr.median": 0.1, "cagr.p10": 0.01 }) };
  const shown = cells(headlineCells(one.schedule, partial));
  assert.deepEqual(shown[2], ["Median difference vs SPY", "—", undefined]);
  assert.deepEqual(shown[3], ["Trials beating SPY", "2/3 complete", undefined]);
  const lines = measureLines(partial).map((line) => line.text);
  assert.deepEqual([lines[1], lines[5]], ["—", "3 of 4 complete"]);
});

test("the headline of one trial is its CAGR, SPY's, the difference and the growth of $1", () => {
  const fixed: TrialsReply = { trials: [trial(1, 0.1, 0.05)], statistics: stats({ completed: 1, "cagr.median": 0.1 }) };
  assert.deepEqual(cells(headlineCells(two.schedule, fixed)), [
    ["Strategy CAGR", "10.00%", undefined],
    ["SPY CAGR", "5.00%", undefined],
    ["Difference vs SPY", "+5.00 pp", "up"],
    ["Growth of $1", "$1.10", undefined],
  ]);
});

test("the default name says the ranks, the last Rank, the interval and the other steps", () => {
  assert.equal(defaultName(one), "Ranks 1–50 · EBITDA yield · highest first · quarterly · Market cap ≥ $100M · Sector is not Utilities");
  assert.equal(defaultName({ ...one, schedule: { ...one.schedule, every: "12m" } }), "Ranks 1–50 · EBITDA yield · highest first · Market cap ≥ $100M · Sector is not Utilities");
  assert.equal(defaultName({ ...one, schedule: { ...one.schedule, every: "5w" } }).split(" · ")[3], "every 5 weeks");
  assert.equal(defaultName({ ...one, schedule: { ...one.schedule, every: "+03m" } }).split(" · ")[3], "quarterly");
  assert.equal(defaultName(two), "Hong Kong · Ranks 1–5 · Sleeves Land + Large");
  const long = { ...one, strategy: { sleeves: [{ steps: [...Array(9).fill(one.strategy.sleeves[0]!.steps[0]), one.strategy.sleeves[0]!.steps[2]] }] } };
  long.steps = [[...Array(9).fill(one.steps[0]![0]), one.steps[0]![2]]];
  assert.equal(defaultName(long).length, 120);
});

const holding = { sector: "Real Estate", exchange: "HKSE", market_cap: 12583039190.255821, enterprise_value: 2783124027.1080284 };

test("a ranking value is written in the display of its sleeve's last Rank; one sleeve also names the direction", () => {
  const single = rankingOf(one);
  assert.equal(single.heading, "Ranking value · highest");
  assert.equal(single.display(1), "percent");
  const sleeves = rankingOf(two);
  assert.equal(sleeves.heading, "Ranking value");
  assert.equal(sleeves.display(1), "percent");
  assert.equal(sleeves.display(2), "usd");
});

test("a trail gives each step's value in its display, then its rank or passed", () => {
  const rows = [
    { sleeve: 1, step: 3, value: 0.13968, step_rank: 4 },
    { sleeve: 1, step: 1, value: 12583039190.26, step_rank: null },
    { sleeve: 1, step: 2, value: null, step_rank: null },
  ];
  assert.deepEqual(trailOf(one, holding, rows), [
    {
      sleeve: null,
      lines: [
        "Step 1 · Filter · Market cap · $12,583.04M · passed",
        "Step 2 · Filter · Sector · Real Estate · passed",
        "Step 3 · Rank · EBITDA yield · 13.97% · rank 4 (kept 1–50)",
      ],
    },
  ]);
});

test("a sleeve holding has one trail for each sleeve that picked it; a field step reads the holding", () => {
  const rows = [
    { sleeve: 2, step: 1, value: null, step_rank: 1 },
    { sleeve: 1, step: 2, value: 0.25, step_rank: 2 },
    { sleeve: 1, step: 1, value: null, step_rank: null },
  ];
  assert.deepEqual(trailOf(two, holding, rows), [
    {
      sleeve: "Land",
      lines: ["Step 1 · Filter · Enterprise value in dollars · $2,783,124,027.11 · passed", "Step 2 · Rank · Cheap · 25.00% · rank 2 (kept 1–2)"],
    },
    { sleeve: "Large", lines: ["Step 1 · Rank · Market cap in dollars · $12,583,039,190.26 · rank 1 (kept 1–3)"] },
  ]);
});
