import type { ComponentChildren } from "preact";
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import type { SectorShare } from "../api/SectorShare.ts";
import type { SectorsReply } from "../api/SectorsReply.ts";
import type { RunRow } from "../api/RunRow.ts";
import type { TrialsReply } from "../api/TrialsReply.ts";
import { type SectorBar, SectorBars, sectorColor } from "../charts/Sectors.tsx";
import { client } from "../client.ts";
import { percent } from "../format.ts";
import { asFailure, useRead } from "../read.ts";
import { useSelection } from "./selection.ts";
import { statistic } from "./statistics.ts";

/** What the sector view covers: `all` trials together, or the one trial that
 *  the shared selection has, period by period. A fixed schedule has one trial
 *  and is always `trial`. `placed` is the trial for which the view has set
 *  the shared period to the trial's last one (null before any): the
 *  one-trial view does it when it first shows a trial, then reads and sets
 *  that period, which Returns shares. The page keeps this while another tab
 *  is shown. */
export type SectorView = { scope: "all" | "trial"; placed: number | null };

type Across = Extract<SectorsReply, { trials: unknown }>;
type Weight = { sector: string; mean: number };
const bySize = (a: Weight, b: Weight) => b.mean - a.mean || a.sector.localeCompare(b.sector);

/** The Selection tab of a complete run: what the strategy selects, by sector.
 *  Across the trials, a bar for each trial and the spread of the trials'
 *  mean weights; for one trial, a bar for each rebalance and the weights of
 *  the chosen one. The sector in the shared selection is the chosen sector:
 *  pressing a legend entry or a row sets or clears it. Inspecting a trial or
 *  a period sets the shared selection (trial, period, sector) and shows the
 *  holdings on Returns. */
export function SelectionTab({ run, trials, view: [view, setView] }: { run: RunRow; trials: TrialsReply; view: [SectorView, (view: SectorView) => void] }) {
  const { selection, select } = useSelection();
  const random = run.schedule.trials !== undefined;
  const one = !random || view.scope === "trial";
  const all = useRead(() => client.sectors(run.id), [run.id]);
  const scopeChoice = (value: string) => {
    if (value === "all") return setView({ ...view, scope: "all" });
    setView({ ...view, scope: "trial" });
    select({ trial: Number(value), sector: selection.sector });
  };
  return (
    <section id="sector-view" class="panel" aria-labelledby="sector-heading">
      <div class="toolbar">
        <div>
          <h2 id="sector-heading">What does this strategy select?</h2>
          <p class="hint">Compare sector allocations, then inspect the original trial and stocks.</p>
        </div>
        <label>
          Review scope
          <select id="sector-trial" value={one ? String(selection.trial) : "all"} onChange={(event) => scopeChoice(event.currentTarget.value)}>
            {random && <option value="all">All original trials</option>}
            {trials.trials.map((each) => (
              <option key={each.trial} value={String(each.trial)}>
                {random ? `Trial ${each.trial}` : "Fixed schedule"}
              </option>
            ))}
          </select>
        </label>
      </div>
      {all.state !== "done" ? (
        <p id="sector-message" role="status" aria-live="polite">
          {all.state === "failed" ? all.failure.message : READING}
        </p>
      ) : one ? (
        <OneTrial key={selection.trial} run={run} trials={trials} across={all.value} view={[view, setView]} />
      ) : (
        <AllTrials run={run} trials={trials} across={all.value} />
      )}
      <details class="sector-method">
        <summary>How sector weights are calculated</summary>
        <p class="hint">
          Each stock has equal weight at entry. Divide the sector's stock count by the actual book size. Average rebalances within each trial, then average complete trials equally. Empty books count as cash. Missing labels remain Unavailable and stay in the denominator. These are entry allocations, not daily
          exposure or one combined portfolio. Labels are those recorded in the original result.
        </p>
      </details>
    </section>
  );
}

const READING = "Reading sector counts from original saved holdings…";

/** What a sector view draws, apart from its table or period controls. */
type View = {
  message: string;
  insight: string;
  chartTitle: string;
  chartNote: string;
  bars: SectorBar[];
  selected?: number;
  thin: boolean;
  onPick: (key: number) => void;
  legend: Weight[];
  mixTitle: string;
  mixNote: string;
  mix: (Weight & { note?: string })[];
  /** A note under the mix rows. */
  mixFoot?: string;
};

/** The message, the insight, the filter button, the bar chart with its
 *  legend and the mix rows, then `children`. A legend entry or a mix row sets
 *  the chosen sector in the shared selection, or clears it when it is the
 *  chosen one. */
