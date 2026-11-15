import type { StatusReply } from "../src/api/StatusReply.ts";
import { expect, test } from "./fixture.ts";

/** The seconds in the status bar's "Running for 1 min 5 sec", or -1 for any
 *  other text. (A function that `expect.poll` calls must not throw: the poll
 *  would end with that error instead of reading again.) */
const seconds = (text: string | null) => {
  const parts = /^Running for (?:(\d+) hr )?(?:(\d+) min )?(\d+) sec$/.exec(text ?? "");
  if (!parts) return -1;
  return Number(parts[1] ?? 0) * 3600 + Number(parts[2] ?? 0) * 60 + Number(parts[3]);
};

test.beforeAll(({ home }) => home.reset());

test("the status bar shows a long run waiting, then running, then idle after Stop", async ({ page, home }) => {
  const state = page.locator("#workspace-run-state");
  const detail = page.locator("#workspace-run-detail");
  const waiting = page.locator("#workspace-waiting");
  await home.api("PUT", "/api/queue", { paused: true });
  const run = await home.addLongRun("Long run");
  await page.goto("/");

  await expect(waiting).toHaveText("Queue paused · 1 waiting");
  await expect(state).toHaveText("Idle");
  await expect(state).toHaveAttribute("data-state", "attention");
  await expect(page.locator("#workspace-queue-count")).toHaveText("1");

  await home.api("PUT", "/api/queue", { paused: false });
  await home.whileRunning(run.id, async () => {
    await expect(state).toHaveText("Running · Long run");
    await expect(state).toHaveAttribute("data-state", "running");
    await expect(waiting).toHaveText("0 waiting");
    // The time since start is read again until it is a time, and then until it has grown.
    let first = -1;
    await expect.poll(async () => (first = seconds(await detail.textContent()))).toBeGreaterThanOrEqual(0);
    await expect.poll(async () => seconds(await detail.textContent())).toBeGreaterThan(first);
  });

  await home.api("POST", `/api/runs/${run.id}/stop`);
  await expect(state).toHaveText("Idle");
  await expect(state).toHaveAttribute("data-state", "idle");
  await expect(detail).toHaveText("No active backtest.");
  await expect(page.locator("#workspace-queue-count")).toHaveText("0");
});

test("the data page lists each market with its prepared data", async ({ page, home }) => {
  const status = await home.api<StatusReply>("GET", "/api/data/status");
  await page.goto("/data.html");
  for (const market of status.markets) {
    const section = page.locator(`[data-market=${market.market}]`);
    await expect(section.locator(".data-status strong").first()).toHaveText("Ready for backtests");
    await expect(section).toContainText(market.prepared!.last_session!);
    await expect(section).toContainText(`Generation ${market.prepared!.generation} · ${market.prepared!.companies} companies`);
  }
  await expect(page.locator("h3")).toHaveText(["US", "Hong Kong", "Japan · Tokyo"]);
});
