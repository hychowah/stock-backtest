import type { Page } from "@playwright/test";
import { existsSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { UpdateProgress } from "../src/api/UpdateProgress.ts";
import type { UpdateStatus } from "../src/api/UpdateStatus.ts";
import { formatTime } from "../src/format.ts";
import { expect, type Home, test } from "./fixture.ts";

/** Writes the update's record into the home before the page opens. No update
 *  holds the lock, so a record that says running reads as interrupted. */
function seed(home: Home, progress: Partial<UpdateProgress>, last_success: string | null = null) {
  const full: UpdateProgress = {
    state: "complete",
    pid: 4242,
    stage: "preparing",
    market: null,
    done: 0,
    total: 0,
    failed: 0,
    failures: [],
    started: "2026-11-15T06:00:00Z",
    finished: "2026-11-15T06:40:00Z",
    end: "2026-11-13",
    reports: "due",
    error: null,
    ...progress,
  };
  writeFileSync(join(home.dir, "data/update.json"), JSON.stringify({ memory: { last_success }, progress: full }));
}

const panel = (page: Page) => page.locator("#data-update-panel");
const steps = (page: Page) => page.locator("#data-steps li");

/** No record and no stop request, before and after each check. */
const clear = ({ home }: { home: Home }) => {
  for (const file of ["update.json", "update.stop", "update.done"]) rmSync(join(home.dir, "data", file), { force: true });
};

const state = async (home: Home) => (await home.api<{ update: UpdateStatus }>("GET", "/api/data/status")).update.state;
const idle = async (home: Home) => !["running", "stopping"].includes(await state(home));

/** Leaves no update running and no lock held, also after a failed check:
 *  the provider closes what it holds and every connection from now on, an
 *  update that still runs is stopped, and the check waits until it ends. */
async function settle(home: Home) {
  home.provider.mode = "close";
  home.provider.release();
  if (!(await idle(home))) await home.api("POST", "/api/data/stop").catch(() => {});
  await expect.poll(() => idle(home), { timeout: 60_000, message: "the update ends" }).toBe(true);
}

test.beforeEach(clear);
test.afterEach(async ({ home }) => {
  await settle(home);
  clear({ home });
});

test("with no update recorded, Update data is offered and nothing is in progress", async ({ page }) => {
  await page.goto("/data.html");
  await expect(panel(page)).toContainText("No update recorded");
  await expect(panel(page)).toContainText("None yet");
  await expect(page.getByRole("button", { name: "Update data" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Stop update" })).toHaveCount(0);
  await expect(steps(page)).toHaveCount(0);
  await expect(page.locator("[data-market]")).toHaveCount(3);
});

test("a complete update shows every step done and the time of the last complete update", async ({ page, home }) => {
  const last = "2026-11-15T06:40:00Z";
  seed(home, { state: "complete", reports: "not_due", stage: "preparing", done: 3, total: 3 }, last);
  await page.goto("/data.html");
  await expect(panel(page)).toContainText("Data updated");
  await expect(panel(page)).toContainText(formatTime(last));
  await expect(steps(page)).toHaveText(["✓ Companies", "Reports: next check Saturday", "✓ Prices", "✓ Preparing", "✓ Ready"]);
  await expect(page.locator("#data-steps [aria-current]")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Update data" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Stop update" })).toHaveCount(0);
});

test("a partial update lists the failed items with their files, and says when the list is cut", async ({ page, home }) => {
  const failures = Array.from({ length: 20 }, (_, i) => ({ message: "the provider gave up after 3 tries", place: `raw/px/US/S${i}.json` }));
  seed(home, { state: "partial", stage: "preparing", failed: 35, failures }, "2026-11-14T06:40:00Z");
  await page.goto("/data.html");
  await expect(panel(page)).toContainText("Updated, with failed items");
  await expect(panel(page)).toContainText("35 failed");
  await expect(page.locator("#data-failures li")).toHaveCount(20);
  await expect(page.locator("#data-failures li").first()).toHaveText("the provider gave up after 3 tries (raw/px/US/S0.json)");
  await expect(panel(page)).toContainText("The first 20 failed items are listed.");
  await expect(page.getByRole("button", { name: "Update data" })).toBeEnabled();
});

test("a failed update shows its message and offers Continue update", async ({ page, home }) => {
  seed(home, {
    state: "failed",
    stage: "prices",
    market: "us",
    done: 120,
    total: 700,
    finished: "2026-11-15T06:10:00Z",
    error: { message: "the provider refused the key", place: "provider" },
  });
  await page.goto("/data.html");
  await expect(panel(page)).toContainText("Update failed");
  await expect(panel(page)).toContainText("Prices, US: 120 of 700");
  await expect(page.locator(".data-error")).toHaveText("the provider refused the key (provider)");
  await expect(steps(page)).toHaveText(["✓ Companies", "✓ Reports", "Prices", "Preparing", "Ready"]);
  await expect(page.getByRole("button", { name: "Continue update" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Stop update" })).toHaveCount(0);
});

const elapsed = (page: Page) => panel(page).locator(".data-status div", { hasText: "Elapsed" }).locator("strong");

test("Update data starts an update, which shows running and ticking; Stop update says Stopping safely at once, the update stops and Continue update runs it again", async ({ page, home }) => {
  // The provider holds every connection and never answers, so the update stays in its first step.
  home.provider.mode = "hold";
  await page.goto("/data.html");
  await page.getByRole("button", { name: "Update data" }).click();
  await expect(panel(page)).toContainText("Updating your data");
  await expect(page.locator('#data-steps [aria-current="step"]')).toHaveText("Companies");
  await expect(page.getByRole("button", { name: "Update data" })).toBeDisabled();
  await expect(elapsed(page)).toHaveText(/^(\d+ hr )?(\d+ min )?\d+ sec$/);
  const first = await elapsed(page).textContent();
  await expect.poll(() => elapsed(page).textContent()).not.toBe(first);

  // The stop shows at once; the update itself ends when its requests in flight end, which the page learns by its next reads.
  await page.getByRole("button", { name: "Stop update" }).click();
  await expect(page.getByRole("button", { name: "Stopping safely" })).toBeDisabled();
  await expect(panel(page)).toContainText("Stopping safely");
  home.provider.mode = "close";
  home.provider.release();
  await expect(panel(page)).toContainText("Update stopped");
  await expect(page.getByRole("button", { name: "Continue update" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Stop update" })).toHaveCount(0);

  // Continue update starts the same update again.
  home.provider.mode = "hold";
  await page.getByRole("button", { name: "Continue update" }).click();
  await expect(panel(page)).toContainText("Updating your data");
  await expect(page.locator('#data-steps [aria-current="step"]')).toHaveText("Companies");
  await page.getByRole("button", { name: "Stop update" }).click();
  await expect(page.getByRole("button", { name: "Stopping safely" })).toBeDisabled();
  home.provider.mode = "close";
  home.provider.release();
  await expect(panel(page)).toContainText("Update stopped");
  expect(await state(home)).toBe("stopped");
});

test("a provider that never replies fails the update after its tries, with the message and Continue update", async ({ page, home }) => {
  // Every connection is closed without a reply: the client tries three times, then the company list fails.
  home.provider.mode = "close";
  try {
    await page.goto("/data.html");
    await page.getByRole("button", { name: "Update data" }).click();
    await expect(panel(page)).toContainText("Update failed");
    // The words of a company list that got no reply: the update reached the local provider.
    await expect(page.locator(".data-error")).toHaveText(/^company-screener \w+ listed page 0: the provider did not reply \(/);
    await expect(page.locator(".data-error")).not.toContainText("http");
    await expect(page.getByRole("button", { name: "Continue update" })).toBeEnabled();
    await expect(page.getByRole("button", { name: "Stop update" })).toHaveCount(0);
  } finally {
    // The failed update still prepares the saved data, at the time now.
    await settle(home);
    home.prepare();
  }
});
