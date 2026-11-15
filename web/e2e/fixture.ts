import { expect, type Page, test as base } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer, type Server as TcpServer, type Socket } from "node:net";
import { createInterface } from "node:readline";
import type { AddRun } from "../src/api/AddRun.ts";
import type { RunRow } from "../src/api/RunRow.ts";
import type { RunsReply } from "../src/api/RunsReply.ts";
import type { Schedule } from "../src/api/Schedule.ts";
import type { StrategyFile } from "../src/api/StrategyFile.ts";
import type { Variable } from "../src/api/Variable.ts";

const root = new URL("../..", import.meta.url).pathname;
/** The `bt` that `cargo build -p bt` (or `cargo test`) builds. */
const BT = join(root, "target/debug/bt");
/** The as-of time of the fictional fixture's expected tables. */
const AS_OF = "2023-06-30T07:30:00+00:00";

/** The schedule of the long run: 1,000 weekly trials over seven and a half
 *  years of the fictional US data, ranks 1 to 50: about 40 s with a debug
 *  `bt` on a quiet machine. A check stops it as soon
 *  as it has seen it running and its time since start grow, so it only has to
 *  outlast the page's next read of the run list (every 2 s while a run waits
 *  or runs) and a slow machine's delays. Enlarge the window or shorten the
 *  interval, or rank more, if a check fails because the run ended before the
 *  page showed it running. */
const LONG_RUN: Schedule = { start: "2016-01-04", end: "2023-06-28", every: "1w", trials: 1000 };

/** How long a short run may take to end (ms): far above what a quiet machine
 *  needs, because a wait that ends as soon as the run has ended costs nothing. */
const RUN_TIMEOUT = 90_000;

/** Makes the page read the run list now, as it does when it becomes visible.
 *  Use it after a change made through the API: the page learns of it at its
 *  next read, which is up to 15 s away when no run waits or runs. */
export const reread = (page: Page) => page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));

