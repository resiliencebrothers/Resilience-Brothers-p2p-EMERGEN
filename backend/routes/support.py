"""iter102 — Client-facing Support tickets + editable FAQ.

Two audiences share this router:
 - CLIENTS post tickets from `/dashboard/support`, view their own thread history,
   and reply to staff messages. Rate-limited so we don't get spammed.
 - STAFF (`support` permission) view every open ticket, reply, and close threads
   from `/admin/support`. Notifications fan out to admins on new client tickets
   and to the client when staff replies.

FAQ is a simple CRUD collection admins can edit from `/admin/support` without a
redeploy. Public read for logged-in clients; admin write.

Schema — `support_tickets` collection (thread-per-ticket):
    id: uuid hex
    user_id: str                    # owner (client)
    user_name / user_email: str     # snapshot for staff listing
    category: "general|kyc|convert|withdrawal|fees|other"
    subject: str (max 120 chars)
    status: "open|answered|closed"
    unread_by_staff: bool           # true after client sends, false after staff opens
    unread_by_client: bool          # true after staff sends, false after client opens
    messages: [{ id, author_role, author_user_id, author_name, text,
                 images: [str], created_at: ISO }]
    created_at / updated_at: ISO
    closed_at: ISO | None
    closed_by: user_id | None

Schema — `faq_entries` collection:
    id: uuid hex
    category: same enum as tickets
    question_es / question_en: str
    answer_es / answer_en: str
    order: int                      # display order (lower first)
    is_active: bool
    created_at / updated_at: ISO
"""
from typing import Optional, List, Any
from datetime import datetime, timezone, timedelta
import uuid
import logging
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from db_client import db
from auth_utils import require_user, require_permission, now_utc, iso
from services.proof_upload import maybe_upload_proof

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Support"])


VALID_CATEGORIES = {"general", "kyc", "convert", "withdrawal", "fees", "other"}
VALID_STATUSES = {"open", "answered", "closed"}

MAX_MESSAGE_LEN = 4000
MAX_SUBJECT_LEN = 120
MAX_IMAGES_PER_MESSAGE = 3
RATE_LIMIT_TICKETS_PER_HOUR = 5


# ============================================================
# Pydantic payloads
# ============================================================

class NewTicketPayload(BaseModel):
    category: str
    subject: str = Field(..., min_length=3, max_length=MAX_SUBJECT_LEN)
    message: str = Field(..., min_length=5, max_length=MAX_MESSAGE_LEN)
    images: List[str] = Field(default_factory=list)  # base64 or existing keys

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(VALID_CATEGORIES)}")
        return v

    @field_validator("images")
    @classmethod
    def _limit_images(cls, v: List[str]) -> List[str]:
        if len(v) > MAX_IMAGES_PER_MESSAGE:
            raise ValueError(f"max {MAX_IMAGES_PER_MESSAGE} images per message")
        return v


class ReplyPayload(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LEN)
    images: List[str] = Field(default_factory=list)

    @field_validator("images")
    @classmethod
    def _limit_images(cls, v: List[str]) -> List[str]:
        if len(v) > MAX_IMAGES_PER_MESSAGE:
            raise ValueError(f"max {MAX_IMAGES_PER_MESSAGE} images per message")
        return v


class FaqEntryPayload(BaseModel):
    category: str
    question_es: str = Field(..., min_length=3, max_length=200)
    question_en: str = Field(..., min_length=3, max_length=200)
    answer_es: str = Field(..., min_length=3, max_length=2000)
    answer_en: str = Field(..., min_length=3, max_length=2000)
    order: int = 0
    is_active: bool = True

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(VALID_CATEGORIES)}")
        return v


# ============================================================
# Helpers
# ============================================================

def _upload_message_images(images: List[str]) -> List[str]:
    """Push every base64 image through the R2 storage pipeline. Returns the
    list of final references (either `/api/files/...` keys or bare base64
    when storage is disabled). Skips empty strings."""
    out: List[str] = []
    for i, img in enumerate(images):
        if not img:
            continue
        try:
            ref = maybe_upload_proof(img, folder=f"support/{datetime.now(timezone.utc):%Y/%m/%d}")
            if ref:
                out.append(ref)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"[support] image {i} upload failed: {e}")
    return out


