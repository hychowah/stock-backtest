import type { ScreenReply } from "../api/ScreenReply.ts";
import type { StrategyFile } from "../api/StrategyFile.ts";
import { Download } from "../common/Download.tsx";
import { ScrollTable } from "../common/ScrollTable.tsx";
import { StepTrail } from "../common/StepTrail.tsx";
import { type RunSettings, trailOf } from "../describe.ts";
import { count, format } from "../format.ts";

/** A latest screen: the strategy sent and the server's reply. */
export type Screen = { strategy: StrategyFile; reply: ScreenReply };

const HEADS = [
  "Rank",
  "Symbol",
  "Company",
  "Exchange",
  "Sector",
  "Adj. price (USD)",
  "Market cap",
  "Enterprise value",
  "EBITDA/EV",
  "EV/EBITDA",
  "Fiscal year-end",
  "Available from (assumed)",
  "Price date",
  "Details",
];

/** The settings of a screen that its step trails read. */
function screenSettings(screen: Screen): RunSettings {
  const { reply } = screen;
  return {
    market: reply.market,
    schedule: { start: reply.day, end: reply.day },
    strategy: screen.strategy,
    steps: reply.description.sleeves.map((sleeve) => sleeve.steps),
  };
}

/** The latest picks: the screened session, the count and the picks' medians,
 *  the CSV download, and
 *  one row per pick with its step trail under Details. `stale` marks picks
 *  that do not match the current settings. */
export function Latest({ screen, stale, hidden }: { screen: Screen | null; stale: boolean; hidden: boolean }) {
  const reply = screen?.reply;
  const settings = screen && screenSettings(screen);
  return (
    <section id="latest-view" class="panel" hidden={hidden} data-results-stale={String(stale)}>
      <div class="toolbar">
        <h2>
          Stock picks · <span id="latest-date">{reply?.day ?? "—"}</span>
        </h2>
        <div class="latest-facts">
          <span>
            Selected stocks<strong id="latest-count">{reply ? count(reply.picks.length) : "—"}</strong>
          </span>
          <span>
            Median market cap<strong id="latest-median-cap">{format(reply?.median_market_cap, "usd_million")}</strong>
          </span>
          <span>
            Median EBITDA yield<strong id="latest-median-yield">{format(reply?.median_ebitda_yield, "percent")}</strong>
          </span>
        </div>
        {reply && (
          <Download id="download-latest" file={`latest-picks-${reply.day}.csv`} rows={() => reply.picks.map(({ steps: _steps, ...pick }) => pick)}>
            Download latest picks ↓
          </Download>
        )}
      </div>
      <p class="hint">A saved-data screen at this session’s cached prices, not a live quote feed. Price and listing coverage limit which stocks can be picked.</p>
      <ScrollTable kind="latest-table">
        <table class="stock-table">
          <thead>
            <tr>
              {HEADS.map((head) => (
                <th key={head}>{head}</th>
              ))}
            </tr>
          </thead>
          <tbody id="latest-body">
            {reply && settings && reply.picks.length ? (
              reply.picks.map((pick) => (
                <tr key={pick.symbol}>
                  <td>{pick.rank}</td>
                  <td>{pick.symbol}</td>
                  <td>{pick.name}</td>
                  <td>{pick.exchange}</td>
                  <td>{pick.sector || "Unknown"}</td>
                  <td>{format(pick.price, "number")}</td>
                  <td>{format(pick.market_cap, "usd_million")}</td>
                  <td>{format(pick.enterprise_value, "usd_million")}</td>
                  <td>{format(pick.ebitda_yield, "percent")}</td>
                  <td>{format(pick.ev_ebitda, "multiple")}</td>
                  <td>{pick.fiscal}</td>
                  <td>{pick.known}</td>
                  <td>{pick.price_date}</td>
                  <td>
                    <details class="holding-details">
                      <summary>Details</summary>
                      <StepTrail trails={trailOf(settings, pick, pick.steps)} />
                    </details>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={HEADS.length}>{reply ? "No stocks match these latest-date filters." : "No latest picks yet."}</td>
              </tr>
            )}
          </tbody>
        </table>
      </ScrollTable>
      <details class="how-it-works">
        <summary>How this works</summary>
        <p class="hint">
          Re-ranked using prices on this exact session and available annual financials, with the selected market’s reporting policy and an 800-day report-age limit. US uses 90 days; HK/Japan
          use verified publication dates where available, otherwise four/three calendar months. Stocks without a price on this date, including old trading stops, are excluded.
        </p>
        <p class="hint">
          Market cap and EV are estimates at the displayed date using dividend-adjusted prices and report net debt. “Available from” follows the market’s publication-date or fallback policy. FMP coverage, later statement revisions and corporate-action data can limit
          accuracy. No holding return or contribution exists yet for these picks.
        </p>
      </details>
    </section>
  );
}
