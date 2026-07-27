import { API_BASE, get, post } from "./client";
import type { AuthUser, LoginResponse } from "./types";

export function login(email: string, password: string): Promise<LoginResponse> {
  return post<LoginResponse>(API_BASE.gateway, "/auth/login", { email, password });
}

export function me(): Promise<AuthUser> {
  return get<AuthUser>(API_BASE.gateway, "/auth/me");
}
