/**
 * iter97 — Global SSE live stream hook.
 *
 * Opens a single EventSource to /api/live/stream per browser tab and
 * multiplexes events to any consumer via `useLiveEvent(type, handler)`.
 *
 * Design:
 * - One connection per tab (React context + provider) — never per hook
 *   call, so the platform can have hundreds of subscribers without
 *   opening hundreds of sockets.
 * - Auto-reconnect with exponential back-off (1s, 2s, 4s, capped 30s)
 *   when the socket drops.
 * - Reconnects when the tab regains focus (visibilitychange) — mobile
 *   Safari / Android background-freezes the connection and doesn't
 *   fire `onerror`, so we re-open proactively.
 * - `useLiveEvent(type, handler)` registers a handler that will fire
 *   every time an event of that type arrives. Handler ref is kept
 *   fresh (useRef) so callers can pass inline arrows without
 *   re-subscribing on every render.
 *
 * Events we currently consume:
 *   • hello                     → connection confirmed
 *   • rates_updated             → any admin created/edited/deleted a rate
 *   • order_status_changed      → my order moved to a new status
 *   • withdrawal_status_changed → my withdrawal moved to a new status
 *   • balance_updated           → my VIP/company balance moved
 *   • order_created             → (admin/staff only) a client posted a new order
 *   • withdrawal_created        → (admin/staff only) a client posted a new withdrawal
 */
import {
  createContext, useContext, useEffect, useRef, useState, useCallback,
} from "react";
import { API } from "@/App";

const LiveCtx = createContext({
  connected: false,
  subscribe: () => () => {},
});

const BACKOFF_STEPS = [1000, 2000, 4000, 8000, 15000, 30000];

export function LiveStreamProvider({ children, enabled = true }) {
  const [connected, setConnected] = useState(false);
  const esRef = useRef(null);
  const listenersRef = useRef(new Map()); // event type → Set<handler>
  const backoffIdxRef = useRef(0);
  const reconnectTimeoutRef = useRef(null);

  const notify = useCallback((eventType, payload) => {
    const set = listenersRef.current.get(eventType);
    if (!set) return;
    set.forEach((h) => {
      try { h(payload); } catch (err) {
        // Isolate faulty handler — one bad subscriber must not stop the
        // rest from receiving the event.
        if (process.env.NODE_ENV !== "production") {
          console.warn(`[live] handler for "${eventType}" threw:`, err);
        }
      }
    });
  }, []);

  const closeStream = useCallback(() => {
    if (esRef.current) {
      try { esRef.current.close(); } catch (err) {
        if (process.env.NODE_ENV !== "production") {
          console.warn("[live] EventSource.close() threw:", err);
        }
      }
      esRef.current = null;
    }
  }, []);

  const openStream = useCallback(() => {
    if (!enabled) return;
    if (esRef.current) return;
    // `withCredentials` is required so the session_token cookie is
    // sent on the EventSource GET.
    const es = new EventSource(`${API}/live/stream`, { withCredentials: true });
    esRef.current = es;

    es.addEventListener("open", () => {
      setConnected(true);
      backoffIdxRef.current = 0;
    });

    // Every named event → dispatch to registered listeners.
    const forward = (type) => (msg) => {
      let data = null;
      try { data = JSON.parse(msg.data); } catch (_) { data = msg.data; }
      notify(type, data);
    };
    [
      "hello",
      "rates_updated",
      "order_status_changed",
      "withdrawal_status_changed",
      "balance_updated",
      "order_created",
      "withdrawal_created",
    ].forEach((t) => es.addEventListener(t, forward(t)));

    es.addEventListener("error", () => {
      setConnected(false);
      closeStream();
      // Reconnect with back-off.
      const delay = BACKOFF_STEPS[Math.min(backoffIdxRef.current, BACKOFF_STEPS.length - 1)];
      backoffIdxRef.current += 1;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = setTimeout(() => openStream(), delay);
    });
  }, [enabled, notify, closeStream]);

  useEffect(() => {
    if (!enabled) return () => {};
    openStream();
    // Mobile Safari / Android silently freeze socket in background;
    // force reconnect when the tab regains focus.
    const onVis = () => {
      if (document.visibilityState === "visible") {
        if (!esRef.current) openStream();
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      closeStream();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, [enabled, openStream, closeStream]);

  const subscribe = useCallback((eventType, handler) => {
    if (!listenersRef.current.has(eventType)) {
      listenersRef.current.set(eventType, new Set());
    }
    listenersRef.current.get(eventType).add(handler);
    return () => {
      const set = listenersRef.current.get(eventType);
      if (set) {
        set.delete(handler);
        if (set.size === 0) listenersRef.current.delete(eventType);
      }
    };
  }, []);

  return (
    <LiveCtx.Provider value={{ connected, subscribe }}>
      {children}
    </LiveCtx.Provider>
  );
}

/**
 * Subscribe to a single event type. The `handler` is stored in a ref
 * so components can pass inline arrows without triggering re-subscribes
 * on every render.
 */
export function useLiveEvent(eventType, handler) {
  const { subscribe } = useContext(LiveCtx);
  const handlerRef = useRef(handler);
  useEffect(() => { handlerRef.current = handler; }, [handler]);
  useEffect(() => {
    if (!eventType) return () => {};
    return subscribe(eventType, (data) => handlerRef.current && handlerRef.current(data));
  }, [eventType, subscribe]);
}

export function useLiveStatus() {
  return useContext(LiveCtx).connected;
}
