import type { ComponentChildren } from "preact";
import type { Picture as Part } from "../api/Picture.ts";

const OPERATORS = { "+": "+", "-": "−", "*": "×" } as const;

/** How the server read a formula: names in their own style, a division as
 *  a fraction over a line (with "> 0" under a bottom that must be above
 *  zero), a function with its hint as the tooltip, and brackets only where
 *  the server set `parens`. */
export function Picture({ part }: { part: Part }) {
  let drawn: ComponentChildren;
  if ("name" in part) drawn = <span class="variable-picture-name">{part.name}</span>;
  else if ("number" in part) drawn = part.number + (part.unit ? " " + part.unit : "");
  else if ("fn" in part)
    drawn = (
      <span title={part.hint}>
        {part.fn}(
        {part.args.map((arg, i) => (
          <>
            {i > 0 && ", "}
            <Picture part={arg} />
          </>
        ))}
        )
      </span>
    );
  else if (part.op === "/")
    drawn = (
      <span class="variable-picture-fraction">
        <span>
          <Picture part={part.top} />
        </span>
        <span title={part.positive ? "Divides only by a value above zero" : undefined}>
          <Picture part={part.bottom} />
          {part.positive && (
            <>
              {" "}
              <small>&gt; 0</small>
            </>
          )}
        </span>
      </span>
    );
  else if (part.op === "neg")
    drawn = (
      <>
        −<Picture part={part.arg} />
      </>
    );
  else
    drawn = (
      <>
        <Picture part={part.left} /> {OPERATORS[part.op]} <Picture part={part.right} />
      </>
    );
  return part.parens ? <>({drawn})</> : <>{drawn}</>;
}
