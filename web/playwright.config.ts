import { defineConfig } from "@playwright/test";

// The browser checks: each worker serves its own fictional home with the
// built site (e2e/fixture.ts). Build first: `npm run build` and, from the
// repository root, `cargo build -p bt`.
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  reporter: "list",
  use: { trace: "retain-on-failure" },
});
