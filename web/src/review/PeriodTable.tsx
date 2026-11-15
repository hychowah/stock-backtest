import type { PeriodRow } from "../api/PeriodRow.ts";
import { ScrollTable } from "../common/ScrollTable.tsx";
import { percent } from "../format.ts";

/** One row for each rebalance period of a trial: entry, exit, the number of
 *  stocks held, and the strategy's and SPY's returns. */
export function PeriodTable({ periods }: { periods: PeriodRow[] }) {
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
