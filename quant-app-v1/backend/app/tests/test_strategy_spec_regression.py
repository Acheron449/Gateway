"""Regression: StrategySpec content-addressed ID determinism (Phase 3)."""
from __future__ import annotations
import sys
sys.path.insert(0, "/Users/ChristineC/Documents/GitHub/Gateway/quant-app-v1")
from importlib.util import spec_from_file_location, module_from_spec
spec = spec_from_file_location("strategy", "/Users/ChristineC/Documents/GitHub/Gateway/quant-app-v1/backend/app/models/strategy.py")
strategy = module_from_spec(spec)
spec.loader.exec_module(strategy)
# Rebuild forward refs in case of deferred annotations
from pydantic import TypeAdapter
for cls_name in ("EntryRule","ExitRule","SizingRule","InvalidationRule","Assumptions","StrategySpec"):
    cls = getattr(strategy, cls_name)
    if hasattr(cls, "model_rebuild"):
        cls.model_rebuild(force=True)
StrategySpec, Timeframe, EntryRule, ExitRule, SizingRule, InvalidationRule, Assumptions = (strategy.StrategySpec, strategy.Timeframe, strategy.EntryRule, strategy.ExitRule, strategy.SizingRule, strategy.InvalidationRule, strategy.Assumptions)

def test_content_id_determinism():
    s1 = StrategySpec(
        asset_universe=["AAPL","MSFT"], timeframe=Timeframe.D1,
        entry=EntryRule(condition="rsi<30"), exit=ExitRule(condition="rsi>70"),
        sizing=SizingRule(mode="pct_equity", amount=0.1),
        invalidation=InvalidationRule(stop_loss=0.05),
        assumptions=Assumptions(commission=0.001, spread=0.01, slippage=0.005, latency_ms=50, fx=1.0, corp_actions=True),
    )
    s2 = StrategySpec(
        asset_universe=["AAPL","MSFT"], timeframe=Timeframe.D1,
        entry=EntryRule(condition="rsi<30"), exit=ExitRule(condition="rsi>70"),
        sizing=SizingRule(mode="pct_equity", amount=0.1),
        invalidation=InvalidationRule(stop_loss=0.05),
        assumptions=Assumptions(commission=0.001, spread=0.01, slippage=0.005, latency_ms=50, fx=1.0, corp_actions=True),
    )
    assert s1.id == s2.id, f"content-ID not deterministic: {s1.id} vs {s2.id}"
    assert len(s1.id) > 0
    print("test_content_id_determinism PASSED")

if __name__ == "__main__":
    test_content_id_determinism()
