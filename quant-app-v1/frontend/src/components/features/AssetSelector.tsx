export interface AssetSelectorProps {
  value: string;
  onChange: (symbol: string) => void;
  options?: readonly string[];
}

interface Asset {
  symbol: string;
  name: string;
  type: "STOCK" | "CRYPTO";
  change?: number; // optional so it still works with simple lists
}

export interface AssetSelectorProps {
  value: string;
  onChange: (symbol: string) => void;
  assets?: Asset[];          // richer data (for sidebar)
  options?: readonly string[]; // fallback (for datalist)
}

const DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN"] as const;

export function AssetSelector({
  value,
  onChange,
  assets,
  options = DEFAULT_WATCHLIST,
}: AssetSelectorProps) {
  const listId = "watchlist-presets";

  const symbols = assets?.map((a) => a.symbol) ?? options;

  return (
    <div style={{ display: "flex", height: "100%" }}>
      
      {/* Sidebar Watchlist (only if assets provided) */}
      {assets && (
        <div
          style={{
            width: "220px",
            background: "#0d1117",
            borderRight: "1px solid #30363d",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div style={{ padding: "0.75rem", borderBottom: "1px solid #30363d" }}>
            <span style={{ fontSize: "0.75rem", color: "#8b949e" }}>
              WATCHLIST
            </span>
          </div>

          <div style={{ overflowY: "auto", flex: 1 }}>
            {assets.map((asset) => {
              const selected = value === asset.symbol;

              return (
                <button
                  key={asset.symbol}
                  onClick={() => onChange(asset.symbol)}
                  style={{
                    width: "100%",
                    display: "flex",
                    justifyContent: "space-between",
                    padding: "0.75rem",
                    background: selected ? "#1f6feb22" : "transparent",
                    borderRight: selected ? "2px solid #1f6feb" : "none",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ textAlign: "left" }}>
                    <div
                      style={{
                        fontWeight: "bold",
                        color: selected ? "#58a6ff" : "#e6edf3",
                      }}
                    >
                      {asset.symbol}
                    </div>
                    <div style={{ fontSize: "0.75rem", color: "#8b949e" }}>
                      {asset.name}
                    </div>
                  </div>

                  {asset.change !== undefined && (
                    <div
                      style={{
                        fontSize: "0.8rem",
                        color:
                          asset.change >= 0 ? "#3fb950" : "#f85149",
                        fontFamily: "monospace",
                      }}
                    >
                      {asset.change >= 0 ? "+" : ""}
                      {asset.change}%
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Input Selector */}
      <label
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "0.35rem",
          fontSize: "0.8125rem",
          color: "#8b949e",
          padding: "0.75rem",
          minWidth: "180px",
        }}
      >
        <span>Ticker</span>

        <input
          type="text"
          list={listId}
          value={value.toUpperCase()}
          onChange={(e) =>
            onChange(
              e.target.value.toUpperCase().replace(/\s+/g, "").slice(0, 12)
            )
          }
          spellCheck={false}
          style={{
            padding: "0.4rem 0.5rem",
            borderRadius: "6px",
            border: "1px solid #30363d",
            background: "#0d1117",
            color: "#e6edf3",
            textTransform: "uppercase",
          }}
        />

        <datalist id={listId}>
          {[...symbols].sort().map((sym) => (
            <option key={sym} value={sym} />
          ))}
        </datalist>
      </label>
    </div>
  );
}