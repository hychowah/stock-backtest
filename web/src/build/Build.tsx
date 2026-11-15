import { useEffect, useRef, useState } from "preact/hooks";
import type { Market } from "../api/Market.ts";
import type { ScreenBody } from "../api/ScreenBody.ts";
import { type ApiFailure, client } from "../client.ts";
import { defaultName, type RunSettings } from "../describe.ts";
import { type Draft, isRank, resetStrategy, scheduleOf, setMarket, setSchedule, sleeveName, sourceOf, strategyFile } from "../draft.ts";
import { marketName, placeInWords } from "../format.ts";
import { act, useLibrary } from "../live.ts";
import { asFailure, useRead } from "../read.ts";
import { describeSource } from "../sources.ts";
import { Dates } from "./Dates.tsx";
import { Latest, type Screen } from "./Latest.tsx";
import { changeDraft, placeDefaultStart, update, useBuildState } from "./state.ts";
import { Steps } from "./Steps.tsx";

export { editHeld, heldEditOpen, OPEN_EDIT, tune } from "./state.ts";

/** A refusal in words: its place, then the server's message. */
const refusal = (failure: ApiFailure) => (failure.place ? placeInWords(failure.place) + ": " : "") + failure.message;

/** Build strategy; `setPill` sets the text of the header's pill ("" hides it).
 *
 *  It shows the live draft, or the draft of a held run while that run is
 *  edited (editHeld). Latest stock picks screens the draft on the market's
 *  last session: Screen latest, or Auto-run 400 ms after a change. Historical
 *  backtest adds the draft to the queue as a test (Add to queue), or saves a
 *  held run's new settings and releases it (Save changes). The server checks
 *  every strategy and schedule; its refusal shows under the button that sent
 *  them, with its place in words. */
