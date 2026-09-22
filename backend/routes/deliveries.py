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
import uuid
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


def _strip_courier_secret(doc: Any) -> Any:
    """Mejora #2 — el PIN de entrega es SOLO del cliente: jamás viaja en las
    respuestas del mensajero. Se expone `pin_required` para que la UI sepa
    que debe pedirlo al confirmar la entrega."""
    if isinstance(doc, dict):
        doc["pin_required"] = bool(doc.get("delivery_pin")) \
            and not doc.get("pin_verified")
        doc.pop("delivery_pin", None)
    return doc


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
    # MSG07 — las reservas dirigidas al mensajero se consultan SIEMPRE con
    # prioridad propia: nunca desaparecen detrás del tope de la lista libre.
    reserved_docs = await db.deliveries.find(
        {"status": "available", "assigned_to_courier_id": uid},
        {"_id": 0},
    ).sort("created_at", -1).to_list(50)
    open_docs = await db.deliveries.find(
        {"status": "available",
         "$or": [{"assigned_to_courier_id": {"$in": [None, ""]}},
                 {"assigned_to_courier_id": {"$exists": False}}]},
        {"_id": 0},
    ).sort("created_at", -1).to_list(50)
    available_docs = reserved_docs + open_docs
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
    # MSG07 — totales por AGREGACIÓN sobre todo el historial, no sobre la
    # ventana de 50 filas mostrada: mensajero y administración coinciden.
    agg = await db.deliveries.aggregate([
        {"$match": {"courier_id": uid, "status": "confirmed"}},
        {"$group": {"_id": None,
                    "earned": {"$sum": "$courier_share_usdt"},
                    "count": {"$sum": 1}}},
    ]).to_list(1)
    earned = float((agg[0] if agg else {}).get("earned") or 0)
    completed_count = int((agg[0] if agg else {}).get("count") or 0)
    pending_agg = await db.deliveries.aggregate([
        {"$match": {"courier_id": uid, "status": "delivered"}},
        {"$group": {"_id": None, "s": {"$sum": "$courier_share_usdt"}}},
    ]).to_list(1)
    pending = float((pending_agg[0] if pending_agg else {}).get("s") or 0)
    # Mejora #1 — efectivo a rendir del mensajero (por moneda).
    from services.courier_cash import cash_pending
    my_cash = [c for c in await cash_pending(uid) if c["pending"] != 0]
    for d in available_docs + mine + history:
        _strip_courier_secret(d)
    return {
        "available": available_docs,
        "mine": mine,
        "history": history,
        "cash_pending": my_cash,
        "earnings": {
            "confirmed_usdt": round(earned, 2),
            "pending_usdt": round(pending, 2),
            "completed_count": completed_count,
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
    existing = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="No encontrada.")
    # MSG03 — el origen (retiro/canje/depósito) debe seguir operable antes
    # de aceptar: una operación rechazada no admite aceptación ni comisión.
    from services.deliveries import (REF_COLLS, TERMINAL_REF_STATUSES,
                                     handle_origin_rejected)
    ref_coll = REF_COLLS.get(existing.get("kind"))
    if ref_coll and existing.get("ref_id"):
        ref = await db[ref_coll].find_one({"id": existing["ref_id"]},
                                          {"_id": 0, "status": 1})
        if ref and ref.get("status") in TERMINAL_REF_STATUSES:
            await handle_origin_rejected(
                existing["kind"], existing["ref_id"],
                note=f"origen {ref.get('status')}")
            raise HTTPException(
                status_code=409,
                detail=("La operación de origen fue rechazada/cancelada — "
                        "esta entrega ya no está disponible."))
    # iter208/ME02 — la reserva del admin se respeta DENTRO del filtro
    # atómico: una reserva escrita entre la lectura y la aceptación ya no
    # puede ser borrada por un mensajero que llegó tarde.
    updated = await db.deliveries.find_one_and_update(
        {"id": did, "status": "available",
         "$or": [{"assigned_to_courier_id": {"$in": [None, ""]}},
                 {"assigned_to_courier_id": me["user_id"]}]},
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
        fresh = await db.deliveries.find_one(
            {"id": did}, {"_id": 0, "status": 1, "assigned_to_courier_id": 1})
        reserved = (fresh or {}).get("assigned_to_courier_id")
        if (fresh or {}).get("status") == "available" and reserved \
                and reserved != me["user_id"]:
            raise HTTPException(
                status_code=403,
                detail="Esta entrega está reservada para otro mensajero.")
        raise HTTPException(status_code=409,
                            detail="Esta entrega ya fue tomada por otro mensajero.")
    # MSG10 — los demás paneles abiertos ven desaparecer el trabajo en vivo.
    try:
        from services.deliveries import publish_delivery_event
        await publish_delivery_event(did, "accepted")
    except Exception:
        pass
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
    return _strip_courier_secret(updated)


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
    # MSG06 — la liberación exige que la reserva LEÍDA siga vigente: un
    # rechazo atrasado de A jamás borra la reserva nueva de B.
    res = await db.deliveries.update_one(
        {"id": did, "status": "available",
         "assigned_to_courier_id": me["user_id"]}, {
            "$set": {"assigned_to_courier_id": None, "updated_at": now},
            "$push": {"timeline": {
                "status": "available", "at": now, "by": me["user_id"],
                "note": f"Reserva rechazada por {courier_name}: {reason}"}},
        })
    if res.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail=("La reserva cambió (ya no está asignada a ti o la "
                    "entrega cambió de estado); recarga tu panel."))
    try:
        from services.deliveries import publish_delivery_event
        await publish_delivery_event(did, "available")
    except Exception:
        pass
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
    return _strip_courier_secret(
        await db.deliveries.find_one({"id": did}, {"_id": 0}))


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
    extra_set: Dict[str, Any] = {}
    tl_note = None
    # Mejora #2 auditoría — evidencia de entrega: PIN de un solo uso del
    # cliente, o excepción con motivo (queda marcada para revisión admin).
    if new_status == "delivered" and d.get("delivery_pin") \
            and not d.get("pin_verified"):
        pin = str(payload.get("pin") or "").strip()
        exc_reason = str(payload.get("pin_exception_reason") or "").strip()
        if pin:
            if pin != str(d["delivery_pin"]):
                raise HTTPException(
                    status_code=400,
                    detail="PIN incorrecto — pídeselo al cliente que recibe.")
            extra_set["pin_verified"] = True
            extra_set["pin_verified_at"] = now
            tl_note = "PIN de entrega verificado"
        elif exc_reason:
            if len(exc_reason) < 5:
                raise HTTPException(
                    status_code=400,
                    detail="Indica el motivo de la excepción (mínimo 5 caracteres).")
            extra_set["pin_exception"] = {"reason": exc_reason[:300],
                                          "by": me["user_id"], "at": now}
            tl_note = f"Entrega SIN PIN — motivo: {exc_reason[:120]}"
        else:
            raise HTTPException(
                status_code=400,
                detail=("Introduce el PIN del cliente para confirmar la "
                        "entrega, o registra una excepción con motivo."))
    # MSG01 — la escritura exige que SIGAN vigentes el estado y el repartidor
    # comprobados: una petición atrasada (cancelación/reasignación en medio)
    # pierde con 409 y no revive ni altera la entrega.
    res = await db.deliveries.update_one(
        {"id": did, "status": d["status"], "courier_id": me["user_id"]}, {
            "$set": {"status": new_status, "updated_at": now, **extra_set},
            "$push": {"timeline": {"status": new_status, "at": now,
                                   "by": me["user_id"], "note": tl_note}},
        })
    if res.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail=("La entrega cambió de estado o de mensajero mientras "
                    "actualizabas — recarga tu panel."))
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
        # Mejora #1 — registro automático del efectivo en tránsito.
        from services.courier_cash import auto_events_for_delivered
        await auto_events_for_delivered({**d, "status": "delivered"},
                                        me["user_id"])
        if extra_set.get("pin_exception"):
            try:
                from admin_alerts import notify_all_admins
                await notify_all_admins(
                    db,
                    title="⚠️ Entrega confirmada SIN PIN",
                    body=(f"{me.get('name') or 'Mensajero'} marcó entregada "
                          f"#{did[:8]} de {d.get('client_name', '')} sin PIN. "
                          f"Motivo: {extra_set['pin_exception']['reason']}"),
                    url_path="/admin/deliveries")
            except Exception as e:
                logger.error(f"pin exception notify failed: {e}")
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
    return _strip_courier_secret(updated)


