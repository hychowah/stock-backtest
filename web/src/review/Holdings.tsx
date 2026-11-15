import type { Attribution } from "../api/Attribution.ts";
import type { HoldingsReply } from "../api/HoldingsReply.ts";
import type { JoinedHolding } from "../api/JoinedHolding.ts";
import type { PeriodRow } from "../api/PeriodRow.ts";
import type { RunRow } from "../api/RunRow.ts";
import type { StepRow } from "../api/StepRow.ts";
import { Pie, type Slice } from "../charts/Pie.tsx";
import { ScrollTable } from "../common/ScrollTable.tsx";
import { StepTrail } from "../common/StepTrail.tsx";
import { settingsOf, trailOf } from "../describe.ts";
import { type Display, format, percent, points, rounded } from "../format.ts";
import type { Read } from "../read.ts";
import { useSelection } from "./selection.ts";

/** The holdings of one period of the chosen trial, as the shared selection
 *  has it: a choice of the period, the contribution pies of the period, and a
 *  row for each holding with its Details and step trail. A sector in the
 *  selection limits the rows to that sector; the ranks, weights and
 *  contributions stay those of the whole period. `holdings` is the read of
 *  that one period's holdings. */
export function Holdings({ run, periods, holdings, attributions }: { run: RunRow; periods: PeriodRow[]; holdings: Read<HoldingsReply>; attributions: Read<Attribution[]> }) {
  const { selection, select } = useSelection();
  const period = periods.find((row) => row.period === selection.period);
  const rank = rankingOf(run);
  return (
    <div>
      <h3>Explore each rebalance</h3>
      <label>
        Holding period{" "}
        <select id="schedule-period" value={String(selection.period)} onChange={(event) => select({ period: Number(event.currentTarget.value) })}>
          {periods.map((row) => (
            <option key={row.period} value={String(row.period)}>
              {row.period}. {row.entry} → {row.exit} · {row.names} stocks
            </option>
          ))}
        </select>
      </label>
      <p id="schedule-sector-note" class="hint">
        {selection.sector === undefined ? "Original selected stocks; ranks and weights are unchanged." : `Sector filter: ${selection.sector}. Ranks and weights remain those of the whole original book.`}
      </p>
      <details id="schedule-attribution-disclosure">
        <summary>Stock return contributions</summary>
        <div id="schedule-attribution">
          {attributions.state === "loading" && <p>Reading contributions…</p>}
          {attributions.state === "failed" && <p>{attributions.failure.message}</p>}
          {attributions.state === "done" && <Attribute attribution={attributions.value.find((row) => row.period === selection.period)} />}
        </div>
      </details>
      {holdings.state === "loading" && <p class="hint">Reading the holdings…</p>}
      {holdings.state === "failed" && <p class="screen-message warning">{holdings.failure.message}</p>}
      {holdings.state === "done" && <Table run={run} holdings={holdings.value} period={period} sector={selection.sector} rank={rank} />}
    </div>
  );
}

function Table({ run, holdings, period, sector, rank }: { run: RunRow; holdings: HoldingsReply; period: PeriodRow | undefined; sector: string | undefined; rank: Ranking }) {
  const rows = holdings.holdings.filter((holding) => sector === undefined || holding.sector === sector);
  return (
    <ScrollTable kind="latest-table">
      <table id="schedule-stock-table" class="stock-table">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Stock / company</th>
            <th>Sector</th>
            <th>Entry weight</th>
            <th id="schedule-multiple-head">{rank.heading}</th>
            <th>Period return</th>
            <th>Contribution</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody id="schedule-stock-body">
          {rows.map((holding) => (
            <Holding key={holding.rank} run={run} holding={holding} steps={holdings.steps.filter((step) => step.rank === holding.rank)} display={rank.display(holding)} />
          ))}
          {!rows.length && (
            <tr>
              <td colspan={8}>{period ? "No matching stocks in this period." : "This trial has no such period."}</td>
            </tr>
          )}
        </tbody>
      </table>
    </ScrollTable>
  );
}

type Ranking = { heading: string; display: (holding: JoinedHolding) => Display };

/** How the page writes a holding's ranking value: the display of the last
 *  Rank step of the sleeve that first picked it, and the column heading (the
 *  direction too when the strategy has one sleeve). */
function rankingOf(run: RunRow): Ranking {
  const { strategy, steps } = settingsOf(run);
  const last = (sleeve: number) => strategy.sleeves[sleeve - 1]?.steps.findLastIndex((step) => "rank" in step) ?? -1;
  const only = strategy.sleeves.length === 1 ? strategy.sleeves[0]?.steps[last(1)] : undefined;
  const heading = only && "rank" in only ? `Ranking value · ${only.order}` : "Ranking value";
  return { heading, display: (holding) => steps[holding.sleeve - 1]?.[last(holding.sleeve)]?.display ?? "number" };
}

function Holding({ run, holding, steps, display }: { run: RunRow; holding: JoinedHolding; steps: StepRow[]; display: Display }) {
  const details: [string, string][] = [
    ["Exchange", holding.exchange],
    ["Market cap", format(holding.market_cap, "usd_million")],
    ["Enterprise value", format(holding.enterprise_value, "usd_million")],
    ["Fiscal date", holding.fiscal],
    ["Entry", holding.entry],
    ["Exit / mark", holding.exit],
    ["Exit basis", holding.status],
  ];
  return (
    <tr>
      <td>{holding.rank}</td>
      <td>
        <strong>{holding.symbol}</strong>
        <small class="holding-company">{holding.name}</small>
      </td>
      <td>{holding.sector}</td>
      <td>{percent(holding.weight)}</td>
      <td>{format(holding.ranking_value, display)}</td>
      <td>{percent(holding.return)}</td>
      <td>{rounded(holding.contribution)} pp</td>
      <td>
        <details class="holding-details">
          <summary>Details</summary>
          <dl>
            {details.map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <StepTrail trails={trailOf(settingsOf(run), holding, steps)} />
        </details>
      </td>
    </tr>
  );
}

/** The contributions of one period: the pie of its gains and the pie of its
 *  losses, each cut into the top holdings and the rest, and the top holdings
 *  in words. All numbers are the contributions route's. */
function Attribute({ attribution }: { attribution: Attribution | undefined }) {
  if (!attribution || !attribution.count) return <p>No stocks to attribute.</p>;
  const { top } = attribution;
  const slices = (sign: 1 | -1, rest: number): Slice[] => {
    const parts: Slice[] = top.filter((holding) => holding.contribution * sign > 0).map((holding) => ({ label: holding.symbol, value: holding.contribution * sign, contribution: holding.contribution, other: false }));
    if (rest > 0) parts.push({ label: sign > 0 ? "Other gainers" : "Other losers", value: rest, contribution: rest * sign, other: true });
    return parts;
  };
  return (
    <>
      <h3>Top 10 contributors</h3>
      <div class="contribution-pies">
        <Pie slices={slices(1, attribution.other_gains)} total={attribution.gains} sign={1} />
        <Pie slices={slices(-1, attribution.other_losses)} total={attribution.losses} sign={-1} />
      </div>
      <p>
        Top {top.length} stocks: {top.map((holding) => `${holding.symbol} (${points(holding.contribution)})`).join(", ")}. Contributions use all {attribution.count} selected stocks; pies show gains and losses separately.
      </p>
    </>
  );
}
