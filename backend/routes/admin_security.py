"""Admin security audit dashboard.

`GET /api/admin/security/audit` — read-only aggregation over the last 7 days
covering:
  * Active user sessions (grouped by role, top-20 admins with counts)
  * Admin/employee logins from IPs never seen before (last 7 days)
  * Top-10 IPs blocked by the rate limiter (429s)
  * Latest 20 origin-allowlist violations (403s)

Consumed by the frontend `AdminSecurity.jsx` page (admin-only, employee is 403).
Intentionally NOT `can_manage_blocklist`-gated — this shows raw security posture
that even trusted employees should not see (rotate secrets, IP addresses, etc.).
"""
import logging
from datetime import timedelta
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import require_staff, now_utc, iso

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Admin"])


async def _require_admin_only(request: Request) -> dict:
    """Reject anyone who isn't role=admin (no employee-level access)."""
    user = await require_staff(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo los administradores pueden ver este panel.")
    return user


async def _count_active_sessions() -> dict:
    """Group live sessions by role + list top 20 admin/employee sessions."""
    now_iso = iso(now_utc())
    cursor = db.user_sessions.find({"expires_at": {"$gte": now_iso}}, {"_id": 0})
    sessions = await cursor.to_list(5000)
    if not sessions:
        return {"total": 0, "by_role": {}, "staff_active": []}

    # Enrich each session with user metadata (role/email). Fetch users in one round.
    user_ids = list({s["user_id"] for s in sessions})
    users = await db.users.find(
        {"user_id": {"$in": user_ids}},
        {"_id": 0, "user_id": 1, "email": 1, "name": 1, "role": 1},
    ).to_list(len(user_ids))
    user_by_id = {u["user_id"]: u for u in users}

    by_role: dict[str, int] = {}
    staff_active: list[dict] = []
    for s in sessions:
        u = user_by_id.get(s["user_id"])
        role = (u or {}).get("role", "unknown")
        by_role[role] = by_role.get(role, 0) + 1
        if role in ("admin", "employee"):
            staff_active.append({
                "user_id": s["user_id"],
                "email": (u or {}).get("email"),
                "name": (u or {}).get("name"),
                "role": role,
                "created_at": s.get("created_at"),
                "expires_at": s.get("expires_at"),
            })
    staff_active.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {
        "total": len(sessions),
        "by_role": by_role,
        "staff_active": staff_active[:20],
    }


async def _admin_new_ip_logins(days: int = 7) -> List[dict]:
    from services.security_events import KIND_ADMIN_NEW_IP
    cutoff = iso(now_utc() - timedelta(days=days))
    cursor = db.security_events.find(
        {"kind": KIND_ADMIN_NEW_IP, "created_at": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("created_at", -1).limit(50)
    return await cursor.to_list(50)


async def _top_rate_limited_ips(days: int = 7, limit: int = 10) -> List[dict]:
    from services.security_events import KIND_RATE_LIMIT_HIT
    cutoff = iso(now_utc() - timedelta(days=days))
    pipeline = [
        {"$match": {"kind": KIND_RATE_LIMIT_HIT, "created_at": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$ip",
            "hits": {"$sum": 1},
            "last_seen": {"$max": "$created_at"},
            "paths": {"$addToSet": "$path"},
        }},
        {"$sort": {"hits": -1}},
        {"$limit": limit},
    ]
    rows = await db.security_events.aggregate(pipeline).to_list(limit)
    return [
        {
            "ip": r["_id"] or "unknown",
            "hits": r["hits"],
            "last_seen": r["last_seen"],
            "top_paths": (r.get("paths") or [])[:5],
        }
        for r in rows
    ]


async def _recent_origin_violations(days: int = 7, limit: int = 20) -> List[dict]:
    from services.security_events import KIND_ORIGIN_BLOCKED
    cutoff = iso(now_utc() - timedelta(days=days))
    cursor = db.security_events.find(
        {"kind": KIND_ORIGIN_BLOCKED, "created_at": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("created_at", -1).limit(limit)
    return await cursor.to_list(limit)


async def _recent_login_bursts(days: int = 7, limit: int = 10) -> List[dict]:
    """Failed-login burst events (from the anti-scam brute-force protector)."""
    cutoff = iso(now_utc() - timedelta(days=days))
    cursor = db.login_attempts.find(
        {"success": False, "created_at": {"$gte": cutoff}},
        {"_id": 0, "identifier": 1, "created_at": 1, "success": 1},
    ).sort("created_at", -1).limit(200)
    rows = await cursor.to_list(200)
    # Group by identifier + count
    counts: dict[str, int] = {}
    last_seen: dict[str, str] = {}
    for r in rows:
        k = r.get("identifier") or "unknown"
        counts[k] = counts.get(k, 0) + 1
        if k not in last_seen:
            last_seen[k] = r.get("created_at", "")
    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [
        {"identifier": ident, "failed_attempts": n, "last_seen": last_seen[ident]}
        for ident, n in top
    ]


@router.get("/admin/security/audit")
async def security_audit(request: Request) -> Any:
    """Aggregate 4 signals into a single dashboard payload.
    Admin-only endpoint.
    """
    await _require_admin_only(request)

    active_sessions = await _count_active_sessions()
    new_ip_logins = await _admin_new_ip_logins()
    top_rate_limited = await _top_rate_limited_ips()
    origin_violations = await _recent_origin_violations()
    login_bursts = await _recent_login_bursts()

    return {
        "generated_at": iso(now_utc()),
        "window_days": 7,
        "active_sessions": active_sessions,
        "admin_new_ip_logins": new_ip_logins,
        "top_rate_limited_ips": top_rate_limited,
        "recent_origin_violations": origin_violations,
        "recent_login_bursts": login_bursts,
    }


@router.post("/admin/security/sessions/{user_id}/revoke")
async def revoke_user_sessions(user_id: str, request: Request) -> Any:
    """Kill every active session for `user_id`. Emergency knob when a staff
    account is suspected of being compromised."""
    await _require_admin_only(request)
    r = await db.user_sessions.delete_many({"user_id": user_id})
    logger.warning(f"[security] Revoked {r.deleted_count} sessions for user {user_id}")
    return {"ok": True, "revoked": r.deleted_count}


# ============================================================
# iter50 — Cloudflare WAF IP block management (admin-only)
# ============================================================

class _CloudflareBlockPayload(BaseModel):  # type: ignore[misc]
    ip: str = Field(..., min_length=3, max_length=45)
    notes: str = Field("", max_length=500)


@router.get("/admin/security/cloudflare/blocks")
async def cloudflare_blocks_list(
    request: Request, status: Optional[str] = None,
) -> Any:
    """List every IP block record. `status` filter accepts:
    active | pending_create | pending_delete | deleted | failed."""
    await _require_admin_only(request)
    from services import cloudflare_blocks, cloudflare_client
    items = await cloudflare_blocks.list_blocks(db, status=status)
    return {
        "items": items,
        "configured": cloudflare_client._is_configured(),
        "auto_block_enabled": cloudflare_client.is_auto_block_enabled(),
    }


@router.post("/admin/security/cloudflare/blocks")
async def cloudflare_block_ip(payload: _CloudflareBlockPayload, request: Request) -> Any:
    """Manually block an IP at Cloudflare WAF (source='admin')."""
    admin = await _require_admin_only(request)
    from services import cloudflare_blocks
    from middleware.ip_blocklist import invalidate_cache
    notes = payload.notes.strip() or f"manual: admin_id={admin['user_id']}"
    if "manual:" not in notes:
        notes = f"manual: {notes} (admin_id={admin['user_id']})"
    res = await cloudflare_blocks.create_block(
        db, payload.ip.strip(), notes,
        source="admin",
        user_id=admin["user_id"], user_email=admin.get("email"),
    )
    # Force app-level middleware to re-read the blocklist immediately.
    invalidate_cache()
    return res


@router.delete("/admin/security/cloudflare/blocks/{block_id}")
async def cloudflare_unblock_ip(block_id: str, request: Request) -> Any:
    """Manual unblock. Local record moves to `deleted` even if Cloudflare
    delete fails so the admin UI stays consistent."""
    await _require_admin_only(request)
    from services import cloudflare_blocks
    from middleware.ip_blocklist import invalidate_cache
    res = await cloudflare_blocks.delete_block(db, block_id)
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail=res.get("error", "not_found"))
    # Invalidate cache so the unblock takes effect immediately (no 30s wait).
    invalidate_cache()
    return res
