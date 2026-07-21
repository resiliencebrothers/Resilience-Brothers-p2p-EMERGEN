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
from typing import Optional, Any

from fastapi import APIRouter, Request

from db_client import db
from auth_utils import require_user, now_utc, iso
from push_service import (
    send_push_to_user,
    build_new_pending_user_payload,
    build_phone_verified_payload,
    build_phone_rejected_payload,
)
from services.notification_i18n import t as _t, resolve_lang


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Notifications"])


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


async def notify_staff_new_pending_user(target_user: dict) -> Any:
    """Fan-out a notification to every admin and every employee with
    can_manage_blocklist=True, so they see a new user is waiting for verification.
    Also delivers a Web Push notification to each recipient's registered devices."""
    recipients_cursor = db.users.find(
        {"$or": [
            {"role": "admin"},
            {"role": "employee", "can_manage_blocklist": True},
        ]},
        {"_id": 0, "user_id": 1, "preferred_language": 1},
    )
    recipients = [r async for r in recipients_cursor]
    name = target_user.get("name") or target_user.get("email") or "Usuario"
    phone = target_user.get("phone") or "-"
    email = target_user.get("email") or "-"
    data = {
        "target_user_id": target_user["user_id"],
        "email": target_user.get("email"),
        "phone": target_user.get("phone"),
        "name": target_user.get("name"),
    }
    for r in recipients:
        uid = r["user_id"]
        lang = r.get("preferred_language")
        try:
            await _insert_notification(
                recipient_user_id=uid, type="new_user_pending",
                title=_t("new_user_pending", lang, "title"),
                message=_t("new_user_pending", lang, "message", name=name, email=email, phone=phone),
                data=data,
            )
            await send_push_to_user(db, uid, build_new_pending_user_payload(target_user, lang=lang))
        except Exception as e:
            logger.error(f"Failed to deliver pending-user notification to {uid}: {e}")


async def notify_user_phone_verified(target_user: dict) -> Any:
    """Tell the user their phone has been verified and the account is now active."""
    lang = target_user.get("preferred_language") or await resolve_lang(db, target_user["user_id"])
    await _insert_notification(
        recipient_user_id=target_user["user_id"],
        type="phone_verified",
        title=_t("phone_verified", lang, "title"),
        message=_t("phone_verified", lang, "message"),
        data={"phone": target_user.get("phone")},
    )
    await send_push_to_user(db, target_user["user_id"], build_phone_verified_payload(target_user, lang=lang))


async def notify_user_phone_rejected(target_user: dict, reason: str) -> Any:
    """Tell the user their phone was rejected and the account remains under review."""
    lang = target_user.get("preferred_language") or await resolve_lang(db, target_user["user_id"])
    await _insert_notification(
        recipient_user_id=target_user["user_id"],
        type="phone_rejected",
        title=_t("phone_rejected", lang, "title"),
        message=_t("phone_rejected", lang, "message", reason=reason),
        data={"phone": target_user.get("phone"), "reason": reason},
    )
    await send_push_to_user(
        db, target_user["user_id"],
        build_phone_rejected_payload(target_user, reason, lang=lang),
    )


async def notify_staff_new_appeal(appeal: dict) -> Any:
    """Fan out an in-app notification (and Web Push) to every admin and every
    employee with `can_manage_blocklist=True` when a client submits a new
    self-service appeal from the under-review banner."""
    recipients_cursor = db.users.find(
        {"$or": [
            {"role": "admin"},
            {"role": "employee", "can_manage_blocklist": True},
        ]},
        {"_id": 0, "user_id": 1, "preferred_language": 1},
    )
    recipients = [r async for r in recipients_cursor]
    name = appeal.get("user_name") or appeal.get("user_email") or "Usuario"
    email = appeal.get("user_email") or "-"
    preview = (appeal.get("message") or "")[:120]
    data = {
        "appeal_id": appeal["id"],
        "target_user_id": appeal["user_id"],
        "user_email": appeal.get("user_email"),
        "preview": preview,
    }
    for r in recipients:
        uid = r["user_id"]
        lang = r.get("preferred_language")
        title = _t("new_appeal", lang, "title")
        message = _t("new_appeal", lang, "message", name=name, email=email)
        push_payload = {
            "title": title,
            "body": f"{name}: {preview}",
            "icon": "/icons/icon-192.png",
            "badge": "/icons/icon-192.png",
            "tag": f"appeal-{appeal['id']}",
            "url": "/admin/appeals",
        }
        try:
            await _insert_notification(
                recipient_user_id=uid, type="new_appeal",
                title=title, message=message, data=data,
            )
            await send_push_to_user(db, uid, push_payload)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to deliver new-appeal notification to {uid}: {e}")


