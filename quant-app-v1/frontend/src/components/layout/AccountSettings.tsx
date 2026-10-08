import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "../../lib/constants";
import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";

/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * Account settings (item 19): edit personal details and request account
 * deletion. Deletion is a *request* — the backend queues a reviewable ticket
 * rather than destroying data inline, so the UI shows the ticket back to the
 * user instead of signing them out.
 */
function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("gateway_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function readError(response: Response, fallback: string): Promise<string> {
  const text = await response.text().catch(() => "");
  if (!text) return `${response.status} ${response.statusText}`.trim();
  try {
    const payload = JSON.parse(text) as any;
    if (payload && typeof payload.detail === "string") return payload.detail;
  } catch {
    /* not JSON */
  }
  return text.slice(0, 300) || fallback;
}

export function AccountSettings({ isAuthenticated }: { isAuthenticated: boolean }) {
  const { user, refresh } = useAuth();
  const { openAuth } = useAuthUI();

  const [name, setName] = useState(user?.name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [ticket, setTicket] = useState<string | null>(null);
  const [requestErr, setRequestErr] = useState<string | null>(null);

  // Seed the form from the signed-in profile whenever the *account* changes
  // (sign-in, sign-out, switching users) — not on every profile refresh, so
  // an in-progress edit is never clobbered.
  const userId = user?.id;
  useEffect(() => {
    setName(user?.name ?? "");
    setEmail(user?.email ?? "");
    setSaveMsg(null);
    setSaveErr(null);
    setTicket(null);
    setConfirmed(false);
    setReason("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const saveDetails = useCallback(async () => {
    setSaveErr(null);
    setSaveMsg(null);
    if (!name.trim() && !email.trim()) {
      setSaveErr("Enter a name or an email address.");
      return;
    }
    setSaving(true);
    try {
      const response = await fetch(`${API_BASE}/auth/me`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          name: name.trim() || null,
          email: email.trim() || null,
        }),
      });
      if (!response.ok) throw new Error(await readError(response, "Could not save details"));
      await response.json();
      await refresh();
      setSaveMsg("Personal details saved.");
    } catch (err) {
      setSaveErr(err instanceof Error ? err.message : "Could not save details");
    } finally {
      setSaving(false);
    }
  }, [name, email, refresh]);

  const submitDeletion = useCallback(async () => {
    setRequestErr(null);
    if (!confirmed) {
      setRequestErr("Confirm that you want your account deleted.");
      return;
    }
    setRequesting(true);
    try {
      const response = await fetch(`${API_BASE}/auth/delete-request`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ reason: reason.trim() || null, confirm: true }),
      });
      if (!response.ok) throw new Error(await readError(response, "Could not submit request"));
      const data = (await response.json()) as { ticket: string; message: string };
      setTicket(data.ticket);
    } catch (err) {
      setRequestErr(err instanceof Error ? err.message : "Could not submit request");
    } finally {
      setRequesting(false);
    }
  }, [reason, confirmed]);

  if (!isAuthenticated) {
    return (
      <div className="settings-section">
        <h2>Account</h2>
        <div className="auth-gate-card">
          <div className="auth-gate-icon" aria-hidden="true">🔒</div>
          <div className="auth-gate-copy">
            <h3>Sign in to manage your account</h3>
            <p>Personal details and deletion requests need a signed-in account.</p>
          </div>
          <div className="auth-gate-actions">
            <button className="btn-primary" onClick={() => openAuth("login")}>Sign in</button>
            <button className="btn-secondary" onClick={() => openAuth("signup")}>Create account</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="settings-section">
      <h2>Account</h2>
      <p className="settings-description">
        Your personal details and account lifecycle. Changes apply immediately to your profile.
      </p>

      <div className="account-grid">
        {/* ── Personal details ── */}
        <section className="account-card" aria-labelledby="account-details-h">
          <h3 id="account-details-h">Personal details</h3>
          <label className="account-field">
            <span>Display name</span>
            <input
              type="text"
              value={name}
              maxLength={120}
              placeholder="Your name"
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="account-field">
            <span>Email address</span>
            <input
              type="email"
              value={email}
              maxLength={255}
              placeholder="you@example.com"
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>

          {saveErr && <p className="account-error" role="alert">{saveErr}</p>}
          {saveMsg && !saveErr && <p className="account-ok" role="status">{saveMsg}</p>}

          <div className="account-actions">
            <button className="btn-primary" onClick={() => void saveDetails()} disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </section>

        {/* ── Deletion request ── */}
        <section className="account-card account-card-danger" aria-labelledby="account-delete-h">
          <h3 id="account-delete-h">Request account deletion</h3>
          {ticket ? (
            <>
              <p className="account-ok" role="status">
                Deletion requested. Ticket <b>{ticket}</b> — quote it to follow up. Your account
                stays active until the request is reviewed.
              </p>
              <div className="account-actions">
                <button className="btn-secondary" onClick={() => setTicket(null)}>Done</button>
              </div>
            </>
          ) : (
            <>
              <p className="settings-description">
                This submits a reviewable deletion request — your account and data are not removed
                instantly. An operator will confirm before anything is erased.
              </p>
              <label className="account-field">
                <span>Reason (optional)</span>
                <textarea
                  value={reason}
                  maxLength={500}
                  rows={3}
                  placeholder="Why are you deleting your account?"
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              <label className="account-check">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                <span>I understand my account will be scheduled for deletion.</span>
              </label>

              {requestErr && <p className="account-error" role="alert">{requestErr}</p>}

              <div className="account-actions">
                <button
                  className="btn-danger"
                  onClick={() => void submitDeletion()}
                  disabled={requesting || !confirmed}
                >
                  {requesting ? "Submitting…" : "Request deletion"}
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
