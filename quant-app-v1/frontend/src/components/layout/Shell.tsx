import Navigation from "./Navigation";
import CommandPalette from "./CommandPalette";

export default function Shell({
  activeKey,
  onNavigate,
  children,
}: {
  activeKey: string;
  onNavigate: (k: string) => void;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "#0d1117", color: "#e6edf3" }}>
      <Navigation onNavigate={onNavigate} />
      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <header
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0.75rem 1rem",
            borderBottom: "1px solid rgba(255,255,255,0.08)",
            gap: 12,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: 0.2 }}>
            Gateway / {activeKey}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <CommandPalette onSelect={onNavigate} />
          </div>
        </header>
        <section style={{ flex: 1, overflow: "auto", padding: "1rem" }}>{children}</section>
      </main>
      <aside
        aria-label="Inspector"
        style={{
          width: 320,
          borderLeft: "1px solid rgba(255,255,255,0.08)",
          background: "#161b22",
          padding: "1rem",
          display: "none",
        }}
      >
        <h3 style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 0.8, color: "#8b949e", marginBottom: 8 }}>
          Inspector
        </h3>
        <p style={{ fontSize: 13, color: "#c9d1d9" }}>
          Source + timestamp shown per data point (Phase 1.3).
        </p>
      </aside>
    </div>
  );
}
