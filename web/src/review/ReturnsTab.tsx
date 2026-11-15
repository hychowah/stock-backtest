import type { RunRow } from "../api/RunRow.ts";
import type { TrialsReply } from "../api/TrialsReply.ts";
import { Curve } from "../charts/Curve.tsx";
import { client } from "../client.ts";
import { intervalWords, readEvery } from "../describe.ts";
import { growth, percent } from "../format.ts";
import { useRead } from "../read.ts";
import { coverageOf, trialChoice } from "./coverage.ts";
import { Downloads } from "./Downloads.tsx";
import { Holdings } from "./Holdings.tsx";
import { PeriodReturns } from "./PeriodTable.tsx";
import { useSelection } from "./selection.ts";

/** The Returns tab of a complete run: the chosen trial's value of $1, its
 *  period returns as bars and a table, their downloads, and the holdings of
 *  one of its periods. Random dates start with the trial's header and the
 *  choice of the trial. The trial, the period and the sector are the shared
 *  selection's. */
export function ReturnsTab({ run, trials }: { run: RunRow; trials: TrialsReply }) {
  const { selection, select } = useSelection();
  const random = run.schedule.trials !== undefined;
  const trial = selection.trial;
  const row = trials.trials[trial - 1];
  const periods = useRead(() => client.periods(run.id, trial), [run.id, trial]);
  const holdings = useRead(() => client.holdings(run.id, trial, selection.period), [run.id, trial, selection.period]);
  const attributions = useRead(() => client.contributions(run.id, trial), [run.id, trial]);
  return (
    <>
      {random && row && (
        <div id="schedule-trial">
          <h3 id="schedule-trial-title">
            Trial {trial} of {trials.trials.length}
          </h3>
          <p class="hint">This is one sampled trial. The headline shows all trials. Choose another trial here or under Each sampled trial in Overview.</p>
          <label>
            Trial{" "}
            <select id="schedule-trial-choice" value={String(trial)} onChange={(event) => select({ trial: Number(event.currentTarget.value) })}>
              {trials.trials.map((each) => (
                <option key={each.trial} value={String(each.trial)}>
                  {trialChoice(each)}
                </option>
              ))}
            </select>
          </label>
          <p id="schedule-dates">
            {row.start} → {row.end}
            {run.schedule.every !== undefined && ` · every ${intervalWords(readEvery(run.schedule.every))}`}
          </p>
          <div class="latest-facts">
            <span>
              Strategy CAGR<strong id="schedule-cagr">{percent(row.cagr)}</strong>
            </span>
            <span>
              SPY CAGR<strong id="schedule-spy-cagr">{percent(row.spy_cagr)}</strong>
            </span>
            <span>
              Growth of $1<strong id="schedule-growth">{growth(row.growth)}</strong>
            </span>
          </div>
          <p id="schedule-coverage" class="hint">
            {coverageOf(row, undefined)}
          </p>
        </div>
      )}
      <Curve id={run.id} trial={trial} />
      <PeriodReturns periods={periods} />
      {periods.state === "done" && <Downloads run={run} trial={trial} periods={periods.value} />}
      {periods.state === "done" && <Holdings run={run} periods={periods.value} holdings={holdings} attributions={attributions} />}
    </>
  );
}