def _sanitize_subject(s: str) -> str:
    """Strip control chars + collapse whitespace so the admin list stays legible."""
    return re.sub(r"\s+", " ", s.strip())[:MAX_SUBJECT_LEN]


async def _rate_limit_check(user_id: str) -> None:
    """Raise 429 if the caller opened too many tickets in the last hour."""
    since = (now_utc() - timedelta(hours=1)).isoformat()
    count = await db.support_tickets.count_documents(
        {"user_id": user_id, "created_at": {"$gte": since}}
    )
    if count >= RATE_LIMIT_TICKETS_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail=(f"Has abierto {count} tickets en la última hora. "
                    "Espera un momento antes de crear otro (máximo "
                    f"{RATE_LIMIT_TICKETS_PER_HOUR}/hora)."),
        )


def _new_message(author_role: str, user: dict, text: str, images: List[str]) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "author_role": author_role,
        "author_user_id": user.get("user_id") or user.get("id"),
        "author_name": user.get("name") or user.get("email") or "—",
        "text": text.strip(),
        "images": images,
        "created_at": iso(now_utc()),
    }


async def _notify_staff_new_ticket(ticket: dict) -> None:
    """iter102 — Web push + in-app notification to every admin/employee with
    `support` permission when a client posts a new ticket."""
    try:
        from routes.notifications import _insert_notification
        from push_service import send_push_to_user
    except Exception as e:  # noqa: BLE001
        logger.error(f"[support] notify import failed: {e}")
        return
    cursor = db.users.find(
        {"$or": [
            {"role": "admin"},
            {"role": "employee", "allowed_permissions": "support"},
            {"role": "employee", "allowed_permissions": {"$in": [[], None]}},
        ]},
        {"_id": 0, "user_id": 1, "preferred_language": 1},
    )
    recipients = [r async for r in cursor]
    name = ticket.get("user_name") or ticket.get("user_email") or "Cliente"
    subject = ticket.get("subject", "")
    for r in recipients:
        uid = r["user_id"]
        try:
            await _insert_notification(
                recipient_user_id=uid,
                type="new_support_ticket",
                title="Nuevo ticket de soporte",
                message=f"{name}: {subject}",
                data={"ticket_id": ticket["id"], "category": ticket["category"]},
            )
            await send_push_to_user(db, uid, {
                "title": "Nuevo ticket de soporte",
                "body": f"{name}: {subject[:120]}",
                "icon": "/icons/icon-192.png",
                "badge": "/icons/icon-192.png",
                "tag": f"support-{ticket['id']}",
                "url": "/admin/support",
            })
        except Exception as e:  # noqa: BLE001
            logger.error(f"[support] staff notify {uid} failed: {e}")


async def _notify_client_staff_reply(ticket: dict, staff_name: str) -> None:
    try:
        from routes.notifications import _insert_notification
        from push_service import send_push_to_user
    except Exception as e:  # noqa: BLE001
        logger.error(f"[support] notify import failed: {e}")
        return
    uid = ticket["user_id"]
    subject = ticket.get("subject", "")
    try:
        await _insert_notification(
            recipient_user_id=uid,
            type="support_reply",
            title=f"Respuesta de soporte: {subject[:60]}",
            message=f"{staff_name} respondió a tu ticket.",
            data={"ticket_id": ticket["id"]},
        )
        await send_push_to_user(db, uid, {
            "title": "Respuesta de soporte",
            "body": f"{staff_name}: {subject[:120]}",
            "icon": "/icons/icon-192.png",
            "badge": "/icons/icon-192.png",
            "tag": f"support-reply-{ticket['id']}",
            "url": "/dashboard/support",
        })
    except Exception as e:  # noqa: BLE001
        logger.error(f"[support] client notify {uid} failed: {e}")


async def _publish_ticket_sse(ticket: dict, event_type: str) -> None:
    """Push an SSE event so open panels update in real time."""
    try:
        from services.live_bus import publish as live_publish
        payload = {
            "ticket_id": ticket["id"],
            "status": ticket.get("status"),
            "subject": ticket.get("subject"),
            "category": ticket.get("category"),
            "updated_at": ticket.get("updated_at"),
        }
        await live_publish(event_type, payload, user_id=ticket["user_id"])
        await live_publish(event_type, payload, roles=("admin", "employee"))
    except Exception as e:  # noqa: BLE001
        logger.error(f"[support] SSE publish failed: {e}")


