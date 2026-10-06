import { createContext, useContext, useState, useEffect, useCallback, useRef, ReactNode } from "react";
import { API_BASE } from "../lib/constants";
import { auth0Enabled } from "../lib/auth0";

interface User {
  id: string;
  email: string;
  name?: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
  isAuthenticated: boolean;
  /** True when VITE_AUTH0_* is configured (Auth0 sign-in available). */
  auth0Enabled: boolean;
  /** Adopt an Auth0-issued access token as the app session (used by Auth0Bridge).
   *  Validates the token against /auth/me and throws if the API rejects it. */
  adoptSession: (token: string) => Promise<void>;
  /** Drop the local session without touching an external (Auth0) session. */
  clearSession: () => void;
  /** Called by Auth0Bridge so logout() can also end the Auth0 session. */
  registerExternalLogout: (fn: (() => void) | null) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const TOKEN_KEY = "gateway_auth_token";
const USER_KEY = "gateway_user";

async function apiGetMe(token: string): Promise<User | null> {
  try {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return null;
    const data = await res.json();
    return { id: data.id, email: data.email, name: data.name };
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const storedToken = localStorage.getItem(TOKEN_KEY);
    if (storedToken) {
      setToken(storedToken);
      apiGetMe(storedToken).then((u) => {
        if (u) {
          setUser(u);
          localStorage.setItem(USER_KEY, JSON.stringify(u));
        } else {
          localStorage.removeItem(TOKEN_KEY);
          localStorage.removeItem(USER_KEY);
        }
      });
    }
    setIsLoading(false);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Login failed" }));
      throw new Error(error.detail || "Login failed");
    }
    const { access_token } = await res.json();
    setToken(access_token);
    localStorage.setItem(TOKEN_KEY, access_token);
    const me = await apiGetMe(access_token);
    if (me) {
      setUser(me);
      localStorage.setItem(USER_KEY, JSON.stringify(me));
    }
  }, []);

  const register = useCallback(async (email: string, password: string, name?: string) => {
    const res = await fetch(`${API_BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Registration failed" }));
      throw new Error(error.detail || "Registration failed");
    }
    const { access_token } = await res.json();
    setToken(access_token);
    localStorage.setItem(TOKEN_KEY, access_token);
    const me = await apiGetMe(access_token);
    if (me) {
      setUser(me);
      localStorage.setItem(USER_KEY, JSON.stringify(me));
    }
  }, []);

  const externalLogoutRef = useRef<(() => void) | null>(null);

  const clearSession = useCallback(() => {
    setToken(null);
    setUser(null);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }, []);

  const logout = useCallback(() => {
    clearSession();
    try {
      // Auth0 bridge registers this; must never block local sign-out.
      externalLogoutRef.current?.();
    } catch {
      /* external logout failed — local session is already gone */
    }
  }, [clearSession]);

  const adoptSession = useCallback(async (newToken: string) => {
    // Validate against the API first: a frontend/backend Auth0 mismatch
    // (missing AUTH0_DOMAIN, wrong audience) must fail loudly, not leave a
    // half-signed-in UI where every data call 401s.
    const me = await apiGetMe(newToken);
    if (!me) {
      throw new Error(
        "The API rejected the Auth0 token — check AUTH0_DOMAIN / AUTH0_AUDIENCE on the backend",
      );
    }
    setToken(newToken);
    setUser(me);
    localStorage.setItem(TOKEN_KEY, newToken);
    localStorage.setItem(USER_KEY, JSON.stringify(me));
  }, []);

  const registerExternalLogout = useCallback((fn: (() => void) | null) => {
    externalLogoutRef.current = fn;
  }, []);

  const refresh = useCallback(async () => {
    if (!token) return;
    const me = await apiGetMe(token);
    if (!me) {
      logout();
    } else {
      setUser(me);
      localStorage.setItem(USER_KEY, JSON.stringify(me));
    }
  }, [token, logout]);

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        login,
        register,
        logout,
        refresh,
        isAuthenticated: !!token && !!user,
        auth0Enabled,
        adoptSession,
        clearSession,
        registerExternalLogout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
