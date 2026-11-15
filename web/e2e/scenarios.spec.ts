import type { Page } from "@playwright/test";
import type { RunRow } from "../src/api/RunRow.ts";
import type { RunsReply } from "../src/api/RunsReply.ts";
import type { ScreenBody } from "../src/api/ScreenBody.ts";
import type { ScreenReply } from "../src/api/ScreenReply.ts";
import type { StrategyFile } from "../src/api/StrategyFile.ts";
import { canonical, expect, test } from "./fixture.ts";

// A user's two walks through the pages: the loop of building variants,
// queueing, comparing, opening and tuning, and the latest picks of the same
// strategy. The server is asked only to read back what it stored,
// and to give the numbers that the page shows.

const FORMULA = "Cash and equivalents / Total debt";
const WINDOW = { start: "2021-07-01", end: "2023-06-28" };

test.beforeEach(({ home }) => home.reset());

/** Builds, in the page's controls, the strategy of both walks: the default
 *  sleeve, and a second one that copies it, adds a Sector filter and ranks by
 *  a variable that is made in the formula editor and saved to My variables. */
async function buildStrategy(page: Page, name: string): Promise<void> {
  await page.click("#sleeve-copy");
  await expect(page.locator("#sleeve-tabs button")).toHaveText(["Sleeve 1", "Sleeve 2"]);

  await page.click("#add-filter");
  await expect(page.locator("#filter-search-new")).toBeFocused();
  await page.keyboard.type("sector");
  await expect(page.locator("#filter-options-new [role=option]").first()).toContainText("Sector");
  await page.keyboard.press("Enter");
  await expect(page.locator("#strategy-steps .step-name")).toHaveText(["Step 1 · Filter", "Step 2 · Filter", "Step 3 · Filter", "Step 4 · Rank"]);
  const value = page.locator("#strategy-steps select[id^=step-value]");
  await expect(value).toBeFocused();
  await value.selectOption("Technology");
  await expect(page.locator('#sleeve-tabs button[aria-pressed="true"]')).toHaveText("Technology");

  await page.click("#add-rank");
  await page.click("#filter-search-new");
  await page.locator("#filter-options-new").getByRole("option", { name: /Create a new variable/ }).click();
  await expect(page.locator("#variable-dialog")).toBeVisible();
  await page.locator("#variable-formula").fill(FORMULA);
  await expect(page.locator("#variable-check-text")).toHaveText("✓ Ready · Result: ratio");
  await page.fill("#variable-name", name);
  await page.selectOption("#variable-display", "multiple");
  await page.click("#variable-save");
  await expect(page.locator("#variable-message")).toHaveText(`Saved “${name}” to My variables.`);
  await page.click("#variable-apply");
  await expect(page.locator("#variable-dialog")).toHaveCount(0);
  await expect(page.locator("#strategy-steps .step-name")).toHaveText(["Step 1 · Filter", "Step 2 · Filter", "Step 3 · Filter", "Step 4 · Rank", "Step 5 · Rank"]);
  await page.locator("#strategy-steps select[id^=step-direction]").last().selectOption("lowest");
  await page.locator("#strategy-steps input[id^=step-rank_to]").last().fill("3");
}

/** The strategy that buildStrategy makes, as the strategy file says it. */
const built = (name: string): StrategyFile => {
  const shared = [
    { filter: "Market cap", op: ">=", value: "100" },
    { filter: "Enterprise value", op: ">=", value: "50" },
  ] as const;
  return {
    variables: { [name]: { formula: FORMULA, display: "multiple" } },
    sleeves: [
      { name: "Sleeve 1", steps: [...shared, { rank: "EBITDA yield", order: "highest", from: 1, to: 50 }] },
      {
        name: "Technology",
        steps: [...shared, { filter: "Sector", op: "is", value: "Technology" }, { rank: "EBITDA yield", order: "highest", from: 1, to: 50 }, { rank: name, order: "lowest", from: 1, to: 3 }],
      },
    ],
  };
};

/** Sets the dates of a fixed schedule in the page. */
async function fixedSchedule(page: Page, months: number): Promise<void> {
  await page.fill("#trade-start", WINDOW.start);
  await page.fill("#trade-end", WINDOW.end);
  await page.selectOption("#date-testing", "single");
  await page.selectOption("#rebalance-months", String(months));
}

/** Adds the live draft to the queue under `name`. */
async function queue(page: Page, name: string): Promise<void> {
  await page.fill("#queue-name", name);
  await page.click("#queue-add");
  await expect(page.locator("#queue-add-status")).toHaveText("Test added to the queue. You can change the settings and add another.");
  // The message stays from an earlier add: the page clears the name only once this one is stored.
  await expect(page.locator("#queue-name")).toHaveValue("");
}

const run = async (api: <T>(method: string, path: string) => Promise<T>, name: string): Promise<RunRow> => {
  const list = await api<RunsReply>("GET", "/api/runs");
  const row = list.runs.find((each) => each.name === name);
  if (!row) throw new Error(`no run named ${name}`);
  return api<RunRow>("GET", `/api/runs/${row.id}`);
};

