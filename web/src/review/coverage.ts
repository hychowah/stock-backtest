import type { TrialRow } from "../api/TrialRow.ts";
import { percent, rounded } from "../format.ts";

/** A trial as its option in a choice of trials: `Trial 3 · 2016-01-05 · CAGR 12.34%`. */
export const trialChoice = (trial: TrialRow) => `Trial ${trial.trial} · ${trial.first_trade ?? "—"} · CAGR ${percent(trial.cagr)}`;

/** The coverage note of one trial: its short and empty periods, what an empty
 *  period holds, how long the strategy held cash before its first trade, and,
 *  when `seconds` is given, how long the run computed. Only a fixed schedule
 *  gives it: the run's time is not one trial's. */
export function coverageOf(trial: TrialRow, seconds: number | undefined): string {
  return (
    `${trial.short_periods} short periods; ${trial.empty_periods} empty periods. ` +
    (trial.empty_periods ? "Empty periods hold cash at 0%; SPY keeps its period return. " : "") +
    (seconds !== undefined ? `Computed in ${rounded(seconds)} s.` : "") +
    (trial.cash_days ? ` Both strategy and paired SPY hold cash until ${trial.first_trade} (${trial.cash_days} days); CAGR uses the common window.` : "")
  ).trim();
}
