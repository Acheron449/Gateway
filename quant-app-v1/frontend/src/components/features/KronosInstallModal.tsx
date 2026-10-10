import { useCallback, useEffect, useRef, useState } from "react";

import { API_BASE } from "../../lib/constants";

export interface KronosInstallStatus {
  installed: boolean;
  /** Repository checkout present (may still be missing Python packages). */
  repo_ready?: boolean;
  repo_path: string;
  repo_present: boolean;
  dependencies?: Record<string, boolean>;
  missing_dependencies?: string[];
  models: { tokenizer: boolean; model: boolean };
  installing: boolean;
  exit_code: number | null;
  log_tail: string;
}

/** Seconds the consent screen must stay up before Continue enables (item 10). */
const CONSENT_WAIT_SECONDS = 10;

const REQUIREMENTS: { label: string; detail: string }[] = [
  { label: "Disk space", detail: "≈ 2 GB for the repository, Python wheels and model weights" },
  { label: "Python", detail: "3.10+ running this app's backend interpreter" },
  { label: "Git", detail: "clones the upstream Kronos repository" },
  { label: "Network", detail: "GitHub (source) and Hugging Face (weights) must be reachable" },
  { label: "Time", detail: "a few minutes, running in the background — you can keep working" },
];

type Step = "consent" | "location" | "installing";

