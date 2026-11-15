import type { UpdateProgress } from "../api/UpdateProgress.ts";
import type { UpdateStage } from "../api/UpdateStage.ts";
import type { UpdateState } from "../api/UpdateState.ts";
import { count, marketName } from "../format.ts";

/** What the update panel shows for the state and progress of the update that
 *  `GET /api/data/status` reports: pure rules, so the panel only draws them. */

/** Whether an update is running or ending. */
export const active = (state: UpdateState) => state === "running" || state === "stopping";

/** The delay in ms before the next status read: 1 s while an update runs or
 *  stops, otherwise 5 s. */
export const statusInterval = (state: UpdateState | undefined) => (state !== undefined && active(state) ? 1000 : 5000);

/** The start button: Continue update after an update that did not finish
 *  (stopped, interrupted or failed), Update data otherwise. Both send the
 *  same request; the button waits while an update is active. */
export function startButton(state: UpdateState): { label: string; enabled: boolean } {
  const unfinished = state === "stopped" || state === "interrupted" || state === "failed";
  return { label: unfinished ? "Continue update" : "Update data", enabled: !active(state) };
}

/** The stop button: hidden when no update is active, Stop update while it
 *  runs, and a waiting "Stopping safely" once a stop was asked. */
export function stopButton(state: UpdateState): { label: string; enabled: boolean } | null {
  return active(state) ? { label: state === "stopping" ? "Stopping safely" : "Stop update", enabled: state === "running" } : null;
}

/** The state in words. */
export function headline(state: UpdateState): string {
  switch (state) {
    case "idle":
      return "No update recorded";
    case "running":
      return "Updating your data";
    case "stopping":
      return "Stopping safely";
    case "stopped":
      return "Update stopped";
    case "interrupted":
      return "Update interrupted";
    case "failed":
      return "Update failed";
    case "partial":
      return "Updated, with failed items";
    case "complete":
      return "Data updated";
  }
}

/** One step of the update: done (✓), the one running now, still to come, or
 *  skipped because reports are not due. */
type Step = { label: string; mark: "done" | "current" | "todo" | "skipped" };

const STAGES: { stage: UpdateStage; label: string }[] = [
  { stage: "companies", label: "Companies" },
  { stage: "reports", label: "Reports" },
  { stage: "prices", label: "Prices" },
  { stage: "preparing", label: "Preparing" },
];

/** The steps Companies, Reports, Prices, Preparing and Ready, with the
 *  current one marked. A step before the stage the update is on is done; all
 *  are done once the update finished (complete or partial). A stopped,
 *  interrupted or failed update marks no step as current. */
export function steps(progress: UpdateProgress): Step[] {
  const finished = progress.state === "complete" || progress.state === "partial";
  const at = progress.stage === null ? -1 : STAGES.findIndex((step) => step.stage === progress.stage);
  const marked = STAGES.map(({ stage, label }, i): Step => {
    if (stage === "reports" && progress.reports === "not_due") return { label: "Reports: next check Saturday", mark: "skipped" };
    if (finished || i < at) return { label, mark: "done" };
    return { label, mark: i === at && active(progress.state) ? "current" : "todo" };
  });
  return [...marked, { label: "Ready", mark: finished ? "done" : "todo" }];
}

/** The stage's count and the update's failed items, such as
 *  "Prices, US: 120 of 700 · 3 failed"; empty when there is neither. */
export function counts(progress: UpdateProgress): string {
  const parts: string[] = [];
  const stage = STAGES.find((step) => step.stage === progress.stage);
  if (stage && progress.total > 0) {
    const market = progress.market ? ", " + marketName(progress.market) : "";
    parts.push(`${stage.label}${market}: ${count(progress.done)} of ${count(progress.total)}`);
  }
  if (progress.failed > 0) parts.push(`${count(progress.failed)} failed`);
  return parts.join(" · ");
}
