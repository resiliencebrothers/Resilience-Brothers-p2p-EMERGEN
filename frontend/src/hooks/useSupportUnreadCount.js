/**
 * useSupportUnreadCount — iter107.1
 *
 * Powers the "🔴 N" pill next to the "Usuarios" nav item in the admin
 * sidebar. Keeps the counter fresh by:
 *   1. Fetching /admin/support/unread-count on mount.
 *   2. Refetching whenever the live-bus emits `support_ticket_created`
 *      or `support_ticket_updated` (so a new client ticket lights up the
 *      sidebar instantly without waiting for the poll interval).
 *   3. Polling every 60s as a fallback for tabs whose SSE dropped.
 *
 * Only runs for staff with the `support` permission — no-op for clients
 * so we don't hit the endpoint from `/dashboard`.
 */
import { useEffect, useState, useCallback, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { captureError } from "@/sentry";

const POLL_MS = 60_000;

function hasSupportPerm(user) {
  if (!user) return false;
  if (user.role === "admin") return true;
  if (user.role !== "employee") return false;
  const perms = user.allowed_permissions || [];
  return perms.length === 0 || perms.includes("support");
}

export function useSupportUnreadCount() {
  const { user } = useAuth();
  const enabled = hasSupportPerm(user);
  const [unread, setUnread] = useState(0);
  const pollRef = useRef(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    try {
      const r = await axios.get(`${API}/admin/support/unread-count`, {
        withCredentials: true,
      });
      setUnread(r.data?.unread || 0);
    } catch (err) {
      captureError(err, { stage: "support.unread_count" });
    }
  }, [enabled]);

  // Initial fetch + 60s polling fallback.
  useEffect(() => {
    if (!enabled) { setUnread(0); return () => {}; }
    refresh();
    pollRef.current = setInterval(refresh, POLL_MS);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [enabled, refresh]);

  // Realtime bumps whenever a ticket is created / replied / closed.
  useLiveEvent(enabled ? "support_ticket_created" : null, refresh);
  useLiveEvent(enabled ? "support_ticket_updated" : null, refresh);

  return { unread, refresh };
}
