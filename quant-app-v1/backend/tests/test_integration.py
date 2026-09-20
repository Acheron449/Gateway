import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch
from app.quant import impact_model, recognition
from app.api.v1.analysis import get_analysis

# Mock data for testing
@pytest.fixture
def mock_price_data():
    """Returns a synthetic DataFrame with a clear Head and Shoulders pattern."""
    data = {
        "High": [100, 105, 102, 108, 104, 110, 106, 102],
        "Low": [98, 103, 100, 106, 102, 108, 104, 100],
        "Open": [99, 104, 101, 107, 103, 109, 105, 101],
        "Close": [101, 104, 101, 107, 104, 109, 105, 101],
    }
    return pd.DataFrame(data)


@pytest.fixture
def mock_hs_price_data():
    """Returns a synthetic DataFrame with enough bars for pivot detection and a clear Head and Shoulders pattern."""
    # Need enough bars for pivot detection (window=3 needs 7 bars minimum)
    # Pattern: left shoulder ~110, head ~115, right shoulder ~110
    # Data ends at right shoulder to avoid extra pivots
    import numpy as np
    np.random.seed(42)
    n = 45
    highs = np.ones(n) * 100
    lows = np.ones(n) * 98

    # Left shoulder
    highs[8:12] = [108, 109, 110, 109]
    lows[8:12] = [106, 107, 108, 107]

    # Valley between left shoulder and head
    highs[12:20] = [105, 103, 102, 101, 102, 103, 104, 105]
    lows[12:20] = [103, 101, 100, 99, 100, 101, 102, 103]

    # Head
    highs[20:28] = [108, 110, 112, 114, 115, 114, 112, 110]
    lows[20:28] = [106, 108, 110, 112, 113, 112, 110, 108]

    # Valley between head and right shoulder
    highs[28:36] = [108, 106, 104, 102, 101, 102, 103, 104]
    lows[28:36] = [106, 104, 102, 100, 99, 100, 101, 102]

    # Right shoulder - END DATA HERE
    highs[36:44] = [106, 108, 110, 111, 110, 109, 108, 107]
    lows[36:44] = [104, 106, 108, 109, 108, 107, 106, 105]

    # Add small noise
    highs += np.random.normal(0, 0.1, n)
    lows += np.random.normal(0, 0.1, n)
    opens = (highs + lows) / 2 + np.random.normal(0, 0.1, n)
    closes = (highs + lows) / 2 + np.random.normal(0, 0.1, n)

    return pd.DataFrame({'High': highs, 'Low': lows, 'Open': opens, 'Close': closes})

@pytest.mark.asyncio
async def test_impact_model_logic():
    """Verify impact_model correctly aggregates patterns and sentiment."""
    patterns = [
        {"type": "HeadAndShoulders", "confidence": 0.8, "direction": "Bearish"},
        {"type": "DoubleBottom", "confidence": 0.6, "direction": "Bullish"}
    ]
    
    # Case 1: Bearish pattern + negative sentiment -> High confidence Bearish
    res1 = impact_model.calculate_final_signal(patterns, sentiment_score=-0.5)
    assert res1["direction"] == "Bearish"
    assert res1["confidence"] > 0.5

    # Case 2: Bullish pattern + positive sentiment -> High confidence Bullish
    patterns_bull = [{"type": "DoubleBottom", "confidence": 0.7, "direction": "Bullish"}]
    res2 = impact_model.calculate_final_signal(patterns_bull, sentiment_score=0.5)
    assert res2["direction"] == "Bullish"
    assert res2["confidence"] > 0.7

@pytest.mark.asyncio
async def test_recognition_engine_patterns(mock_hs_price_data):
    """Verify recognition engine detects expected patterns in mock data."""
    from app.quant.recognition import find_pivots, detect_head_and_shoulders
    
    pivots = find_pivots(mock_hs_price_data)
    patterns = detect_head_and_shoulders(pivots)
    
    assert len(patterns) > 0
    assert patterns[0].type == "HeadAndShoulders"

@pytest.mark.asyncio
async def test_analysis_api_integration():
    """End-to-end test of the analysis API endpoint."""
    from app.services.market_data import OhlcvResult
    
    ticker = "AAPL"
    
    # Mocking market_data.fetch_ohlcv, technicals.calculate_all_indicators, 
    # sentiment.get_latest_score_for_ticker
    with patch("app.services.market_data.fetch_ohlcv", new_callable=AsyncMock) as mock_fetch, \
         patch("app.quant.technicals.calculate_all_indicators") as mock_tech, \
         patch("app.api.nlp.sentiment.get_latest_score_for_ticker", return_value=0.5) as mock_sent:
        
        # Setup mock returns
        mock_df = pd.DataFrame({
            "High": [100, 110, 105, 115, 110],
            "Low": [90, 100, 95, 105, 100],
            "Open": [95, 105, 100, 110, 105],
            "Close": [105, 110, 105, 115, 110],
            "RSI": [50, 55, 52, 60, 58]
        })
        mock_fetch.return_value = OhlcvResult(
            dataframe=mock_df,
            provenance={"source": "yfinance", "provider_version": "test", "coverage": "US equities / daily"}
        )
        mock_tech.return_value = mock_df
        
        response = await get_analysis(ticker)
        
        assert response["ticker"] == ticker.upper()
        assert "price" in response
        assert "rsi" in response
        assert "direction" in response
        assert "overall_confidence" in response
        assert "provenance" in response
