import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import type { Attribution } from "../src/api/Attribution.ts";
import type { HoldingsReply } from "../src/api/HoldingsReply.ts";
import type { PeriodRow } from "../src/api/PeriodRow.ts";
import type { RunRow } from "../src/api/RunRow.ts";
import type { SectorsReply } from "../src/api/SectorsReply.ts";
import type { TrialsReply } from "../src/api/TrialsReply.ts";
import { toCsv } from "../src/csv.ts";
import { settingsOf, trailOf } from "../src/describe.ts";
import { format, percent, points } from "../src/format.ts";
import { expect, test, type Home } from "./fixture.ts";

const cases = new URL("../../fixtures/fictional/cases/", import.meta.url);
const strategy = (name: string) => JSON.parse(readFileSync(new URL(name + "/strategy.json", cases), "utf8"));
const schedule = (name: string) => {
  const { start, end, interval, trials, seed } = JSON.parse(readFileSync(new URL(name + "/run.json", cases), "utf8"));
  return { start, end, every: interval, trials, seed };
};

async function added(home: Home, name: string, kind: string): Promise<RunRow> {
  const { id } = await home.api<RunRow>("POST", "/api/runs", { name, market: "us", schedule: schedule(kind), strategy: strategy(kind) });
  const run = await home.finished(id);
  if (run.state === "failed") throw new Error(run.error?.message);
  return run;
}

let random: RunRow;
let fixed: RunRow;

test.beforeAll(async ({ home }) => {
  await home.reset();
  random = await added(home, "Random sectors", "formulas/us-random");
  fixed = await added(home, "Fixed sleeves", "builtins/us-built-ins-months");
});

const open = async (page: Page, id: number, tab: "Returns" | "Selection") => {
  await page.goto(`/#/results/${id}`);
  await page.locator(`#workspace-review-tabs >> text=${tab}`).click();
};
const holdingsOf = (home: Home, run: RunRow, trial: number, period?: number) =>
  home.api<HoldingsReply>("GET", `/api/runs/${run.id}/holdings?trial=${trial}` + (period ? `&period=${period}` : ""));
const sectorsOf = (home: Home, run: RunRow) => home.api<Extract<SectorsReply, { trials: unknown }>>("GET", `/api/runs/${run.id}/sectors`);
const weightsOf = (home: Home, run: RunRow, trial: number) => home.api<Extract<SectorsReply, { weights: unknown }>>("GET", `/api/runs/${run.id}/sectors?trial=${trial}`);

test("the trial and the period choice change the period table and the holdings", async ({ page, home }) => {
  const trials = await home.api<TrialsReply>("GET", `/api/runs/${random.id}/trials`);
  await open(page, random.id, "Returns");
  await expect(page.locator("#schedule-trial-title")).toHaveText(`Trial 1 of ${trials.trials.length}`);
  for (const trial of [1, 3]) {
    await page.locator("#schedule-trial-choice").selectOption(String(trial));
    const periods = await home.api<PeriodRow[]>("GET", `/api/runs/${random.id}/periods?trial=${trial}`);
    await expect(page.locator("#schedule-trial-title")).toHaveText(`Trial ${trial} of ${trials.trials.length}`);
    await expect(page.locator("#schedule-cagr")).toHaveText(percent(trials.trials[trial - 1]!.cagr));
    await expect(page.locator("#schedule-rows tr")).toHaveCount(periods.length);
    await expect(page.locator("#schedule-rows tr").first()).toContainText(periods[0]!.entry);
    await expect(page.locator("#schedule-period option")).toHaveCount(periods.length);
    for (const period of periods.slice(0, 2)) {
      await page.locator("#schedule-period").selectOption(String(period.period));
      const holdings = (await holdingsOf(home, random, trial, period.period)).holdings;
      await expect(page.locator("#schedule-stock-body tr")).toHaveCount(holdings.length);
      await expect(page.locator("#schedule-stock-body tr").first()).toContainText(holdings[0]!.symbol);
      await expect(page.locator("#schedule-stock-body tr").first()).toContainText(percent(holdings[0]!.return));
    }
  }
  await expect(page.locator("#schedule-chart rect")).not.toHaveCount(0);
});

