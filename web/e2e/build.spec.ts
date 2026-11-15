import type { Locator, Page } from "@playwright/test";
import type { AddRun } from "../src/api/AddRun.ts";
import type { RunRow } from "../src/api/RunRow.ts";
import type { RunsReply } from "../src/api/RunsReply.ts";
import type { StatusReply } from "../src/api/StatusReply.ts";
import type { StrategyFile } from "../src/api/StrategyFile.ts";
import { canonical, expect, test } from "./fixture.ts";

/** A row of the queue panel by the run's name, with its Details open. */
async function queueRow(page: Page, name: string): Promise<Locator> {
  const row = page.locator("#queue-list > li").filter({ has: page.locator(".run-name", { hasText: name }) });
  if (!(await row.locator("details").evaluate((details) => (details as HTMLDetailsElement).open))) await row.locator("summary").click();
  return row;
}

/** The values of the fields a locator finds, in page order. */
const values = (fields: Locator) => fields.evaluateAll((elements) => elements.map((element) => (element as HTMLInputElement).value));

const named = async (api: <T>(method: string, path: string) => Promise<T>, name: string) => {
  const list = await api<RunsReply>("GET", "/api/runs");
  const row = list.runs.find((run) => run.name === name);
  if (!row) throw new Error(`no run named ${name}`);
  return api<RunRow>("GET", `/api/runs/${row.id}`);
};

test.beforeAll(({ home }) => home.reset());

test.beforeEach(async ({ home }) => {
  // Runs added here wait, so that nothing runs beside the checks.
  await home.api("PUT", "/api/queue", { paused: true });
});

/** Counts the animations the page starts (`Element.animate`): an animation
 *  that ends before a check looks for it (the longest lasts 700 ms) is still
 *  counted, and a page that starts none shows 0 for as long as the check
 *  waits. Install it before the action. */
const countAnimations = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { started?: number };
    if (w.started === undefined) {
      const animate = Element.prototype.animate;
      Element.prototype.animate = function (...args) {
        w.started = (w.started ?? 0) + 1;
        return animate.apply(this, args);
      };
    }
    w.started = 0;
  });
const animationsStarted = (page: Page) => page.evaluate(() => (window as unknown as { started: number }).started);

test("two sleeves are built in the page, and Add to queue stores what bt check prints", async ({ page, home }) => {
  await home.api("POST", "/api/variables", { name: "Cheap", formula: "1 / P/E", display: "percent", favourite: true });
  const status = await home.api<StatusReply>("GET", "/api/data/status");
  await page.goto("/");
  await page.click("#mode-backtest");

  await page.click("#sleeve-copy");
  await expect(page.locator("#sleeve-tabs button")).toHaveText(["Sleeve 1", "Sleeve 2"]);
  await expect(page.locator('#sleeve-tabs button[aria-pressed="true"]')).toHaveText("Sleeve 2");

  // A filter goes before the last Rank; the keyboard takes the best match.
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

  // A Rank goes last; My variables lists the library's favourites marked ★.
  await page.click("#add-rank");
  await expect(page.locator("#filter-search-new")).toBeFocused();
  await page.keyboard.type("cheap");
  const cheap = page.locator('#filter-options-new [role=group][aria-label="My variables"] [role=option]');
  await expect(cheap).toHaveText(["★ CheapSaved variable"]);
  await cheap.dispatchEvent("mousedown");
  // The new step is drawn before its controls are the last ones.
  await expect(page.locator("#strategy-steps .step-name")).toHaveText(["Step 1 · Filter", "Step 2 · Filter", "Step 3 · Filter", "Step 4 · Rank", "Step 5 · Rank"]);
  await page.locator("#strategy-steps select[id^=step-direction]").last().selectOption("lowest");
  await page.locator("#strategy-steps input[id^=step-rank_to]").last().fill("3");

  await page.locator("#sleeve-tabs button").first().click();
  await expect(page.locator('#sleeve-tabs button[aria-pressed="true"]')).toHaveText("Sleeve 1");
  await page.fill("#sleeve-name", "Value");
  await expect(page.locator("#strategy-heading")).toHaveText("Sleeves Value + Technology");
  await page.fill("#queue-name", "Two sleeves");
  await page.click("#queue-add");
  await expect(page.locator("#queue-add-status")).toHaveText("Test added to the queue. You can change the settings and add another.");
  await expect(page.locator("#queue-name")).toHaveValue("");

  const built: StrategyFile = {
    variables: { Cheap: { formula: "1 / P/E", display: "percent" } },
    sleeves: [
      {
        name: "Value",
        steps: [
          { filter: "Market cap", op: ">=", value: "100" },
          { filter: "Enterprise value", op: ">=", value: "50" },
          { rank: "EBITDA yield", order: "highest", from: 1, to: 50 },
        ],
      },
      {
        name: "Technology",
        steps: [
          { filter: "Market cap", op: ">=", value: "100" },
          { filter: "Enterprise value", op: ">=", value: "50" },
          { filter: "Sector", op: "is", value: "Technology" },
          { rank: "EBITDA yield", order: "highest", from: 1, to: 50 },
          { rank: "Cheap", order: "lowest", from: 1, to: 3 },
        ],
      },
    ],
  };
  const run = await named(home.api, "Two sleeves");
  expect(run.strategy).toEqual(canonical(built));
  const last = status.markets.find((market) => market.market === "us")!.prepared!.last_session;
  expect(run.schedule).toMatchObject({ start: status.markets.find((market) => market.market === "us")!.prepared!.first_session, end: last, every: "12m", trials: 24 });
  expect(run.market).toBe("us");
});

