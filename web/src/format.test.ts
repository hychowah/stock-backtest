import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDollars, formatPercent } from "./format.ts";

test("formatPercent shows a fraction with two decimals", () => {
  assert.equal(formatPercent(0.1234), "12.34%");
  assert.equal(formatPercent(-0.05), "-5.00%");
  assert.equal(formatPercent(0), "0.00%");
});

test("formatDollars shows two decimals", () => {
  assert.equal(formatDollars(1.5), "$1.50");
  assert.equal(formatDollars(12.5), "$12.50");
});

test("a missing value shows as a dash", () => {
  assert.equal(formatPercent(null), "—");
  assert.equal(formatPercent(undefined), "—");
  assert.equal(formatDollars(null), "—");
});
