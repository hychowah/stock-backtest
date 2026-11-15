import { Fragment } from "preact";
import type { Trail } from "../describe.ts";

/** A holding's or a pick's step trail (describe.ts trailOf): for each sleeve
 *  that picked it, the sleeve's name when the strategy has several, then one
 *  line per step. It sits inside the item's Details. */
export function StepTrail({ trails }: { trails: Trail[] }) {
  return (
    <>
      {trails.map((trail, i) => (
        <Fragment key={i}>
          {trail.sleeve !== null && <p>{trail.sleeve}</p>}
          <ol class="step-trail" aria-label="Step trail">
            {trail.lines.map((line, j) => (
              <li key={j}>{line}</li>
            ))}
          </ol>
        </Fragment>
      ))}
    </>
  );
}