test("a holding's Details give its fields and the step trail of the holdings route", async ({ page, home }) => {
  const period = 2;
  const reply = await holdingsOf(home, fixed, 1, period);
  await open(page, fixed.id, "Returns");
  await page.locator("#schedule-period").selectOption(String(period));
  await expect(page.locator("#schedule-stock-body tr")).toHaveCount(reply.holdings.length);
  const settings = settingsOf(fixed);
  for (const [i, holding] of reply.holdings.slice(0, 6).entries()) {
    const row = page.locator("#schedule-stock-body tr").nth(i);
    await row.locator("summary").click();
    const details = row.locator(".holding-details");
    await expect(details).toContainText(holding.exchange);
    await expect(details).toContainText(holding.status);
    const trails = trailOf(settings, holding, reply.steps.filter((step) => step.rank === holding.rank));
    await expect(details.locator(".step-trail")).toHaveCount(trails.length);
    for (const [t, trail] of trails.entries()) {
      await expect(details.locator(".step-trail").nth(t).locator("li")).toHaveText(trail.lines);
      for (const line of trail.lines) expect(line).toMatch(/^Step \d+ · (Filter|Rank) · .+ · .+ · (passed|rank \d+ \(kept \d+–\d+\))$/);
    }
    // A sleeve of several: the sleeve's name leads its steps, and a rank step's value is in its display.
    await expect(details.locator("p").first()).toHaveText(trails[0]!.sleeve!);
    const rank = reply.steps.find((step) => step.rank === holding.rank && step.step_rank !== null)!;
    const display = settings.steps[rank.sleeve - 1]![rank.step - 1]!.display;
    await expect(details).toContainText(format(rank.value, display) + " · rank " + rank.step_rank);
  }
  // The ranking value column is the last rank step's value of the holding's first sleeve, in its display.
  const first = reply.holdings[0]!;
  const lastRank = settings.steps[first.sleeve - 1]!.findLast((step) => step.source.kind !== "field")!;
  await expect(page.locator("#schedule-stock-body tr").first().locator("td").nth(4)).toHaveText(format(first.ranking_value, lastRank.display));
});

