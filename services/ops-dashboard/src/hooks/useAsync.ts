import { useCallback, useEffect, useRef, useState } from "react";

export type AsyncState<T> =
  | { status: "loading"; data?: undefined; error?: undefined }
  | { status: "error"; error: Error; data?: undefined }
  | { status: "success"; data: T; error?: undefined };

interface UseAsyncOptions {
  /** Re-run the fetcher on this interval (ms) while the component is mounted. */
  pollIntervalMs?: number;
}

/**
 * Generic async-data hook: tracks loading/error/success explicitly (never
 * conflates "no data yet" with "failed") and exposes `refetch` for manual
 * retries plus optional polling for live-ish screens (Observability).
 *
 * Deps are joined into a string key so callers can pass inline fetcher
 * closures without an exhaustive-deps violation, and — per React's
 * documented "adjusting state during rendering" pattern
 * (https://react.dev/reference/react/useState#storing-information-from-previous-renders)
 * — a deps-key change resets `state` to "loading" synchronously during
 * render, not via a synchronous `setState` inside the effect body (which
 * `react-hooks/set-state-in-effect` flags).
 */
export function useAsync<T>(
  fetcher: () => Promise<T>,
  deps: React.DependencyList,
  options: UseAsyncOptions = {},
): AsyncState<T> & { refetch: () => void } {
  const depsKey = deps.join("|");
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });
  const [resolvedDepsKey, setResolvedDepsKey] = useState(depsKey);
  const [tick, setTick] = useState(0);

  if (depsKey !== resolvedDepsKey) {
    setResolvedDepsKey(depsKey);
    setState({ status: "loading" });
  }

  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;

    fetcherRef
      .current()
      .then((data) => {
        if (!cancelled) setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            error: error instanceof Error ? error : new Error(String(error)),
          });
        }
      });

    let interval: ReturnType<typeof setInterval> | undefined;
    if (options.pollIntervalMs) {
      interval = setInterval(() => setTick((t) => t + 1), options.pollIntervalMs);
    }

    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
    // depsKey/tick intentionally stand in for `deps`/`fetcher` — see the doc comment above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depsKey, tick]);

  return { ...state, refetch };
}
