import type { ComponentChildren } from "preact";

/** A wide table or chart in a scroll region: a hint line, then a region
 *  that scrolls sideways and takes keyboard focus. `kind` is
 *  the region's class, which sets its height in the carried CSS: `table-wrap`
 *  (370 px high), `latest-table` (520 px) or `scroll` (a chart; no limit). A
 *  table with the class `stock-table` keeps its second column (the symbol)
 *  in view while the region scrolls. */
export function ScrollTable({ kind = "table-wrap", children }: { kind?: "table-wrap" | "latest-table" | "scroll"; children: ComponentChildren }) {
  return (
    <>
      <p class="scroll-hint">Scroll sideways for more columns or chart periods.</p>
      <div class={kind} tabindex={0} role="region" aria-label="Scrollable chart or data table">
        {children}
      </div>
    </>
  );
}