# ============================================================
# Client endpoints
# ============================================================

@router.get("/support/tickets/me")
async def list_my_tickets(request: Request) -> Any:
    user = await require_user(request)
    cursor = db.support_tickets.find(
        {"user_id": user["user_id"]},
        {"_id": 0},
    ).sort("updated_at", -1).limit(50)
    return [t async for t in cursor]


@router.post("/support/tickets")
async def create_ticket(payload: NewTicketPayload, request: Request) -> Any:
    user = await require_user(request)
    if user.get("role") in ("admin", "employee"):
        raise HTTPException(status_code=403,
                            detail="Los tickets se abren desde el rol de cliente.")
    await _rate_limit_check(user["user_id"])
    images = _upload_message_images(payload.images)
    first_msg = _new_message("client", user, payload.message, images)
    ticket = {
        "id": uuid.uuid4().hex,
        "user_id": user["user_id"],
        "user_name": user.get("name") or "",
        "user_email": user.get("email") or "",
        "category": payload.category,
        "subject": _sanitize_subject(payload.subject),
        "status": "open",
        "unread_by_staff": True,
        "unread_by_client": False,
        "messages": [first_msg],
        "created_at": iso(now_utc()),
        "updated_at": iso(now_utc()),
        "closed_at": None,
        "closed_by": None,
    }
    await db.support_tickets.insert_one(ticket)
    await _notify_staff_new_ticket(ticket)
    await _publish_ticket_sse(ticket, "support_ticket_created")
    fresh = await db.support_tickets.find_one({"id": ticket["id"]}, {"_id": 0})
    return fresh


@router.post("/support/tickets/{ticket_id}/reply")
async def client_reply(ticket_id: str, payload: ReplyPayload, request: Request) -> Any:
    user = await require_user(request)
    t = await db.support_tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t or t["user_id"] != user["user_id"]:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    if t["status"] == "closed":
        raise HTTPException(status_code=400,
                            detail="Este ticket está cerrado. Abre uno nuevo si necesitas ayuda.")
    images = _upload_message_images(payload.images)
    msg = _new_message("client", user, payload.text, images)
    await db.support_tickets.update_one(
        {"id": ticket_id},
        {"$push": {"messages": msg},
         "$set": {"status": "open", "unread_by_staff": True,
                  "unread_by_client": False,
                  "updated_at": iso(now_utc())}},
    )
    fresh = await db.support_tickets.find_one({"id": ticket_id}, {"_id": 0})
    await _notify_staff_new_ticket(fresh)  # reuse: same tag, staff sees updated ticket
    await _publish_ticket_sse(fresh, "support_ticket_updated")
    return fresh


