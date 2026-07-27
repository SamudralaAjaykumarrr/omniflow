import type { ApiErrorBody } from "./types";

/**
 * Base paths for the four real backends this dashboard talks to. In
 * production (the Docker image) these are same-origin paths that
 * services/ops-dashboard/nginx.conf reverse-proxies to the matching
 * container; in `npm run dev` they're proxied by vite.config.ts's dev
 * server instead. Either way the browser only ever calls same-origin
 * paths, so no CORS configuration is needed on any backend service.
 */
export const API_BASE = {
  gateway: "/gw",
  inventory: "/inventory-api",
  orchestrator: "/orchestrator-api",
  prometheus: "/prom-api",
  failureLab: "/failure-lab-api",
} as const;

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody | undefined;

  constructor(status: number, message: string, body?: ApiErrorBody) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export class NetworkError extends Error {
  constructor(cause: unknown) {
    super("Network request failed — the backend may be unreachable.");
    this.name = "NetworkError";
    this.cause = cause;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 8000;

// Phase 9 (JWT/RBAC): the current session's bearer token, set/cleared by
// AuthContext — a plain module-level variable (not React state) since
// every API call in this file is a plain function, not a component. A 401
// from any backend call clears it and notifies AuthContext via
// `onUnauthorized`, so an expired/invalidated token doesn't keep getting
// silently resent.
let authToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
}

export function getAuthToken(): string | null {
  return authToken;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

async function request<T>(base: string, path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS);

  const externalSignal = options.signal;
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  const headers: Record<string, string> = {};
  if (options.body) headers["Content-Type"] = "application/json";
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      method: options.method ?? "GET",
      headers: Object.keys(headers).length > 0 ? headers : undefined,
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });
  } catch (cause) {
    throw new NetworkError(cause);
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = undefined;
    }
    if (response.status === 401) {
      onUnauthorized?.();
    }
    const message =
      body?.message ?? body?.detail ?? `Request failed with status ${response.status}`;
    throw new ApiError(response.status, message, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function get<T>(
  base: string,
  path: string,
  options?: Omit<RequestOptions, "method" | "body">,
) {
  return request<T>(base, path, { ...options, method: "GET" });
}

export function post<T>(
  base: string,
  path: string,
  body?: unknown,
  options?: Omit<RequestOptions, "method" | "body">,
) {
  return request<T>(base, path, { ...options, method: "POST", body });
}
