import { expect, test as base } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline";
import type { AddRun } from "../src/api/AddRun.ts";
import type { RunRow } from "../src/api/RunRow.ts";
import type { Schedule } from "../src/api/Schedule.ts";

const root = new URL("../..", import.meta.url).pathname;
/** The `bt` that `cargo build -p bt` (or `cargo test`) builds. */
const BT = join(root, "target/debug/bt");
/** The as-of time of the fictional fixture's expected tables. */
const AS_OF = "2023-06-30T07:30:00+00:00";

/** The schedule of the long run: 1,000 weekly trials over seven and a half
 *  years of the fictional US data. It must run long enough for a check to see
 *  it running and its time since start grow, after the page's next read of
 *  the run list (every 2 s while a run waits or runs). Enlarge it (a longer
 *  window or a shorter interval) if a check fails because the run ended
 *  before the page showed it running. */
const LONG_RUN: Schedule = { start: "2016-01-04", end: "2023-06-28", every: "1w", trials: 1000 };

/** One fictional home served by `bt serve`, for one worker. */
export type Home = {
  /** `http://127.0.0.1:PORT`, also the tests' baseURL. */
  url: string;
  /** The home folder: `raw` and `web` are links, `data/` is its own. */
  dir: string;
  /** Sends a request as the website does (with its Origin); returns the
   *  JSON reply, or throws with the status and the server's message. */
  api<T>(method: string, path: string, body?: unknown): Promise<T>;
  /** Adds the long run (LONG_RUN, ranked by EBITDA yield) under `name`;
   *  it waits, or runs at once when the queue is not paused. */
  addLongRun(name: string): Promise<RunRow>;
  /** Runs `shown`, the checks that the page shows run `id` waiting or
   *  running. When they fail because the run already ended, the error names
   *  LONG_RUN to enlarge. */
  whileRunning(id: number, shown: () => Promise<void>): Promise<void>;
};

type Server = { url: string; stop: () => Promise<void> };

/** Starts `bt serve --port 0` on `home` and reads its `{"serving": url}`
 *  line. A server that does not start is stopped (if it runs) before the
 *  error is thrown. */
async function serve(home: string): Promise<Server> {
  const child = spawn(BT, ["serve", "--port", "0", "--home", home], { stdio: ["ignore", "pipe", "inherit"] });
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
      try {
        const home = join(dir, "home");
        mkdirSync(home);
        symlinkSync(join(root, "fixtures/fictional/raw"), join(home, "raw"));
        symlinkSync(join(root, "web/dist"), join(home, "web"));
        execFileSync(BT, ["data", "prepare", "--as-of", AS_OF, "--home", home], { stdio: "ignore" });
        server = await serve(home);
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
        const strategy = { sleeves: [{ steps: [{ rank: "EBITDA yield", order: "highest" as const, from: 1, to: 5 }] }] };
        await use({
          url,
          dir: home,
          api,
          addLongRun: (name) => api<RunRow>("POST", "/api/runs", { name, market: "us", schedule: LONG_RUN, strategy } satisfies AddRun),
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
        rmSync(dir, { recursive: true, force: true });
      }
    },
    { scope: "worker" },
  ],
  baseURL: async ({ home }, use) => use(home.url),
});

export { expect };
