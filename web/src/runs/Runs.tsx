import type { ComponentChildren } from "preact";
import { SavedPanel } from "./SavedPanel.tsx";

/** Runs & saved: the queue panel (`queue`, drawn here while the tray is
 *  closed), then the saved table. */
export function Runs({ visible, queue }: { visible: boolean; queue: ComponentChildren }) {
  return (
    <section id="workspace-runs" hidden={!visible}>
      {queue}
      <SavedPanel />
    </section>
  );
}