function Body({ view, across, children }: { view: View; across: Across; children: ComponentChildren }) {
  const { selection, select } = useSelection();
  const chosen = selection.sector;
  const sectors = across.spread.map((row) => row.sector);
  const choose = (sector: string) => select({ sector: chosen === sector ? undefined : sector });
  return (
    <>
      <p id="sector-message" role="status" aria-live="polite">
        {view.message}
      </p>
      <p id="sector-insight" class="sector-insight" hidden={!view.insight}>
        {view.insight}
      </p>
      <button id="sector-clear" type="button" hidden={chosen === undefined} onClick={() => select({ sector: undefined })}>
        {chosen === undefined ? "Show all sectors" : `Clear ${chosen} filter`}
      </button>
      <div class="sector-grid">
        <section class="sector-card">
          <h3 id="sector-chart-title">{view.chartTitle}</h3>
          <p id="sector-chart-note" class="hint">
            {view.chartNote}
          </p>
          <div class="sector-chart-scroll" tabindex={0} role="region" aria-label="Sector allocation chart">
            <SectorBars bars={view.bars} sectors={sectors} chosen={chosen} selected={view.selected} thin={view.thin} onPick={view.onPick} />
          </div>
          <div id="sector-legend" class="sector-legend">
            {view.legend.map((each) => (
              <button key={each.sector} type="button" aria-pressed={chosen === each.sector} onClick={() => choose(each.sector)}>
                <i style={`background:${sectorColor(sectors, each.sector)}`} />
                {each.sector}
              </button>
            ))}
            <span>
              <i class="sector-cash" />
              Cash
            </span>
          </div>
        </section>
        <section class="sector-card">
          <h3 id="sector-mix-title">{view.mixTitle}</h3>
          <p id="sector-mix-note" class="hint">
            {view.mixNote}
          </p>
          <div id="sector-mix">
            {view.mix.map((each) => (
              <button key={each.sector} type="button" class="sector-mix-row" aria-pressed={chosen === each.sector} onClick={() => choose(each.sector)}>
                <span>
                  <i style={`background:${sectorColor(sectors, each.sector)}`} />
                  {each.sector}
                  <small>{each.note}</small>
                  <strong>{percent(each.mean)}</strong>
                </span>
                <span class="sector-track">
                  <span style={`width:${each.mean * 100}%;background:${sectorColor(sectors, each.sector)}`} />
                </span>
              </button>
            ))}
            {view.mixFoot && <p class="hint">{view.mixFoot}</p>}
          </div>
        </section>
      </div>
      {children}
    </>
  );
}

/** The sector view across the trials: a bar for each trial, the spread of
 *  the trials' mean weights, and a row for each trial with its inspect
 *  button. Only the latest press of an inspect button counts, and none counts
 *  once this tab is no longer shown. */
