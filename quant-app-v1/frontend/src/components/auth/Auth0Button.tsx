import { useState } from "react";
import { useAuth0 } from "@auth0/auth0-react";

/**
 * "Continue with Auth0" button rendered inside the auth modal.
 *
 * Only mount this inside the Auth0Provider (App.tsx gates rendering on the
 * same `auth0Enabled` flag that mounts the provider).
 */
export function Auth0Button() {
  const { loginWithRedirect, isLoading } = useAuth0();
  const [error, setError] = useState("");

  const handleClick = async () => {
    setError("");
    try {
      await loginWithRedirect();
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Auth0 sign-in failed");
    }
  };

  return (
    <>
      <div className="auth-divider">
        <span>or</span>
      </div>
      <button type="button" className="auth0-submit" onClick={handleClick} disabled={isLoading}>
        {isLoading ? "Redirecting…" : "Continue with Auth0"}
      </button>
      {error && (
        <div className="auth-error" role="alert">
          {error}
        </div>
      )}
    </>
  );
}
