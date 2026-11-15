import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import type { AddRun } from "../src/api/AddRun.ts";
import type { CurveReply } from "../src/api/CurveReply.ts";
import type { ExploreReply } from "../src/api/ExploreReply.ts";
import type { PeriodRow } from "../src/api/PeriodRow.ts";
import type { RunRow } from "../src/api/RunRow.ts";
import type { TrialsReply } from "../src/api/TrialsReply.ts";
import { toCsv } from "../src/csv.ts";
import { headlineCells } from "../src/describe.ts";
import { percent } from "../src/format.ts";
import { expect, test, type Home } from "./fixture.ts";

const RANK = { sleeves: [{ steps: [{ rank: "EBITDA yield", order: "highest" as const, from: 1, to: 3 }] }] };
const WINDOW = { start: "2021-07-01", end: "2023-06-28", every: "3m" };
const FUTURE = {
  variables: { "Later revenue": { formula: "at(Revenue, 2022-12-30)", display: "usd" } },
  sleeves: [{ steps: [{ rank: "Later revenue", order: "highest" as const, from: 1, to: 3 }] }],
};

const add = (home: Home, name: string, schedule: AddRun["schedule"], strategy: AddRun["strategy"] = RANK) =>
  home.api<RunRow>("POST", "/api/runs", { name, market: "us", schedule, strategy } satisfies AddRun);

async function finished(home: Home, id: number): Promise<RunRow> {
  for (let i = 0; i < 200; i++) {
    const run = await home.api<RunRow>("GET", `/api/runs/${id}`);
    if (run.state === "complete" || run.state === "failed") return run;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`run ${id} did not finish`);
}

let random: RunRow;
let fixed: RunRow;

test.beforeAll(async ({ home }) => {
  random = await finished(home, (await add(home, "Random test", { ...WINDOW, trials: 12, seed: 7 })).id);
  fixed = await finished(home, (await add(home, "Fixed test", WINDOW)).id);
});

const open = (page: Page, id: number) => page.goto(`/#/results/${id}`);

