"""Security middleware wiring: strict CORS, rate limiting, headers.

Central place for all defensive middleware so `server.py` stays a thin bootstrap.

All three concerns are driven by env vars so production/preview can differ:
- `CORS_ORIGINS` (required, comma-separated list — `*` is refused when
  `SENTRY_ENV=production` to prevent accidental prod misconfiguration).
- `RATE_LIMIT_ENABLED` (default `true` — set `false` in tests to bypass).
- `CSP_REPORT_URI` (optional — if present, adds `report-uri` to CSP).

iter47 — security hardening.
"""
import os
import logging
from typing import Callable, Awaitable

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------

def _parse_origins(raw: str) -> list[str]:
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def configure_cors(app: FastAPI) -> None:
    """Attach a strict CORSMiddleware. Rejects wildcard in production.

    Fallback (dev/preview when unset): allow the current preview origin from
    `APP_URL` plus `http://localhost:3000` for local development.
    """
    env = os.environ.get("SENTRY_ENV", "preview").lower()
    raw = os.environ.get("CORS_ORIGINS", "").strip()

    if raw == "*" and env == "production":
        raise RuntimeError(
            "CORS_ORIGINS='*' is refused in production. Set an explicit "
            "comma-separated allow-list (e.g. https://resiliencebrothers.com)."
        )

    if raw and raw != "*":
        origins = _parse_origins(raw)
    else:
        # Sensible default for preview/dev — never a wildcard.
        preview_url = os.environ.get("APP_URL", "").strip().rstrip("/")
        origins = [preview_url, "http://localhost:3000"] if preview_url else ["http://localhost:3000"]

    logger.info(f"CORS allow_origins ({env}): {origins}")
    app.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "Idempotency-Key"],
        expose_headers=["X-RateLimit-Remaining", "X-RateLimit-Reset"],
    )


# ---------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------

def _rate_key(request: Request) -> str:
    """Compose a rate-limit bucket per (route + real client IP).
    Behind Cloudflare/nginx, `X-Forwarded-For` is set; slowapi's
    `get_remote_address` already picks the left-most entry."""
    return get_remote_address(request)


# Global limiter — imported by routers to attach per-endpoint decorators.
limiter = Limiter(
    key_func=_rate_key,
    default_limits=["300/minute"],
    headers_enabled=True,
    enabled=os.environ.get("RATE_LIMIT_ENABLED", "true").lower() != "false",
)


def configure_rate_limiter(app: FastAPI) -> None:
    """Wire the global `limiter` to the FastAPI app.
    Individual routes opt-in to stricter buckets via `@limiter.limit("N/period")`.
    """
    app.state.limiter = limiter
    # mypy: slowapi handler is typed as `Callable[[Request, RateLimitExceeded], Response]`,
    # but Starlette expects `Callable[[Request, Exception], Response]`. The
    # runtime behaviour is correct (RateLimitExceeded IS-A Exception).
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------

# Content-Security-Policy for a React SPA served from the same origin as the API.
# `unsafe-inline` is required by shadcn/tailwind runtime styles; `unsafe-eval`
# is kept ONLY for dev (React devtools). Adjust `img-src` if you serve avatars
# from a CDN.
_CSP_PROD = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://accounts.google.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data: blob: https:; "
    "connect-src 'self' https://accounts.google.com https://oauth2.googleapis.com https://*.sentry.io wss:; "
    "frame-src 'self' https://accounts.google.com; "
    "frame-ancestors 'none'; "
    "form-action 'self' https://accounts.google.com; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "upgrade-insecure-requests"
)