/** The canonical form that `bt check` prints for a strategy file. */
export function canonical(strategy: StrategyFile): StrategyFile {
  const dir = mkdtempSync(join(tmpdir(), "bt-check-"));
  try {
    writeFileSync(join(dir, "strategy.json"), JSON.stringify(strategy));
    const reply = JSON.parse(execFileSync(BT, ["check", join(dir, "strategy.json")], { encoding: "utf8" })) as { files: { canonical: string }[] };
    return JSON.parse(reply.files[0]!.canonical) as StrategyFile;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

/** The data provider of one worker's server: a local TCP port that never
 *  gives a reply, so no update of a check can save a raw file: the home's
 *  `raw/` is a link to the tracked `fixtures/fictional/raw`, and a check that
 *  needs replies must use a copy.
 *  `bt serve` takes its address as `BT_PROVIDER`; the update that the page
 *  starts is its child and has the same environment. */
export type Provider = {
  /** What it does with a connection: `close` it at once (the client sees no
   *  reply and tries again, three times in all), or `hold` it open. */
  mode: "close" | "hold";
  /** Closes the connections held so far. */
  release(): void;
};

/** One fictional home served by `bt serve`, for one worker. */
export type Home = {
  /** `http://127.0.0.1:PORT`, also the tests' baseURL. */
  url: string;
  /** The home folder: `raw` and `web` are links, `data/` is its own. */
  dir: string;
  /** The provider of the home's server. */
  provider: Provider;
  /** Prepares the home again at the fixture's as-of time. An update that
   *  is not stopped prepares the home at the time now, which moves the last
   *  session that the other checks read. */
  prepare(): void;
  /** Sends a request as the website does (with its Origin); returns the
   *  JSON reply, or throws with the status and the server's message. */
  api<T>(method: string, path: string, body?: unknown): Promise<T>;
  /** Adds the long run (LONG_RUN, ranked by EBITDA yield) under `name`;
   *  it waits, or runs at once when the queue is not paused. */
  addLongRun(name: string): Promise<RunRow>;
  /** Leaves the home with no run and no variable, and a queue that is not
   *  paused. The home lives as long as its worker, so a file that needs
   *  a clean list calls it first. */
  reset(): Promise<void>;
  /** Waits until run `id` is complete or failed, and returns it. */
  finished(id: number): Promise<RunRow>;
  /** Waits until no run waits or runs. */
  idle(): Promise<void>;
  /** Runs `shown`, the checks that the page shows run `id` waiting or
   *  running. When they fail because the run already ended, the error names
   *  LONG_RUN to enlarge. */
  whileRunning(id: number, shown: () => Promise<void>): Promise<void>;
};

type Server = { url: string; stop: () => Promise<void> };

/** Listens on a free local port as the worker's provider. */
async function listen(): Promise<{ address: string; provider: Provider; stop: () => Promise<void> }> {
  const held = new Set<Socket>();
  const provider: Provider = {
    mode: "close",
    release: () => {
      for (const socket of held) socket.destroy();
      held.clear();
    },
  };
  const tcp: TcpServer = createServer((socket) => {
    socket.on("error", () => {});
    if (provider.mode === "hold") held.add(socket);
    else socket.destroy();
  });
  await new Promise<void>((resolve) => tcp.listen(0, "127.0.0.1", resolve));
  const port = (tcp.address() as { port: number }).port;
  return {
    address: `http://127.0.0.1:${port}`,
    provider,
    stop: () => {
      provider.release();
      return new Promise<void>((resolve) => tcp.close(() => resolve()));
    },
  };
}

/** Starts `bt serve --port 0` on `home` and reads its `{"serving": url}`
 *  line. A server that does not start is stopped (if it runs) before the
 *  error is thrown.
 *
 *  The server never sees the real provider or the real key, whatever a
 *  check does: a click on Update data starts `bt data update` with the
 *  server's environment. `HOME` is a private folder that holds a made-up
 *  key, and `BT_PROVIDER` is the local `provider`. */
async function serve(home: string, user: string, provider: string): Promise<Server> {
  const env = { ...process.env, HOME: user, BT_PROVIDER: provider };
  const child = spawn(BT, ["serve", "--port", "0", "--home", home], { stdio: ["ignore", "pipe", "inherit"], env });
  const ended = new Promise<void>((resolve) => {
    child.once("exit", () => resolve());
    child.once("error", () => resolve());
  });
  const stop = async () => {
    if (child.pid !== undefined && child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
    await ended;
  };
  const lines = createInterface({ input: child.stdout! });
  try {
    const first = await new Promise<string>((resolve, reject) => {
      lines.once("line", resolve);
      child.once("error", (error) => reject(new Error(`bt serve could not start: ${error.message}`)));
      child.once("exit", (code) => reject(new Error(`bt serve exited with ${code} before it was ready`)));
    });
    let url: unknown;
    try {
      url = (JSON.parse(first) as { serving?: unknown }).serving;
    } catch {}
    if (typeof url !== "string") throw new Error(`bt serve did not start: ${first}`);
    return { url, stop };
  } catch (error) {
    await stop();
    throw error;
  } finally {
    lines.close();
    child.stdout!.resume();
  }
}

export const test = base.extend<{}, { home: Home }>({
  home: [
    async ({}, use) => {
      if (!existsSync(BT)) throw new Error(`${BT} is missing: run cargo build -p bt in ${root}`);
      if (!existsSync(join(root, "web/dist/index.html"))) throw new Error("web/dist is missing: run npm run build");
      const dir = mkdtempSync(join(tmpdir(), "bt-web-"));
      let server: Server | undefined;
      let listener: Awaited<ReturnType<typeof listen>> | undefined;
      try {
        const home = join(dir, "home");
        mkdirSync(home);
        // A link to the tracked fixture: no check saves a raw file through it (the provider gives no reply); a check that needs replies must use a copy.
        symlinkSync(join(root, "fixtures/fictional/raw"), join(home, "raw"));
        symlinkSync(join(root, "web/dist"), join(home, "web"));
        execFileSync(BT, ["data", "prepare", "--as-of", AS_OF, "--home", home], { stdio: "ignore" });
        const user = join(dir, "user");
        mkdirSync(join(user, ".grok/secrets"), { recursive: true });
        writeFileSync(join(user, ".grok/secrets/fmp_api_key"), "made-up-key-for-the-browser-checks\n");
        listener = await listen();
        server = await serve(home, user, listener.address);
        const url = server.url;
        const api = async <T,>(method: string, path: string, body?: unknown): Promise<T> => {
          const response = await fetch(url + path, {
            method,
            headers: { Origin: url, "Content-Type": "application/json" },
            body: body === undefined ? undefined : JSON.stringify(body),
          });
          const reply = (await response.json()) as T & { error?: { message: string; place: string } };
          if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${reply.error?.message} (${reply.error?.place})`);
          return reply;
        };
        const strategy = { sleeves: [{ steps: [{ rank: "EBITDA yield", order: "highest" as const, from: 1, to: 50 }] }] };
        await use({
          url,
          dir: home,
          provider: listener.provider,
          prepare: () => void execFileSync(BT, ["data", "prepare", "--as-of", AS_OF, "--home", home], { stdio: "ignore" }),
          api,
          addLongRun: (name) => api<RunRow>("POST", "/api/runs", { name, market: "us", schedule: LONG_RUN, strategy } satisfies AddRun),
          reset: async () => {
            // Paused, so that no deleted run is followed by another start.
            await api("PUT", "/api/queue", { paused: true });
            for (const run of (await api<RunsReply>("GET", "/api/runs")).runs) {
              if (run.locked) await api("PATCH", `/api/runs/${run.id}`, { locked: false });
              await api("DELETE", `/api/runs/${run.id}`);
            }
            for (const variable of (await api<Variable[]>("GET", "/api/variables")).reverse()) await api("DELETE", `/api/variables/${variable.id}`);
            await api("PUT", "/api/queue", { paused: false });
          },
          finished: async (id) => {
            await expect
              .poll(async () => (await api<RunRow>("GET", `/api/runs/${id}`)).state, { timeout: RUN_TIMEOUT, message: `run ${id} ends` })
              .toMatch(/^(complete|failed)$/);
            return api<RunRow>("GET", `/api/runs/${id}`);
          },
          idle: async () => {
            const active = async () => (await api<RunsReply>("GET", "/api/runs")).runs.filter((run) => run.state === "waiting" || run.state === "running").length;
            await expect.poll(active, { timeout: RUN_TIMEOUT, message: "every run has ended" }).toBe(0);
          },
          whileRunning: async (id, shown) => {
            try {
              await shown();
            } catch (error) {
              const run = await api<RunRow>("GET", `/api/runs/${id}`);
              if (run.state === "complete" || run.state === "failed")
                throw new Error(`The long run ended (${run.state}) before the page showed it: enlarge LONG_RUN in e2e/fixture.ts.`, { cause: error });
              throw error;
            }
          },
        });
      } finally {
        await server?.stop();
        await listener?.stop();
        rmSync(dir, { recursive: true, force: true });
      }
    },
    { scope: "worker", timeout: 120_000 },
  ],
  baseURL: async ({ home }, use) => use(home.url),
});

export { expect };
