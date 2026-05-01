export interface AssetSelectorProps {
  value: string;
  onChange: (symbol: string) => void;
  options?: readonly string[];
}

const DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN"] as const;

/** Text input backed by datalist presets for rapid symbol selection. */
export function AssetSelector({
  value,
  onChange,
  options = DEFAULT_WATCHLIST,
}: AssetSelectorProps) {
  const listId = "watchlist-presets";

  return (
    <label
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.35rem",
        fontSize: "0.8125rem",
        color: "#8b949e",
        minWidth: "160px",
      }}
    >
      <span>Ticker</span>
      <input
        type="text"
        list={listId}
        value={value.toUpperCase()}
        onChange={(e) =>
          onChange(e.target.value.toUpperCase().replace(/\s+/g, "").slice(0, 12))
        }
        spellCheck={false}
        aria-label="Asset ticker symbol"
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
        {[...options]
          .slice()
          .sort()
          .map((sym) => (
            <option key={sym} value={sym} />
          ))}
      </datalist>
    </label>
  );
}
