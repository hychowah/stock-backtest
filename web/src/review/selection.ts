import { createContext } from "preact";
import { useContext } from "preact/hooks";

/** The tabs of the result page. Settings is a tab on a narrow window only,
 *  where the settings panel does not fit beside the result. */
export type Tab = "overview" | "selection" | "returns" | "settings";

/** What the open result shows. It belongs to one result: opening another
 *  result starts it afresh (`opening`), and it survives a visit to another
 *  workspace because the page stays mounted.
 *
 *  `trial` is the trial the Returns tab shows, counting from 1: Overview's
 *  "Inspect an original trial" changes it, and a fixed schedule has only
 *  trial 1. `period` is the period of that trial that Returns lists the
 *  holdings of, counting from 1. `sector` limits those holdings to one sector:
 *  undefined for all of them (a company without a sector has the sector
 *  "Unavailable").
 *  The tabs read these four from here. Overview's trial choice is a draft in
 *  its own select until "Show stocks and period returns" sets `trial`; the
 *  Explore selection and the distribution measure belong to the page, not to
 *  this selection. */
export type Selection = { tab: Tab; trial: number; period: number; sector: string | undefined };

/** The selection of a result just opened: Overview, trial 1, period 1, no
 *  sector. */
export const opening: Selection = { tab: "overview", trial: 1, period: 1, sector: undefined };

/** The change that `select` takes: any of the fields. Choosing another trial
 *  without a period goes back to period 1 and to all sectors, because a
 *  period and a sector belong to one trial. */
export type Choice = Partial<Selection>;

/** The selection and the way to change it. */
type Selected = { selection: Selection; select: (choice: Choice) => void };

/** The selection after `choice`. */
export function choose(selection: Selection, choice: Choice): Selection {
  const trialChanged = choice.trial !== undefined && choice.trial !== selection.trial;
  const reset = trialChanged ? { period: 1, sector: undefined } : {};
  return { ...selection, ...reset, ...choice };
}

/** Where `Review` provides the selection of the open result. */
export const SelectionContext = createContext<Selected | null>(null);

/** The selection of the open result, for a tab or any part of the page. */
export function useSelection(): Selected {
  const selected = useContext(SelectionContext);
  if (!selected) throw new Error("useSelection is used outside the result page");
  return selected;
}
