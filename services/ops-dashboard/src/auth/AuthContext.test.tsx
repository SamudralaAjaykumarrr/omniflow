import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthContext";
import { useAuth } from "./useAuth";
import * as authApi from "../api/auth";
import { getAuthToken } from "../api/client";
import type { AuthUser, LoginResponse } from "../api/types";

function Probe() {
  const { user, isAuthenticated, login, logout, hasRole } = useAuth();
  return (
    <div>
      <span data-testid="user">{user ? `${user.email}:${user.role}` : "none"}</span>
      <span data-testid="authenticated">{String(isAuthenticated)}</span>
      <span data-testid="has-ops">{String(hasRole("ops"))}</span>
      <button onClick={() => login("a@example.com", "pw").catch(() => undefined)}>login</button>
      <button onClick={logout}>logout</button>
    </div>
  );
}

const LOGIN_RESPONSE: LoginResponse = {
  access_token: "tok",
  token_type: "bearer",
  expires_in: 1800,
  role: "ops",
};

const ME_RESPONSE: AuthUser = { id: "u1", email: "a@example.com", role: "ops" };

function renderProbe() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

describe("AuthContext", () => {
  it("starts unauthenticated with no stored session", () => {
    renderProbe();
    expect(screen.getByTestId("authenticated")).toHaveTextContent("false");
    expect(getAuthToken()).toBeNull();
  });

  it("login stores the token and calls GET /auth/me to hydrate the user", async () => {
    vi.spyOn(authApi, "login").mockResolvedValue(LOGIN_RESPONSE);
    vi.spyOn(authApi, "me").mockResolvedValue(ME_RESPONSE);
    renderProbe();

    await userEvent.click(screen.getByRole("button", { name: "login" }));

    expect(await screen.findByTestId("user")).toHaveTextContent("a@example.com:ops");
    expect(screen.getByTestId("authenticated")).toHaveTextContent("true");
    expect(screen.getByTestId("has-ops")).toHaveTextContent("true");
    expect(getAuthToken()).toBe("tok");
    expect(JSON.parse(sessionStorage.getItem("omniflow.auth")!)).toEqual({
      token: "tok",
      user: ME_RESPONSE,
    });
  });

  it("logout clears in-memory state, the token, and sessionStorage", async () => {
    vi.spyOn(authApi, "login").mockResolvedValue(LOGIN_RESPONSE);
    vi.spyOn(authApi, "me").mockResolvedValue(ME_RESPONSE);
    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "login" }));
    await screen.findByTestId("user");

    await userEvent.click(screen.getByRole("button", { name: "logout" }));

    expect(screen.getByTestId("authenticated")).toHaveTextContent("false");
    expect(getAuthToken()).toBeNull();
    expect(sessionStorage.getItem("omniflow.auth")).toBeNull();
  });

  it("restores an already-stored session on mount, including the module-level token", () => {
    sessionStorage.setItem(
      "omniflow.auth",
      JSON.stringify({
        token: "stored-tok",
        user: { id: "u2", email: "b@example.com", role: "viewer" },
      }),
    );
    renderProbe();
    expect(screen.getByTestId("user")).toHaveTextContent("b@example.com:viewer");
    expect(getAuthToken()).toBe("stored-tok");
  });

  it("hasRole ranks viewer below ops (viewer < ops < admin)", async () => {
    vi.spyOn(authApi, "login").mockResolvedValue({ ...LOGIN_RESPONSE, role: "viewer" });
    vi.spyOn(authApi, "me").mockResolvedValue({
      id: "u3",
      email: "v@example.com",
      role: "viewer",
    });
    renderProbe();
    await userEvent.click(screen.getByRole("button", { name: "login" }));
    await screen.findByTestId("user");
    expect(screen.getByTestId("has-ops")).toHaveTextContent("false");
  });

  it("does not authenticate when the login call itself rejects", async () => {
    vi.spyOn(authApi, "login").mockRejectedValue(new Error("invalid credentials"));
    renderProbe();

    await userEvent.click(screen.getByRole("button", { name: "login" }));

    expect(screen.getByTestId("authenticated")).toHaveTextContent("false");
    expect(getAuthToken()).toBeNull();
  });
});
