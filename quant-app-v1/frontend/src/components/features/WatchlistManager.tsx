import { useState, useEffect } from "react";
import { API_BASE } from "@/lib/constants";
import { useAuth } from "@/context/AuthContext";

interface Watchlist { id: string; name: string; symbols: string[]; }

export default function WatchlistManager() {
  const { user } = useAuth();
  const [items, setItems] = useState<Watchlist[]>([]);
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState("");
  const [symbol, setSymbol] = useState("");

  useEffect(() => { load(); }, [user]);

  async function load() {
    if (!user) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/watchlists`, { headers: { Authorization: `Bearer ${localStorage.getItem("gateway_auth_token")}` } });
      if (res.ok) setItems(await res.json()); else setItems([]);
    } catch { setItems([]); }
    finally { setLoading(false); }
  }

  async function add() {
    if (!name.trim()) return;
    const res = await fetch(`${API_BASE}/watchlists`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("gateway_auth_token")}` },
      body: JSON.stringify({ name: name.trim(), symbols: symbol ? [symbol] : [] }),
    });
    if (res.ok) { setName(""); setSymbol(""); load(); }
  }

  async function remove(id: string) {
    const res = await fetch(`${API_BASE}/watchlists/${id}`, { method: "DELETE", headers: { Authorization: `Bearer ${localStorage.getItem("gateway_auth_token")}` } });
    if (res.ok) load();
  }

  return (
    <div style={{ padding: 12 }}>
      <h3 style={{ fontSize: 14, marginBottom: 8 }}>Saved Watchlists</h3>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Watchlist name" style={{ flex: 1, padding: 6, border: "1px solid rgba(255,255,255,0.12)", borderRadius: 4, background: "#0d1117", color: "#e6edf3" }} />
        <input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="Symbol" style={{ width: 90, padding: 6, border: "1px solid rgba(255,255,255,0.12)", borderRadius: 4, background: "#0d1117", color: "#e6edf3" }} />
        <button onClick={add} style={{ padding: "6px 10px", background: "#633cff", color: "#fff", borderRadius: 4, border: "none", cursor: "pointer" }}>Add</button>
      </div>
      {loading && <div style={{ color: "#8b949e", fontSize: 12 }}>Loading…</div>}
      <ul style={{ listStyle: "none", padding: 0 }}>
        {items.map((w) => (
          <li key={w.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.06)", fontSize: 13 }}>
            <span>{w.name} — {w.symbols.join(", ")}</span>
            <button onClick={() => remove(w.id)} style={{ background: "transparent", border: "1px solid rgba(255,255,255,0.1)", color: "#8b949e", cursor: "pointer" }}>✕</button>
          </li>
        ))}
      </ul>
    </div>
  );
}