import { useState } from "react";

const routes = [
  { label: "Overview", key: "overview" },
  { label: "Scanner", key: "scanner" },
  { label: "Markets", key: "markets" },
  { label: "Calendar", key: "calendar" },
  { label: "Strategies", key: "strategies" },
  { label: "Backtests", key: "backtests" },
  { label: "Paper Trading", key: "paper" },
  { label: "Journal", key: "journal" },
];

export default function Navigation({ onNavigate }: { onNavigate: (k: string) => void }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <nav
      aria-label="Primary"
      style={{
        width: collapsed ? 48 : 220,
        borderRight: "1px solid rgba(255,255,255,0.08)",
        background: "#0d1117",
        minHeight: "100vh",
        padding: "0.75rem 0.5rem",
        display: "flex",
        flexDirection: "column",
        gap: "0.25rem",
      }}
    >
      <button
        onClick={() => setCollapsed((s) => !s)}
        aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
        style={{
          background: "transparent",
          border: "1px solid rgba(255,255,255,0.12)",
          color: "#e6edf3",
          padding: "0.35rem 0.5rem",
          borderRadius: 6,
          fontSize: 12,
          marginBottom: 4,
          cursor: "pointer",
        }}
      >
        {collapsed ? "›" : "‹"}
      </button>
      {routes.map((r) => (
        <button
          key={r.key}
          onClick={() => onNavigate(r.key)}
          style={{
            background: "transparent",
            border: "1px solid transparent",
            color: "#c9d1d9",
            padding: "0.5rem 0.6rem",
            borderRadius: 6,
            fontSize: 13,
            textAlign: "left",
            cursor: "pointer",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
        >
          {!collapsed ? r.label : r.label[0]}
        </button>
      ))}
    </nav>
  );
}