function AllTrials({ run, trials, across }: { run: RunRow; trials: TrialsReply; across: Across }) {
  const { selection, select } = useSelection();
  const [problem, setProblem] = useState("");
  const press = useRef(0);
  useEffect(() => () => void press.current++, []);
  const chosen = selection.sector;

  /** Shows the holdings of a trial on Returns, in the last period that holds
   *  the sector (the last period when there is none). */
  async function inspect(number: number, sector: string | undefined) {
    const mine = ++press.current;
    setProblem("");
    try {
      const { weights } = await client.sectors(run.id, number);
      if (mine !== press.current) return;
      const last = trials.trials[number - 1]!.periods;
      const period = sector === undefined ? last : (weights.findLast((weight) => weight.sector === sector && weight.weight > 0)?.period ?? last);
      select({ trial: number, period, sector, tab: "returns" });
    } catch (failure) {
      if (mine === press.current) setProblem(asFailure(failure).message);
    }
  }

  const shares = new Map<number, SectorShare[]>();
  for (const share of across.trials) shares.set(share.trial, [...(shares.get(share.trial) ?? []), share]);
  const cash = new Map(across.cash.map((each) => [each.trial, each.cash]));
  const overall = [...across.spread].sort(bySize);
  const valid = statistic(trials.statistics, "valid");
  const lead = overall[0];
  const view: View = {
    message: problem || `${valid ?? "—"} complete trials · ${statistic(trials.statistics, "incomplete") ?? "—"} incomplete (excluded from the combined average).`,
    insight: lead ? `${lead.sector} has the largest mean allocation in ${lead.leading} of ${valid ?? "—"} complete trials. Mean entry allocation: ${percent(lead.mean)}.` : "No sector average is available.",
    chartTitle: "Sector mix in every trial",
    chartNote: "Average entry allocations within each trial. Select a trial bar to inspect its books.",
    bars: trials.trials.map((each) => ({ key: each.trial, text: `Trial ${each.trial}`, weights: (shares.get(each.trial) ?? []).map((share) => ({ sector: share.sector, weight: share.mean })), cash: cash.get(each.trial) ?? 0 })),
    thin: false,
    onPick: (key) => void inspect(key, chosen),
    legend: overall,
    mixTitle: "Average across complete trials",
    mixNote: "Ranges compare trial averages. Each complete trial counts equally.",
    mix: overall.map((each) => ({ sector: each.sector, mean: each.mean, note: `${percent(each.minimum)}–${percent(each.maximum)}` })),
    mixFoot: across.mean_cash > 0 ? `Average cash: ${percent(across.mean_cash)}.` : undefined,
  };
  return (
    <Body view={view} across={across}>
      <div id="sector-trials-wrap" class="latest-table" tabindex={0} role="region" aria-label="Sector allocation by trial">
        <table>
          <thead>
            <tr>
              <th>Trial</th>
              <th>Sector</th>
              <th>Average entry allocation</th>
              <th>Rebalance range</th>
              <th>Present</th>
              <th>Coverage</th>
              <th />
            </tr>
          </thead>
          <tbody id="sector-trials">
            {trials.trials.map((each) => {
              const own = shares.get(each.trial) ?? [];
              const shown = chosen === undefined ? [...own].sort(bySize)[0] : (own.find((share) => share.sector === chosen) ?? { sector: chosen, mean: 0, minimum: 0, maximum: 0, present: 0 });
              return (
                <tr key={each.trial}>
                  <td>{each.trial}</td>
                  <td>{shown?.sector ?? "Cash"}</td>
                  <td>{percent(shown ? shown.mean : cash.get(each.trial))}</td>
                  <td>{shown ? `${percent(shown.minimum)}–${percent(shown.maximum)}` : "—"}</td>
                  <td>
                    {shown?.present ?? 0} / {each.periods}
                  </td>
                  <td>Complete</td>
                  <td>
                    <button type="button" data-sector-inspect={each.trial} onClick={() => void inspect(each.trial, shown?.sector)}>
                      Inspect →
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Body>
  );
}

/** The sector view of the trial in the shared selection: a bar for each
 *  rebalance, the weights of one period, and the choice of the period, which
 *  is the shared period (the one Returns lists the holdings of). The first
 *  time the view shows a trial it sets the shared period to the trial's last
 *  one. Pressing a bar shows that period's holdings on Returns. */
function OneTrial({ run, trials, across, view: [state, setState] }: { run: RunRow; trials: TrialsReply; across: Across; view: [SectorView, (view: SectorView) => void] }) {
  const { selection, select } = useSelection();
  const trial = selection.trial;
  const settled = state.placed === trial;
  useLayoutEffect(() => {
    if (settled) return;
    select({ period: trials.trials[trial - 1]?.periods ?? 1 });
    setState({ ...state, placed: trial });
  }, [settled]);
  const detail = useRead(() => client.sectors(run.id, trial), [run.id, trial]);
  const periods = useRead(() => client.periods(run.id, trial), [run.id, trial]);
  const failed = [detail, periods].find((each) => each.state === "failed");
  if (!settled || detail.state !== "done" || periods.state !== "done") {
    return (
      <p id="sector-message" role="status" aria-live="polite">
        {failed?.state === "failed" ? failed.failure.message : READING}
      </p>
    );
  }
  const rows = periods.value;
  const current = selection.period;
  const period = rows.find((each) => each.period === current);
  const weights = new Map<number, { sector: string; weight: number; count: number }[]>();
  for (const weight of detail.value.weights) weights.set(weight.period, [...(weights.get(weight.period) ?? []), weight]);
  const mine = across.trials.filter((share) => share.trial === trial).sort(bySize);
  const lead = mine[0];
  const row = trials.trials[trial - 1];
  const view: View = {
    message: "",
    insight: lead ? `${lead.sector} averages ${percent(lead.mean)} at entry in this trial. ${row?.empty_periods ?? "—"} of ${row?.periods ?? "—"} rebalances hold cash.` : "No sector average is available.",
    chartTitle: "Sector mix through time",
    chartNote: "Entry allocation at each rebalance. Select a bar to inspect its stocks.",
    bars: rows.map((each) => ({ key: each.period, text: `${each.entry} → ${each.exit}`, weights: weights.get(each.period) ?? [], cash: each.names === 0 ? 1 : 0 })),
    selected: current,
    thin: true,
    onPick: (key) => select({ period: key, tab: "returns" }),
    legend: mine,
    mixTitle: period?.entry ?? "No period selected",
    mixNote: period ? `${period.names} selected stocks · held through ${period.exit}` : "",
    mix: (weights.get(current) ?? []).map((weight) => ({ sector: weight.sector, mean: weight.weight, note: `${weight.count} ${weight.count === 1 ? "stock" : "stocks"}` })).sort(bySize),
    mixFoot: period?.names === 0 ? "No stocks selected. The portfolio holds cash until the next rebalance." : undefined,
  };
  return (
    <Body view={view} across={across}>
      <div id="sector-period-controls" class="run-controls">
        <button type="button" id="sector-period-back" disabled={current === rows[0]?.period} onClick={() => select({ period: current - 1 })}>
          Previous rebalance
        </button>
        <label>
          Holding period
          <select id="sector-period" value={String(current)} onChange={(event) => select({ period: Number(event.currentTarget.value) })}>
            {rows.map((each) => (
              <option key={each.period} value={String(each.period)}>
                {each.period}. {each.entry} → {each.exit} · {each.names} stocks
              </option>
            ))}
          </select>
        </label>
        <button type="button" id="sector-period-next" disabled={current === rows[rows.length - 1]?.period} onClick={() => select({ period: current + 1 })}>
          Next rebalance
        </button>
      </div>
    </Body>
  );
}
