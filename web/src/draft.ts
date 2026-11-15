import type { FileStep } from "./api/FileStep.ts";
import type { FileVariable } from "./api/FileVariable.ts";
import type { Market } from "./api/Market.ts";
import type { RunRow } from "./api/RunRow.ts";
import type { Schedule } from "./api/Schedule.ts";
import type { StrategyFile } from "./api/StrategyFile.ts";
import type { Variable } from "./api/Variable.ts";
import { readEvery, writeEvery } from "./describe.ts";
import { requestVariables } from "./variables.ts";

/** The strategy the builder edits, with its run settings. Plain data: each
 *  change returns a new draft. The live draft is kept in localStorage under one
 *  key; a stored draft that does not read is replaced by the default. The
 *  pending "New filter / New rank" row is view state, so step N here is step N
 *  in the file and in the server's error places. strategyFile() writes what
 *  the server reads, with the variables from variables.ts.
 *
 *  Each step carries an id that exists only in the page, so that a row keeps
 *  its place on screen while it moves; strategyFile() leaves it out. Nothing
 *  here checks a strategy or a schedule: the server does, when the draft is
 *  screened or added. */

type Mode = "latest" | "backtest";
export type Step = FileStep & { id: number };
type Filter = Extract<FileStep, { filter: string }>;
type Rank = Extract<FileStep, { rank: string }>;
/** A sleeve's name is "" until one is typed: then sleeveName() names it. */
type Sleeve = { name: string; steps: Step[] };

/** The dates and frequency controls. `end` "" is the market's last session.
 *  The interval is `months` (a preset) or, with `custom`, `count` weeks or
 *  months. `testing` is one fixed schedule, random trials (with `seed` when
 *  `repeat`), or the trade `dates` of a copied test. */
export type ScheduleForm = {
  start: string;
  end: string;
  months: number;
  custom: boolean;
  count: number;
  unit: "week" | "month";
  testing: "single" | "random" | "dates";
  trials: number;
  repeat: boolean;
  seed: number;
  dates: string[];
};

export type Draft = {
  mode: Mode;
  market: Market;
  autoRun: boolean;
  /** The typed test name; "" takes the default name. */
  name: string;
  sleeves: Sleeve[];
  /** The draft's own variables, from a copied test, in file order. */
  variables: Record<string, FileVariable>;
  schedule: ScheduleForm;
};

/** The presets of Rebalance frequency. */
export const PRESETS = [
  { months: 1, label: "Monthly" },
  { months: 3, label: "Quarterly" },
  { months: 6, label: "Half-yearly" },
  { months: 12, label: "Yearly" },
  { months: 24, label: "Every 2 years" },
];
const PRESET_MONTHS = PRESETS.map((preset) => preset.months);

const defaultSteps = (): FileStep[] => [
  { filter: "Market cap", op: ">=", value: "100" },
  { filter: "Enterprise value", op: ">=", value: "50" },
  { rank: "EBITDA yield", order: "highest", from: 1, to: 50 },
];

const withIds = (steps: readonly FileStep[], first: number): Step[] => steps.map((step, i) => ({ ...step, id: first + i }));

/** A new strategy: size floors, then the highest EBITDA yield, ranks 1–50,
 *  in latest mode, tested later on random dates from 2015 every 12 months. */
export function defaultDraft(): Draft {
  return {
    mode: "latest",
    market: "us",
    autoRun: true,
    name: "",
    sleeves: [{ name: "", steps: withIds(defaultSteps(), 1) }],
    variables: {},
    schedule: { start: "2015-01-01", end: "", months: 12, custom: false, count: 1, unit: "week", testing: "random", trials: 24, repeat: false, seed: 42, dates: [] },
  };
}

export const isRank = <T extends FileStep>(step: T): step is Extract<T, Rank> => "rank" in step;
/** The source name a step reads. */
export const sourceOf = (step: FileStep) => (isRank(step) ? step.rank : step.filter);
/** A filter on a text source (sector, exchange) compares with is or is not. */
export const isTextFilter = (step: FileStep) => !isRank(step) && (step.op === "is" || step.op === "is not");