@router.post("/support/tickets/{ticket_id}/mark-read")
async def client_mark_read(ticket_id: str, request: Request) -> Any:
    user = await require_user(request)
    result = await db.support_tickets.update_one(
        {"id": ticket_id, "user_id": user["user_id"]},
        {"$set": {"unread_by_client": False}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    return {"ok": True}


# ============================================================
# Admin endpoints
# ============================================================

@router.get("/admin/support/unread-count")
async def admin_support_unread_count(request: Request) -> Any:
    """iter107.1 — Lightweight endpoint for the sidebar badge to poll every
    ~60s (or refresh on SSE events). Returns only the count of open/answered
    tickets waiting on staff — no listing, no thread payload.
    """
    await require_permission(request, "support")
    unread = await db.support_tickets.count_documents(
        {"unread_by_staff": True, "status": {"$ne": "closed"}}
    )
    return {"unread": unread}


@router.get("/admin/support/tickets")
async def admin_list_tickets(
    request: Request,
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    await require_permission(request, "support")
    q: dict = {}
    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="status inválido.")
        q["status"] = status
    if category:
        if category not in VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail="category inválido.")
        q["category"] = category
    total = await db.support_tickets.count_documents(q)
    unread = await db.support_tickets.count_documents({"unread_by_staff": True,
                                                       "status": {"$ne": "closed"}})
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    cursor = db.support_tickets.find(q, {"_id": 0}) \
        .sort([("unread_by_staff", -1), ("updated_at", -1)]) \
        .skip(offset).limit(limit)
    items = [t async for t in cursor]
    return {"items": items, "total": total, "unread": unread}


@router.post("/admin/support/tickets/{ticket_id}/reply")
async def admin_reply(ticket_id: str, payload: ReplyPayload, request: Request) -> Any:
    actor = await require_permission(request, "support")
    t = await db.support_tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    if t["status"] == "closed":
        raise HTTPException(status_code=400, detail="Este ticket está cerrado.")
    images = _upload_message_images(payload.images)
    msg = _new_message("staff", actor, payload.text, images)
    await db.support_tickets.update_one(
        {"id": ticket_id},
        {"$push": {"messages": msg},
         "$set": {"status": "answered",
                  "unread_by_staff": False,
                  "unread_by_client": True,
                  "updated_at": iso(now_utc())}},
    )
    fresh = await db.support_tickets.find_one({"id": ticket_id}, {"_id": 0})
    await _notify_client_staff_reply(fresh, actor.get("name") or "Soporte")
    await _publish_ticket_sse(fresh, "support_ticket_updated")
    return fresh


@router.post("/admin/support/tickets/{ticket_id}/close")
async def admin_close(ticket_id: str, request: Request) -> Any:
    actor = await require_permission(request, "support")
    t = await db.support_tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    await db.support_tickets.update_one(
        {"id": ticket_id},
        {"$set": {"status": "closed",
                  "closed_at": iso(now_utc()),
                  "closed_by": actor.get("user_id"),
                  "unread_by_staff": False,
                  "updated_at": iso(now_utc())}},
    )
    fresh = await db.support_tickets.find_one({"id": ticket_id}, {"_id": 0})
    await _publish_ticket_sse(fresh, "support_ticket_updated")
    return fresh


@router.post("/admin/support/tickets/{ticket_id}/mark-read")
async def admin_mark_read(ticket_id: str, request: Request) -> Any:
    await require_permission(request, "support")
    result = await db.support_tickets.update_one(
        {"id": ticket_id},
        {"$set": {"unread_by_staff": False}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    return {"ok": True}


# ============================================================
# FAQ endpoints (public read + admin CRUD)
# ============================================================

@router.get("/support/faq")
async def list_faq(request: Request) -> Any:
    """Public read (auth required to keep behind login gate). Returns only
    active entries; admin editor uses a separate endpoint to see everything."""
    await require_user(request)
    cursor = db.faq_entries.find({"is_active": True}, {"_id": 0}) \
        .sort([("category", 1), ("order", 1)])
    return [e async for e in cursor]


@router.get("/admin/support/faq")
async def admin_list_faq(request: Request) -> Any:
    await require_permission(request, "support")
    cursor = db.faq_entries.find({}, {"_id": 0}).sort([("category", 1), ("order", 1)])
    return [e async for e in cursor]


@router.post("/admin/support/faq")
async def admin_create_faq(payload: FaqEntryPayload, request: Request) -> Any:
    await require_permission(request, "support")
    entry = {
        "id": uuid.uuid4().hex,
        **payload.model_dump(),
        "created_at": iso(now_utc()),
        "updated_at": iso(now_utc()),
    }
    await db.faq_entries.insert_one(entry)
    return await db.faq_entries.find_one({"id": entry["id"]}, {"_id": 0})


@router.put("/admin/support/faq/{entry_id}")
async def admin_update_faq(entry_id: str, payload: FaqEntryPayload, request: Request) -> Any:
    await require_permission(request, "support")
    r = await db.faq_entries.update_one(
        {"id": entry_id},
        {"$set": {**payload.model_dump(), "updated_at": iso(now_utc())}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="FAQ no encontrada.")
    return await db.faq_entries.find_one({"id": entry_id}, {"_id": 0})


@router.delete("/admin/support/faq/{entry_id}")
async def admin_delete_faq(entry_id: str, request: Request) -> Any:
    await require_permission(request, "support")
    r = await db.faq_entries.delete_one({"id": entry_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="FAQ no encontrada.")
    return {"ok": True}
