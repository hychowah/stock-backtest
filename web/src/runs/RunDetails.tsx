import type { RunRow } from "../api/RunRow.ts";
import type { TrialsReply } from "../api/TrialsReply.ts";
import { client } from "../client.ts";
import { headlineCells, settingsLines, settingsOf } from "../describe.ts";
import { useRead } from "../read.ts";

/** What a row's open Details says about its run: the settings, one line each
 *  (describe.ts), and for a saved run its headline and its id. It reads the
 *  run when it is drawn, so a row that nobody opens reads nothing; the row
 *  draws it only while its Details is open, and opening Details again reads
 *  again. */
export function RunDetails({ id, saved }: { id: number; saved: boolean }) {
  const read = useRead<[RunRow, TrialsReply | null]>(() => Promise.all([client.run(id), saved ? client.trials(id) : null]), [id, saved]);
  if (read.state === "loading") return <p role="status">Reading the saved settings…</p>;
  if (read.state === "failed") return <p role="status">The saved settings were not read. {read.failure.message} Close Details and open it again to retry.</p>;
  const [run, trials] = read.value;
  return (
    <>
      {settingsLines(settingsOf(run)).map((line) => (
        <p key={line.key}>
          {line.label}: {line.text}
        </p>
      ))}
      {trials && (
        <>
          <dl class="headline">
            {headlineCells(run.schedule, trials).map((cell) => (
              <div key={cell.key}>
                <dt>{cell.label}</dt>
                <dd>{cell.text}</dd>
              </div>
            ))}
          </dl>
          <p class="saved-id">Saved ID: {run.id}</p>
        </>
      )}
    </>
  );
}
