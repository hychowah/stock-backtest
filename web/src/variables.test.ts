import assert from "node:assert/strict";
import { test } from "node:test";
import type { Variable } from "./api/Variable.ts";
import { requestVariables } from "./variables.ts";

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
