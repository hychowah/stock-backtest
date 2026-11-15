import { useState } from "preact/hooks";
import type { MarketStatus } from "../api/MarketStatus.ts";
import type { UpdateState } from "../api/UpdateState.ts";
import type { UpdateStatus } from "../api/UpdateStatus.ts";
import { client } from "../client.ts";
import { count, formatTime, marketName, since } from "../format.ts";
import { changeData, useDataStatus, useNow } from "../live.ts";
import { asFailure } from "../read.ts";
import { errorNote } from "../runs.ts";
import { active, counts, headline, startButton, steps, stopButton } from "./update.ts";

/** The data page: the update of the data and what data each market has, from
 *  `GET /api/data/status`. The update runs in its own process (`bt data
 *  update`), which the page starts and stops and whose state it only reads. */
export function DataPage() {
  const status = useDataStatus();
  return (
    <main>
      <header>
        <a href="index.html">← Strategy builder</a>
        <span class="eyebrow">Backtest data</span>
      </header>
      <h1>
        Keep your data
        <br />
        ready for backtests.
      </h1>
      <p class="intro">
        Backtests and latest picks read the prepared data of each market. Your saved backtests stay unchanged. Returns and filters use USD; all markets compare against SPY total return.
      </p>
      <section class="panel update-panel" aria-labelledby="update-title">
        <h2 id="update-title">Your data</h2>
        {status.failure && <p id="data-error" class="data-error" role="alert">{status.failure.message}</p>}
        {status.value === null && !status.failure && <p class="hint">Checking the data…</p>}
        {status.value && (
          <>
            <Update update={status.value.update} />
            {status.value.markets.map((market) => <Market key={market.market} status={market} />)}
          </>
        )}
      </section>
      <footer>No downloads start when you open this page.</footer>
    </main>
  );
}

/** One market: whether it is ready, its sessions, and its prepared generation. */
function Market({ status }: { status: MarketStatus }) {
  const prepared = status.prepared;
  return (
    <section aria-label={marketName(status.market)} data-market={status.market}>
      <h3>{marketName(status.market)}</h3>
      <div class="data-status">
        <div>
          <span>Status</span>
          <strong>{prepared ? "Ready for backtests" : status.raw ? "Not prepared" : "No saved data"}</strong>
          <small>{status.raw ? "Raw data saved" : "No raw data"}</small>
        </div>
        <div>
          <span>Prices through</span>
          <strong>{prepared?.last_session ?? "No prepared session"}</strong>
          <small>{prepared?.first_session ? "From " + prepared.first_session : "Latest completed market session"}</small>
        </div>
        <div>
          <span>Prepared</span>
          <strong>{prepared ? formatTime(prepared.as_of) : "Not prepared"}</strong>
          <small>{prepared ? `Generation ${prepared.generation} · ${count(prepared.companies)} companies` : ""}</small>
        </div>
      </div>
    </section>
  );
}

/** The update: its state, the buttons, the steps with the current one marked,
 *  the counts, and what failed. */
function Update({ update }: { update: UpdateStatus }) {
  const [asking, setAsking] = useState(false);
  // A refusal belongs to the state it came in: it goes when the state changes.
  const [refused, setRefused] = useState<{ message: string; state: UpdateState } | null>(null);
  // The update (by its start time) that a stop was asked for: the stop reply
  // still says running until the update itself writes `stopping`.
  const [stopAsked, setStopAsked] = useState<string | null>(null);
  const progress = update.progress;
  const state = update.state === "running" && progress && stopAsked === progress.started ? "stopping" : update.state;
  const now = useNow(active(state));
  const start = startButton(state);
  const stop = stopButton(state);
  /** Sends one action; a refusal (409 when the update's state changed meanwhile) is shown beside the buttons. */
  async function send(action: () => Promise<UpdateStatus>) {
    setAsking(true);
    setRefused(null);
    try {
      await changeData(action);
    } catch (thrown) {
      setRefused({ message: asFailure(thrown).message, state: update.state });
    }
    setAsking(false);
  }
  return (
    <section aria-label="Update" id="data-update-panel">
      <div class="data-status">
        <div>
          <span>Update</span>
          <strong>{headline(state)}</strong>
          <small>{progress ? counts(progress) : ""}</small>
        </div>
        <div>
          <span>Last complete update</span>
          <strong>{update.last_success ? formatTime(update.last_success) : "None yet"}</strong>
        </div>
        {progress && active(state) && (
          <div>
            <span>Elapsed</span>
            <strong>{since(progress.started, now)}</strong>
          </div>
        )}
      </div>
      <div class="actions">
        <button type="button" class="primary" disabled={!start.enabled || asking} onClick={() => send(client.startUpdate)}>
          {start.label}
        </button>
        {stop && (
          <button
            type="button"
            disabled={!stop.enabled || asking}
            onClick={async () => {
              if (progress) setStopAsked(progress.started);
              await send(client.stopUpdate);
            }}
          >
            {stop.label}
          </button>
        )}
      </div>
      {refused?.state === update.state && <p class="data-error" role="alert">{refused.message}</p>}
      {progress && (
        <>
          <ol id="data-steps" aria-label="Update steps">
            {steps({ ...progress, state }).map((step) => (
              <li key={step.label} aria-current={step.mark === "current" ? "step" : undefined}>
                {step.mark === "done" ? "✓ " : ""}
                {step.label}
              </li>
            ))}
          </ol>
          {progress.error && <p class="data-error" role="alert">{errorNote(progress.error)}</p>}
          {progress.failures.length > 0 && (
            <>
              <ul id="data-failures" class="hint">
                {progress.failures.map((failure, i) => (
                  <li key={i}>{errorNote(failure)}</li>
                ))}
              </ul>
              {progress.failed > progress.failures.length && <p class="hint">The first {progress.failures.length} failed items are listed.</p>}
            </>
          )}
        </>
      )}
      <p class="hint">You can close this page while an update runs. If the update stops, choose Continue update: what it saved is kept.</p>
    </section>
  );
}
