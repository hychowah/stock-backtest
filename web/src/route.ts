/** The place after `#`: #/build, #/runs, #/results/<id>, and #/results for the
 *  last opened result. Anything else is #/build. The route only chooses the
 *  visible workspace. The three workspaces stay mounted, so the draft, the
 *  latest picks, a held edit, and the open result with its tab, scroll,
 *  inspected trial and Explore selection all survive a visit to another
 *  workspace. Opening another result id starts its selection afresh. A reload
 *  keeps only the draft (localStorage) and the address.
 *
 *  The shell follows the address: a workspace changes the route with go() or
 *  a link to hrefOf(), never by showing itself. */
export type Route =
  | { view: "build" }
  | { view: "runs" }
  /** `id` null: #/results before any result was opened. */
  | { view: "review"; id: number | null };

/** The route of an address's hash, such as `#/results/12`; `#/results` reads
 *  as `lastResult` (null when no result was opened). */
export function parseRoute(hash: string, lastResult: number | null): Route {
  const parts = hash.replace(/^#\/?/, "").split("/");
  if (parts.length === 1 && parts[0] === "runs") return { view: "runs" };
  if (parts[0] === "results") {
    if (parts.length === 1) return { view: "review", id: lastResult };
    if (parts.length === 2 && /^[1-9][0-9]{0,15}$/.test(parts[1] ?? "")) return { view: "review", id: Number(parts[1]) };
  }
  return { view: "build" };
}

/** The hash of a route: `#/build`, `#/runs`, `#/results/<id>` or `#/results`. */
export function hrefOf(route: Route): string {
  if (route.view === "review") return route.id === null ? "#/results" : `#/results/${route.id}`;
  return `#/${route.view}`;
}

/** Shows a route: sets the address, which the shell follows. When the
 *  address is already the route's, a `hashchange` event is sent all the same,
 *  so the shell does what it does for any other visit: it closes the queue
 *  tray and scrolls to the top. */
export function go(route: Route): void {
  const hash = hrefOf(route);
  if (location.hash === hash) dispatchEvent(new HashChangeEvent("hashchange"));
  else location.hash = hash;
}
