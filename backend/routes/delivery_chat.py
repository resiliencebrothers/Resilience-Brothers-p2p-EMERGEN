"""iter210 — Chat dentro de la app entre cliente y mensajero durante la
entrega, sin compartir números personales.

- GET  /deliveries/{did}/chat  → mensajes + contexto (marca como leídos)
- POST /deliveries/{did}/chat  → enviar mensaje (solo cliente/mensajero,
  mientras la entrega está activa). SSE en vivo + push al otro participante.
Los admins/staff con permiso `deliveries` pueden LEER el chat (soporte).
"""
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from services.permissions import _has_permission
from db_client import db
from auth_utils import require_user, iso, now_utc

logger = logging.getLogger("delivery_chat")

router = APIRouter(tags=["DeliveryChat"])

CHAT_OPEN_STATUSES = ("accepted", "on_the_way", "arrived", "delivered")


async def unread_counts_for(delivery_ids: list, uid: str) -> dict:
    """{delivery_id: n} de mensajes del otro participante aún no leídos."""
    if not delivery_ids:
        return {}
    rows = await db.delivery_chat.aggregate([
        {"$match": {"delivery_id": {"$in": delivery_ids},
                    "sender_id": {"$ne": uid},
                    "read_by": {"$ne": uid}}},
        {"$group": {"_id": "$delivery_id", "n": {"$sum": 1}}},
    ]).to_list(500)
    return {r["_id"]: r["n"] for r in rows}


async def _chat_context(did: str, user: dict) -> tuple:
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Entrega no encontrada.")
    uid = user["user_id"]
    if d.get("user_id") == uid:
        kind = "client"
    elif d.get("courier_id") == uid:
        kind = "courier"
    elif _has_permission(user, "deliveries"):
        # iter257(D13) — permiso canónico del staff (allowed_permissions vía
        # el predicado central), no el campo legado `permissions`.
        kind = "staff"
    else:
        raise HTTPException(status_code=403,
                            detail="No participas en esta entrega.")
    return d, kind


@router.get("/deliveries/{did}/chat")
async def get_chat(did: str, request: Request) -> Any:
    user = await require_user(request)
    d, kind = await _chat_context(did, user)
    msgs = await db.delivery_chat.find(
        {"delivery_id": did}, {"_id": 0},
    ).sort("created_at", 1).to_list(300)
    if kind in ("client", "courier"):
        await db.delivery_chat.update_many(
            {"delivery_id": did, "sender_id": {"$ne": user["user_id"]},
             "read_by": {"$ne": user["user_id"]}},
            {"$addToSet": {"read_by": user["user_id"]}},
        )
    return {
        "messages": msgs,
        "my_kind": kind,
        "chat_open": d["status"] in CHAT_OPEN_STATUSES,
        "can_send": kind in ("client", "courier")
        and d["status"] in CHAT_OPEN_STATUSES,
        "courier_name": (d.get("courier_name") or "").split(" ")[0],
        "client_name": (d.get("client_name") or "").split(" ")[0],
        "delivery_status": d["status"],
    }


@router.post("/deliveries/{did}/chat")
async def send_chat(did: str, payload: dict, request: Request) -> Any:
    user = await require_user(request)
    d, kind = await _chat_context(did, user)
    if kind not in ("client", "courier"):
        raise HTTPException(
            status_code=403,
            detail="Solo el cliente y el mensajero pueden escribir en este chat.")
    if d["status"] not in CHAT_OPEN_STATUSES:
        raise HTTPException(status_code=409,
                            detail="El chat de esta entrega está cerrado.")
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Escribe un mensaje.")
    if len(text) > 500:
        raise HTTPException(status_code=400,
                            detail="Máximo 500 caracteres por mensaje.")
    first_name = (user.get("name") or "").split(" ")[0] or "Usuario"
    msg = {
        "id": f"dmsg_{uuid.uuid4().hex[:12]}",
        "delivery_id": did,
        "sender_id": user["user_id"],
        "sender_name": first_name,
        "sender_kind": kind,
        "text": text,
        "read_by": [user["user_id"]],
        "created_at": iso(now_utc()),
    }
    await db.delivery_chat.insert_one(dict(msg))
    other_id = d.get("courier_id") if kind == "client" else d.get("user_id")
    # SSE en vivo a ambos participantes (todas sus pestañas abiertas).
    try:
        from services.live_bus import publish as live_publish
        event = {"delivery_id": did, "message": msg}
        for uid in {user["user_id"], other_id} - {None}:
            await live_publish("delivery_chat_message", event, user_id=uid)
    except Exception as e:
        logger.error(f"chat SSE failed: {e}")
    # Push al otro participante — tag por chat para que se colapsen.
    if other_id:
        try:
            from push_service import (
                send_push_to_user, build_generic_admin_alert_payload,
            )
            other = await db.users.find_one({"user_id": other_id},
                                            {"_id": 0, "role": 1})
            url = ("/admin/deliveries"
                   if (other or {}).get("role") in ("admin", "employee")
                   else ("/dashboard/deliveries" if kind == "client"
                         else "/dashboard/vip"))
            p = build_generic_admin_alert_payload(
                title=f"💬 {first_name} — chat de entrega",
                body=text[:120],
                url=url,
                tag=f"delivery-chat-{did}",
            )
            await send_push_to_user(db, other_id, p)
        except Exception as e:
            logger.error(f"chat push failed: {e}")
    return msg
