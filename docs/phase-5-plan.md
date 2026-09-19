
---

#### **`docs/phase-5-plan.md`**
```markdown
# Phase 5 — Controlled Live Execution (30+ weeks)

## Prerequisites (ALL must be complete before starting)

- [ ] Phase 4 paper reconciliation proven over ≥1000 paper trades with <0.1% discrepancy
- [ ] Security review completed (pen test, dependency audit, secrets management)
- [ ] Legal/compliance review for target jurisdiction (US: FINRA/SEC considerations)
- [ ] User explicitly authorizes live trading scope in writing
- [ ] `GATEWAY_EXECUTION_MODE=paper` still default; live opt-in only

## Slices (high-level, sequential)

### Slice 5.1: First Broker Adapter (Week 1–6)
**Focus:** One broker (Alpaca live), single asset class (US equities), documented capabilities/limitations

**Deliverables**
- `quant-app-v1/backend/app/providers/alpaca_live.py` — extends `alpaca_provider.py` with live endpoints
- Idempotency: every order gets `client_order_id` (UUID v7); broker dedup on retry
- Partial fill handling: `Fill` events with `liquidity` flag; position updates incremental
- Reconciliation job: `cron` every 5 min — compare local `orders`/`fills`/`positions` vs broker API; alert on drift > threshold
- Account sync: `GET /api/v1/live/account` — cash, buying power, positions from broker
- Feature flag: `ENABLE_LIVE_ALPACA` (default false)

**Acceptance criteria**
- Live order submitted → acknowledged → filled → reconciled within 5 min
- Idempotent retry on network failure (test: kill network mid-submit, retry → single fill)
- Reconciliation alerts on position drift > 1 share

### Slice 5.2: Live Eligibility Gates (Week 6–10)
**Focus:** No account eligible without proven paper history, acknowledgement, limits, monitoring

**Deliverables**
- `quant-app-v1/backend/app/services/live_gates.py`:
  - **Paper history gate**: min 500 trades OR 90 days paper trading (configurable)
  - **User acknowledgement**: signed digital agreement (stored in `user_agreements` table)
  - **Account-level limits**: max position size, max daily volume, max open orders
  - **Monitoring dashboard**: `GET /api/v1/live/monitoring` — latency, fill rate, error rate, risk utilization
  - **Reversible kill switch**: `POST /api/v1/live/kill-switch` — blocks new live orders instantly; existing orders cancelable
- `quant-app-v1/frontend/src/components/features/LiveActivation.tsx` — wizard: paper stats → agreement → limits → activate

**Acceptance criteria**
- Account with <500 paper trades cannot activate live (test)
- Kill switch blocks new live orders in <100ms (load test)
- Monitoring shows live latency <500ms p99

### Slice 5.3: Audit & Replay (Week 10–14)
**Focus:** Event-sourced audit log, deterministic replay, incident runbooks

**Deliverables**
- `quant-app-v1/backend/app/services/audit_log.py` — immutable append-only log (DB + WAL):
  - Events: `LiveOrderSubmitted`, `BrokerAck`, `BrokerFill`, `BrokerReject`, `RiskCheck`, `KillSwitchTriggered`, `ReconciliationDrift`
  - Each event: `event_id`, `timestamp`, `correlation_id`, `payload_json`, `hash_chain` (SHA256 of prev + current)
- `quant-app-v1/backend/app/services/replay_engine.py` — deterministic replay from audit log:
  - Input: `start_event_id`, `end_event_id` (or time range)
  - Output: reconstructed portfolio state + divergence report vs actual
- Incident runbooks (Markdown in `docs/runbooks/`):
  - `broker_disconnect.md`
  - `risk_breach.md`
  - `reconciliation_drift.md`
  - `data_feed_failure.md`

**Acceptance criteria**
- Every live order replayable from audit log (test: replay last 100 orders → identical state)
- Hash chain verified on startup (tamper detection)
- Runbook for broker disconnect tested in staging

### Slice 5.4: Production Operations (Week 14–20)
**Focus:** Monitoring, backups, security, privacy, legal

**Deliverables**
- **Monitoring/alerting** (Prometheus/Grafana or Datadog):
  - Latency (p50/p95/p99), error rate, fill rate, queue depth
  - Risk utilization (buying power, concentration, daily loss)
  - Broker API health (latency, errors, rate limit remaining)
  - Alerts: PagerDuty/Slack on kill switch, risk breach, reconciliation drift, broker down
- **Backups/recovery**:
  - DB: point-in-time recovery (PITR) enabled
  - Audit log: replicated to immutable storage (S3 + Glacier)
  - RTO < 1hr, RPO < 5min
- **Security hardening**:
  - mTLS between services
  - Secrets: Vault/Sealed Secrets (no env vars in prod)
  - Dependency scanning (Dependabot + Trivy)
  - Pen test report addressed
- **Privacy/legal**:
  - Privacy policy, terms of service published
  - Data retention/deletion policy
  - Jurisdiction-specific compliance (US: Regulation NMS, best execution docs)

**Acceptance criteria**
- All alerts fire in staging chaos test (kill broker, spike latency, breach risk)
- Backup restore tested quarterly
- Security scan passes (0 critical, 0 high)
- Legal sign-off obtained

## Acceptance criteria (from ROADMAP.md)

- Every live order can be reconciled to the broker and replayed from durable events
- The platform safely halts execution on risk, data, broker, or connectivity failure
- No account is eligible for live trading without the required activation gates

## Intentionally unavailable (until explicitly authorized)

- Additional brokers (IBKR, Tradier, etc.) — one at a time after Phase 5.1 proven
- Additional asset classes (options, futures, FX, crypto)
- Algorithmic execution (VWAP, TWAP, POV, dark pool)
- Multi-account / sub-account management
- Prime brokerage integration