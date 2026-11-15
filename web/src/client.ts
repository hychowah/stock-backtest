import type { AddRun } from "./api/AddRun.ts";
import type { Attribution } from "./api/Attribution.ts";
import type { CatalogReply } from "./api/CatalogReply.ts";
import type { CurveReply } from "./api/CurveReply.ts";
import type { Deleted } from "./api/Deleted.ts";
import type { EditRun } from "./api/EditRun.ts";
import type { ExploreReply } from "./api/ExploreReply.ts";
import type { FormulaReply } from "./api/FormulaReply.ts";
import type { FormulaRequest } from "./api/FormulaRequest.ts";
import type { HoldingsReply } from "./api/HoldingsReply.ts";
import type { Market } from "./api/Market.ts";
import type { MoveRun } from "./api/MoveRun.ts";
import type { NewVariable } from "./api/NewVariable.ts";
import type { PeriodRow } from "./api/PeriodRow.ts";
import type { Queue } from "./api/Queue.ts";
import type { RunRow } from "./api/RunRow.ts";
import type { RunsReply } from "./api/RunsReply.ts";
import type { ScreenBody } from "./api/ScreenBody.ts";
import type { ScreenReply } from "./api/ScreenReply.ts";
import type { SectorsReply } from "./api/SectorsReply.ts";
import type { StatusReply } from "./api/StatusReply.ts";
import type { TrialsReply } from "./api/TrialsReply.ts";
import type { Variable } from "./api/Variable.ts";

/** A request that `bt serve` refused, or that it did not answer. */
export class ApiFailure extends Error {
  /** The HTTP status; 0 when the server did not answer. */
  readonly status: number;
  /** The input, file or folder the message is about, such as
   *  `strategy: sleeves[1].steps[2]`; empty when the server did not say. */
  readonly place: string;

  constructor(status: number, message: string, place: string) {
    super(message);
    this.name = "ApiFailure";
    this.status = status;
    this.place = place;
  }
}

/** The message of a request that got no answer. */
export const NO_ANSWER = "The server does not answer.";

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      cache: "no-store",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiFailure(0, NO_ANSWER, "");
  }
  let reply: unknown;
  try {
    reply = await response.json();
  } catch {
    throw new ApiFailure(response.status, `The server's reply (status ${response.status}) could not be read.`, "");
  }
  if (!response.ok) {
    const error = (reply as { error?: { message?: string; place?: string } }).error;
    throw new ApiFailure(response.status, error?.message ?? `The server refused the request (status ${response.status}).`, error?.place ?? "");
  }
  return reply as T;
}

const get = <T>(path: string) => send<T>("GET", path);
const runPath = (id: number) => `/api/runs/${id}`;
const query = (values: Record<string, string | number | undefined>) => {
  const entries = Object.entries(values).filter((entry): entry is [string, string | number] => entry[1] !== undefined);
  return entries.length ? "?" + new URLSearchParams(entries.map(([key, value]) => [key, String(value)])).toString() : "";
};

/** Each trial's sector shares and the spread over the trials; with `trial`,
 *  that trial's weight of each sector in each period. */
function sectors(id: number): Promise<Extract<SectorsReply, { trials: unknown }>>;
function sectors(id: number, trial: number): Promise<Extract<SectorsReply, { weights: unknown }>>;
function sectors(id: number, trial?: number): Promise<SectorsReply> {
  return get<SectorsReply>(runPath(id) + "/sectors" + query({ trial }));
}

/** The website's one door to `bt serve`: one function per route, typed by the
 *  generated types. A refused request throws ApiFailure with the server's
 *  message and place; status 0 means the server did not answer. Nothing else
 *  is thrown.
 *
 *  Status 400 is wrong input (the place names it), 404 an unknown id or
 *  market, 409 a change that the run's state does not allow or a result asked
 *  of a run that is not complete, 500 a failed read or write of the home. */
export const client = {
  /** The pause and every run, without its strategy. */
  runs: () => get<RunsReply>("/api/runs"),
  /** Adds a waiting run at the end of the queue. */
  addRun: (body: AddRun) => send<RunRow>("POST", "/api/runs", body),
  /** One run, with its canonical strategy and the description of its steps. */
  run: (id: number) => get<RunRow>(runPath(id)),
  /** Renames or locks a run, or changes a waiting or held run's settings. */
  editRun: (id: number, body: EditRun) => send<RunRow>("PATCH", runPath(id), body),
  /** Removes a run that is not locked; a running run is stopped first. */
  deleteRun: (id: number) => send<Deleted>("DELETE", runPath(id)),
  hold: (id: number) => send<RunRow>("POST", runPath(id) + "/hold"),
  release: (id: number) => send<RunRow>("POST", runPath(id) + "/release"),
  stop: (id: number) => send<RunRow>("POST", runPath(id) + "/stop"),
  /** Moves a waiting or held run to a place in the queue, from 1. */
  move: (id: number, body: MoveRun) => send<RunRow>("POST", runPath(id) + "/move", body),
  /** Pauses or resumes the queue. */
  setQueue: (body: Queue) => send<Queue>("PUT", "/api/queue", body),

  /** The variable library, in dependency order. */
  variables: () => get<Variable[]>("/api/variables"),
  addVariable: (body: NewVariable) => send<Variable>("POST", "/api/variables", body),
  editVariable: (id: number, body: NewVariable) => send<Variable>("PUT", `/api/variables/${id}`, body),
  /** 409 when another entry uses it. */
  deleteVariable: (id: number) => send<Deleted>("DELETE", `/api/variables/${id}`),
  /** Checks formula text: `checked`, or a `fault`, always with status 200. */
  formula: (body: FormulaRequest) => send<FormulaReply>("POST", "/api/formula", body),

  /** A complete run's statistics and each trial. `trial` counts from 1. */
  trials: (id: number) => get<TrialsReply>(runPath(id) + "/trials"),
  periods: (id: number, trial: number) => get<PeriodRow[]>(runPath(id) + "/periods" + query({ trial })),
  /** One trial's holdings, or one period's, with their step rows. */
  holdings: (id: number, trial: number, period?: number) => get<HoldingsReply>(runPath(id) + "/holdings" + query({ trial, period })),
  /** The band over the trials without `trial`, or one trial's growth. */
  curve: (id: number, trial?: number) => get<CurveReply>(runPath(id) + "/curve" + query({ trial })),
  sectors,
  contributions: (id: number, trial: number) => get<Attribution[]>(runPath(id) + "/contributions" + query({ trial })),
  /** `trial` is a number or `all`; `periods` and `ranks` are `A-B`. */
  explore: (id: number, selection: { trial: number | "all"; periods: string; ranks: string }) =>
    get<ExploreReply>(runPath(id) + "/explore" + query(selection)),

  /** The names, functions and units a market's strategies can use. */
  catalog: (market: Market) => get<CatalogReply>(`/api/catalog/${market}`),
  /** A strategy's picks on the market's last session. */
  screen: (body: ScreenBody) => send<ScreenReply>("POST", "/api/screen", body),
  /** What prepared data each market has. */
  dataStatus: () => get<StatusReply>("/api/data/status"),
};
