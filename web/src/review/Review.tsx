import type { ComponentChildren } from "preact";
import { useLayoutEffect, useRef, useState } from "preact/hooks";
import type { RunRow } from "../api/RunRow.ts";
import type { TrialsReply } from "../api/TrialsReply.ts";
import { client } from "../client.ts";
import { headlineCells, measureLines, settingsLines, settingsOf } from "../describe.ts";
import { placeInWords, since } from "../format.ts";
import { useNow, useRuns } from "../live.ts";
import { useRead } from "../read.ts";
import { go } from "../route.ts";
import type { Measure } from "../charts/Distribution.tsx";
import { Explore, type ExploredTrials } from "./Explore.tsx";
import { Fixed } from "./Fixed.tsx";
import { Random } from "./Random.tsx";
import { ReturnsTab } from "./ReturnsTab.tsx";
import { choose, type Choice, opening, type Selection, SelectionContext, type Tab, useSelection } from "./selection.ts";
import { SelectionTab } from "./SelectionTab.tsx";

/** Result review of run `id`; null when no result is open. The page keeps the
 *  selection of the open result (selection.ts) while another workspace is
 *  shown, and starts it afresh when another result is opened. A run that is
 *  waiting, held or running shows its state, watched in the run list, and
 *  opens its result when the list says it is complete; a failed run shows
 *  the server's message and place; a stopped run says so. */
export function Review({ visible, id }: { visible: boolean; id: number | null }) {
  return id === null ? (
    <Section visible={visible}>
      <div class="workspace-review-layout">
        <div class="workspace-review-main">
          <Heading title="Result review" />
          <div id="workspace-no-result" class="panel">
            <h2>No backtest is open</h2>
            <p>Open a saved backtest to review it. To run a new test, select Add to queue in Build strategy.</p>
            <button type="button" onClick={() => go({ view: "runs" })}>
              Open Runs &amp; saved
            </button>
          </div>
        </div>
      </div>
    </Section>
  ) : (
    <Open key={id} visible={visible} id={id} />
  );
}

function Section({ visible, tab, children }: { visible: boolean; tab?: Tab; children: ComponentChildren }) {
  return (
    <section id="workspace-review" hidden={!visible} data-section={tab}>
      {children}
    </section>
  );
}

function Heading({ title, window }: { title: string; window?: string }) {
  return (
    <div class="workspace-review-heading">
      <div>
        <span class="eyebrow">Original saved result</span>
        <h1 id="workspace-result-title">{title}</h1>
        <p id="workspace-result-window">{window}</p>
      </div>
    </div>
  );
}

/** One result: reads its run, and again when the run list shows another
 *  state (waiting, running, complete). The last run read stays on the page
 *  while the next read loads, so a state change or a rename in Runs & saved
 *  does not reset what the page shows; the name is the list's. Gives the
 *  selection to everything below it. */
function Open({ visible, id }: { visible: boolean; id: number }) {
  const [selection, setSelection] = useState<Selection>(opening);
  const scroll = useRef<{ saved: Partial<Record<Tab, number>>; after: "top" | "first" | number | null }>({ saved: {}, after: null });
  const last = useRef<RunRow | null>(null);
  const runs = useRuns();
  const row = runs.value?.runs.find((listed) => listed.id === id);
  const read = useRead(() => client.run(id), [id, row?.state ?? "none"]);
  if (read.state === "done") last.current = read.value;
  const found = read.state === "failed" ? null : last.current;
  const run = found && { ...found, name: row?.name ?? found.name };

  // A tab remembers where it was scrolled to. A tab shown for the first time
  // starts under the tab row when that row is stuck at the top of the window.
  const select = (choice: Choice) => {
    const tab = selection.tab;
    if (choice.tab !== undefined && choice.tab !== tab) {
      const tabs = document.getElementById("workspace-review-tabs");
      const stuck = (tabs?.getBoundingClientRect().top ?? 1) < 1;
      scroll.current.saved[tab] = scrollY;
      scroll.current.after = scroll.current.saved[choice.tab] ?? (stuck ? "first" : null);
    }
    setSelection((before) => choose(before, choice));
  };
  useLayoutEffect(() => {
    const after = scroll.current.after;
    scroll.current.after = null;
    if (typeof after === "number") return keepScroll(after);
    if (after === "first") {
      let next = document.getElementById("workspace-review-tabs")?.nextElementSibling ?? null;
      while (next && !next.getClientRects().length) next = next.nextElementSibling;
      next?.scrollIntoView();
    }
  }, [selection.tab]);

  return (
    <SelectionContext.Provider value={{ selection, select }}>
      <Section visible={visible} tab={selection.tab}>
        <div class="workspace-review-layout">
          <div class="workspace-review-main">
            {run === null ? (
              <>
                <Heading title="Result review" />
                <div id="workspace-run-message" class="panel" role="status">
                  {read.state === "failed" ? <p>{read.failure.message}</p> : <p>Reading the backtest…</p>}
                </div>
              </>
            ) : run.state === "complete" ? (
              <Complete run={run} />
            ) : (
              <>
                <Heading title={run.name} window={`${run.schedule.start} → ${run.schedule.end}`} />
                <RunState run={run} visible={visible} />
              </>
            )}
          </div>
          {run?.strategy && run.description && <Settings run={run} />}
        </div>
      </Section>
    </SelectionContext.Provider>
  );
}

