export default function DecisionInspector() {
  return (
    <aside style={{ width: 320, borderLeft: "1px solid rgba(255,255,255,0.08)", background: "#161b22", padding: 12, overflow: "auto" }} aria-label="Right inspector">
      <h3 style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 0.8, color: "#8b949e", marginBottom: 8 }}>Inspector</h3>
      <section style={{ marginBottom: 12 }}>
        <h4 style={{ fontSize: 13, color: "#e6edf3", marginBottom: 4 }}>Price / Freshness</h4>
        <div style={{ fontSize: 12, color: "#c9d1d9", lineHeight: 1.4 }}>
          <div>AAPL +1.23% (delayed 2s)</div>
          <div style={{ color: "#8b949e" }}>Source: Phase 0 /api/v1/analysis • fetched_at: 2026-09-20T02:04Z</div>
        </div>
      </section>
      <section style={{ marginBottom: 12 }}>
        <h4 style={{ fontSize: 13, color: "#e6edf3", marginBottom: 4 }}>Next Events</h4>
        <div style={{ fontSize: 12, color: "#c9d1d9" }}>Macro calendar — Phase 2 (pending delivery).</div>
      </section>
      <section style={{ marginBottom: 12 }}>
        <h4 style={{ fontSize: 13, color: "#e6edf3", marginBottom: 4 }}>Signals</h4>
        <div style={{ fontSize: 12, color: "#c9d1d9" }}>RSI 58 / BB touch (Phase 0 analysis).</div>
      </section>
      <section style={{ marginBottom: 12 }}>
        <h4 style={{ fontSize: 13, color: "#e6edf3", marginBottom: 4 }}>Paper Preview</h4>
        <div style={{ fontSize: 12, color: "#c9d1d9" }}>AAPL • BUY • 10 • est. $1,234 • risk checks: pass</div>
      </section>
      <section>
        <h4 style={{ fontSize: 13, color: "#e6edf3", marginBottom: 4 }}>Risk / Provenance</h4>
        <div style={{ fontSize: 11, color: "#8b949e", lineHeight: 1.3 }}>
          Every point: source + fetched_at + delay. No raw JSON shown.
        </div>
      </section>
    </aside>
  );
}
