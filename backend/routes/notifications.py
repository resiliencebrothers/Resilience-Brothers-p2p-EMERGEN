"""In-app notifications — iter29.

Two audiences:
 - Staff (admin + employees with can_manage_blocklist): notified when a new user
   completes registration with a phone and lands in 'under_review'. They take action
   from Admin → Users → ✓ Verificar / ✕ Rechazar.
 - Clients: notified when staff verifies (account activated) or rejects (account
   stays under_review) their phone.

Schema (collection `notifications`):
  {
    id: uuid hex,
    recipient_user_id: str,     # owner of the inbox
    type: "new_user_pending" | "phone_verified" | "phone_rejected" | "info",
    title: str,
    message: str,
    data: dict,                  # extra payload (target_user_id, phone, reason...)
    read: bool,
    created_at: ISO datetime,
    read_at: ISO datetime | None,
  }
"""
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Request

from db_client import db
from auth_utils import require_user, now_utc, iso


logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# Helpers — call these from anywhere in the app
# ============================================================

async def _insert_notification(*, recipient_user_id: str, type: str, title: str,
                                 message: str, data: Optional[dict] = None) -> str:
    doc = {
        "id": uuid.uuid4().hex,
        "recipient_user_id": recipient_user_id,
        "type": type,
        "title": title,
        "message": message,
        "data": data or {},
        "read": False,
        "created_at": iso(now_utc()),
        "read_at": None,
    }
    await db.notifications.insert_one(doc)
    return doc["id"]


async def notify_staff_new_pending_user(target_user: dict):
    """Fan-out a notification to every admin and every employee with
    can_manage_blocklist=True, so they see a new user is waiting for verification."""
    recipients_cursor = db.users.find(
        {"$or": [
            {"role": "admin"},
            {"role": "employee", "can_manage_blocklist": True},
        ]},
        {"_id": 0, "user_id": 1},
    )
    recipients = [r["user_id"] async for r in recipients_cursor]
    title = "Nuevo usuario pendiente de verificación"
    name = target_user.get("name") or target_user.get("email") or "Usuario"
    phone = target_user.get("phone") or "-"
    email = target_user.get("email") or "-"
    message = f"{name} ({email}) acaba de registrarse con el teléfono {phone}. Verifica o rechaza desde Admin → Usuarios."
    data = {
        "target_user_id": target_user["user_id"],
        "email": target_user.get("email"),
        "phone": target_user.get("phone"),
        "name": target_user.get("name"),
    }
    for uid in recipients:
        try:
            await _insert_notification(
                recipient_user_id=uid, type="new_user_pending",
                title=title, message=message, data=data,
            )
        except Exception as e:
            logger.error(f"Failed to insert pending-user notification for {uid}: {e}")


async def notify_user_phone_verified(target_user: dict):
    """Tell the user their phone has been verified and the account is now active."""
    await _insert_notification(
        recipient_user_id=target_user["user_id"],
        type="phone_verified",
        title="¡Tu cuenta está activa!",
        message="Hemos verificado tu teléfono. Ya puedes operar en la plataforma: hacer intercambios, retiros y canjes.",
        data={"phone": target_user.get("phone")},
    )


async def notify_user_phone_rejected(target_user: dict, reason: str):
    """Tell the user their phone was rejected and the account remains under review."""
    await _insert_notification(
        recipient_user_id=target_user["user_id"],
        type="phone_rejected",
        title="Verificación rechazada",
        message=f"No pudimos verificar tu teléfono. Motivo: {reason}. Si crees que es un error, contacta a soporte por WhatsApp para apelar.",
        data={"phone": target_user.get("phone"), "reason": reason},
    )


# ============================================================
# Endpoints
# ============================================================

@router.get("/notifications")
async def list_my_notifications(request: Request, limit: int = 30,
                                  only_unread: bool = False):
    user = await require_user(request)
    query = {"recipient_user_id": user["user_id"]}
    if only_unread:
        query["read"] = False
    cursor = db.notifications.find(query, {"_id": 0}).sort("created_at", -1).limit(min(max(limit, 1), 100))
    items = await cursor.to_list(length=limit)
    return {"items": items}


@router.get("/notifications/unread-count")
async def my_unread_count(request: Request):
    user = await require_user(request)
    n = await db.notifications.count_documents(
        {"recipient_user_id": user["user_id"], "read": False}
    )
    return {"count": n}


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, request: Request):
    user = await require_user(request)
    r = await db.notifications.update_one(
        {"id": notification_id, "recipient_user_id": user["user_id"], "read": False},
        {"$set": {"read": True, "read_at": iso(now_utc())}},
    )
    if r.matched_count == 0:
        # Already read or doesn't belong to user — return 200 either way for idempotency
        return {"ok": True, "already_read": True}
    return {"ok": True}


@router.post("/notifications/mark-all-read")
async def mark_all_read(request: Request):
    user = await require_user(request)
    r = await db.notifications.update_many(
        {"recipient_user_id": user["user_id"], "read": False},
        {"$set": {"read": True, "read_at": iso(now_utc())}},
    )
    return {"ok": True, "marked": r.modified_count}
