import { useEffect, useRef, useState, type FormEvent } from "react";

import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";

/**
 * Centered modal with Sign in / Create account tabs.
 * Opened from the topbar avatar, the landing CTAs, and the provider gate.
 */
export function AuthModal() {
  const { authMode, openAuth, closeAuth } = useAuthUI();
  const { login, register } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  const isSignup = authMode === "signup";

  useEffect(() => {
    if (!authMode) return;
    setError("");
    setSubmitting(false);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeAuth();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [authMode, closeAuth]);

  if (!authMode) return null;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (isSignup && password !== confirm) {
      setError("Passwords do not match");
      return;
    }
    setSubmitting(true);
    try {
      if (isSignup) {
        await register(email.trim(), password, name.trim() || undefined);
      } else {
        await login(email.trim(), password);
      }
      closeAuth();
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  const switchMode = () => {
    openAuth(isSignup ? "login" : "signup");
    setError("");
  };

  return (
    <div className="auth-overlay" onMouseDown={(e) => e.target === e.currentTarget && closeAuth()}>
      <div className="auth-modal" role="dialog" aria-modal="true" aria-label={isSignup ? "Create account" : "Sign in"} ref={dialogRef}>
        <button className="auth-close" onClick={closeAuth} aria-label="Close">
          ✕
        </button>
        <div className="auth-brand">
          <span className="auth-brand-icon">⚡</span>
          <span className="auth-brand-name">Gateway</span>
        </div>
        <h2 className="auth-title">{isSignup ? "Create your account" : "Welcome back"}</h2>
        <p className="auth-subtitle">
          {isSignup
            ? "Sign up to configure providers, save layouts, and run backtests."
            : "Sign in to manage provider keys and your workspace."}
        </p>

        <form onSubmit={handleSubmit} className="auth-form">
          {isSignup && (
            <label className="auth-field">
              <span>Name (optional)</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
                placeholder="Ada Lovelace"
              />
            </label>
          )}
          <label className="auth-field">
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              placeholder="you@example.com"
              required
            />
          </label>
          <label className="auth-field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={isSignup ? "new-password" : "current-password"}
              placeholder="••••••••"
              minLength={8}
              required
            />
          </label>
          {isSignup && (
            <label className="auth-field">
              <span>Confirm password</span>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                placeholder="••••••••"
                minLength={8}
                required
              />
            </label>
          )}

          {error && (
            <div className="auth-error" role="alert">
              {error}
            </div>
          )}

          <button type="submit" className="auth-submit" disabled={submitting || !email || !password}>
            {submitting ? (isSignup ? "Creating account…" : "Signing in…") : isSignup ? "Create account" : "Sign in"}
          </button>
        </form>

        <div className="auth-switch">
          {isSignup ? "Already have an account?" : "New to Gateway?"}{" "}
          <button type="button" className="auth-switch-link" onClick={switchMode}>
            {isSignup ? "Sign in" : "Create one"}
          </button>
        </div>
      </div>
    </div>
  );
}