export function Build({ visible, setPill }: { visible: boolean; setPill: (text: string) => void }) {
  const { live, held, loads, message } = useBuildState();
  const draft = held?.draft ?? live;
  const latest = draft.mode === "latest";

  const [sleeve, setSleeve] = useState(0);
  useEffect(() => setSleeve(0), [loads, held === null]);
  const active = Math.min(sleeve, draft.sleeves.length - 1);

  const status = useRead(client.dataStatus, []);
  const prepared = status.state === "done" ? status.value.markets.filter((market) => market.prepared?.first_session && market.prepared.last_session) : null;
  const sessionsOf = (market: Market) => {
    const data = prepared?.find((other) => other.market === market)?.prepared;
    return data?.first_session && data.last_session ? { first: data.first_session, last: data.last_session } : null;
  };
  const sessions = sessionsOf(draft.market);
  // A market without prepared data gives way to the first that has some, as
  // a change of market; the default draft's start moves inside the sessions.
  useEffect(() => {
    const first = prepared?.[0];
    if (first && !sessions) changeDraft((current) => setMarket(current, first.market, sessionsOf(first.market)));
    else if (sessions) placeDefaultStart(sessions);
  }, [prepared?.length, draft.market]);

  const catalogRead = useRead(() => client.catalog(draft.market), [draft.market]);
  const catalog = catalogRead.state === "done" ? catalogRead.value : null;
  const library = useLibrary();
  const entries = library.value ?? [];
  const pickerNote =
    catalogRead.state === "loading" || (library.value === null && !library.failure)
      ? "Loading the market's names and saved variables…"
      : catalogRead.state === "failed"
        ? "The market's names could not be read: " + catalogRead.failure.message
        : library.failure && !library.value
          ? "Saved variables could not be read: " + library.failure.message
          : "";

  const strategy = strategyFile(draft, entries);
  const known = { own: draft.variables, library: entries, catalog };
  const settings: RunSettings = {
    market: draft.market,
    schedule: scheduleOf(draft.schedule, sessions?.last ?? ""),
    strategy,
    steps: draft.sleeves.map((other) =>
      other.steps.map((step) => describeSource(sourceOf(step), known) ?? { source: { kind: "formula", name: sourceOf(step) }, display: "number" }),
    ),
  };
  const testName = defaultName(settings);

  // Latest picks.
  const request: ScreenBody = { market: draft.market, strategy };
  const key = JSON.stringify(request);
  const [screen, setScreen] = useState<(Screen & { key: string }) | null>(null);
  const [screenError, setScreenError] = useState("");
  const [screening, setScreening] = useState(false);
  const sequence = useRef(0);
  /** The key of the last screen sent. */
  const sent = useRef<string | null>(null);
  const screenNow = (body: ScreenBody, bodyKey: string) => {
    const number = ++sequence.current;
    sent.current = bodyKey;
    setScreening(true);
    client.screen(body).then(
      (reply) => {
        if (number !== sequence.current) return;
        setScreen({ strategy: body.strategy, reply, key: bodyKey });
        setScreenError("");
        setScreening(false);
      },
      (thrown: unknown) => {
        if (number !== sequence.current) return;
        setScreenError(refusal(asFailure(thrown)));
        setScreening(false);
      },
    );
  };
  const libraryRead = library.value !== null || library.failure !== null;
  useEffect(() => {
    if (!latest || !draft.autoRun || !libraryRead || key === screen?.key) return;
    const timer = setTimeout(() => screenNow(request, key), 400);
    return () => clearTimeout(timer);
  }, [key, latest, draft.autoRun, libraryRead]);
  useEffect(() => setPill(screen?.reply.day ?? ""), [screen?.reply.day]);
  const stale = screen !== null && screen.key !== key;
  // With auto-run, the current settings that were not sent yet are about to be.
  const missing = screen === null && !screening && !(draft.autoRun && sent.current !== key);
  const reply = screen?.reply;
  const [from, to] = reply?.description.ranks ?? [0, 0];
  // Several sleeves can pick the same stock, so only one sleeve's ranks say
  // how many picks there should be.
  const shortOf = reply ? reply.description.sleeves.length === 1 && reply.picks.length < to - from + 1 : false;
  const dataProblem =
    status.state === "failed"
      ? "The prepared data's status could not be read: " + refusal(status.failure)
      : status.state === "done" && !sessions
        ? `Prepare ${marketName(draft.market)} data from Data & preparation before running this market.`
        : "";

  // Add to queue, and the held edit.
  const form = useRef<HTMLFormElement>(null);
  const [busy, setBusy] = useState(false);
  const say = (text: string, failed = false) => update({ message: { text, failed } });

  const add = async () => {
    if (busy || (form.current && !form.current.reportValidity())) return;
    setBusy(true);
    const body = { name: draft.name.trim() || testName, market: draft.market, schedule: settings.schedule, strategy };
    try {
      if (held) {
        const id = held.run.id;
        await act(() => client.editRun(id, body));
        // The changes are saved: the edit ends even when the release is
        // refused, as for a test released meanwhile.
        const released = await act(() => client.release(id)).then(
          () => true,
          () => false,
        );
        update({ held: null });
        say(released ? "Queued test updated. It can run with the new settings." : "Queued test updated. Its changes were saved.");
      } else {
        await act(() => client.addRun(body));
        changeDraft((current) => ({ ...current, name: "" }));
        say("Test added to the queue. You can change the settings and add another.");
      }
    } catch (thrown) {
      say(refusal(asFailure(thrown)), true);
    } finally {
      setBusy(false);
    }
  };
  const cancel = async () => {
    if (!held || busy) return;
    setBusy(true);
    // The edit ends whatever the release answers: the run's settings were
    // not changed, and a run released meanwhile needs no release.
    await act(() => client.release(held.run.id)).catch(() => undefined);
    update({ held: null, message: { text: "Edit cancelled. Its previous settings are kept.", failed: false } });
    setBusy(false);
  };

  const lastRank = draft.sleeves[0]?.steps.findLast(isRank);
  const heading =
    draft.sleeves.length > 1
      ? "Sleeves " + draft.sleeves.map(sleeveName).join(" + ")
      : lastRank
        ? (lastRank.order === "highest" ? "Highest " : "Lowest ") + lastRank.rank
        : "Add a Rank step";
  const mode = (next: Draft["mode"]) => changeDraft((current) => ({ ...current, mode: next }));

  return (
    <section id="workspace-builder" hidden={!visible}>
      <div class="mode-switch" role="group" aria-label="Screening view">
        <button id="mode-latest" type="button" aria-pressed={latest ? "true" : "false"} onClick={() => mode("latest")}>
          Latest stock picks
        </button>{" "}
        <button id="mode-backtest" type="button" aria-pressed={latest ? "false" : "true"} onClick={() => mode("backtest")}>
          Historical backtest
        </button>
      </div>
      <section class="panel" aria-labelledby="strategy-heading">
        <form
          id="strategy-form"
          ref={form}
          onSubmit={(event) => {
            // Screen latest submits the form; in Historical backtest a submit,
            // such as Enter in a step field, starts nothing.
            event.preventDefault();
            if (latest && !screening) screenNow(request, key);
          }}
        >
          <div class="toolbar">
            <div>
              <span class="eyebrow">Strategy builder</span>
              <h2 id="strategy-heading">{heading}</h2>
            </div>
            <div class="strategy-actions">
              <button
                type="button"
                id="reset-strategy"
                onClick={() => {
                  changeDraft(resetStrategy);
                  setSleeve(0);
                }}
              >
                Reset strategy
              </button>
              <button type="submit" id="run-screen" class="primary" hidden={!latest} disabled={screening}>
                Screen latest
              </button>
              <span id="queue-controls" hidden={latest}>
                <input
                  id="queue-name"
                  type="text"
                  maxlength={120}
                  aria-label="Test name (optional)"
                  placeholder={testName || "Test name (optional)"}
                  value={draft.name}
                  onInput={(event) => {
                    const name = event.currentTarget.value;
                    changeDraft((current) => ({ ...current, name }));
                  }}
                  onKeyDown={(event) => {
                    // Enter adds the test, as the button does; it never submits the form.
                    if (event.key !== "Enter" || event.isComposing) return;
                    event.preventDefault();
                    void add();
                  }}
                />
                <button type="button" id="queue-add" class="primary" disabled={busy} onClick={() => void add()}>
                  {held ? "Save changes" : "Add to queue"}
                </button>
                <button type="button" id="queue-cancel-edit" hidden={!held} disabled={busy} onClick={() => void cancel()}>
                  Cancel edit
                </button>
                <a id="queue-link" href="#/runs">
                  Open Runs &amp; saved →
                </a>
              </span>
            </div>
          </div>
          <p id="queue-builder-status" class="hint" role="status" aria-live="polite" hidden={!held && !message}>
            <span id="queue-add-status" class={message?.failed ? "backtest-failed" : "hint"}>
              {message?.text}
            </span>{" "}
            <span id="queue-edit-note">
              {held ? `Editing “${held.run.name}”. Edit the strategy controls in Historical backtest mode. Then select Save changes to release this test, or Cancel edit to keep its previous settings.` : ""}
            </span>
          </p>
          <div class="builder-options">
            <label>
              Market
              <select id="stock-market" value={draft.market} onChange={(event) => {
                  const market = event.currentTarget.value as Market;
                  changeDraft((current) => setMarket(current, market, sessionsOf(market)));
                }}>
                {(prepared?.length ? prepared.map((market) => market.market) : [draft.market]).map((market) => (
                  <option value={market} key={market}>
                    {marketName(market)}
                  </option>
                ))}
              </select>
            </label>
            <span id="auto-run-controls" hidden={!latest}>
              <label class="check">
                <input type="checkbox" id="auto-run" checked={draft.autoRun} onChange={(event) => {
                    const autoRun = event.currentTarget.checked;
                    changeDraft((current) => ({ ...current, autoRun }));
                  }} /> Auto-run when settings change
              </label>
            </span>
          </div>
          <Steps key={`${loads}-${held ? "held" : "live"}`} draft={draft} sleeve={active} setSleeve={setSleeve} catalog={catalog} library={library.value} note={pickerNote} />
          <Dates hidden={latest} form={draft.schedule} sessions={sessions} change={(edit) => changeDraft((current) => setSchedule(current, edit))} />
          <p id="screen-error" role="alert">
            {dataProblem || (latest && screenError && screenError + (reply ? " The previous result remains displayed." : ""))}
          </p>
          <p id="screen-status" class={"screen-message" + (shortOf ? " warning" : "")} aria-live="polite" hidden={!latest}>
            {reply
              ? shortOf
                ? `Only ${reply.picks.length} picks are available for the requested ${to - from + 1} ranks on ${reply.day}.`
                : `Showing ${reply.picks.length} picks valued at the ${reply.day} cached close.`
              : ""}
          </p>
        </form>
      </section>
      <p id="results-state" class={"screen-message" + (stale || missing ? " warning" : "")} role="status" aria-live="polite" hidden={!latest}>
        {stale
          ? "Settings changed — displayed results do not match the current settings. Select Screen latest to update them. Downloads still use the displayed results."
          : missing
            ? "No results for these settings yet. Select Screen latest."
            : ""}
      </p>
      <Latest screen={screen} stale={stale} hidden={!latest} />
      <p id="screen-coverage" class="result-note" hidden={!latest}>
        {reply ? `${marketName(reply.market)} · USD values. Latest cached session: ${reply.day}. ` : ""}FMP historical observations only; coverage is incomplete. Available financial statements may
        include later revisions. Provider prices and corporate-action adjustments can contain errors.
      </p>
      <p id="range-note" class="result-note" aria-live="polite" hidden={!latest}>
        {reply ? `Latest picks · ${reply.day} · Ranks ${from}–${to}, equal weight. No holding returns or future performance are used in this list.` : ""}
      </p>
    </section>
  );
}
