export interface IndicatorOverlayProps {
  rsi: number | null;
}

/** Compact readout fed from `/ws/trading` (same pipe as MainChart live updates). */
export function IndicatorOverlay({ rsi }: IndicatorOverlayProps) {
  const display =
    rsi !== null && !Number.isNaN(rsi)
      ? rsi.toLocaleString(undefined, { maximumFractionDigits: 2 })
      : "…";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.5rem",
        padding: "0.5rem 0.65rem",
        borderRadius: "6px",
        border: "1px solid #30363d",
        background: "#161b22",
        fontVariantNumeric: "tabular-nums",
        fontSize: "0.9rem",
      }}
    >
      <span style={{ color: "#8b949e" }}>RSI (14 proxy)</span>
      <strong>{display}</strong>
    </div>
  );
}
