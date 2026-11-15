import assert from "node:assert/strict";
import { test } from "node:test";
import { formatPercent } from "./format.ts";

test("formatPercent shows a fraction with two decimals", () => {
  assert.equal(formatPercent(0.1234), "12.34%");
  assert.equal(formatPercent(-0.05), "-5.00%");
  assert.equal(formatPercent(0), "0.00%");
});

test("a missing value shows as a dash", () => {
  assert.equal(formatPercent(null), "—");
  assert.equal(formatPercent(undefined), "—");
});
