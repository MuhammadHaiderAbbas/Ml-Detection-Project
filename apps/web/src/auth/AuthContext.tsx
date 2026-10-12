import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler, tokenStore } from "../api/client";
import type { Me } from "../api/types";

interface AuthValue {
  user: Me | null;
  checking: boolean;
  /** UI hint only: the server enforces every permission on its own. */
  can: (permission: string) => boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [checking, setChecking] = useState(true);

  const reset = useCallback(() => { tokenStore.clear(); setUser(null); }, []);

  useEffect(() => {
    setUnauthorizedHandler(reset);
    if (!tokenStore.get()) { setChecking(false); return; }
    api.get<Me>("/auth/me").then(setUser).catch(reset).finally(() => setChecking(false));
  }, [reset]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.post<{ access_token: string; user: Me }>("/auth/login", { username, password });
    tokenStore.set(res.access_token);
    setUser(res.user);
  }, []);

  const logout = useCallback(async () => {
    try { await api.post("/auth/logout"); } catch { /* token may already be invalid */ }
    reset();
  }, [reset]);

  const can = useCallback((p: string) => !!user?.permissions?.includes(p), [user]);
  const value = useMemo(() => ({ user, checking, can, login, logout }), [user, checking, can, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
