import type { Page } from "@playwright/test";
import type { RunRow } from "../src/api/RunRow.ts";
import type { RunsReply } from "../src/api/RunsReply.ts";
import type { Variable } from "../src/api/Variable.ts";
import { type Draft, defaultDraft } from "../src/draft.ts";
import { expect as base, test } from "./fixture.ts";

// A slow machine delays the server's checks and replies: wait longer than the default.
const expect = base.configure({ timeout: 15_000 });

// The library belongs to the worker's home, so each check uses names of its own.
let count = 0;
const unique = (name: string) => `${name} ${process.pid} ${++count}`;

/** Opens the formula editor from the picker of a new step. */
async function createVariable(page: Page, kind: "filter" | "rank"): Promise<void> {
  await page.click(kind === "filter" ? "#add-filter" : "#add-rank");
  await page.click("#filter-search-new");
  await page.locator("#filter-options-new").getByRole("option", { name: /Create a new variable/ }).click();
  await expect(page.locator("#variable-dialog")).toBeVisible();
}

/** Makes step `id` read `name`, chosen from its picker. */
async function chooseSource(page: Page, id: number, name: string): Promise<void> {
  await page.click(`#filter-search-${id}`);
  await page.locator(`#filter-options-${id} [role=option]`).filter({ has: page.getByText(name, { exact: true }) }).click();
  await expect(page.locator(`#filter-search-${id}`)).toHaveValue(name);
}

/** Starts the page with a stored draft: the default one in Historical
 *  backtest, so that no change starts a screen, then changed. */
async function startWith(page: Page, change: (draft: Draft) => void = () => {}): Promise<void> {
  const draft = defaultDraft();
  draft.mode = "backtest";
  draft.schedule.start = "2018-01-02";
  change(draft);
  await page.addInitScript((text) => localStorage.setItem("stock-backtest-draft", text), JSON.stringify(draft));
  await page.goto("/#/build");
}

/** Adds the draft to the queue as a dated test named `name`; gives the run. */
async function addToQueue(page: Page, api: <T>(method: string, path: string) => Promise<T>, name: string): Promise<RunRow> {
  await page.click("#mode-backtest");
  await page.fill("#queue-name", name);
  await page.click("#queue-add");
  await expect(page.locator("#queue-add-status")).toContainText("Test added to the queue.", { timeout: 30_000 });
  const list = await api<RunsReply>("GET", "/api/runs");
  return api<RunRow>("GET", `/api/runs/${list.runs.find((row) => row.name === name)!.id}`);
}

test.beforeEach(async ({ home }) => {
  // Runs added here wait, so that nothing runs beside the checks.
  await home.api("PUT", "/api/queue", { paused: true });
});

test("a typo gives the server's suggestions, and applying one gives the picture", async ({ page }) => {
  await startWith(page);
  await createVariable(page, "filter");
  await expect(page.locator("#variable-dialog-title")).toHaveText("New filter");
  await expect(page.locator("#variable-apply")).toHaveText("Add as filter");
  await expect(page.locator("#variable-check-text")).toHaveText("Type a formula");
  await expect(page.locator("#variable-formula")).toBeFocused();

  await page.locator("#variable-formula").fill("Cash and equivalents / Totl debt");
  // Leaving the field hides the typing list ("debt" begins Total debt), which lies over the check line.
  await page.locator("#variable-formula").blur();
  await expect(page.locator("#variable-check")).toHaveAttribute("data-state", "error");
  await expect(page.locator("#variable-check-text")).toContainText("“Totl debt” is not a known name");
  await expect(page.locator("#variable-fixes button")).toHaveText(["Total debt", "Net debt", "Total assets"]);
  await expect(page.locator("#variable-picture")).toBeEmpty();

  await page.locator("#variable-fixes").getByRole("button", { name: "Total debt" }).click();
  await expect(page.locator("#variable-formula")).toHaveValue("Cash and equivalents / Total debt");
  await expect(page.locator("#variable-check-text")).toHaveText("✓ Ready · Result: ratio");
  await expect(page.locator("#variable-picture .variable-picture-fraction > span")).toHaveText(["Cash and equivalents", "Total debt"]);
  await expect(page.locator("#variable-display")).toHaveValue("percent");
});

