import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { ScrollTable } from "../common/ScrollTable.tsx";

const HINT = "Tap, hover over, or focus a chart mark to see details.";

/** A chart in a region that scrolls sideways and takes keyboard focus, with
 *  the line below it that names the mark under the pointer, in focus or
 *  tapped. A mark is a `rect`, `path` or `line` with an `aria-label`, or a
 *  `title` child, that holds its words. `children` are the SVG's contents. */
export function ScrollChart({ id, viewBox, label, children }: { id?: string; viewBox: string; label: string; children: ComponentChildren }) {
  const [detail, setDetail] = useState(HINT);
  const show = (event: Event) => {
    const mark = event.target instanceof Element ? event.target.closest("rect,path,line") : null;
    const text = mark?.getAttribute("aria-label") ?? mark?.querySelector("title")?.textContent;
    if (text) setDetail(text);
  };
  return (
    <>
      <ScrollTable kind="scroll">
        <svg id={id} viewBox={viewBox} role="img" aria-label={label} onClick={show} onPointerOver={show} onFocusIn={show}>
          {children}
        </svg>
      </ScrollTable>
      <p class="chart-detail" aria-live="polite">
        {detail}
      </p>
    </>
  );
}
