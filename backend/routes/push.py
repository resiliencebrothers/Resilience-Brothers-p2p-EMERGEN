"""Push subscriptions router — iter32. Web Push (VAPID) infrastructure.

Endpoints:
- GET  /push/vapid-public-key  (public — frontend uses this to subscribe)
- POST /push/subscribe         (auth — register a browser PushSubscription)
- POST /push/unsubscribe       (auth — remove by endpoint)
- POST /push/test              (auth — fire a sample push so user can verify)
"""
import uuid
import logging
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from db_client import db
from auth_utils import require_user, require_staff, now_utc, iso
from push_service import VAPID_PUBLIC_KEY, send_push


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Push"])


class PushSubscriptionCreate(BaseModel):
    subscription: dict  # browser PushSubscription JSON
    user_agent: Optional[str] = ""


@router.get("/push/vapid-public-key")
async def push_vapid_public_key() -> Any:
    return {"key": VAPID_PUBLIC_KEY}


@router.post("/push/subscribe")
async def push_subscribe(payload: PushSubscriptionCreate, request: Request) -> Any:
    user = await require_user(request)
    endpoint = (payload.subscription or {}).get("endpoint", "")
    if not endpoint:
        raise HTTPException(status_code=400, detail="Subscription inválida")
    await db.push_subscriptions.update_one(
        {"endpoint": endpoint},
        {"$set": {
            "id": str(uuid.uuid4()),
            "user_id": user["user_id"],
            "endpoint": endpoint,
            "subscription": payload.subscription,
            "user_agent": payload.user_agent or "",
            "created_at": iso(now_utc()),
        }},
        upsert=True,
    )
    return {"ok": True}


@router.post("/push/unsubscribe")
async def push_unsubscribe(payload: dict, request: Request) -> Any:
    user = await require_user(request)
    endpoint = payload.get("endpoint", "")
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint requerido")
    await db.push_subscriptions.delete_one({"endpoint": endpoint, "user_id": user["user_id"]})
    return {"ok": True}


@router.post("/push/test")
async def push_test(request: Request) -> Any:
    """Send a test push to the current user's devices — useful for staff to confirm
    their phone receives alerts BEFORE walking away from the PC."""
    user = await require_user(request)
    subs = await db.push_subscriptions.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(50)
    if not subs:
        raise HTTPException(status_code=404, detail="No tienes dispositivos suscritos")
    payload = {
        "title": "Resilience Brothers",
        "body": "Notificaciones activadas correctamente ✓",
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": "test-notification",
        "url": "/dashboard",
    }
    delivered = sum(1 for s in subs if send_push(s["subscription"], payload) == "ok")
    return {"delivered": delivered, "total": len(subs)}


@router.get("/admin/push/stats")
async def admin_push_stats(request: Request) -> Any:
    """iter55.5 — Diagnostic endpoint. Returns counts of push subscriptions
    per role so the operator can verify why a fanout may have delivered zero
    notifications (e.g. no clients subscribed, VAPID mismatch after redeploy,
    etc.)."""
    await require_staff(request)
    subs = await db.push_subscriptions.find({}, {"_id": 0}).to_list(5000)
    user_ids = list({s.get("user_id") for s in subs if s.get("user_id")})
    users = await db.users.find(
        {"user_id": {"$in": user_ids}},
        {"_id": 0, "user_id": 1, "role": 1, "email": 1, "name": 1},
    ).to_list(len(user_ids))
    role_by_id = {u["user_id"]: u.get("role") for u in users}
    name_by_id = {u["user_id"]: {"email": u.get("email"), "name": u.get("name")} for u in users}
    by_role: dict = {}
    for s in subs:
        role = role_by_id.get(s.get("user_id")) or "orphan"
        by_role[role] = by_role.get(role, 0) + 1
    return {
        "total_subscriptions": len(subs),
        "by_role": by_role,
        "client_subscriptions": by_role.get("vip", 0) + by_role.get("normal", 0),
        "sample_last_5": [
            {
                "user_id": s.get("user_id"),
                "user_email": name_by_id.get(s.get("user_id"), {}).get("email"),
                "role": role_by_id.get(s.get("user_id")) or "orphan",
                "user_agent": (s.get("user_agent") or "")[:60],
                "endpoint_host": (s.get("endpoint") or "")[:60],
                "created_at": s.get("created_at"),
            }
            for s in sorted(subs, key=lambda x: x.get("created_at", ""), reverse=True)[:5]
        ],
    }
