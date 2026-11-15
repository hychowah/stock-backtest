import type { MarketStatus } from "../api/MarketStatus.ts";
import { client } from "../client.ts";
import { count, formatTime, marketName } from "../format.ts";
import { useRead } from "../read.ts";

/** The data page: what data each market has, from `GET /api/data/status`. */
export function DataPage() {
  const status = useRead(client.dataStatus, []);
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
        {status.state === "loading" && <p class="hint">Checking the data…</p>}
        {status.state === "failed" && <p id="data-error" role="alert">{status.failure.message}</p>}
        {status.state === "done" && status.value.markets.map((market) => <Market key={market.market} status={market} />)}
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
