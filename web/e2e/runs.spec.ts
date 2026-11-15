import { readFileSync } from "node:fs";
import type { Locator, Page } from "@playwright/test";
import type { AddRun } from "../src/api/AddRun.ts";
import type { Market } from "../src/api/Market.ts";
import type { RunRow } from "../src/api/RunRow.ts";
import type { RunsReply } from "../src/api/RunsReply.ts";
import type { TrialsReply } from "../src/api/TrialsReply.ts";
import { percent } from "../src/format.ts";
import { expect, type Home, test } from "./fixture.ts";

const cases = new URL("../../fixtures/fictional/cases/", import.meta.url).pathname;

/** Adds a fictional case (a folder of `run.json` and `strategy.json`) as a run. */
function addCase(home: Home, folder: string, name: string): Promise<RunRow> {
  const read = (file: string) => JSON.parse(readFileSync(cases + folder + "/" + file, "utf8")) as Record<string, unknown>;
  const { market, start, end, interval, dates, trials, seed } = read("run.json");
  const body = { name, market: market as Market, schedule: { start, end, every: interval, dates, trials, seed }, strategy: read("strategy.json") };
  return home.api<RunRow>("POST", "/api/runs", body as AddRun);
}

const list = (home: Home) => home.api<RunsReply>("GET", "/api/runs");

const named = (name: string) => new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`);
const queueRow = (page: Page, name: string) => page.locator("#queue-list > li").filter({ has: page.locator(".run-name", { hasText: named(name) }) });
const savedRow = (page: Page, name: string) => page.locator("#saved-list > li").filter({ has: page.locator(".run-name", { hasText: named(name) }) });
const savedRowOf = (page: Page, id: number) => page.locator("#saved-list > li").filter({ has: page.locator(`#saved-tick-${id}`) });
const details = async (row: Locator) => {
  await row.locator("summary").click();
  return row;
};

test.beforeEach(({ home }) => home.reset());

test("with no run, both lists say so, and the queue pauses and resumes", async ({ page, home }) => {
  await page.goto("/#/runs");
  await expect(page.locator("#queue-list")).toHaveText("No test is waiting or running. Select Add to queue in Build strategy.");
  await expect(page.locator("#saved-list")).toHaveText("No saved backtests yet.");
  await expect(page.locator("#queue-status")).toHaveText("Queue ready. Tests and results are saved on the server.");
  await expect(page.locator("#queue-pause")).toHaveText("Pause queue");
  await page.locator("#queue-pause").click();
  await expect(page.locator("#queue-pause")).toHaveText("Resume queue");
  await expect(page.locator("#queue-status")).toHaveText("Queue paused. The active test can finish.");
  expect((await list(home)).paused).toBe(true);
  await page.locator("#queue-pause").click();
  await expect(page.locator("#queue-pause")).toHaveText("Pause queue");
  await expect(page.locator("#queue-status")).toHaveText("Queue resumed.");
  expect((await list(home)).paused).toBe(false);
});

