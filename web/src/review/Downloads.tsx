import type { PeriodRow } from "../api/PeriodRow.ts";
import type { RunRow } from "../api/RunRow.ts";
import { client } from "../client.ts";
import { Download } from "../common/Download.tsx";

/** The downloads of one trial's period returns and holdings, as CSV files
 *  with the replies' field names. The holdings of every period are read when
 *  their button is pressed, whatever sector or period the page shows. */
export function Downloads({ run, trial, periods }: { run: RunRow; trial: number; periods: PeriodRow[] }) {
  const file = (kind: string) => `scheduled-${kind}-${run.schedule.start}-${run.schedule.end}${run.schedule.trials === undefined ? "" : "-trial-" + trial}.csv`;
  return (
    <div>
      <Download id="schedule-download-returns" file={file("returns")} rows={() => periods}>
        Download original period returns
      </Download>{" "}
      <Download id="schedule-download-holdings" file={file("holdings")} rows={async () => (await client.holdings(run.id, trial)).holdings}>
        Download original holdings
      </Download>
    </div>
  );
}
