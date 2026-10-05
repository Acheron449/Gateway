import { useEffect, useState } from "react";

import { API_BASE } from "../../lib/constants";

export interface NewsTerminalProps {
  ticker: string;
}

interface AnalysisPayload {
  ticker?: string;
  direction?: string;
  overall_confidence?: number;
  signals?: unknown[];
  price?: number;
  rsi?: number;
}

export function NewsTerminal({ ticker }: NewsTerminalProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const sym = ticker.trim().toUpperCase();
    if (!sym) {
      setLines([]);
      return;
    }

    const ac = new AbortController();

    fetch(`${API_BASE}/analysis/${encodeURIComponent(sym)}`, { signal: ac.signal })
      .then(async (res) => {
        if (!res.ok) {
          const txt = await res.text().catch(() => "");
          throw new Error(txt || `${res.status}`);
        }
        return res.json() as Promise<AnalysisPayload>;
      })
      .then((j) => {
        const msgs: string[] = [
          `${j.ticker ?? sym}: direction ${String(j.direction ?? "n/a")}`,
          `confidence ${String(j.overall_confidence ?? "n/a")}`,
          `patterns ${Array.isArray(j.signals) ? j.signals.length : 0} (from REST snapshot)`,
        ];

        const newsLines: string[] = [
          `[DATA] Price: $${j.price?.toFixed(2) ?? "0.00"}`,
          `[DATA] RSI: ${j.rsi?.toFixed(2) ?? "0.00"}`,
          `[SIGNAL] Direction: ${String(j.direction ?? "n/a").toUpperCase()}`,
          `[SIGNAL] Confidence: ${(j.overall_confidence ?? 0) * 100}`,
          `[SIG] Patterns: ${Array.isArray(j.signals) ? j.signals.length : 0} detected`,
        ];

        setLines(msgs.concat(newsLines));
        setError(null);
      })
      .catch((e: unknown) => {
        if ((e as { name?: string }).name === "AbortError") return;
        setError(e instanceof Error ? e.message : "News fetch failed");
        setLines([]);
      });

    return () => ac.abort();
  }, [ticker]);

  return (
    <section
      style={{
        flex: "1",
        minHeight: "150px",
        padding: "0.65rem",
        borderRadius: "8px",
        border: "1px solid #30363d",
        background: "#0d1117",
        fontFamily: "ui-monospace, monospace",
        fontSize: "0.75rem",
        color: "#3fb950",
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
        gap: "0.25rem",
      }}
    >
      <div style={{ 
        marginBottom: "0.5rem", 
        paddingBottom: "0.25rem",
        borderBottom: "1px solid #21262d",
        color: "#8b949e", 
        fontFamily: "sans-serif",
        fontSize: "0.7rem",
        textTransform: "uppercase",
        letterSpacing: "0.05em"
      }}>
        Real-time Intelligence Terminal · {ticker.toUpperCase()}
      </div>
      {error ? (
        <div style={{ color: "#f85149" }}>[ERROR] {error}</div>
      ) : (
        lines.map((ln, i) => (
          <div key={i} style={{ display: 'flex', gap: '0.5rem' }}>
            <span style={{ color: '#8b949e' }}>{'>'}</span>
            <span>{ln}</span>
          </div>
        ))
      )}
    </section>
  );
}
