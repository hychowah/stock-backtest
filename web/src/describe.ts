import type { DescribedStep } from "./api/DescribedStep.ts";
import type { FileStep } from "./api/FileStep.ts";
import type { Market } from "./api/Market.ts";
import type { RunRow } from "./api/RunRow.ts";
import type { Schedule } from "./api/Schedule.ts";
import type { StepRow } from "./api/StepRow.ts";
import type { StrategyFile } from "./api/StrategyFile.ts";
import type { TrialsReply } from "./api/TrialsReply.ts";
import type { Display } from "./api/Display.ts";
import { format, formatTyped, marketName, percent, points, rounded } from "./format.ts";

/** A run in words: the one place that writes settings for people. Input:
 *  RunSettings (market, schedule, strategy file and each step's display), made
 *  from a run (settingsOf) or from the draft. Output: labelled settings lines
 *  (market; the window, interval, trials and seed; each sleeve's steps, with
 *  thresholds in their display), the headline cells and other measures of a
 *  complete run (from its trials reply), the lines of a holding's or a pick's
 *  step trail, and the default test name.
 *  Schedule.every (Nw|Nm) and a trial's dates (ISO days joined by spaces) are
 *  read here and nowhere else. */
export type RunSettings = {
  market: Market;
  schedule: Schedule;
  strategy: StrategyFile;
  /** For each sleeve, each step's source and display, in file order: the
   *  `sleeves` of a Description. */
  steps: Pick<DescribedStep, "source" | "display">[][];
};

/** One labelled line of words. `key` is the same for the same setting of
 *  two runs, so that a comparison can align them. */
export type Line = { key: string; label: string; text: string };

/** One headline cell; `tone` gives the colour of a difference by its sign. */
export type Cell = Line & { tone?: "up" | "down" };

/** The settings of a run that a reply about one run (GET /api/runs/{id})
 *  carries; the list's rows carry no strategy. */
export function settingsOf(run: RunRow): RunSettings {
  if (!run.strategy || !run.description) throw new Error(`run ${run.id} was read from the list, which holds no strategy`);
  return {
    market: run.market,
    schedule: run.schedule,
    strategy: run.strategy,
    steps: run.description.sleeves.map((sleeve) => sleeve.steps),
  };
}

/** A rebalance interval: `3m` is 3 months, `1w` 1 week. */
export type Interval = { count: number; unit: "week" | "month" };

/** Schedule.every as an interval. The server keeps it as it was typed, so
 *  `+3m` and `03m` read as 3 months. */
export function readEvery(every: string): Interval {
  const parts = /^\+?(\d+)([wm])$/.exec(every);
  if (!parts) throw new Error(`not an interval: ${every}`);
  return { count: Number(parts[1]), unit: parts[2] === "w" ? "week" : "month" };
}

/** An interval as Schedule.every writes it. */
export function writeEvery(interval: Interval): string {
  return interval.count + (interval.unit === "week" ? "w" : "m");
}

/** The days of a trial's `dates` (ISO days joined by spaces). */
export function tradeDays(dates: string): string[] {
  return dates.split(" ").filter(Boolean);
}

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

/** An interval in words: 1 week, 3 months. */
export function intervalWords(interval: Interval): string {
  return plural(interval.count, interval.unit);
}

const OPERATORS: Record<string, string> = { "<": "<", "<=": "≤", ">": ">", ">=": "≥", is: "is", "is not": "is not" };

const isRank = (step: FileStep): step is Extract<FileStep, { rank: string }> => "rank" in step;

/** A step in words: `Market cap in dollars ≥ $13,000,000,000` or
 *  `EBITDA yield · highest first · ranks 1–50`. */
function stepWords(step: FileStep, display: Display): string {
  if (isRank(step)) return `${step.rank} · ${step.order} first · ranks ${step.from}–${step.to}`;
  return `${step.filter} ${OPERATORS[step.op]} ${display === "text" ? step.value : formatTyped(step.value, display)}`;
}

function displayOf(settings: RunSettings, sleeve: number, step: number): Display {
  const described = settings.steps[sleeve]?.[step];
  if (!described) throw new Error(`no display for step ${step + 1} of sleeve ${sleeve + 1}`);
  return described.display;
}

/** The settings in labelled lines: the test type, market and currency; the
 *  window, then the interval or the trade dates; the trials and their random
 *  date set; each variable's formula; then each step, named by its sleeve
 *  when there are several. */