test("the queue's controls: move, hold and release, delete, resume", async ({ page, home }) => {
  await home.api("PUT", "/api/queue", { paused: true });
  const [a, b, c] = [await addCase(home, "builtins/us-built-ins-months", "First"), await addCase(home, "builtins/us-built-ins-months", "Second"), await addCase(home, "builtins/us-built-ins-months", "Third")];
  await page.goto("/#/runs");
  await expect(page.locator("#queue-pause")).toHaveText("Resume queue");
  const order = async () => (await list(home)).runs.map((run) => run.name);
  await expect(page.locator("#queue-list > li .run-name")).toHaveText(["First", "Second", "Third"]);
  await expect(queueRow(page, "First").locator(".queue-state")).toHaveText("Waiting");
  await expect(page.locator("#queue-count")).toHaveText("3");

  // The first run cannot move up, the last cannot move down.
  await details(queueRow(page, "First"));
  await expect(queueRow(page, "First").getByRole("button", { name: "Move up" })).toBeDisabled();
  await details(queueRow(page, "Third"));
  await expect(queueRow(page, "Third").getByRole("button", { name: "Move down" })).toBeDisabled();

  await queueRow(page, "Third").getByRole("button", { name: "Move up" }).click();
  await expect(page.locator("#queue-list > li .run-name")).toHaveText(["First", "Third", "Second"]);
  expect(await order()).toEqual(["First", "Third", "Second"]);
  await queueRow(page, "First").getByRole("button", { name: "Move down" }).click();
  await expect(page.locator("#queue-list > li .run-name")).toHaveText(["Third", "First", "Second"]);

  // A held run says so, and Release hold puts it back to waiting in its place.
  await home.api("POST", `/api/runs/${b.id}/hold`);
  await expect(queueRow(page, "Second").locator(".queue-state")).toHaveText("Held");
  await expect(queueRow(page, "Second")).toHaveAttribute("data-state", "held");
  await details(queueRow(page, "Second"));
  await queueRow(page, "Second").getByRole("button", { name: "Release hold" }).click();
  await expect(queueRow(page, "Second").locator(".queue-state")).toHaveText("Waiting");
  expect(await order()).toEqual(["Third", "First", "Second"]);

  // Open result goes to the page of a waiting run, and Back returns to the same rows.
  await queueRow(page, "First").getByRole("button", { name: "Open result" }).click();
  await expect(page).toHaveURL(new RegExp(`#/results/${a.id}$`));
  await page.goBack();
  await expect(page.locator("#queue-list > li")).toHaveCount(3);

  // Delete asks first; Keep leaves the run. The row's Details stays open while its state changes.
  await queueRow(page, "Second").getByRole("button", { name: "Delete", exact: true }).click();
  await expect(queueRow(page, "Second")).toContainText("Delete this test and its result?");
  await queueRow(page, "Second").getByRole("button", { name: "Keep" }).click();
  await expect(queueRow(page, "Second")).toBeVisible();
  await queueRow(page, "Second").getByRole("button", { name: "Delete", exact: true }).click();
  await queueRow(page, "Second").getByRole("button", { name: "Delete test" }).click();
  await expect(queueRow(page, "Second")).toHaveCount(0);
  await expect(page.locator("#queue-status")).toHaveText("Selected test deleted.");
  await expect(page.locator("#queue-count")).toHaveText("2");

  // Resume: the runs complete and move to the saved table, in the order the queue gave.
  await page.locator("#queue-pause").click();
  await expect(page.locator("#queue-pause")).toHaveText("Pause queue");
  await expect(page.locator("#queue-status")).toHaveText("Queue resumed.");
  await expect(page.locator("#queue-list")).toHaveText("No test is waiting or running. Select Add to queue in Build strategy.");
  await expect(page.locator("#saved-list > li")).toHaveCount(2);
  const done = (await list(home)).runs.filter((run) => run.state === "complete");
  expect(done.map((run) => run.id).sort()).toEqual([a.id, c.id].sort());
});

test("the queue panel in the tray has the same rows as in Runs & saved", async ({ page, home }) => {
  await home.api("PUT", "/api/queue", { paused: true });
  await addCase(home, "builtins/us-built-ins-months", "Tray row");
  await page.goto("/#/build");
  await page.locator("#workspace-queue-open").click();
  await expect(page.locator("#workspace-queue-tray #queue-list > li")).toHaveCount(1);
  await expect(page.locator("#queue-panel")).toHaveCount(1);
  await page.locator("#workspace-queue-close").click();
  await page.goto("/#/runs");
  await expect(page.locator("#workspace-runs #queue-list > li")).toHaveCount(1);
  await expect(page.locator("#queue-panel")).toHaveCount(1);
});

test("a long run shows its time since start growing, and Stop test stops it", async ({ page, home }) => {
  await home.api("PUT", "/api/queue", { paused: true });
  const run = await home.addLongRun("Long one");
  await page.goto("/#/runs");
  await expect(queueRow(page, "Long one").locator(".queue-state")).toHaveText("Waiting");
  await page.locator("#queue-pause").click();
  // The seconds in "Running for 1 min 5 sec", or -1 for other text (a function that expect.poll calls must not throw).
  const seconds = async () => {
    const parts = /^Running for (?:(\d+) min )?(\d+) sec$/.exec((await queueRow(page, "Long one").locator(".queue-progress").textContent()) ?? "");
    return parts ? Number(parts[1] ?? 0) * 60 + Number(parts[2]) : -1;
  };
  await home.whileRunning(run.id, async () => {
    await expect(queueRow(page, "Long one").locator(".queue-state")).toHaveText("Running");
    await expect(queueRow(page, "Long one")).toHaveAttribute("data-state", "running");
    let first = -1;
    await expect.poll(async () => (first = await seconds())).toBeGreaterThanOrEqual(0);
    await expect.poll(seconds).toBeGreaterThan(first);
    await details(queueRow(page, "Long one"));
    await expect(queueRow(page, "Long one").getByRole("button", { name: "Delete", exact: true })).toHaveCount(0);
    await queueRow(page, "Long one").getByRole("button", { name: "Stop test" }).click();
  });
  await expect(queueRow(page, "Long one").locator(".queue-state")).toHaveText("Stopped");
  await expect(queueRow(page, "Long one").locator(".queue-progress")).toHaveText("");
  expect((await home.api<RunRow>("GET", `/api/runs/${run.id}`)).state).toBe("stopped");
  await queueRow(page, "Long one").getByRole("button", { name: "Delete", exact: true }).click();
  await queueRow(page, "Long one").getByRole("button", { name: "Delete test" }).click();
  await expect(queueRow(page, "Long one")).toHaveCount(0);
});

