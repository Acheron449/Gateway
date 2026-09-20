import { useState, useEffect, useCallback } from "react";

export default function ScannerV2() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const debouncedSearch = useCallback(() => {
    if (!query.trim()) { setResults([]); return; }
    setLoading(true);
    // Phase 0 /catalogue/search endpoint; paper-only for now
    fetch(`/catalogue/search?q=${encodeURIComponent(query)}`)
      .then((r) => r.ok ? r.json() : Promise.resolve({ symbols: [] }))
      .then((data) => setResults(Array.isArray(data?.symbols) ? data.symbols : []))
      .catch(() => setResults([]))
      .finally(() => setLoading(false));
  }, [query]);

  useEffect(() => { const t = setTimeout(debouncedSearch, 250); return () => clearTimeout(t); }, [debouncedSearch]);

  return (
    <div style={{ padding: 12 }}>
      <h2 style={{ fontSize: 18, marginBottom: 8 }}>Scanner V2</h2>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search symbols / filters…"
        style={{ width: "100%", maxWidth: 640, padding: 8, borderRadius: 6, border: "1px solid rgba(255,255,255,0.12)", background: "#0d1117", color: "#e6edf3" }}
      />
      {loading && <div style={{ color: "#8b949e", fontSize: 13, marginTop: 8 }}>Searching…</div>}
      <ul style={{ listStyle: "none", padding: 0, margin: 8 }}>
        {results.map((s) => (
          <li key={s} style={{ padding: "0.4rem 0.25rem", borderBottom: "1px solid rgba(255,255,255,0.06)", fontSize: 14 }}>
            {s}
          </li>
        ))}
      </ul>
    </div>
  );
}
