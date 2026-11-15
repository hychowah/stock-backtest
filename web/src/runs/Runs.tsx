import type { ComponentChildren } from "preact";

/** Runs & saved; `queue` is the queue panel, drawn first when it is not in the tray. */
export const Runs = ({ visible, queue }: { visible: boolean; queue: ComponentChildren }) => <section id="workspace-runs" hidden={!visible}>{queue}</section>;