test("a result opens by its address, and #/results shows the last one opened", async ({ page }) => {
  await page.goto("/#/results");
  await expect(page.locator("#workspace-no-result h2")).toHaveText("No backtest is open");
  await page.locator("#workspace-no-result button").click();
  await expect(page).toHaveURL(/#\/runs$/);

  await open(page, random.id);
  await expect(page.locator("#workspace-result-title")).toHaveText("Random test");
  await expect(page.locator("#workspace-result-window")).toHaveText("2021-07-01 → 2023-06-28 · Random dates");
  await page.locator("#workspace-nav >> text=Build strategy").click();
  await expect(page.locator("#workspace-review")).toBeHidden();
  await page.locator("#workspace-nav >> text=Result review").click();
  await expect(page).toHaveURL(new RegExp(`#/results/${random.id}$`));
  await expect(page.locator("#workspace-result-title")).toHaveText("Random test");

  await open(page, fixed.id);
  await expect(page.locator("#workspace-result-title")).toHaveText("Fixed test");
});

test("the headline and the settings are the server's numbers in words", async ({ page, home }) => {
  for (const run of [random, fixed]) {
    const trials = await home.api<TrialsReply>("GET", `/api/runs/${run.id}/trials`);
    await open(page, run.id);
    const cells = headlineCells(run.schedule, trials);
    await expect(page.locator("#workspace-headline > div")).toHaveCount(cells.length);
    for (const [i, cell] of cells.entries()) {
      const shown = page.locator("#workspace-headline > div").nth(i);
      await expect(shown.locator("dt")).toHaveText(cell.label);
      await expect(shown.locator("dd")).toHaveText(cell.text);
    }
    await expect(page.locator("#workspace-parameters")).toContainText("Step 1 · Rank");
    await expect(page.locator("#workspace-parameters")).toContainText("EBITDA yield · highest first · ranks 1–3");
  }
});

test("the curve is a band for random dates and a line for a fixed schedule, with a hover readout", async ({ page, home }) => {
  await open(page, random.id);
  const band = (await home.api<Extract<CurveReply, { band: unknown }>>("GET", `/api/runs/${random.id}/curve`)).band;
  await expect(page.locator("#curve-all-chart path[opacity='.16']")).toHaveCount(1);
  await expect(page.locator("#curve-trial")).toHaveCount(0);
  const readout = page.locator("#curve-all-readout");
  await expect(readout).toContainText(band[band.length - 1]!.day);
  const box = (await page.locator("#curve-all-chart").boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await expect(readout).toContainText("Median trial");
  await expect(readout).not.toContainText(band[band.length - 1]!.day);
  await page.mouse.move(box.x - 10, box.y - 10);
  await expect(readout).toContainText(band[band.length - 1]!.day);

  await open(page, fixed.id);
  const growth = (await home.api<Extract<CurveReply, { growth: unknown }>>("GET", `/api/runs/${fixed.id}/curve?trial=1`)).growth;
  await expect(page.locator("#curve-trial-chart")).toBeVisible();
  await expect(page.locator("#curve-trial-chart path[opacity]")).toHaveCount(0);
  await expect(page.locator("#curve-trial-chart path[stroke]")).toHaveCount(2);
  const line = page.locator("#curve-trial-readout");
  await expect(line).toContainText(growth[growth.length - 1]!.day);
  const fixedBox = (await page.locator("#curve-trial-chart").boundingBox())!;
  await page.mouse.move(fixedBox.x + fixedBox.width * 0.3, fixedBox.y + fixedBox.height * 0.5);
  await expect(line).toContainText("Strategy");
  await expect(line).not.toContainText(growth[growth.length - 1]!.day);
});

test("a fixed schedule shows a bar for the strategy and for SPY in each period", async ({ page, home }) => {
  const periods = await home.api<PeriodRow[]>("GET", `/api/runs/${fixed.id}/periods?trial=1`);
  await open(page, fixed.id);
  await expect(page.locator("#schedule-chart rect")).toHaveCount(periods.length * 2);
  await expect(page.locator("#schedule-chart rect").first()).toHaveAttribute("aria-label", `${periods[0]!.entry} → ${periods[0]!.exit} · Strategy ${percent(periods[0]!.portfolio)}`);
  await expect(page.locator("#schedule-rows tr")).toHaveCount(periods.length);
  await page.locator("#schedule-chart rect").nth(1).hover();
  await expect(page.locator(".chart-detail")).toContainText("SPY");
  await page.locator("#schedule-chart rect").nth(2).focus();
  await expect(page.locator(".chart-detail")).toHaveText(`${periods[1]!.entry} → ${periods[1]!.exit} · Strategy ${percent(periods[1]!.portfolio)}`);
  await open(page, random.id);
  await expect(page.locator("#schedule-chart")).toHaveCount(0);
});

test("the distribution, the statistics and the trial table show the trials, and a trial can be inspected", async ({ page, home }) => {
  const trials = await home.api<TrialsReply>("GET", `/api/runs/${random.id}/trials`);
  await open(page, random.id);
  await expect(page.locator("#robustness-trials tr")).toHaveCount(trials.trials.length);
  await expect(page.locator("#robustness-trials tr").first()).toContainText(percent(trials.trials[0]!.cagr));
  await expect(page.locator("#robustness-chart rect[tabindex]")).not.toHaveCount(0);
  await expect(page.locator("#robustness-chart path[stroke-dasharray]")).toHaveCount(2);
  await page.locator("#robustness-measure").selectOption("excess_cagr");
  await expect(page.locator("#robustness-chart path[stroke-dasharray]")).toHaveCount(1);
  await expect(page.locator("#robustness-chart-note")).toContainText("Seed 7 · 12 complete trials.");
  const mean = trials.statistics.find((row) => row.statistic === "cagr.mean")!.value as number;
  await expect(page.locator("#robustness-distribution tr").first()).toContainText(percent(mean));

  await page.locator("#robustness-trial").selectOption("3");
  await page.locator("#robustness-inspect").click();
  await expect(page.locator("#workspace-review-tabs [aria-current=page]")).toHaveText("Returns");
  await expect(page.locator("#workspace-review")).toHaveAttribute("data-section", "returns");
  await page.locator("#workspace-review-tabs >> text=Overview").click();
  await expect(page.locator("#robustness-trial")).toHaveValue("3");
});

test("the trial table downloads as CSV with the reply's field names", async ({ page, home }) => {
  const trials = await home.api<TrialsReply>("GET", `/api/runs/${random.id}/trials`);
  await open(page, random.id);
  const download = page.waitForEvent("download");
  await page.locator("#robustness-download").click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("random-dates-seed-7.csv");
  expect(readFileSync((await file.path())!, "utf8")).toBe(toCsv(trials.trials));
});

test("each tab remembers its scroll position", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 500 });
  await open(page, random.id);
  await expect(page.locator("#robustness-trials tr").first()).toBeVisible();
  // A pointer click, as a reader makes it: it does not move the page first.
  const press = async (name: string) => {
    const box = (await page.locator(`#workspace-review-tabs >> text=${name}`).boundingBox())!;
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  };
  await page.mouse.move(600, 400);
  await page.mouse.wheel(0, 900);
  await expect.poll(() => page.evaluate(() => Math.round(scrollY))).toBe(900);
  await press("Selection");
  await expect(page.locator("#workspace-review")).toHaveAttribute("data-section", "selection");
  await press("Overview");
  await expect(page.locator("#workspace-review")).toHaveAttribute("data-section", "overview");
  await expect.poll(() => page.evaluate(() => Math.round(scrollY))).toBe(900);
});

