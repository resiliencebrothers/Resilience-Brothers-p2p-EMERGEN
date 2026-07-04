"""Client self-service appeals for `under_review` accounts.

Flow:
1. Any user with `account_status == 'under_review'` can submit ONE open appeal
   at a time via `POST /appeals` explaining why they should be reviewed.
2. Staff (admin + employee with `can_manage_blocklist`) see appeals in a queue
   via `GET /admin/appeals` and resolve them via
   `POST /admin/appeals/{id}/resolve` or `POST /admin/appeals/{id}/reject`
   with a note back to the client.
3. Both submission (staff-inbound) and resolution (client-inbound) fire in-app
   notifications + Web Push via `routes/notifications`.

Resolving an appeal does NOT auto-activate the user; staff must still go through
the existing `Verify Phone` flow (`POST /admin/users/{user_id}/verify-phone`).
This keeps concerns separated: an appeal is a *message*, activation is a
*decision*.

Idempotency guarantee: `POST /appeals` is rejected with 409 if the user already
has an appeal with `status == "pending"`.
"""
import uuid
import logging
from typing import Any, Optional, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from security_middleware import limiter
from db_client import db
from auth_utils import require_user, require_staff, now_utc, iso
from audit_log import log_action

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Appeals"])


# ============================================================
# Permission helper (mirrors blocklist.py)
# ============================================================

async def _assert_can_review_appeals(actor: dict) -> None:
    if actor.get("role") == "admin":
        return
    if actor.get("role") == "employee" and actor.get("can_manage_blocklist"):
        return
    raise HTTPException(
        status_code=403,
        detail="No tienes permiso para revisar apelaciones. Pídeselo a un administrador.",
    )


# ============================================================
# Models
# ============================================================

class AppealCreatePayload(BaseModel):
    message: str = Field(..., min_length=10, max_length=2000)


class AppealResolvePayload(BaseModel):
    response: str = Field(..., min_length=1, max_length=1000)


# ============================================================
# Client endpoints
# ============================================================

@router.post("/appeals")
@limiter.limit("5/hour")
async def create_appeal(payload: AppealCreatePayload, request: Request, response: Response) -> Any:
    """Submit a new appeal. Only allowed while the account is `under_review`."""
    user = await require_user(request)
    if user.get("account_status") != "under_review":
        raise HTTPException(
            status_code=400,
            detail="Solo puedes enviar una apelación si tu cuenta está bajo revisión.",
        )
    existing_pending = await db.appeals.find_one(
        {"user_id": user["user_id"], "status": "pending"}, {"_id": 0}
    )
    if existing_pending:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "APPEAL_ALREADY_PENDING",
                "message": "Ya tienes una apelación pendiente. Espera a que el staff la revise antes de enviar otra.",
                "appeal_id": existing_pending["id"],
            },
        )
    doc = {
        "id": uuid.uuid4().hex,
        "user_id": user["user_id"],
        "user_email": user.get("email", ""),
        "user_name": user.get("name", ""),
        "user_phone": user.get("phone", ""),
        "message": payload.message.strip(),
        "status": "pending",
        "staff_response": None,
        "resolved_by": None,
        "resolved_by_email": None,
        "resolved_at": None,
        "created_at": iso(now_utc()),
    }
    await db.appeals.insert_one(doc)
    # motor's insert_one mutates `doc` adding `_id`; strip it before returning.
    doc.pop("_id", None)
    # Fan-out notification to staff. Import lazily to avoid circulars.
    try:
        from routes.notifications import notify_staff_new_appeal
        await notify_staff_new_appeal(doc)
    except Exception as e:  # noqa: BLE001
        logger.error(f"notify_staff_new_appeal failed: {e}")
    return {"ok": True, "appeal": doc}


@router.get("/appeals/me")
async def list_my_appeals(request: Request) -> Any:
    """Return the caller's most recent appeals, newest first (max 20)."""
    user = await require_user(request)
    cursor = db.appeals.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(20)
    items = await cursor.to_list(length=20)
    return {"items": items}


# ============================================================
# Staff endpoints
# ============================================================

@router.get("/admin/appeals")
async def list_appeals(
    request: Request,
    status: Optional[Literal["pending", "resolved", "rejected"]] = None,
    limit: int = 100,
) -> Any:
    """Staff queue of appeals. Default lists all statuses newest-first."""
    requester = await require_staff(request)
    await _assert_can_review_appeals(requester)
    q: dict = {}
    if status:
        q["status"] = status
    limit = min(max(limit, 1), 500)
    cursor = db.appeals.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    items = await cursor.to_list(length=limit)
    pending_count = await db.appeals.count_documents({"status": "pending"})
    return {"items": items, "pending_count": pending_count}


async def _resolve_appeal_internal(
    appeal_id: str, requester: dict, payload: AppealResolvePayload,
    new_status: Literal["resolved", "rejected"],
) -> dict:
    appeal = await db.appeals.find_one({"id": appeal_id}, {"_id": 0})
    if not appeal:
        raise HTTPException(status_code=404, detail="Apelación no encontrada")
    if appeal["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Esta apelación ya fue procesada (estado actual: {appeal['status']}).",
        )
    resolved_at = iso(now_utc())
    await db.appeals.update_one(
        {"id": appeal_id},
        {"$set": {
            "status": new_status,
            "staff_response": payload.response.strip(),
            "resolved_by": requester["user_id"],
            "resolved_by_email": requester.get("email", ""),
            "resolved_at": resolved_at,
        }},
    )
    fresh = await db.appeals.find_one({"id": appeal_id}, {"_id": 0})
    # Notify the user that their appeal was reviewed.
    try:
        from routes.notifications import notify_user_appeal_reviewed
        await notify_user_appeal_reviewed(fresh)
    except Exception as e:  # noqa: BLE001
        logger.error(f"notify_user_appeal_reviewed failed: {e}")
    await log_action(
        db, requester, f"appeal.{new_status}", "appeal", appeal_id,
        summary=f"Apelación {new_status} para {appeal.get('user_email','')}",
        details={
            "user_id": appeal["user_id"],
            "user_email": appeal.get("user_email"),
            "response": payload.response.strip()[:200],
        },
    )
    return fresh


@router.post("/admin/appeals/{appeal_id}/resolve")
async def resolve_appeal(
    appeal_id: str, payload: AppealResolvePayload, request: Request,
) -> Any:
    """Mark the appeal as `resolved` — the staff message is delivered to the
    client. Does NOT re-activate the account; use `verify-phone` for that."""
    requester = await require_staff(request)
    await _assert_can_review_appeals(requester)
    fresh = await _resolve_appeal_internal(appeal_id, requester, payload, "resolved")
    return {"ok": True, "appeal": fresh}


@router.post("/admin/appeals/{appeal_id}/reject")
async def reject_appeal(
    appeal_id: str, payload: AppealResolvePayload, request: Request,
) -> Any:
    """Mark the appeal as `rejected`. Client keeps `under_review` status but is
    told why the appeal did not succeed."""
    requester = await require_staff(request)
    await _assert_can_review_appeals(requester)
    fresh = await _resolve_appeal_internal(appeal_id, requester, payload, "rejected")
    return {"ok": True, "appeal": fresh}
