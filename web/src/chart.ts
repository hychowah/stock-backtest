/** Where the server's numbers go on a chart: scales, ticks, histogram bins and
 *  the text of SVG paths. The module places given values on the screen and
 *  computes no statistic, return or growth: a distribution's mean and standard
 *  deviation are the server's, passed in. The components in `charts/` draw
 *  the axes, marks and hover readout from it. */

/** A value's place on an axis, in the SVG's units. */
type Scale = (value: number) => number;

/** The lowest value a log scale tells apart: a total loss sits at this floor
 *  instead of at minus infinity. */
const FLOOR = 1e-4;

/** A straight scale: `low` at `from`, `high` at `to`. Equal values (no span)
 *  put everything at `from`. */
export function linearScale(low: number, high: number, from: number, to: number): Scale {
  const span = high - low || 1;
  return (value) => from + ((value - low) / span) * (to - from);
}

function extent(values: readonly number[]): [number, number] {
  let low = Infinity;
  let high = -Infinity;
  for (const value of values) {
    low = Math.min(low, value);
    high = Math.max(high, value);
  }
  return [low, high];
}

/** A log scale for values that grow by percentages (the value of $1): equal
 *  heights are equal percentage moves. It fits `values` with a margin of 3%
 *  of the log range at each end and puts the lowest at `from` and the
 *  highest at `to`. `low` and `high` are the values at the two ends. */
export function logAxis(values: readonly number[], from: number, to: number): { at: Scale; low: number; high: number } {
  const logs = values.map((value) => Math.log(Math.max(value, FLOOR)));
  const [lowest, highest] = extent(logs);
  const bottom = lowest - 0.03;
  const top = highest + 0.03;
  const span = top - bottom;
  return { at: (value) => from + ((Math.log(Math.max(value, FLOOR)) - bottom) / span) * (to - from), low: Math.exp(bottom), high: Math.exp(top) };
}

/** `count + 1` evenly spaced values from `low` to `high`, ends included. */
export function evenTicks(low: number, high: number, count: number): number[] {
  return Array.from({ length: count + 1 }, (_, i) => low + ((high - low) * i) / count);
}

/** Round dollar values for a log axis within [low, high]: the 1, 2 and 5
 *  steps of each power of ten over a wide range, even steps (1, 2, 2.5, 5 or
 *  10 times a power of ten) over a narrow one. */
export function dollarTicks(low: number, high: number): number[] {
  const found: number[] = [];
  for (let k = Math.floor(Math.log10(low)); k <= Math.ceil(Math.log10(high)); k++) {
    for (const step of [1, 2, 5]) {
      const value = step * 10 ** k;
      if (value >= low && value <= high) found.push(value);
    }
  }
  if (found.length >= 3) return found;
  const rough = (high - low) / 4;
  const unit = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((factor) => factor * unit).find((value) => value >= rough) ?? rough;
  const first = Math.ceil(low / step);
  return Array.from({ length: Math.max(0, Math.floor(high / step) - first + 1) }, (_, i) => Number(((first + i) * step).toPrecision(12)));
}

/** The time of an ISO day, in ms (UTC midnight). */
export const dayTime = (day: string) => Date.parse(day + "T00:00:00Z");

/** Date ticks for a window from `first` to `last` (ms): the 1st of January,
 *  labelled with the year, over three years or more, every `step` years so
 *  that about twelve fit; the 1st of a month, labelled `2023-04`, over a
 *  shorter window. */
export function dayTicks(first: number, last: number): { time: number; label: string }[] {
  const start = new Date(first);
  const end = new Date(last);
  const months = (end.getUTCFullYear() - start.getUTCFullYear()) * 12 + end.getUTCMonth() - start.getUTCMonth();
  const yearly = months >= 36;
  const unit = yearly ? 12 : 1;
  const step = Math.ceil(months / unit / 12) * unit;
  const found: { time: number; label: string }[] = [];
  for (let m = start.getUTCMonth() + 1; ; m++) {
    const time = Date.UTC(start.getUTCFullYear(), m, 1);
    if (time > last) break;
    const date = new Date(time);
    const wanted = yearly ? date.getUTCMonth() === 0 && date.getUTCFullYear() % (step / 12) === 0 : m % step === 0;
    if (wanted) found.push({ time, label: yearly ? String(date.getUTCFullYear()) : date.toISOString().slice(0, 7) });
  }
  return found;
}

