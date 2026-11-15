import type { RunRow } from "../api/RunRow.ts";
import { PeriodBars } from "../charts/PeriodBars.tsx";
import { Curve } from "../charts/Curve.tsx";
import { client } from "../client.ts";
import { useRead } from "../read.ts";
import { PeriodTable } from "./PeriodTable.tsx";

/** Overview of a fixed schedule, which has one trial: the value of $1 day by
 *  day, then the return of each rebalance period as bars and as a table. */
export function Fixed({ run }: { run: RunRow }) {
  const periods = useRead(() => client.periods(run.id, 1), [run.id]);
  return (
    <>
      <Curve id={run.id} trial={1} />
      <div>
        <h3>Returns by holding period</h3>
        <p class="hint">Green: strategy. Grey: SPY. Each bar is one rebalance period, not an annual return.</p>
        {periods.state === "done" ? (
          <>
            <PeriodBars periods={periods.value} />
            <PeriodTable periods={periods.value} />
          </>
        ) : (
          periods.state === "failed" && <p class="screen-message warning">{periods.failure.message}</p>
        )}
      </div>
    </>
  );
}
