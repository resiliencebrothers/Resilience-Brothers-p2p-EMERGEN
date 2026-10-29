import { createContext, useContext, useEffect, useRef, useState, useCallback, useMemo } from "react";
import axios from "axios";
import { API } from "@/App";
import { setSentryUser, captureError } from "@/sentry";
import { applyServerLanguage } from "@/lib/langSync";
import {
  AUTH_STATUS,
  isValidUser,
  createAuthGeneration,
  reduceAuthCheck,
  confirmLoginIdentity,
} from "@/lib/authGuard";

export { AUTH_STATUS };

const AuthContext = createContext(null);

// Thrown when credentials were accepted but the session could not be confirmed
// (cookie not stored, /auth/me not recognising it, identity drift). The UI
// shows "No se pudo confirmar la sesión" — never "contraseña incorrecta".
export class SessionUnconfirmedError extends Error {
  constructor(message) {
    super(message || "SESSION_UNCONFIRMED");
    this.name = "SessionUnconfirmedError";
    this.code = "SESSION_UNCONFIRMED";
  }
}

// R2 — thrown when a sign-in attempt is superseded by a newer generation
// (logout or another login) while it awaited the network. The form must
// ignore it silently: no success toast, no redirect, no credentials error.
export class AuthAttemptStaleError extends Error {
  constructor(message) {
    super(message || "AUTH_STALE");
    this.name = "AuthAttemptStaleError";
    this.code = "AUTH_STALE";
  }
}