export function settingsLines(settings: RunSettings): Line[] {
  const { schedule, strategy } = settings;
  const random = schedule.trials !== undefined;
  const lines: Line[] = [
    { key: "type", label: "Test type", text: random ? "Random dates" : "Fixed dates" },
    { key: "market", label: "Stock market", text: marketName(settings.market) },
    { key: "currency", label: "Return currency", text: "USD" },
    { key: "start", label: "Requested start", text: schedule.start },
    { key: "end", label: "Requested end", text: schedule.end },
  ];
  if (schedule.every !== undefined) lines.push({ key: "interval", label: "Rebalance interval", text: intervalWords(readEvery(schedule.every)) });
  if (schedule.dates !== undefined) lines.push({ key: "dates", label: "Trade dates", text: schedule.dates.join(", ") });
  if (random) {
    lines.push({ key: "trials", label: "Trials", text: String(schedule.trials) });
    lines.push({ key: "seed", label: "Random date set", text: schedule.seed === undefined ? "Drawn when the test is added" : String(schedule.seed) });
  }
  for (const [name, variable] of Object.entries(strategy.variables ?? {})) {
    lines.push({ key: "variable." + name, label: "Variable · " + name, text: variable.formula });
  }
  const several = strategy.sleeves.length > 1;
  strategy.sleeves.forEach((sleeve, s) =>
    sleeve.steps.forEach((step, i) =>
      lines.push({
        key: `sleeve.${s + 1}.step.${i + 1}`,
        label: (several ? (sleeve.name ?? `Sleeve ${s + 1}`) + " · " : "") + `Step ${i + 1} · ${isRank(step) ? "Rank" : "Filter"}`,
        text: stepWords(step, displayOf(settings, s, i)),
      }),
    ),
  );
  return lines;
}

/** A statistic of a run's trials by name (`cagr.median`, `beat_spy`), or
 *  null when the reply does not hold it (or holds no number). */
