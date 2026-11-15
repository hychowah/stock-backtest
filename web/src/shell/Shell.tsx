import { useEffect, useRef, useState } from "preact/hooks";
import { Build } from "../build/Build.tsx";
import { lastResult, useRuns } from "../live.ts";
import { Review } from "../review/Review.tsx";
import { go, parseRoute, type Route } from "../route.ts";
import { QueuePanel } from "../runs/QueuePanel.tsx";
import { Runs } from "../runs/Runs.tsx";
import { StatusBar } from "./StatusBar.tsx";

const currentRoute = (): Route => {
  const route = parseRoute(location.hash, lastResult.id);
  if (route.view === "review" && route.id !== null) lastResult.id = route.id;
  return route;
};

/** The page: the nav, the three workspaces, the status bar and the queue
 *  tray. The header's pill is hidden while empty; Build strategy sets its
 *  text (setPill), as the old page showed the latest picks' day there. The
 *  address chooses the visible workspace; all three stay mounted
 *  (route.ts). Result review keeps the last result it showed while another
 *  workspace is visible.
 *
 *  The queue panel is drawn in one place, so each of its ids appears once: in
 *  the tray while the tray is open, otherwise first in Runs & saved. It is
 *  drawn anew when it moves, so state that must survive the move belongs in a
 *  module, not in the panel. */
export function Shell() {
  const [route, setRoute] = useState(currentRoute);
  const [reviewId, setReviewId] = useState(lastResult.id);
  const [trayOpen, setTrayOpen] = useState(false);
  const [pill, setPill] = useState("");
  const tray = useRef<HTMLDialogElement>(null);
  const runs = useRuns();

  useEffect(() => {
    const follow = () => {
      const next = currentRoute();
      setRoute(next);
      if (next.view === "review") setReviewId(next.id);
      setTrayOpen(false);
      scrollTo(0, 0);
    };
    addEventListener("hashchange", follow);
    return () => removeEventListener("hashchange", follow);
  }, []);

  useEffect(() => {
    const dialog = tray.current;
    if (trayOpen && dialog && !dialog.open) dialog.showModal();
    if (!trayOpen && dialog?.open) dialog.close();
  }, [trayOpen]);

  const list = runs.value?.runs;
  const active = list?.filter((run) => run.state === "waiting" || run.state === "held" || run.state === "running").length;
  const current = (view: Route["view"]) => (route.view === view ? "page" : "false");

  return (
    <>
      <nav id="workspace-nav" aria-label="Research workspace">
        <a class="workspace-brand" href="#/build">
          Stock Backtest<small>Strategy research</small>
        </a>
        <button type="button" aria-current={current("build")} onClick={() => go({ view: "build" })}>
          Build strategy
        </button>
        <button type="button" aria-current={current("runs")} onClick={() => go({ view: "runs" })}>
          Runs & saved <span id="workspace-queue-count">{active ?? ""}</span>
        </button>
        <button type="button" aria-current={current("review")} onClick={() => go({ view: "review", id: lastResult.id })}>
          Result review
        </button>
        <a href="data.html">Data & preparation ↗</a>
      </nav>
      <StatusBar runs={runs} onOpenRuns={() => go({ view: "runs" })} onOpenTray={() => setTrayOpen(true)} />
      <dialog id="workspace-queue-tray" aria-labelledby="queue-heading" ref={tray} onClose={() => setTrayOpen(false)}>
        <button type="button" id="workspace-queue-close" class="workspace-tray-close" onClick={() => setTrayOpen(false)}>
          Close queue
        </button>
        <div id="workspace-queue-content">{trayOpen && <QueuePanel />}</div>
      </dialog>
      <main>
        <header>
          <span class="eyebrow">Stock Backtest / Research results</span>
          <span class="pill">{pill}</span>
        </header>
        <Build visible={route.view === "build"} setPill={setPill} />
        <Runs visible={route.view === "runs"} queue={!trayOpen && <QueuePanel />} />
        <Review visible={route.view === "review"} id={reviewId} />
        <footer>Source: prepared data and saved results · No market-data requests are made by this page.</footer>
      </main>
    </>
  );
}
