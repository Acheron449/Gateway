/**
 * Shared cache for the most recent Kronos forecast (item 24).
 *
 * The Markets chart panel runs the model once per symbol/timeframe; AI
 * Insights reads the same numbers instead of paying for a second inference
 * call. This is an in-memory, one-slot cache — it is intentionally not
 * persisted, since a forecast goes stale as soon as a new candle prints.
 */

export interface KronosSnapshotRow {
  index: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface KronosSnapshot {
  /** Symbol the forecast was built from (uppercase, e.g. "AAPL"). */
  symbol: string;
  horizon: number;
  /** Human unit for the horizon, e.g. "days". */
  unit: string;
  rows: KronosSnapshotRow[];
  updatedAt: number;
  /** Whether the Kronos package was installed when the forecast ran. */
  installed: boolean;
  /** Last actual close the forecast was projected from (baseline for the move). */
  lastClose?: number;
}

let snapshot: KronosSnapshot | null = null;
const listeners = new Set<() => void>();

export function writeKronosSnapshot(next: KronosSnapshot): void {
  snapshot = next;
  for (const listener of listeners) listener();
}

export function readKronosSnapshot(): KronosSnapshot | null {
  return snapshot;
}

/** Subscribe to cache updates; returns an unsubscribe function. */
export function subscribeKronosSnapshot(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Last actual close before the forecast, used as the baseline for the move. */
export function kronosBaseline(rows: KronosSnapshotRow[]): number | null {
  if (!rows.length) return null;
  const first = rows[0];
  return typeof first?.close === "number" ? first.close : null;
}
