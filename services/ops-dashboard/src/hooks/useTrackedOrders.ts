import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "omniflow.trackedOrderIds";

/**
 * Order Service has no list-all-orders endpoint (checked: only
 * GET /orders/{id} and /orders/{id}/history exist — see
 * docs/phase-7-ops-dashboard.md "Missing API contracts"). Rather than add
 * one to a service this phase doesn't otherwise touch, the dashboard tracks
 * order IDs it has created or been given client-side, then fetches each
 * one's real current state individually. This is real data about real
 * orders — just client-curated, not server-listed.
 */
export function useTrackedOrders() {
  const [ids, setIds] = useState<string[]>(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      return raw ? (JSON.parse(raw) as string[]) : [];
    } catch {
      return [];
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
    } catch {
      // localStorage unavailable (private browsing, quota) — tracking is
      // best-effort UX, not a source of truth, so failing silently is safe.
    }
  }, [ids]);

  const addOrder = useCallback((orderId: string) => {
    setIds((prev) => (prev.includes(orderId) ? prev : [orderId, ...prev]));
  }, []);

  const removeOrder = useCallback((orderId: string) => {
    setIds((prev) => prev.filter((id) => id !== orderId));
  }, []);

  return { ids, addOrder, removeOrder };
}
