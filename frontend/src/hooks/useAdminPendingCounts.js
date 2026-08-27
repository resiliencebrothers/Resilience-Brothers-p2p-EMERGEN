/**
 * useAdminPendingCounts — iter191
 * Live pending-matter counts per admin section (withdrawals hub, orders,
 * VIP batches, reconciliation) for the red sidebar badges. Polls every 45s
 * and refreshes instantly on relevant SSE events.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { useLiveEvent } from "@/hooks/useLiveStream";

const EMPTY = {
  withdrawals_hub: 0, withdrawals: 0, deposits: 0, capital_requests: 0,
  vip_batches: 0, orders: 0, reconciliation: 0,
};

export function useAdminPendingCounts() {
  const { user } = useAuth();
  const [counts, setCounts] = useState(EMPTY);
  const timerRef = useRef(null);
  const enabled = user && (user.role === "admin" || user.role === "employee");

  const refresh = useCallback(async () => {
    if (!enabled) return;
    try {
      const r = await axios.get(`${API}/admin/pending-counts`, { withCredentials: true });
      setCounts({ ...EMPTY, ...(r.data || {}) });
    } catch { /* best-effort badge */ }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return undefined;
    refresh();
    timerRef.current = setInterval(refresh, 45000);
    return () => clearInterval(timerRef.current);
  }, [enabled, refresh]);

  useLiveEvent(enabled ? "withdrawal_status_changed" : null, refresh);
  useLiveEvent(enabled ? "deposit_created" : null, refresh);
  useLiveEvent(enabled ? "order_status_changed" : null, refresh);
  useLiveEvent(enabled ? "reconciliation_import" : null, refresh);

  return { counts, refresh };
}
