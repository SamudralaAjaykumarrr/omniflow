import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  NetworkError,
  get,
  getAuthToken,
  post,
  setAuthToken,
  setUnauthorizedHandler,
} from "./client";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api/client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setAuthToken(null);
    setUnauthorizedHandler(null);
  });

  it("get() returns parsed JSON on a 2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ hello: "world" })));
    const result = await get<{ hello: string }>("/gw", "/healthz");
    expect(result).toEqual({ hello: "world" });
  });

  it("post() sends a JSON body and Content-Type header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await post("/gw", "/api/orders", { foo: "bar" });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ foo: "bar" });
  });

  it("throws ApiError with the backend's message on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ message: "order not found" }, 404)),
    );
    await expect(get("/gw", "/api/orders/missing")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      message: "order not found",
    });
  });

  it("ApiError falls back to a generic message when the body isn't JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", { status: 500 })));
    await expect(get("/gw", "/x")).rejects.toBeInstanceOf(ApiError);
  });

  it("throws NetworkError when fetch itself rejects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(get("/gw", "/x")).rejects.toBeInstanceOf(NetworkError);
  });

  it("returns undefined for a 204 No Content response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    const result = await get("/gw", "/x");
    expect(result).toBeUndefined();
  });

  describe("Phase 9 (JWT/RBAC) — auth token handling", () => {
    it("attaches an Authorization: Bearer header once a token is set", async () => {
      setAuthToken("my-token");
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
      vi.stubGlobal("fetch", fetchMock);

      await get("/gw", "/api/orders/1");

      const [, init] = fetchMock.mock.calls[0];
      expect(init.headers["Authorization"]).toBe("Bearer my-token");
    });

    it("sends no Authorization header when no token is set", async () => {
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
      vi.stubGlobal("fetch", fetchMock);

      await get("/gw", "/healthz");

      const [, init] = fetchMock.mock.calls[0];
      expect(init.headers).toBeUndefined();
    });

    it("getAuthToken reflects the most recently set token", () => {
      expect(getAuthToken()).toBeNull();
      setAuthToken("abc");
      expect(getAuthToken()).toBe("abc");
    });

    it("invokes the registered unauthorized handler on a 401 response", async () => {
      const handler = vi.fn();
      setUnauthorizedHandler(handler);
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "no" }, 401)));

      await expect(get("/gw", "/api/orders")).rejects.toBeInstanceOf(ApiError);
      expect(handler).toHaveBeenCalledOnce();
    });

    it("does not invoke the unauthorized handler on a non-401 error", async () => {
      const handler = vi.fn();
      setUnauthorizedHandler(handler);
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "forbidden" }, 403)));

      await expect(get("/gw", "/api/orders")).rejects.toBeInstanceOf(ApiError);
      expect(handler).not.toHaveBeenCalled();
    });
  });
});
