# Archived plans (superseded 2026-11-07)

These documents were the working plan set before Gateway's scope was cut to a
**backtesting and demo-trading** product. They are kept for history and for the
audit trail behind the security remediation work; they are **not** requirements
and must not be used to justify building anything.

**Current requirements live in [`../SRS.md`](../SRS.md).** Its §11 traceability
table records, document by document, what survived into the SRS, what was cut,
and what was deferred.

| File | Was | Now |
| --- | --- | --- |
| `phase-0-plan.md` … `phase-9-plan.md` | Ten sequential phase plans (1,709 lines total) | Replaced by SRS §9 phases P1–P6 |
| `phase-5-prerequisites.md` | Dependency tracker for live-trading gates | Gate set deleted with live execution |
| `phase-8-draft.md` | Draft of the external-service layer | Only Supabase survives |
| `gateway-roadmap.md` | Product roadmap and competitive benchmark | §1.1 thesis, §6.5 UX, §6.6 disclaimers |
| `auth0.md` | Dual-auth design (local HS256 + Auth0 RS256) | Auth0 is removed; Supabase Auth only |
| `status.md` | Feature-by-feature completion ledger as of 2026-10-18 | Build facts carried into SRS §3.4 |
| `security.md`, `backups.md`, `monitoring.md`, `legal.md` | 0-byte stubs | Requirements in SRS §6 |
| `terms.md` | Phase-scoped terms | SRS NFR-27…30 |
| `analytics.md`, `cookie.md`, `llms.txt`, `robots.txt` | One-line placeholders / starter artifacts | Deferred |

Two things still referenced from the live tree are **not** archived:

- [`../deployment.md`](../deployment.md) — rewritten for Cloudflare Pages, the API container and Supabase.
- [`../superpowers/specs/`](../superpowers/specs/) — the 2026-10-18 security remediation designs. Their requirements were carried into SRS §6.2 (NFR-6…16) as acceptance gates, so the designs remain useful source material for P6.

Restoring any of this is a `git mv` away — nothing was deleted.
