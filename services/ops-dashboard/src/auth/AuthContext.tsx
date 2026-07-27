import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { login as apiLogin, me as apiMe } from "../api/auth";
import { setAuthToken, setUnauthorizedHandler } from "../api/client";
import type { AuthUser, Role } from "../api/types";
import { AuthContext } from "./context";
import type { AuthContextValue } from "./context";

const STORAGE_KEY = "omniflow.auth";

interface StoredAuth {
  token: string;
  user: AuthUser;
}

const ROLE_RANK: Record<Role, number> = { viewer: 0, ops: 1, admin: 2 };

function loadStored(): StoredAuth | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredAuth;
  } catch {
    return null;
  }
}

function persist(auth: StoredAuth | null): void {
  if (auth) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(auth));
  else sessionStorage.removeItem(STORAGE_KEY);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => loadStored()?.user ?? null);

  // Session token lives in sessionStorage (cleared when the tab closes) —
  // a simpler, more contained default than localStorage for a bearer token
  // with no refresh flow (ADR 0009's own named simplification).
  useEffect(() => {
    const stored = loadStored();
    setAuthToken(stored?.token ?? null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      persist(null);
      setAuthToken(null);
      setUser(null);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  const login = useCallback(async (email: string, password: string): Promise<void> => {
    const response = await apiLogin(email, password);
    setAuthToken(response.access_token);
    // A second round trip (GET /auth/me) rather than trusting a
    // client-decoded token — the server is the source of truth for the
    // authenticated identity, not a JWT payload read without verification.
    const authUser = await apiMe();
    persist({ token: response.access_token, user: authUser });
    setUser(authUser);
  }, []);

  const logout = useCallback((): void => {
    persist(null);
    setAuthToken(null);
    setUser(null);
  }, []);

  const hasRole = useCallback(
    (minRole: Role): boolean => {
      if (!user) return false;
      return ROLE_RANK[user.role] >= ROLE_RANK[minRole];
    },
    [user],
  );

  const value = useMemo<AuthContextValue>(
    () => ({ user, isAuthenticated: user !== null, login, logout, hasRole }),
    [user, login, logout, hasRole],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
