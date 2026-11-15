import type { PeriodRow } from "../api/PeriodRow.ts";
import { evenTicks, linearScale } from "../chart.ts";
import { percent } from "../format.ts";
import { ScrollChart } from "./ScrollChart.tsx";

const [LEFT, WIDTH, TOP, HEIGHT] = [60, 1100, 30, 260];

/** One bar of the strategy (green) and one of SPY (grey) for each rebalance
 *  period of a trial: its return from entry to exit, as the server gives it.
 *  The axis runs from the lowest return (or 0) to the highest (or 10%); the
 *  entry day is labelled under about twelve of the periods. */
export function PeriodBars({ periods }: { periods: PeriodRow[] }) {
  const values = periods.flatMap((period) => [period.portfolio, period.spy]).filter(Number.isFinite);
  const low = values.reduce((a, b) => Math.min(a, b), 0);
  const high = values.reduce((a, b) => Math.max(a, b), 0.1);
  const y = linearScale(low, high, TOP + HEIGHT, TOP);
  const step = WIDTH / periods.length;
  const every = Math.max(1, Math.ceil(periods.length / 12));
  return (
    <ScrollChart id="schedule-chart" viewBox="0 0 1200 370" label="Custom schedule period returns">
      <line x1={LEFT} x2={LEFT + WIDTH} y1={y(0)} y2={y(0)} stroke="#acb8c5" />
      {evenTicks(low, high, 4).map((value) => (
        <text key={value} x={LEFT - 5} y={y(value) + 4} text-anchor="end" font-size="11">
          {percent(value)}
        </text>
      ))}
      {periods.map((period, i) => {
        const x = LEFT + i * step;
        const width = Math.max(0.3, (step - 2) / 2);
        return (
          <g key={period.period}>
            {(
              [
                [period.portfolio, 0, "#20775e", "Strategy"],
                [period.spy, width, "#acb8c5", "SPY"],
              ] as const
            ).map(([value, offset, color, who]) => {
              const text = `${period.entry} → ${period.exit} · ${who} ${percent(value)}`;
              return (
                <rect key={who} x={x + offset} y={Math.min(y(0), y(value))} width={width} height={Math.max(1, Math.abs(y(value) - y(0)))} fill={color} tabindex={0} aria-label={text}>
                  <title>{text}</title>
                </rect>
              );
            })}
            {i % every === 0 && (
              <text x={x} y="315" font-size="10" transform={`rotate(-35 ${x} 315)`}>
                {period.entry}
              </text>
            )}
          </g>
        );
      })}
    </ScrollChart>
  );
}