test("Explore of one trial equals the route, with the strategy's ranks as defaults", async ({ page, home }) => {
  const route = (periods: string, ranks: string) => home.api<Extract<ExploreReply, { cagr: unknown }>>("GET", `/api/runs/${fixed.id}/explore?trial=1&periods=${periods}&ranks=${ranks}`);
  await open(page, fixed.id);
  await page.locator("#explore-title").click();
  await expect(page.locator("#explore-status")).toHaveText("Summary of saved returns. No backtest was run.");
  await expect(page.locator("#explore-rank-from")).toHaveValue("1");
  await expect(page.locator("#explore-rank-to")).toHaveValue("3");
  const whole = await route("1-8", "1-3");
  await expect(page.locator("#explore-strategy-return")).toHaveText(percent(whole.total_return));
  await expect(page.locator("#explore-spy-cagr")).toHaveText(percent(whole.spy_cagr));

  await page.locator("#explore-period-from").selectOption("2");
  await page.locator("#explore-period-to").selectOption("5");
  await page.locator("#explore-rank-to").fill("2");
  await expect(page.locator("#explore-status")).toHaveText("Selection changed. Select Apply to update the summary.");
  await page.locator("#explore-apply").click();
  const part = await route("2-5", "1-2");
  await expect(page.locator("#explore-strategy-return")).toHaveText(percent(part.total_return));
  await expect(page.locator("#explore-strategy-cagr")).toHaveText(percent(part.cagr));
  await expect(page.locator("#explore-window")).toHaveText(`${part.start} → ${part.end} · ranks 1–2 · 4 holding periods`);

  await page.locator("#explore-reset").click();
  await expect(page.locator("#explore-strategy-return")).toHaveText(percent(whole.total_return));
  await expect(page.locator("#explore-rank-to")).toHaveValue("3");
  await expect(page.locator("#explore-period-from")).toHaveValue("1");
});

test("Explore of all trials equals the route and replaces the distribution until Reset", async ({ page, home }) => {
  const route = await home.api<Extract<ExploreReply, { trials: unknown }>>("GET", `/api/runs/${random.id}/explore?trial=all&periods=2-6&ranks=1-2`);
  const original = await home.api<TrialsReply>("GET", `/api/runs/${random.id}/trials`);
  await open(page, random.id);
  await expect(page.locator("#explore-title")).toHaveText("Explore all 12 trials");
  await page.locator("#explore-title").click();
  await expect(page.locator("#explore-rank-from")).toHaveValue("1");
  await expect(page.locator("#explore-rank-to")).toHaveValue("3");
  await expect(page.locator("#explore-period-to option")).toHaveCount(8);
  await page.locator("#explore-period-from").selectOption("2");
  await page.locator("#explore-period-to").selectOption("6");
  await page.locator("#explore-rank-to").fill("2");
  await page.locator("#explore-apply").click();
  const mean = route.statistics.find((row) => row.statistic === "cagr.mean")!.value as number;
  await expect(page.locator("#robustness-mean")).toHaveText(percent(mean));
  await expect(page.locator("#robustness-scope")).toContainText(`Explore selection: ${route.start} → ${route.end} · ranks 1–2`);
  await expect(page.locator("#robustness-trials tr").first()).toContainText(percent(route.trials[0]!.cagr));
  await expect(page.locator("#workspace-headline")).toContainText(percent(original.statistics.find((row) => row.statistic === "cagr.median")!.value as number));

  await page.locator("#explore-reset").click();
  await expect(page.locator("#robustness-scope")).toHaveCount(0);
  await expect(page.locator("#robustness-mean")).toHaveText(percent(original.statistics.find((row) => row.statistic === "cagr.mean")!.value as number));
});

