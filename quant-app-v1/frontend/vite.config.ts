import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// Canonical public origin for robots.txt and sitemap.xml. Pages sets
// VITE_SITE_URL to the project's pages.dev domain (or a custom domain);
// local builds fall back to the dev-server origin.
const siteOrigin = (process.env.VITE_SITE_URL || "http://localhost:5173").replace(/\/+$/, "");

const SITEMAP_PATHS = [
  { path: "/", priority: "1.0" },
  { path: "/app/overview", priority: "0.9" },
  { path: "/app/backtests", priority: "0.8" },
] as const;

function siteFiles(): Plugin {
  return {
    name: "gateway-site-files",
    apply: "build",
    generateBundle() {
      const robots = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /secrets/",
        "Disallow: /admin/",
        `Sitemap: ${siteOrigin}/sitemap.xml`,
        "",
      ].join("\n");
      const entries = SITEMAP_PATHS.map(
        ({ path, priority }) =>
          `  <url><loc>${siteOrigin}${path}</loc><lastmod>2026-11-07</lastmod><priority>${priority}</priority></url>`,
      ).join("\n");
      const sitemap = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        entries,
        "</urlset>",
        "",
      ].join("\n");

      this.emitFile({ type: "asset", fileName: "robots.txt", source: robots });
      this.emitFile({ type: "asset", fileName: "sitemap.xml", source: sitemap });
    },
  };
}

export default defineConfig({
  plugins: [react(), siteFiles()],
  server: { port: 5173 },
});
