import type { Display } from "./api/Display.ts";
import type { Market } from "./api/Market.ts";

export type { Display };

/** How the page writes one value. A source's value is in its unit (dollars, a
 *  plain number, a fraction). Its display says how to write it: usd_million
 *  $1,234.00M, percent 12.34%, and so on. One table, keyed by the generated
 *  Display. Also writes dates, the time since a start, and an error's place
 *  in words.
 *
 *  Every number on screen has the same rounding (rounded()): 2 decimals;
 *  below 0.01, 2 significant digits; below 0.000001, 0.00. A missing value
 *  (null, or not finite) is a dash. */

const DASH = "—";

/** A market's name: US, Hong Kong, Japan · Tokyo. */
export function marketName(market: Market): string {
  return { us: "US", hk: "Hong Kong", jp: "Japan · Tokyo" }[market];
}

/** A number with the page's rounding, without grouping: 12.34, 0.0012. */
export function rounded(value: number): string {
  const size = Math.abs(value);
  return size < 1e-6 ? "0.00" : size < 0.01 ? value.toPrecision(2) : value.toFixed(2);
}

/** Thousands separators in the whole part of a written number. */
const grouped = (text: string) => text.replace(/^(-?)(\d+)/, (_all, sign: string, whole: string) => sign + whole.replace(/\B(?=(\d{3})+$)/g, ","));

/** `$` after the sign: -$5, $5. */
const dollars = (text: string) => text.replace(/^(-?)/, "$1$$");

/** For each display: how a value in its unit is written, and how a threshold
 *  typed in the display (decimal text, as a strategy file holds it) is
 *  written. A text source (sector, exchange) is written as it is. A display
 *  missing from the table fails the type check. */
const DISPLAYS: Record<Display, { value: (value: number) => string; typed: (text: string) => string }> = {
  number: { value: rounded, typed: (text) => text },
  multiple: { value: (value) => rounded(value) + "×", typed: (text) => text + "×" },
  percent: { value: (value) => rounded(value * 100) + "%", typed: (text) => text + "%" },
  percentage_points: { value: (value) => rounded(value * 100) + " pp", typed: (text) => text + " pp" },
  usd: { value: (value) => dollars(grouped(rounded(value))), typed: (text) => dollars(grouped(text)) },
  usd_million: { value: (value) => dollars(grouped(rounded(value / 1e6))) + "M", typed: (text) => dollars(grouped(text)) + "M" },
  usd_per_share: { value: (value) => dollars(rounded(value)) + " per share", typed: (text) => dollars(text) + " per share" },
  shares: { value: (value) => grouped(rounded(value)) + " shares", typed: (text) => grouped(text) + " shares" },
  text: { value: rounded, typed: (text) => text },
};

/** A source's value in its display, such as 12.34% for 0.1234 in percent. */
export function format(value: number | null | undefined, display: Display): string {
  return value == null || !Number.isFinite(value) ? DASH : DISPLAYS[display].value(value);
}

/** A threshold as a strategy file holds it (decimal text in the display's
 *  units), written with its display: "100" in usd_million is $100M. */
export function formatTyped(text: string, display: Display): string {
  return DISPLAYS[display].typed(text);
}

/** A fraction as a percentage: 0.1234 is 12.34%. */
export const percent = (value: number | null | undefined) => format(value, "percent");

/** A difference of fractions in percentage points, with a plus sign for a
 *  gain: 0.05 is +5.00 pp. */
export function points(value: number | null | undefined): string {
  return value != null && value > 0 && Number.isFinite(value) ? "+" + format(value, "percentage_points") : format(value, "percentage_points");
}

/** A whole count with thousands separators: 1,000. */
export const count = (value: number) => value.toLocaleString("en-US");

/** A time of the server (ISO, such as `2026-11-15T06:00:00Z` or an as-of
 *  time with its offset) in the viewer's time zone, short: 15 Nov, 14:05. */
export function formatTime(utc: string): string {
  return new Date(utc).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** A length of time in whole seconds: 45 sec, 2 min 5 sec, 1 hr 0 min 5 sec. */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  return (hours ? hours + " hr " : "") + (minutes || hours ? minutes + " min " : "") + (s % 60) + " sec";
}

/** The time from a UTC start of the server to `now` (ms), as formatDuration. */
export function since(utc: string, now: number): string {
  return formatDuration((now - Date.parse(utc)) / 1000);
}

/** The words of the keys of a request that the server names as a place. */
const KEYS: Record<string, string> = {
  market: "Market",
  name: "Name",
  start: "Start date",
  end: "End date",
  every: "Rebalance interval",
  trials: "Trials",
  seed: "Random date set",
  dates: "Trade dates",
  strategy: "Strategy",
  sleeves: "Sleeves",
};

/** An error's place in words: `strategy: sleeves[1].steps[2], character 4`
 *  is "Sleeve 1, step 2, character 4"; `strategy: variables."Cheap"` is
 *  "Variable “Cheap”"; `every` is "Rebalance interval". A place of another
 *  form is returned as it is; it never throws. */
export function placeInWords(place: string): string {
  const inStrategy = place.replace(/^strategy: /, "");
  const step = /^sleeves\[(\d+)\](?:\.steps\[(\d+)\])?(?:\.(name|steps))?(, .*)?$/.exec(inStrategy);
  if (step) {
    const words = ["Sleeve " + step[1]];
    if (step[2]) words.push("step " + step[2]);
    if (step[3] === "name") words.push("name");
    return words.join(", ") + (step[4] ?? "");
  }
  const variable = /^variables\."((?:[^"\\]|\\.)*)"(?:\.(formula|display))?(, .*)?$/.exec(inStrategy);
  if (variable) {
    // The server writes the name as Rust's debug format does: only \" and
    // \\ are undone here; any other escape, such as \u{301}, stays as written.
    const name = (variable[1] ?? "").replace(/\\(["\\])/g, "$1");
    return `Variable “${name}”` + (variable[2] ? ", " + variable[2] : "") + (variable[3] ?? "");
  }
  return KEYS[inStrategy] ?? place;
}
