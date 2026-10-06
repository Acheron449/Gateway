import { useEffect, useRef } from "react";
import { useAuth0 } from "@auth0/auth0-react";

import { useAuth } from "./AuthContext";

/**
 * Connects the Auth0 SDK to the app's own token session.
 *
 * Mounted inside both the Auth0Provider (App.tsx) and AuthProvider, it:
 *
 * - on Auth0 sign-in: silently fetches an access token and hands it to
 *   `adoptSession` (the API validates it, so misconfiguration fails loudly);
 * - on Auth0 sign-out/expiry: drops the local session;
 * - registers an external logout so `AuthContext.logout()` also ends the
 *   Auth0 session — guarded so the two sides never bounce sign-out loops.
 *
 * Renders nothing.
 */
export function Auth0Bridge() {
  const { isAuthenticated, user, getAccessTokenSilently, logout: auth0Logout } = useAuth0();
  const { adoptSession, clearSession, registerExternalLogout } = useAuth();

  const adoptedSubRef = useRef<string | null>(null);
  const authedRef = useRef(isAuthenticated);

  useEffect(() => {
    authedRef.current = isAuthenticated;
  }, [isAuthenticated]);

  // Sync Auth0 session state into the app session.
  useEffect(() => {
    let cancelled = false;
    const sub = user?.sub;

    if (isAuthenticated && sub) {
      if (adoptedSubRef.current === sub) return; // already adopted
      getAccessTokenSilently()
        .then(async (token) => {
          if (cancelled || !token) return;
          await adoptSession(token);
          adoptedSubRef.current = sub;
        })
        .catch((err) => {
          if (!cancelled) console.error("Auth0 session could not be adopted:", err);
        });
    } else if (!isAuthenticated && adoptedSubRef.current) {
      // Only clear sessions this bridge adopted — a local email/password
      // login stays intact while Auth0 is idle.
      adoptedSubRef.current = null;
      clearSession();
    }
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, user?.sub, getAccessTokenSilently, adoptSession, clearSession]);

  // Keep the adopted access token fresh (silent renewal every 30 minutes).
  useEffect(() => {
    if (!isAuthenticated) return;
    const id = window.setInterval(() => {
      getAccessTokenSilently()
        .then((token) => (token ? adoptSession(token) : undefined))
        .catch(() => {
          /* transient failure — retry on the next tick */
        });
    }, 30 * 60 * 1000);
    return () => window.clearInterval(id);
  }, [isAuthenticated, getAccessTokenSilently, adoptSession]);

  // Let AuthContext.logout() end the Auth0 session too (single direction:
  // the Auth0-side clear above never calls back into logout()).
  useEffect(() => {
    registerExternalLogout(() => {
      if (authedRef.current) {
        auth0Logout({ logoutParams: { returnTo: window.location.origin } });
      }
    });
    return () => registerExternalLogout(null);
  }, [auth0Logout, registerExternalLogout]);

  return null;
}
