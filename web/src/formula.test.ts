import assert from "node:assert/strict";
import { test } from "node:test";
import type { CheckedFormula } from "./api/CheckedFormula.ts";
import type { CatalogReply } from "./api/CatalogReply.ts";
import type { Variable } from "./api/Variable.ts";
import { bothDrafts } from "./build/state.ts";
import { defaultDraft } from "./draft.ts";
import { faultLine, faultRange, formulaWords, keepCopy, renameSource, spelling, typingMatches, useSource } from "./formula.ts";

const fault = (start: number, end: number, message = "“Revnue” is not a known name or a variable of this file.") => ({ code: "UNKNOWN_NAME", message, start, end, suggestions: [] });

test("a fault's range, counted in code points, is where a suggestion goes and what the check line quotes", () => {
  const replace = (text: string, start: number, end: number, value: string) => {
    const [from, to] = faultRange(text, { start, end });
    return text.slice(0, from) + value + text.slice(to);
  };
  assert.equal(replace("Revnue / Total assets", 0, 6, "Revenue"), "Revenue / Total assets");
  // "𝑥" is one code point and two UTF-16 units; "×" is one of each.
  assert.equal(replace("[𝑥 ratio] × Revnue - 1", 12, 18, "Revenue"), "[𝑥 ratio] × Revenue - 1");
  assert.equal(replace("max(ROE 2", 7, 7, ","), "max(ROE, 2");
  // The line quotes the characters at fault when the message does not.
  assert.equal(faultLine("Revnue / 2", fault(0, 6)), "✗ “Revnue” is not a known name or a variable of this file.");
  assert.equal(faultLine("𝑥 max(ROE, 2", fault(6, 12, "Give a number of years.")), "✗ Give a number of years. (“ROE, 2”)");
});

const entry = (id: number, name: string, uses: string[] = []): Variable => ({ id, name, formula: `ROE * ${id}`, display: "percent", favourite: false, uses });

test("a name that does not start with a letter is typed in brackets, with ] doubled", () => {
  assert.equal(spelling("Total debt"), "Total debt");
  assert.equal(spelling("Équité"), "Équité");
  assert.equal(spelling("3y ROE"), "[3y ROE]");
  assert.equal(spelling("_x [a]"), "[_x [a]]]");
  assert.equal(spelling("Ⅻ index"), "[Ⅻ index]");
});

test("the typing list: the fragment at the caret, the names it begins a word of, those that start with it first, at most 8", () => {
  const catalog = {
    names: [
      { name: "Enterprise value", kind: "built-in", category: "Market", unit: "USD", display: "usd_million", step_only: false },
      { name: "Enterprise value in dollars", kind: "field", category: "Size and listing", unit: "USD", display: "usd", step_only: true },
      { name: "Total debt", kind: "input", category: "Balance sheet", unit: "USD", display: "usd_million", step_only: false },
      { name: "Net debt", kind: "measure", category: "Balance sheet", unit: "USD", display: "usd_million", step_only: false },
      { name: "Total debt/EBITDA", kind: "built-in", category: "Debt and liquidity", unit: "scalar", display: "multiple", step_only: false },
    ],
    functions: [
      { form: "average(INPUT, N years)", meaning: "the mean" },
      { form: "A / positive(B)", meaning: "B above zero" },
    ],
  } as unknown as CatalogReply;
  const words = formulaWords([entry(1, "3y debt"), entry(2, "Debt cover")], catalog);
  assert.deepEqual(
    words.map((word) => [word.name, word.text, word.detail]),
    [
      ["3y debt", "[3y debt]", "My variable"],
      ["Debt cover", "Debt cover", "My variable"],
      ["Enterprise value", "Enterprise value", "$ million"],
      ["Total debt", "Total debt", "$ million"],
      ["Net debt", "Net debt", "$ million"],
      ["Total debt/EBITDA", "Total debt/EBITDA", "Multiple (×)"],
      ["average", "average(", "the mean"],
      ["positive", "positive(", "B above zero"],
    ],
  );
  const names = (before: string) => {
    const found = typingMatches(before, words);
    return found && [found.start, ...found.words.map((word) => word.name)];
  };
  assert.deepEqual(names("Total debt / Enter"), [13, "Enterprise value"]);
  // "total d" covers two words; the names that start with it come first.
  assert.deepEqual(names("2 * total  D"), [4, "Total debt", "Total debt/EBITDA"]);
  // "debt" begins a word of five names: Debt cover starts with it, the rest keep their order.
  assert.deepEqual(names("debt"), [0, "Debt cover", "3y debt", "Total debt", "Net debt", "Total debt/EBITDA"]);
  assert.deepEqual(names("ROE * pos"), [6, "positive"]);
  // No start inside a word, none that matches, and one match that is the fragment itself.
  assert.equal(names("xenter"), null);
  assert.equal(names("Revenue + 1"), null);
  assert.equal(names("Net debt"), null);
  const many = Array.from({ length: 12 }, (_, i) => ({ name: `Debt ${i}`, text: `Debt ${i}`, detail: "" }));
  assert.equal(typingMatches("debt", many)!.words.length, 8);
});

