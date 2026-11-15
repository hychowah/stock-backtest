import { useEffect, useRef, useState } from "preact/hooks";
import type { ExploreReply } from "../api/ExploreReply.ts";
import type { Exploration } from "../api/Exploration.ts";
import type { RunRow } from "../api/RunRow.ts";
import type { TrialRow } from "../api/TrialRow.ts";
import type { TrialsReply } from "../api/TrialsReply.ts";
import { client } from "../client.ts";
import { statistic, tradeDays } from "../describe.ts";
import { percent } from "../format.ts";
import { asFailure, useRead } from "../read.ts";

/** The reply of an Explore of all trials: the trials and statistics of the
 *  selected window and ranks, to show in place of the original ones. */
export type ExploredTrials = Extract<ExploreReply, { trials: unknown }>;

const ALL_STATUS = "Summary across all saved trials. No backtest was run.";
const CHANGED = "Selection changed. Select Apply to update the summary.";

/** `first` for one date, else `first … last`: the entry days of a period over
 *  the trials. */
function label(days: string[]): string {
  const sorted = [...days].sort();
  const [first, last] = [sorted[0], sorted[sorted.length - 1]];
  return first === last ? (first ?? "") : `${first} … ${last}`;
}

/** The entry and exit labels of each period of all trials, from their trade
 *  days; null when the trials do not all have the same periods. */
function blocks(trials: TrialRow[]): { from: string[]; to: string[] } | null {
  const periods = trials[0]?.periods ?? 0;
  const days = trials.map((trial) => tradeDays(trial.dates));
  if (!periods || trials.some((trial, i) => trial.periods !== periods || days[i]!.length !== periods)) return null;
  const at = (i: number) => (i < periods ? days.map((row) => row[i]!) : trials.map((trial) => trial.end));
  return {
    from: Array.from({ length: periods }, (_, i) => label(at(i))),
    to: Array.from({ length: periods }, (_, i) => label(at(i + 1))),
  };
}

type Choice = { from: string; to: string; rankFrom: string; rankTo: string };

/** "Explore this result": a saved time window and stock rank range of the
 *  open result, summarised by the server without a new backtest. It starts
 *  closed and reads its date labels when it opens. A fixed schedule explores
 *  its one trial and shows that trial's returns for the selection. Random
 *  dates explore all trials: `onApplied` gives the page the selection's
 *  trials and statistics to show in place of the original ones, or null for
 *  the original. The defaults, and "Reset to original", are the strategy's
 *  ranks (`Description.ranks`) and all periods. A strategy with several
 *  sleeves explores time windows only. */