test("the contribution pies equal the contributions route", async ({ page, home }) => {
  const route = await home.api<Attribution[]>("GET", `/api/runs/${random.id}/contributions?trial=2`);
  await open(page, random.id, "Returns");
  await page.locator("#schedule-trial-choice").selectOption("2");
  await page.locator("#schedule-attribution-disclosure summary").click();
  for (const attribution of route.slice(0, 3)) {
    await page.locator("#schedule-period").selectOption(String(attribution.period));
    const pies = page.locator("#schedule-attribution .contribution-pies figure");
    await expect(pies).toHaveCount(2);
    for (const [sign, heading, total, other] of [
      [1, "Gains", attribution.gains, attribution.other_gains],
      [-1, "Losses", attribution.losses, attribution.other_losses],
    ] as const) {
      const pie = pies.nth(sign > 0 ? 0 : 1);
      await expect(pie.locator("h4")).toHaveText(heading);
      await expect(pie.locator(".contribution-pie-center")).toContainText(points(sign * total));
      // A slice's share is its value's part of the pie's total.
      const expected = attribution.top.filter((top) => top.contribution * sign > 0).map((top) => `${top.symbol} · ${percent((top.contribution * sign) / total)} · ${points(top.contribution)}`);
      if (other > 0) expected.push(`${sign > 0 ? "Other gainers" : "Other losers"} · ${percent(other / total)} · ${points(other * sign)}`);
      if (expected.length) await expect(pie.locator("li")).toHaveText(expected);
      else await expect(pie.locator("li")).toHaveCount(0);
      if (total > 0) await expect(pie.locator(".contribution-pie")).toHaveAttribute("style", /conic-gradient\(/);
    }
    await expect(page.locator("#schedule-attribution p").last()).toContainText(`Top ${attribution.top.length} stocks: ${attribution.top.map((top) => `${top.symbol} (${points(top.contribution)})`).join(", ")}`);
    await expect(page.locator("#schedule-attribution p").last()).toContainText(`all ${attribution.count} selected stocks`);
  }
});

test("the sector view across the trials equals the sectors reply", async ({ page, home }) => {
  const reply = await sectorsOf(home, random);
  const trials = await home.api<TrialsReply>("GET", `/api/runs/${random.id}/trials`);
  await open(page, random.id, "Selection");
  await expect(page.locator("#sector-trial option")).toHaveCount(trials.trials.length + 1);
  await expect(page.locator("#sector-chart .sector-bar")).toHaveCount(trials.trials.length);
  const spread = [...reply.spread].sort((a, b) => b.mean - a.mean || a.sector.localeCompare(b.sector));
  await expect(page.locator("#sector-mix .sector-mix-row")).toHaveCount(spread.length);
  for (const [i, row] of spread.entries()) {
    const shown = page.locator("#sector-mix .sector-mix-row").nth(i);
    await expect(shown).toContainText(row.sector);
    await expect(shown.locator("strong")).toHaveText(percent(row.mean));
    await expect(shown.locator("small")).toHaveText(`${percent(row.minimum)}–${percent(row.maximum)}`);
    await expect(page.locator("#sector-legend button").nth(i)).toHaveText(row.sector);
  }
  await expect(page.locator("#sector-insight")).toHaveText(
    `${spread[0]!.sector} has the largest mean allocation in ${spread[0]!.leading} of ${trials.trials.length} complete trials. Mean entry allocation: ${percent(spread[0]!.mean)}.`,
  );
  await expect(page.locator("#sector-trials tr")).toHaveCount(trials.trials.length);
  for (const trial of trials.trials) {
    const mine = reply.trials.filter((share) => share.trial === trial.trial).sort((a, b) => b.mean - a.mean || a.sector.localeCompare(b.sector));
    const row = page.locator("#sector-trials tr").nth(trial.trial - 1);
    await expect(row).toContainText(mine[0]!.sector);
    await expect(row.locator("td").nth(2)).toHaveText(percent(mine[0]!.mean));
    await expect(row.locator("td").nth(3)).toHaveText(`${percent(mine[0]!.minimum)}–${percent(mine[0]!.maximum)}`);
    await expect(row.locator("td").nth(4)).toHaveText(`${mine[0]!.present} / ${trial.periods}`);
    // Each bar's segments are the trial's sectors, as high as their mean weights.
    const segments = page.locator("#sector-chart .sector-bar").nth(trial.trial - 1).locator(".sector-segment");
    await expect(segments).toHaveCount(mine.filter((share) => share.mean > 0).length);
  }
  // A sector chosen in the legend is the one the table shows for each trial, and Clear returns to all.
  const pick = spread[spread.length - 1]!;
  await page.locator("#sector-legend button").last().click();
  await expect(page.locator("#sector-clear")).toHaveText(`Clear ${pick.sector} filter`);
  for (const trial of trials.trials) {
    const share = reply.trials.find((each) => each.trial === trial.trial && each.sector === pick.sector);
    await expect(page.locator("#sector-trials tr").nth(trial.trial - 1).locator("td").nth(2)).toHaveText(percent(share?.mean ?? 0));
  }
  await page.locator("#sector-clear").click();
  await expect(page.locator("#sector-clear")).toBeHidden();
});

test("the sector view at each rebalance equals the trial's weights, starting on the last period", async ({ page, home }) => {
  const trial = 2;
  const weights = (await weightsOf(home, random, trial)).weights;
  const periods = await home.api<PeriodRow[]>("GET", `/api/runs/${random.id}/periods?trial=${trial}`);
  await open(page, random.id, "Selection");
  await page.locator("#sector-trial").selectOption(String(trial));
  await expect(page.locator("#sector-chart .sector-bar")).toHaveCount(periods.length);
  await expect(page.locator("#sector-trials-wrap")).toHaveCount(0);
  await expect(page.locator("#sector-period option")).toHaveCount(periods.length);
  await expect(page.locator("#sector-period")).toHaveValue(String(periods.length));
  await expect(page.locator("#sector-period-next")).toBeDisabled();
  for (const period of [...periods].reverse()) {
    const mine = weights.filter((weight) => weight.period === period.period).sort((a, b) => b.weight - a.weight || a.sector.localeCompare(b.sector));
    await expect(page.locator("#sector-mix-title")).toHaveText(period.entry);
    await expect(page.locator("#sector-mix-note")).toHaveText(`${period.names} selected stocks · held through ${period.exit}`);
    await expect(page.locator("#sector-mix .sector-mix-row")).toHaveCount(mine.length);
    for (const [i, weight] of mine.entries()) {
      await expect(page.locator("#sector-mix .sector-mix-row").nth(i)).toContainText(weight.sector);
      await expect(page.locator("#sector-mix .sector-mix-row").nth(i).locator("strong")).toHaveText(percent(weight.weight));
      await expect(page.locator("#sector-mix .sector-mix-row").nth(i).locator("small")).toHaveText(`${weight.count} ${weight.count === 1 ? "stock" : "stocks"}`);
    }
    const heights = await page.locator("#sector-chart .sector-bar").nth(period.period - 1).locator(".sector-segment").evaluateAll((all) => all.map((each) => (each as HTMLElement).style.height));
    const shown = heights.map(parseFloat).sort((a, b) => a - b);
    const given = mine.map((weight) => weight.weight * 100).sort((a, b) => a - b);
    expect(shown).toHaveLength(given.length);
    given.forEach((height, i) => expect(shown[i]).toBeCloseTo(height, 3));
    if (period.period > 1) await page.locator("#sector-period-back").click();
  }
  await expect(page.locator("#sector-period-back")).toBeDisabled();
  await page.locator("#sector-period").selectOption(String(periods.length));
  await expect(page.locator("#sector-period-next")).toBeDisabled();
});

test("an inspect button opens the matching holdings on Returns, limited to its sector", async ({ page, home }) => {
  const reply = await sectorsOf(home, random);
  await open(page, random.id, "Selection");
  // A trial row: its first listed sector, in the last period that holds it.
  const trial = 3;
  const mine = reply.trials.filter((share) => share.trial === trial).sort((a, b) => b.mean - a.mean || a.sector.localeCompare(b.sector));
  const sector = mine[0]!.sector;
  await page.locator(`#sector-trials button[data-sector-inspect="${trial}"]`).click();
  await expect(page.locator("#workspace-review")).toHaveAttribute("data-section", "returns");
  await expect(page.locator("#schedule-trial-title")).toContainText(`Trial ${trial} of`);
  const first = (await weightsOf(home, random, trial)).weights.findLast((weight) => weight.sector === sector && weight.weight > 0)!.period;
  await expect(page.locator("#schedule-period")).toHaveValue(String(first));
  await expect(page.locator("#schedule-sector-note")).toContainText(`Sector filter: ${sector}.`);
  const expected = (await holdingsOf(home, random, trial, first)).holdings.filter((holding) => holding.sector === sector);
  await expect(page.locator("#schedule-stock-body tr")).toHaveCount(expected.length);
  await expect(page.locator("#schedule-stock-body tr td:nth-child(3)")).toHaveText(expected.map(() => sector));
  // Another period of the same trial keeps the sector; its ranks are those of the whole period.
  await page.locator("#schedule-period").selectOption("1");
  const second = (await holdingsOf(home, random, trial, 1)).holdings.filter((holding) => holding.sector === sector);
  await expect(page.locator("#schedule-stock-body tr")).toHaveCount(second.length || 1);
  if (second.length) await expect(page.locator("#schedule-stock-body tr td:first-child")).toHaveText(second.map((holding) => String(holding.rank)));

  // One trial's bar: that period on Returns, with the chosen sector.
  await page.locator("#workspace-review-tabs >> text=Selection").click();
  await page.locator("#sector-trial").selectOption(String(trial));
  await page.locator("#sector-chart .sector-bar").nth(1).click();
  await expect(page.locator("#workspace-review")).toHaveAttribute("data-section", "returns");
  await expect(page.locator("#schedule-period")).toHaveValue("2");
  await expect(page.locator("#schedule-sector-note")).toContainText(`Sector filter: ${sector}.`);
});

test("a fixed schedule has one trial: its sector view, period choice and no trial choice", async ({ page, home }) => {
  const periods = await home.api<PeriodRow[]>("GET", `/api/runs/${fixed.id}/periods?trial=1`);
  const weights = (await weightsOf(home, fixed, 1)).weights;
  await open(page, fixed.id, "Selection");
  await expect(page.locator("#sector-trial option")).toHaveText(["Fixed schedule"]);
  await expect(page.locator("#sector-chart .sector-bar")).toHaveCount(periods.length);
  await expect(page.locator("#sector-period")).toHaveValue(String(periods.length));
  await expect(page.locator("#sector-mix .sector-mix-row")).toHaveCount(weights.filter((weight) => weight.period === periods.length).length);
  await page.locator("#sector-legend button").first().click();
  await page.locator("#workspace-review-tabs >> text=Returns").click();
  await expect(page.locator("#schedule-trial-title")).toHaveCount(0);
  await expect(page.locator("#schedule-sector-note")).toContainText("Sector filter:");
});

test("the period and holding files are the replies as CSV", async ({ page, home }) => {
  for (const [run, trial, tab] of [
    [random, 2, "Returns"],
    [fixed, 1, "Overview"],
    [fixed, 1, "Returns"],
  ] as const) {
    await page.goto(`/#/results/${run.id}`);
    await page.locator(`#workspace-review-tabs >> text=${tab}`).click();
    if (trial === 2) await page.locator("#schedule-trial-choice").selectOption("2");
    const periods = await home.api<PeriodRow[]>("GET", `/api/runs/${run.id}/periods?trial=${trial}`);
    const holdings = await holdingsOf(home, run, trial);
    // The files are made from what the page shows: wait for the chosen trial's table.
    await expect(page.locator("#schedule-rows tr")).toHaveCount(periods.length);
    await expect(page.locator("#schedule-rows tr").first()).toContainText(periods[0]!.entry);
    await expect(page.locator("#schedule-download-holdings")).toBeVisible();
    await expect(page.locator("#schedule-download-returns")).toBeVisible();
    const returns = page.waitForEvent("download");
    await page.locator("#schedule-download-returns").click();
    const file = await returns;
    expect(file.suggestedFilename()).toMatch(/^scheduled-returns-2021-07-01-2023-06-28/);
    expect(readFileSync((await file.path())!, "utf8")).toBe(toCsv(periods));
    const second = page.waitForEvent("download");
    await page.locator("#schedule-download-holdings").click();
    const holdingsFile = await second;
    expect(holdingsFile.suggestedFilename()).toMatch(/^scheduled-holdings-/);
    expect(readFileSync((await holdingsFile.path())!, "utf8")).toBe(toCsv(holdings.holdings));
  }
});

test("the coverage line names the shown trial's short and empty periods and how long a fixed schedule computed", async ({ page, home }) => {
  const trials = await home.api<TrialsReply>("GET", `/api/runs/${random.id}/trials`);
  await open(page, random.id, "Returns");
  await page.locator("#schedule-trial-choice").selectOption("3");
  const trial = trials.trials[2]!;
  await expect(page.locator("#schedule-trial #schedule-coverage")).toContainText(`${trial.short_periods} short periods; ${trial.empty_periods} empty periods.`);
  await expect(page.locator("#schedule-coverage")).not.toContainText("Computed in");
  await open(page, fixed.id, "Returns");
  await page.locator("#workspace-recorded-context summary").click();
  await expect(page.locator("#schedule-coverage")).toContainText("Computed in ");
});

test("only the latest press of an inspect button counts, and none counts after the tab is left", async ({ page }) => {
  await open(page, random.id, "Selection");
  const held: (() => void)[] = [];
  await page.route("**/api/runs/*/sectors?trial=*", async (route) => {
    await new Promise<void>((release) => held.push(release));
    await route.continue();
  });
  const press = (trial: number) => page.locator(`#sector-trials button[data-sector-inspect="${trial}"]`).click();
  // Lets a held reply through, and waits until the page has had its turn to read it: the reply
  // has been received whole, and two frames have been drawn.
  const released = async (release: () => void, query: string) => {
    const response = page.waitForResponse((reply) => reply.url().includes("/sectors?") && reply.url().includes(query));
    release();
    await (await response).finished();
    await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
  };
  // Trial 1, then trial 2: the reply of trial 1 comes while Selection is still shown and is
  // ignored; the reply of trial 2 opens Returns.
  await press(1);
  await press(2);
  await expect.poll(() => held.length).toBe(2);
  await released(held[0]!, "trial=1");
  await expect(page.locator("#workspace-review")).toHaveAttribute("data-section", "selection");
  held[1]!();
  await expect(page.locator("#workspace-review")).toHaveAttribute("data-section", "returns");
  await expect(page.locator("#schedule-trial-title")).toContainText("Trial 2 of");

  // A press, then Overview: the reply, arriving later, does not bring the page back to Returns.
  held.length = 0;
  await page.locator("#workspace-review-tabs >> text=Selection").click();
  await press(3);
  await expect.poll(() => held.length).toBe(1);
  await page.locator("#workspace-review-tabs >> text=Overview").click();
  await released(held[0]!, "trial=3");
  await expect(page.locator("#workspace-review")).toHaveAttribute("data-section", "overview");
  await page.unroute("**/api/runs/*/sectors?trial=*");
});

test("the holdings of a period are read for the table and the whole trial only for its download, whose failure shows beside the button", async ({ page, home }) => {
  const reads: string[] = [];
  page.on("request", (request) => request.url().includes("/holdings") && reads.push(new URL(request.url()).search));
  await open(page, fixed.id, "Returns");
  await expect(page.locator("#schedule-stock-body tr").first()).toBeVisible();
  await expect.poll(() => reads).toEqual(["?trial=1&period=1"]);
  await page.locator("#schedule-period").selectOption("2");
  await expect(page.locator("#schedule-stock-body tr").first()).toContainText((await holdingsOf(home, fixed, 1, 2)).holdings[0]!.symbol);
  await expect.poll(() => reads).toEqual(["?trial=1&period=1", "?trial=1&period=2"]);
  await page.route("**/api/runs/*/holdings?trial=1", (route) => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { message: "The result could not be read.", place: "" } }) }));
  await page.locator("#schedule-download-holdings").click();
  await expect(page.locator("#schedule-download-holdings + .warning")).toHaveText("The result could not be read.");
  await expect(page.locator("#schedule-download-returns")).toBeVisible();
});

