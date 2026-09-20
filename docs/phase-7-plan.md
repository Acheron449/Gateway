---
#### **`docs/phase-7-plan.md`**
```markdown
# Phase 7 — SEO / Crawlability / Discovery Layer + llms.txt + Backlinks (build transition, 2026-09-20)

> Status: Build-mode authorizations active (user: "create a 7th phase where..."). Build-mode only — implementing the plan document and starter artifacts (sitemap.xml skeleton, robots.txt, llms.txt, canonical/noindex/alt/meta specs); full site crawl, HTTPS enforcement, Core Web Vitals tuning, slug cleanup, backlink execution = subsequent slices requiring hosting access / external outreach.
>
> Source: user request (sitemap.xml + robots.txt + noindex removal + canonical + meta title/description + alt + schema + internal links + broken-link fix + Core Web Vitals + HTTPS + URL slug cleanup + llms.txt + backlink strategy).

## Prerequisites (must complete before production deployment of this layer)

- [ ] Phase 6 OpenBB integration design finalized (`docs/phase-6-plan.md` emitted; source edits pending user confirmation of scope)
- [ ] Phase 5 live-execution prerequisites met (currently BLOCKED: `alpaca_live.py` = 3-line draft; `ENABLE_LIVE_ALPACA` false) — Phase 7 does NOT depend on live broker but should not ship before Phase 5 security/legal gates if this site handles trades
- [ ] Hosting / domain configured: HTTPS certificate active; HTTP→HTTPS redirect enforced; clean URL pipeline (slug normalization)
- [ ] Existing site inventory: crawl baseline (`/robots.txt`, any existing `sitemap.xml`, `llms.txt`, meta tags) — use `curl` / `wget --spider` / `screaming-frog` equivalent
- [ ] Backlink source list compiled (partners, docs references, GitHub repos, data-source citations from OpenBB)

## Slices (high-level, sequential)

### Slice 7.1: Crawl Foundation — sitemap.xml + robots.txt (Week 1–2)
**Focus:** Make the site discoverable to crawlers and LLM agents.

**Deliverables**
- `public/sitemap.xml` (NEW): all indexable pages (landing, docs, phase plans 0–7, openbb integration docs, runbooks, releases); `lastmod` dates; `<priority>` per section; excludes `/admin/`, `/secrets/`, `/.git/` analogs
- `public/robots.txt` (NEW / REPLACEMENT if exists): `User-agent: *` / `Allow: /` / `Disallow: /secrets/ /admin/ /quant-app-v1/backend/app/auth/` / `Sitemap: https://<host>/sitemap.xml`; no `Disallow` of docs or public pages
- `llms.txt` (NEW, root-level): concise site map for LLM consumption — sections = overview, phases, openbb integration, legal, monitoring, runbooks, external refs; include `https://github.com/OpenBB-finance/OpenBB`; format per `llms.txt` convention (plain text, structured headings, no hidden content)
- Crawl verification: `curl -s -o /dev/null -w "%{http_code}" https://<host>/robots.txt`; sitemap validates via `xmllint` or online validator

**Acceptance criteria**
- `https://<host>/sitemap.xml` returns 200 + valid XML; includes `/docs/phase-5-plan.md`, `/docs/phase-6-plan.md`, `/docs/phase-7-plan.md`, `/README.md` (if served)
- `https://<host>/robots.txt` allows `/docs/`; does NOT block `/docs/phase-7-plan.md`
- `llms.txt` present at root; contains section list + key links + OpenBB reference
- No `noindex` directive in robots.txt (see 7.2)

---

### Slice 7.2: Indexability — remove noindex, add canonical (Week 2–3)
**Focus:** Ensure pages are indexable; eliminate duplicate-content signals.

**Deliverables**
- Audit current meta tags: grep / crawl for `<meta name="robots" content="noindex">`; `<meta name="robots" content="noindex, nofollow">`; remove all from `docs/`, `quant-app-v1/frontend/src/`, `README.md`-derived pages
- Add `<link rel="canonical" href="https://<host>/docs/phase-7-plan.md">` to each docs page (and analog for README if served as HTML)
- If using a static site generator / server-rendered docs: inject canonical in template (`<head>`); if manual HTML: edit per file
- Add `X-Robots-Tag: all` header (or remove `noindex` header) via web-server / proxy config (`nginx.conf`, `docker-compose.yml` proxy, or app middleware)
- Remove `<meta name="robots" content="none">` equivalents

