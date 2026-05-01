/** REST /history + Lightweight Charts candle */
export interface HistoryCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

/** Server → client on /ws/trading */
export interface TradingWsPayload {
  symbol: string;
  price: number;
  rsi: number;
  /** Optional: when backend attaches pattern alerts */
  pattern_detected?: boolean;
  /** Unix seconds — marker anchor */
  pattern_time?: number;
  pattern_label?: string;
}

export interface PatternSignal {
  name: string;
  sentiment: number;
  timestamp: number;
}

/**
 * Standard OHLCV Candle format required by Lightweight Charts.
 * Time must be a Unix timestamp (seconds) for performance.
 */
export interface CandleData {
    time: number;
    open: number;
    high: number;
    low: number;
    close: number;
    volume?: number; // Optional for basic candlestick charts
  }
  
  /**
   * Results from your backend/app/quant engine.
   */
  export interface Technicals {
    rsi: number;
    ema_20?: number;
    volatility: number;
  }
  
  /**
   * Geometric or algorithmic patterns identified in recognition.py.
   */
  export interface MarketPattern {
    id: string;
    name: string; // e.g., "Head and Shoulders", "Double Bottom"
    type: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
    confidence: number; // 0.0 to 1.0
    points: { time: number; price: number }[]; // Coordinates to draw the shape
  }
  
  /**
   * Global events and news sentiment from nlp/sentiment.py.
   */
  export interface NewsSentiment {
    id: string;
    headline: string;
    source: string;
    timestamp: number;
    sentimentScore: number; // -1.0 to 1.0
    impactWeight: number; // How much this should move the "Confidence"
  }
  
  /**
   * The unified payload sent over the WebSocket.
   * This is what your frontend 'useSocket' hook will parse.
   */
  export interface LiveUpdate {
    ticker: string;
    priceData: CandleData;
    indicators: Technicals;
    patterns?: MarketPattern[];
    latestNews?: NewsSentiment;
  }