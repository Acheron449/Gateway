import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export type AuthMode = "login" | "signup";

interface AuthUIContextType {
  authMode: AuthMode | null;
  openAuth: (mode?: AuthMode) => void;
  closeAuth: () => void;
}

const AuthUIContext = createContext<AuthUIContextType | undefined>(undefined);

export function AuthUIProvider({ children }: { children: ReactNode }) {
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);

  const openAuth = useCallback((mode: AuthMode = "login") => setAuthMode(mode), []);
  const closeAuth = useCallback(() => setAuthMode(null), []);

  const value = useMemo(() => ({ authMode, openAuth, closeAuth }), [authMode, openAuth, closeAuth]);

  return <AuthUIContext.Provider value={value}>{children}</AuthUIContext.Provider>;
}

export function useAuthUI() {
  const ctx = useContext(AuthUIContext);
  if (!ctx) throw new Error("useAuthUI must be used within an AuthUIProvider");
  return ctx;
}
