import { render } from "@testing-library/react";
import type { RenderOptions, RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { AuthProvider } from "../auth/AuthContext";
import type { AuthUser } from "../api/types";

const STORAGE_KEY = "omniflow.auth";

/** Phase 9 (JWT/RBAC): pages render a `<TopBar>` that calls `useAuth()`, so
 * every page-level test needs an `AuthProvider` in its tree — these tests
 * predate the login gate and were written against pages rendered in
 * isolation, not through `<App>`'s route tree. Seeds an already-authenticated
 * `admin` session (the superset role) by default so existing assertions
 * about role-gated buttons being present/enabled keep passing unchanged;
 * override `user` for a test that specifically cares about a lower role. */
export function seedAuth(
  user: AuthUser = { id: "test-user-id", email: "admin@example.com", role: "admin" },
): void {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ token: "test-token", user }));
}

export function renderWithAuth(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper">,
): RenderResult {
  seedAuth();
  return render(ui, { wrapper: AuthProvider, ...options });
}
