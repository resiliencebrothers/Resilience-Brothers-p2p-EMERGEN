"""iter109 — VIP status request flow.

Product ask (25 Jul 2026): allow newly registered `normal` clients to
formally request being upgraded to VIP. Approval by an admin (or staff
with `vip_requests` permission) auto-upgrades the user's role.

Data model — one collection: `vip_requests`
    {
      id, user_id, user_email, user_name,
      message,                       # motivo (20-500 chars)
      estimated_monthly_volume_usd,  # >0, <=10M
      preferred_payment_method,      # crypto | bank_transfer | cash | other
      status: pending | approved | rejected,
      created_at, updated_at,
      # admin decisions
      reviewed_by, reviewed_at, admin_note (optional, max 500)
    }

Endpoints:
    POST /api/vip/requests                             (normal → pending)
    GET  /api/vip/requests/me                          (client polls state)
    GET  /api/admin/vip-requests                       (staff w/ vip_requests perm)
    GET  /api/admin/vip-requests/pending-count         (badge)
    POST /api/admin/vip-requests/{id}/approve          → user.role="vip" + notif
    POST /api/admin/vip-requests/{id}/reject           (with admin_note)

Rules (iter109):
  - Only role="normal" may POST /vip/requests.
  - One `pending` request per user at a time (409 otherwise).
  - After rejection → 7-day cooldown before user can submit again.
  - On approve: user.role becomes "vip". Notification to client (in-app +
    push + SSE). Audit-logged.
  - On reject: notification to client with admin_note. No role change.
  - On submit: notification to every staff with `vip_requests` permission.
"""
from __future__ import annotations

import uuid
import logging
from typing import Any, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import require_user, require_permission, iso, now_utc
from audit_log import log_action

logger = logging.getLogger("vip_requests")

router = APIRouter(tags=["VIP Requests"])

REJECTION_COOLDOWN_DAYS = 7
ALLOWED_PAYMENT_METHODS = {"crypto", "bank_transfer", "cash", "other"}


# ============================================================
# Payloads
# ============================================================

class VipRequestCreate(BaseModel):
    """Client submission."""
    model_config = ConfigDict(extra="ignore")
    message: str = Field(..., min_length=20, max_length=500)
    estimated_monthly_volume_usd: float = Field(..., gt=0, le=10_000_000)
    preferred_payment_method: str = Field(..., min_length=2, max_length=32)


class VipRequestReject(BaseModel):
    model_config = ConfigDict(extra="ignore")
    admin_note: str = Field(default="", max_length=500)


# ============================================================
# Helpers
# ============================================================

def _serialize(doc: dict) -> dict:
    d = dict(doc)
    d.pop("_id", None)
    return d


def _cooldown_remaining(rejected_at_iso: str) -> int:
    """Return remaining cooldown days after a rejection, 0 if elapsed."""
    try:
        rejected_at = datetime.fromisoformat(rejected_at_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 0
    elapsed = (datetime.now(timezone.utc) - rejected_at).days
    return max(0, REJECTION_COOLDOWN_DAYS - elapsed)


async def _notify_staff_new_request(req: dict) -> None:
    """In-app + push to every staff member with `vip_requests` permission."""
    try:
        from routes.notifications import _insert_notification
        from push_service import send_push_to_user
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_requests] notify import failed: {e}")
        return
    cursor = db.users.find(
        {"$or": [
            {"role": "admin"},
            {"role": "employee", "allowed_permissions": "vip_requests"},
            {"role": "employee", "allowed_permissions": {"$in": [[], None]}},
        ]},
        {"_id": 0, "user_id": 1},
    )
    recipients = [r async for r in cursor]
    name = req.get("user_name") or req.get("user_email") or "Cliente"
    volume = req.get("estimated_monthly_volume_usd", 0)
    for r in recipients:
        uid = r["user_id"]
        try:
            await _insert_notification(
                recipient_user_id=uid,
                type="new_vip_request",
                title="Nueva solicitud VIP",
                message=f"{name} solicita ser VIP (volumen: ${volume:,.0f}/mes).",
                data={"request_id": req["id"], "user_id": req["user_id"]},
            )
            await send_push_to_user(db, uid, {
                "title": "Nueva solicitud VIP",
                "body": f"{name} — ${volume:,.0f}/mes",
                "icon": "/icons/icon-192.png",
                "tag": f"vip-req-{req['id']}",
                "url": "/admin/users?tab=vip-requests",
            })
        except Exception as e:  # noqa: BLE001
            logger.error(f"[vip_requests] staff notify {uid} failed: {e}")


