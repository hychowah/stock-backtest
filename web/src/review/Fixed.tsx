import type { RunRow } from "../api/RunRow.ts";
import { Curve } from "../charts/Curve.tsx";
import { client } from "../client.ts";
import { useRead } from "../read.ts";
import { Downloads } from "./Downloads.tsx";
import { PeriodReturns } from "./PeriodTable.tsx";

/** Overview of a fixed schedule, which has one trial: the value of $1 day by
 *  day, then the return of each rebalance period as bars and as a table, and
 *  their downloads. */
export function Fixed({ run }: { run: RunRow }) {
  const periods = useRead(() => client.periods(run.id, 1), [run.id]);
  return (
    <>
      <Curve id={run.id} trial={1} />
      <PeriodReturns periods={periods} />
      {periods.state === "done" && <Downloads run={run} trial={1} periods={periods.value} />}
    </>
  );
}
