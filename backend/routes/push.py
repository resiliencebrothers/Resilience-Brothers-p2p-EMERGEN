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
from auth_utils import require_user, now_utc, iso
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
