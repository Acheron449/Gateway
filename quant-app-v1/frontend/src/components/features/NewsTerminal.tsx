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
        setLines(msgs);
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
        minHeight: "120px",
        padding: "0.65rem",
        borderRadius: "8px",
        border: "1px solid #30363d",
        background: "#0d1117",
        fontFamily: "ui-monospace, monospace",
        fontSize: "0.8rem",
        color: "#7ee787",
        overflowY: "auto",
      }}
    >
      <div style={{ marginBottom: "0.35rem", color: "#8b949e", fontFamily: "sans-serif" }}>
        Terminal · {ticker.toUpperCase() || "—"}
      </div>
      {error ? (
        <div style={{ color: "#ff7b72" }}>{error}</div>
      ) : (
        lines.map((ln) => (
          <div key={ln}>{ln}</div>
        ))
      )}
    </section>
  );
}
