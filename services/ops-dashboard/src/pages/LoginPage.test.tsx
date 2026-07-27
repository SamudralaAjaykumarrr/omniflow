import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { LoginPage } from "./LoginPage";
import { AuthProvider } from "../auth/AuthContext";
import * as authApi from "../api/auth";
import { ApiError } from "../api/client";

function renderLoginPage() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<div>home page</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  it("logs in with valid credentials and navigates to the redirect target", async () => {
    vi.spyOn(authApi, "login").mockResolvedValue({
      access_token: "tok",
      token_type: "bearer",
      expires_in: 1800,
      role: "ops",
    });
    vi.spyOn(authApi, "me").mockResolvedValue({ id: "u1", email: "ops@example.com", role: "ops" });
    renderLoginPage();

    await userEvent.type(screen.getByLabelText(/email/i), "ops@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText("home page")).toBeInTheDocument();
  });

  it("shows an error message and stays on the login page for wrong credentials", async () => {
    vi.spyOn(authApi, "login").mockRejectedValue(new ApiError(401, "invalid email or password"));
    renderLoginPage();

    await userEvent.type(screen.getByLabelText(/email/i), "ops@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid email or password/i);
    expect(screen.queryByText("home page")).not.toBeInTheDocument();
  });

  it("disables the submit button while the request is in flight", async () => {
    let resolveLogin: (value: {
      access_token: string;
      token_type: string;
      expires_in: number;
      role: "ops";
    }) => void = () => undefined;
    vi.spyOn(authApi, "login").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveLogin = resolve;
        }),
    );
    vi.spyOn(authApi, "me").mockResolvedValue({ id: "u1", email: "ops@example.com", role: "ops" });
    renderLoginPage();

    await userEvent.type(screen.getByLabelText(/email/i), "ops@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled();
    resolveLogin({ access_token: "tok", token_type: "bearer", expires_in: 1800, role: "ops" });

    // Let the pending state update (submitting -> false, then navigate) settle
    // inside this test's own act() scope rather than leaking into the next test.
    expect(await screen.findByText("home page")).toBeInTheDocument();
  });
});