**Acceptance criteria**
- Zero `noindex` meta tags across served docs/pages (verified by `grep -rni 'noindex' public/` or crawl)
- Every docs page has canonical pointing to HTTPS version (no `http://`, no trailing slash mismatch)
- HTTP response headers do NOT contain `X-Robots-Tag: noindex`

---

### Slice 7.3: On-page SEO — titles, descriptions, alt, schema (Week 3–5)
**Focus:** Rich snippets, accessibility, and search relevance.

**Deliverables**
- `docs/` and landing page meta titles: `<title>Phase 7 Plan — Gateway / OpenBB Integration — SEO & Discovery</title>` (pattern); `<meta name="description" content="...">` 150–160 chars per page
- `README.md` / landing: description = "Open data platform (OpenBB) + controlled live execution (Alpaca) gateway — docs, phases 0–7, open-source quant infrastructure"
- Alt text: every `<img>` (logo, diagram, OpenBB badge) gets `alt="OpenBB open data platform logo"` / `alt="Gateway phase architecture diagram"`; no empty `alt=""` on meaningful images; decorative images get `alt=""` explicitly
- Schema markup (JSON-LD `<script type="application/ld+json">`): `WebSite` (name, url, description), `SoftwareApplication` (name=Gateway, applicationCategory=FinancialApplication, offers=Free, url=repo URL), `Organization` (name=Gateway / OpenBB reference); add to landing / docs index
- Internal links: cross-link `docs/phase-6-plan.md` → `docs/phase-5-plan.md` (prerequisites reference) and → `docs/phase-7-plan.md` (this); `README.md` links to all phase docs; `llms.txt` links to all phases; avoid orphan pages

**Acceptance criteria**
- Every served HTML page has unique `<title>` and `<meta description>` (no duplicates across phases)
- All images have non-empty `alt` (except decorative with explicit `alt=""`)
- Schema JSON-LD validates via Google Rich Results / Schema validator (at least no syntax errors)
- Internal link graph: each doc page has ≥2 internal links (to other docs or landing); crawl shows <10% orphan rate

---

### Slice 7.4: Link Hygiene — broken links + URL slugs (Week 5–6)
**Focus:** Fix 404s; clean URLs.

**Deliverables**
- Broken-link scan: `wget --spider -r -nd -nv -l 3 https://<host>/` or `lychee` / `linkchecker` across docs/; list 404s
- Fix broken links: update `README.md` refs, docs cross-links, `llms.txt` links; replace dead external URLs (OpenBB docs, Alpaca docs) with current equivalents
- URL slug cleanup: enforce lowercase, hyphen-separated (`docs/phase-7-plan.md` not `docs/Phase-7-plan.md`); redirect old cases (`rewrite ^/docs/Phase-7-plan.md$ /docs/phase-7-plan.md permanent;`)
- Remove trailing-slash inconsistencies; enforce one canonical form (prefer no-trailing-slash for docs files; with-trailing for directories if served)
- Add `404.html` with sitemap/llms links

**Acceptance criteria**
- Broken-link scan reports 0 broken links on `/docs/` and landing (allow external if unavoidable, document)
- All doc URLs lowercase + hyphenated; 301 redirects from old variants
- `curl -IL` on cleaned URLs returns 200 + correct `Content-Type`

---

### Slice 7.5: Performance — Core Web Vitals (Week 6–7)
**Focus:** Speed, interactivity, visual stability.

**Deliverables**
- Measure baseline: Lighthouse / PageSpeed Insights / `lighthouse-cli` for landing + `docs/phase-7-plan.md` (if rendered as HTML); record LCP, INP, CLS
- Optimizations (apply to static site / server config):
  - Image compression (WebP/AVIF where possible; responsive `srcset`)
  - Font loading: `font-display: swap`; preload critical fonts
  - CSS/JS: minify; defer non-critical JS; eliminate render-blocking resources
  - Caching: `Cache-Control: public, max-age=3600` for static assets; ETag / Last-Modified headers
  - Server response: TTFB < 200ms (hosting / CDN / Docker resource limits)
- If using frontend build (`quant-app-v1/frontend`): configure Vite / webpack split chunks; prefetch docs links

**Acceptance criteria**
- Lighthouse score ≥ 90 (Performance / Accessibility / Best Practices / SEO) for docs index; ≥ 85 for deepest doc page
- LCP < 2.5s; INP < 200ms; CLS < 0.1
- All static assets served with `Cache-Control`; no 404 resources (verify via DevTools Network / crawl)

