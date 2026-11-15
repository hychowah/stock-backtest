import { readFileSync } from "node:fs";
import type { ScreenBody } from "../src/api/ScreenBody.ts";
import type { ScreenReply } from "../src/api/ScreenReply.ts";
import { toCsv } from "../src/csv.ts";
import { trailOf } from "../src/describe.ts";
import { defaultDraft } from "../src/draft.ts";
import { format } from "../src/format.ts";
import { expect, test } from "./fixture.ts";

/** The default draft's strategy, as Latest stock picks sends it. */
const DEFAULT: ScreenBody = {
  market: "us",
  strategy: {
    sleeves: [
      {
        steps: [
          { filter: "Market cap", op: ">=", value: "100" },
          { filter: "Enterprise value", op: ">=", value: "50" },
          { rank: "EBITDA yield", order: "highest", from: 1, to: 50 },
        ],
      },
    ],
  },
};

test("the latest picks and a pick's step trail equal the reply of POST /api/screen", async ({ page, home }) => {
  const reply = await home.api<ScreenReply>("POST", "/api/screen", DEFAULT);
  expect(reply.picks.length).toBeGreaterThan(1);
  await page.goto("/");

  // Auto-run screens the draft without a click.
  const rows = page.locator("#latest-body tr");
  await expect(rows).toHaveCount(reply.picks.length);
  await expect(page.locator("#latest-date")).toHaveText(reply.day);
  await expect(page.locator("header .pill")).toHaveText(reply.day);
  await expect(page.locator("#latest-count")).toHaveText(String(reply.picks.length));
  expect(reply.median_market_cap).toBeDefined();
  await expect(page.locator("#latest-median-cap")).toHaveText(format(reply.median_market_cap, "usd_million"));
  await expect(page.locator("#latest-median-yield")).toHaveText(format(reply.median_ebitda_yield, "percent"));
  await expect(page.locator("#results-state")).toHaveText("");
  await expect(page.locator("#latest-view thead th").nth(3)).toHaveText("Ranking value · highest");
  for (const [i, pick] of reply.picks.entries()) {
    // A closed Details shows only its summary.
    await expect.poll(() => rows.nth(i).locator("td").allInnerTexts()).toEqual([
      String(pick.rank),
      pick.symbol,
      pick.name,
      format(pick.ranking_value, "percent"),
      pick.exchange,
      pick.sector || "Unknown",
      format(pick.price, "number"),
      format(pick.market_cap, "usd_million"),
      format(pick.enterprise_value, "usd_million"),
      format(pick.ebitda_yield, "percent"),
      format(pick.ev_ebitda, "multiple"),
      pick.fiscal,
      pick.known,
      pick.price_date,
      "Details",
    ]);
  }

  const settings = { market: reply.market, schedule: { start: reply.day, end: reply.day }, strategy: DEFAULT.strategy, steps: reply.description.sleeves.map((sleeve) => sleeve.steps) };
  const pick = reply.picks[1]!;
  const [trail] = trailOf(settings, pick, pick.steps);
  await rows.nth(1).locator("summary").click();
  await expect(rows.nth(1).locator(".step-trail li")).toHaveText(trail!.lines);
  expect(trail!.lines[0]).toBe(`Step 1 · Filter · Market cap · ${format(pick.steps[0]!.value, "usd_million")} · passed`);

  // The CSV holds the reply's picks under their field names.
  const download = page.waitForEvent("download");
  await page.click("#download-latest");
  const file = await download;
  expect(file.suggestedFilename()).toBe(`latest-picks-${reply.day}.csv`);
  expect(readFileSync(await file.path(), "utf8")).toBe(toCsv(reply.picks.map(({ steps: _steps, ...rest }) => rest)));
});

test("each pick shows the value it was ranked on, in the display of its Rank", async ({ page, home }) => {
  const rank = { rank: "EV/EBITDA", order: "lowest", from: 1, to: 50 } as const;
  const body: ScreenBody = { ...DEFAULT, strategy: { sleeves: [{ steps: [...DEFAULT.strategy.sleeves[0]!.steps.slice(0, 2), rank] }] } };
  const reply = await home.api<ScreenReply>("POST", "/api/screen", body);
  expect(reply.picks.length).toBeGreaterThan(1);
  expect(reply.description.sleeves[0]!.steps[2]!.display).toBe("multiple");

  const draft = defaultDraft();
  draft.sleeves[0]!.steps[2] = { ...rank, id: draft.sleeves[0]!.steps[2]!.id };
  await page.addInitScript((text) => localStorage.setItem("stock-backtest-draft", text), JSON.stringify(draft));
  await page.goto("/");

  const rows = page.locator("#latest-body tr");
  await expect(rows).toHaveCount(reply.picks.length);
  await expect(page.locator("#latest-view thead th").nth(3)).toHaveText("Ranking value · lowest");
  await expect.poll(() => rows.locator("td:nth-child(2)").allInnerTexts()).toEqual(reply.picks.map((pick) => pick.symbol));
  await expect.poll(() => rows.locator("td:nth-child(4)").allInnerTexts()).toEqual(reply.picks.map((pick) => format(pick.ranking_value, "multiple")));
});

test("picks that do not match the settings say so until Screen latest", async ({ page, home }) => {
  await page.goto("/");
  await expect(page.locator("#latest-body tr").first().locator("td").first()).toHaveText("1");
  await page.click("#auto-run");
  await page.fill("#step-rank_to-3", "2");
  await expect(page.locator("#results-state")).toContainText("Settings changed — displayed results do not match the current settings.");
  await expect(page.locator("#latest-view")).toHaveAttribute("data-results-stale", "true");

  const reply = await home.api<ScreenReply>("POST", "/api/screen", {
    ...DEFAULT,
    strategy: { sleeves: [{ steps: [...DEFAULT.strategy.sleeves[0]!.steps.slice(0, 2), { rank: "EBITDA yield", order: "highest", from: 1, to: 2 }] }] },
  });
  await page.click("#run-screen");
  await expect(page.locator("#latest-body tr")).toHaveCount(reply.picks.length);
  await expect(page.locator("#results-state")).toHaveText("");
  await expect(page.locator("#latest-view")).toHaveAttribute("data-results-stale", "false");
  await expect(page.locator("#range-note")).toContainText(`Ranks 1–2, equal weight.`);

  // A refused screen keeps the picks and says where the fault is.
  await page.fill("#step-value-1", "");
  await page.click("#run-screen");
  await expect(page.locator("#screen-error")).toContainText(/^Sleeve 1, step 1: .* The previous result remains displayed\.$/);
  await expect(page.locator("#latest-body tr")).toHaveCount(reply.picks.length);
});

test("Screen latest is not blocked by a date control of Historical backtest", async ({ page }) => {
  await page.goto("/");
  await page.click("#auto-run");
  await page.click("#mode-backtest");
  await page.check("#calendar-custom");
  await page.selectOption("#calendar-unit", "month");
  await page.fill("#calendar-count", "30");
  await page.click("#mode-latest");
  const request = page.waitForRequest((request) => request.url().endsWith("/api/screen"));
  await page.click("#run-screen");
  await request;
  await expect(page.locator("#latest-body tr").first().locator("td").first()).toHaveText("1");
});
