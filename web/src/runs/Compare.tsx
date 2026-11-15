import type { RunRow } from "../api/RunRow.ts";
import { ApiFailure, client } from "../client.ts";
import { settingsOf } from "../describe.ts";
import { asFailure } from "../read.ts";
import { type CompareRow, type Described, compareRuns } from "../runs.ts";

/** Reads each run for a comparison: its settings (GET /api/runs/{id}) and its
 *  trials reply. A run that cannot be read fails the whole read, with a
 *  message that names it. */
export function readDescribed(runs: RunRow[]): Promise<Described[]> {
  return Promise.all(
    runs.map(async ({ id, name }) => {
      try {
        const [run, trials] = await Promise.all([client.run(id), client.trials(id)]);
        return { name: run.name, schedule: run.schedule, settings: settingsOf(run), trials };
      } catch (thrown) {
        const failure = asFailure(thrown);
        throw new ApiFailure(failure.status, `Could not read “${name}”. ${failure.message}`, failure.place);
      }
    }),
  );
}

const Group = ({ title, rows, runs }: { title: string; rows: CompareRow[]; runs: number }) => (
  <tbody>
    <tr class="comparison-group">
      <th scope="rowgroup" colspan={runs + 1}>
        {title}
      </th>
    </tr>
    {rows.map((row) => (
      <tr key={row.key}>
        <th scope="row">{row.label}</th>
        {row.cells.map((cell, i) => (
          <td key={i}>{cell}</td>
        ))}
      </tr>
    ))}
  </tbody>
);

/** One column for each run, in the order given: the settings that differ,
 *  then the headline; under "More measures and all settings", the other
 *  measures of random dates, the settings that are the same, and the random
 *  date set of each run (a recorded fact, never a difference). Many runs
 *  scroll sideways inside the panel. */
export function Compare({ runs }: { runs: Described[] }) {
  const result = compareRuns(runs);
  const table = (caption: string, groups: [string, CompareRow[], boolean?][]) => (
    <div class="comparison-scroll">
      <table style={`min-width:${170 + 140 * runs.length}px`}>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <td />
            {runs.map((run, i) => (
              <th key={i} scope="col" title={run.name}>
                <span>{run.name}</span>
              </th>
            ))}
          </tr>
        </thead>
        {groups.filter(([, rows, keep]) => rows.length || keep).map(([title, rows]) => (
          <Group key={title} title={title} rows={rows} runs={runs.length} />
        ))}
      </table>
    </div>
  );
  const more = result.measures.length ? "More measures and all settings" : "All settings";
  return (
    <>
      {result.notices.map((text) => (
        <p key={text} class="comparison-notice">
          {text}
        </p>
      ))}
      {table(`Comparison of ${runs.length} ticked tests`, [
        [result.differ.length ? "Settings that differ" : "Same settings", result.differ, true],
        ["Headline", result.headline],
      ])}
      <details>
        <summary>{more}</summary>
        {table(`${more} of the ticked tests`, [
          ["More measures", result.measures],
          ["Same settings", result.same],
          ["Recorded", result.seed],
        ])}
      </details>
    </>
  );
}