const checked = (canonical: string, display: CheckedFormula["display"] = "percent"): CheckedFormula => ({
  canonical,
  unit: "scalar",
  display,
  displays: ["number", "multiple", "percent", "percentage_points"],
  picture: { name: canonical },
});

test("Use keeps the source while its text and display are unchanged, else uses the formula text in its default display", () => {
  const opened = { source: "Asset turnover", text: "Revenue/Total assets", display: "multiple" };
  assert.equal(useSource(opened, "Revenue/Total assets", "multiple", checked("Revenue / Total assets")), "Asset turnover");
  assert.equal(useSource(opened, "Revenue / Total assets * 2", "percent", checked("Revenue / Total assets * 2")), "Revenue / Total assets * 2");
  // Another display than the default needs a saved variable.
  assert.equal(useSource(opened, "Revenue/Total assets", "percent", checked("Revenue / Total assets")), "Revenue / Total assets");
  assert.equal(useSource(null, "Revenue/Total assets", "multiple", checked("Revenue / Total assets")), null);
  // Formula text opened from a step has the default display.
  assert.equal(useSource({ source: "ROE*2", text: "ROE*2", display: null }, "ROE*2", "percent", checked("ROE * 2")), "ROE*2");
});

test("a renamed library entry is renamed in the steps that read it, unless the draft has its own variable of that name", () => {
  const draft = defaultDraft();
  draft.sleeves[0]!.steps.push({ filter: "asset  TURNOVER", op: ">", value: "1", id: 9 }, { rank: "Asset turnover", order: "lowest", from: 1, to: 5, id: 10 });
  const renamed = renameSource(draft, "Asset turnover", "Turnover");
  assert.deepEqual(
    renamed.sleeves[0]!.steps.map((step) => ("rank" in step ? step.rank : step.filter)),
    ["Market cap", "Enterprise value", "EBITDA yield", "Turnover", "Turnover"],
  );
  const own = { ...draft, variables: { "Asset Turnover": { formula: "Revenue / Total assets", display: "multiple" } } };
  assert.equal(renameSource(own, "Asset turnover", "Turnover"), own);
});

test("a deleted entry that the steps read stays in the draft as its own copy, with the entries it uses", () => {
  const library = [entry(1, "Base"), entry(2, "Other"), entry(3, "Mid", ["Base"]), entry(4, "Gone", ["Base", "Mid"])];
  const draft = defaultDraft();
  draft.sleeves[0]!.steps.push({ rank: "gone", order: "highest", from: 1, to: 5, id: 9 });
  const kept = keepCopy(draft, library[3]!, library);
  assert.deepEqual(kept.variables, {
    Base: { formula: "ROE * 1", display: "percent" },
    Mid: { formula: "ROE * 3", display: "percent" },
    Gone: { formula: "ROE * 4", display: "percent" },
  });
  // A used entry the draft already has, identical, is not copied again.
  const same = { ...draft, variables: { base: { formula: "ROE * 1", display: "percent" } } };
  assert.deepEqual(Object.keys(keepCopy(same, library[3]!, library).variables), ["base", "Mid", "Gone"]);
  // One the draft has with another formula or display would change what the step reads: nothing is copied.
  for (const base of [{ formula: "ROA", display: "percent" }, { formula: "ROE * 1", display: "number" }]) {
    const owned = { ...draft, variables: { base } };
    assert.equal(keepCopy(owned, library[3]!, library), owned);
  }
  // A draft whose steps do not read the entry stays as it is.
  const plain = defaultDraft();
  assert.equal(keepCopy(plain, library[3]!, library), plain);
});

test("a library change applies to the live draft and to a held run's draft", () => {
  const live = defaultDraft();
  live.sleeves[0]!.steps.push({ rank: "Cheap", order: "highest", from: 1, to: 5, id: 9 });
  const held = { run: { id: 7 } as never, draft: structuredClone(live) };
  const rename = (draft: typeof live) => renameSource(draft, "cheap", "Cheaper");
  const next = bothDrafts({ live, held, fresh: false }, rename);
  assert.equal(next.live.sleeves[0]!.steps.at(-1)!.id, 9);
  assert.deepEqual([next.live, next.held!.draft].map((draft) => (draft.sleeves[0]!.steps.at(-1) as { rank: string }).rank), ["Cheaper", "Cheaper"]);
  assert.equal(next.held!.run, held.run);
  // Without a held run only the live draft changes; an unchanged default draft stays fresh.
  const alone = bothDrafts({ live: defaultDraft(), held: null, fresh: true }, rename);
  assert.equal(alone.held, null);
  assert.equal(alone.fresh, true);
});
