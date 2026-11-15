import { useEffect, useState } from "preact/hooks";
import type { MarketChoice } from "../runs.ts";

const KEY = "runs-market";
const listeners = new Set<(choice: MarketChoice) => void>();
let chosen: MarketChoice = "";
try {
  const stored = localStorage.getItem(KEY);
  if (stored === "us" || stored === "hk" || stored === "jp") chosen = stored;
} catch {}

/** The market switch's choice, shared by the queue panel (wherever it is
 *  drawn) and the saved table, and kept for the next visit in this browser. It
 *  lives here because the queue panel is drawn anew when it moves between the
 *  tray and Runs & saved. */
export function useMarket(): [MarketChoice, (choice: MarketChoice) => void] {
  const [choice, setChoice] = useState(chosen);
  useEffect(() => {
    listeners.add(setChoice);
    setChoice(chosen);
    return () => void listeners.delete(setChoice);
  }, []);
  const choose = (next: MarketChoice) => {
    chosen = next;
    try {
      localStorage.setItem(KEY, next);
    } catch {}
    for (const listener of listeners) listener(next);
  };
  return [choice, choose];
}
