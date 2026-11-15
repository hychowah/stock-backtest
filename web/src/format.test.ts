import assert from "node:assert/strict";
import { test } from "node:test";
import { format, formatDuration, formatTyped, placeInWords, points, rounded } from "./format.ts";

test("numbers have 2 decimals, 2 significant digits below 0.01, and 0.00 below 0.000001", () => {
  assert.equal(rounded(12.345), "12.35");
  assert.equal(rounded(-3), "-3.00");
  assert.equal(rounded(0.0123), "0.01");
  assert.equal(rounded(0.001234), "0.0012");
  assert.equal(rounded(-0.00456), "-0.0046");
  assert.equal(rounded(0.0000004), "0.00");
  assert.equal(rounded(0), "0.00");
});

test("each display writes a value in its unit", () => {
  assert.equal(format(0.1234, "percent"), "12.34%");
  assert.equal(format(0.00001234, "percent"), "0.0012%");
  assert.equal(format(-0.05, "percentage_points"), "-5.00 pp");
  assert.equal(format(7.159, "multiple"), "7.16×");
  assert.equal(format(1234567890, "usd_million"), "$1,234.57M");
  assert.equal(format(-2500000, "usd_million"), "-$2.50M");
  assert.equal(format(12583039190.255821, "usd"), "$12,583,039,190.26");
  assert.equal(format(3.5, "usd_per_share"), "$3.50 per share");
  assert.equal(format(1500000, "shares"), "1,500,000.00 shares");
  assert.equal(format(2.5, "number"), "2.50");
  assert.equal(format(null, "percent"), "—");
  assert.equal(format(Number.NaN, "usd"), "—");
});

test("a typed threshold keeps its text and gains its display's sign", () => {
  assert.equal(formatTyped("100", "usd_million"), "$100M");
  assert.equal(formatTyped("13000000000", "usd"), "$13,000,000,000");
  assert.equal(formatTyped("-0.5", "percent"), "-0.5%");
  assert.equal(formatTyped("8", "multiple"), "8×");
});

test("a difference has a plus sign only for a gain", () => {
  assert.equal(points(0.05), "+5.00 pp");
  assert.equal(points(-0.012), "-1.20 pp");
  assert.equal(points(0), "0.00 pp");
});

test("a duration is written in hours, minutes and seconds", () => {
  assert.equal(formatDuration(5.9), "5 sec");
  assert.equal(formatDuration(125), "2 min 5 sec");
  assert.equal(formatDuration(3605), "1 hr 0 min 5 sec");
});

test("an error's place is written in words", () => {
  assert.equal(placeInWords("strategy: sleeves[1].steps[2]"), "Sleeve 1, step 2");
  assert.equal(placeInWords("strategy: sleeves[2].steps[1], character 10"), "Sleeve 2, step 1, character 10");
  assert.equal(placeInWords("strategy: sleeves[3].name"), "Sleeve 3, name");
  assert.equal(placeInWords('strategy: variables."Cheap", characters 3–5'), "Variable “Cheap”, characters 3–5");
  assert.equal(placeInWords('strategy: variables."Cheap".display'), "Variable “Cheap”, display");
  assert.equal(placeInWords('strategy: variables."Cafe\\u{301} \\"x\\" a\\\\b"'), 'Variable “Cafe\\u{301} "x" a\\b”');
  assert.equal(placeInWords("name"), "Name");
  assert.equal(placeInWords("strategy: sleeves"), "Sleeves");
  assert.equal(placeInWords("every"), "Rebalance interval");
  assert.equal(placeInWords("strategy: us, trial 1, 2022-07-01, x"), "strategy: us, trial 1, 2022-07-01, x");
});
