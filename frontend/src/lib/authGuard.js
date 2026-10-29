/**
 * authGuard — pure, React-free auth-state helpers (auditoría AUTH-01/02/03).
 *
 * Extracted so the race/validation logic is unit-testable the same way as
 * `latestResponseGuard`. AuthContext wires these into axios + React state.
 */

// Auth state machine (AUTH-02): a user whose session could not be checked due
// to a transient network/5xx error (ERROR, recoverable) must be told apart
// from one that is confirmed-anonymous (ANONYMOUS, redirect to login).
export const AUTH_STATUS = {
  CHECKING: "checking",
  AUTHENTICATED: "authenticated",
  ANONYMOUS: "anonymous",
  ERROR: "error",
};

// AUTH-03 — a resolved HTTP 200 is NOT proof of identity. Any user object we
// trust must carry a coherent contract (non-empty string user_id + role).
export function isValidUser(u) {
  return !!(
    u &&
    typeof u === "object" &&
    typeof u.user_id === "string" && u.user_id.length > 0 &&
    typeof u.role === "string" && u.role.length > 0
  );
}

// AUTH-01 — monotonic auth generation. Every login/logout bumps it; any auth
// response whose captured generation is stale must be discarded on resolve so
// it can neither wipe a newer login nor restore a user after logout/switch.
export function createAuthGeneration() {
  let gen = 0;
  return {
    current() { return gen; },
    bump() { gen += 1; return gen; },
    isStale(captured) { return captured !== gen; },
  };
}

/**
 * AUTH-02 — map a /auth/me outcome to the next {user, status}.
 * @param {{user: any}} prev        current identity (user may be null)
 * @param {{ok: boolean, user?: any, httpStatus?: number}} outcome
 */
export function reduceAuthCheck(prev, outcome) {
  if (outcome.ok) {
    return isValidUser(outcome.user)
      ? { user: outcome.user, status: AUTH_STATUS.AUTHENTICATED }
      : { user: null, status: AUTH_STATUS.ANONYMOUS };
  }
  if (outcome.httpStatus === 401) {
    // Definitive "not authenticated" → confirmed anonymous.
    return { user: null, status: AUTH_STATUS.ANONYMOUS };
  }
  // Transient: network loss / 5xx / timeout. Never drop a confirmed session.
  return prev && prev.user
    ? { user: prev.user, status: AUTH_STATUS.AUTHENTICATED }
    : { user: null, status: AUTH_STATUS.ERROR };
}

/**
 * AUTH-03 — a login is trustworthy only if the confirmation /auth/me returns a
 * valid identity matching the login response.
 */
export function confirmLoginIdentity(loginUser, meUser) {
  if (!isValidUser(loginUser)) return { ok: false, reason: "login_invalid" };
  if (!isValidUser(meUser)) return { ok: false, reason: "me_invalid" };
  if (loginUser.user_id !== meUser.user_id) return { ok: false, reason: "mismatch" };
  return { ok: true };
}
