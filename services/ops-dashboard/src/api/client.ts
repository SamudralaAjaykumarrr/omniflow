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

async function request<T>(base: string, path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS);

  const externalSignal = options.signal;
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      method: options.method ?? "GET",
      headers: options.body ? { "Content-Type": "application/json" } : undefined,
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