_CSP_DEV = _CSP_PROD.replace(
    "script-src 'self' 'unsafe-inline'",
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Emits defensive HTTP response headers on every response.

    - `Strict-Transport-Security`: forces HTTPS for 6 months + preload eligible.
    - `X-Content-Type-Options: nosniff`: blocks MIME confusion attacks.
    - `X-Frame-Options: DENY`: iframe blocking (redundant with CSP frame-ancestors,
      kept for legacy browsers).
    - `Referrer-Policy: strict-origin-when-cross-origin`: minimises leak of
      full URLs to third parties on outbound links.
    - `Permissions-Policy`: disables sensitive browser APIs by default.
    - `Content-Security-Policy`: whitelist of allowed sources.
    """

    def __init__(self, app: FastAPI, env: str) -> None:
        super().__init__(app)
        self.env = env
        self.csp = _CSP_PROD if env == "production" else _CSP_DEV

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        # Do NOT overwrite headers that upstream middleware/routes may already set.
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=15552000; includeSubDomains; preload"
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
        )
        # CSP intentionally not set on API-only JSON responses to avoid breaking
        # 3rd-party callers; the FE HTML sends its own CSP via <meta>. Still we
        # apply a conservative default here.
        response.headers.setdefault("Content-Security-Policy", self.csp)
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        return response


class OriginAllowlistMiddleware(BaseHTTPMiddleware):
    """Defence-in-depth against `Access-Control-Allow-Origin: *` rewrites by
    upstream proxies (Emergent's Cloudflare + K8s ingress overrides our CORS
    headers with `*` on preflight). We enforce origin policy in-app: any
    write request (POST/PUT/PATCH/DELETE) carrying an `Origin` header that is
    not on the allow-list is rejected with 403 before hitting the handler.

    GET/HEAD/OPTIONS are always allowed (same-site fetches, public data
    endpoints, and the standard CORS preflight all need to succeed).
    Requests WITHOUT an Origin header (server-to-server, curl, test suite)
    are allowed — CSRF risk is mitigated by session cookies being SameSite=None
    only with an authenticated bearer token that server-to-server callers must
    supply explicitly.
    """

    UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app: FastAPI, allowed_origins: list[str]) -> None:
        super().__init__(app)
        # Normalise (strip trailing slash + lower-case) once for O(1) checks.
        self.allowed = {o.rstrip("/").lower() for o in allowed_origins}

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in self.UNSAFE_METHODS:
            origin = (request.headers.get("origin") or "").rstrip("/").lower()
            if origin and origin not in self.allowed:
                logger.warning(f"Blocked cross-origin {request.method} from {origin} to {request.url.path}")
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin request blocked (origin not in allow-list)."},
                )
        return await call_next(request)


def configure_security_headers(app: FastAPI) -> None:
    env = os.environ.get("SENTRY_ENV", "preview").lower()
    app.add_middleware(SecurityHeadersMiddleware, env=env)


def configure_origin_allowlist(app: FastAPI) -> None:
    """Compute allowed origins once and wire the OriginAllowlistMiddleware.
    Mirrors the CORS logic in configure_cors so both are in sync."""
    raw = os.environ.get("CORS_ORIGINS", "").strip()
    if raw and raw != "*":
        origins = _parse_origins(raw)
    else:
        preview_url = os.environ.get("APP_URL", "").strip().rstrip("/")
        origins = [preview_url, "http://localhost:3000"] if preview_url else ["http://localhost:3000"]
    if raw != "*":
        # Only enable the strict allow-list when CORS is configured; wildcard is
        # only ever legal in local dev.
        app.add_middleware(OriginAllowlistMiddleware, allowed_origins=origins)


# ---------------------------------------------------------------------
# One-shot wiring
# ---------------------------------------------------------------------

def install_security_middleware(app: FastAPI) -> None:
    """Wire all four defenses in the correct order.
    Order matters (middleware runs LIFO): security_headers wraps last so it
    applies to every response; then origin allowlist blocks cross-origin
    writes; then CORS answers preflight; then rate limiter throttles by IP."""
    configure_rate_limiter(app)
    configure_cors(app)
    configure_origin_allowlist(app)
    configure_security_headers(app)
