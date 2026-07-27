import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  // Phase 9 (JWT/RBAC): auth state persists in sessionStorage — clear it so
  // one test's seeded/logged-in session never leaks into the next (same
  // shared-mutable-state pitfall RISKS.md #10 already names for the
  // gateway's rate-limit counter).
  sessionStorage.clear();
});
