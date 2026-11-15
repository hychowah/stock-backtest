import type { CatalogReply } from "./api/CatalogReply.ts";
import type { CheckedFormula } from "./api/CheckedFormula.ts";
import type { Display } from "./api/Display.ts";
import type { Fault } from "./api/Fault.ts";
import type { Unit } from "./api/Unit.ts";
import type { Variable } from "./api/Variable.ts";
import { type Draft, isRank, sourceOf } from "./draft.ts";
import { describeSource, displayName, type Known } from "./sources.ts";
import { nameKey } from "./variables.ts";

/** The formula editor's rules. The server reads each formula and answers
 *  with its picture, unit and displays, or a fault with its characters and
 *  suggestions; the page only places them in the text and decides what Use
 *  puts in the step. A check carries no display, so the display of a checked
 *  formula is its unit's default. */

/** The characters `[start, end)` of a fault, which the server counts in
 *  Unicode code points, as a range of the text's UTF-16 units: the units of
 *  a field's selection and of `slice`. */
export function faultRange(text: string, fault: Pick<Fault, "start" | "end">): [number, number] {
  const points = Array.from(text);
  const units = (count: number) => points.slice(0, count).join("").length;
  return [units(fault.start), units(fault.end)];
}

/** The check line of a fault: its message, then the characters at fault when
 *  the message does not quote them. */
export function faultLine(text: string, fault: Fault): string {
  const [start, end] = faultRange(text, fault);
  const bad = text.slice(start, end).trim();
  return "✗ " + fault.message + (bad && !fault.message.includes(bad) ? ` (“${bad}”)` : "");
}

const UNIT_NAMES: Record<Unit, string> = {
  scalar: "ratio",
  USD: "US dollars",
  "USD/share": "US dollars per share",
  share: "shares",
  text: "text",
};

/** The check line of a formula that reads. */
export const readyLine = (checked: CheckedFormula) => "✓ Ready · Result: " + UNIT_NAMES[checked.unit];

/** The display the editor shows: the chosen one while the formula's unit
 *  allows it, else the unit's default. */
export function shownDisplay(chosen: string | null, checked: CheckedFormula): Display {
  return checked.displays.find((display) => display === chosen) ?? checked.display;
}

/** What the editor holds as the step's current source: the source's name or
 *  text, its formula text and its display (null: the unit's default). */
export type Opened = { source: string; text: string; display: string | null };

/** What "Edit formula" opens for a step's source: a library entry, a
 *  variable of the draft (`own`), or formula text. */
export type Edited = { opened: Opened; entry: Variable | null; own: boolean };

/** Whether a step's source is formula text: a name that neither the draft,
 *  the library nor the catalog knows. Unknown (false) until the catalog and
 *  the library (`loaded`) are read. */
export function isFormulaText(name: string, known: Known, loaded: boolean): boolean {
  return loaded && known.catalog !== null && describeSource(name, known) === null;
}

/** What "Edit formula" opens for a step's source. Null for a catalog name,
 *  and while the catalog or the library (`loaded`) is not read. */
export function editedSource(name: string, known: Known, loaded: boolean): Edited | null {
  if (!loaded || !known.catalog) return null;
  const described = describeSource(name, known);
  if (described?.source.kind === "variable") {
    const key = nameKey(described.source.name);
    const own = Object.entries(known.own).find(([own]) => nameKey(own) === key);
    if (own) return { opened: { source: own[0], text: own[1].formula, display: own[1].display }, entry: null, own: true };
    const entry = known.library.find((entry) => nameKey(entry.name) === key)!;
    return { opened: { source: entry.name, text: entry.formula, display: entry.display }, entry, own: false };
  }
  return described ? null : { opened: { source: name, text: name, display: null }, entry: null, own: false };
}

/** How a name is typed in a formula, as the server writes it: as it is when
 *  it starts with a letter, else in square brackets with each `]` doubled. */
export function spelling(name: string): string {
  return /^(?!\p{N})\p{Alphabetic}/u.test(name) ? name : `[${name.replaceAll("]", "]]")}]`;
}

/** A word of the typing list: shown as `name` with `detail`, inserted as
 *  `text`. */
export type Word = { name: string; text: string; detail: string };

/** The words of the typing list, in this order: the library entries, the
 *  catalog's names that a formula can read (not step-only), with their
 *  display's name, and the functions with their meaning. A function is
 *  inserted as its word and "(": the word is the letters just before the
 *  first "(" of its form, as in "average(INPUT, N years)" and
 *  "A / positive(B)". */
