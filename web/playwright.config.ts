import { defineConfig } from "@playwright/test";

// The browser checks: each worker serves its own fictional home with the
// built site (e2e/fixture.ts). Build first: `npm run build` and, from the
// repository root, `cargo build -p bt`.
//
// An assertion returns as soon as it holds, so its timeout costs nothing when
// a check passes: it is set for a slow machine (a debug `bt` on two cores), not
// for a quiet one. A check that still fails after this wait has found a
// real fault. No check is retried.
export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  retries: 0,
  reporter: "list",
  use: { trace: "retain-on-failure" },
});