test("a saved entry is listed under My variables, favourites first, and a step that uses it goes to the queue with it", async ({ page, home }) => {
  const plain = unique("Plain");
  await home.api<Variable>("POST", "/api/variables", { name: plain, formula: "ROE", favourite: false });
  const cover = unique("Cash cover");
  await startWith(page);
  await createVariable(page, "rank");
  await page.locator("#variable-formula").fill("Cash and equivalents / Total debt");
  await expect(page.locator("#variable-check")).toHaveAttribute("data-state", "ready");
  await page.fill("#variable-name", cover);
  await page.selectOption("#variable-display", "multiple");
  await page.click("#variable-save");
  await expect(page.locator("#variable-message")).toHaveText(`Saved “${cover}” to My variables.`);
  await expect(page.locator("#variable-save")).toHaveText("Save changes");
  await page.click("#variable-favourite");
  await expect(page.locator("#variable-favourite")).toHaveText("★ Favourite");
  await expect(page.locator("#variable-message")).toHaveText("Added to favourites.");

  await page.click("#variable-apply");
  await expect(page.locator("#variable-dialog")).toHaveCount(0);
  await expect(page.locator("#filter-search-4")).toHaveValue(cover);
  await expect(page.locator("#step-edit-4")).toBeVisible();

  await page.click("#filter-search-1");
  const mine = page.locator('#filter-options-1 [role=group][aria-label="My variables"] [role=option] > span');
  const names = await mine.allTextContents();
  const starred = names.filter((name) => name.startsWith("★ "));
  expect(starred).toContain(`★ ${cover}`);
  expect(names.slice(0, starred.length)).toEqual(starred);
  expect(names.slice(starred.length)).toContain(plain);
  await page.keyboard.press("Escape");

  const run = await addToQueue(page, home.api, unique("Queued cover"));
  expect(run.strategy!.variables).toEqual({ [cover]: { formula: "Cash and equivalents / Total debt", display: "multiple" } });
  expect(run.strategy!.sleeves[0]!.steps.at(-1)).toEqual({ rank: cover, order: "highest", from: 1, to: 50 });
});

test("Edit formula opens a library entry, whose check leaves out the entries that use it, and Delete shows the server's refusal", async ({ page, home }) => {
  const base = unique("Base");
  const double = unique("Double");
  await home.api<Variable>("POST", "/api/variables", { name: base, formula: "ROE", favourite: false });
  await home.api<Variable>("POST", "/api/variables", { name: double, formula: `[${base}] * 2`, favourite: false });
  await startWith(page);
  await chooseSource(page, 1, base);
  await expect(page.locator("#step-edit-2")).toHaveCount(0);

  await page.click("#step-edit-1");
  await expect(page.locator("#variable-dialog-title")).toHaveText("Step 1 · Filter");
  await expect(page.locator("#variable-apply")).toHaveText("Update step 1");
  await expect(page.locator("#variable-formula")).toHaveValue("ROE");
  await expect(page.locator("#variable-name")).toHaveValue(base);
  await expect(page.locator("#variable-check-text")).toHaveText("✓ Ready · Result: ratio");

  // While Base is edited, Double (which uses it) is not a name the formula can read.
  await page.locator("#variable-formula").fill(`[${double}] + 1`);
  await expect(page.locator("#variable-check-text")).toContainText("is not a known name");

  await page.click("#variable-delete");
  await expect(page.locator("#variable-message")).toHaveText(`${double} uses "${base}": change it first`);
  await expect(page.locator("#variable-message")).toHaveClass("backtest-failed");

  // Close discards the edit: the step still reads the entry.
  await page.click("#variable-close");
  await expect(page.locator("#variable-dialog")).toHaveCount(0);
  await expect(page.locator("#filter-search-1")).toHaveValue(base);
});

