export default function DecisionInspector() {
  return (
    <aside style={{ width: 320, borderLeft: "1px solid rgba(255,255,255,0.08)", background: "#161b22", padding: 12 }}>
      <h3 style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 0.8, color: "#8b949e", marginBottom: 8 }}>Inspector</h3>
      <div style={{ fontSize: 13, color: "#c9d1d9", lineHeight: 1.5 }}>
        <p>Price / freshness badge (source + fetched_at + delay)</p>
        <p>Next macro events (Phase 2 calendar)</p>
        <p>Signals & confidence (Phase 0 analysis)</p>
        <p>Paper order preview (Phase 4)</p>
        <p>Risk / provenance — every point shows source + timestamp</p>
      </div>
    </aside>
  );
}