test("Tune this strategy opens Build strategy with the run's market and sleeves", async ({ page }) => {
  await open(page, fixed.id, "Returns");
  await page.locator("#workspace-edit-copy").click();
  await expect(page).toHaveURL(/#\/build$/);
  await expect(page.locator("#stock-market")).toHaveValue(fixed.market);
  await expect(page.locator("#sleeve-tabs button")).toHaveText(strategy("builtins/us-built-ins-months").sleeves.map((sleeve: { name: string }) => sleeve.name));
});

test("cash shows as a segment of each trial's bar, as the average under the mix, and as a full bar for an empty period", async ({ page, home }) => {
  const { start, end, interval } = JSON.parse(readFileSync(new URL("builtins/jp-built-ins-months/run.json", cases), "utf8"));
  const { id } = await home.api<RunRow>("POST", "/api/runs", { name: "Cash run", market: "jp", schedule: { start, end, every: interval, trials: 3, seed: 6 }, strategy: strategy("builtins/jp-built-ins-months") });
  expect((await home.finished(id)).state).toBe("complete");
  const reply = await home.api<Extract<SectorsReply, { trials: unknown }>>("GET", `/api/runs/${id}/sectors`);
  expect(reply.cash.some((each) => each.cash > 0)).toBe(true);
  await open(page, id, "Selection");
  await expect(page.locator("#sector-chart .sector-bar")).toHaveCount(reply.cash.length);
  for (const each of reply.cash) {
    const segment = page.locator("#sector-chart .sector-bar").nth(each.trial - 1).locator(".sector-cash");
    if (each.cash === 0) {
      await expect(segment).toHaveCount(0);
      continue;
    }
    await expect(segment).toHaveCount(1);
    await expect(segment).toHaveAttribute("title", `Cash ${percent(each.cash)}`);
    expect(parseFloat((await segment.getAttribute("style"))!.match(/height:\s*([\d.]+)%/)![1]!)).toBeCloseTo(each.cash * 100, 3);
  }
  await expect(page.locator("#sector-mix .hint")).toHaveText(`Average cash: ${percent(reply.mean_cash)}.`);
  await expect(page.locator("#sector-legend")).toContainText("Cash");

  // One trial: an empty period is a full cash bar, and the mix says so.
  const trial = reply.cash.find((each) => each.cash > 0)!.trial;
  const periods = await home.api<PeriodRow[]>("GET", `/api/runs/${id}/periods?trial=${trial}`);
  const empty = periods.find((period) => period.names === 0)!;
  await page.locator("#sector-trial").selectOption(String(trial));
  await expect(page.locator("#sector-chart .sector-bar")).toHaveCount(periods.length);
  await expect(page.locator("#sector-chart .sector-bar").nth(empty.period - 1).locator(".sector-cash")).toHaveCount(1);
  await page.locator("#sector-period").selectOption(String(empty.period));
  await expect(page.locator("#sector-mix-note")).toHaveText(`0 selected stocks · held through ${empty.exit}`);
  await expect(page.locator("#sector-mix .hint")).toHaveText("No stocks selected. The portfolio holds cash until the next rebalance.");
});

test("Selection and Returns share one current period", async ({ page, home }) => {
  const periods = await home.api<PeriodRow[]>("GET", `/api/runs/${random.id}/periods?trial=2`);
  const last = periods.length;
  await open(page, random.id, "Selection");
  await page.locator("#sector-trial").selectOption("2");
  await expect(page.locator("#sector-period")).toHaveValue(String(last));
  await page.locator("#sector-period").selectOption("2");
  await expect(page.locator("#sector-mix-title")).toHaveText(periods[1]!.entry);
  await page.locator("#workspace-review-tabs >> text=Returns").click();
  await expect(page.locator("#schedule-period")).toHaveValue("2");
  await page.locator("#schedule-period").selectOption("3");
  await page.locator("#workspace-review-tabs >> text=Selection").click();
  await expect(page.locator("#sector-period")).toHaveValue("3");
  await expect(page.locator("#sector-chart .sector-bar.selected")).toHaveCount(1);
  await expect(page.locator("#sector-chart .sector-bar").nth(2)).toHaveClass(/selected/);
  await page.locator("#sector-chart .sector-bar").nth(0).click();
  await expect(page.locator("#schedule-period")).toHaveValue("1");
  await page.locator("#workspace-review-tabs >> text=Selection").click();
  await expect(page.locator("#sector-period")).toHaveValue("1");
  await expect(page.locator("#sector-chart .sector-bar").nth(0)).toHaveClass(/selected/);

  // A fixed schedule: Returns opens on period 1 until Selection has been shown, which sets the last.
  const fixedPeriods = await home.api<PeriodRow[]>("GET", `/api/runs/${fixed.id}/periods?trial=1`);
  await open(page, fixed.id, "Returns");
  await expect(page.locator("#schedule-period")).toHaveValue("1");
  await page.locator("#workspace-review-tabs >> text=Selection").click();
  await expect(page.locator("#sector-period")).toHaveValue(String(fixedPeriods.length));
  await page.locator("#workspace-review-tabs >> text=Returns").click();
  await expect(page.locator("#schedule-period")).toHaveValue(String(fixedPeriods.length));
});
