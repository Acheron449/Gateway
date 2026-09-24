# Risk Breach Runbook (Slice 5.3)

## Trigger
Risk utilization exceeds threshold (buying power > 95%, daily loss > 3%, concentration > 20%), or kill switch auto-activates.

## Detection
- LiveGatesService.pre_trade() returns FAILED for risk gates
- Monitoring alert: `risk_utilization_pct > 80`
- Audit log records `RiskCheck` event with `status: breached`

## Immediate Actions (within 1 minute)
1. **Auto-act**: Kill switch triggers automatically on risk breach (no human delay)
2. **Verify**: Confirm kill switch active in `LiveGatesService.get_activation_status()`
3. **Notify**: On-call via PagerDuty; Slack #risk-alerts
4. **Audit**: Confirm `KillSwitchTriggered` event with reason field

## Assessment
1. Identify breached gates via `LiveGatesService.can_activate_live()`
2. Check position breakdown: `LimitsGate.check_position_size()` per symbol
3. Determine if breach is market-driven (wider spreads) or configuration error

## Mitigation
1. **Cancel all open orders** via broker API (if auto-kill failed)
2. **Reduce positions**: manual sell-down to within limits
3. **Adjust limits** only with documented authorization
4. **Deactivate kill switch** only when all gates PASS

## Rollback
- Do NOT deactivate kill switch until all risk gates PASS for 10 consecutive minutes
- Requires explicit sign-off from risk officer

## Post-incident
- Risk officer reviews all events in breach window via replay engine
- Document lessons; adjust limits/gates if warranted
