from __future__ import annotations

import os
from collections import deque

import pandas as pd
import pandas_ta as ta
from loguru import logger


def calculate_rsi(price_series: pd.Series, period: int = 14) -> pd.Series:
    delta = price_series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def calculate_rsi_pandas_ta(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI via pandas-ta (matches live-stream path)."""
    out = ta.rsi(close.astype(float), length=period)
    return out.fillna(50.0) if isinstance(out, pd.Series) else close * 0 + 50.0


def calculate_bollinger_bands(
    price_series: pd.Series, period: int = 20, std_mult: float = 2.0
) -> tuple[pd.Series, pd.Series]:
    middle = price_series.rolling(period, min_periods=period).mean()
    std = price_series.rolling(period, min_periods=period).std()
    upper = middle + (std_mult * std)
    lower = middle - (std_mult * std)
    return upper.bfill(), lower.bfill()


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    output["RSI"] = calculate_rsi(output["Close"])
    output["EMA_20"] = output["Close"].ewm(span=20, adjust=False).mean()
    output["Upper_Band"], output["Lower_Band"] = calculate_bollinger_bands(
        output["Close"]
    )
    return output


def _alpaca_credentials() -> tuple[str, str] | None:
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    if key and secret:
        return key, secret
    return None


def _stock_feed():
    from alpaca.data.enums import DataFeed

    return DataFeed.SIP if os.getenv("ALPACA_STOCK_FEED", "").upper() == "SIP" else DataFeed.IEX


def _bar_to_live_row(data) -> dict:
    if isinstance(data, dict):
        return {
            "timestamp": data.get("t") or data.get("timestamp"),
            "open": float(data.get("o") or data.get("open") or 0),
            "high": float(data.get("h") or data.get("high") or 0),
            "low": float(data.get("l") or data.get("low") or 0),
            "close": float(data.get("c") or data.get("close") or 0),
            "volume": float(data.get("v") or data.get("volume") or 0),
            "symbol": data.get("S") or data.get("symbol"),
        }
    return {
        "timestamp": data.timestamp,
        "open": float(data.open),
        "high": float(data.high),
        "low": float(data.low),
        "close": float(data.close),
        "volume": float(data.volume),
        "symbol": getattr(data, "symbol", None),
    }


class LiveRSIStrategy:
    """
    Rolling deque of Alpaca minute bars + pandas-ta RSI and simple threshold signals.
    """

    def __init__(
        self,
        symbol: str,
        rsi_period: int = 14,
        buffer_size: int = 30,
    ) -> None:
        self.symbol = symbol.upper()
        self.rsi_period = rsi_period
        cap = max(buffer_size, rsi_period + 2)
        self._bar_buffer: deque[dict] = deque(maxlen=cap)

    async def handle_bar(self, data) -> None:
        row = _bar_to_live_row(data)
        sym = row.get("symbol") or getattr(data, "symbol", None) or self.symbol
        new_bar = {
            "timestamp": row["timestamp"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
        }

        self._bar_buffer.append(new_bar)

        if len(self._bar_buffer) < self.rsi_period:
            logger.info(
                "Gathering data... ({}/{}) [{}]",
                len(self._bar_buffer),
                self.rsi_period,
                sym,
            )
            return

        df = pd.DataFrame(list(self._bar_buffer))
        rsi_series = ta.rsi(df["close"], length=self.rsi_period)
        current_rsi = rsi_series.iloc[-1]

        if pd.isna(current_rsi):
            logger.warning("[{}] RSI not yet defined for latest bar — buffer filling", sym)
            return

        status = "NEUTRAL"
        if current_rsi < 30:
            status = "OVERSOLD (BUY SIGNAL)"
        elif current_rsi > 70:
            status = "OVERBOUGHT (SELL SIGNAL)"

        close_px = df["close"].iloc[-1]
        logger.info(
            "[{}] Price: ${:.2f} | RSI: {:.2f} | Status: {}",
            sym,
            float(close_px),
            float(current_rsi),
            status,
        )


def start_quant_stream(
    symbol: str | None = None,
    rsi_period: int = 14,
    buffer_size: int = 30,
) -> None:
    """
    Blocking: Alpaca StockDataStream minute bars → rolling RSI (pandas-ta).

    Credentials: ALPACA_API_KEY + ALPACA_SECRET_KEY (or APCA_* equivalents).
    Optional: ALPACA_STOCK_FEED=SIP.
    Symbol default: ENV QUANT_STREAM_SYMBOL or AAPL.
    """
    sym = symbol or os.getenv("QUANT_STREAM_SYMBOL", "AAPL")
    creds = _alpaca_credentials()
    if not creds:
        logger.error(
            "Set ALPACA_API_KEY and ALPACA_SECRET_KEY (or APCA_*) before start_quant_stream()."
        )
        return

    from alpaca.data.live import StockDataStream

    engine = LiveRSIStrategy(sym, rsi_period=rsi_period, buffer_size=buffer_size)
    stream = StockDataStream(creds[0], creds[1], raw_data=False, feed=_stock_feed())
    stream.subscribe_bars(engine.handle_bar, engine.symbol)

    logger.success(
        "Quant engine live for {} (RSI period={}, buffer max={}).",
        engine.symbol,
        rsi_period,
        buffer_size,
    )
    stream.run()


if __name__ == "__main__":
    start_quant_stream()
