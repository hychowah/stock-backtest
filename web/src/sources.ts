import type { CatalogReply } from "./api/CatalogReply.ts";
import type { DescribedStep } from "./api/DescribedStep.ts";
import type { Display } from "./api/Display.ts";
import type { FileVariable } from "./api/FileVariable.ts";
import type { Variable } from "./api/Variable.ts";
import { nameKey } from "./variables.ts";

/** What a step can read, as the source picker lists it: the catalog's names
 *  of the market and the variable library, in the groups of the picker. A
 *  step names its source by name, so a choice is a name. */

/** One choice of the picker. `detail` is its second line. */
export type Choice = { name: string; label: string; detail?: string };
export type Group = { label: string; choices: Choice[] };

/** The EV/EBITDA metrics, each with the direction that means cheaper. */
const METRICS: Record<string, string> = {
  "EBITDA yield": "Higher is cheaper",
  "EV/EBITDA": "Lower is cheaper",
  "3-year average EBITDA yield": "Higher is cheaper",
  "EV/3-year average EBITDA": "Lower is cheaper",
};

/** The picker's groups for a Filter or a Rank step:
 *  - Size and listing (Filters only): the catalog's fields, the sizes
 *    before the text fields (market cap, enterprise value, sector, exchange);
 *  - EV/EBITDA metrics, with the direction that means cheaper;
 *  - Built-in values: the other built-ins;
 *  - My variables: the library, favourites first, marked ★;
 *  - Financial inputs: the inputs and measures, with their category.
 *  A group that the catalog or library (still null while loading) does not
 *  fill is left out. */
export function sourceGroups(kind: "filter" | "rank", catalog: CatalogReply | null, library: readonly Variable[] | null): Group[] {
  const names = catalog?.names ?? [];
  const groups: Group[] = [];
  if (kind === "filter") {
    const fields = names.filter((name) => name.kind === "field");
    const sizesFirst = [...fields.filter((name) => name.unit !== "text"), ...fields.filter((name) => name.unit === "text")];
    groups.push({ label: "Size and listing", choices: sizesFirst.map((name) => ({ name: name.name, label: name.name })) });
  }
  groups.push({
    label: "EV/EBITDA metrics",
    choices: Object.entries(METRICS)
      .filter(([metric]) => names.some((name) => name.name === metric))
      .map(([metric, detail]) => ({ name: metric, label: metric, detail })),
  });
  groups.push({ label: "Built-in values", choices: names.filter((name) => name.kind === "built-in" && !(name.name in METRICS)).map((name) => ({ name: name.name, label: name.name })) });
  const favouritesFirst = [...(library ?? [])].sort((a, b) => Number(b.favourite) - Number(a.favourite));
  groups.push({ label: "My variables", choices: favouritesFirst.map((entry) => ({ name: entry.name, label: (entry.favourite ? "★ " : "") + entry.name, detail: "Saved variable" })) });
  groups.push({
    label: "Financial inputs",
    choices: names.filter((name) => name.kind === "input" || name.kind === "measure").map((name) => ({ name: name.name, label: name.name, detail: name.category })),
  });
  return groups.filter((group) => group.choices.length);
}

/** Whether a choice matches typed text: every word of the text is in its
 *  label or detail, ignoring case. */
export function matches(choice: Choice, typed: string): boolean {
  const text = [choice.label, choice.detail ?? ""].join(" ").toLowerCase();
  return typed.toLowerCase().split(/\s+/).filter(Boolean).every((word) => text.includes(word));
}

/** Where a source's display is found: the draft's own variables, the
 *  library, and the catalog. */
export type Known = { own: Readonly<Record<string, FileVariable>>; library: readonly Variable[]; catalog: CatalogReply | null };

/** What the page knows of a source by its name: its kind and display, or
 *  null for formula text and for a name it does not know (yet). A variable
 *  of the draft comes before a library entry of the same name, as in a
 *  request. */
export function describeSource(name: string, known: Known): Pick<DescribedStep, "source" | "display"> | null {
  const key = nameKey(name);
  const own = Object.entries(known.own).find(([own]) => nameKey(own) === key);
  if (own) return { source: { kind: "variable", name: own[0] }, display: own[1].display as Display };
  const entry = known.library.find((entry) => nameKey(entry.name) === key);
  if (entry) return { source: { kind: "variable", name: entry.name }, display: entry.display };
  const listed = known.catalog?.names.find((listed) => nameKey(listed.name) === key);
  return listed ? { source: { kind: listed.kind, name: listed.name }, display: listed.display } : null;
}

/** The market's text values of a text source (Sector, Exchange), or null for
 *  a source that is not text. */
export function textChoices(name: string, catalog: CatalogReply | null): string[] | null {
  const listed = catalog?.names.find((listed) => nameKey(listed.name) === nameKey(name));
  if (!catalog || listed?.unit !== "text") return null;
  return nameKey(name) === "exchange" ? catalog.exchanges : catalog.sectors;
}

const DISPLAY_NAMES: Record<Display, string> = {
  number: "Number",
  multiple: "Multiple (×)",
  percent: "Percent (%)",
  percentage_points: "Percentage points",
  usd: "US dollars",
  usd_million: "$ million",
  usd_per_share: "$ per share",
  shares: "Shares",
  text: "Text",
};

/** A display's name, as the unit beside a threshold: Percent (%). */
export function displayName(display: Display): string {
  return DISPLAY_NAMES[display];
}
