import { useState } from "preact/hooks";
import type { CurveReply } from "../api/CurveReply.ts";
import { bandPath, dayTicks, dayTime, dollarTicks, linePath, logAxis, nearest } from "../chart.ts";
import { client } from "../client.ts";
import { format } from "../format.ts";
import { useRead } from "../read.ts";

const STRATEGY = "#20775e";
const SPY = "#557ca5";
const [WIDTH, HEIGHT, LEFT, RIGHT, TOP, BOTTOM] = [1200, 350, 86, 1170, 48, 312];

type Line = { label: string; color: string; values: number[] };

/** Dollars on an axis: $2, $10, $1.50. */
const axisDollars = (value: number) => format(value, "usd").replace(/\.00$/, "");

/** The value of $1 day by day, from the server's curve of run `id`: one
 *  trial's growth with SPY's when `trial` is given (a fixed schedule has one
 *  trial), else the band over all trials with its median, and the median of
 *  SPY. A log scale. Pointing at the chart reads one day; at rest it reads
 *  the last. The ids are `curve-trial…` for a trial and `curve-all…` for
 *  the band. A failed read shows its message where the readout goes. */
export function Curve({ id, trial }: { id: number; trial?: number }) {
  const name = trial === undefined ? "all" : "trial";
  const read = useRead(() => client.curve(id, trial), [id, trial ?? 0]);
  const hint =
    trial === undefined
      ? "Middle line: the median trial on each day. Band: the lowest to the highest trial. Log scale: equal heights are equal % moves."
      : "Strategy and SPY from $1 at the start. Point at the chart to read a day. Log scale: equal heights are equal % moves.";
  return (
    <div id={"curve-" + name}>
      <h3>Value of $1 day by day</h3>
      <p class="hint">{hint}</p>
      <div style="overflow-x:auto">
        {read.state === "done" ? (
          <CurveChart name={name} reply={read.value} />
        ) : (
          <>
            <svg id={`curve-${name}-chart`} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Value of $1" style="min-width:640px" />
            <p id={`curve-${name}-readout`} class="hint">
              {read.state === "failed" ? read.failure.message : ""}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function CurveChart({ name, reply }: { name: string; reply: CurveReply }) {
  const band = "band" in reply ? reply.band : null;
  const growth = "growth" in reply ? reply.growth : [];
  const days = (band ?? growth).map((row) => row.day);
  const label = band ? "Value of $1 across all trials" : "Value of $1 for this trial and SPY";
  const [at, setAt] = useState(days.length - 1);
  const times = days.map(dayTime);
  const [first, last] = [times[0] ?? 0, times[times.length - 1] ?? 0];
  const span = last - first || 1;
  const x = (time: number) => LEFT + ((time - first) / span) * (RIGHT - LEFT);

  const lines: Line[] = band
    ? [
        { label: "Median trial", color: STRATEGY, values: band.map((row) => row.median) },
        { label: "SPY (median)", color: SPY, values: band.map((row) => row.spy) },
      ]
    : [
        { label: "Strategy", color: STRATEGY, values: growth.map((row) => row.strategy) },
        { label: "SPY", color: SPY, values: growth.map((row) => row.spy) },
      ];
  const everything = lines.flatMap((line) => line.values).concat(band ? band.flatMap((row) => [row.lowest, row.highest]) : []);
  const axis = logAxis(everything, BOTTOM, TOP);
  const points = (values: number[]) => values.map((value, i) => [x(times[i]!), axis.at(value)] as const);

  const readout = (i: number) => {
    const day = days[i]!;
    if (band) {
      const row = band[i]!;
      return `${day} · Median trial ${format(row.median, "usd")} (lowest ${format(row.lowest, "usd")}, highest ${format(row.highest, "usd")}) · SPY ${format(row.spy, "usd")}`;
    }
    const row = growth[i]!;
    return `${day} · Strategy ${format(row.strategy, "usd")} · SPY ${format(row.spy, "usd")}`;
  };
  const point = (event: PointerEvent) => {
    const box = (event.currentTarget as SVGSVGElement).getBoundingClientRect();
    const time = first + ((((event.clientX - box.left) / box.width) * WIDTH - LEFT) / (RIGHT - LEFT)) * span;
    setAt(nearest(times, time));
  };
  const marker = x(times[at] ?? last);

  return (
    <>
      <svg
        id={`curve-${name}-chart`}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={label}
        style="min-width:640px"
        onPointerMove={point}
        onPointerLeave={() => setAt(days.length - 1)}
      >
        {dollarTicks(axis.low, axis.high).map((value) => (
          <g key={value}>
            <line x1={LEFT} x2={RIGHT} y1={axis.at(value)} y2={axis.at(value)} stroke={value === 1 ? "#9aa8a4" : "#e3e8e1"} />
            <text x={LEFT - 8} y={axis.at(value) + 4} text-anchor="end" font-size="16">
              {axisDollars(value)}
            </text>
          </g>
        ))}
        {dayTicks(first, last).map((tick) => (
          <text key={tick.time} x={x(tick.time)} y={BOTTOM + 28} text-anchor="middle" font-size="16">
            {tick.label}
          </text>
        ))}
        {band && <path d={bandPath(points(band.map((row) => row.highest)), points(band.map((row) => row.lowest)))} fill={STRATEGY} opacity=".16" />}
        {lines.map((line, j) => (
          <g key={line.label}>
            <path d={linePath(points(line.values))} fill="none" stroke={line.color} stroke-width="2.5" />
            <line x1={LEFT + j * 240} x2={LEFT + 24 + j * 240} y1="18" y2="18" stroke={line.color} stroke-width="3" />
            <text x={LEFT + 32 + j * 240} y="24" font-size="17">
              {line.label}
            </text>
          </g>
        ))}
        {band && (
          <>
            <rect x={LEFT + lines.length * 240} y="11" width="24" height="14" fill={STRATEGY} opacity=".16" />
            <text x={LEFT + 32 + lines.length * 240} y="24" font-size="17">
              Lowest to highest trial
            </text>
          </>
        )}
        <line id={`curve-${name}-marker`} x1={marker} x2={marker} y1={TOP} y2={BOTTOM} stroke="#7a8a86" stroke-dasharray="3 3" />
      </svg>
      <p id={`curve-${name}-readout`} class="hint">
        {readout(at)}
      </p>
    </>
  );
}
