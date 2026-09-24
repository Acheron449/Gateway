# Reconciliation Drift Runbook (Slice 5.3)

## Trigger
Reconciliation job (every 5 min) detects drift: local orders/fills/positions vs broker API mismatch > threshold.

## Detection
- Audit log records `ReconciliationDrift` event with `drift_type` field
- Monitoring alert: `reconciliation_drift_shares > 1`
- Manual check: `GET /api/v1/live/account` vs broker account endpoint

## Immediate Actions
1. **Severity check**:
   - **Position drift > 1 share**: Page on-call immediately
   - **Cash drift > $1**: Investigate within 15 min
   - **Fill price drift**: Investigate within 30 min
2. **Preserve**: Snapshot both local and broker state for diff
3. **Audit**: Pull all events in drift window via `ReplayEngine`

## Investigation
1. Check network: packet loss, latency spikes during drift window
2. Check broker API rate limits (did we exceed?)
3. Check for partial fills not captured locally
4. Re-run reconciliation job; compare results

## Resolution
1. **Authoritative source**: Broker state wins for existing positions
2. **Reconcile**: Update local DB to match broker snapshot
3. **Idempotency check**: Verify no duplicate fills from retry logic
4. **Re-run**: Full reconciliation from start of drift window

## Rollback
- If drift due to local bug: restore local state from last known good reconciliation
- If drift due to broker bug: wait for broker fix; use cached broker state

## Post-incident
- Document drift root cause in incident log
- Adjust reconciliation threshold if false positives confirmed
- Review reconciliation job latency
