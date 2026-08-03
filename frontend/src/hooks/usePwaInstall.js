import { useCallback, useEffect, useState } from "react";

// Non-sensitive UI preference (dismiss timestamp only — no tokens/PII), so
// plain localStorage is the right storage: it must persist across sessions.
const DISMISS_KEY = "rb_install_dismissed_until";
const DISMISS_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

/**
 * Module-level singleton for the `beforeinstallprompt` event so it stays
 * captured across mount/unmount of consumer components (Sheet portals,
 * conditional dialogs, etc.). Chrome fires the event exactly ONCE per
 * page load, so any component that mounts after that point would miss
 * it if we relied purely on a local useEffect listener.
 */
let deferredEvent = null;
let standaloneCached = null;
const listeners = new Set();

function notify() {
  listeners.forEach((fn) => fn());
}

// Register the global listener as soon as this module is imported, which
// happens as part of the JS bundle before React even mounts.
if (typeof window !== "undefined") {
  const captureHandler = (e) => {
    e.preventDefault();
    deferredEvent = e;
    notify();
  };
  const installedHandler = () => {
    deferredEvent = null;
    standaloneCached = true;
    notify();
  };
  window.addEventListener("beforeinstallprompt", captureHandler);
  window.addEventListener("appinstalled", installedHandler);
}

function detectStandalone() {
  if (standaloneCached !== null) return standaloneCached;
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true
  );
}

/**
 *   const { canInstall, isIos, isStandalone, install, dismiss } = usePwaInstall();
 */
export function usePwaInstall() {
  const [, forceRender] = useState(0);

  useEffect(() => {
    const fn = () => forceRender((n) => n + 1);
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  }, []);

  const ua = typeof navigator !== "undefined" ? navigator.userAgent : "";
  const isIos = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
  const isStandalone = detectStandalone();

  const install = useCallback(async () => {
    if (!deferredEvent) return { outcome: "unavailable" };
    deferredEvent.prompt();
    const choice = await deferredEvent.userChoice;
    deferredEvent = null;
    notify();
    return choice;
  }, []);

  const dismiss = useCallback(() => {
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now() + DISMISS_MS));
      notify();
    } catch { /* localStorage blocked */ }
  }, []);

  const isDismissed = (() => {
    try {
      const until = Number(localStorage.getItem(DISMISS_KEY) || 0);
      return until > Date.now();
    } catch {
      return false;
    }
  })();

  return {
    canInstall: !!deferredEvent,
    isIos,
    isStandalone,
    isDismissed,
    install,
    dismiss,
  };
}
