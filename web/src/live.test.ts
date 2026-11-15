import assert from "node:assert/strict";
import { test } from "node:test";
import type { RunsReply } from "./api/RunsReply.ts";
import type { State } from "./api/State.ts";
import { ApiFailure, client } from "./client.ts";
import { act, type Shared, watchRuns } from "./live.ts";

/** A fake server: each request waits until the test answers it. */
type Pending = { method: string; path: string; answer: (status: number, body: unknown) => void; fail: () => void };
const pending: Pending[] = [];
globalThis.fetch = (input, init) =>
  new Promise((resolve, reject) =>
    pending.push({
      method: init?.method ?? "GET",
      path: String(input),
      answer: (status, body) => resolve(new Response(JSON.stringify(body), { status })),
      fail: () => reject(new TypeError("fetch failed")),
    }),
  );

/** The next request, once the page has sent it. */
async function next(): Promise<Pending> {
  for (let i = 0; i < 100 && !pending.length; i++) await new Promise((resolve) => setTimeout(resolve, 1));
  const request = pending.shift();
  assert.ok(request, "a request was sent");
  return request;
}

const list = (state: State): RunsReply => ({
  paused: false,
  runs: [{ id: 1, name: "Long run", market: "us", schedule: { start: "2016-01-04", end: "2023-06-28", every: "1w" }, state, locked: false, created: "2026-11-15T06:00:00Z" }],
});
const settle = () => new Promise((resolve) => setTimeout(resolve, 5));

test("a list asked for before a change is dropped, so a row never steps back", async () => {
  const seen: Shared<RunsReply>[] = [];
  const stop = watchRuns((state) => seen.push(state));
  const before = await next();
  assert.equal(before.path, "/api/runs");

  const change = act(() => client.stop(1));
  const post = await next();
  assert.deepEqual([post.method, post.path], ["POST", "/api/runs/1/stop"]);
  post.answer(200, list("stopped").runs[0]);
  await change;
  const after = await next();
  assert.equal(after.path, "/api/runs");
  before.answer(200, list("running"));
  await settle();
  after.answer(200, list("stopped"));
  await settle();

  assert.deepEqual(seen.map((state) => state.value?.runs[0]?.state ?? null), [null, "stopped"]);
  stop();
});

test("a refused change throws its failure to the caller, and the list is read again", async () => {
  const stop = watchRuns(() => {});
  (await next()).answer(200, list("running"));
  const change = act(() => client.deleteRun(1));
  (await next()).answer(409, { error: { message: "run 1 is locked", place: "id" } });
  await assert.rejects(change, (failure: unknown) => failure instanceof ApiFailure && failure.status === 409 && failure.place === "id");
  assert.equal((await next()).path, "/api/runs");
  stop();
});

test("a list that gets no answer keeps the last list and says the server does not answer", async () => {
  let last: Shared<RunsReply> | undefined;
  const stop = watchRuns((state) => (last = state));
  (await next()).answer(200, list("waiting"));
  await settle();
  await act(() => Promise.resolve());
  (await next()).fail();
  await settle();
  assert.equal(last?.value?.runs[0]?.state, "waiting");
  assert.equal(last?.failure?.status, 0);
  assert.equal(last?.failure?.message, "The server does not answer.");
  stop();
});
