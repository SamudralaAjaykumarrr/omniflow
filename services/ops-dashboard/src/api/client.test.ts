import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, NetworkError, get, post } from "./client";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api/client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
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
});
