import type { StatisticRow } from "../api/StatisticRow.ts";
import type { TrialRow } from "../api/TrialRow.ts";
import { evenTicks, histogram, type Histogram, linePath, linearScale, normalCount, type Series } from "../chart.ts";
import { format } from "../format.ts";
import { statistic } from "../review/statistics.ts";
import { ScrollChart } from "./ScrollChart.tsx";

/** What the distribution shows: each trial's CAGR (with its paired SPY),
 *  its total return, or its CAGR difference to SPY. */
export type Measure = "cagr" | "total_return" | "excess_cagr";

export const MEASURE_OPTIONS: { value: Measure; label: string }[] = [
  { value: "cagr", label: "CAGR: strategy and SPY" },
  { value: "total_return", label: "Total return: strategy" },
  { value: "excess_cagr", label: "CAGR difference vs SPY" },
];

const AXIS_LABEL: Record<Measure, string> = { cagr: "CAGR", total_return: "Total return", excess_cagr: "CAGR difference vs SPY (pp)" };
const STRATEGY = "#20775e";
const SPY = "#557ca5";

/** The histogram of the trials' values of one measure, as bars of the number
 *  of trials in each bin, with a dashed normal curve and a dotted line at the
 *  mean of each series. The mean and the standard deviation of the curve are
 *  the server's statistics (`<measure>.mean` and `.stddev`); the page counts
 *  only. Strategy and paired SPY share bins and axes. `seed` is named in the
 *  note under the chart. */
export function Distribution({ measure, trials, statistics, seed }: { measure: Measure; trials: TrialRow[]; statistics: StatisticRow[]; seed?: number }) {
  const complete = trials.filter((trial) => Number.isFinite(trial.cagr));
  const named = (name: string, field: keyof TrialRow, stats: string) => ({
    name,
    color: name === "Paired SPY" ? SPY : STRATEGY,
    values: complete.map((trial) => trial[field]).filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
    mean: statistic(statistics, stats + ".mean"),
    stddev: statistic(statistics, stats + ".stddev"),
  });
  const series =
    measure === "cagr"
      ? [named("Strategy", "cagr", "cagr"), named("Paired SPY", "spy_cagr", "spy_cagr")]
      : measure === "total_return"
        ? [named("Strategy", "total_return", "total_return")]
        : [named("Strategy − SPY", "excess_cagr", "excess_cagr")];
  const write = (value: number) => format(value, measure === "excess_cagr" ? "percentage_points" : "percent");
  const bins = histogram(series);
  const note = `Seed ${seed ?? "not recorded"} · ${statistic(statistics, "valid") ?? "—"} complete trials.` + (series.every((s) => !s.stddev) ? " Each series has identical returns; no bell curves are fitted." : "");

  return (
    <>
      <ScrollChart id="robustness-chart" viewBox="0 0 1000 390" label="Return histogram and fitted normal curve">
        {bins === null ? (
          <text x="60" y="80">
            No complete trials to plot.
          </text>
        ) : (
          <Marks bins={bins} series={series} write={write} title={`${AXIS_LABEL[measure]} distribution for seed ${seed ?? "not recorded"}`} axis={AXIS_LABEL[measure]} />
        )}
      </ScrollChart>
      <p id="robustness-chart-note" class="hint">
        {note}
      </p>
    </>
  );
}

type Named = Series & { name: string; color: string };

function Marks({ bins, series, write, title, axis }: { bins: Histogram; series: Named[]; write: (value: number) => string; title: string; axis: string }) {
  const { low, high, width, counts } = bins;
  const top = Math.max(1, ...counts.flat(), ...series.map((s) => (s.mean !== null && s.stddev ? normalCount(s.mean, s.mean, s.stddev, s.values.length, width) : 0))) * 1.15;
  const x = linearScale(low, high, 70, 950);
  const y = linearScale(0, top, 310, 70);
  return (
    <>
      <title>{title}</title>
      {evenTicks(0, top, 4).map((count) => (
        <g key={count}>
          <line x1="70" x2="950" y1={y(count)} y2={y(count)} stroke="#dce3e8" />
          <text x="58" y={y(count) + 4} text-anchor="end" font-size="12">
            {count.toFixed(1)}
          </text>
        </g>
      ))}
      {series.map((s, j) => (
        <g key={s.name}>
          <rect x={70 + j * 400} y="12" width="14" height="14" fill={s.color} />
          <text x={92 + j * 400} y="24" font-size="13">
            {s.name}
            {s.mean === null ? " · no data" : " · mean " + write(s.mean)}
          </text>
          {counts[j]!.map((count, i) => (
            <rect key={i} tabindex={0} x={x(low + i * width) + 1} y={y(count)} width={880 / counts[j]!.length - 2} height={310 - y(count)} fill={s.color} opacity=".45">
              <title>{`${s.name}: ${write(low + i * width)} to ${write(low + (i + 1) * width)}: ${count} trials`}</title>
            </rect>
          ))}
          {s.mean !== null && s.stddev ? (
            <path
              d={linePath(Array.from({ length: 201 }, (_, i) => [x(low + ((high - low) * i) / 200), y(normalCount(low + ((high - low) * i) / 200, s.mean!, s.stddev!, s.values.length, width))] as const))}
              fill="none"
              stroke={s.color}
              stroke-width="3"
              stroke-dasharray="7 4"
            />
          ) : null}
          {s.mean !== null && <line x1={x(s.mean)} x2={x(s.mean)} y1="60" y2="310" stroke={s.color} stroke-dasharray="3 4" />}
        </g>
      ))}
      {evenTicks(low, high, 5).map((value) => (
        <text key={value} x={x(value)} y="335" text-anchor="middle" font-size="12">
          {write(value)}
        </text>
      ))}
      <text x="510" y="370" text-anchor="middle" font-size="14">
        {axis}
      </text>
      <text transform="translate(18,180) rotate(-90)" text-anchor="middle" font-size="14">
        Trial count
      </text>
    </>
  );
}
