import { pieArcs } from "../chart.ts";
import { percent, points } from "../format.ts";

/** One slice of a contribution pie: a holding, or the rest of the gainers or
 *  losers. `value` sets its angle and is positive; `contribution` is what the
 *  legend writes (negative for a loser). Both are the server's fractions of
 *  the portfolio. */
export type Slice = { label: string; value: number; contribution: number; other: boolean };

const GAIN_COLORS = ["#20775e", "#359671", "#549e7b", "#77b38f", "#95c8a6", "#16745b", "#428b76", "#66b6a0", "#88c9b7", "#b1dbc8"];
const LOSS_COLORS = ["#ae4d40", "#c96957", "#db8a70", "#e3a38d", "#edc0ac"];

/** One pie of the gains (`sign` 1) or of the losses (-1) of a period: a
 *  ring cut into slices, with the period's total in the middle and a legend
 *  that writes each slice's contribution and its share of the pie. `total`
 *  is the server's gains or losses of the period (a positive number); a
 *  slice's angle, and the share written for it, is its value's part of it. */
export function Pie({ slices, total, sign }: { slices: Slice[]; total: number; sign: 1 | -1 }) {
  const heading = sign > 0 ? "Gains" : "Losses";
  const colors = sign > 0 ? GAIN_COLORS : LOSS_COLORS;
  const arcs = pieArcs(
    slices.map((slice) => slice.value),
    total,
  );
  const parts = slices.map((slice, i) => ({ ...slice, color: slice.other ? (sign > 0 ? "#d8e3dc" : "#e8cbc3") : colors[i % colors.length]!, arc: arcs[i]! }));
  const written = points(sign * total);
  const share = (part: (typeof parts)[number]) => percent(part.value / total);
  const description =
    total > 0 ? `${heading} contribution ${written}. ${parts.map((part) => `${part.label}: ${share(part)} of ${heading.toLowerCase()}`).join("; ")}` : `No ${heading.toLowerCase()} in this book.`;
  return (
    <figure>
      <h4>{heading}</h4>
      <div
        class="contribution-pie"
        role="img"
        aria-label={description}
        style={`background:${parts.length ? "conic-gradient(" + parts.map((part) => `${part.color} ${part.arc.start}% ${part.arc.end}%`).join(",") + ")" : "#e5eae4"}`}
      >
        <div class="contribution-pie-center">
          {written}
          <small>portfolio impact</small>
        </div>
      </div>
      {parts.length ? (
        <ul class="contribution-legend">
          {parts.map((part) => (
            <li key={part.label}>
              <i style={`background:${part.color}`} />
              {part.label} · {share(part)} · {points(part.contribution)}
            </li>
          ))}
        </ul>
      ) : (
        <p class="hint">No {heading.toLowerCase()} in this period.</p>
      )}
    </figure>
  );
}
