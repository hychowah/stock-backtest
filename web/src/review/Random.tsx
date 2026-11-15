import { useState } from "preact/hooks";
import type { RunRow } from "../api/RunRow.ts";
import type { TrialRow } from "../api/TrialRow.ts";
import type { TrialsReply } from "../api/TrialsReply.ts";
import { Curve } from "../charts/Curve.tsx";
import { Distribution, MEASURE_OPTIONS, type Measure } from "../charts/Distribution.tsx";
import { Download } from "../common/Download.tsx";
import { ScrollTable } from "../common/ScrollTable.tsx";
import { format, percent, rounded } from "../format.ts";
import type { ExploredTrials } from "./Explore.tsx";
import { useSelection } from "./selection.ts";
import { statistic } from "./statistics.ts";

/** A difference of fractions in percentage points without the unit, which the
 *  column heading names: -9.39. */
const bare = (v: number | null | undefined) => format(v, "percentage_points").replace(/ pp$/, "");

const DISTRIBUTIONS: [string, string, (v: number | null) => string][] = [
  ["Strategy CAGR", "cagr", percent],
  ["Paired SPY CAGR", "spy_cagr", percent],
  ["CAGR difference (pp)", "excess_cagr", bare],
  ["Total strategy return", "total_return", percent],
  ["Ending value of $1", "growth", (v) => (v === null ? "—" : "$" + rounded(v))],
];
const COLUMNS = ["mean", "median", "p10", "p25", "p75", "p90", "min", "max", "stddev"];

/** Overview of random dates: the band of the trials' value of $1, the
 *  distribution of the trials' returns, the statistics over the trials and a
 *  row for each trial, with the choice of the trial that Returns shows. The
 *  chart and tables show `explored` (an Explore selection) in place of the
 *  original trials while there is one, and say so; the original trials are
 *  what the download holds and what is inspected. The chosen `measure` is
 *  kept by the page, so it survives a visit to another tab. */
export function Random({ run, trials, explored, measure: [measure, setMeasure] }: { run: RunRow; trials: TrialsReply; explored: ExploredTrials | null; measure: [Measure, (measure: Measure) => void] }) {
  const { selection, select } = useSelection();
  const [inspect, setInspect] = useState(selection.trial);
  const shown = explored ?? trials;
  const stat = (name: string) => statistic(shown.statistics, name);
  const count = (name: string) => stat(name) ?? "—";

  return (
    <div id="robustness-results">
      <Curve id={run.id} />
      <div class="review-heading">
        <h3>Return distribution for this seed</h3>
        <label>
          Return measure{" "}
          <select id="robustness-measure" value={measure} onChange={(event) => setMeasure(event.currentTarget.value as Measure)}>
            {MEASURE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {explored && (
        <p id="robustness-scope" class="screen-message warning" role="status">
          Explore selection: {explored.start} → {explored.end} · ranks {explored.rank_from}–{explored.rank_to}. The chart and tables below show this temporary selection. The headline shows the original result. Select Reset to original in Explore to restore them.
        </p>
      )}
      <Distribution measure={measure} trials={shown.trials} statistics={shown.statistics} seed={run.schedule.seed} />
      <h3>Distribution across complete trials</h3>
      <p id="robustness-description" class="hint">
        {count("completed")} trials · {count("valid")} complete, {count("incomplete")} incomplete · {count("unique_schedules")} distinct schedules · {count("beat_spy")}/{count("valid")} complete trials beat paired SPY.
      </p>
      <ScrollTable kind="latest-table">
        <table>
          <thead>
            <tr>
              <th>Measure</th>
              <th>Mean</th>
              <th>Median</th>
              <th>P10</th>
              <th>P25</th>
              <th>P75</th>
              <th>P90</th>
              <th>Worst</th>
              <th>Best</th>
              <th>Std. dev.</th>
            </tr>
          </thead>
          <tbody id="robustness-distribution">
            {DISTRIBUTIONS.map(([label, key, write]) => (
              <tr key={key}>
                <td>{label}</td>
                {COLUMNS.map((column) => (
                  <td key={column}>{write(stat(`${key}.${column}`))}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollTable>
      <h3>Each sampled trial</h3>
      <Download id="robustness-download" file={`random-dates-seed-${run.schedule.seed ?? "unknown"}.csv`} rows={() => trials.trials}>
        Download original trial results and dates
      </Download>
      <TrialTable trials={shown.trials} />
      <label>
        Inspect an original trial{" "}
        <select id="robustness-trial" value={String(inspect)} onChange={(event) => setInspect(Number(event.currentTarget.value))}>
          {trials.trials.map((trial) => (
            <option key={trial.trial} value={String(trial.trial)}>
              Trial {trial.trial} · {trial.first_trade ?? "—"} · CAGR {percent(trial.cagr)}
            </option>
          ))}
        </select>
      </label>{" "}
      <button id="robustness-inspect" type="button" onClick={() => select({ trial: inspect, tab: "returns" })}>
        Show stocks and period returns
      </button>
      <details class="how-it-works">
        <summary>How to read this</summary>
        <p class="hint">
          Return distribution: bars show observed trial counts. Strategy and paired SPY use the same bins and axes. Dashed bell curves are normal fits, not evidence that returns are normally distributed. They are not confidence intervals.
        </p>
        <p class="hint">Percentiles use linear interpolation. Std. dev. describes the sampled scenarios. Incomplete trials are listed in the trial table and excluded from both paired summaries.</p>
      </details>
    </div>
  );
}

/** One row for each trial: its window, first trade, number of periods, CAGR,
 *  paired SPY CAGR and difference, and its empty and short periods. */
function TrialTable({ trials }: { trials: TrialRow[] }) {
  return (
    <ScrollTable kind="latest-table">
      <table>
        <thead>
          <tr>
            <th>Trial</th>
            <th>Window start</th>
            <th>First trade</th>
            <th>End / mark</th>
            <th>Books</th>
            <th>Strategy CAGR</th>
            <th>Paired SPY CAGR</th>
            <th>Difference (pp)</th>
            <th>Empty periods</th>
            <th>Short books</th>
          </tr>
        </thead>
        <tbody id="robustness-trials">
          {trials.map((trial) => (
            <tr key={trial.trial}>
              <td>{trial.trial}</td>
              <td>{trial.start}</td>
              <td>{trial.first_trade ?? "—"}</td>
              <td>{trial.end}</td>
              <td>{trial.periods}</td>
              <td>{percent(trial.cagr)}</td>
              <td>{percent(trial.spy_cagr)}</td>
              <td>{bare(trial.excess_cagr)}</td>
              <td>{trial.empty_periods}</td>
              <td>{trial.short_periods}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollTable>
  );
}