export function formulaWords(library: readonly Variable[], catalog: CatalogReply | null): Word[] {
  const words: Word[] = library.map((entry) => ({ name: entry.name, text: spelling(entry.name), detail: "My variable" }));
  for (const listed of catalog?.names ?? []) if (!listed.step_only) words.push({ name: listed.name, text: spelling(listed.name), detail: displayName(listed.display) });
  for (const { form, meaning } of catalog?.functions ?? []) {
    const word = /(\w+)\(/.exec(form)?.[1];
    if (word) words.push({ name: word, text: word + "(", detail: meaning });
  }
  return words;
}

const fold = (text: string) => text.replace(/\s+/g, " ").toLowerCase();

/** The typing list for the text before the caret: the fragment starts at the
 *  first letter (not after a letter, digit or "_") from which the rest of the
 *  text, folded (case and runs of spaces aside), begins a word of a name, so
 *  "total d" can cover several words. The names that start with it come
 *  first, then the others in `words` order; at most 8. Null when nothing
 *  matches, or when the one match is the fragment itself. */
export function typingMatches(before: string, words: readonly Word[]): { start: number; words: Word[] } | null {
  for (let at = 0; at < before.length; at++) {
    if (!/[a-z]/i.test(before[at]!) || /\w/.test(before[at - 1] ?? "")) continue;
    const partial = fold(before.slice(at));
    const found = words.filter((word) => (" " + fold(word.name)).includes(" " + partial));
    if (!found.length) continue;
    found.sort((a, b) => Number(fold(b.name).startsWith(partial)) - Number(fold(a.name).startsWith(partial)));
    return found.length > 1 || fold(found[0]!.name) !== partial ? { start: at, words: found.slice(0, 8) } : null;
  }
  return null;
}

/** What Use puts in the step: the source the editor holds while its text and
 *  display are unchanged; else the checked formula text. A step shows formula
 *  text in its unit's default display, so another display needs a saved
 *  variable: then null. */
export function useSource(opened: Opened | null, text: string, display: Display, checked: CheckedFormula): string | null {
  if (opened && text === opened.text && display === (opened.display ?? checked.display)) return opened.source;
  return display === checked.display ? checked.canonical : null;
}

const reads = (draft: Draft, key: string) => draft.sleeves.some((sleeve) => sleeve.steps.some((step) => nameKey(sourceOf(step)) === key));
const owns = (draft: Draft, key: string) => Object.keys(draft.variables).some((name) => nameKey(name) === key);

/** The draft after library entry `from` was renamed `to`: its steps that
 *  read `from` read `to`. A draft with a variable of its own named `from`
 *  reads that variable, so it stays as it is. */
export function renameSource(draft: Draft, from: string, to: string): Draft {
  const key = nameKey(from);
  if (owns(draft, key) || !reads(draft, key)) return draft;
  return {
    ...draft,
    sleeves: draft.sleeves.map((sleeve) => ({
      ...sleeve,
      steps: sleeve.steps.map((step) => (nameKey(sourceOf(step)) !== key ? step : isRank(step) ? { ...step, rank: to } : { ...step, filter: to })),
    })),
  };
}

/** The draft after library entry `gone` was deleted: when its steps read the
 *  entry (and no variable of its own has that name), it keeps its own copy of
 *  the entry and of the entries that the entry uses, in library order, so
 *  that its steps read the same formulas. A used entry that the draft has an
 *  identical variable of its own for is not copied again. When the draft has
 *  one that differs (in formula or display), the copy would read it instead,
 *  so nothing is copied and the step stays refused, as it was. */
export function keepCopy(draft: Draft, gone: Variable, library: readonly Variable[]): Draft {
  const key = nameKey(gone.name);
  if (owns(draft, key) || !reads(draft, key)) return draft;
  const needed = new Set(gone.uses.map(nameKey));
  const used = library.filter((entry) => entry.id !== gone.id && needed.has(nameKey(entry.name)));
  const ownOf = (entry: Variable) => Object.entries(draft.variables).find(([name]) => nameKey(name) === nameKey(entry.name))?.[1];
  const differs = (entry: Variable) => {
    const own = ownOf(entry);
    return own !== undefined && (own.formula !== entry.formula || own.display !== entry.display);
  };
  if (used.some(differs)) return draft;
  const copied = [...used.filter((entry) => !ownOf(entry)), gone];
  const variables = { ...draft.variables };
  for (const entry of copied) variables[entry.name] = { formula: entry.formula, display: entry.display };
  return { ...draft, variables };
}
