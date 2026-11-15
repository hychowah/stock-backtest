import assert from "node:assert/strict";
import { test } from "node:test";
import type { Variable } from "./api/Variable.ts";
import { checkVariables, ownCheckVariables, requestVariables } from "./variables.ts";

const entry = (id: number, name: string, uses: string[] = []): Variable => ({ id, name, formula: `ROE * ${id}`, display: "percent", favourite: false, uses });

test("the draft's own variables come first, then the library entries that neither share a name nor use one", () => {
  const own = { Quality: { formula: "ROE", display: "percent" }, "Net cash": { formula: "Cash and equivalents - Total debt", display: "usd_million" } };
  const library = [entry(1, "Cheap"), entry(2, "  quality "), entry(3, "Better", ["QUALITY"]), entry(4, "Best", ["Cheap"]), entry(5, "Net  Cash"), entry(6, "Deep", ["Cheap", "Net cash"])];
  const variables = requestVariables(own, library);
  assert.deepEqual(Object.keys(variables), ["Quality", "Net cash", "Cheap", "Best"]);
  assert.deepEqual(variables.Cheap, { formula: "ROE * 1", display: "percent" });
  assert.deepEqual(variables.Quality, own.Quality);
});

test("without own variables the request carries the whole library, in its order", () => {
  const library = [entry(2, "Base"), entry(1, "Built", ["Base"])];
  assert.deepEqual(Object.keys(requestVariables({}, library)), ["Base", "Built"]);
  assert.deepEqual(requestVariables({}, []), {});
});

test("while entry X is edited, the check carries the entries that are not X and do not use X", () => {
  const library = [entry(1, "Base"), entry(2, "Cheap"), entry(3, "Better", ["base"]), entry(4, "Best", ["Base", "Better"]), entry(5, "Other", ["Cheap"])];
  assert.deepEqual(Object.keys(checkVariables({}, library, library[0]!)), ["Cheap", "Other"]);
  assert.deepEqual(Object.keys(checkVariables({}, library, library[2]!)), ["Base", "Cheap", "Other"]);
  // A new formula reads the whole request: the draft's own variables, then the library.
  const own = { Mine: { formula: "ROE", display: "percent" } };
  assert.deepEqual(Object.keys(checkVariables(own, library, null)), ["Mine", "Base", "Cheap", "Better", "Best", "Other"]);
});

test("an entry that uses an own variable identical to the library's is sent after it; one that differs hides the entries that use it", () => {
  const library = [entry(1, "Base"), entry(2, "Aent", ["Base"]), entry(3, "Bent", ["Base"])];
  const copy = { Base: { formula: "ROE * 1", display: "percent" }, Aent: { formula: "Base * 2", display: "percent" } };
  assert.deepEqual(Object.keys(requestVariables(copy, library)), ["Base", "Aent", "Bent"]);
  assert.deepEqual(Object.keys(requestVariables({ base: { formula: "ROE * 1", display: "number" } }, library)), ["base"]);
  assert.deepEqual(Object.keys(requestVariables({ Base: { formula: "ROA", display: "percent" } }, library)), ["Base"]);
});

test("while an own variable is edited, the check carries the own variables before it and no library entry", () => {
  const own = { A: { formula: "ROE", display: "percent" }, V: { formula: "A * 2", display: "percent" }, X: { formula: "V * 2", display: "percent" } };
  assert.deepEqual(ownCheckVariables(own, "V"), { A: own.A });
  assert.deepEqual(ownCheckVariables(own, "A"), {});
});