/** A sleeve's name: the typed one, else the value of its sector Is filter,
 *  else "Sleeve N" (N from 1). */
export function sleeveName(sleeve: Sleeve, index: number): string {
  if (sleeve.name) return sleeve.name;
  const sector = sleeve.steps.find((step) => !isRank(step) && step.filter === "Sector" && step.op === "is" && step.value);
  return sector && !isRank(sector) ? sector.value : `Sleeve ${index + 1}`;
}

/** The strategy file of a draft: a name for each sleeve when there are
 *  several (or one was typed), and the variables a request carries. */
export function strategyFile(draft: Draft, library: readonly Variable[]): StrategyFile {
  const variables = requestVariables(draft.variables, library);
  const several = draft.sleeves.length > 1;
  return {
    ...(Object.keys(variables).length ? { variables } : {}),
    sleeves: draft.sleeves.map((sleeve, i) => ({
      ...(several || sleeve.name ? { name: sleeveName(sleeve, i) } : {}),
      steps: sleeve.steps.map(({ id: _id, ...step }) => step),
    })),
  };
}

/** The schedule of the form; `lastSession` stands in for an empty end. */
export function scheduleOf(form: ScheduleForm, lastSession: string): Schedule {
  const window = { start: form.start, end: form.end || lastSession };
  if (form.testing === "dates") return { ...window, dates: [...form.dates] };
  const every = form.custom ? writeEvery({ count: form.count, unit: form.unit }) : `${form.months}m`;
  if (form.testing === "single") return { ...window, every };
  return { ...window, every, trials: form.trials, ...(form.repeat ? { seed: form.seed } : {}) };
}

/** The form of a schedule. A control the schedule does not set keeps its
 *  value in `base`. */
export function formOf(schedule: Schedule, base: ScheduleForm): ScheduleForm {
  const form: ScheduleForm = { ...base, start: schedule.start, end: schedule.end, dates: [] };
  if (schedule.every !== undefined) {
    const interval = readEvery(schedule.every);
    const preset = interval.unit === "month" && PRESET_MONTHS.includes(interval.count) && schedule.every === writeEvery(interval);
    if (preset) Object.assign(form, { custom: false, months: interval.count });
    else Object.assign(form, { custom: true, count: interval.count, unit: interval.unit });
  }
  if (schedule.dates !== undefined) return { ...form, testing: "dates", dates: [...schedule.dates] };
  if (schedule.trials === undefined) return { ...form, testing: "single" };
  return { ...form, testing: "random", trials: schedule.trials, repeat: schedule.seed !== undefined, seed: schedule.seed ?? base.seed };
}

/** A run's settings as a draft for a dated test (a reply of GET
 *  /api/runs/{id}, which holds the strategy). The name is left empty. A
 *  sleeve name that equals its default is left empty too, so that it follows
 *  the sector filter again. */
export function fromRun(run: RunRow, base: Draft = defaultDraft()): Draft {
  if (!run.strategy) throw new Error(`run ${run.id} was read from the list, which holds no strategy`);
  let id = 1;
  const several = run.strategy.sleeves.length > 1;
  const sleeves = run.strategy.sleeves.map((sleeve, i) => {
    const steps = withIds(sleeve.steps, id);
    id += steps.length;
    const name = sleeve.name ?? "";
    return { name: several && name === sleeveName({ name: "", steps }, i) ? "" : name, steps };
  });
  return {
    ...base,
    mode: "backtest",
    market: run.market,
    name: "",
    sleeves,
    variables: { ...run.strategy.variables },
    schedule: formOf(run.schedule, base.schedule),
  };
}

const nextId = (draft: Draft) => Math.max(0, ...draft.sleeves.flatMap((sleeve) => sleeve.steps.map((step) => step.id))) + 1;

