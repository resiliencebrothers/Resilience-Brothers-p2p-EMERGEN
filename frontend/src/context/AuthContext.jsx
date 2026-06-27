import { createContext, useContext, useEffect, useState, useCallback, useMemo } from "react";
import axios from "axios";
import { API } from "@/App";
import { setSentryUser, captureError } from "@/sentry";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/auth/me`, { withCredentials: true });
      setUser(res.data);
      setSentryUser(res.data);
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