function statistic(reply: TrialsReply, name: string): number | null {
  const value = reply.statistics.find((row) => row.statistic === name)?.value;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

const toneOf = (value: number | null) => (value === null || value === 0 ? {} : { tone: value > 0 ? ("up" as const) : ("down" as const) });

/** The headline of a complete run, from its trials reply (GET
 *  /api/runs/{id}/trials). Random dates: the median strategy CAGR, the
 *  median SPY CAGR, the median of each trial's difference to SPY, the trials
 *  beating SPY, and the worst and best trial CAGR. Another schedule (one
 *  trial): its CAGR, SPY's, the difference and the growth of $1. A missing
 *  statistic is a dash. The CAGR column of a list row is
 *  `Outcome.headline.median`, which equals the first cell. */
export function headlineCells(schedule: Schedule, reply: TrialsReply): Cell[] {
  if (schedule.trials === undefined) {
    const trial = reply.trials[0];
    const difference = trial ? trial.excess_cagr : null;
    return [
      { key: "cagr", label: "Strategy CAGR", text: percent(trial?.cagr) },
      { key: "spy_cagr", label: "SPY CAGR", text: percent(trial?.spy_cagr) },
      { key: "difference", label: "Difference vs SPY", text: points(difference), ...toneOf(difference) },
      { key: "growth", label: "Growth of $1", text: trial && Number.isFinite(trial.growth) ? "$" + rounded(trial.growth) : "—" },
    ];
  }
  const stat = (name: string) => statistic(reply, name);
  const difference = stat("excess_cagr.median");
  const [beat, valid, incomplete] = [stat("beat_spy"), stat("valid"), stat("incomplete")];
  return [
    { key: "cagr", label: "Median strategy CAGR", text: percent(stat("cagr.median")) },
    { key: "spy_cagr", label: "Median SPY CAGR", text: percent(stat("spy_cagr.median")) },
    { key: "difference", label: "Median difference vs SPY", text: points(difference), ...toneOf(difference) },
    { key: "beat_spy", label: "Trials beating SPY", text: beat === null || valid === null ? "—" : `${beat}/${valid}` + (incomplete ? " complete" : "") },
    { key: "worst", label: "Worst trial CAGR", text: percent(stat("cagr.min")) },
    { key: "best", label: "Best trial CAGR", text: percent(stat("cagr.max")) },
  ];
}

/** The other measures of a random-dates run, from its trials reply: the mean
 *  strategy CAGR, its P10 to P90 and standard deviation, the mean difference
 *  to SPY, the worst to best difference, and the number of trials. */
export function measureLines(reply: TrialsReply): Line[] {
  const stat = (name: string) => statistic(reply, name);
  const range = (low: string, high: string, write: (value: number) => string) => {
    const [a, b] = [stat(low), stat(high)];
    return a === null || b === null ? "—" : write(a) + " to " + write(b);
  };
  const [completed, valid, incomplete] = [stat("completed"), stat("valid"), stat("incomplete")];
  return [
    { key: "cagr.mean", label: "Mean strategy CAGR", text: percent(stat("cagr.mean")) },
    { key: "cagr.range", label: "Strategy CAGR, P10 to P90", text: range("cagr.p10", "cagr.p90", percent) },
    { key: "cagr.stddev", label: "Std. dev. of strategy CAGR", text: percent(stat("cagr.stddev")) },
    { key: "excess_cagr.mean", label: "Mean difference vs SPY", text: points(stat("excess_cagr.mean")) },
    { key: "excess_cagr.range", label: "Difference vs SPY, worst to best", text: range("excess_cagr.min", "excess_cagr.max", points) },
    { key: "trials", label: "Trials", text: completed === null ? "—" : incomplete && valid !== null ? `${valid} of ${completed} complete` : String(completed) },
  ];
}

/** The fields of a holding or a pick that a field step reads. */
export type TrailItem = { sector: string; exchange: string; market_cap: number; enterprise_value: number };

/** The step trail of one picking sleeve: its name (when the strategy has
 *  several sleeves) and one line per step. */
export type Trail = { sleeve: string | null; lines: string[] };

/** The step trail of a holding or a pick: for each sleeve that picked it,
 *  each step's value in its display, then its rank or "passed":
 *  `Step 2 · Rank · EBITDA yield · 13.97% · rank 1 (kept 1–5)`. `rows` are
 *  the item's step rows (a holding's from `holdings`, a pick's `steps`). A
 *  field step's value is the item's own field. */
export function trailOf(settings: RunSettings, item: TrailItem, rows: readonly Pick<StepRow, "sleeve" | "step" | "value" | "step_rank">[]): Trail[] {
  const sleeves = [...new Set(rows.map((row) => row.sleeve))].sort((a, b) => a - b);
  const several = settings.strategy.sleeves.length > 1;
  return sleeves.map((number) => {
    const sleeve = settings.strategy.sleeves[number - 1];
    if (!sleeve) throw new Error(`no sleeve ${number} in the strategy`);
    const lines = rows
      .filter((row) => row.sleeve === number)
      .sort((a, b) => a.step - b.step)
      .map((row) => {
        const step = sleeve.steps[row.step - 1];
        if (!step) throw new Error(`no step ${row.step} in sleeve ${number}`);
        const display = displayOf(settings, number - 1, row.step - 1);
        const source = settings.steps[number - 1]?.[row.step - 1]?.source;
        const value = source?.kind === "field" ? fieldValue(item, source.name, display) : format(row.value, display);
        const outcome = isRank(step) ? `rank ${row.step_rank} (kept ${step.from}–${step.to})` : "passed";
        return [`Step ${row.step}`, isRank(step) ? "Rank" : "Filter", isRank(step) ? step.rank : step.filter, value, outcome].join(" · ");
      });
    return { sleeve: several ? (sleeve.name ?? `Sleeve ${number}`) : null, lines };
  });
}

/** A field step's value: the item's sector or exchange, or its market cap or
 *  enterprise value in dollars. */
function fieldValue(item: TrailItem, name: string, display: Display): string {
  const field = ({ Sector: "sector", Exchange: "exchange", "Market cap in dollars": "market_cap", "Enterprise value in dollars": "enterprise_value" } as const)[name];
  if (!field) throw new Error(`not a field: ${name}`);
  const value = item[field];
  return typeof value === "string" ? value || "Unknown" : format(value, display);
}

const INTERVAL_NAMES: Record<string, string> = { "1w": "weekly", "1m": "monthly", "3m": "quarterly", "6m": "half-yearly", "24m": "every 2 years" };

/** The default test name: what the run list's columns do not say. A market
 *  other than US first; the ranks kept; the last Rank (or the sleeves'
 *  names); the interval unless it is 12 months; then the other steps. At
 *  most 120 characters. */
export function defaultName(settings: RunSettings): string {
  const { strategy, schedule } = settings;
  const words: string[] = settings.market === "us" ? [] : [marketName(settings.market)];
  const lastRanks = strategy.sleeves.map((sleeve) => sleeve.steps.findLast(isRank));
  if (strategy.sleeves.length > 1) {
    const kept = lastRanks.reduce((sum, rank) => sum + (rank ? rank.to - rank.from + 1 : 0), 0);
    words.push(`Ranks 1–${kept}`, "Sleeves " + strategy.sleeves.map((sleeve, s) => sleeve.name ?? `Sleeve ${s + 1}`).join(" + "));
  } else {
    const rank = lastRanks[0];
    if (rank) words.push(`Ranks ${rank.from}–${rank.to}`, `${rank.rank} · ${rank.order} first`);
  }
  const interval = schedule.every === undefined ? null : readEvery(schedule.every);
  if (interval && !(interval.unit === "month" && interval.count === 12)) {
    words.push(INTERVAL_NAMES[writeEvery(interval)] ?? "every " + intervalWords(interval));
  }
  if (strategy.sleeves.length === 1) {
    const steps = strategy.sleeves[0]?.steps ?? [];
    steps.forEach((step, i) => step !== lastRanks[0] && words.push(stepWords(step, displayOf(settings, 0, i))));
  }
  return words.join(" · ").slice(0, 120).trim();
}