test("the picker reopens with the keyboard, and a refusal shows under the button with its place in words", async ({ page }) => {
  await page.goto("/");
  await page.click("#mode-backtest");
  // Escape closes the list and ArrowDown opens it again; a choice on a row
  // moves focus to that step's value.
  const source = page.locator("#filter-search-2");
  await source.focus();
  await expect(source).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(source).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("ArrowDown");
  await expect(source).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#filter-options-2 [role=group]").first()).toHaveAttribute("aria-label", "Size and listing");
  await expect(page.locator("#filter-options-2 [role=group]").first().locator("[role=option]")).toHaveText([
    "Market cap in dollars",
    "Enterprise value in dollars",
    "Sector",
    "Exchange",
  ]);
  await page.keyboard.type("market cap in");
  await page.keyboard.press("Enter");
  await expect(source).toHaveValue("Market cap in dollars");
  await expect(page.locator("#step-value-2")).toBeFocused();
  await page.click("#add-filter");
  await expect(page.locator("#filter-search-new")).toBeFocused();
  await page.keyboard.type("P/E");
  await expect(page.locator("#filter-options-new [role=option]").first()).toHaveText("P/E");
  await page.keyboard.press("Enter");
  await page.click("#queue-add");
  await expect(page.locator("#queue-add-status")).toHaveClass("backtest-failed");
  await expect(page.locator("#queue-add-status")).toContainText(/^Sleeve 1, step 3: /);
  await expect(page.locator("#queue-add")).toBeEnabled();
});

test("moving a step slides the rows, and nothing moves under reduced motion", async ({ page }) => {
  await page.goto("/");
  const sources = page.locator("#strategy-steps [role=combobox]");
  await expect.poll(() => values(sources)).toEqual(["Market cap", "Enterprise value", "EBITDA yield"]);
  await countAnimations(page);
  await page.click("#step-up-3");
  await expect.poll(() => values(sources)).toEqual(["Market cap", "EBITDA yield", "Enterprise value"]);
  expect(await animationsStarted(page)).toBeGreaterThan(0);
  await expect(page.locator("#step-up-3")).toBeFocused();

  await page.emulateMedia({ reducedMotion: "reduce" });
  await countAnimations(page);
  await page.click("#step-up-3");
  await expect.poll(() => values(sources)).toEqual(["EBITDA yield", "Market cap", "Enterprise value"]);
  expect(await animationsStarted(page)).toBe(0);
  // At the top, Up is disabled, so focus moves to Down.
  await expect(page.locator("#step-down-3")).toBeFocused();
  await page.click("#step-remove-3");
  await expect.poll(() => values(sources)).toEqual(["Market cap", "Enterprise value"]);
  expect(await animationsStarted(page)).toBe(0);
});