export function KronosInstallModal({
  open,
  status,
  onClose,
  onStatus,
}: {
  open: boolean;
  status: KronosInstallStatus | null;
  onClose: () => void;
  onStatus: (next: KronosInstallStatus) => void;
}) {
  const [step, setStep] = useState<Step>("consent");
  const [secondsLeft, setSecondsLeft] = useState(CONSENT_WAIT_SECONDS);
  const [accepted, setAccepted] = useState(false);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  // Reset the consent screen each time the popup opens, and restart the wait.
  useEffect(() => {
    if (!open) return undefined;
    setStep("consent");
    setAccepted(false);
    setError(null);
    setBusy(false);
    setSecondsLeft(CONSENT_WAIT_SECONDS);
    setTarget(status?.repo_path ?? "");
    const id = window.setInterval(() => {
      setSecondsLeft((left) => (left > 0 ? left - 1 : 0));
    }, 1000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // If an install is already running when the popup opens, show its progress.
  useEffect(() => {
    if (open && status?.installing) setStep("installing");
  }, [open, status?.installing]);

  // Poll while the detached installer runs.
  const pollStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/forecast/kronos/install/status`);
      if (!res.ok) return;
      const body = (await res.json()) as KronosInstallStatus;
      onStatus(body);
      if (body.installed || (!body.installing && body.exit_code !== null)) {
        if (pollRef.current !== null) {
          window.clearInterval(pollRef.current);
          pollRef.current = null;
        }
      }
    } catch {
      /* status is decoration */
    }
  }, [onStatus]);

  useEffect(() => {
    if (step !== "installing") return undefined;
    void pollStatus();
    pollRef.current = window.setInterval(() => void pollStatus(), 3000);
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [step, pollStatus]);

  const startInstall = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (target.trim()) params.set("path", target.trim());
      // Re-installing over an existing checkout must be explicit.
      if (status?.installed) params.set("force", "true");
      const query = params.toString() ? `?${params.toString()}` : "";
      const res = await fetch(`${API_BASE}/forecast/kronos/install${query}`, { method: "POST" });
      const body = (await res.json().catch(() => ({}))) as { detail?: string } & KronosInstallStatus;
      if (!res.ok) throw new Error(body.detail ?? "Install failed to start");
      onStatus(body);
      setStep("installing");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Install failed to start");
    } finally {
      setBusy(false);
    }
  }, [target, status?.installed, onStatus]);

  if (!open) return null;

  const canContinue = secondsLeft === 0 && accepted;
  const installing = step === "installing";
  const installed = status?.installed ?? false;
  const failed = (status?.exit_code ?? null) !== null && status?.exit_code !== 0;

  return (
    <div className="kronos-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="kronos-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="kronos-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="kronos-modal-head">
          <div>
            <h2 id="kronos-modal-title">Install Kronos</h2>
            <p>
              {step === "consent"
                ? "Step 1 of 2 · What you're installing"
                : step === "location"
                  ? "Step 2 of 2 · Where to save it"
                  : "Installing…"}
            </p>
          </div>
          <button type="button" className="kronos-modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        {/* ── Step 1: information, requirements, legal ── */}
        {step === "consent" && (
          <div className="kronos-modal-body">
            <section>
              <h3>What this does</h3>
              <p>
                Kronos is an optional zero-shot forecasting model. Installing it clones the upstream
                repository, installs its Python packages into this app's interpreter, and downloads
                the pretrained weights. Nothing is executed against your brokerage account — the
                model only projects future prices from the candles already on your chart.
              </p>
              {status?.repo_ready && status.missing_dependencies?.length ? (
                <p className="kronos-missing">
                  The repository is already here; these packages are still missing and will be
                  installed: <code>{status.missing_dependencies.join(", ")}</code>
                </p>
              ) : null}
            </section>

            <section>
              <h3>Requirements</h3>
              <dl className="kronos-reqs">
                {REQUIREMENTS.map((item) => (
                  <div key={item.label}>
                    <dt>{item.label}</dt>
                    <dd>{item.detail}</dd>
                  </div>
                ))}
              </dl>
            </section>

            <section>
              <h3>Legal</h3>
              <p className="kronos-legal">
                Kronos is third-party open-source software distributed under its own license — this
                app does not ship it. You are responsible for reviewing that license before
                installing. Model weights are downloaded from Hugging Face and run locally; your
                market data never leaves this machine.
              </p>
              <label className="kronos-consent">
                <input
                  type="checkbox"
                  checked={accepted}
                  onChange={(event) => setAccepted(event.target.checked)}
                />
                <span>
                  I have read the above, accept the third-party license, and consent to downloading
                  the model weights.
                </span>
              </label>
            </section>
          </div>
        )}

        {/* ── Step 2: save location ── */}
        {step === "location" && (
          <div className="kronos-modal-body">
            <section>
              <h3>File save location</h3>
              <p>
                Choose where the repository and model weights are written. The default is inside
                this app's vendor directory; pick anywhere writable with ~2 GB free.
              </p>
              <label className="kronos-path-field">
                <span>Save to</span>
                <input
                  type="text"
                  value={target}
                  placeholder={status?.repo_path ?? "e.g. ~/models/Kronos"}
                  onChange={(event) => setTarget(event.target.value)}
                  spellCheck={false}
                />
              </label>
              <p className="kronos-path-hint">
                Weights are always saved under <code>models/kronos/</code> next to the backend.
              </p>
            </section>
            {error ? <p className="kronos-error">{error}</p> : null}
          </div>
        )}

        {/* ── Installing: live log ── */}
        {installing && (
          <div className="kronos-modal-body">
            <p className="kronos-install-state">
              {installed
                ? "✔ Installed — the panel will start forecasting."
                : failed
                  ? "Install finished with an error — see the log."
                  : "Running in the background. You can close this window."}
            </p>
            {status?.log_tail ? (
              <pre className="kronos-install-log">
                {status.log_tail.split("\n").slice(-16).join("\n")}
              </pre>
            ) : null}
            {failed ? (
              <p className="kronos-error">
                Install exited with code {status?.exit_code} — check the log above.
              </p>
            ) : null}
          </div>
        )}

        <footer className="kronos-modal-foot">
          {step === "consent" && (
            <>
              <span className="kronos-wait">
                {secondsLeft > 0
                  ? `Please review — continue in ${secondsLeft}s`
                  : "Review complete"}
              </span>
              <div className="kronos-modal-actions">
                <button type="button" className="btn-secondary" onClick={onClose}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  disabled={!canContinue}
                  onClick={() => setStep("location")}
                >
                  Continue
                </button>
              </div>
            </>
          )}

          {step === "location" && (
            <>
              <span className="kronos-wait">~2 GB download</span>
              <div className="kronos-modal-actions">
                <button type="button" className="btn-secondary" onClick={() => setStep("consent")}>
                  Back
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  disabled={busy}
                  onClick={() => void startInstall()}
                >
                  {busy ? "Starting…" : "Install"}
                </button>
              </div>
            </>
          )}

          {installing && (
            <div className="kronos-modal-actions">
              <button type="button" className="btn-primary" onClick={onClose}>
                {installed ? "Done" : "Close"}
              </button>
            </div>
          )}
        </footer>
      </div>
    </div>
  );
}