test("two variants are queued and compared, one result is opened and read, and Tune adds the same settings again", async ({ page, context, home }) => {
  const cover = "Cash cover";

  // Variant A: quarterly, on fixed dates. The editor's variable is saved to My variables and used by the second sleeve.
  await page.goto("/");
  await page.click("#mode-backtest");
  await fixedSchedule(page, 3);
  await buildStrategy(page, cover);
  await queue(page, "Cover A");

  // Variant B: the same strategy tried half-yearly, with five stocks in the cover sleeve.
  await page.selectOption("#rebalance-months", "6");
  await page.locator("#strategy-steps input[id^=step-rank_to]").last().fill("5");
  await queue(page, "Cover B");
  expect((await run(home.api, "Cover A")).strategy).toEqual(canonical(built(cover)));

  // Both tests are in the queue; they finish and move to the saved table.
  await page.locator("#workspace-nav >> text=Runs & saved").click();
  await expect(page).toHaveURL(/#\/runs$/);
  await expect(page.locator("#queue-list")).toHaveText("No test is waiting or running. Select Add to queue in Build strategy.", { timeout: 90_000 });
  await expect(page.locator("#saved-list > li")).toHaveCount(2);
  const saved = (name: string) => page.locator("#saved-list > li").filter({ has: page.locator(".run-name", { hasText: new RegExp(`^${name}$`) }) });
  await expect(saved("Cover A").locator(".run-type")).toHaveText("Fixed dates");

  // Compare: the settings that differ come first.
  await page.locator("#saved-sort-name").click();
  await expect(page.locator("#saved-list .run-name")).toHaveText(["Cover A", "Cover B"]);
  await saved("Cover A").getByRole("checkbox").check();
  await saved("Cover B").getByRole("checkbox").check();
  await page.locator("#saved-compare").click();
  const panel = page.locator("#saved-comparison");
  await expect(panel).toBeVisible();
  const table = panel.locator("table").first();
  await expect(table.locator(".comparison-group th")).toHaveText(["Settings that differ", "Headline"]);
  const differing = table.locator("tbody").first().locator("tr th[scope=row]");
  await expect(differing).toHaveText(["Rebalance interval", "Technology · Step 5 · Rank"]);
  // Each variant has its own column, in the table's order (by name).
  const interval = table.locator("tbody").first().locator("tr", { hasText: "Rebalance interval" }).locator("td");
  await expect(interval).toHaveText(["3 months", "6 months"]);
  await page.locator("#saved-compare").click();
  await expect(panel).toBeHidden();

  // Open one result by its row, and again by its address.
  await saved("Cover A").locator(".run-name").click();
  await expect(page).toHaveURL(/#\/results\/\d+$/);
  const address = page.url();
  await expect(page.locator("#workspace-result-title")).toHaveText("Cover A");
  await expect(page.locator("#workspace-result-window")).toHaveText(`${WINDOW.start} → ${WINDOW.end} · Fixed schedule`);
  await expect(page.locator("#workspace-headline dd").first()).toHaveText(/%$/);
  const headline = (await page.locator("#workspace-headline").textContent())!;
  const second = await context.newPage();
  await second.goto(address);
  await expect(second.locator("#workspace-result-title")).toHaveText("Cover A");
  await expect(second.locator("#workspace-headline")).toHaveText(headline);
  await second.close();

  // Returns: a holding's step trail names its sleeve, then each step it passed, and the rank it won.
  await page.locator("#workspace-review-tabs >> text=Returns").click();
  const holding = page.locator("#schedule-stock-body tr").first();
  await holding.locator("summary").click();
  const trail = holding.locator(".step-trail").first().locator("li");
  await expect(trail.first()).toHaveText(/^Step 1 · Filter · Market cap · .+ · passed$/);
  await expect(trail.last()).toHaveText(/^Step \d · Rank · .+ · rank \d+ \(kept 1–\d+\)$/);

  // Tune this strategy: Build strategy has the sleeves and the dates, and adding it again stores what the first time did.
  await page.locator("#workspace-edit-copy").click();
  await expect(page).toHaveURL(/#\/build$/);
  await expect(page.locator("#mode-backtest")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#sleeve-tabs button")).toHaveText(["Sleeve 1", "Technology"]);
  await expect(page.locator("#rebalance-months")).toHaveValue("3");
  await expect(page.locator("#queue-name")).toHaveValue("");
  await queue(page, "Cover A again");
  const first = await run(home.api, "Cover A");
  const again = await run(home.api, "Cover A again");
  expect(again.strategy).toEqual(first.strategy);
  expect(again.schedule).toEqual(first.schedule);
  expect(again.market).toBe(first.market);
});

test("the latest picks of the same strategy are the picks of the server's screen", async ({ page, home }) => {
  const cover = "Cash cover";
  await page.goto("/");
  await expect(page.locator("#mode-latest")).toHaveAttribute("aria-pressed", "true");
  // The screen runs once the strategy is built, not after each change.
  await page.click("#auto-run");
  await buildStrategy(page, cover);
  const request = page.waitForRequest((each) => each.url().endsWith("/api/screen") && each.method() === "POST");
  await page.click("#run-screen");
  const body = (await request).postDataJSON() as ScreenBody;
  expect(canonical(body.strategy)).toEqual(canonical(built(cover)));

  const reply = await home.api<ScreenReply>("POST", "/api/screen", body);
  expect(reply.picks.length).toBeGreaterThan(1);
  const rows = page.locator("#latest-body tr");
  await expect(rows).toHaveCount(reply.picks.length);
  await expect(page.locator("#latest-date")).toHaveText(reply.day);
  await expect(page.locator("#latest-count")).toHaveText(String(reply.picks.length));
  await expect(page.locator("#results-state")).toHaveText("");
  await expect.poll(() => rows.locator("td:nth-child(2)").allInnerTexts()).toEqual(reply.picks.map((pick) => pick.symbol));
  await expect.poll(() => rows.locator("td:nth-child(1)").allInnerTexts()).toEqual(reply.picks.map((pick) => String(pick.rank)));
});
