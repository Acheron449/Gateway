from __future__ import annotations
import dataclasses

@dataclasses.dataclass
class RiskConfig:
    max_portfolio_risk: float = 0.02  # Max % of capital to risk per trade
    stop_loss_pct: float = 0.05       # 5% Stop Loss
    take_profit_pct: float = 0.10      # 10% Take Profit

class RiskManager:
    def __init__(self, total_capital: float, config: RiskConfig = RiskConfig()):
        self.total_capital = total_capital
        self.config = config

    def calculate_position_size(self, current_price: float, volatility: float) -> float:
        """
        Calculates position size based on the Kelly Criterion or fixed fractional risk.
        Returns the amount of capital to allocate to the position.
        """
        # Simplified fixed fractional: Risk 2% of total capital on this trade
        risk_amount = self.total_capital * self.config.max_portfolio_risk
        
        # Adjust size based on volatility (higher volatility = smaller position)
        # Using volatility as a proxy for the distance to stop-loss
        adjusted_size = risk_amount / (volatility + 1e-6)
        
        return adjusted_size

    def get_exit_levels(self, entry_price: float, direction: str) -> dict[str, float]:
        """
        Calculates stop-loss and take-profit prices.
        """
        if direction == "Long":
            stop_loss = entry_price * (1 - self.config.stop_loss_pct)
            take_profit = entry_price * (1 + self.config.take_profit_pct)
        elif direction == "Short":
            stop_loss = entry_price * (1 + self.config.stop_loss_pct)
            take_profit = entry_price * (1 - self.config.take_profit_pct)
        else:
            raise ValueError(f"Invalid direction: {direction}")
            
        return {
            "stop_loss": stop_loss,
            "take_profit": take_profit
        }

    def validate_exposure(self, current_exposure: float, new_trade_value: float) -> bool:
        """
        Checks if the new trade would exceed the maximum allowed portfolio risk.
        """
        if (current_exposure + new_trade_value) > self.total_capital:
            return False
        return True