test("the saved table: the numbers of the server, sorting, Details, rename, lock, and Delete ticked leaves a locked run", async ({ page, home }) => {
  const fixed = await addCase(home, "builtins/us-built-ins-months", "Ranks 1–10 fixed");
  const random = await addCase(home, "formulas/us-random", "Ranks 1–6 random");
  const third = await addCase(home, "builtins/us-built-ins-weeks", "Weekly");
  await home.idle();
  await page.goto("/#/runs");
  await expect(page.locator("#saved-list > li")).toHaveCount(3);

  // A row's CAGR is the median the server stored; the type and window come from the schedule.
  for (const run of [fixed, random, third]) {
    const stored = await home.api<RunRow>("GET", `/api/runs/${run.id}`);
    const row = savedRow(page, run.name);
    await expect(row.locator(".run-cagr")).toHaveText(percent(stored.outcome!.headline.median));
    await expect(row.locator(".run-window")).toHaveText(`${stored.schedule.start} → ${stored.schedule.end}`);
  }
  await expect(savedRow(page, "Ranks 1–6 random").locator(".run-type")).toHaveText("Random · 3 trials");
  await expect(savedRow(page, "Ranks 1–10 fixed").locator(".run-type")).toHaveText("Fixed dates");

  // Sorting: the table starts with Saved, newest first; a heading sorts by name, with numbers in number order.
  await expect(page.locator("#saved-sort-saved")).toHaveText("Saved ↓");
  await page.locator("#saved-sort-name").click();
  await expect(page.locator("#saved-sort-name")).toHaveText("Name ↑");
  await expect(page.locator("#saved-sort-name")).toHaveAttribute("aria-current", "true");
  await expect(page.locator("#saved-sort-saved")).toHaveText("Saved");
  await expect(page.locator("#saved-sort-saved")).not.toHaveAttribute("aria-current", "true");
  await expect(page.locator("#saved-list .run-name")).toHaveText(["Ranks 1–6 random", "Ranks 1–10 fixed", "Weekly"]);
  await page.locator("#saved-sort-name").click();
  await expect(page.locator("#saved-list .run-name")).toHaveText(["Weekly", "Ranks 1–10 fixed", "Ranks 1–6 random"]);
  await page.locator("#saved-sort-cagr").click();
  await expect(page.locator("#saved-sort-cagr")).toHaveText("CAGR ↓");
  const byCagr = await Promise.all([fixed, random, third].map(async (run) => ({ name: run.name, median: (await home.api<RunRow>("GET", `/api/runs/${run.id}`)).outcome!.headline.median })));
  await expect(page.locator("#saved-list .run-name")).toHaveText(byCagr.sort((a, b) => b.median - a.median).map((run) => run.name));

  // Details: the settings lines and the headline of the stored trials.
  const row = await details(savedRowOf(page, random.id));
  await expect(row).toContainText("Test type: Random dates");
  await expect(row).toContainText("Trials: 3");
  await expect(row).toContainText("Step 1 · Filter");
  const trials = await home.api<TrialsReply>("GET", `/api/runs/${random.id}/trials`);
  const median = trials.statistics.find((stat) => stat.statistic === "cagr.median")!.value;
  await expect(row.locator(".headline")).toContainText("Median strategy CAGR" + percent(median));
  await expect(row).toContainText(`Saved ID: ${random.id}`);

  // Rename: Escape leaves the name, Enter saves it.
  await row.getByRole("button", { name: "Rename", exact: true }).click();
  await row.getByLabel("New name").fill("Discard this");
  await row.getByLabel("New name").press("Escape");
  await expect(row.getByLabel("New name")).toHaveCount(0);
  await row.getByRole("button", { name: "Rename", exact: true }).click();
  await row.getByLabel("New name").fill("Random, renamed");
  await row.getByLabel("New name").press("Enter");
  await expect(page.locator("#saved-status")).toContainText("Renamed to “Random, renamed”.");
  await expect(savedRow(page, "Random, renamed")).toHaveCount(1);
  expect((await home.api<RunRow>("GET", `/api/runs/${random.id}`)).name).toBe("Random, renamed");
  await row.getByRole("button", { name: "Rename", exact: true }).click();
  await row.getByLabel("New name").fill("   ");
  await row.getByRole("button", { name: "Save name" }).click();
  await expect(page.locator("#saved-status")).toHaveText("Use a backtest name with 1–120 characters.");
  await row.getByRole("button", { name: "Cancel" }).click();

  // Lock ticked: the row says Locked and offers no Delete.
  await page.locator(`#saved-tick-${fixed.id}`).check();
  await expect(page.locator("#saved-bar")).toContainText("1 test ticked.");
  await expect(page.locator("#saved-bar")).toContainText("Tick another to compare.");
  await expect(page.locator("#saved-compare")).toBeDisabled();
  await page.locator("#saved-lock-ticked").click();
  await expect(page.locator("#saved-status")).toHaveText("Saved backtest locked.");
  await expect(savedRow(page, "Ranks 1–10 fixed").locator(".queue-state")).toHaveText("Locked");
  expect((await home.api<RunRow>("GET", `/api/runs/${fixed.id}`)).locked).toBe(true);
  await details(savedRow(page, "Ranks 1–10 fixed"));
  await expect(savedRow(page, "Ranks 1–10 fixed").getByRole("button", { name: "Delete", exact: true })).toHaveCount(0);
  await expect(page.locator("#saved-delete-ticked")).toBeDisabled();
  await expect(page.locator("#saved-lock-ticked")).toHaveText("Unlock ticked");

  // The box in the heading ticks every row; Delete ticked asks once, deletes the unlocked rows, and leaves the locked one.
  await page.locator("#saved-tick-all").check();
  await expect(page.locator("#saved-bar")).toContainText("3 tests ticked");
  await page.locator("#saved-delete-ticked").click();
  await expect(page.locator("#saved-bar")).toContainText("Delete 2 saved backtests? Locked tests stay.");
  await page.locator("#saved-keep-ticked").click();
  await expect(page.locator("#saved-list > li")).toHaveCount(3);
  await page.locator("#saved-delete-ticked").click();
  await page.locator("#saved-confirm-ticked").click();
  await expect(page.locator("#saved-list > li")).toHaveCount(1);
  await expect(page.locator("#saved-status")).toHaveText("2 saved backtests deleted.");
  expect((await list(home)).runs.map((run) => run.id)).toEqual([fixed.id]);

  // Unlock ticked, then a single row's Delete asks, and deletes.
  await page.locator(`#saved-tick-${fixed.id}`).check();
  await page.locator("#saved-lock-ticked").click();
  await expect(page.locator("#saved-status")).toHaveText("Saved backtest unlocked.");
  const last = savedRow(page, "Ranks 1–10 fixed"); // Its Details is still open.
  await last.getByRole("button", { name: "Delete", exact: true }).click();
  await last.getByRole("button", { name: "Delete record" }).click();
  await expect(page.locator("#saved-list")).toHaveText("No saved backtests yet.");
});

