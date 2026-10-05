# Phase 2 — Data, News & Macro Intelligence (8–14 weeks)

> Status: **Not started.** Only planning/proposed. Completed upstream: Phase 0 (safety, catalogue, increment4, boundary) and Phase 1 slices 1.1–1.3 (Shell, Scanner, Workspace). Dependencies: Phase 0 domain models partial (`models/` only strategy/user); `base.py` missing. See `docs/phase-5-prerequisites.md` (priority 2).

## User outcome

Gateway has dependable context for US equities without HTML scraping. Provider adapters return normalized records with full provenance (source, fetched_at, data_time, coverage, delay, entitlement). Licensed calendar/news provider integrated. Historical event snapshots enable reproducible backtests. Chart shows event markers with detail inspector.

## Slices (in dependency order)

### Slice 2.1: Provider Adapter Layer (Week 1–3)
**Depends on:** Phase 0 domain models (`Instrument`, `Quote`, `Candle`, `Provenance`), `GATEWAY_ENV` profiles

**Deliverables**
- `quant-app-v1/backend/app/providers/base.py` — abstract `Provider` interface:
  ```python
  class Provider(Protocol):
      def catalogue(self) -> list[Instrument]: ...
      def history(self, instrument: str, interval: str, range: str) -> list[Candle]: ...
      def quote(self, instrument: str) -> Quote: ...
      def news(self, instruments: list[str] | None, since: datetime | None) -> list[NewsItem]: ...
      def calendar(self, countries: list[str] | None, since: datetime | None, until: datetime | None) -> list[EconomicEvent]: ...
      def health(self) -> ProviderHealth: ...  # coverage, delay, status