async def notify_user_appeal_reviewed(appeal: dict) -> Any:
    """Tell the client that staff processed their appeal (either resolved or
    rejected) and surface the staff response verbatim."""
    status = appeal.get("status", "resolved")
    response = appeal.get("staff_response") or ""
    lang = await resolve_lang(db, appeal["user_id"])
    key = "appeal_resolved" if status == "resolved" else "appeal_rejected"
    title = _t(key, lang, "title")
    message = _t(key, lang, "message", response=response)
    await _insert_notification(
        recipient_user_id=appeal["user_id"],
        type=f"appeal_{status}",
        title=title, message=message,
        data={"appeal_id": appeal["id"], "staff_response": response},
    )
    push_payload = {
        "title": title,
        "body": response[:120] if response else message[:120],
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"appeal-review-{appeal['id']}",
        "url": "/dashboard",
    }
    try:
        await send_push_to_user(db, appeal["user_id"], push_payload)
    except Exception as e:  # noqa: BLE001
        logger.error(f"appeal-review push failed for {appeal['user_id']}: {e}")


# ============================================================
# Endpoints
# ============================================================

@router.get("/notifications")
async def list_my_notifications(request: Request, limit: int = 30,
                                  only_unread: bool = False) -> Any:
    user = await require_user(request)
    query = {"recipient_user_id": user["user_id"]}
    if only_unread:
        query["read"] = False
    cursor = db.notifications.find(query, {"_id": 0}).sort("created_at", -1).limit(min(max(limit, 1), 100))
    items = await cursor.to_list(length=limit)
    return {"items": items}


@router.get("/notifications/unread-count")
async def my_unread_count(request: Request) -> Any:
    user = await require_user(request)
    n = await db.notifications.count_documents(
        {"recipient_user_id": user["user_id"], "read": False}
    )
    return {"count": n}


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, request: Request) -> Any:
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
async def mark_all_read(request: Request) -> Any:
    user = await require_user(request)
    r = await db.notifications.update_many(
        {"recipient_user_id": user["user_id"], "read": False},
        {"$set": {"read": True, "read_at": iso(now_utc())}},
    )
    return {"ok": True, "marked": r.modified_count}


# ============================================================
# iter55.18 — Delete notifications (individual + bulk read cleanup)
# ============================================================

@router.delete("/notifications/read")
async def delete_all_read_notifications(request: Request) -> Any:
    """Bulk-delete every read notification for the current user. Useful to
    empty the inbox after a triage session. Unread items are preserved."""
    user = await require_user(request)
    r = await db.notifications.delete_many(
        {"recipient_user_id": user["user_id"], "read": True},
    )
    return {"ok": True, "deleted": r.deleted_count}


@router.delete("/notifications/{notification_id}")
async def delete_notification(notification_id: str, request: Request) -> Any:
    """Delete a single notification. Owner-scoped: users can only delete their
    own inbox items. Idempotent — deleting an already-gone id returns 200."""
    user = await require_user(request)
    r = await db.notifications.delete_one(
        {"id": notification_id, "recipient_user_id": user["user_id"]},
    )
    if r.deleted_count == 0:
        return {"ok": True, "already_gone": True}
    return {"ok": True}




# ============================================================
# iter52 — KYC verification notifications (client-inbound)
# ============================================================

async def notify_user_kyc_verified(_db: Any, user_id: str) -> Any:
    """Client identity was approved — they can operate at full capacity."""
    resolver_db = _db if _db is not None else db
    lang = await resolve_lang(resolver_db, user_id)
    await _insert_notification(
        recipient_user_id=user_id,
        type="kyc_verified",
        title=_t("kyc_verified", lang, "title"),
        message=_t("kyc_verified", lang, "message"),
        data={},
    )


async def notify_user_kyc_rejected(_db: Any, user_id: str, reasons: list, notes: str) -> Any:
    """KYC was rejected — user can resubmit new documents."""
    resolver_db = _db if _db is not None else db
    lang = await resolve_lang(resolver_db, user_id)
    # Pull the locale-appropriate default reason + tail prefix from the
    # catalogue so we render a fully localised sentence.
    from services.notification_i18n import get_field
    reason_txt = " · ".join(reasons) if reasons else get_field("kyc_rejected", lang, "reason_default")
    tail = f"{get_field('kyc_rejected', lang, 'tail_prefix')}{notes}" if notes else ""
    await _insert_notification(
        recipient_user_id=user_id,
        type="kyc_rejected",
        title=_t("kyc_rejected", lang, "title"),
        message=_t("kyc_rejected", lang, "message", reason_txt=reason_txt, tail=tail),
        data={"reasons": reasons, "notes": notes},
    )


async def notify_user_kyc_needs_more_info(_db: Any, user_id: str, notes: str) -> Any:
    """Reviewer needs a clearer photo / different document — user can resubmit."""
    resolver_db = _db if _db is not None else db
    lang = await resolve_lang(resolver_db, user_id)
    await _insert_notification(
        recipient_user_id=user_id,
        type="kyc_needs_more_info",
        title=_t("kyc_needs_more_info", lang, "title"),
        message=_t("kyc_needs_more_info", lang, "message", notes=notes),
        data={"notes": notes},
    )
