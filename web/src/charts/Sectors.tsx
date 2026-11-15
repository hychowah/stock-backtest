import { percent } from "../format.ts";

/** One bar of the sector chart: a trial's, or a period's. A segment is one
 *  sector's weight, the server's fraction of the portfolio. `cash` is the
 *  fraction held in cash (a trial's share of empty periods; 1 for an empty
 *  period); no cash segment is drawn for 0. */
export type SectorBar = { key: number; text: string; weights: { sector: string; weight: number }[]; cash: number };

/** The colour of a sector, by its place in the list of all the result's
 *  sectors, so that a sector keeps its colour in every view. */
const COLORS = ["#42674b", "#8aa481", "#aec4a1", "#cfb47d", "#c8906b", "#90afb5", "#b6a3bc", "#a1b6c8", "#a4ad81", "#d5bba7", "#8e97b1"];
export const sectorColor = (sectors: readonly string[], sector: string) => COLORS[Math.max(0, sectors.indexOf(sector)) % COLORS.length]!;

/** Stacked bars of sector weights, one button for each bar: the segments
 *  are as high as the weights, in percent of the bar. A sector other than
 *  `chosen` is dimmed while one is chosen, `selected` marks one bar, and
 *  `thin` labels the bars 1, k, 2k, … with k set to about twelve labels over
 *  the chart (a long list of periods) instead of every bar. A bar is 24 px
 *  wide, and the chart at least 280. Pressing a bar gives its key to
 *  `onPick`. */
export function SectorBars({ bars, sectors, chosen, selected, thin, onPick }: { bars: SectorBar[]; sectors: readonly string[]; chosen: string | undefined; selected?: number; thin: boolean; onPick: (key: number) => void }) {
  const step = Math.max(1, Math.ceil(bars.length / 12));
  return (
    <div id="sector-chart" style={`min-width:${Math.max(280, bars.length * 24)}px`}>
      {bars.map((bar) => (
        <button key={bar.key} type="button" class={"sector-bar " + (bar.key === selected ? "selected" : "")} data-sector-bar={bar.key} aria-label={`${bar.text} · inspect selections`} onClick={() => onPick(bar.key)}>
          <span class="sector-stack">
            {bar.weights
              .filter((part) => part.weight > 0)
              .map((part) => (
                <span key={part.sector} class={"sector-segment " + (chosen !== undefined && chosen !== part.sector ? "dimmed" : "")} style={`height:${part.weight * 100}%;background:${sectorColor(sectors, part.sector)}`} title={`${part.sector} ${percent(part.weight)}`} />
              ))}
            {bar.cash > 0 && <span class="sector-segment sector-cash" style={`height:${bar.cash * 100}%`} title={`Cash ${percent(bar.cash)}`} />}
          </span>
          <span class="sector-bar-label">{thin ? (bar.key % step === 0 || bar.key === 1 ? bar.text.slice(0, 10) : "·") : bar.key}</span>
        </button>
      ))}
    </div>
  );
}
