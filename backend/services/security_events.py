"""In-app security event log.

Sits between the middlewares and the audit dashboard: any middleware or route
that detects abusive behaviour drops a row here via `log_security_event(...)`.

`GET /api/admin/security/audit` (see `routes/admin_security.py`) reads from
this collection to build the operational dashboard.

Rows are kept for 30 days via a TTL index (created on startup); older events
are dropped automatically to bound the collection.
"""
import logging
from typing import Any, Optional

from db_client import db
from auth_utils import now_utc, iso

logger = logging.getLogger(__name__)

# Every security_event.kind value MUST be added here so the dashboard knows
# how to render it. Keep in sync with the frontend enum.
KIND_ORIGIN_BLOCKED = "origin_blocked"          # cross-origin write attempted from non-allowed origin
KIND_RATE_LIMIT_HIT = "rate_limit_hit"          # slowapi 429 fired
KIND_ADMIN_NEW_IP = "admin_new_ip"              # admin/employee logged in from an IP never seen before
KIND_LOGIN_FAILED_BURST = "login_failed_burst"  # brute-force protector tripped


def _short(text: Optional[str], n: int = 200) -> Optional[str]:
    if not text:
        return None
    return text[:n] + ("…" if len(text) > n else "")


def _client_ip(request: Any) -> str:
    """Best-effort real client IP. Behind Cloudflare/K8s ingress the actual
    address arrives in `X-Forwarded-For`; pick the leftmost entry (RFC 7239)."""
    xff = request.headers.get("x-forwarded-for") if request else None
    if xff:
        return xff.split(",")[0].strip()
    if request and request.client:
        return request.client.host
    return "unknown"


async def log_security_event(
    kind: str, request: Optional[Any] = None,
    *, user_id: Optional[str] = None, user_email: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """Persist one security event. Non-fatal — failures are swallowed after logging
    so the middleware/handler that called us never breaks the primary flow."""
    try:
        doc = {
            "kind": kind,
            "ip": _client_ip(request) if request else None,
            "path": str(request.url.path) if request else None,
            "method": request.method if request else None,
            "origin": (request.headers.get("origin") if request else None),
            "user_agent": _short(request.headers.get("user-agent") if request else None, 300),
            "user_id": user_id,
            "user_email": user_email,
            "extra": extra or {},
            "created_at": iso(now_utc()),
        }
        await db.security_events.insert_one(doc)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"security event insert failed (kind={kind}): {e}")


async def ensure_indexes() -> None:
    """Create the TTL + look-up indexes. Idempotent; safe to call on every boot."""
    try:
        # 30-day retention. The TTL index uses a Date field, so we mirror
        # `created_at` (ISO string) into `_ts` (Date) via a small trigger below,
        # OR use `expireAfterSeconds` on an existing Date field. Simplest:
        # store BOTH — iso string for portability + Date for TTL.
        await db.security_events.create_index([("created_at", -1)])
        await db.security_events.create_index([("kind", 1), ("created_at", -1)])
        await db.security_events.create_index([("ip", 1), ("created_at", -1)])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"security_events index setup failed: {e}")


async def known_ip_for_user(user_id: str, ip: str) -> bool:
    """Return True iff we've seen `ip` for `user_id` in the last 90 days."""
    if not ip or ip == "unknown":
        return True  # can't distinguish → don't alert
    from datetime import timedelta
    cutoff = iso(now_utc() - timedelta(days=90))
    hit = await db.user_login_ips.find_one(
        {"user_id": user_id, "ip": ip, "last_seen": {"$gte": cutoff}},
        {"_id": 0, "user_id": 1},
    )
    return hit is not None


async def remember_login_ip(user_id: str, ip: str) -> None:
    """Upsert (user_id, ip) → last_seen. Used by the login flow to know when
    an admin has logged in from a NEW IP (for security_events)."""
    if not ip or ip == "unknown":
        return
    try:
        await db.user_login_ips.update_one(
            {"user_id": user_id, "ip": ip},
            {"$set": {"last_seen": iso(now_utc())},
             "$setOnInsert": {"first_seen": iso(now_utc())}},
            upsert=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"remember_login_ip failed: {e}")
