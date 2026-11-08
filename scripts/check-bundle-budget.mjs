import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { relative, resolve, sep } from "node:path";
import { gzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
// Match the SRS 500 KB per-chunk and 5 MB total gzip budgets. Decimal units
// match Vite's kB output.
const MAX_CHUNK_BYTES = 500 * 1000;
const MAX_TOTAL_GZIP_BYTES = 5 * 1000 * 1000;
// dist-pages is a copy of dist, so enforce the total per artifact instead of
// summing both and counting the same bytes twice.
const targets = process.argv.length > 2 ? process.argv.slice(2) : ["dist", "dist-pages"];

const formatKb = (bytes) => `${(bytes / 1000).toFixed(2)} KB`;
const formatMb = (bytes) => `${(bytes / 1_000_000).toFixed(2)} MB`;
const formatBytes = (bytes) => `${bytes.toLocaleString("en-US")} bytes`;

function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

let failed = false;
const rows = [];
const summaries = [];

for (const target of targets) {
  const directory = resolve(root, target);
  if (!existsSync(directory) || !statSync(directory).isDirectory()) {
    console.error(`Bundle budget check failed: ${target} is missing. Build it before checking.`);
    failed = true;
    continue;
  }

  const files = walk(directory).filter((file) => /\.(?:js|mjs)$/.test(file));
  if (files.length === 0) {
    console.error(`Bundle budget check failed: ${target} has no production JS files.`);
    failed = true;
    continue;
  }

  const chunks = files.map((file) => {
    const source = readFileSync(file);
    return {
      path: relative(root, file).split(sep).join("/"),
      bytes: statSync(file).size,
      gzipBytes: gzipSync(source).length,
    };
  });

  const totalGzip = chunks.reduce((total, chunk) => total + chunk.gzipBytes, 0);
  const largest = chunks.reduce((max, chunk) => Math.max(max, chunk.bytes), 0);
  console.log(
    `${target}: ${chunks.length} JS file(s), largest ${formatKb(largest)}, total gzip ${formatKb(totalGzip)}`,
  );
  summaries.push({ target, totalGzip });
  rows.push(...chunks);
}

rows.sort((a, b) => b.bytes - a.bytes);
if (rows.length > 0) {
  console.log("\nLargest production JS files:");
  for (const chunk of rows.slice(0, 10)) {
    console.log(`  ${formatKb(chunk.bytes).padStart(10)}  ${chunk.path}`);
  }
}

const chunkViolations = rows.filter((chunk) => chunk.bytes > MAX_CHUNK_BYTES);
if (chunkViolations.length > 0) {
  console.error(
    `\nBundle budget exceeded: ${chunkViolations.length} file(s) over ${formatKb(MAX_CHUNK_BYTES)} (${formatBytes(MAX_CHUNK_BYTES)}):`,
  );
  for (const chunk of chunkViolations) {
    console.error(`  ${formatKb(chunk.bytes)} (${formatBytes(chunk.bytes)})  ${chunk.path}`);
  }
  failed = true;
}

const totalViolations = summaries.filter(({ totalGzip }) => totalGzip > MAX_TOTAL_GZIP_BYTES);
if (totalViolations.length > 0) {
  console.error(
    `\nBundle gzip budget exceeded: ${totalViolations.length} artifact(s) over ${formatMb(MAX_TOTAL_GZIP_BYTES)} (${formatBytes(MAX_TOTAL_GZIP_BYTES)}):`,
  );
  for (const summary of totalViolations) {
    console.error(`  ${summary.target}: ${formatMb(summary.totalGzip)} (${formatBytes(summary.totalGzip)}) gzip`);
  }
  failed = true;
}

if (failed) {
  console.error("\nBundle budget check failed.");
  process.exitCode = 1;
} else {
  console.log(
    `\nBundle budget check passed: no JS file exceeds ${formatKb(MAX_CHUNK_BYTES)} (${formatBytes(MAX_CHUNK_BYTES)}) and no artifact exceeds ${formatMb(MAX_TOTAL_GZIP_BYTES)} (${formatBytes(MAX_TOTAL_GZIP_BYTES)}) gzip.`,
  );
}