/** Scrolls to `top`, and again each time the page changes size, until the
 *  reader scrolls, or for 3 seconds: the content of a tab that was shown
 *  before is read again, so the page is shorter until it arrives. Returns the
 *  function that stops it. */
function keepScroll(top: number): () => void {
  const page = document.getElementById("workspace-review");
  const apply = () => Math.round(scrollY) !== top && scrollTo(0, top);
  apply();
  const watch = new ResizeObserver(apply);
  if (page) watch.observe(page);
  const stop = () => {
    clearTimeout(timer);
    watch.disconnect();
    for (const name of ["wheel", "touchstart", "keydown", "pointerdown"]) removeEventListener(name, stop);
  };
  const timer = setTimeout(stop, 3000);
  for (const name of ["wheel", "touchstart", "keydown", "pointerdown"]) addEventListener(name, stop, { passive: true });
  return stop;
}

/** What a run that has no result yet is doing. The time since it started
 *  ticks only while the page is shown. */
function RunState({ run, visible }: { run: RunRow; visible: boolean }) {
  const now = useNow(visible && run.state === "running");
  const failed = run.state === "failed";
  return (
    <div id="workspace-run-message" class="panel" role="status">
      {run.state === "waiting" && (
        <>
          <h2>Waiting in the queue</h2>
          <p>This test has not started. Its result opens here when it finishes.</p>
        </>
      )}
      {run.state === "held" && (
        <>
          <h2>On hold</h2>
          <p>This test is held and does not run. Release it in Runs &amp; saved to run it.</p>
        </>
      )}
      {run.state === "running" && (
        <>
          <h2>Running</h2>
          <p>{run.started ? "Running for " + since(run.started, now) : "This test is running on the server."} Its result opens here when it finishes.</p>
        </>
      )}
      {run.state === "stopped" && (
        <>
          <h2>Stopped</h2>
          <p>This test was stopped before it finished, so it has no result.</p>
        </>
      )}
      {failed && (
        <>
          <h2>This test failed</h2>
          <p id="workspace-run-error" role="alert">
            {run.error?.message ?? "The server did not say why."}
          </p>
          {run.error?.place && <p class="hint">Where: {placeInWords(run.error.place)}</p>}
        </>
      )}
    </div>
  );
}

/** The recorded settings beside the result, in words. */
function Settings({ run }: { run: RunRow }) {
  return (
    <aside id="workspace-settings" class="panel" aria-label="Recorded result settings">
      <span class="eyebrow">Recorded settings</span>
      <h2>Strategy behind this result</h2>
      <div id="workspace-parameters">
        <dl>
          {settingsLines(settingsOf(run)).map((line) => (
            <div key={line.key}>
              <dt>{line.label}</dt>
              <dd>{line.text}</dd>
            </div>
          ))}
        </dl>
      </div>
      <p class="hint">These are the original settings.</p>
    </aside>
  );
}