export function Explore({ run, trials, applied, onApplied, hidden }: { run: RunRow; trials: TrialsReply; applied: ExploredTrials | null; onApplied: (reply: ExploredTrials | null) => void; hidden: boolean }) {
  const all = run.schedule.trials !== undefined;
  const [first, last] = run.description!.ranks;
  const sleeves = run.description!.sleeves.length;
  const [opened, setOpened] = useState(false);
  const [chosen, setChosen] = useState<Choice | null>(null);
  const [status, setStatus] = useState("Choose a saved time window and stock ranks.");
  const [busy, setBusy] = useState(false);
  const [one, setOne] = useState<Exploration | null>(null);
  const sequence = useRef(0);
  const started = useRef(false);

  const periods = useRead(() => (opened && !all ? client.periods(run.id, 1) : Promise.resolve([])), [run.id, opened ? 1 : 0]);
  const labels = !opened
    ? null
    : all
      ? blocks(trials.trials)
      : periods.state === "done" && periods.value.length
        ? { from: periods.value.map((row) => row.entry), to: periods.value.map((row) => row.exit) }
        : null;
  const count = labels?.from.length ?? 0;
  const defaults: Choice = { from: "1", to: String(count), rankFrom: String(first), rankTo: String(last) };
  const now = chosen ?? defaults;

  async function summarise(choice: Choice) {
    const mine = ++sequence.current;
    setBusy(true);
    setStatus("Summarizing saved returns…");
    try {
      const reply = await client.explore(run.id, { trial: all ? "all" : 1, periods: `${choice.from}-${choice.to}`, ranks: `${choice.rankFrom}-${choice.rankTo}` });
      if (mine !== sequence.current) return;
      if ("trials" in reply) {
        const whole = choice.from === "1" && choice.to === String(count) && Number(choice.rankFrom) === first && Number(choice.rankTo) === last;
        onApplied(whole ? null : reply);
        setStatus(ALL_STATUS);
      } else {
        setOne(reply);
        setStatus("Summary of saved returns. No backtest was run.");
      }
    } catch (thrown) {
      if (mine === sequence.current) setStatus(asFailure(thrown).message);
    } finally {
      if (mine === sequence.current) setBusy(false);
    }
  }

  function reset() {
    sequence.current++;
    setChosen(null);
    if (all) {
      onApplied(null);
      setBusy(false);
      setStatus(ALL_STATUS);
    } else void summarise(defaults);
  }

  useEffect(() => {
    if (opened && !all && count && !started.current) {
      started.current = true;
      void summarise(defaults);
    }
    if (opened && all && !started.current) {
      started.current = true;
      setStatus(labels ? ALL_STATUS : "Complete saved trial dates are required.");
    }
  }, [opened, count, labels === null]);

  const change = (field: keyof Choice) => (event: Event) => {
    sequence.current++;
    setBusy(false);
    setChosen({ ...now, [field]: (event.target as HTMLInputElement | HTMLSelectElement).value });
    setStatus(CHANGED);
  };

  const shown = applied ?? { statistics: trials.statistics, trials: trials.trials };
  const window = all
    ? applied
      ? { start: applied.start, end: applied.end, from: applied.rank_from, to: applied.rank_to, periods: applied.periods }
      : { start: trials.trials[0]?.start ?? "—", end: trials.trials[0]?.end ?? "—", from: first, to: last, periods: trials.trials[0]?.periods ?? 0 }
    : one && { start: one.start, end: one.end, from: one.rank_from, to: one.rank_to, periods: one.periods };
  const windowText = window
    ? `${window.start} → ${window.end} · ranks ${window.from}–${window.to} · ${window.periods} holding periods` + (all ? ` per trial · ${statistic(shown.statistics, "completed") ?? "—"} trials` : "")
    : "";
  const cash = shown.trials.filter((trial) => trial.empty_periods > 0).length;
  const coverage = all
    ? `${statistic(shown.statistics, "valid") ?? "—"} complete trials; ${statistic(shown.statistics, "incomplete") ?? "—"} incomplete trials. Trials with cash periods: ${cash}. Empty selections hold cash at 0%; SPY keeps its period return. Counts appear in the trial table.`
    : one
      ? `${one.short} short periods; ${one.empty} empty periods.` + (one.empty ? " Empty periods hold cash at 0%; SPY keeps its period return." : "") + (one.cash_days ? ` Includes ${one.cash_days} initial days in cash.` : "")
      : "";

  return (
    <details id="result-explorer" hidden={hidden} onToggle={(event) => event.currentTarget.open && setOpened(true)} aria-busy={busy ? "true" : "false"}>
      <summary id="explore-title">{all ? `Explore all ${statistic(trials.statistics, "completed") ?? ""} trials` : "Explore this result"}</summary>
      <p class="hint">
        View a saved time window and stock rank range without rerunning the backtest. Random-date selections apply to all saved trials. Dates identify their original entry and exit blocks.
      </p>
      <div class="filter-grid">
        <label>
          <span id="explore-from-label">{all ? "From entry block" : "From entry"}</span>
          <select id="explore-period-from" aria-label="Exploration start" value={now.from} onInput={change("from")}>
            {labels?.from.map((text, i) => (
              <option key={i} value={String(i + 1)}>
                {text}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span id="explore-to-label">{all ? "Through exit block" : "Through exit / mark"}</span>
          <select id="explore-period-to" aria-label="Exploration end" value={now.to} onInput={change("to")}>
            {labels?.to.map((text, i) => (
              <option key={i} value={String(i + 1)}>
                {text}
              </option>
            ))}
          </select>
        </label>
        <label id="explore-rank-from-field" hidden={sleeves > 1}>
          From rank
          <input id="explore-rank-from" type="number" min={first} max={last} step="1" value={now.rankFrom} onInput={change("rankFrom")} />
        </label>
        <label id="explore-rank-to-field" hidden={sleeves > 1}>
          Through rank
          <input id="explore-rank-to" type="number" min={first} max={last} step="1" value={now.rankTo} onInput={change("rankTo")} />
        </label>
      </div>
      <div class="run-controls">
        <button id="explore-apply" type="button" class="primary" disabled={!labels} onClick={() => void summarise(now)}>
          Apply
        </button>
        <button id="explore-reset" type="button" disabled={!labels} onClick={reset}>
          Reset to original
        </button>
      </div>
      <p id="explore-status" role="status" aria-live="polite">
        {periods.state === "failed" ? periods.failure.message : status}
      </p>
      <p id="explore-window">{windowText}</p>
      {all ? (
        <div id="explore-trials" class="latest-facts">
          <span>
            Mean strategy CAGR<strong id="robustness-mean">{percent(statistic(shown.statistics, "cagr.mean"))}</strong>
          </span>
          <span>
            Median strategy CAGR<strong id="robustness-median">{percent(statistic(shown.statistics, "cagr.median"))}</strong>
          </span>
          <span>
            Mean paired SPY CAGR<strong id="robustness-spy">{percent(statistic(shown.statistics, "spy_cagr.mean"))}</strong>
          </span>
        </div>
      ) : (
        <table id="explore-summary" aria-label="Selected window returns">
          <thead>
            <tr>
              <th>Portfolio</th>
              <th>Total return</th>
              <th>CAGR</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Strategy</td>
              <td id="explore-strategy-return">{percent(one?.total_return)}</td>
              <td id="explore-strategy-cagr">{percent(one?.cagr)}</td>
            </tr>
            <tr>
              <td>SPY</td>
              <td id="explore-spy-return">{percent(one?.spy_total_return)}</td>
              <td id="explore-spy-cagr">{percent(one?.spy_cagr)}</td>
            </tr>
          </tbody>
        </table>
      )}
      <p id="explore-coverage" class="hint">
        {coverage}
      </p>
      <p class="hint">
        This summary is temporary. For random dates, the distribution chart, the statistics and the trial table in Overview also show this selection. The headline, holding details, downloads and comparisons use the original result.
      </p>
    </details>
  );
}
