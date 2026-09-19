import { type FormEvent, useState } from "react";

import { API_BASE } from "../lib/constants";

export interface ScannerProps {
  onPickSymbol?: (symbol: string) => void;
}

interface CatalogueInstrument {
  symbol: string;
  name?: string;
  exchange?: string;
  instrument_type?: string;
  description?: string;
  provenance?: {
    source?: string;
    provider_version?: string;
    data_time?: string;
  };
}

interface CatalogueSearchPayload {
  query?: string;
  matches?: string[];
  instruments?: CatalogueInstrument[];
}

/** Symbol search backed by the versioned Gateway instrument catalogue. */
export function Scanner({ onPickSymbol }: ScannerProps) {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<CatalogueInstrument[]>([]);
  const [provenance, setProvenance] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runSearch = async (evt?: FormEvent) => {
    evt?.preventDefault();
    const q = query.trim().toUpperCase();
    if (q.length < 1) {
      setMatches([]);
      setProvenance(null);
      return;
    }
    setBusy(true);
    setError(null);

    try {
      const url = `${API_BASE}/catalogue/search?query=${encodeURIComponent(q)}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      const body = (await res.json()) as CatalogueSearchPayload;
      const instruments = Array.isArray(body.instruments) ? body.instruments : [];
      setMatches(instruments);
      const first = instruments[0];
      setProvenance(
        first?.provenance?.source && first?.provenance?.provider_version
          ? `${first.provenance.source} · ${first.provenance.provider_version}`
          : null,
      );
    } catch {
      setError("Catalogue search failed");
      setMatches([]);
      setProvenance(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      style={{
        padding: "0.65rem",
        borderRadius: "8px",
        border: "1px solid #30363d",
        background: "#161b22",
      }}
    >
      <form onSubmit={(e) => void runSearch(e)} style={{ display: "flex", gap: "0.5rem" }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value.toUpperCase())}
          placeholder="Search catalogue…"
          style={{
            flex: "1",
            padding: "0.4rem 0.5rem",
            borderRadius: "6px",
            border: "1px solid #30363d",
            background: "#0d1117",
            color: "#e6edf3",
          }}
          aria-label="Catalogue query"
        />
        <button
          type="submit"
          disabled={busy}
          style={{
            padding: "0.4rem 0.85rem",
            borderRadius: "6px",
            border: "1px solid #30363d",
            background: busy ? "#21262d" : "#238636",
            color: "#fff",
          }}
        >
          Scan
        </button>
      </form>
      {error && (
        <p style={{ color: "#f85149", fontSize: "0.825rem", margin: "0.35rem 0 0" }}>{error}</p>
      )}
      {provenance && (
        <p style={{ fontSize: "0.7rem", color: "#8b949e", margin: "0.45rem 0 0" }}>
          Source: {provenance}
        </p>
      )}
      {matches.length > 0 && (
        <ul
          style={{
            margin: "0.65rem 0 0",
            padding: 0,
            listStyle: "none",
            display: "flex",
            flexWrap: "wrap",
            gap: "0.35rem",
          }}
        >
          {matches.map((inst) => (
            <li key={inst.symbol}>
              <button
                type="button"
                onClick={() => onPickSymbol?.(inst.symbol ?? "")}
                title={inst.name ?? inst.symbol}
                style={{
                  padding: "0.25rem 0.55rem",
                  borderRadius: "999px",
                  border: "1px solid #30363d",
                  background: "#0d1117",
                  color: "#58a6ff",
                  fontWeight: 600,
                }}
              >
                {inst.symbol}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}