test("Use puts typed formula text in the step, and Edit formula opens it again", async ({ page }) => {
  await startWith(page);
  await page.click("#filter-search-1");
  await page.locator("#filter-options-1").getByRole("option", { name: /Create a new variable/ }).click();
  await expect(page.locator("#variable-apply")).toHaveText("Update step 1");
  await page.locator("#variable-formula").fill("ROE*2");
  await expect(page.locator("#variable-check-text")).toHaveText("✓ Ready · Result: ratio");

  // A formula in a step shows in its unit's default display; another needs a saved variable.
  await page.selectOption("#variable-display", "multiple");
  await page.click("#variable-apply");
  await expect(page.locator("#variable-message")).toHaveText("A formula in a step shows as Percent (%). Save it to My variables to show it as Multiple (×).");
  await page.selectOption("#variable-display", "percent");
  await page.click("#variable-apply");
  await expect(page.locator("#variable-dialog")).toHaveCount(0);
  await expect(page.locator("#filter-search-1")).toHaveValue("ROE * 2");

  await page.click("#step-edit-1");
  await expect(page.locator("#variable-formula")).toHaveValue("ROE * 2");
  await expect(page.locator("#variable-name")).toHaveValue("");
  await expect(page.locator("#variable-favourite")).toBeHidden();
  await expect(page.locator("#variable-picture")).toContainText("ROE × 2");
});

test("while typing, a list offers the names the word at the caret begins; Enter inserts one", async ({ page }) => {
  await startWith(page);
  await createVariable(page, "filter");
  const field = page.locator("#variable-formula");
  await field.pressSequentially("Total debt / Enter");
  const list = page.locator("#variable-suggestions");
  await expect(list).toBeVisible();
  await expect(list.locator('[role=option][aria-selected="true"] > span')).toHaveText("Enterprise value");
  await page.keyboard.press("Enter");
  await expect(field).toHaveValue("Total debt / Enterprise value");
  await expect(list).toBeHidden();
  await expect(page.locator("#variable-check-text")).toHaveText("✓ Ready · Result: ratio");

  // Escape hides the list and leaves the window open.
  await field.pressSequentially(" * Net d");
  await expect(list).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(list).toBeHidden();
  await expect(page.locator("#variable-dialog")).toBeVisible();
});

test("a draft's own variable edited and used changes in the draft, so the queued test carries the new formula", async ({ page, home }) => {
  const cheap = unique("Cheap");
  await startWith(page, (draft) => {
    draft.variables = { [cheap]: { formula: "ROE", display: "percent" } };
    draft.sleeves[0]!.steps[0] = { filter: cheap, op: ">", value: "1", id: 1 };
  });
  await page.click("#step-edit-1");
  await expect(page.locator("#variable-name")).toHaveValue(cheap);
  await expect(page.locator("#variable-formula")).toHaveValue("ROE");
  await page.locator("#variable-formula").fill("ROE * 3");
  await expect(page.locator("#variable-check")).toHaveAttribute("data-state", "ready");
  await page.selectOption("#variable-display", "multiple");
  await page.click("#variable-save");
  await expect(page.locator("#variable-message")).toHaveText(`Saved “${cheap}” to My variables.`);
  await expect(page.locator("#variable-save")).toHaveText("Save changes");
  await page.click("#variable-apply");
  await expect(page.locator("#variable-dialog")).toHaveCount(0);
  await expect(page.locator('li[data-row="1"] .condition-unit')).toHaveText("Multiple (×)");

  const run = await addToQueue(page, home.api, unique("Own cheap"));
  expect(run.strategy!.variables).toEqual({ [cheap]: { formula: "ROE * 3", display: "multiple" } });
  const library = await home.api<Variable[]>("GET", "/api/variables");
  expect(library.find((entry) => entry.name === cheap)).toMatchObject({ formula: "ROE * 3", display: "multiple" });
});

test("a deleted library entry stays in the draft as its own copy, with the entries it uses", async ({ page, home }) => {
  const base = unique("Base");
  const gone = unique("Gone");
  await home.api<Variable>("POST", "/api/variables", { name: base, formula: "ROE", favourite: false });
  await home.api<Variable>("POST", "/api/variables", { name: gone, formula: `${base} * 2`, display: "multiple", favourite: false });
  await startWith(page);
  await chooseSource(page, 1, gone);
  await page.click("#step-edit-1");
  await page.click("#variable-delete");
  await expect(page.locator("#variable-message")).toHaveText("Deleted from My variables. Tests already added keep their own copy.");
  await page.click("#variable-close");
  await expect(page.locator("#filter-search-1")).toHaveValue(gone);
  await expect(page.locator('li[data-row="1"] .condition-unit')).toHaveText("Multiple (×)");

  const run = await addToQueue(page, home.api, unique("Kept copy"));
  expect(run.strategy!.variables).toEqual({ [base]: { formula: "ROE", display: "percent" }, [gone]: { formula: `${base} * 2`, display: "multiple" } });
});

