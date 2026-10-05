# Broker Disconnect Runbook (Slice 5.3)

## Trigger
Broker API unreachable, health check fails, or `BrokerService` reports connection error.

## Detection
- `BrokerService.health()` returns `unhealthy` or raises `RuntimeError`
- Monitoring alert: `broker_latency_seconds > 10` sustained 60s
- Audit log records `RECONCILIATION_DRIFT` event with `broker_unreachable` flag

## Immediate Actions (within 2 minutes)
1. **Verify**: `POST /api/v1/live/kill-switch` — activate kill switch (blocks new live orders)
2. **Audit**: Confirm `KillSwitchTriggered` event in audit log
3. **Notify**: On-call via PagerDuty; Slack #ops-alerts
4. **Preserve**: Snapshot in-memory order/fill state before any restart

## Investigation
1. Check broker status page / API health endpoint
2. Check network connectivity: `curl -v {broker_health_url}`
3. Verify API keys not expired
4. Review last 10 audit events via `ReplayEngine.replay` (correlation window)

## Recovery
1. Deactivate kill switch only after broker confirmed reachable
2. Run reconciliation job: compare local `orders`/`fills`/`positions` vs broker API
3. Resolve drift: replay missed events, apply corrections
4. Monitor fill rate + latency for 15 min post-recovery

## Rollback
- Kill switch stays active until drift < 0 shares for 5 consecutive minutes
- If broker down > 30 min: escalate to engineering lead

## Post-incident
- Document in incident log
- Review audit log for any unordered fills during outage
