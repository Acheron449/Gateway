import type { PatternSignal } from "../../types/market";

export interface PatternListProps {
  activePatterns: PatternSignal[];
  onZoomToPattern?: (timestamp: number) => void;
}

export function PatternList({ activePatterns, onZoomToPattern }: PatternListProps) {
  return (
    <aside
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.65rem",
        padding: "0.75rem",
        border: "1px solid #30363d",
        borderRadius: "8px",
        maxWidth: "320px",
        background: "#161b22",
      }}
    >
      <h2 style={{ margin: "0 0 0.25rem", fontSize: "1rem", fontWeight: 600 }}>
        Patterns
      </h2>
      {activePatterns.length === 0 ? (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "0.5rem",
            padding: "0.5rem",
            borderRadius: "6px",
            background: "#0d1117",
            border: "1px dashed #30363d",
          }}
        >
          <p style={{ margin: 0, color: "#8b949e", fontSize: "0.875rem", textAlign: "center" }}>
            Waiting for market signals...
          </p>
        </div>
      ) : (
        activePatterns.map((pattern) => {
          const pos = pattern.sentiment > 0;
          return (
            <div
              key={`${pattern.name}-${pattern.timestamp}`}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "0.35rem",
                padding: "0.5rem",
                borderRadius: "6px",
                background: "#0d1117",
                border: "1px solid #21262d",
              }}
              className="pattern-card"
            >
              <span style={{ fontWeight: 600 }}>{pattern.name}</span>
              <span style={{ color: pos ? "#3fb950" : "#f85149", fontSize: "0.875rem" }}>
                Sentiment: {pattern.sentiment.toFixed(2)}
              </span>
              <button
                type="button"
                onClick={() => onZoomToPattern?.(pattern.timestamp)}
                style={{
                  alignSelf: "flex-start",
                  padding: "0.35rem 0.65rem",
                  borderRadius: "6px",
                  border: "1px solid #30363d",
                  background: "#21262d",
                  color: "#e6edf3",
                }}
              >
                View on chart
              </button>
            </div>
          );
        })
      )}
    </aside>
  );
}
