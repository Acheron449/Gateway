/* eslint-disable @typescript-eslint/no-explicit-any */

export interface BtTrade {
  direction: "long" | "short";
  entry_equity: number;
  exit_equity: number;
  pnl_pct: number;
  entry_time: number | null;
  entry_price: number | null;
  exit_time: number | null;
  exit_price: number | null;
}

export interface BtDecision {
  time: number;
  action: string;
  price: number;
  reason: string;
  risk?: { rule: string; proposed: string; approved: string; reason: string };
}

export interface BtRun {
  id: string;
  created_at: string;
  kind: string;
  strategy: string;
  symbol: string;
  symbol_b?: string | null;
  pair_config?: Record<string, any>;
  pair_series?: { time: number; spread: number | null; zscore: number | null; beta: number | null; pvalue: number | null; cointegrated: boolean; signal: string }[];
  walk_forward?: { folds?: { fold: number; test_start: number; test_end: number; cointegration_pvalue: number | null; cointegrated: boolean; metrics: Record<string, any> }[]; out_of_sample_metrics?: Record<string, any> };
  fills?: { status: string; fill_time?: number; legs?: { symbol_leg: string; side: string; filled_quantity: number; fill_price: number; modeled_spread_bps: number; fee: number; status: string }[] }[];
  execution_model?: { warning?: string; participation_rate?: number; spread_floor_bps?: number; range_factor?: number };
  bars: number;
  tf: string;
  capital: number;
  provider: string | null;
  model: string | null;
  decisions: BtDecision[];
  trades: BtTrade[];
  equity_curve: { time: number; equity: number }[];
  risk_events?: { time: number; rule: string; reason: string }[];
  bar_returns?: number[];
  metrics: Record<string, any>;
}