test("a reload keeps the draft, and Reset strategy brings back the default steps", async ({ page }) => {
  await page.goto("/");
  await page.click("#mode-backtest");
  await page.fill("#step-value-1", "250");
  await page.click("#sleeve-copy");
  await page.locator("#sleeve-tabs button").first().click();
  await page.selectOption("#date-testing", "single");
  await page.selectOption("#rebalance-months", "3");
  await page.fill("#queue-name", "Kept");
  // Numbers the draft cannot hold are not taken: a negative interval count, a
  // fractional rank. A typed start stays as typed.
  await page.check("#calendar-custom");
  await page.fill("#calendar-count", "-1");
  await page.fill("#step-rank_to-3", "2.5");
  await page.focus("#trade-start");
  await page.keyboard.type("03152019");
  await expect(page.locator("#trade-start")).toHaveValue("2019-03-15");
  await expect(page.locator("#strategy-heading")).toHaveText("Sleeves Sleeve 1 + Sleeve 2");
  await page.reload();

  await expect(page.locator("#mode-backtest")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#sleeve-tabs button")).toHaveText(["Sleeve 1", "Sleeve 2"]);
  await expect(page.locator("#step-value-1")).toHaveValue("250");
  await expect(page.locator("#date-testing")).toHaveValue("single");
  await expect(page.locator("#rebalance-months")).toHaveValue("3");
  await expect(page.locator("#queue-name")).toHaveValue("Kept");
  await expect(page.locator("#calendar-count")).toHaveValue("1");
  await expect(page.locator("#step-rank_to-3")).toHaveValue("50");
  await expect(page.locator("#trade-start")).toHaveValue("2019-03-15");

  await page.click("#reset-strategy");
  await expect(page.locator("#sleeve-tabs button")).toHaveText(["Sleeve 1"]);
  await expect(page.locator("#step-value-1")).toHaveValue("100");
  await expect(page.locator("#queue-name")).toHaveValue("Kept");
  await expect(page.locator("#date-testing")).toHaveValue("single");

  // A stored draft that does not read gives the default.
  await page.evaluate(() => localStorage.setItem("stock-backtest-draft", '{"mode":"backtest"}'));
  await page.reload();
  await expect(page.locator("#mode-latest")).toHaveAttribute("aria-pressed", "true");
});

test("Edit settings of a waiting run saves through Save changes or ends with Cancel edit, and the live draft stays", async ({ page, home }) => {
  const strategy = { sleeves: [{ steps: [{ filter: "P/E", op: "<", value: "30" }, { rank: "ROE", order: "highest", from: 1, to: 5 }] }] } satisfies StrategyFile;
  const schedule = { start: "2021-07-01", end: "2023-06-28", every: "6m" };
  const added = await home.api<RunRow>("POST", "/api/runs", { name: "Held test", market: "us", schedule, strategy } satisfies AddRun);
  const other = await home.api<RunRow>("POST", "/api/runs", { name: "Other test", market: "us", schedule, strategy } satisfies AddRun);
  const state = async (id: number) => (await home.api<RunRow>("GET", `/api/runs/${id}`)).state;
  const sources = page.locator("#strategy-steps [role=combobox]");

  // Edit settings from the queue tray on Build strategy closes the tray.
  await page.goto("/#/build");
  await page.click("#workspace-queue-open");
  await expect(page.locator("#workspace-queue-tray")).toBeVisible();
  await (await queueRow(page, "Held test")).getByRole("button", { name: "Edit settings" }).click();
  await expect(page.locator("#queue-add")).toHaveText("Save changes");
  await expect(page.locator("#workspace-queue-tray")).toBeHidden();
  await expect(page).toHaveURL(/#\/build$/);
  expect(await state(added.id)).toBe("held");
  await expect(page.locator("#queue-add")).toHaveText("Save changes");
  await expect(page.locator("#queue-cancel-edit")).toBeVisible();
  await expect(page.locator("#queue-edit-note")).toContainText("Editing “Held test”.");
  await expect(page.locator("#queue-name")).toHaveValue("Held test");
  await expect.poll(() => values(sources)).toEqual(["P/E", "ROE"]);
  await expect(page.locator("#date-testing")).toHaveValue("single");
  await expect(page.locator("#rebalance-months")).toHaveValue("6");

  // While the edit is open, Edit settings and Tune of another run are refused:
  // nothing is held, the page stays, and the edit stays. The tray draws its
  // panel anew each time it opens, so each refusal is its own.
  for (const action of ["Edit settings", "Tune"]) {
    await page.click("#workspace-queue-open");
    await expect(page.locator("#queue-status")).not.toHaveText(/Save or cancel/);
    await (await queueRow(page, "Other test")).getByRole("button", { name: action }).click();
    await expect(page.locator("#queue-status")).toHaveText("Save or cancel the queued edit before replacing the strategy settings.");
    await expect(page.locator("#workspace-queue-tray")).toBeVisible();
    await expect(page).toHaveURL(/#\/build$/);
    await page.click("#workspace-queue-close");
  }
  expect(await state(other.id)).toBe("waiting");
  await expect.poll(() => values(sources)).toEqual(["P/E", "ROE"]);

  await page.fill("#step-rank_to-2", "7");
  await page.selectOption("#rebalance-months", "3");
  await page.click("#queue-add");
  await expect(page.locator("#queue-add-status")).toHaveText("Queued test updated. It can run with the new settings.");
  await expect(page.locator("#queue-add")).toHaveText("Add to queue");
  // The live draft, the default, is shown again.
  await expect.poll(() => values(sources)).toEqual(["Market cap", "Enterprise value", "EBITDA yield"]);
  const saved = await home.api<RunRow>("GET", `/api/runs/${added.id}`);
  expect(saved.state).toBe("waiting");
  expect(saved.name).toBe("Held test");
  expect(saved.schedule).toEqual({ ...schedule, every: "3m" });
  expect(saved.strategy).toEqual(canonical({ sleeves: [{ steps: [strategy.sleeves[0]!.steps[0]!, { rank: "ROE", order: "highest", from: 1, to: 7 }] }] }));

  await page.goto("/#/runs");
  await (await queueRow(page, "Held test")).getByRole("button", { name: "Edit settings" }).click();
  await page.fill("#step-rank_to-2", "9");
  // A refused save keeps the edit open.
  await page.fill("#step-value-1", "");
  await page.click("#queue-add");
  await expect(page.locator("#queue-add-status")).toContainText(/^Sleeve 1, step 1: /);
  await expect(page.locator("#queue-add")).toHaveText("Save changes");
  // Cancel edit releases the run and keeps its settings.
  await page.click("#queue-cancel-edit");
  await expect(page.locator("#queue-add-status")).toHaveText("Edit cancelled. Its previous settings are kept.");
  await expect(page.locator("#queue-cancel-edit")).toBeHidden();
  await expect.poll(() => state(added.id)).toBe("waiting");
  expect((await home.api<RunRow>("GET", `/api/runs/${added.id}`)).strategy).toEqual(saved.strategy);
  for (const run of [added, other]) await home.api("DELETE", `/api/runs/${run.id}`);
});

test("Tune puts a run's settings into the live draft without its name, and adding it again stores the same settings", async ({ page, home }) => {
  const strategy: StrategyFile = {
    sleeves: [
      { name: "Land", steps: [{ filter: "Sector", op: "is", value: "Industrials" }, { rank: "EBITDA yield", order: "highest", from: 1, to: 2 }] },
      { name: "Large", steps: [{ rank: "Market cap in dollars", order: "lowest", from: 1, to: 3 }] },
    ],
  };
  const added = await home.api<RunRow>("POST", "/api/runs", { name: "To tune", market: "hk", schedule: { start: "2021-07-01", end: "2023-06-28", every: "2w", trials: 3, seed: 5 }, strategy } satisfies AddRun);
  await page.goto("/#/runs");
  await (await queueRow(page, "To tune")).getByRole("button", { name: "Tune" }).click();
  await expect(page).toHaveURL(/#\/build$/);
  await expect(page.locator("#queue-add-status")).toHaveText("Settings copied to the strategy controls. Change them and add a new test.");
  await expect(page.locator("#mode-backtest")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#stock-market")).toHaveValue("hk");
  await expect(page.locator("#sleeve-tabs button")).toHaveText(["Land", "Large"]);
  await expect(page.locator("#queue-name")).toHaveValue("");
  await expect(page.locator("#calendar-custom")).toBeChecked();
  await expect(page.locator("#calendar-count")).toHaveValue("2");
  await expect(page.locator("#random-trials")).toHaveValue("3");
  await expect(page.locator("#repeat-random")).toBeChecked();
  await expect(page.locator("#random-seed")).toHaveValue("5");

  await page.fill("#queue-name", "Tuned");
  await page.click("#queue-add");
  await expect(page.locator("#queue-add-status")).toHaveText("Test added to the queue. You can change the settings and add another.");
  const tuned = await named(home.api, "Tuned");
  const original = await home.api<RunRow>("GET", `/api/runs/${added.id}`);
  expect(tuned.strategy).toEqual(original.strategy);
  expect(tuned.schedule).toEqual(original.schedule);
});