---

### Slice 7.6: Security / Transport — HTTPS enforcement (Week 7)
**Focus:** Encrypt all traffic; eliminate mixed content.

**Deliverables**
- HTTPS redirect: `nginx` or proxy config: `if ($scheme = http) { return 301 https://$host$request_uri; }`
- HSTS header: `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`
- Mixed-content scan: `grep -rni 'http://' docs/` (if HTML generated) / crawl for `http://` assets; replace with `https://`
- Certificate: valid (not expired); SNI configured; auto-renewal (Let's Encrypt / certbot) documented
- If internal: internal CA certs; if public: standard TLS 1.3 / 1.2

**Acceptance criteria**
- `curl -I -L http://<host>/docs/phase-7-plan.md` returns 301 → 200 on HTTPS
- Zero `Mixed Content` warnings in browser console (verify via crawl / Lighthouse)
- SSL Labs / testssl.sh: A or A+ rating

---

### Slice 7.7: Backlink Strategy + llms.txt refinement (Week 8–10)
**Focus:** Visibility through citations, references, and structured LLM access.

**Deliverables**
- `llms.txt` (refined): full site index; include `https://github.com/OpenBB-finance/OpenBB`; section descriptions (Phase 0–7); key endpoints (`/docs/phase-6-plan.md`, `/docs/phase-7-plan.md`); no hidden sections; avoid marketing fluff — factual index
- Backlink source list (documented in `docs/backlink-strategy.md` or this section):
  - OpenBB repo reference (cite OpenBB docs / README); GitHub repo link to Gateway / docs
  - Partner / source citations: Alpaca docs, FINRA / SEC guidance (if relevant to Phase 5), quantitative finance reference sources
  - Data-source citations: OpenBB equity/crypto integrations (each integration gets a backlink citation)
  - Internal backlinks: every phase doc links to every other phase doc + landing; sitemap links to llms.txt; robot links to sitemap
- Outreach / submission (if applicable): submit sitemap to search engines; add site to OpenBB / partner directories; share `llms.txt` with LLM-tool registries
- Backlink tracking: spreadsheet or `docs/backlinks-tracker.md` with URL, source, date, status (requested / live / removed)

**Acceptance criteria**
- `llms.txt` updated with 7-phase index + OpenBB link + key doc URLs
- Backlink source list has ≥10 sources (partner, data, reference) documented; ≥3 live backlinks verified by crawl
- Sitemap submitted / referenced; no orphan docs (all linked from index / sitemap / llms.txt)

---

## File Paths (new + modified)

**New artifacts (built in this phase)**
- `public/sitemap.xml` (or `docs/sitemap.xml` + server copy)
- `public/robots.txt`
- `llms.txt` (root / served root)
- `docs/phase-7-plan.md` (this document — emitted during build)
- `docs/backlink-strategy.md` (optional, if tracking needs separate file)

**Modified (apply per slice)**
- All docs pages (`docs/phase-0-plan.md` … `docs/phase-7-plan.md`): meta title / description / canonical / alt / schema / internal links — can be batch-edited via `sed` / Python / static-gen template; if manual: edit per file
- `README.md`: meta-style header / link updates; backlink citations
- `quant-app-v1/frontend/src/` (if HTML served from frontend): meta injection templates; image `alt` updates; schema JSON-LD in `index.html`
- `nginx.conf` / `docker-compose.yml` / proxy: HTTPS redirect, HSTS, cache headers, `robots.txt` / `sitemap.xml` root mapping
- `requirements.txt` / build: Lighthouse CLI / `lychee` / `linkchecker` if added as dev dependencies

## Dependency / License / Compatibility Notes

- No new runtime dependency required for SEO layer (pure static / server config). Dev dependencies optional: `lighthouse`, `lychee`, `xmllint`.
- OpenBB reference (`https://github.com/OpenBB-finance/OpenBB`) stays AGPLv3 — backlink / citation does not alter license of Gateway code.
- Phase 7 assumes site is served (static or app); if repo-only (no hosting), slices 7.1 (serve sitemap/robots) and 7.6 (HTTPS) apply only when deployed.

## Acceptance Criteria (from this plan + user request)

- [ ] `sitemap.xml` present, valid XML, includes all phase docs + `llms.txt`
- [ ] `robots.txt` allows `/docs/`; no `noindex`
- [ ] `llms.txt` present at root; contains structured site map + OpenBB link
- [ ] Zero `noindex` meta tags / headers (verified by crawl / grep)
- [ ] Canonical tags on every doc page (HTTPS, canonical URL)
- [ ] Meta titles + descriptions unique per page
- [ ] All images have `alt` (decorative explicit `alt=""`)
- [ ] Schema markup (JSON-LD) on landing / docs index; validates
- [ ] Internal links: each doc page links to ≥2 others; <10% orphan
- [ ] Broken links: 0 on site (external documented separately)
- [ ] URL slugs: lowercase, hyphenated; old variants redirect (301)
- [ ] Core Web Vitals: LCP <2.5s, INP <200ms, CLS <0.1; Lighthouse ≥85
- [ ] HTTPS enforced (301 from HTTP; HSTS; SSL A+); zero mixed content
- [ ] Backlink strategy document / list live; ≥3 verified backlinks
- [ ] Phase 6 reference maintained (`docs/phase-6-plan.md` links preserved); no regression to Phase 5 prerequisites

## Intentionally Unavailable (until explicitly authorized / until prerequisites met)

- Phase 5 live broker activation (still BLOCKED — `alpaca_live.py` draft); Phase 7 does NOT unlock it
- Production deployment of Phase 7 on a live trading domain until Phase 5 legal/security gates complete (if domain handles trading data)
- Paid backlink / SEO agency execution (plan defines strategy; execution is user-authorized separately)
- Removal of AGPLv3 attribution for OpenBB references (must remain)

## Build / Transition Notes

- Mode shifted from plan → build (system reminder, 2026-09-20). This document is the phase plan; starter artifacts (sitemap skeleton, robots.txt, llms.txt skeleton) will be emitted as separate file operations if user confirms.
- All 8 prior clarifications (scope/filename/dependency) from Phase 6 do NOT apply here — Phase 7 is self-contained (SEO/discovery) with only Phase 5/6 prerequisites noted.
- User request: "create a 7th phase where..." — all listed items covered in slices 7.1–7.7. If any item needs deeper spec (e.g., exact schema markup JSON), ask; otherwise proceed with starter artifacts.

---

### Append 7.8 (build add): Custom 404 + Cookie Banner + Terms + Analytics + Above-the-Fold CTA
**Status:** Added per user (build mode, 2026-09-20).

- `public/404.html` — custom 404; links back to sitemap, llms.txt, docs index; branded header/footer; meta title = "Not Found — Gateway"; noindex none (use `noindex` intentionally on 404? Standard: allow crawl of 404 page but don't index; add `<meta robots="noindex">` only if desired — here kept indexable for error-logging but with canonical to root).
- `public/cookie-banner.html` (or injected in `<head>` / banner component): banner text ("We use cookies for analytics and site improvement."); Accept / Reject buttons; links to terms; stores consent in `localStorage` / cookie `gateway_cookie_consent`; respects `Do Not Track`.
- `docs/terms.md` — Terms of Service / Terms page; covers open-source license (AGPLv3 for OpenBB references), data use, no-live-trading guarantee until Phase 5 gates passed, liability disclaimer (mirror OpenBB disclaimer style), cookie/analytics disclosure.
- Analytics: `public/analytics.html` / embedded snippet — Google Analytics / Plausible / Matomo (privacy-respecting); expose `G-XXXX` / site ID via config; only load after cookie consent; no tracking before consent; document in `docs/phase-7-plan.md`.
- CTA above the fold: `<section id="cta-above-fold">` / banner component on landing (`README.md` / index): headline ("Open Data + Controlled Execution"), sub ("Phase 5 live broker | Phase 6 OpenBB integration | Phase 7 SEO / discovery"), action buttons ("Read Phase 7 Plan", "OpenBB Data", "Live Status — Paper Only"). Placed at top of landing, before docs list; accessible; responsive.

**Acceptance criteria (append)**
- `curl -I https://<host>/nonexistent` returns 404 with `public/404.html` content (custom branding, sitemap/llms links, meta title)
- Cookie banner visible on first visit; Accept/Reject functional; no analytics load before consent; banner respects `localStorage`
- `/docs/terms.md` (or `/terms`) returns 200; covers AGPLv3, no-live-trading, cookies/analytics, liability; links from cookie banner + footer
- Analytics snippet present; only fires post-consent; no PII in URL/query; privacy policy referenced
- CTA visible above docs/index; responsive; links to Phase 7 / Phase 6 / live-status; ARIA labels present
