/**
 * Sentry initialization — frontend.
 *
 * Disabled by default. Activates only when
 *   REACT_APP_SENTRY_DSN
 * is configured at build time. Captures unhandled errors, network
 * failures, and (optionally) session replays for production.
 */
import * as Sentry from "@sentry/react";

export function initSentry() {
  const dsn = process.env.REACT_APP_SENTRY_DSN;
  if (!dsn) {
    // Silent no-op when DSN is missing (dev / preview without monitoring).
    return false;
  }
  const environment = process.env.REACT_APP_SENTRY_ENV || "production";
  const tracesRate = parseFloat(
    process.env.REACT_APP_SENTRY_TRACES_SAMPLE_RATE || "0.1",
  );
  const release = process.env.REACT_APP_SENTRY_RELEASE || undefined;

  Sentry.init({
    dsn,
    environment,
    release,
    tracesSampleRate: tracesRate,
    // Replay only on errors (cheap on free tier).
    replaysSessionSampleRate: 0.0,
    replaysOnErrorSampleRate: 1.0,
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.replayIntegration({ maskAllText: true, blockAllMedia: true }),
    ],
    sendDefaultPii: false,
    beforeSend(event) {
      // Drop noisy errors we don't care about
      const msg = event.message || event.exception?.values?.[0]?.value || "";
      if (typeof msg === "string") {
        const noise = [
          "ResizeObserver loop limit",
          "Non-Error promise rejection captured",
          "Network request failed",  // user offline, not actionable
        ];
        if (noise.some((n) => msg.includes(n))) return null;
      }
      return event;
    },
  });
  return true;
}

/**
 * Tag the current actor on every Sentry event. Called from AuthContext once
 * the user is loaded; called with `null` on logout.
 */
export function setSentryUser(user) {
  if (!process.env.REACT_APP_SENTRY_DSN) return;
  if (!user) {
    Sentry.setUser(null);
    return;
  }
  Sentry.setUser({
    id: user.user_id,
    email: user.email,
    role: user.role,
  });
}

/** Shortcut to manually capture an exception with extra context. */
export function captureError(err, context) {
  if (!process.env.REACT_APP_SENTRY_DSN) {
    // Fallback to console in dev so we don't swallow errors.
    // eslint-disable-next-line no-console
    console.error(err, context);
    return;
  }
  Sentry.withScope((scope) => {
    if (context) scope.setContext("extra", context);
    Sentry.captureException(err);
  });
}