const withSleeve = (draft: Draft, index: number, change: (sleeve: Sleeve) => Sleeve): Draft => ({
  ...draft,
  sleeves: draft.sleeves.map((sleeve, i) => (i === index ? change(sleeve) : sleeve)),
});

const withSteps = (draft: Draft, index: number, change: (steps: Step[]) => Step[]): Draft =>
  withSleeve(draft, index, (sleeve) => ({ ...sleeve, steps: change(sleeve.steps) }));

/** A filter step on `source`: is with no value on a text source, otherwise
 *  more than, keeping a typed number of a filter it replaces. */
function retarget(source: string, text: boolean, previous: Filter | null): Filter {
  if (text) return { filter: source, op: "is", value: "" };
  const numeric = previous && previous.op !== "is" && previous.op !== "is not";
  return numeric ? { filter: source, op: previous.op, value: previous.value } : { filter: source, op: ">", value: "" };
}

/** Adds a step that reads `source` to a sleeve: a filter goes before the
 *  sleeve's last Rank, so it applies before the final ranking; a Rank goes
 *  last, highest first, ranks 1–50. Gives the draft and the new step's id. */
export function addStep(draft: Draft, sleeve: number, kind: "filter" | "rank", source: string, text: boolean): [Draft, number] {
  const id = nextId(draft);
  const step: Step = kind === "rank" ? { rank: source, order: "highest", from: 1, to: 50, id } : { ...retarget(source, text, null), id };
  const next = withSteps(draft, sleeve, (steps) => {
    const last = steps.findLastIndex(isRank);
    const at = kind === "filter" && last >= 0 ? last : steps.length;
    return [...steps.slice(0, at), step, ...steps.slice(at)];
  });
  return [next, id];
}

/** Makes a step read another source. A Rank keeps its order and ranks. */
export function setSource(draft: Draft, sleeve: number, id: number, source: string, text: boolean): Draft {
  return withSteps(draft, sleeve, (steps) =>
    steps.map((step) => {
      if (step.id !== id) return step;
      if (isRank(step)) return { ...step, rank: source };
      return { ...retarget(source, text, step), id };
    }),
  );
}

/** Changes a filter's comparison or value, or a Rank's order or ranks. */
export function editStep(draft: Draft, sleeve: number, id: number, change: Partial<Pick<Filter, "op" | "value">> | Partial<Pick<Rank, "order" | "from" | "to">>): Draft {
  return withSteps(draft, sleeve, (steps) => steps.map((step) => (step.id === id ? ({ ...step, ...change } as Step) : step)));
}

/** A Rank whose first rank passed its last: the other end moves to the one
 *  just set (`key`), so the first rank stays at most the last. */
export function commitRanks(draft: Draft, sleeve: number, id: number, key: "from" | "to"): Draft {
  return withSteps(draft, sleeve, (steps) =>
    steps.map((step) => (step.id === id && isRank(step) && step.from > step.to ? (key === "from" ? { ...step, to: step.from } : { ...step, from: step.to }) : step)),
  );
}

/** Moves a step one place up (-1) or down (1) in its sleeve. */
export function moveStep(draft: Draft, sleeve: number, id: number, offset: -1 | 1): Draft {
  return withSteps(draft, sleeve, (steps) => {
    const at = steps.findIndex((step) => step.id === id);
    const to = at + offset;
    if (at < 0 || to < 0 || to >= steps.length) return steps;
    const next = [...steps];
    [next[at], next[to]] = [next[to]!, next[at]!];
    return next;
  });
}

export function removeStep(draft: Draft, sleeve: number, id: number): Draft {
  return withSteps(draft, sleeve, (steps) => steps.filter((step) => step.id !== id));
}

/** Adds a copy of a sleeve's steps, without its typed name, at the end. */
export function copySleeve(draft: Draft, sleeve: number): Draft {
  const source = draft.sleeves[sleeve];
  if (!source) return draft;
  return { ...draft, sleeves: [...draft.sleeves, { name: "", steps: withIds(source.steps.map(({ id: _id, ...step }) => step), nextId(draft)) }] };
}