test("a rename in the run list changes the title and keeps the open Explore and the chosen measure", async ({ page, home }) => {
  await open(page, random.id);
  await page.locator("#robustness-measure").selectOption("excess_cagr");
  await page.locator("#explore-title").click();
  await expect(page.locator("#explore-status")).toHaveText("Summary across all saved trials. No backtest was run.");
  await home.api("PATCH", `/api/runs/${random.id}`, { name: "Renamed test" });
  // The run list is read again when the page becomes visible (as after a change in Runs & saved).
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(page.locator("#workspace-result-title")).toHaveText("Renamed test");
  await expect(page.locator("#result-explorer")).toHaveAttribute("open", "");
  await expect(page.locator("#robustness-measure")).toHaveValue("excess_cagr");
  await page.locator("#workspace-review-tabs >> text=Selection").click();
  await page.locator("#workspace-review-tabs >> text=Overview").click();
  await expect(page.locator("#robustness-measure")).toHaveValue("excess_cagr");
  await home.api("PATCH", `/api/runs/${random.id}`, { name: "Random test" });
});

test("a waiting, held, failed, running and stopped run show their state, and a finished run opens its result", async ({ page, home }) => {
  await home.api("PUT", "/api/queue", { paused: true });
  const quick = await add(home, "Quick test", { ...WINDOW, trials: 3, seed: 1 });
  const failing = await add(home, "Future test", { start: "2021-07-01", end: "2023-06-28", dates: ["2022-07-01", "2023-01-02"] }, FUTURE);
  const long = await home.addLongRun("Long test");
  const held = await add(home, "Held test", { ...WINDOW, trials: 3, seed: 2 });
  await home.api("POST", `/api/runs/${held.id}/hold`);

  await open(page, held.id);
  await expect(page.locator("#workspace-run-message h2")).toHaveText("On hold");
  await expect(page.locator("#workspace-run-message")).toContainText("Release it in Runs & saved");

  await open(page, quick.id);
  await expect(page.locator("#workspace-run-message h2")).toHaveText("Waiting in the queue");
  await expect(page.locator("#workspace-result-title")).toHaveText("Quick test");
  await expect(page.locator("#workspace-parameters")).toContainText("Random dates");

  await home.api("PUT", "/api/queue", { paused: false });
  await expect(page.locator("#workspace-headline > div").first().locator("dt")).toHaveText("Median strategy CAGR", { timeout: 20_000 });
  await expect(page.locator("#workspace-run-message")).toHaveCount(0);

  const failed = await finished(home, failing.id);
  expect(failed.state).toBe("failed");
  await open(page, failing.id);
  await expect(page.locator("#workspace-run-error")).toContainText(failed.error!.message);
  await expect(page.locator("#workspace-run-message")).toContainText(failed.error!.place);
  await expect(page.locator("#workspace-run-message h2")).toHaveText("This test failed");

  await home.whileRunning(long.id, async () => {
    await open(page, long.id);
    await expect(page.locator("#workspace-run-message h2")).toHaveText("Running");
    await expect(page.locator("#workspace-run-message p")).toContainText("Running for");
  });
  await home.api("POST", `/api/runs/${long.id}/stop`);
  await expect(page.locator("#workspace-run-message h2")).toHaveText("Stopped");
  await expect(page.locator("#workspace-run-message")).toContainText("stopped before it finished");
});
