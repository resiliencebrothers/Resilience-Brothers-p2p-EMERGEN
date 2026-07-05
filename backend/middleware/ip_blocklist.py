"""Application-level IP blocklist middleware (iter50b).

Reads active blocks from `cloudflare_ip_blocks` (collection name kept for
continuity with iter50 persistence layer) and returns 403 for any request
whose real client IP appears in the blocklist.

Why app-level instead of Cloudflare WAF?
- Emergent's platform already fronts our app with THEIR Cloudflare instance,
  so the `p2p.resiliencebrothers.com` traffic never reaches our own Cloudflare
  zone. Enforcing at the app layer is the only way to give admins actionable
  IP-blocking that actually protects the P2P app.

Design:
- Cache the active-block IP set in-process for 30s. Trade-off: an admin
  create/delete propagates within 30s worst-case (invalidate_cache() is
  called from the admin endpoints for instant effect).
- Records with status in {active, failed, pending_create} are ALL treated as
  blocked. `failed` means the CF sync failed but the admin decision was to
  block — we honor it at the app layer.
- Records with status in {deleted, pending_delete} are NOT enforced (admin
  chose to unblock).

Ordering: this middleware is added LAST in `install_security_middleware`, so
it runs FIRST for incoming requests (Starlette middleware is LIFO). Blocked
IPs are dropped before slowapi consumes a rate-limit slot.
"""
import logging
import time
from typing import Awaitable, Callable, Set

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from db_client import db
from services.security_events import _client_ip

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30
_BLOCKED_STATUSES = ("active", "failed", "pending_create")


class _BlocklistCache:
    def __init__(self) -> None:
        self._ips: Set[str] = set()
        self._expires_at: float = 0.0

    async def get(self) -> Set[str]:
        now = time.time()
        if now < self._expires_at:
            return self._ips
        try:
            cursor = db.cloudflare_ip_blocks.find(
                {"status": {"$in": list(_BLOCKED_STATUSES)}},
                {"_id": 0, "ip": 1},
            )
            docs = await cursor.to_list(5000)
            self._ips = {d["ip"] for d in docs if d.get("ip")}
            self._expires_at = now + _CACHE_TTL_SECONDS
        except Exception as e:  # noqa: BLE001
            logger.warning(f"IP blocklist cache refresh failed: {e}")
        return self._ips

    def invalidate(self) -> None:
        self._expires_at = 0.0


_cache = _BlocklistCache()


def invalidate_cache() -> None:
    """Force the next request to re-fetch the blocklist. Called by admin
    create/delete endpoints so an unblock takes effect immediately without
    waiting for the 30s TTL."""
    _cache.invalidate()


class IPBlocklistMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        ip = _client_ip(request)
        if ip and ip != "unknown":
            blocked = await _cache.get()
            if ip in blocked:
                logger.info(
                    f"[ip-blocklist] Blocked request from {ip} to "
                    f"{request.method} {request.url.path}"
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            "Tu dirección IP está bloqueada por actividad "
                            "sospechosa. Si crees que es un error, contacta a soporte."
                        ),
                        "code": "IP_BLOCKED",
                    },
                )
        return await call_next(request)


def install_ip_blocklist_middleware(app: FastAPI) -> None:
    """Attach the IP blocklist middleware. Must be called AFTER
    install_security_middleware so this runs FIRST for incoming requests."""
    app.add_middleware(IPBlocklistMiddleware)
