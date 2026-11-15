// Writes the website to dist/: index.html with main.js and main.css, and
// data.html with data.js and data.css. `bt serve` serves a home's `web/`
// folder, which links to or holds a copy of dist/.
import { build } from "esbuild";
import { copyFileSync, mkdirSync, rmSync } from "node:fs";

const out = new URL("dist/", import.meta.url).pathname;
rmSync(out, { recursive: true, force: true });
mkdirSync(out);
await build({
  entryPoints: { main: "src/main.tsx", data: "src/data/main.tsx" },
  absWorkingDir: new URL(".", import.meta.url).pathname,
  bundle: true,
  format: "esm",
  target: "es2023",
  jsx: "automatic",
  jsxImportSource: "preact",
  sourcemap: true,
  outdir: out,
  logLevel: "warning",
});
for (const page of ["index.html", "data.html"]) copyFileSync(new URL(page, import.meta.url), out + page);