@router.post("/courier/location")
async def courier_share_location(payload: dict, request: Request) -> Any:
    """iter207 — el mensajero comparte su posición en vivo: se refleja en
    TODOS sus trabajos activos para que el cliente lo siga en el mapa."""
    me = await _require_courier(request)
    try:
        lat = float(str(payload.get("lat")))
        lon = float(str(payload.get("lon")))
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


# ------------------------------------------------------------------
# Mejora #3 auditoría — incidencias y reprogramación
# ------------------------------------------------------------------

INCIDENT_TYPES = {
    "no_responde": "Cliente no responde",
    "direccion_incorrecta": "Dirección incorrecta",
    "importe_diferente": "Importe diferente",
    "no_entregado": "No se pudo entregar",
    "reprogramar": "Reprogramar",
}


@router.post("/courier/deliveries/{did}/incident")
async def courier_report_incident(did: str, payload: dict,
                                  request: Request) -> Any:
    """El mensajero registra una incidencia sobre SU entrega activa: motivo,
    nota y (opcional) próximo intento. El operador la ve con responsable y
    línea de tiempo; para «importe diferente» NUNCA se confirma la cifra
    automáticamente — la resuelve el admin."""
    me = await _require_courier(request)
    itype = payload.get("type")
    if itype not in INCIDENT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de incidencia inválido")
    note = (payload.get("note") or "").strip()
    if len(note) < 5:
        raise HTTPException(
            status_code=400,
            detail="Describe la incidencia (mínimo 5 caracteres).")
    if len(note) > 300:
        raise HTTPException(
            status_code=400,
            detail="La descripción no puede superar 300 caracteres.")
    next_attempt = (str(payload.get("next_attempt_at") or "").strip()
                    or None)
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="No encontrada.")
    if d.get("courier_id") != me["user_id"]:
        raise HTTPException(status_code=403, detail="Esta entrega no es tuya")
    if d["status"] not in ("accepted", "on_the_way", "arrived", "delivered"):
        raise HTTPException(
            status_code=409,
            detail=f"No se pueden registrar incidencias en estado {d['status']}.")
    now = iso(now_utc())
    inc = {"id": uuid.uuid4().hex[:12], "type": itype, "note": note,
           "by": me["user_id"], "by_name": me.get("name") or "",
           "at": now, "next_attempt_at": next_attempt, "status": "open"}
    # Escritura condicionada (misma disciplina MSG01): la entrega debe seguir
    # en el estado leído y a nombre del mensajero.
    res = await db.deliveries.update_one(
        {"id": did, "courier_id": me["user_id"], "status": d["status"]},
        {"$push": {"incidents": inc,
                   "timeline": {"status": "incident", "at": now,
                                "by": me["user_id"],
                                "note": f"{INCIDENT_TYPES[itype]}: {note[:150]}"}},
         "$set": {"has_open_incident": True, "updated_at": now}})
    if res.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="La entrega cambió mientras registrabas — recarga tu panel.")
    cname = me.get("name") or "El mensajero"
    try:
        from admin_alerts import notify_all_admins
        await notify_all_admins(
            db,
            title=f"⚠️ Incidencia en entrega #{did[:8]}: {INCIDENT_TYPES[itype]}",
            body=(f"{cname} reporta «{INCIDENT_TYPES[itype]}» en la entrega de "
                  f"{d.get('client_name', '')} ({d.get('amount_label', '')}). "
                  f"Nota: {note}"
                  + (f" · Próximo intento: {next_attempt}" if next_attempt else "")),
            url_path="/admin/deliveries")
    except Exception as e:
        logger.error(f"incident admin notify failed: {e}")
    if itype in ("no_responde", "reprogramar") and d.get("user_id"):
        try:
            from routes.notifications import _insert_notification
            from push_service import (send_push_to_user,
                                      build_generic_admin_alert_payload)
            title = ("📞 Tu mensajero no logra contactarte"
                     if itype == "no_responde"
                     else "📅 Tu entrega será reprogramada")
            body = (f"{cname}: {note}"
                    + (f" · Próximo intento: {next_attempt}"
                       if next_attempt else ""))
            await _insert_notification(
                recipient_user_id=d["user_id"], type="delivery_incident",
                title=title, message=body,
                data={"delivery_id": did, "incident_type": itype})
            push = build_generic_admin_alert_payload(
                title=title, body=body, url="/dashboard",
                tag=f"delivery-incident-{did}")
            await send_push_to_user(db, d["user_id"], push)
        except Exception as e:
            logger.error(f"incident client notify failed: {e}")
    try:
        from services.deliveries import publish_delivery_event
        await publish_delivery_event(did, d["status"],
                                     courier_ids=[me["user_id"]])
    except Exception:
        pass
    return _strip_courier_secret(
        await db.deliveries.find_one({"id": did}, {"_id": 0}))


