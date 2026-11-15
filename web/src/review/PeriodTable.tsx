import type { PeriodRow } from "../api/PeriodRow.ts";
import { PeriodBars } from "../charts/PeriodBars.tsx";
import { ScrollTable } from "../common/ScrollTable.tsx";
import { percent } from "../format.ts";
import type { Read } from "../read.ts";

/** Returns by holding period: the read periods of one trial as bars and as a
 *  table, or why they could not be read. */
export function PeriodReturns({ periods }: { periods: Read<PeriodRow[]> }) {
  return (
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
  );
}

/** One row for each rebalance period of a trial: entry, exit, the number of
 *  stocks held, and the strategy's and SPY's returns. */
function PeriodTable({ periods }: { periods: PeriodRow[] }) {
  return (
    <ScrollTable>
      <table>
        <thead>
          <tr>
            <th>Entry</th>
            <th>Exit / mark</th>
            <th>Stocks</th>
            <th>Strategy</th>
            <th>SPY</th>
          </tr>
        </thead>
        <tbody id="schedule-rows">
          {periods.map((period) => (
            <tr key={period.period}>
              <td>{period.entry}</td>
              <td>{period.exit}</td>
              <td>{period.names}</td>
              <td>{percent(period.portfolio)}</td>
              <td>{percent(period.spy)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollTable>
  );
}
