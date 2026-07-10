/**
 * useNotifications — iter38.
 *
 * Custom hook split from NotificationBell. Centralises:
 *   - polling /notifications/unread-count every 30 s
 *   - fetching the list on demand
 *   - mark-read + mark-all-read mutations
 *   - error reporting through Sentry (no silent swallows)
 *
 * Returns `{ unreadCount, items, loading, loadList, markRead, markAllRead }`.
 */
import { useEffect, useState, useCallback, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { captureError } from "@/sentry";

const POLL_MS = 30_000;

export function useNotifications() {
  const { user } = useAuth();
  const [unreadCount, setUnreadCount] = useState(0);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const pollRef = useRef(null);

  const refreshCount = useCallback(async () => {
    if (!user) return;
    try {
      const r = await axios.get(`${API}/notifications/unread-count`, { withCredentials: true });
      setUnreadCount(r.data?.count || 0);
    } catch (err) {
      // Poll error — don't block the UI but surface to Sentry so we notice
      // recurring backend issues (e.g., notifications service down).
      captureError(err, { stage: "notifications.unread_count" });
    }
  }, [user]);

  const loadList = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const r = await axios.get(`${API}/notifications`, {
        withCredentials: true, params: { limit: 30 },
      });
      setItems(r.data?.items || []);
    } catch (err) {
      captureError(err, { stage: "notifications.list" });
    } finally {
      setLoading(false);
    }
  }, [user]);

  const markRead = useCallback(async (id) => {
    try {
      await axios.post(`${API}/notifications/${id}/read`, {}, { withCredentials: true });
      setItems((prev) => prev.map((it) => (it.id === id ? { ...it, read: true } : it)));
      refreshCount();
    } catch (err) {
      captureError(err, { stage: "notifications.mark_read", id });
    }
  }, [refreshCount]);

  const markAllRead = useCallback(async () => {
    try {
      await axios.post(`${API}/notifications/mark-all-read`, {}, { withCredentials: true });
      setItems((prev) => prev.map((it) => ({ ...it, read: true })));
      setUnreadCount(0);
    } catch (err) {
      captureError(err, { stage: "notifications.mark_all_read" });
    }
  }, []);

  const deleteOne = useCallback(async (id) => {
    // Optimistic UI: drop the row immediately, roll back on failure.
    let snapshot = [];
    setItems((prev) => {
      snapshot = prev;
      return prev.filter((it) => it.id !== id);
    });
    try {
      await axios.delete(`${API}/notifications/${id}`, { withCredentials: true });
      refreshCount();
    } catch (err) {
      captureError(err, { stage: "notifications.delete_one", id });
      setItems(snapshot);  // rollback
    }
  }, [refreshCount]);

  const deleteAllRead = useCallback(async () => {
    let snapshot = [];
    setItems((prev) => {
      snapshot = prev;
      return prev.filter((it) => !it.read);
    });
    try {
      await axios.delete(`${API}/notifications/read`, { withCredentials: true });
      refreshCount();
    } catch (err) {
      captureError(err, { stage: "notifications.delete_read" });
      setItems(snapshot);
    }
  }, [refreshCount]);

  useEffect(() => {
    if (!user) return;
    refreshCount();
    pollRef.current = setInterval(refreshCount, POLL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [user, refreshCount]);

  return { unreadCount, items, loading, loadList, markRead, markAllRead, deleteOne, deleteAllRead };
}
