import type { Locator, Page } from "@playwright/test";
import { build } from "esbuild";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { AddRun } from "../src/api/AddRun.ts";
import type { RunRow } from "../src/api/RunRow.ts";
import type { RunsReply } from "../src/api/RunsReply.ts";
import type { StatusReply } from "../src/api/StatusReply.ts";
import type { StrategyFile } from "../src/api/StrategyFile.ts";
import { expect, test } from "./fixture.ts";

const web = new URL("..", import.meta.url).pathname;
const BT = join(web, "../target/debug/bt");

/** The canonical form that `bt check` prints for a strategy file. */
function canonical(strategy: StrategyFile): StrategyFile {
  const dir = mkdtempSync(join(tmpdir(), "bt-check-"));
  try {
    writeFileSync(join(dir, "strategy.json"), JSON.stringify(strategy));
    const reply = JSON.parse(execFileSync(BT, ["check", join(dir, "strategy.json")], { encoding: "utf8" })) as { files: { canonical: string }[] };
    return JSON.parse(reply.files[0]!.canonical) as StrategyFile;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

/** The site's script with Build strategy's tune, editHeld and heldEditOpen on
 *  `globalThis`,
 *  which the other workspaces call; it stands in for main.js. */
let exposed: Promise<string> | undefined;
async function withLoaders(page: Page): Promise<void> {
  exposed ??= build({
    stdin: { contents: 'import "./src/main.tsx"; import { editHeld, heldEditOpen, tune } from "./src/build/Build.tsx"; Object.assign(globalThis, { editHeld, heldEditOpen, tune });', resolveDir: web, loader: "ts" },
    bundle: true,
    format: "esm",
    jsx: "automatic",
    jsxImportSource: "preact",
    outdir: join(tmpdir(), "unused"),
    write: false,
    logLevel: "warning",
  }).then((result) => result.outputFiles.find((file) => file.path.endsWith(".js"))!.text);
  const body = await exposed;
  await page.route("**/main.js", (route) => route.fulfill({ body, contentType: "text/javascript" }));
}

/** The values of the fields a locator finds, in page order. */
const values = (fields: Locator) => fields.evaluateAll((elements) => elements.map((element) => (element as HTMLInputElement).value));

const named = async (api: <T>(method: string, path: string) => Promise<T>, name: string) => {
  const list = await api<RunsReply>("GET", "/api/runs");
  const row = list.runs.find((run) => run.name === name);
  if (!row) throw new Error(`no run named ${name}`);
  return api<RunRow>("GET", `/api/runs/${row.id}`);
};

test.beforeEach(async ({ home }) => {
  // Runs added here wait, so that nothing runs beside the checks.
  await home.api("PUT", "/api/queue", { paused: true });
});

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
  await page.keyboard.press("Enter");
  await expect(page.locator("#strategy-steps .step-name")).toHaveText(["Step 1 · Filter", "Step 2 · Filter", "Step 3 · Filter", "Step 4 · Rank"]);
  const value = page.locator("#strategy-steps select[id^=step-value]");
  await expect(value).toBeFocused();
  await value.selectOption("Technology");
  await expect(page.locator('#sleeve-tabs button[aria-pressed="true"]')).toHaveText("Technology");

  // A Rank goes last; My variables lists the library's favourites marked ★.
  await page.click("#add-rank");
  await page.keyboard.type("cheap");
  const cheap = page.locator('#filter-options-new [role=group][aria-label="My variables"] [role=option]');
  await expect(cheap).toHaveText(["★ CheapSaved variable"]);
  await cheap.dispatchEvent("mousedown");
  await page.locator("#strategy-steps select[id^=step-direction]").last().selectOption("lowest");
  await page.locator("#strategy-steps input[id^=step-rank_to]").last().fill("3");

  await page.locator("#sleeve-tabs button").first().click();
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
  await page.click("#step-up-3");
  await expect.poll(() => values(sources)).toEqual(["Market cap", "EBITDA yield", "Enterprise value"]);
  expect(await page.evaluate(() => document.getAnimations().length)).toBeGreaterThan(0);
  await expect(page.locator("#step-up-3")).toBeFocused();

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.evaluate(() => document.getAnimations().forEach((animation) => animation.finish()));
  await page.click("#step-up-3");
  await expect.poll(() => values(sources)).toEqual(["EBITDA yield", "Market cap", "Enterprise value"]);
  expect(await page.evaluate(() => document.getAnimations().length)).toBe(0);
  // At the top, Up is disabled, so focus moves to Down.
  await expect(page.locator("#step-down-3")).toBeFocused();
  await page.click("#step-remove-3");
  await expect.poll(() => values(sources)).toEqual(["Market cap", "Enterprise value"]);
  expect(await page.evaluate(() => document.getAnimations().length)).toBe(0);
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

test("a held run's settings are edited and saved, or the edit is cancelled, and the live draft stays", async ({ page, home }) => {
  await withLoaders(page);
  const strategy = { sleeves: [{ steps: [{ filter: "P/E", op: "<", value: "30" }, { rank: "ROE", order: "highest", from: 1, to: 5 }] }] } satisfies StrategyFile;
  const added = await home.api<RunRow>("POST", "/api/runs", {
    name: "Held test",
    market: "us",
    schedule: { start: "2021-07-01", end: "2023-06-28", every: "6m" },
    strategy,
  } satisfies AddRun);
  const hold = async () => {
    await home.api("POST", `/api/runs/${added.id}/hold`);
    return home.api<RunRow>("GET", `/api/runs/${added.id}`);
  };
  type Loaders = { editHeld: (run: RunRow) => void; tune: (run: RunRow) => void; heldEditOpen: () => boolean };
  const open = () => page.evaluate(() => (globalThis as unknown as Loaders).heldEditOpen());

  await page.goto("/#/runs");
  await page.evaluate((run) => (globalThis as unknown as { editHeld: (run: RunRow) => void }).editHeld(run), await hold());
  await expect(page).toHaveURL(/#\/build$/);
  await expect(page.locator("#queue-add")).toHaveText("Save changes");
  await expect(page.locator("#queue-cancel-edit")).toBeVisible();
  await expect(page.locator("#queue-edit-note")).toContainText("Editing “Held test”.");
  await expect(page.locator("#queue-name")).toHaveValue("Held test");
  await expect.poll(() => values(page.locator("#strategy-steps [role=combobox]"))).toEqual(["P/E", "ROE"]);
  await expect(page.locator("#date-testing")).toHaveValue("single");
  await expect(page.locator("#rebalance-months")).toHaveValue("6");
  expect(await open()).toBe(true);

  // While the edit is open, another edit and Tune are refused, and the edit stays.
  for (const load of ["editHeld", "tune"] as const) {
    await page.evaluate(([run, load]) => (globalThis as unknown as Loaders)[load](run), [added, load] as const);
    await expect(page.locator("#queue-add-status")).toHaveText("Save or cancel the queued edit before replacing the strategy settings.");
    await expect.poll(() => values(page.locator("#strategy-steps [role=combobox]"))).toEqual(["P/E", "ROE"]);
  }

  await page.fill("#step-rank_to-2", "7");
  await page.selectOption("#rebalance-months", "3");
  await page.click("#queue-add");
  await expect(page.locator("#queue-add-status")).toHaveText("Queued test updated. It can run with the new settings.");
  await expect(page.locator("#queue-add")).toHaveText("Add to queue");
  expect(await open()).toBe(false);
  // The live draft, the default, is shown again.
  await expect.poll(() => values(page.locator("#strategy-steps [role=combobox]"))).toEqual(["Market cap", "Enterprise value", "EBITDA yield"]);
  await expect.poll(async () => (await home.api<RunRow>("GET", `/api/runs/${added.id}`)).state).toBe("waiting");
  const saved = await home.api<RunRow>("GET", `/api/runs/${added.id}`);
  expect(saved.name).toBe("Held test");
  expect(saved.schedule).toEqual({ start: "2021-07-01", end: "2023-06-28", every: "3m" });
  expect(saved.strategy).toEqual(canonical({ sleeves: [{ steps: [strategy.sleeves[0]!.steps[0]!, { rank: "ROE", order: "highest", from: 1, to: 7 }] }] }));

  await page.evaluate((run) => (globalThis as unknown as { editHeld: (run: RunRow) => void }).editHeld(run), await hold());
  await page.fill("#step-rank_to-2", "9");
  // A refused save keeps the edit open.
  await page.fill("#step-value-1", "");
  await page.click("#queue-add");
  await expect(page.locator("#queue-add-status")).toContainText(/^Sleeve 1, step 1: /);
  await expect(page.locator("#queue-add")).toHaveText("Save changes");
  // Cancel edit ends the edit even when the release is refused.
  await home.api("POST", `/api/runs/${added.id}/release`);
  await page.click("#queue-cancel-edit");
  await expect(page.locator("#queue-add-status")).toHaveText("Edit cancelled. Its previous settings are kept.");
  await expect(page.locator("#queue-cancel-edit")).toBeHidden();
  const kept = await home.api<RunRow>("GET", `/api/runs/${added.id}`);
  expect(kept.state).toBe("waiting");
  expect(kept.strategy).toEqual(saved.strategy);
  await home.api("DELETE", `/api/runs/${added.id}`);
});

test("Tune puts a run's settings into the live draft without its name", async ({ page, home }) => {
  await withLoaders(page);
  const strategy: StrategyFile = {
    sleeves: [
      { name: "Land", steps: [{ filter: "Sector", op: "is", value: "Industrials" }, { rank: "EBITDA yield", order: "highest", from: 1, to: 2 }] },
      { name: "Large", steps: [{ rank: "Market cap in dollars", order: "lowest", from: 1, to: 3 }] },
    ],
  };
  const added = await home.api<RunRow>("POST", "/api/runs", { name: "To tune", market: "hk", schedule: { start: "2021-07-01", end: "2023-06-28", every: "2w", trials: 3, seed: 5 }, strategy } satisfies AddRun);
  await page.goto("/#/runs");
  await page.evaluate((run) => (globalThis as unknown as { tune: (run: RunRow) => void }).tune(run), await home.api<RunRow>("GET", `/api/runs/${added.id}`));
  await expect(page).toHaveURL(/#\/build$/);
  await expect(page.locator("#mode-backtest")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#stock-market")).toHaveValue("hk");
  await expect(page.locator("#sleeve-tabs button")).toHaveText(["Land", "Large"]);
  await expect(page.locator("#queue-name")).toHaveValue("");
  await expect(page.locator("#calendar-custom")).toBeChecked();
  await expect(page.locator("#calendar-count")).toHaveValue("2");
  await expect(page.locator("#random-trials")).toHaveValue("3");
  await expect(page.locator("#repeat-random")).toBeChecked();
  await expect(page.locator("#random-seed")).toHaveValue("5");

  // Adding it again stores the same canonical form.
  await page.fill("#queue-name", "Tuned");
  await page.click("#queue-add");
  await expect(page.locator("#queue-add-status")).toHaveText("Test added to the queue. You can change the settings and add another.");
  const tuned = await named(home.api, "Tuned");
  const original = await home.api<RunRow>("GET", `/api/runs/${added.id}`);
  expect(tuned.strategy).toEqual(original.strategy);
  expect(tuned.schedule).toEqual(original.schedule);
});