/** The index of the time in `times` (increasing) that is nearest to `time`. */
export function nearest(times: readonly number[], time: number): number {
  let low = 0;
  let high = times.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if ((times[mid] ?? 0) < time) low = mid + 1;
    else high = mid;
  }
  const before = times[low - 1];
  return low > 0 && before !== undefined && time - before < (times[low] ?? 0) - time ? low - 1 : low;
}

/** A line through points: `M x,y L x,y …`, one decimal each. */
export function linePath(points: readonly (readonly [number, number])[]): string {
  return points.map(([x, y], i) => (i ? "L" : "M") + x.toFixed(1) + "," + y.toFixed(1)).join("");
}

/** The closed shape between an upper line and a lower one, which both run
 *  left to right: along the upper line, back along the lower, closed. */
export function bandPath(upper: readonly (readonly [number, number])[], lower: readonly (readonly [number, number])[]): string {
  return linePath(upper) + "L" + [...lower].reverse().map(([x, y]) => x.toFixed(1) + "," + y.toFixed(1)).join("L") + "Z";
}

/** One series of a histogram: its values, and the mean and standard
 *  deviation the server gave for them (null when it gave none). */
export type Series = { values: readonly number[]; mean: number | null; stddev: number | null };

/** The bins of one or more series on shared axes. */
export type Histogram = {
  /** The first bin's lower edge and the last bin's upper edge. */
  low: number;
  high: number;
  /** The width of one bin. */
  width: number;
  /** For each series, the number of values in each bin. */
  counts: number[][];
};

/** The number of bins: 1 when all values are the same, else 3 per square root
 *  of the number of values, from 12 to 40. */
function binCount(n: number, varied: boolean): number {
  return varied ? Math.min(40, Math.max(12, Math.ceil(3 * Math.sqrt(n)))) : 1;
}

/** Bins the series on one set of edges. The range is the values' and each
 *  series' mean ± 3 standard deviations, widened by a margin of 0.6 standard
 *  deviations (at least 1% of the first value, at least 0.0001). Null for no
 *  values at all. */
export function histogram(series: readonly Series[]): Histogram | null {
  const all = series.flatMap((s) => [...s.values]);
  const first = all[0];
  if (first === undefined) return null;
  const [lowest, highest] = extent(all);
  const bins = binCount(
    Math.max(...series.map((s) => s.values.length)),
    highest > lowest,
  );
  const pad = Math.max(...series.map((s) => (s.stddev ?? 0) * 0.6), Math.abs(first) * 0.01, 0.0001);
  const bounds = series.filter((s) => s.mean !== null).flatMap((s) => [s.mean! - 3 * (s.stddev ?? 0), s.mean! + 3 * (s.stddev ?? 0)]);
  const low = Math.min(lowest, ...bounds) - pad;
  const high = Math.max(highest, ...bounds) + pad;
  const width = (high - low) / bins;
  const counts = series.map((s) => {
    const row = Array<number>(bins).fill(0);
    for (const value of s.values) row[Math.min(bins - 1, Math.floor((value - low) / width))]!++;
    return row;
  });
  return { low, high, width, counts };
}

/** The height of a normal curve with the given mean and standard deviation at
 *  `x`, scaled to a histogram of `n` values with bins of `width`: the count
 *  that a bin at `x` would hold. 0 without a spread. */
export function normalCount(x: number, mean: number, stddev: number, n: number, width: number): number {
  return stddev > 0 ? ((n * width) / (stddev * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * ((x - mean) / stddev) ** 2) : 0;
}

/** Where each slice of a pie starts and ends, in percent of the circle, from
 *  the slices' values and the total that they are parts of (the server's
 *  gains or losses of the period): a slice's angle is its value's part of the
 *  total. The total is above 0, since the slices are positive parts of it. */
export function pieArcs(values: readonly number[], total: number): { start: number; end: number }[] {
  let cursor = 0;
  return values.map((value) => {
    const start = cursor;
    cursor += (value / total) * 100;
    return { start, end: cursor };
  });
}
