import assert from "node:assert/strict";
import { test } from "node:test";
import { bandPath, dayTicks, dayTime, dollarTicks, evenTicks, histogram, linearScale, linePath, logAxis, nearest, normalCount } from "./chart.ts";

test("a linear scale puts its ends at the given places, and a flat range at the start", () => {
  const at = linearScale(-0.1, 0.3, 290, 30);
  assert.equal(at(-0.1), 290);
  assert.equal(at(0.3), 30);
  assert.ok(Math.abs(at(0.1) - 160) < 1e-9);
  assert.equal(linearScale(5, 5, 10, 20)(5), 10);
});

test("a log scale gives equal heights to equal percentage moves, with a margin, and floors a total loss", () => {
  const { at, low, high } = logAxis([1, 2, 4], 312, 48);
  assert.ok(Math.abs(at(1) - at(2) - (at(2) - at(4))) < 1e-9);
  assert.ok(at(1) < 312 && at(4) > 48, "the margin keeps the ends inside");
  assert.ok(low < 1 && high > 4);
  assert.ok(Math.abs(at(low) - 312) < 1e-9 && Math.abs(at(high) - 48) < 1e-9);
  assert.equal(at(0), at(-5), "a value at or below zero sits on the floor");
  assert.ok(Number.isFinite(at(0)));
});

test("even ticks include both ends", () => {
  assert.deepEqual(evenTicks(0, 1, 4), [0, 0.25, 0.5, 0.75, 1]);
});

test("dollar ticks use 1-2-5 steps over a wide range and even steps over a narrow one", () => {
  assert.deepEqual(dollarTicks(0.9, 12), [1, 2, 5, 10]);
  assert.deepEqual(dollarTicks(0.4, 120), [0.5, 1, 2, 5, 10, 20, 50, 100]);
  assert.deepEqual(dollarTicks(1.01, 1.19), [1.05, 1.1, 1.15]);
  for (const value of dollarTicks(1.2, 1.9)) assert.ok(value >= 1.2 && value <= 1.9);
});

test("date ticks label years over a long window and months over a short one", () => {
  const years = dayTicks(dayTime("2016-01-04"), dayTime("2023-06-28"));
  assert.deepEqual(years.map((tick) => tick.label), ["2017", "2018", "2019", "2020", "2021", "2022", "2023"]);
  assert.equal(years[0]!.time, Date.UTC(2017, 0, 1));
  const months = dayTicks(dayTime("2021-07-01"), dayTime("2021-10-28"));
  assert.deepEqual(months.map((tick) => tick.label), ["2021-08", "2021-09", "2021-10"]);
  assert.deepEqual(dayTicks(dayTime("2021-07-01"), dayTime("2021-07-20")), []);
});

test("the nearest time is found at, between and beyond the ends", () => {
  const times = [10, 20, 40];
  assert.equal(nearest(times, 20), 1);
  assert.equal(nearest(times, 24), 1);
  assert.equal(nearest(times, 31), 2);
  assert.equal(nearest(times, 5), 0);
  assert.equal(nearest(times, 99), 2);
  assert.equal(nearest([7], 3), 0);
});

test("paths are written with one decimal, and a band runs along the top then back along the bottom", () => {
  assert.equal(linePath([[1, 2], [3.14159, 4]]), "M1.0,2.0L3.1,4.0");
  assert.equal(bandPath([[0, 1], [10, 2]], [[0, 5], [10, 6]]), "M0.0,1.0L10.0,2.0L10.0,6.0L0.0,5.0Z");
});

test("a histogram counts every value once on shared edges", () => {
  const values = Array.from({ length: 100 }, (_, i) => i / 100);
  const other = values.map((value) => value + 0.5);
  const bins = histogram([
    { values, mean: 0.495, stddev: 0.29 },
    { values: other, mean: 0.995, stddev: 0.29 },
  ])!;
  assert.equal(bins.counts.length, 2);
  for (const row of bins.counts) {
    assert.equal(row.length, 30);
    assert.equal(row.reduce((a, b) => a + b, 0), 100);
  }
  assert.ok(bins.low < 0 && bins.high > 1.49, "the range covers the values and mean ± 3 deviations");
  assert.ok(Math.abs(bins.width * 30 - (bins.high - bins.low)) < 1e-9);
});

test("equal values fall into one bin, and no values give no histogram", () => {
  const bins = histogram([{ values: [0.2, 0.2, 0.2], mean: 0.2, stddev: 0 }])!;
  assert.deepEqual(bins.counts, [[3]]);
  assert.equal(histogram([{ values: [], mean: null, stddev: null }]), null);
});

test("a normal curve peaks at its mean with the height of a histogram of that many values, and is flat without a spread", () => {
  const peak = normalCount(1, 1, 2, 100, 0.5);
  assert.ok(Math.abs(peak - (100 * 0.5) / (2 * Math.sqrt(2 * Math.PI))) < 1e-9);
  assert.ok(normalCount(3, 1, 2, 100, 0.5) < peak);
  assert.equal(normalCount(1, 1, 0, 100, 0.5), 0);
});
