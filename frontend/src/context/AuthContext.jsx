import { createContext, useContext, useEffect, useRef, useState, useCallback, useMemo } from "react";
import axios from "axios";
import i18n from "@/i18n";
import { API } from "@/App";
import { setSentryUser, captureError } from "@/sentry";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  // iter55.36p — guard against React.StrictMode's intentional double-invoke of
  // useEffect (dev + preview builds). Without this, /api/auth/me is hit twice on
  // every hard-refresh, which produces spurious 401 pairs in the browser
  // console whenever the session cookie hasn't fully propagated yet.
  const initialAuthChecked = useRef(false);

  const checkAuth = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/auth/me`, { withCredentials: true });
      setUser(res.data);
      setSentryUser(res.data);
      // iter67 — Sync UI language with the user's server-side preference so
      // it follows them across devices. If they haven't picked one yet, we
      // leave whatever the browser detected in place (won't nag them).
      const preferred = res.data?.preferred_language;
      if (preferred && preferred !== (i18n.resolvedLanguage || i18n.language)) {
        i18n.changeLanguage(preferred);
      }
    } catch (err) {
      if (err?.response?.status !== 401) {
        captureError(err, { stage: "auth_check" });
      }
      setUser(null);
      setSentryUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (window.location.hash?.includes("session_id=")) {
      setLoading(false);
      return;
    }
    if (initialAuthChecked.current) return;
    initialAuthChecked.current = true;
    checkAuth();
  }, [checkAuth]);

  const logout = useCallback(async () => {
    try {
      await axios.post(`${API}/auth/logout`, {}, { withCredentials: true });
    } catch (err) {
      captureError(err, { stage: "logout" });
    }
    setUser(null);
    setSentryUser(null);
    window.location.href = "/";
  }, []);

  const login = useCallback(() => {
    // iter22 — Custom Google OAuth (replaces auth.emergentagent.com).
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    window.location.href = `${API}/auth/google/login`;
  }, []);

  const value = useMemo(
    () => ({ user, setUser, loading, logout, login, refresh: checkAuth }),
    [user, loading, logout, login, checkAuth]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