async def _notify_client_decision(req: dict, approved: bool, admin_note: str = "") -> None:
    """Notify the requesting client about approval / rejection."""
    try:
        from routes.notifications import _insert_notification
        from push_service import send_push_to_user
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_requests] notify import failed: {e}")
        return
    uid = req["user_id"]
    if approved:
        title = "¡Solicitud VIP aprobada!"
        message = "Tu cuenta ya está marcada como VIP. Refresca la app para ver los nuevos accesos."
    else:
        title = "Solicitud VIP rechazada"
        message = admin_note or "Tu solicitud fue rechazada. Podrás volver a solicitarla en 7 días."
    try:
        await _insert_notification(
            recipient_user_id=uid,
            type="vip_request_approved" if approved else "vip_request_rejected",
            title=title,
            message=message,
            data={"request_id": req["id"]},
        )
        await send_push_to_user(db, uid, {
            "title": title,
            "body": message[:140],
            "icon": "/icons/icon-192.png",
            "tag": f"vip-decision-{req['id']}",
            "url": "/dashboard/profile",
        })
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_requests] client notify {uid} failed: {e}")


# ============================================================
# Client endpoints
# ============================================================

@router.post("/vip/requests")
async def create_vip_request(payload: VipRequestCreate, request: Request) -> Any:
    """A `normal` client submits a request to be upgraded to VIP. Rejected
    with 403 for other roles, 409 if one is already pending, and 429 if the
    user was rejected less than 7 days ago."""
    user = await require_user(request)
    if user.get("role") != "normal":
        raise HTTPException(
            status_code=403,
            detail="Solo los clientes con rol Normal pueden solicitar VIP.",
        )
    method = payload.preferred_payment_method.strip().lower()
    if method not in ALLOWED_PAYMENT_METHODS:
        raise HTTPException(
            status_code=422,
            detail=f"Método de pago inválido. Usa uno de: {sorted(ALLOWED_PAYMENT_METHODS)}",
        )

    # Guard: one pending at a time.
    existing = await db.vip_requests.find_one(
        {"user_id": user["user_id"], "status": "pending"},
        {"_id": 0},
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Ya tienes una solicitud VIP en revisión.",
        )

    # Guard: 7-day cooldown after last rejection.
    last_rejected = await db.vip_requests.find_one(
        {"user_id": user["user_id"], "status": "rejected"},
        {"_id": 0, "reviewed_at": 1},
        sort=[("reviewed_at", -1)],
    )
    if last_rejected and last_rejected.get("reviewed_at"):
        remaining = _cooldown_remaining(last_rejected["reviewed_at"])
        if remaining > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Debes esperar {remaining} día(s) antes de volver a solicitar VIP.",
            )

    doc = {
        "id": f"vipreq_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "user_email": user.get("email", ""),
        "user_name": user.get("name", ""),
        "message": payload.message.strip(),
        "estimated_monthly_volume_usd": round(float(payload.estimated_monthly_volume_usd), 2),
        "preferred_payment_method": method,
        "status": "pending",
        "created_at": iso(now_utc()),
        "updated_at": iso(now_utc()),
        "reviewed_by": None,
        "reviewed_at": None,
        "admin_note": None,
    }
    await db.vip_requests.insert_one(doc)
    await log_action(
        db=db, actor=user, action="vip_request.create",
        entity_type="vip_request", entity_id=doc["id"],
        details={"volume": doc["estimated_monthly_volume_usd"], "method": method},
    )
    await _notify_staff_new_request(doc)
    return _serialize(doc)


