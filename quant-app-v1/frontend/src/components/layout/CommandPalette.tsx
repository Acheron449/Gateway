import { useState, useEffect, useRef } from "react";

const actions = [
  { label: "Overview", key: "overview" },
  { label: "Scanner", key: "scanner" },
  { label: "Markets", key: "markets" },
  { label: "Calendar", key: "calendar" },
  { label: "Paper Trading", key: "paper" },
  { label: "Backtests", key: "backtests" },
];

export default function CommandPalette({ onSelect }: { onSelect: (k: string) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape" && open) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  const filtered = actions.filter(
    (a) => a.label.toLowerCase().includes(query.toLowerCase()) || a.key.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        aria-label="Open command palette (⌘K)"
        style={{
          background: "rgba(255,255,255,0.05)",
          border: "1px solid rgba(255,255,255,0.12)",
          color: "#8b949e",
          padding: "0.35rem 0.75rem",
          borderRadius: 6,
          fontSize: 12,
          cursor: "pointer",
        }}
        title="⌘K"
      >
        ⌘K
      </button>
      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Command palette"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 100,
            background: "rgba(0,0,0,0.65)",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "center",
            paddingTop: "15vh",
          }}
          onClick={() => setOpen(false)}
        >
          <div
            style={{
              width: 480,
              maxWidth: "92vw",
              background: "#161b22",
              border: "1px solid rgba(255,255,255,0.12)",
              borderRadius: 12,
              boxShadow: "0 20px 50px rgba(0,0,0,0.6)",
              padding: 12,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search actions or symbols…"
              style={{
                width: "100%",
                background: "#0d1117",
                border: "1px solid rgba(255,255,255,0.14)",
                color: "#e6edf3",
                padding: "0.55rem 0.75rem",
                borderRadius: 6,
                fontSize: 14,
                outline: "none",
              }}
            />
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 2 }}>
              {filtered.map((a) => (
                <button
                  key={a.key}
                  onClick={() => {
                    onSelect(a.key);
                    setOpen(false);
                    setQuery("");
                  }}
                  style={{
                    background: "transparent",
                    border: "1px solid transparent",
                    color: "#c9d1d9",
                    padding: "0.45rem 0.55rem",
                    borderRadius: 6,
                    fontSize: 13,
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                >
                  {a.label}
                </button>
              ))}
              {filtered.length === 0 && (
                <div style={{ padding: "0.5rem 0.55rem", color: "#8b949e", fontSize: 13 }}>No results</div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
