import assert from "node:assert/strict";
import { test } from "node:test";
import type { UpdateProgress } from "../api/UpdateProgress.ts";
import { counts, startButton, statusInterval, steps, stopButton } from "./update.ts";

const progress = (over: Partial<UpdateProgress>): UpdateProgress => ({
  state: "running",
  pid: 1,
  stage: "prices",
  market: "us",
  done: 0,
  total: 0,
  failed: 0,
  failures: [],
  started: "2026-11-15T06:00:00Z",
  finished: null,
  end: "2026-11-13",
  reports: "due",
  error: null,
  ...over,
});
const marks = (p: UpdateProgress) => steps(p).map((step) => `${step.mark}:${step.label}`);

test("the page reads the status every second while an update runs or stops, otherwise every 5 s", () => {
  assert.equal(statusInterval("running"), 1000);
  assert.equal(statusInterval("stopping"), 1000);
  for (const state of ["idle", "stopped", "interrupted", "failed", "partial", "complete"] as const) assert.equal(statusInterval(state), 5000);
  assert.equal(statusInterval(undefined), 5000);
});

test("the start button says Continue update after an unfinished update, and waits while one is active", () => {
  assert.deepEqual(startButton("idle"), { label: "Update data", enabled: true });
  assert.deepEqual(startButton("complete"), { label: "Update data", enabled: true });
  assert.deepEqual(startButton("partial"), { label: "Update data", enabled: true });
  for (const state of ["stopped", "interrupted", "failed"] as const) assert.deepEqual(startButton(state), { label: "Continue update", enabled: true });
  assert.equal(startButton("running").enabled, false);
  assert.equal(startButton("stopping").enabled, false);
});

test("the stop button shows only while an update is active, and says Stopping safely after a stop", () => {
  assert.deepEqual(stopButton("running"), { label: "Stop update", enabled: true });
  assert.deepEqual(stopButton("stopping"), { label: "Stopping safely", enabled: false });
  assert.equal(stopButton("idle"), null);
  assert.equal(stopButton("failed"), null);
});

test("the steps before the running stage are done and the running one is current", () => {
  assert.deepEqual(marks(progress({ stage: "prices" })), ["done:Companies", "done:Reports", "current:Prices", "todo:Preparing", "todo:Ready"]);
  assert.deepEqual(marks(progress({ stage: "companies", state: "stopping" })), ["current:Companies", "todo:Reports", "todo:Prices", "todo:Preparing", "todo:Ready"]);
  assert.deepEqual(marks(progress({ stage: null })), ["todo:Companies", "todo:Reports", "todo:Prices", "todo:Preparing", "todo:Ready"]);
});

test("when reports are not due the step says when they are next checked", () => {
  assert.deepEqual(marks(progress({ reports: "not_due", stage: "prices" })), ["done:Companies", "skipped:Reports: next check Saturday", "current:Prices", "todo:Preparing", "todo:Ready"]);
});

test("a finished update has every step done; an unfinished one has none current", () => {
  for (const state of ["complete", "partial"] as const) {
    assert.ok(steps(progress({ state, stage: "preparing" })).every((step) => step.mark === "done"));
  }
  for (const state of ["stopped", "interrupted", "failed"] as const) {
    assert.deepEqual(marks(progress({ state, stage: "prices" })), ["done:Companies", "done:Reports", "todo:Prices", "todo:Preparing", "todo:Ready"]);
  }
});

test("the counts name the stage and market, and the failed items", () => {
  assert.equal(counts(progress({ stage: "prices", market: "hk", done: 1200, total: 3031 })), "Prices, Hong Kong: 1,200 of 3,031");
  assert.equal(counts(progress({ stage: "companies", market: null, done: 1, total: 2, failed: 3 })), "Companies: 1 of 2 · 3 failed");
  assert.equal(counts(progress({ stage: "preparing", total: 0, failed: 1 })), "1 failed");
  assert.equal(counts(progress({ stage: null })), "");
});
