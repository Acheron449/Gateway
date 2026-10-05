# Data Feed Failure Runbook (Slice 5.3)

## Trigger
Market data feed stops updating (> 60s no new candles/quotes for any symbol), or `FeedHealth` metric drops below threshold.

## Detection
- Monitoring alert: `feed_latency_seconds > 60`
- No `Quote`/`Candle` updates in last 60s across all instruments
- Audit log records `RECONCILIATION_DRIFT` with `data_stale` flag

## Immediate Actions (within 2 minutes)
1. **Switch to backup feed**: If secondary provider configured, activate failover
2. **Kill switch**: If no backup feed, activate kill switch (cannot trade on stale data)
3. **Notify**: On-call via PagerDuty; Slack #data-alerts; vendor status page
4. **Audit**: Record `data_feed_failure` event in audit log

## Investigation
1. Check provider status page (Alpaca, Finnhub, etc.)
2. Check network: DNS resolution, firewall rules, proxy health
3. Verify API keys and rate limits not exhausted
4. Check `feed_health` table for last successful update per provider

## Recovery
1. **Restore**: Primary feed confirmed healthy; verify data freshness < 10s
2. **Replay**: Reconstruct any missing data from backup/cache if available
3. **Reconcile**: Verify positions reflect correct market prices before resuming
4. **Deactivate kill switch**: Only after data freshness confirmed

## Rollback
- Stay on backup feed until primary confirmed stable for 30 min
- If both feeds fail: halt all trading; manual review required

## Post-incident
- Review feed SLA vs actual downtime
- Evaluate need for additional redundant providers
- Update runbook with any new failure modes discovered