export function AuthProvider({ children }) {
  const [user, setUserState] = useState(null);
  const [status, setStatus] = useState(AUTH_STATUS.CHECKING);
  const [loading, setLoading] = useState(true);

  // Mirror of `user` readable inside async closures without re-creating them.
  const userRef = useRef(null);
  useEffect(() => { userRef.current = user; }, [user]);

  // AUTH-01 — monotonic auth generation shared by every auth response.
  const authGenRef = useRef(null);
  if (authGenRef.current === null) authGenRef.current = createAuthGeneration();
  const authGen = authGenRef.current;

  // iter55.36p — guard against React.StrictMode's intentional double-invoke of
  // the mount effect so the initial /auth/me does not fire twice.
  const initialAuthChecked = useRef(false);

  const clearIdentity = useCallback((nextStatus) => {
    setUserState(null);
    userRef.current = null;
    setSentryUser(null);
    setStatus(nextStatus);
  }, []);

  const applyIdentity = useCallback((data) => {
    setUserState(data);
    userRef.current = data;
    setStatus(AUTH_STATUS.AUTHENTICATED);
    setSentryUser(data);
    // iter67/iter154 — follow the user's saved UI language across devices.
    applyServerLanguage(data);
  }, []);

  // Raw setter kept for callers that patch an already-authenticated identity in
  // place (e.g. onboarding flag). It never resets the generation.
  const setUser = useCallback((next) => {
    setUserState((prev) => {
      const value = typeof next === "function" ? next(prev) : next;
      userRef.current = value;
      if (isValidUser(value)) {
        setStatus(AUTH_STATUS.AUTHENTICATED);
        setSentryUser(value);
      } else if (value == null) {
        setStatus(AUTH_STATUS.ANONYMOUS);
        setSentryUser(null);
      }
      return value;
    });
  }, []);

  const checkAuth = useCallback(async () => {
    const gen = authGen.current();
    const MAX_ATTEMPTS = 3;
    let outcome;
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      try {
        const res = await axios.get(`${API}/auth/me`, { withCredentials: true });
        outcome = { ok: true, user: res.data };
        break;
      } catch (err) {
        const httpStatus = err?.response?.status;
        outcome = { ok: false, httpStatus };
        if (httpStatus === 401) break;              // definitive — no retry
        if (authGen.isStale(gen)) return null;       // a newer login/logout happened
        // "Sesión más estable" — reintento automático breve ante cortes de red
        // / 5xx para que el usuario rara vez vea la pantalla de reintento.
        if (attempt < MAX_ATTEMPTS) {
          await new Promise((r) => setTimeout(r, 600 * attempt));
          continue;
        }
        captureError(err, { stage: "auth_check" });  // only after the final try
      }
    }
    // AUTH-01 — discard a response that predates a newer login/logout.
    if (authGen.isStale(gen)) return null;
    if (outcome.ok && isValidUser(outcome.user)) {
      applyIdentity(outcome.user);
      setLoading(false);
      return outcome.user;
    }
    // AUTH-02 — transient errors keep a confirmed session alive.
    const next = reduceAuthCheck({ user: userRef.current }, outcome);
    if (next.user) {
      setStatus(AUTH_STATUS.AUTHENTICATED);
    } else {
      clearIdentity(next.status);
    }
    setLoading(false);
    return null;
  }, [authGen, applyIdentity, clearIdentity]);

  useEffect(() => {
    if (window.location.hash?.includes("session_id=")) {
      // Google OAuth callback handles its own commit; skip the mount check.
      setLoading(false);
      return;
    }
    if (initialAuthChecked.current) return;
    initialAuthChecked.current = true;
    checkAuth();
  }, [checkAuth]);

  const logout = useCallback(async () => {
    // AUTH-01 — invalidate every in-flight auth response before clearing so a
    // late success cannot restore the just-logged-out identity.
    authGen.bump();
    try {
      await axios.post(`${API}/auth/logout`, {}, { withCredentials: true });
    } catch (err) {
      captureError(err, { stage: "logout" });
    }
    clearIdentity(AUTH_STATUS.ANONYMOUS);
    window.location.href = "/";
  }, [authGen, clearIdentity]);

  // "Cerrar sesión en todos los dispositivos" (sospecha de acceso indebido).
  // El backend sube session_version (invalida TODA sesión emitida) y borra las
  // filas de sesión; aquí limpiamos el estado local y volvemos al inicio. Hay
  // que iniciar sesión de nuevo en todas partes.
  const logoutAll = useCallback(async () => {
    // Revoke on the server FIRST; only once it succeeds do we invalidate
    // in-flight checks and clear local state. If the POST fails the caller
    // shows an error and the user stays logged in with checks intact.
    await axios.post(`${API}/auth/logout-all`, {}, { withCredentials: true });
    authGen.bump();
    clearIdentity(AUTH_STATUS.ANONYMOUS);
    window.location.href = "/";
  }, [authGen, clearIdentity]);

  const login = useCallback(() => {
    // iter22 — Custom Google OAuth (replaces auth.emergentagent.com).
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    window.location.href = `${API}/auth/google/login`;
  }, []);

  // AUTH-03 — single entry point for email/password sign-in. Announces success
  // ONLY after (1) the server accepts the credentials, (2) the returned object
  // matches the user contract, and (3) an authenticated /auth/me confirms the
  // session cookie persisted and resolves to the SAME identity.
  const signInWithPassword = useCallback(async (body) => {
    authGen.bump();                      // discard any earlier mount /auth/me (AUTH-01)
    const gen = authGen.current();
    try {
      // (1) Credentials. HTTP errors (401/403/429…) propagate unchanged so the
      //     dialog shows the exact server message (wrong password, etc.).
      const res = await axios.post(`${API}/auth/login`, body, { withCredentials: true });
      // R2 — if a newer generation (logout / another login) took over while we
      // awaited, this attempt is OBSOLETE: stop now and NEVER report success.
      if (authGen.isStale(gen)) throw new AuthAttemptStaleError();
      // (3) Confirm the session really exists before granting access.
      let confirmed;
      try {
        const me = await axios.get(`${API}/auth/me`, { withCredentials: true });
        confirmed = me.data;
      } catch (err) {
        throw new SessionUnconfirmedError("/auth/me did not confirm the session");
      }
      if (authGen.isStale(gen)) throw new AuthAttemptStaleError();   // R2 (post-confirm)
      const verdict = confirmLoginIdentity(res.data, confirmed);
      if (!verdict.ok) throw new SessionUnconfirmedError(verdict.reason);
      applyIdentity(confirmed);
      setLoading(false);
      return confirmed;
    } catch (err) {
      // RESIDUAL (auditoría login) — un intento OBSOLETO (un logout u otro
      // login lo invalidó mientras esperaba) NUNCA publica su error tardío:
      // tanto un POST antiguo fallido como un /auth/me de confirmación fallido
      // se reportan como AUTH_STALE, de modo que el formulario no muestre aviso
      // de «sesión no confirmada», toast ni navegación de un intento ya
      // abandonado. Esta comprobación debe ser lo PRIMERO del catch exterior.
      if (authGen.isStale(gen)) {
        throw err?.code === "AUTH_STALE" ? err : new AuthAttemptStaleError();
      }
      // R1 — solo el intento VIGENTE finaliza el estado del proveedor para que
      // una ruta protegida nunca quede en checking/loading=true: re-resuelve la
      // sesión real (un login fallido no prueba que no exista una cookie válida
      // previa) con estado definitivo + loading=false, y propaga el error real.
      checkAuth();
      throw err;
    }
  }, [authGen, applyIdentity, checkAuth]);

  // Commit an identity obtained out of band (Google OAuth callback). Bumps the
  // generation and validates the contract just like the password flow.
  const commitSession = useCallback((data) => {
    authGen.bump();
    if (!isValidUser(data)) {
      throw new SessionUnconfirmedError("session response has no valid identity");
    }
    applyIdentity(data);
    setLoading(false);
    return data;
  }, [authGen, applyIdentity]);

  const value = useMemo(
    () => ({
      user,
      status,
      loading,
      setUser,
      logout,
      logoutAll,
      login,
      signInWithPassword,
      commitSession,
      refresh: checkAuth,
      retry: checkAuth,
    }),
    [user, status, loading, setUser, logout, logoutAll, login, signInWithPassword, commitSession, checkAuth]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