test("a number filter on formula text shows the display its threshold is read in", async ({ page }) => {
  await startWith(page);
  for (const [id, formula, display] of [
    [1, "Cash and equivalents - Total debt", "$ million"],
    [2, "ROE * 2", "Percent (%)"],
  ] as const) {
    await page.click(`#filter-search-${id}`);
    await page.locator(`#filter-options-${id}`).getByRole("option", { name: /Create a new variable/ }).click();
    await page.locator("#variable-formula").fill(formula);
    await expect(page.locator("#variable-check")).toHaveAttribute("data-state", "ready");
    await page.click("#variable-apply");
    await expect(page.locator(`#filter-search-${id}`)).toHaveValue(formula);
    await expect(page.locator(`li[data-row="${id}"] .condition-unit`)).toHaveText(display);
  }
});

test("while a draft's own variable is edited, its check reads only the draft's variables before it", async ({ page, home }) => {
  const lib = unique("Lib");
  await home.api<Variable>("POST", "/api/variables", { name: lib, formula: "ROE", favourite: false });
  const [first, edited, after] = [unique("First"), unique("Edited"), unique("After")];
  await startWith(page, (draft) => {
    draft.variables = {
      [first]: { formula: "ROE * 5", display: "percent" },
      [edited]: { formula: `${first} * 2`, display: "percent" },
      [after]: { formula: `${edited} * 2`, display: "percent" },
    };
    draft.sleeves[0]!.steps[0] = { filter: edited, op: ">", value: "1", id: 1 };
  });
  await page.click("#step-edit-1");
  await expect(page.locator("#variable-formula")).toHaveValue(`${first} * 2`);
  await expect(page.locator("#variable-check-text")).toHaveText("✓ Ready · Result: ratio");
  // The library is out of reach: the lists offer none of it, and a library name is not known.
  await page.click("#variable-inputs summary");
  await expect(page.locator("#variable-input-list h3").first()).toBeVisible();
  expect(await page.locator("#variable-input-list h3").allTextContents()).not.toContain("My variables");
  const field = page.locator("#variable-formula");
  for (const typed of [`${lib} * 2`, `${after} + 1`]) {
    await field.fill(typed);
    await field.blur();
    await expect(page.locator("#variable-check-text")).toContainText("is not a known name");
  }
  await field.fill(`${first} * 3`);
  await expect(page.locator("#variable-check-text")).toHaveText("✓ Ready · Result: ratio");
  await page.click("#variable-apply");
  await expect(page.locator("#variable-dialog")).toHaveCount(0);

  const run = await addToQueue(page, home.api, unique("Own before"));
  expect(run.strategy!.variables).toEqual({ [first]: { formula: "ROE * 5", display: "percent" }, [edited]: { formula: `${first} * 3`, display: "percent" } });
});

test("a copy kept after a delete leaves the other library entries that use the same entry in reach", async ({ page, home }) => {
  const [root, aent, bent] = [unique("Root"), unique("Aent"), unique("Bent")];
  await home.api<Variable>("POST", "/api/variables", { name: root, formula: "ROE", favourite: false });
  await home.api<Variable>("POST", "/api/variables", { name: aent, formula: `${root} * 2`, favourite: false });
  await home.api<Variable>("POST", "/api/variables", { name: bent, formula: `${root} * 3`, favourite: false });
  await startWith(page);
  await chooseSource(page, 1, aent);
  await chooseSource(page, 2, bent);
  await page.click("#step-edit-1");
  await page.click("#variable-delete");
  await expect(page.locator("#variable-message")).toHaveText("Deleted from My variables. Tests already added keep their own copy.");
  await page.click("#variable-close");

  const run = await addToQueue(page, home.api, unique("Both steps"));
  expect(run.strategy!.variables).toEqual({
    [root]: { formula: "ROE", display: "percent" },
    [aent]: { formula: `${root} * 2`, display: "percent" },
    [bent]: { formula: `${root} * 3`, display: "percent" },
  });
});
