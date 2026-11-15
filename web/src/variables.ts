import type { FileVariable } from "./api/FileVariable.ts";
import type { Variable } from "./api/Variable.ts";

/** The variables a request carries: the draft's own (from Tune), then the
 *  library entries that neither have one of those names nor use one. The
 *  server keeps only those that the steps read.
 *
 *  Names compare as the server compares them: case and spacing aside. The
 *  library comes in dependency order, so each entry follows those it uses. */
export function requestVariables(own: Readonly<Record<string, FileVariable>>, library: readonly Variable[]): Record<string, FileVariable> {
  const taken = new Set(Object.keys(own).map(nameKey));
  const variables: Record<string, FileVariable> = { ...own };
  for (const entry of library) {
    if (taken.has(nameKey(entry.name)) || entry.uses.some((name) => taken.has(nameKey(name)))) continue;
    variables[entry.name] = { formula: entry.formula, display: entry.display };
  }
  return variables;
}

/** A name as names compare: lower case, with each run of spaces as one
 *  space and none at the ends. */
export function nameKey(name: string): string {
  return name.trim().replace(/\s+/g, " ").toLowerCase();
}
