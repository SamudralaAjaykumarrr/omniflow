import { createContext } from "react";
import type { AuthUser, Role } from "../api/types";

export interface AuthContextValue {
  user: AuthUser | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  /** True if the current user's role ranks at or above `minRole`
   * (viewer < ops < admin) — mirrors event_contracts.auth's rank check.
   * Client-side only: a UI convenience for hiding actions the backend
   * would reject anyway, never the actual security boundary (the backend
   * enforces that independently on every protected route). */
  hasRole: (minRole: Role) => boolean;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
