import { cpSync, existsSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const dist = resolve(root, "dist");
const out = resolve(root, "dist-pages");

if (!existsSync(resolve(dist, "index.html"))) {
  console.error("Pages build failed: dist/index.html is missing. Run `npm run build` first.");
  process.exit(1);
}

// Workers static assets rejects a catch-all _redirects rule. The Pages
// artifact is separate so adding Pages' SPA fallback cannot break Workers.
if (existsSync(resolve(dist, "_redirects"))) {
  console.error("Pages build failed: dist/_redirects exists; the Workers artifact must stay clean.");
  process.exit(1);
}

rmSync(out, { recursive: true, force: true });
cpSync(dist, out, { recursive: true });
writeFileSync(resolve(out, "_redirects"), "/* /index.html 200\n");

console.log("Pages artifact written to dist-pages/ with SPA fallback.");
