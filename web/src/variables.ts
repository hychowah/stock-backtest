import type { FileVariable } from "./api/FileVariable.ts";
import type { Variable } from "./api/Variable.ts";

/** The variables a request carries: the draft's own (from Tune, or copies
 *  of deleted library entries), then the library entries that neither have
 *  one of those names nor use an own variable that differs (in formula or
 *  display) from the library entry of its name. An entry that uses an own
 *  variable identical to the library's comes after it and reads the same
 *  formula. The server keeps only those that the steps read.
 *
 *  Names compare as the server compares them: case and spacing aside. The
 *  library comes in dependency order, so each entry follows those it uses. */
export function requestVariables(own: Readonly<Record<string, FileVariable>>, library: readonly Variable[]): Record<string, FileVariable> {
  const taken = new Set(Object.keys(own).map(nameKey));
  const differs = new Set(
    Object.entries(own)
      .filter(([name, variable]) => {
        const entry = library.find((entry) => nameKey(entry.name) === nameKey(name));
        return !entry || entry.formula !== variable.formula || entry.display !== variable.display;
      })
      .map(([name]) => nameKey(name)),
  );
  const variables: Record<string, FileVariable> = { ...own };
  for (const entry of library) {
    if (taken.has(nameKey(entry.name)) || entry.uses.some((name) => differs.has(nameKey(name)))) continue;
    variables[entry.name] = { formula: entry.formula, display: entry.display };
  }
  return variables;
}

/** The variables a formula check carries: those of a request, but while
 *  library entry `editing` is edited, only the entries that are not it and do
 *  not use it, so that its new formula cannot name itself. */
export function checkVariables(own: Readonly<Record<string, FileVariable>>, library: readonly Variable[], editing: Variable | null): Record<string, FileVariable> {
  if (!editing) return requestVariables(own, library);
  const key = nameKey(editing.name);
  return requestVariables(
    own,
    library.filter((entry) => entry.id !== editing.id && !entry.uses.some((name) => nameKey(name) === key)),
  );
}

/** The variables a formula check carries while the draft's own variable
 *  `name` is edited: the own variables before it, in the draft's order, and
 *  no library entry, which is what it can read in a request. */
export function ownCheckVariables(own: Readonly<Record<string, FileVariable>>, name: string): Record<string, FileVariable> {
  const names = Object.keys(own);
  return Object.fromEntries(names.slice(0, names.indexOf(name)).map((before) => [before, own[before]!]));
}

/** A name as names compare: lower case, with each run of spaces as one
 *  space and none at the ends. */
export function nameKey(name: string): string {
  return name.trim().replace(/\s+/g, " ").toLowerCase();
}
