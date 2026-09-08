"""iter199 — courier panel (Fase 2): delivery jobs, states and 80/20 split.

Courier-facing:
- GET  /courier/deliveries              → available + mine + history + earnings
- POST /courier/deliveries/{id}/claim   → take a free job (race-safe)
- POST /courier/deliveries/{id}/status  → on_the_way | arrived | delivered

Admin-facing (permission `withdrawals`):
- GET  /admin/deliveries                → list with filters
- GET  /admin/couriers                  → assignable couriers + earnings
- POST /admin/deliveries                → manual create (free deliveries)
- POST /admin/deliveries/{id}/assign    → direct assignment
- POST /admin/deliveries/{id}/confirm   → TOTP; credits courier share (USDT)
- POST /admin/deliveries/{id}/cancel
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from db_client import db
from auth_utils import require_user, require_permission, _enforce_totp_step_up, iso, now_utc
from audit_log import log_action
from services.deliveries import build_delivery_doc

logger = logging.getLogger("deliveries")

router = APIRouter(tags=["Deliveries"])

_TRANSITIONS = {
    "accepted": "on_the_way",
    "on_the_way": "arrived",
    "arrived": "delivered",
}


async def _require_courier(request: Request) -> dict:
    user = await require_user(request)
    if user.get("is_courier") or user.get("role") in ("admin", "employee"):
        return user
    raise HTTPException(status_code=403, detail="Solo mensajeros autorizados")


# ------------------------------------------------------------------
# Courier endpoints
# ------------------------------------------------------------------

@router.get("/courier/deliveries")
async def courier_deliveries(request: Request) -> Any:
    me = await _require_courier(request)
    uid = me["user_id"]
    # iter208 — Un delivery `available` puede estar RESERVADO para un
    # mensajero específico (via admin_assign). Solo debe ver:
    #  - reservada para mí → aparece con `reserved_for_me: True`
    #  - sin asignación previa → visible para todos
    # NO ve reservadas para otros couriers.
    available_docs = await db.deliveries.find(
        {"status": "available",
         "$or": [{"assigned_to_courier_id": {"$in": [None, ""]}},
                 {"assigned_to_courier_id": {"$exists": False}},
                 {"assigned_to_courier_id": uid}]},
        {"_id": 0},
    ).sort("created_at", -1).to_list(50)
    for d in available_docs:
        d["reserved_for_me"] = d.get("assigned_to_courier_id") == uid
    mine = await db.deliveries.find(
        {"courier_id": uid,
         "status": {"$in": ["accepted", "on_the_way", "arrived", "delivered"]}},
        {"_id": 0},
    ).sort("updated_at", -1).to_list(50)
    # iter210 — badge de mensajes de chat sin leer por entrega.
    from routes.delivery_chat import unread_counts_for
    unread = await unread_counts_for([d["id"] for d in mine], uid)
    for d in mine:
        d["chat_unread"] = unread.get(d["id"], 0)
    history = await db.deliveries.find(
        {"courier_id": uid, "status": "confirmed"}, {"_id": 0},
    ).sort("updated_at", -1).to_list(50)
    earned = sum(float(d.get("courier_share_usdt") or 0) for d in history)
    pending = sum(float(d.get("courier_share_usdt") or 0)
                  for d in mine if d["status"] == "delivered")
    return {
        "available": available_docs,
        "mine": mine,
        "history": history,
        "earnings": {
            "confirmed_usdt": round(earned, 2),
            "pending_usdt": round(pending, 2),
            "completed_count": len(history),
        },
    }


@router.get("/admin/deliveries/summary")
async def admin_deliveries_summary(request: Request,
                                   date: Optional[str] = None) -> Any:
    """iter216 — Totales de TODO el equipo para la pestaña Entregas:
    entregas confirmadas del día, ganancias (mensajeros/plataforma), en curso
    ahora y desglose por mensajero. `date` YYYY-MM-DD opcional (hoy UTC)."""
    await require_permission(request, "deliveries")
    day = (date or iso(now_utc())[:10])[:10]
    from datetime import datetime, timedelta
    try:
        next_day = (datetime.strptime(day, "%Y-%m-%d")
                    + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="fecha inválida (YYYY-MM-DD)")
    # Confirmadas del día: tras el sello final nada más toca updated_at.
    confirmed = await db.deliveries.find(
        {"status": "confirmed", "updated_at": {"$gte": day, "$lt": next_day}},
        {"_id": 0, "fee_usdt": 1, "courier_share_usdt": 1,
         "platform_share_usdt": 1, "courier_id": 1, "courier_name": 1},
    ).to_list(2000)
    active = await db.deliveries.aggregate([
        {"$match": {"status": {"$in": ["available", "accepted", "on_the_way",
                                       "arrived", "delivered"]}}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]).to_list(10)
    active_counts = {r["_id"]: r["n"] for r in active}
    by_courier: Dict[str, dict] = {}
    for d in confirmed:
        key = d.get("courier_id") or "—"
        row = by_courier.setdefault(key, {
            "courier_name": (d.get("courier_name") or "—").split(" ")[0],
            "count": 0, "earned_usdt": 0.0})
        row["count"] += 1
        row["earned_usdt"] += float(d.get("courier_share_usdt") or 0)
    rows = sorted(by_courier.values(), key=lambda r: -r["earned_usdt"])
    for r in rows:
        r["earned_usdt"] = round(r["earned_usdt"], 2)
    return {
        "date": day,
        "confirmed_count": len(confirmed),
        "total_fees_usdt": round(sum(float(d.get("fee_usdt") or 0)
                                     for d in confirmed), 2),
        "courier_earned_usdt": round(sum(float(d.get("courier_share_usdt") or 0)
                                         for d in confirmed), 2),
        "platform_earned_usdt": round(sum(float(d.get("platform_share_usdt") or 0)
                                          for d in confirmed), 2),
        "active_count": sum(active_counts.get(s, 0) for s in
                            ("accepted", "on_the_way", "arrived")),
        "available_count": active_counts.get("available", 0),
        "delivered_pending_count": active_counts.get("delivered", 0),
        "by_courier": rows,
    }


@router.post("/courier/deliveries/{did}/claim")
async def claim_delivery(did: str, request: Request) -> Any:
    me = await _require_courier(request)
    now = iso(now_utc())
    # iter208 — respetar la reserva: si el admin ya asignó esta entrega a
    # otro mensajero (assigned_to_courier_id != me), no puede tomarla.
    existing = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="No encontrada.")
    reserved = existing.get("assigned_to_courier_id")
    if reserved and reserved != me["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="Esta entrega está reservada para otro mensajero.")
    updated = await db.deliveries.find_one_and_update(
        {"id": did, "status": "available"},
        {"$set": {"status": "accepted", "courier_id": me["user_id"],
                  "courier_name": me.get("name") or me.get("email"),
                  "assigned_to_courier_id": None,
                  "updated_at": now},
         "$push": {"timeline": {"status": "accepted", "at": now,
                                "by": me["user_id"]}}},
        projection={"_id": 0},
        return_document=True,
    )
    if not updated:
        raise HTTPException(status_code=409,
                            detail="Esta entrega ya fue tomada por otro mensajero.")
    # iter209 — Avisar al cliente que un mensajero confirmó/aceptó su
    # entrega (estilo Careem/Noon): in-app + push, con teléfono si existe.
    if updated.get("user_id"):
        try:
            from routes.notifications import _insert_notification
            from push_service import (
                send_push_to_user, build_generic_admin_alert_payload,
            )
            cname = (me.get("name") or "El mensajero").split(" ")[0]
            is_pickup = updated.get("kind") == "deposit"
            noun = "recogida" if is_pickup else "entrega"
            phone = (me.get("phone") or "").strip()
            phone_line = f" Puedes contactarlo al {phone}." if phone else ""
            title = f"✅ Tu {noun} fue confirmada"
            body = (f"{cname} aceptó tu {noun} ({updated.get('amount_label', '')}). "
                    f"Te avisaremos cuando salga en camino.{phone_line}")
            await _insert_notification(
                recipient_user_id=updated["user_id"], type="delivery_status",
                title=title, message=body,
                data={"delivery_id": did, "status": "accepted"})
            push_payload = build_generic_admin_alert_payload(
                title=title, body=body, url="/dashboard",
                tag=f"delivery-{did}-accepted")
            await send_push_to_user(db, updated["user_id"], push_payload)
        except Exception as e:
            logger.error(f"claim client notify failed: {e}")
    return updated


@router.post("/courier/deliveries/{did}/reject-reservation")
async def reject_reservation(did: str, payload: dict, request: Request) -> Any:
    """iter208 — El mensajero puede rechazar una reserva del admin con un
    motivo. Esto libera la entrega (`assigned_to_courier_id=None`) para que
    otro mensajero la tome o el admin la reasigne. Alerta a los admins con
    push+in-app para que actúen rápido."""
    me = await _require_courier(request)
    reason = (payload.get("reason") or "").strip()
    if not reason or len(reason) < 5:
        raise HTTPException(status_code=400,
                            detail="Indica un motivo (mínimo 5 caracteres).")
    if len(reason) > 300:
        raise HTTPException(status_code=400,
                            detail="El motivo no puede superar 300 caracteres.")
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="No encontrada.")
    if d.get("assigned_to_courier_id") != me["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="No puedes rechazar esta reserva (no está asignada a ti).")
    if d["status"] != "available":
        raise HTTPException(
            status_code=409,
            detail=f"No se puede rechazar en estado {d['status']}.")
    now = iso(now_utc())
    courier_name = me.get("name") or me.get("email") or "El mensajero"
    await db.deliveries.update_one({"id": did}, {
        "$set": {"assigned_to_courier_id": None, "updated_at": now},
        "$push": {"timeline": {
            "status": "available", "at": now, "by": me["user_id"],
            "note": f"Reserva rechazada por {courier_name}: {reason}"}},
    })
    # Alertar a admins/staff con permiso de deliveries.
    try:
        from routes.notifications import _insert_notification
        from push_service import (
            send_push_to_user, build_generic_admin_alert_payload,
        )
        title = "🛵 Mensajero rechazó una reserva"
        body = (f"{courier_name} rechazó la entrega de {d.get('client_name','')} "
                f"({d.get('amount_label','')}). Motivo: {reason}")
        admins = await db.users.find(
            {"$or": [{"role": "admin"}, {"role": "employee"}]},
            {"_id": 0, "user_id": 1, "permissions": 1, "role": 1},
        ).to_list(200)
        payload_push = build_generic_admin_alert_payload(
            title=title, body=body,
            url="/admin/deliveries",
            tag=f"delivery-rejected-{did}",
        )
        for a in admins:
            has_perm = (a.get("role") == "admin" or
                        "deliveries" in (a.get("permissions") or []))
            if not has_perm:
                continue
            try:
                await _insert_notification(
                    recipient_user_id=a["user_id"], type="delivery_rejected",
                    title=title, message=body,
                    data={"delivery_id": did, "courier_id": me["user_id"],
                          "reason": reason},
                )
                await send_push_to_user(db, a["user_id"], payload_push)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"reject notify failed: {e}")
    return await db.deliveries.find_one({"id": did}, {"_id": 0})


@router.post("/courier/deliveries/{did}/status")
async def courier_update_status(did: str, payload: dict, request: Request) -> Any:
    me = await _require_courier(request)
    new_status = payload.get("status")
    if new_status not in ("on_the_way", "arrived", "delivered"):
        raise HTTPException(status_code=400, detail="status inválido")
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="No encontrado")
    if d.get("courier_id") != me["user_id"]:
        raise HTTPException(status_code=403, detail="Esta entrega no es tuya")
    if _TRANSITIONS.get(d["status"]) != new_status:
        raise HTTPException(
            status_code=400,
            detail=f"Transición inválida: {d['status']} → {new_status}")
    now = iso(now_utc())
    await db.deliveries.update_one({"id": did}, {
        "$set": {"status": new_status, "updated_at": now},
        "$push": {"timeline": {"status": new_status, "at": now,
                               "by": me["user_id"]}},
    })
    updated = await db.deliveries.find_one({"id": did}, {"_id": 0})
    # iter208 — Notificar al cliente cuando el mensajero avanza el estado
    # para que no tenga que abrir la app a cada rato. Best-effort.
    if new_status in ("on_the_way", "arrived") and d.get("user_id"):
        try:
            from routes.notifications import _insert_notification
            from push_service import (
                send_push_to_user, build_generic_admin_alert_payload,
            )
            cname = (me.get("name") or "El mensajero").split(" ")[0]
            if new_status == "on_the_way":
                title = "🛵 Tu mensajero está en camino"
                body = f"{cname} salió con tu entrega. Puedes seguirlo en tiempo real."
            else:
                title = "📍 Tu mensajero llegó al punto de entrega"
                body = f"{cname} está en el punto — contáctalo si hace falta."
            await _insert_notification(
                recipient_user_id=d["user_id"],
                type="delivery_status", title=title, message=body,
                data={"delivery_id": did, "status": new_status},
            )
            payload = build_generic_admin_alert_payload(
                title=title, body=body,
                url="/dashboard/vip",
                tag=f"delivery-{did}-{new_status}",
            )
            await send_push_to_user(db, d["user_id"], payload)
        except Exception as e:
            logger.error(f"client status push failed: {e}")
    if new_status == "delivered":
        try:
            from admin_alerts import notify_all_admins
            await notify_all_admins(
                db,
                title=f"📦 Entrega #{did[:8]} marcada como ENTREGADA",
                body=(f"{me.get('name') or 'Mensajero'} entregó a "
                      f"{d.get('client_name', '')} ({d.get('amount_label', '')}). "
                      f"Confírmala para acreditar su {d.get('share_pct_snapshot', 80):g}% "
                      f"({d.get('courier_share_usdt', 0)} USDT)."),
                url_path="/admin/deliveries",
            )
        except Exception as e:
            logger.error(f"delivered admin notify failed: {e}")
        # iter215 — el mensajero confirmó la entrega física: el retiro cash
        # vinculado pasa a 'paid' de inmediato para que Transacciones y
        # Depósitos y Retiros reflejen la realidad sin esperar al admin.
        # (El 80% del mensajero sigue requiriendo la confirmación admin.)
        if d.get("kind") == "withdrawal":
            try:
                from routes.admin_withdrawals import mark_paid_from_delivery
                await mark_paid_from_delivery(d["ref_id"], me)
            except Exception as e:
                logger.error(f"auto-paid after courier delivered failed: {e}")
    return updated


@router.post("/courier/location")
async def courier_share_location(payload: dict, request: Request) -> Any:
    """iter207 — el mensajero comparte su posición en vivo: se refleja en
    TODOS sus trabajos activos para que el cliente lo siga en el mapa."""
    me = await _require_courier(request)
    try:
        lat = float(payload.get("lat"))
        lon = float(payload.get("lon"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Coordenadas inválidas.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Coordenadas inválidas.")
    now = iso(now_utc())
    r = await db.deliveries.update_many(
        {"courier_id": me["user_id"],
         "status": {"$in": ["accepted", "on_the_way", "arrived"]}},
        {"$set": {"courier_location": {"lat": lat, "lon": lon,
                                       "updated_at": now}}},
    )
    return {"updated": r.modified_count}


@router.get("/vip/deliveries/track")
async def track_my_deliveries(request: Request) -> Any:
    """iter207 — el cliente sigue sus entregas en curso: estado, mensajero
    (nombre + teléfono para comunicarse) y su ubicación en vivo."""
    user = await require_user(request)
    rows = await db.deliveries.find(
        {"user_id": user["user_id"],
         "status": {"$in": ["available", "accepted", "on_the_way",
                            "arrived", "delivered"]}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(20)
    from routes.delivery_chat import unread_counts_for
    unread = await unread_counts_for([d["id"] for d in rows], user["user_id"])
    items = []
    for d in rows:
        item = {
            "id": d["id"], "kind": d["kind"], "ref_id": d["ref_id"],
            "status": d["status"], "amount_label": d.get("amount_label"),
            "address": d.get("address"), "province": d.get("province"),
            "km": d.get("km"),
            "delivery_latitude": d.get("delivery_latitude"),
            "delivery_longitude": d.get("delivery_longitude"),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
            "chat_unread": unread.get(d["id"], 0),
            "timeline": [{"status": e.get("status"), "at": e.get("at")}
                         for e in (d.get("timeline") or [])],
            "courier": None,
        }
        if d.get("courier_id"):
            c = await db.users.find_one({"user_id": d["courier_id"]},
                                        {"_id": 0, "name": 1, "phone": 1})
            item["courier"] = {
                "name": d.get("courier_name") or (c or {}).get("name") or "Mensajero",
                "phone": (c or {}).get("phone") or "",
                "location": d.get("courier_location"),
            }
        items.append(item)
    return {"items": items}


# ------------------------------------------------------------------
# Admin endpoints
# ------------------------------------------------------------------

@router.get("/admin/deliveries")
async def admin_list_deliveries(request: Request, status: Optional[str] = None,
                                courier_id: Optional[str] = None) -> Any:
    await require_permission(request, "deliveries")
    q: dict = {}
    if status:
        q["status"] = status
    if courier_id:
        q["courier_id"] = courier_id
    rows = await db.deliveries.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return rows


@router.get("/admin/couriers")
async def admin_list_couriers(request: Request) -> Any:
    await require_permission(request, "deliveries")
    users = await db.users.find(
        {"$or": [{"is_courier": True}, {"role": {"$in": ["admin", "employee"]}}]},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1,
         "is_courier": 1, "phone": 1},
    ).to_list(200)
    stats = await db.deliveries.aggregate([
        {"$match": {"status": "confirmed"}},
        {"$group": {"_id": "$courier_id",
                    "earned": {"$sum": "$courier_share_usdt"},
                    "count": {"$sum": 1}}},
    ]).to_list(500)
    by_id = {s["_id"]: s for s in stats}
    for u in users:
        s = by_id.get(u["user_id"], {})
        u["earned_usdt"] = round(float(s.get("earned") or 0), 2)
        u["deliveries_count"] = int(s.get("count") or 0)
    return users


@router.post("/admin/deliveries")
async def admin_create_delivery(payload: dict, request: Request) -> Any:
    """Manual creation — mainly for FREE deliveries (fee 0) that still need a
    courier, since charged ones are auto-created with the fee."""
    actor = await require_permission(request, "deliveries")
    kind = payload.get("kind")
    ref_id = payload.get("ref_id")
    if kind not in ("withdrawal", "redemption") or not ref_id:
        raise HTTPException(status_code=400, detail="kind/ref_id inválidos")
    coll = db.withdrawals if kind == "withdrawal" else db.redemptions
    ref = await coll.find_one({"id": ref_id}, {"_id": 0})
    if not ref:
        raise HTTPException(status_code=404, detail="Operación no encontrada")
    if kind == "withdrawal" and ref.get("method") != "cash":
        raise HTTPException(status_code=400,
                            detail="Solo retiros en efectivo llevan mensajería")
    existing = await db.deliveries.find_one(
        {"kind": kind, "ref_id": ref_id, "status": {"$ne": "cancelled"}})
    if existing:
        raise HTTPException(status_code=409, detail="Ya existe una entrega para esta operación")
    km = float(ref.get("courier_km") or ref.get("courier_quote_km") or 0)
    fee = float(ref.get("courier_fee_usdt") or 0)
    doc = await build_delivery_doc(kind, ref, km=km, fee_usdt=fee,
                                   created_by=actor["user_id"])
    await db.deliveries.insert_one(dict(doc))
    # iter208 — broadcast a couriers cuando el admin crea manualmente
    # una entrega disponible.
    try:
        from services.deliveries import _broadcast_new_delivery_to_couriers
        await _broadcast_new_delivery_to_couriers(doc)
    except Exception as e:
        logger.error(f"manual create push failed: {e}")
    await log_action(db, actor, "delivery.create", "delivery", doc["id"],
                     summary=f"Entrega manual creada para {kind} {ref_id[:8]}",
                     details={"kind": kind, "ref_id": ref_id, "fee_usdt": fee})
    return doc


@router.post("/admin/deliveries/{did}/assign")
async def admin_assign_delivery(did: str, payload: dict, request: Request) -> Any:
    """iter208 — El admin *reserva* la entrega para un mensajero pero NO la
    acepta en su nombre: la deja como `available` con `assigned_to_courier_id`
    apuntando al mensajero elegido. El mensajero recibe la notificación y
    push, y luego tiene que tocar 'Aceptar' en su panel para pasar a
    `accepted`. Así el mensajero confirma antes de que la orden se le
    contabilice como en curso."""
    actor = await require_permission(request, "deliveries")
    courier_id = payload.get("courier_id")
    if not courier_id:
        raise HTTPException(status_code=400, detail="courier_id requerido")
    courier = await db.users.find_one({"user_id": courier_id}, {"_id": 0})
    if not courier or not (courier.get("is_courier")
                           or courier.get("role") in ("admin", "employee")):
        raise HTTPException(status_code=400, detail="Ese usuario no es mensajero")
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="No encontrado")
    if d["status"] not in ("available", "accepted"):
        raise HTTPException(status_code=409,
                            detail=f"No se puede reasignar en estado {d['status']}")
    now = iso(now_utc())
    courier_display = courier.get("name") or courier.get("email")
    await db.deliveries.update_one({"id": did}, {
        "$set": {"status": "available",
                 "assigned_to_courier_id": courier_id,
                 "courier_id": None,
                 "courier_name": None,
                 "updated_at": now},
        "$push": {"timeline": {"status": "available", "at": now,
                               "by": actor["user_id"],
                               "note": f"Reservada para {courier_display} — pendiente de aceptación"}},
    })
    try:
        from routes.notifications import _insert_notification
        # iter208 — Diferenciamos el copy según sea entrega (retiro/canje)
        # o recogida (depósito cash-courier).
        is_pickup = d.get("kind") == "deposit"
        title = "Nueva recogida asignada" if is_pickup else "Nueva entrega asignada"
        verb = "recoger" if is_pickup else "entregar"
        share = float(d.get("courier_share_usdt") or 0)
        share_line = (f" Tu parte: {share} USDT." if share > 0
                      else "")
        msg = (f"Te asignaron {verb} para {d.get('client_name', '')} "
               f"({d.get('amount_label', '')}).{share_line}")
        await _insert_notification(
            recipient_user_id=courier_id, type="delivery_assigned",
            title=title, message=msg,
            data={"delivery_id": did, "kind": d.get("kind")})
        # iter208 — Alerta empuje al mensajero (misma info que la notif
        # in-app) para que le llegue al móvil aunque no tenga la app abierta.
        try:
            from push_service import (
                send_push_to_user, build_generic_admin_alert_payload,
            )
            payload = build_generic_admin_alert_payload(
                title=title, body=msg,
                url="/courier",
                tag=f"delivery-assigned-{did}",
            )
            await send_push_to_user(db, courier_id, payload)
        except Exception as e:
            logger.error(f"assign push failed: {e}")
    except Exception as e:
        logger.error(f"assign notify failed: {e}")
    return await db.deliveries.find_one({"id": did}, {"_id": 0})


@router.post("/admin/deliveries/{did}/confirm")
async def admin_confirm_delivery(did: str, payload: dict, request: Request) -> Any:
    """Staff seal after the courier marks `delivered`: credits the courier's
    share (80% default) to their in-platform USDT balance. Idempotent."""
    actor = await require_permission(request, "deliveries")
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                 action_label="confirmar entrega")
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="No encontrado")
    if d["status"] != "delivered":
        raise HTTPException(status_code=409,
                            detail="Solo se confirman entregas marcadas como entregadas")
    from services.deliveries import do_confirm_delivery
    return await do_confirm_delivery(d, actor)


@router.post("/admin/deliveries/{did}/cancel")
async def admin_cancel_delivery(did: str, payload: dict, request: Request) -> Any:
    actor = await require_permission(request, "deliveries")
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="No encontrado")
    if d["status"] in ("confirmed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Ya está {d['status']}")
    now = iso(now_utc())
    await db.deliveries.update_one({"id": did}, {
        "$set": {"status": "cancelled", "updated_at": now},
        "$push": {"timeline": {"status": "cancelled", "at": now,
                               "by": actor["user_id"],
                               "note": (payload.get("note") or "")[:200]}},
    })
    await log_action(db, actor, "delivery.cancel", "delivery", did,
                     summary=f"Entrega {did[:8]} cancelada")
    if d.get("courier_id"):
        try:
            from routes.notifications import _insert_notification
            await _insert_notification(
                recipient_user_id=d["courier_id"], type="delivery_cancelled",
                title="Entrega cancelada",
                message=(f"La entrega de {d.get('client_name', '')} fue cancelada "
                         "por el equipo."),
                data={"delivery_id": did})
        except Exception as e:
            logger.error(f"cancel notify failed: {e}")
    return await db.deliveries.find_one({"id": did}, {"_id": 0})