const TABS: [Tab, string][] = [
  ["overview", "Overview"],
  ["selection", "Selection"],
  ["returns", "Returns"],
  ["settings", "Settings"],
];

/** A complete run: the heading, the headline of the original result, the
 *  tabs, and the open tab's content. Explore sits under Overview and Returns. */
function Complete({ run }: { run: RunRow }) {
  const { selection, select } = useSelection();
  const trials = useRead(() => client.trials(run.id), [run.id]);
  const [explored, setExplored] = useState<ExploredTrials | null>(null);
  const [measure, setMeasure] = useState<Measure>("cagr");
  const reply = trials.state === "done" ? trials.value : null;
  const random = run.schedule.trials !== undefined;
  const first = reply?.trials[0];

  return (
    <>
      <Heading title={run.name} window={first ? `${first.start} → ${first.end} · ${random ? "Random dates" : "Fixed schedule"}` : ""} />
      <dl id="workspace-headline" class="headline" aria-label="Headline of the original result">
        {reply &&
          headlineCells(run.schedule, reply).map((cell) => (
            <div key={cell.key} data-tone={cell.tone}>
              <dt>{cell.label}</dt>
              <dd>{cell.text}</dd>
            </div>
          ))}
      </dl>
      {reply && random && (
        <details id="workspace-measures" class="how-it-works">
          <summary>Other measures</summary>
          <dl class="headline">
            {measureLines(reply).map((line) => (
              <div key={line.key}>
                <dt>{line.label}</dt>
                <dd>{line.text}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      <nav id="workspace-review-tabs" aria-label="Result sections">
        {TABS.map(([tab, name]) => (
          <button key={tab} type="button" class={tab === "settings" ? "workspace-phone-settings" : undefined} aria-current={selection.tab === tab ? "page" : "false"} onClick={() => select({ tab })}>
            {name}
          </button>
        ))}
      </nav>
      <section id="custom-view" class="panel">
        <h2>Scheduled backtest</h2>
        <p id="schedule-message" aria-live="polite">
          {trials.state === "failed" ? trials.failure.message : ""}
        </p>
        {reply && <TabBody tab={selection.tab} run={run} trials={reply} explored={explored} measure={[measure, setMeasure]} />}
        {reply && <Explore run={run} trials={reply} applied={explored} onApplied={setExplored} hidden={selection.tab !== "overview" && selection.tab !== "returns"} />}
        {reply && <Recorded run={run} trials={reply} />}
      </section>
    </>
  );
}

function TabBody({ tab, run, trials, explored, measure }: { tab: Tab; run: RunRow; trials: TrialsReply; explored: ExploredTrials | null; measure: [Measure, (measure: Measure) => void] }) {
  if (tab === "overview") return run.schedule.trials !== undefined ? <Random run={run} trials={trials} explored={explored} measure={measure} /> : <Fixed run={run} />;
  if (tab === "selection") return <SelectionTab run={run} trials={trials} />;
  if (tab === "returns") return <ReturnsTab run={run} trials={trials} />;
  return null;
}

/** The notes of the original result: the program that calculated it, and for
 *  a fixed schedule how many periods were short or empty and how long the
 *  strategy held cash first. */
function Recorded({ run, trials }: { run: RunRow; trials: TrialsReply }) {
  const trial = trials.trials[0];
  const outcome = run.outcome;
  const coverage =
    run.schedule.trials === undefined && trial
      ? `${trial.short_periods} short periods; ${trial.empty_periods} empty periods. ` +
        (trial.empty_periods ? "Empty periods hold cash at 0%; SPY keeps its period return. " : "") +
        (trial.cash_days ? `Both strategy and paired SPY hold cash until ${trial.first_trade} (${trial.cash_days} days); CAGR uses the common window.` : "")
      : "";
  return (
    <details id="workspace-recorded-context" class="how-it-works">
      <summary>Recorded coverage and notes</summary>
      <p id="result-producer" class="hint" aria-live="polite">
        {outcome ? `Calculated by ${outcome.program} on prepared data generation ${outcome.generation}, as of ${outcome.as_of}.` : "Producer not recorded in this result."}
      </p>
      <p id="schedule-coverage" class="hint" hidden={!coverage}>
        {coverage}
      </p>
    </details>
  );
}
