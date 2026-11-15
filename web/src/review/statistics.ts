import type { StatisticRow } from "../api/StatisticRow.ts";

/** A statistic of a run's trials by name (`cagr.median`, `valid`), or null
 *  when the rows do not hold it or it is not a finite number. */
export function statistic(rows: readonly StatisticRow[], name: string): number | null {
  const value = rows.find((row) => row.statistic === name)?.value;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