@router.get("/vip/requests/me")
async def get_my_vip_request(request: Request) -> Any:
    """Returns the client's latest VIP request (any status) so the profile
    card can show current state + cooldown info. Returns 200 with `null`
    fields if the user never requested."""
    user = await require_user(request)
    # Only relevant for clients — return an empty envelope for staff.
    doc = await db.vip_requests.find_one(
        {"user_id": user["user_id"]},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    cooldown_days_left = 0
    if doc and doc.get("status") == "rejected" and doc.get("reviewed_at"):
        cooldown_days_left = _cooldown_remaining(doc["reviewed_at"])
    return {
        "request": _serialize(doc) if doc else None,
        "cooldown_days_left": cooldown_days_left,
        "can_submit": (
            user.get("role") == "normal"
            and (not doc or doc.get("status") != "pending")
            and cooldown_days_left == 0
        ),
    }


# ============================================================
# Admin endpoints
# ============================================================

@router.get("/admin/vip-requests/pending-count")
async def admin_vip_requests_pending_count(request: Request) -> Any:
    """Lightweight count for the sidebar badge (mirrors iter107.1's
    /admin/support/unread-count pattern)."""
    await require_permission(request, "vip_requests")
    pending = await db.vip_requests.count_documents({"status": "pending"})
    return {"pending": pending}


@router.get("/admin/vip-requests")
async def admin_list_vip_requests(
    request: Request,
    status: Optional[str] = None,
    limit: int = 200,
) -> Any:
    await require_permission(request, "vip_requests")
    q: dict[str, Any] = {}
    if status and status in ("pending", "approved", "rejected"):
        q["status"] = status
    cursor = db.vip_requests.find(q, {"_id": 0}).sort("created_at", -1).limit(min(max(1, limit), 500))
    items = [_serialize(d) async for d in cursor]
    pending = await db.vip_requests.count_documents({"status": "pending"})
    return {"items": items, "pending": pending}


@router.post("/admin/vip-requests/{req_id}/approve")
async def admin_approve_vip_request(req_id: str, request: Request) -> Any:
    """Approve a pending request → user.role becomes 'vip' + notify."""
    staff = await require_permission(request, "vip_requests")
    doc = await db.vip_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Solicitud VIP no encontrada.")
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail="La solicitud ya fue procesada.")

    # Guard: don't clobber admins/employees.
    target = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0, "role": 1})
    if not target:
        raise HTTPException(status_code=404, detail="El usuario ya no existe.")
    if target.get("role") not in ("normal", "vip"):
        raise HTTPException(
            status_code=409,
            detail=f"No se puede promover a un usuario con rol '{target.get('role')}'.",
        )

    now = iso(now_utc())
    await db.vip_requests.update_one(
        {"id": req_id},
        {"$set": {
            "status": "approved",
            "updated_at": now,
            "reviewed_at": now,
            "reviewed_by": staff["user_id"],
            "admin_note": None,
        }},
    )
    await db.users.update_one(
        {"user_id": doc["user_id"]},
        {"$set": {"role": "vip", "updated_at": now}},
    )
    fresh = await db.vip_requests.find_one({"id": req_id}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="vip_request.approve",
        entity_type="vip_request", entity_id=req_id,
        details={"target_user": doc["user_id"]},
    )
    await _notify_client_decision(fresh, approved=True)
    return _serialize(fresh)


@router.post("/admin/vip-requests/{req_id}/reject")
async def admin_reject_vip_request(req_id: str, payload: VipRequestReject, request: Request) -> Any:
    staff = await require_permission(request, "vip_requests")
    doc = await db.vip_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Solicitud VIP no encontrada.")
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail="La solicitud ya fue procesada.")

    now = iso(now_utc())
    note = (payload.admin_note or "").strip() or None
    await db.vip_requests.update_one(
        {"id": req_id},
        {"$set": {
            "status": "rejected",
            "updated_at": now,
            "reviewed_at": now,
            "reviewed_by": staff["user_id"],
            "admin_note": note,
        }},
    )
    fresh = await db.vip_requests.find_one({"id": req_id}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="vip_request.reject",
        entity_type="vip_request", entity_id=req_id,
        details={"target_user": doc["user_id"], "note": note},
    )
    await _notify_client_decision(fresh, approved=False, admin_note=note or "")
    return _serialize(fresh)