test("the market switch counts the runs and shows one market's rows; another market clears the ticks", async ({ page, home }) => {
  await addCase(home, "builtins/us-built-ins-months", "US one");
  await addCase(home, "builtins/hk-sleeves", "HK one");
  await addCase(home, "builtins/hk-fields-dates", "HK two");
  await home.idle();
  await page.goto("/#/runs");
  const button = (market: string) => page.locator(`#run-markets button[data-market="${market}"]`);
  await expect(page.locator("#run-markets button")).toHaveText(["All 3", "US 1", "Hong Kong 2", "Tokyo 0"]);
  await expect(button("")).toHaveAttribute("aria-pressed", "true");

  await page.locator("#saved-sort-name").click();
  await page.locator("#saved-tick-all").check();
  await button("hk").click();
  await expect(button("hk")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#saved-list .run-name")).toHaveText(["HK one", "HK two"]);
  await expect(page.locator("#saved-bar")).toBeHidden();
  await button("jp").click();
  await expect(page.locator("#saved-list")).toHaveText("No saved Tokyo backtests.");
  await expect(page.locator("#queue-list")).toHaveText("No Tokyo test is waiting or running. Select Add to queue in Build strategy.");
  await button("us").click();
  await expect(page.locator("#saved-list .run-name")).toHaveText(["US one"]);
  await page.reload();
  await expect(button("us")).toHaveAttribute("aria-pressed", "true");
});

test("Compare shows the settings that differ first, then the same ones, with the numbers of the server", async ({ page, home }) => {
  const fixed = await addCase(home, "builtins/us-built-ins-months", "Fixed sleeves");
  const random = await addCase(home, "formulas/us-random", "Random formula");
  await home.idle();
  await page.goto("/#/runs");
  await page.locator(`#saved-tick-${fixed.id}`).check();
  await page.locator(`#saved-tick-${random.id}`).check();
  await expect(page.locator("#saved-bar")).toContainText("2 tests ticked");
  await expect(page.locator("#saved-comparison")).toBeHidden();
  await page.locator("#saved-sort-name").click();
  await page.locator("#saved-compare").click();
  const panel = page.locator("#saved-comparison");
  await expect(panel).toBeVisible();
  await expect(page.locator("#saved-compare")).toHaveText("Hide comparison");
  // The columns follow the table's order: here by name.
  await expect(panel.locator("table").first().locator("thead th")).toHaveText(["Fixed sleeves", "Random formula"]);

  const groups = panel.locator("table").first().locator(".comparison-group th");
  await expect(groups).toHaveText(["Settings that differ", "Headline"]);
  const differing = panel.locator("table").first().locator("tbody").first();
  await expect(differing.locator("tr th[scope=row]").first()).toHaveText("Test type");
  await expect(differing.locator("tr").nth(1)).toContainText("Fixed dates");
  await expect(differing.locator("tr").nth(1)).toContainText("Random dates");
  await expect(panel.locator(".comparison-notice")).toHaveCount(2);

  // The headline cells are the stored numbers: the CAGR of the one trial of the fixed run, the median CAGR of the random run.
  const fixedTrials = await home.api<TrialsReply>("GET", `/api/runs/${fixed.id}/trials`);
  const randomTrials = await home.api<TrialsReply>("GET", `/api/runs/${random.id}/trials`);
  const median = randomTrials.statistics.find((stat) => stat.statistic === "cagr.median")!.value;
  const headline = panel.locator("table").first().locator("tbody").nth(1).locator("tr").nth(1);
  await expect(headline.locator("th")).toHaveText("Strategy CAGR / Median strategy CAGR");
  await expect(headline.locator("td").nth(0)).toHaveText(percent(fixedTrials.trials[0]!.cagr));
  await expect(headline.locator("td").nth(1)).toHaveText(percent(median));

  // Under the disclosure: the other measures of random dates, and the settings that are the same.
  await panel.locator("details > summary").click();
  const more = panel.locator("details table");
  await expect(more.locator(".comparison-group th")).toHaveText(["More measures", "Same settings", "Recorded"]);
  await expect(more.locator("tr", { hasText: "Stock market" }).locator("td")).toHaveText(["US", "US"]);
  const seed = (await home.api<RunRow>("GET", `/api/runs/${random.id}`)).schedule.seed;
  await expect(more.locator("tr", { hasText: "Random date set" }).locator("td")).toHaveText(["—", String(seed)]);
  await expect(panel.locator("table").first()).not.toContainText("Random date set");
  const mean = randomTrials.statistics.find((stat) => stat.statistic === "cagr.mean")!.value;
  await expect(more.locator("tr", { hasText: "Mean strategy CAGR" }).locator("td")).toHaveText(["—", percent(mean)]);

  await page.locator("#saved-compare").click();
  await expect(panel).toBeHidden();
  await page.locator("#saved-clear").click();
  await expect(page.locator("#saved-bar")).toBeHidden();
});

test("Tune in a saved row copies the run's settings to Build strategy", async ({ page, home }) => {
  await addCase(home, "builtins/hk-sleeves", "Two sleeves in Hong Kong");
  await home.idle();
  await page.goto("/#/runs");
  const row = await details(savedRow(page, "Two sleeves in Hong Kong"));
  await row.getByRole("button", { name: "Tune", exact: true }).click();
  await expect(page).toHaveURL(/#\/build$/);
  await expect(page.locator("#stock-market")).toHaveValue("hk");
  await expect(page.locator("#sleeve-tabs button")).toHaveText(["Value", "Income"]);
  await expect(page.locator("#mode-backtest")).toHaveAttribute("aria-pressed", "true");
});
