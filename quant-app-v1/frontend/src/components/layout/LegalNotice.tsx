import { useEffect, useState } from "react";

import { useAuth } from "../../context/AuthContext";
import { API_BASE } from "../../lib/constants";

const NOTICE_TEXT =
  "Gateway is a research and paper-trading tool. Results are simulated and historical, " +
  "not investment advice, and past performance does not predict future results. " +
  "Paper execution only — live brokerage orders are unavailable.";

/** Persistent site-wide notice (NFR-27); mounted in the app shell and landing footer. */
export function LegalNotice() {
  return (
    <footer className="legal-notice" aria-label="Legal notice">
      {NOTICE_TEXT}
    </footer>
  );
}

/** Records a signed-in user's acceptance of that notice on first use (NFR-29). */
export function NoticeAcceptanceGate() {
  const { user, token } = useAuth();
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user || !token) {
      setOpen(false);
      return;
    }
    let cancelled = false;
    fetch(`${API_BASE}/notices`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (response) => (response.ok ? response.json() : null))
      .then((data: { accepted?: boolean } | null) => {
        if (!cancelled && data?.accepted === false) setOpen(true);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [user?.id, token]);

  const accept = async () => {
    if (!token) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/notices`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error("Could not record your acceptance. Try again.");
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record your acceptance.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="notice-gate-backdrop">
      <section
        className="notice-gate"
        role="dialog"
        aria-modal="true"
        aria-labelledby="notice-gate-title"
      >
        <h2 id="notice-gate-title">Before you continue</h2>
        <p>{NOTICE_TEXT}</p>
        <p className="notice-gate-scope">
          Simulated paper fills and historical backtests are research tools, not a forecast,
          performance record or recommendation to trade.
        </p>
        {error && <p className="settings-error" role="alert">{error}</p>}
        <div className="notice-gate-actions">
          <button className="btn-primary" type="button" onClick={() => void accept()} disabled={submitting}>
            {submitting ? "Recording…" : "I understand and accept"}
          </button>
        </div>
      </section>
    </div>
  );
}