@router.post("/admin/deliveries/{did}/incidents/{iid}/resolve")
async def admin_resolve_incident(did: str, iid: str, payload: dict,
                                 request: Request) -> Any:
    """El operador resuelve una incidencia con nota; si no quedan abiertas,
    la entrega deja de estar marcada."""
    actor = await require_permission(request, "deliveries")
    note = (payload.get("note") or "").strip()[:300]
    now = iso(now_utc())
    res = await db.deliveries.update_one(
        {"id": did, "incidents": {"$elemMatch": {"id": iid, "status": "open"}}},
        {"$set": {"incidents.$.status": "resolved",
                  "incidents.$.resolved_by": actor["user_id"],
                  "incidents.$.resolved_at": now,
                  "incidents.$.resolution_note": note,
                  "updated_at": now},
         "$push": {"timeline": {"status": "incident_resolved", "at": now,
                                "by": actor["user_id"],
                                "note": note or None}}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404,
                            detail="Incidencia no encontrada o ya resuelta.")
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    still_open = any(i.get("status") == "open"
                     for i in (d.get("incidents") or []))
    if not still_open:
        await db.deliveries.update_one(
            {"id": did}, {"$set": {"has_open_incident": False}})
        d["has_open_incident"] = False
    await log_action(db, actor, "delivery.incident_resolve", "delivery", did,
                     details={"incident_id": iid, "note": note})
    return d


# ------------------------------------------------------------------
# Mejora #1 auditoría — control de efectivo por mensajero
# ------------------------------------------------------------------

@router.get("/courier/cash")
async def courier_cash_view(request: Request) -> Any:
    """El mensajero ve su efectivo pendiente de rendir y sus últimos
    movimientos de caja."""
    me = await _require_courier(request)
    from services.courier_cash import cash_pending
    pending = await cash_pending(me["user_id"])
    events = await db.courier_cash_events.find(
        {"courier_id": me["user_id"]}, {"_id": 0},
    ).sort("at", -1).to_list(20)
    return {"pending": pending, "events": events}


@router.get("/admin/courier-cash/summary")
async def admin_courier_cash_summary(request: Request) -> Any:
    """Efectivo en tránsito por mensajero y moneda (pendiente de rendición)."""
    await require_permission(request, "deliveries")
    from services.courier_cash import cash_pending
    return {"couriers": await cash_pending()}


@router.get("/admin/courier-cash")
async def admin_courier_cash_events(request: Request,
                                    courier_id: Optional[str] = None) -> Any:
    await require_permission(request, "deliveries")
    q = {"courier_id": courier_id} if courier_id else {}
    return await db.courier_cash_events.find(
        q, {"_id": 0}).sort("at", -1).to_list(100)


@router.post("/admin/courier-cash")
async def admin_courier_cash_register(payload: dict,
                                      request: Request) -> Any:
    """El admin registra la entrega de caja al mensajero (`issued`) o la
    rendición recibida en caja (`returned`). Una diferencia se registra como
    incidencia con nota — jamás como ajuste silencioso."""
    actor = await require_permission(request, "deliveries")
    kind = payload.get("kind")
    if kind not in ("issued", "returned"):
        raise HTTPException(status_code=400,
                            detail="kind debe ser 'issued' o 'returned'")
    courier_id = (payload.get("courier_id") or "").strip()
    if not courier_id:
        raise HTTPException(status_code=400, detail="courier_id requerido")
    c = await db.users.find_one({"user_id": courier_id},
                                {"_id": 0, "name": 1, "email": 1})
    if not c:
        raise HTTPException(status_code=404, detail="Mensajero no encontrado")
    from services.courier_cash import record_cash_event
    discrepancy_note = (payload.get("discrepancy_note") or "").strip()
    ev = await record_cash_event(
        courier_id=courier_id,
        courier_name=c.get("name") or c.get("email") or "",
        kind=kind, currency=payload.get("currency"),
        amount=payload.get("amount"),
        delivery_id=(payload.get("delivery_id") or None),
        note=(payload.get("note") or ""),
        by=actor["user_id"], by_name=actor.get("name") or "",
        discrepancy=bool(discrepancy_note))
    if discrepancy_note:
        try:
            from admin_alerts import notify_all_admins
            await notify_all_admins(
                db,
                title="⚠️ Diferencia de efectivo en rendición",
                body=(f"Rendición de {c.get('name') or courier_id} "
                      f"({ev['amount']} {ev['currency']}) con diferencia: "
                      f"{discrepancy_note}"),
                url_path="/admin/deliveries")
        except Exception as e:
            logger.error(f"cash discrepancy notify failed: {e}")
    await log_action(db, actor, "courier.cash_event", "user", courier_id,
                     details={"kind": kind, "currency": ev["currency"],
                              "amount": ev["amount"],
                              "discrepancy": bool(discrepancy_note)})
    return ev


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
            # Mejora #2 — el PIN es del CLIENTE: se muestra en su seguimiento.
            "delivery_pin": d.get("delivery_pin"),
            "pin_verified": bool(d.get("pin_verified")),
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
                                courier_id: Optional[str] = None,
                                incident: Optional[str] = None) -> Any:
    await require_permission(request, "deliveries")
    q: dict = {}
    if status:
        q["status"] = status
    if courier_id:
        q["courier_id"] = courier_id
    if incident == "open":
        q["has_open_incident"] = True
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
    # MSG03 — una operación rechazada/cancelada no admite crear mensajería.
    if ref.get("status") in ("rejected", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=(f"La operación está {ref['status']} — no se puede crear "
                    "una entrega para ella."))
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
    # MSG02 — el índice único sobre active_key cierra atómicamente la ventana
    # buscar→insertar: dos creaciones simultáneas producen UN solo reparto.
    from pymongo.errors import DuplicateKeyError
    try:
        await db.deliveries.insert_one(dict(doc))
    except DuplicateKeyError:
        raise HTTPException(status_code=409,
                            detail="Ya existe una entrega para esta operación")
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
    # ME02 — reasignación condicionada al estado leído: no puede revivir
    # entregas canceladas/confirmadas que cambiaron entre lectura y escritura.
    # MSG08 — la ubicación GPS del mensajero anterior se INVALIDA al
    # reasignar: el nuevo mensajero no hereda coordenadas ajenas.
    res = await db.deliveries.update_one(
        {"id": did, "status": {"$in": ["available", "accepted"]}}, {
            "$set": {"status": "available",
                     "assigned_to_courier_id": courier_id,
                     "courier_id": None,
                     "courier_name": None,
                     "updated_at": now},
            "$unset": {"courier_location": ""},
            "$push": {"timeline": {"status": "available", "at": now,
                                   "by": actor["user_id"],
                                   "note": f"Reservada para {courier_display} — pendiente de aceptación"}},
        })
    if res.matched_count == 0:
        raise HTTPException(status_code=409,
                            detail="La entrega cambió de estado; recarga.")
    # MSG10 — el mensajero nuevo (y el anterior, si existía) ven el cambio
    # en vivo sin recargar el panel.
    try:
        from services.deliveries import publish_delivery_event
        await publish_delivery_event(
            did, "available",
            courier_ids=[courier_id, d.get("courier_id"),
                         d.get("assigned_to_courier_id")])
    except Exception:
        pass
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
                url="/dashboard/deliveries",
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
    # ME02 — cancelación condicionada: no puede pisar una confirmación (o el
    # pago de la comisión) que ganó la carrera entre lectura y escritura.
    res = await db.deliveries.update_one(
        {"id": did, "status": d["status"], "payout_credited": {"$ne": True}}, {
            "$set": {"status": "cancelled", "updated_at": now},
            "$unset": {"active_key": ""},
            "$push": {"timeline": {"status": "cancelled", "at": now,
                                   "by": actor["user_id"],
                                   "note": (payload.get("note") or "")[:200]}},
        })
    if res.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="La entrega cambió de estado (¿confirmada?); recarga.")
    # MSG10 — el panel del mensajero ve la cancelación en vivo.
    try:
        from services.deliveries import publish_delivery_event
        await publish_delivery_event(
            did, "cancelled",
            courier_ids=None if d["status"] == "available"
            else [d.get("courier_id"), d.get("assigned_to_courier_id")])
    except Exception:
        pass
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
