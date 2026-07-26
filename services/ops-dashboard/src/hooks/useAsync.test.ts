import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAsync } from "./useAsync";

describe("useAsync", () => {
  it("starts in the loading state, then resolves to success", async () => {
    const { result } = renderHook(() => useAsync(() => Promise.resolve(42), []));
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current.data).toBe(42);
  });

  it("transitions to the error state when the fetcher rejects", async () => {
    const { result } = renderHook(() => useAsync(() => Promise.reject(new Error("boom")), []));
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.message).toBe("boom");
  });

  it("re-runs the fetcher when refetch() is called", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce("first").mockResolvedValueOnce("second");
    const { result } = renderHook(() => useAsync(fetcher, []));
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current.data).toBe("first");

    act(() => result.current.refetch());
    await waitFor(() => expect(result.current.data).toBe("second"));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("resets to loading and re-fetches when deps change", async () => {
    const fetcher = vi.fn().mockImplementation((id: string) => Promise.resolve(`data-for-${id}`));
    const { result, rerender } = renderHook(({ id }) => useAsync(() => fetcher(id), [id]), {
      initialProps: { id: "a" },
    });
    await waitFor(() => expect(result.current.data).toBe("data-for-a"));

    rerender({ id: "b" });
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.data).toBe("data-for-b"));
  });
});