export function renameSleeve(draft: Draft, sleeve: number, name: string): Draft {
  return withSleeve(draft, sleeve, (current) => ({ ...current, name }));
}

/** Removes a sleeve; the last sleeve stays. */
export function removeSleeve(draft: Draft, sleeve: number): Draft {
  return draft.sleeves.length < 2 ? draft : { ...draft, sleeves: draft.sleeves.filter((_sleeve, i) => i !== sleeve) };
}

/** Reset strategy: the default steps in one sleeve and no own variables. The
 *  mode, market, dates and name stay. */
export function resetStrategy(draft: Draft): Draft {
  const fresh = defaultDraft();
  return { ...draft, sleeves: fresh.sleeves, variables: {} };
}

/** Another market: the window ends on its last session again, and the start
 *  moves inside its sessions. */
export function setMarket(draft: Draft, market: Market, sessions: { first: string; last: string } | null): Draft {
  let start = draft.schedule.start;
  if (sessions && start < sessions.first) start = sessions.first;
  if (sessions && start > sessions.last) start = sessions.last;
  return { ...draft, market, schedule: { ...draft.schedule, start, end: "" } };
}

export function setSchedule(draft: Draft, change: Partial<ScheduleForm>): Draft {
  return { ...draft, schedule: { ...draft.schedule, ...change } };
}

// Reading a stored draft: every field is checked, and any fault gives null.

type Check = (value: unknown) => boolean;
const isString: Check = (value) => typeof value === "string";
const isWhole = (value: unknown): value is number => Number.isSafeInteger(value);
const atLeast =
  (least: number): Check =>
  (value) =>
    isWhole(value) && value >= least;
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const oneOf =
  (...values: unknown[]): Check =>
  (value) =>
    values.includes(value);
const shaped = (value: unknown, fields: Record<string, Check>): boolean =>
  isRecord(value) && Object.keys(value).length === Object.keys(fields).length && Object.entries(fields).every(([key, check]) => key in value && check(value[key]));
const listOf =
  (check: Check): Check =>
  (value) =>
    Array.isArray(value) && value.every(check);

const isStep: Check = (value) =>
  shaped(value, { filter: isString, op: oneOf("<", "<=", ">", ">=", "is", "is not"), value: isString, id: isWhole }) ||
  shaped(value, { rank: isString, order: oneOf("highest", "lowest"), from: isWhole, to: isWhole, id: isWhole });

const isDraft = (value: unknown): value is Draft =>
  shaped(value, {
    mode: oneOf("latest", "backtest"),
    market: oneOf("us", "hk", "jp"),
    autoRun: oneOf(true, false),
    name: isString,
    sleeves: (sleeves) => Array.isArray(sleeves) && sleeves.length > 0 && sleeves.every((sleeve) => shaped(sleeve, { name: isString, steps: listOf(isStep) })),
    variables: (variables) => isRecord(variables) && Object.values(variables).every((variable) => shaped(variable, { formula: isString, display: isString })),
    schedule: (schedule) =>
      shaped(schedule, {
        start: isString,
        end: isString,
        months: oneOf(...PRESET_MONTHS),
        custom: oneOf(true, false),
        count: atLeast(1),
        unit: oneOf("week", "month"),
        testing: oneOf("single", "random", "dates"),
        trials: atLeast(1),
        repeat: oneOf(true, false),
        seed: atLeast(0),
        dates: listOf(isString),
      }),
  });

/** A stored draft (JSON text), or the default when there is none or it does
 *  not read: wrong JSON, a missing or extra field, a field of another type,
 *  or an interval count or trials below 1. */
export function readDraft(text: string | null): Draft {
  if (text === null) return defaultDraft();
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return defaultDraft();
  }
  return isDraft(value) ? value : defaultDraft();
}
