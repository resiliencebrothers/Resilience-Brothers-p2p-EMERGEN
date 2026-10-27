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
import re
import uuid
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Response

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
    # STAFF-04 (auditoría 26-10-2026) — ejecutar entregas como mensajero exige
    # la marca is_courier. Pertenecer a staff (admin/employee) ya NO basta por
    # sí solo: si a alguien se le retira is_courier, pierde el acceso de
    # mensajero de inmediato.
    if not user.get("is_courier"):
        raise HTTPException(status_code=403, detail="Solo mensajeros autorizados")
    # STAFF-05-R (residual de seguridad) — la suspensión debe alcanzar también
    # el circuito de mensajero. `_require_courier` solo pasa por `require_user`,
    # que NO comprueba `account_status`; por eso un mensajero `blocked` o
    # `under_review` seguía listando y tomando repartos aunque las rutas admin
    # ya lo bloqueaban (`_enforce_staff_active`). Aquí se exige cuenta ACTIVA al
    # propio mensajero —sea staff o cliente— sin depender de que el admin retire
    # is_courier por separado. Como SOLO los usuarios con is_courier llegan a
    # este guard, el onboarding normal de clientes/Empresa (que nunca son
    # mensajeros) no se ve afectado. account_status ausente = active (compat).
    if (user.get("account_status") or "active") != "active":
        raise HTTPException(
            status_code=403,
            detail=("Tu cuenta está suspendida o en revisión. "
                    "No puedes operar como mensajero. Contacta a un administrador."),
        )
    return user


def _strip_courier_secret(doc: Any) -> Any:
    """Mejora #2 — el PIN de entrega es SOLO del cliente: jamás viaja en las
    respuestas del mensajero. Se expone `pin_required` para que la UI sepa
    que debe pedirlo al confirmar la entrega."""
    if isinstance(doc, dict):
        doc["pin_required"] = bool(doc.get("delivery_pin")) \
            and not doc.get("pin_verified")
        doc.pop("delivery_pin", None)
    return doc


def _is_reserved(d: dict) -> bool:
    """MEN-02 — una entrega `available` RESERVADA para un mensajero concreto
    (tiene `assigned_to_courier_id`) y ya validada contra su origen. Es el
    MISMO criterio que usa `find_attention_items` y la cola del mensajero."""
    return bool(
        d.get("status") == "available"
        and (d.get("assigned_to_courier_id") or "")
        and not d.get("needs_origin_check"))


def _derive_display_status(d: dict) -> str:
    """MEN-02 — estado DERIVADO para la UI del admin: una entrega reservada se
    muestra como `assigned` (Asignada — pendiente de aceptación). NO cambia el
    `status` almacenado: el flujo aceptar/rechazar sigue operando sobre
    `available`, igual que antes."""
    if _is_reserved(d):
        return "assigned"
    return d.get("status") or ""


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
    # N05 — SIN tope: las 51 reservas dirigidas aparecen las 51.
    reserved_docs = [d async for d in db.deliveries.find(
        {"status": "available", "assigned_to_courier_id": uid,
         "needs_origin_check": {"$ne": True}},
        {"_id": 0},
    ).sort("created_at", -1)]
    open_docs = await db.deliveries.find(
        {"status": "available",
         "needs_origin_check": {"$ne": True},
         "$or": [{"assigned_to_courier_id": {"$in": [None, ""]}},
                 {"assigned_to_courier_id": {"$exists": False}}]},
        {"_id": 0},
    ).sort("created_at", 1).to_list(50)  # Mejora #4 — atrasados primero
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
    # N01 — se suma el importe CONGELADO al pagar cuando existe.
    agg = await db.deliveries.aggregate([
        {"$match": {"courier_id": uid, "status": "confirmed"}},
        {"$group": {"_id": None,
                    "earned": {"$sum": {"$ifNull": [
                        "$courier_share_paid_usdt", "$courier_share_usdt"]}},
                    "count": {"$sum": 1}}},
    ]).to_list(1)
    earned = float((agg[0] if agg else {}).get("earned") or 0)
    completed_count = int((agg[0] if agg else {}).get("count") or 0)
    pending_agg = await db.deliveries.aggregate([
        {"$match": {"courier_id": uid, "status": "delivered"}},
        {"$group": {"_id": None, "s": {"$sum": {"$ifNull": [
            "$courier_share_paid_usdt", "$courier_share_usdt"]}}}},
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


@router.get("/courier/deliveries/history")
async def courier_delivery_history(request: Request, response: Response,
                                    skip: int = 0, limit: int = 50) -> Any:
    """MEN-04 — historial COMPLETO del mensajero (completadas + canceladas),
    con paginación de servidor. El panel ya no se limita a las últimas 50."""
    me = await _require_courier(request)
    q = {"courier_id": me["user_id"],
         "status": {"$in": ["confirmed", "cancelled"]}}
    skip = max(0, skip)
    limit = max(1, min(limit, 100))
    total = await db.deliveries.count_documents(q)
    response.headers["X-Total-Count"] = str(total)
    rows = await db.deliveries.find(q, {"_id": 0}).sort(
        "updated_at", -1).skip(skip).limit(limit).to_list(limit)
    for d in rows:
        _strip_courier_secret(d)
    return rows



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
    # N05 — Confirmadas del día por AGREGACIÓN completa (sin tope de lista:
    # 2.001 entregas cuentan 2.001). N01 — importes CONGELADOS al pagar.
    groups = await db.deliveries.aggregate([
        {"$match": {"status": "confirmed",
                    "updated_at": {"$gte": day, "$lt": next_day}}},
        {"$group": {
            "_id": {"$ifNull": ["$courier_id", "—"]},
            "courier_name": {"$last": {"$ifNull": ["$courier_name", "—"]}},
            "count": {"$sum": 1},
            "fees": {"$sum": {"$ifNull": ["$fee_paid_usdt", "$fee_usdt"]}},
            "earned": {"$sum": {"$ifNull": ["$courier_share_paid_usdt",
                                            "$courier_share_usdt"]}},
            "platform": {"$sum": {"$ifNull": ["$platform_share_paid_usdt",
                                              "$platform_share_usdt"]}},
        }},
    ]).to_list(5000)
    active = await db.deliveries.aggregate([
        {"$match": {"status": {"$in": ["available", "accepted", "on_the_way",
                                       "arrived", "delivered"]}}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]).to_list(10)
    active_counts = {r["_id"]: r["n"] for r in active}
    # MEN-02 — "disponible" se reparte en LIBRES vs RESERVADAS (asignadas,
    # pendientes de aceptación). Mismo criterio que la cola y el listado.
    free_count = await db.deliveries.count_documents({
        "status": "available", "needs_origin_check": {"$ne": True},
        "$or": [{"assigned_to_courier_id": {"$in": [None, ""]}},
                {"assigned_to_courier_id": {"$exists": False}}]})
    assigned_count = await db.deliveries.count_documents({
        "status": "available", "needs_origin_check": {"$ne": True},
        "assigned_to_courier_id": {"$nin": [None, ""]}})
    rows = sorted(
        ({"courier_name": (g.get("courier_name") or "—").split(" ")[0],
          "count": int(g.get("count") or 0),
          "earned_usdt": round(float(g.get("earned") or 0), 2)}
         for g in groups), key=lambda r: -float(r["earned_usdt"]))
    return {
        "date": day,
        "confirmed_count": sum(int(g.get("count") or 0) for g in groups),
        "total_fees_usdt": round(sum(float(g.get("fees") or 0)
                                     for g in groups), 2),
        "courier_earned_usdt": round(sum(float(g.get("earned") or 0)
                                         for g in groups), 2),
        "platform_earned_usdt": round(sum(float(g.get("platform") or 0)
                                          for g in groups), 2),
        "active_count": sum(active_counts.get(s, 0) for s in
                            ("accepted", "on_the_way", "arrived")),
        "available_count": free_count,
        "assigned_count": assigned_count,
        "delivered_pending_count": active_counts.get("delivered", 0),
        "by_courier": rows,
    }


@router.get("/admin/deliveries/metrics")
async def admin_deliveries_metrics(request: Request,
                                   date_from: Optional[str] = None,
                                   date_to: Optional[str] = None,
                                   courier_id: Optional[str] = None) -> Any:
    """Mejora #8 (Fase C) — métricas operativas de mensajería: tiempos de
    asignación→aceptación→entrega, % de incidencias, trabajos sin rendir y
    costo neto por servicio. Filtros por rango de fechas y mensajero."""
    await require_permission(request, "deliveries")
    from datetime import datetime, timedelta
    q: dict = {}
    if date_from:
        q.setdefault("created_at", {})["$gte"] = date_from[:10]
    if date_to:
        try:
            nxt = (datetime.strptime(date_to[:10], "%Y-%m-%d")
                   + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400,
                                detail="fecha inválida (YYYY-MM-DD)")
        q.setdefault("created_at", {})["$lt"] = nxt
    if courier_id:
        q["courier_id"] = courier_id
    # MS04 — los agregados se calculan sobre TODOS los documentos del filtro
    # (cursor completo, sin tope): con 2.001 confirmaciones la pestaña
    # informa 2.001, igual que el resumen diario.
    cursor = db.deliveries.find(q, {
        "_id": 0, "id": 1, "status": 1, "created_at": 1, "timeline": 1,
        "incidents": 1, "fee_usdt": 1, "courier_share_usdt": 1,
        "platform_share_usdt": 1, "payout_credited": 1,
        "fee_paid_usdt": 1, "courier_share_paid_usdt": 1,
        "platform_share_paid_usdt": 1,
        "settlement_pending": 1}).batch_size(1000)

    def _first_at(tl: list, status: str) -> Optional[str]:
        for e in (tl or []):
            if e.get("status") == status:
                return e.get("at")
        return None

    def _minutes(a: Any, b: Any) -> Optional[float]:
        try:
            da = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
            db_ = datetime.fromisoformat(str(b).replace("Z", "+00:00"))
            return max(0.0, (db_ - da).total_seconds() / 60.0)
        except (ValueError, TypeError):
            return None

    accept_mins: list = []
    deliver_mins: list = []
    total_mins: list = []
    with_incidents = 0
    unsettled = 0
    sync_pending = 0
    cancelled = 0
    finished = 0
    fees = courier_total = platform_total = 0.0
    total = 0
    async for d in cursor:
        total += 1
        tl = d.get("timeline") or []
        accepted_at = _first_at(tl, "accepted")
        delivered_at = _first_at(tl, "delivered")
        if accepted_at:
            m = _minutes(d.get("created_at"), accepted_at)
            if m is not None:
                accept_mins.append(m)
        if accepted_at and delivered_at:
            m = _minutes(accepted_at, delivered_at)
            if m is not None:
                deliver_mins.append(m)
        if delivered_at:
            m = _minutes(d.get("created_at"), delivered_at)
            if m is not None:
                total_mins.append(m)
        if d.get("incidents"):
            with_incidents += 1
        if d.get("status") == "delivered" and not d.get("payout_credited"):
            unsettled += 1
        if d.get("settlement_pending"):
            sync_pending += 1
        if d.get("status") == "cancelled":
            cancelled += 1
        if d.get("status") == "confirmed":
            finished += 1
            # N01 — importes CONGELADOS al pagar cuando existen.
            fees += float(d["fee_paid_usdt"]
                          if d.get("fee_paid_usdt") is not None
                          else d.get("fee_usdt") or 0)
            courier_total += float(d["courier_share_paid_usdt"]
                                   if d.get("courier_share_paid_usdt") is not None
                                   else d.get("courier_share_usdt") or 0)
            platform_total += float(d["platform_share_paid_usdt"]
                                    if d.get("platform_share_paid_usdt") is not None
                                    else d.get("platform_share_usdt") or 0)

    def _avg(xs: list) -> Optional[float]:
        return round(sum(xs) / len(xs), 1) if xs else None

    return {
        "total": total,
        "confirmed": finished,
        "cancelled": cancelled,
        "avg_accept_min": _avg(accept_mins),
        "avg_deliver_min": _avg(deliver_mins),
        "avg_total_min": _avg(total_mins),
        "incidents_count": with_incidents,
        "incidents_pct": (round(with_incidents * 100.0 / total, 1)
                          if total else 0.0),
        "unsettled_count": unsettled,
        "sync_pending_count": sync_pending,
        "fees_usdt": round(fees, 2),
        "courier_paid_usdt": round(courier_total, 2),
        "platform_net_usdt": round(platform_total, 2),
        "avg_fee_usdt": round(fees / finished, 2) if finished else None,
    }


@router.post("/courier/deliveries/{did}/claim")
async def claim_delivery(did: str, request: Request,
                         payload: Optional[dict] = None) -> Any:
    me = await _require_courier(request)
    now = iso(now_utc())
    # ABA (A08) — aceptar se ata a la IDENTIDAD de la asignación mostrada.
    uid = (payload or {}).get("assignment_uid")
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
            try:
                await handle_origin_rejected(
                    existing["kind"], existing["ref_id"],
                    note=f"origen {ref.get('status')}")
            except RuntimeError:
                pass  # estado en disputa: el healer converge; el 409 informa
            raise HTTPException(
                status_code=409,
                detail=("La operación de origen fue rechazada/cancelada — "
                        "esta entrega ya no está disponible."))
    # iter208/ME02/ABA — la reserva del admin se respeta DENTRO del filtro
    # atómico. Si se envía `assignment_uid`, aceptar casa SOLO esa reserva
    # concreta (su ciclo vigente); así un «Aceptar» de un ciclo anterior no
    # revive. Sin uid: toma de un trabajo realmente libre o reserva heredada.
    if uid:
        accept_or = [{"assigned_to_courier_id": me["user_id"],
                      "assignment_uid": uid}]
    else:
        accept_or = [{"assigned_to_courier_id": {"$in": [None, ""]}},
                     {"assigned_to_courier_id": me["user_id"],
                      "assignment_uid": {"$exists": False}}]
    # M01-B — toda ACEPTACIÓN recibe una identidad de ciclo DISTINGUIBLE.
    # Si se acepta una reserva vigente (llega `uid`) conservamos SU uid; si es
    # un trabajo realmente libre —o una reserva heredada SIN uid— generamos uno
    # NUEVO aquí. Así dos aceptaciones sucesivas jamás comparten la "ausencia de
    # uid" como identidad: una reasignación administrativa atrasada que examinó
    # un ciclo anterior no puede confundirlo con un ciclo aceptado posterior.
    cycle_uid = uid or uuid.uuid4().hex
    updated = await db.deliveries.find_one_and_update(
        {"id": did, "status": "available",
         # MV02 — un reparto pendiente de validar contra su origen NO es
         # aceptable: podría llevar una tarifa ya anulada.
         "needs_origin_check": {"$ne": True},
         # M01 — protección ante una petición atrasada: si el CLIENTE está
         # cancelando su operación de origen (DR09 marca `origin_cancel_intent`
         # en la entrega), un «Aceptar» que llega tarde NO debe ganar. El filtro
         # atómico lo excluye; el sello 'delivered' ya estaba protegido, pero la
         # aceptación también debe perder aquí para no tomar algo que se anula.
         "origin_cancel_intent": {"$exists": False},
         "$or": accept_or},
        {"$set": {"status": "accepted", "courier_id": me["user_id"],
                  "courier_name": me.get("name") or me.get("email"),
                  "assigned_to_courier_id": None,
                  "assigned_to_courier_name": None,
                  # M01-B — sella SIEMPRE el ciclo aceptado (ver arriba): una
                  # entrega aceptada mantiene una identidad de ciclo única para
                  # que una reasignación administrativa atrasada no pueda actuar
                  # sobre un ciclo aceptado posterior creyendo que es el que
                  # examinó. Incluye trabajos libres y reservas heredadas.
                  "assignment_uid": cycle_uid,
                  "updated_at": now},
         "$push": {"timeline": {"status": "accepted", "at": now,
                                "by": me["user_id"]}}},
        projection={"_id": 0},
        return_document=True,
    )
    if not updated:
        fresh = await db.deliveries.find_one(
            {"id": did}, {"_id": 0, "status": 1, "assigned_to_courier_id": 1,
                          "needs_origin_check": 1, "origin_cancel_intent": 1,
                          "assignment_uid": 1})
        if (fresh or {}).get("needs_origin_check"):
            raise HTTPException(
                status_code=409,
                detail=("Esta entrega está pendiente de validación — "
                        "inténtalo de nuevo en unos segundos."))
        if (fresh or {}).get("origin_cancel_intent") \
                and (fresh or {}).get("status") not in ("delivered",
                                                        "confirmed"):
            raise HTTPException(
                status_code=409,
                detail=("El cliente está cancelando esta operación — no "
                        "puedes aceptarla ahora. Si persiste, contacta a la "
                        "administración."))
        # ABA — aceptaste una reserva que ya no es la vigente (ciclo nuevo).
        if uid and (fresh or {}).get("status") == "available" \
                and (fresh or {}).get("assignment_uid") != uid:
            raise HTTPException(
                status_code=409,
                detail=("La asignación cambió — recarga tu panel y vuelve a "
                        "intentarlo."))
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
    # MSG06 + ABA (A08) — la liberación exige que la reserva LEÍDA siga vigente:
    # un rechazo atrasado jamás borra una reserva posterior, ni de OTRO mensajero
    # ni del MISMO en un ciclo nuevo (A -> B -> A). El filtro ata el rechazo a la
    # IDENTIDAD de la asignación mostrada (`assignment_uid`); si el cliente no
    # envía uid (reserva heredada sin uid) solo casa reservas sin uid.
    uid = payload.get("assignment_uid")
    # MEN23 — `assignment_uid` debe ser cadena o null; nunca un operador.
    if uid is not None:
        _require_scalar_str(uid, "assignment_uid")
    filt: Dict[str, Any] = {"id": did, "status": "available",
                            "assigned_to_courier_id": me["user_id"],
                            "assignment_uid": uid if uid else {"$exists": False}}
    res = await db.deliveries.update_one(filt, {
        "$set": {"assigned_to_courier_id": None,
                 "assigned_to_courier_name": None, "updated_at": now},
        "$unset": {"assignment_uid": ""},
        "$push": {"timeline": {
            "status": "available", "at": now, "by": me["user_id"],
            "note": f"Reserva rechazada por {courier_name}: {reason}"}},
    })
    if res.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail=("La reserva cambió (ya no está asignada a ti, cambió de "
                    "estado o fue reasignada en un ciclo nuevo); recarga tu "
                    "panel."))
    try:
        from services.deliveries import publish_delivery_event
        await publish_delivery_event(did, "available")
    except Exception:
        pass
    # Alertar a admins y EMPLEADOS AUTORIZADOS a despachar (MEN-05): el aviso
    # se dirige a quien puede reasignar/liberar, usando la FUENTE REAL de
    # permisos (`allowed_permissions`) y el criterio de despacho de MEN-01
    # (`deliveries_assign`), no el campo inexistente `permissions`.
    try:
        from routes.notifications import _insert_notification
        from services.permissions import _has_permission
        from push_service import (
            send_push_to_user, build_generic_admin_alert_payload,
        )
        title = "🛵 Mensajero rechazó una reserva"
        body = (f"{courier_name} rechazó la entrega de {d.get('client_name','')} "
                f"({d.get('amount_label','')}). Motivo: {reason}")
        recipients = await db.users.find(
            {"$or": [{"role": "admin"}, {"role": "employee"}]},
            {"_id": 0, "user_id": 1, "allowed_permissions": 1, "role": 1},
        ).to_list(200)
        payload_push = build_generic_admin_alert_payload(
            title=title, body=body,
            url="/admin/deliveries",
            tag=f"delivery-rejected-{did}",
        )
        for a in recipients:
            if not _has_permission(a, "deliveries_assign"):
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
    # N03 — el origen debe seguir operable en CADA avance (no solo al
    # aceptar): una operación rechazada/cancelada no admite más movimiento.
    from services.deliveries import (REF_COLLS, TERMINAL_REF_STATUSES,
                                     handle_origin_rejected)
    ref_coll = REF_COLLS.get(d.get("kind"))
    if ref_coll and d.get("ref_id"):
        ref = await db[ref_coll].find_one({"id": d["ref_id"]},
                                          {"_id": 0, "status": 1})
        if ref and ref.get("status") in TERMINAL_REF_STATUSES:
            try:
                await handle_origin_rejected(d["kind"], d["ref_id"],
                                             note=f"origen {ref.get('status')}")
            except RuntimeError:
                pass  # estado en disputa: el healer converge; el 409 informa
            raise HTTPException(
                status_code=409,
                detail=("La operación de origen fue rechazada/cancelada — "
                        "esta entrega quedó cancelada y no admite avances. "
                        "Contacta a la administración."))
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
    # N04 — la intención de registrar el efectivo viaja EN el mismo update
    # que sella el movimiento físico: si el insert del evento falla, la
    # tarea queda viva y el healer la completa (idempotente por op_key).
    if new_status == "delivered" and d.get("kind") in ("deposit", "withdrawal"):
        extra_set["cash_event_pending"] = {"at": now,
                                           "actor_id": me["user_id"]}
    # MSG01 — la escritura exige que SIGAN vigentes el estado y el repartidor
    # comprobados: una petición atrasada (cancelación/reasignación en medio)
    # pierde con 409 y no revive ni altera la entrega.
    guard: Dict[str, Any] = {"id": did, "status": d["status"],
                             "courier_id": me["user_id"]}
    if new_status == "delivered":
        # DR09 — el sello del movimiento físico pierde ante una cancelación
        # del origen en curso: la decisión durable vive en ESTE documento.
        guard["origin_cancel_intent"] = {"$exists": False}
    res = await db.deliveries.update_one(
        guard, {
            "$set": {"status": new_status, "updated_at": now, **extra_set},
            "$push": {"timeline": {"status": new_status, "at": now,
                                   "by": me["user_id"], "note": tl_note}},
        })
    if res.matched_count == 0:
        fresh = await db.deliveries.find_one(
            {"id": did}, {"_id": 0, "origin_cancel_intent": 1})
        if new_status == "delivered" and (fresh or {}).get("origin_cancel_intent"):
            raise HTTPException(
                status_code=409,
                detail=("El cliente está cancelando esta operación — la "
                        "entrega no puede sellarse. Contacta a la "
                        "administración antes de entregar el dinero."))
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
        # Mejora #1 — registro del efectivo en tránsito: la tarea durable ya
        # quedó sellada con la transición; un fallo aquí NO rompe la
        # respuesta (el healer completa con el mismo op_key).
        from services.courier_cash import auto_events_for_delivered
        try:
            await auto_events_for_delivered({**d, "status": "delivered"},
                                            me["user_id"])
        except Exception as e:
            logger.error(f"registro de efectivo pendiente (lo completa el "
                         f"healer): {e}")
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
    # Mejora #5 — presencia GPS del mensajero visible para la administración.
    await db.users.update_one({"user_id": me["user_id"]},
                              {"$set": {"courier_last_gps_at": now}})
    return {"updated": r.modified_count, "at": now}


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
    """Efectivo en tránsito por mensajero y moneda (pendiente de rendición),
    con antigüedad del pendiente para alertar rendiciones atrasadas."""
    await require_permission(request, "deliveries")
    from services.courier_cash import cash_pending
    return {"couriers": await cash_pending()}


@router.get("/admin/courier-cash/reconciliation")
async def admin_courier_cash_reconciliation(request: Request) -> Any:
    """Conciliación por moneda: caja física, tránsito (custodia confirmada),
    recogido pendiente de confirmar y total."""
    await require_permission(request, "deliveries")
    from services.courier_cash import reconciliation_by_currency
    return {"rows": await reconciliation_by_currency()}


@router.get("/admin/courier-cash/incomplete-transfers")
async def admin_courier_cash_incomplete(request: Request) -> Any:
    """Auditoría de traslados: reintentos de efectivo a medias (pendientes de
    confirmar, abortados, o confirmados sin evento) para revisión del operador."""
    await require_permission(request, "deliveries")
    from services.courier_cash import incomplete_cash_transfers
    return {"rows": await incomplete_cash_transfers()}


def _cash_events_query(courier_id: Optional[str], currency: Optional[str],
                       kind: Optional[str], start: Optional[str],
                       end: Optional[str]) -> dict:
    q: dict = {}
    if courier_id:
        q["courier_id"] = courier_id
    if currency:
        q["currency"] = (currency or "").strip().upper()
    if kind:
        q["kind"] = kind
    if start or end:
        at: dict = {}
        if start:
            at["$gte"] = start
        if end:
            at["$lte"] = end + "T23:59:59.999999+00:00"
        q["at"] = at
    return q


@router.get("/admin/courier-cash")
async def admin_courier_cash_events(request: Request,
                                    courier_id: Optional[str] = None,
                                    currency: Optional[str] = None,
                                    kind: Optional[str] = None,
                                    start: Optional[str] = None,
                                    end: Optional[str] = None,
                                    skip: int = 0,
                                    limit: int = 25) -> Any:
    """Historial de movimientos de efectivo, paginado y filtrable."""
    await require_permission(request, "deliveries")
    q = _cash_events_query(courier_id, currency, kind, start, end)
    limit = max(1, min(int(limit or 25), 200))
    skip = max(0, int(skip or 0))
    total = await db.courier_cash_events.count_documents(q)
    items = await db.courier_cash_events.find(q, {"_id": 0}).sort(
        "at", -1).skip(skip).limit(limit).to_list(limit)
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/admin/courier-cash/export.csv")
async def admin_courier_cash_export(request: Request,
                                    courier_id: Optional[str] = None,
                                    currency: Optional[str] = None,
                                    kind: Optional[str] = None,
                                    start: Optional[str] = None,
                                    end: Optional[str] = None) -> Any:
    """Exporta a CSV los movimientos de efectivo filtrados."""
    await require_permission(request, "deliveries")
    import csv
    import io
    from fastapi.responses import StreamingResponse
    q = _cash_events_query(courier_id, currency, kind, start, end)
    rows = await db.courier_cash_events.find(q, {"_id": 0}).sort(
        "at", -1).to_list(20000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Fecha", "Mensajero", "Tipo", "Moneda", "Importe",
                "Diferencia", "Nota", "Nota diferencia", "Desglose billetes",
                "Registrado por"])
    for r in rows:
        denoms = r.get("denominations") or {}
        denom_str = "; ".join(f"{k}x{v}" for k, v in denoms.items())
        w.writerow([r.get("at", ""), r.get("courier_name") or r.get("courier_id") or "",
                    r.get("kind", ""), r.get("currency", ""), r.get("amount", ""),
                    "sí" if r.get("discrepancy") else "",
                    r.get("note", ""), r.get("discrepancy_note", ""),
                    denom_str, r.get("by_name") or r.get("by") or ""])
    buf.seek(0)
    fname = f"efectivo_mensajeria_{(start or 'inicio')}_{(end or 'hoy')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/admin/courier-cash/options")
async def admin_courier_cash_options(request: Request) -> Any:
    """EF04 — monedas de efectivo físicas y cuentas de caja disponibles por
    moneda para el formulario (excluye cuentas de custodia de mensajeros)."""
    await require_permission(request, "deliveries")
    from services.courier_cash import physical_cash_currencies
    from services.denominations import get_cash_denominations
    currencies = sorted(await physical_cash_currencies())
    denoms = await get_cash_denominations()
    accounts: dict = {}
    for code in currencies:
        rows = []
        async for fa in db.fund_accounts.find(
            {"currency": code, "method": "cash", "is_active": True,
             "courier_custody_id": {"$exists": False},
             "merged_into": {"$exists": False}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            rows.append({"id": fa["id"], "label": fa.get("name") or fa["id"]})
        accounts[code] = rows
    return {"currencies": currencies, "accounts": accounts,
            "denominations": {c: denoms.get(c, []) for c in currencies}}


@router.post("/admin/courier-cash")
async def admin_courier_cash_register(payload: dict,
                                      request: Request) -> Any:
    """El admin registra la entrega de caja al mensajero (`issued`) o la
    rendición recibida en caja (`returned`) como TRASLADO DE CUSTODIA entre la
    cuenta de caja elegida y la custodia del mensajero (EF01). Valida
    disponibilidad (bloquea si no alcanza, EF02) e idempotencia (EF03). Una
    diferencia se registra como incidencia con nota — jamás ajuste silencioso."""
    actor = await require_permission(request, "deliveries")
    kind = payload.get("kind")
    if kind not in ("issued", "returned"):
        raise HTTPException(status_code=400,
                            detail="kind debe ser 'issued' o 'returned'")
    courier_id = (payload.get("courier_id") or "").strip()
    if not courier_id:
        raise HTTPException(status_code=400, detail="courier_id requerido")
    account_id = (payload.get("account_id") or "").strip()
    if not account_id:
        raise HTTPException(status_code=400,
                            detail="Elige la cuenta de caja de origen/destino")
    c = await db.users.find_one({"user_id": courier_id},
                                {"_id": 0, "name": 1, "email": 1, "role": 1,
                                 "is_courier": 1})
    if not c:
        raise HTTPException(status_code=404, detail="Mensajero no encontrado")
    # EC03 — política UNIFICADA con _require_courier (STAFF-04/05-R): la custodia
    # de efectivo pertenece a un MENSAJERO HABILITADO (is_courier). Pertenecer al
    # staff (admin/employee) NO basta: si se le retiró is_courier, ya no se le
    # puede emitir ni recibir efectivo de custodia, igual que pierde el panel de
    # mensajero. Así no se emite efectivo a quien perdió la habilitación aunque
    # conserve rol de personal.
    if not c.get("is_courier"):
        raise HTTPException(status_code=400,
                            detail="Ese usuario no es un mensajero habilitado")
    courier_name = c.get("name") or c.get("email") or ""
    discrepancy_note = (payload.get("discrepancy_note") or "").strip()
    from services.courier_cash import issue_or_return_cash
    result = await issue_or_return_cash(
        courier_id=courier_id, courier_name=courier_name, kind=kind,
        currency=str(payload.get("currency") or ""),
        amount=payload.get("amount"), account_id=account_id,
        note=(payload.get("note") or ""), discrepancy_note=discrepancy_note,
        denominations=(payload.get("denominations") or None),
        actor_id=actor["user_id"], actor_name=actor.get("name") or "",
        op_key=(payload.get("operation_id") or None))
    ev = result["event"]
    if not ev:
        raise HTTPException(status_code=500,
                            detail="No se pudo registrar el evento")
    if discrepancy_note:
        try:
            from admin_alerts import notify_all_admins
            await notify_all_admins(
                db,
                title="⚠️ Diferencia de efectivo en rendición",
                body=(f"Rendición de {courier_name or courier_id} "
                      f"({ev['amount']} {ev['currency']}) con diferencia: "
                      f"{discrepancy_note}"),
                url_path="/admin/deliveries")
        except Exception as e:
            logger.error(f"cash discrepancy notify failed: {e}")
    await log_action(db, actor, "courier.cash_event", "user", courier_id,
                     details={"kind": kind, "currency": ev["currency"],
                              "amount": ev["amount"],
                              "account_id": account_id,
                              "transfer_id": result["transfer"]["id"],
                              "discrepancy": bool(discrepancy_note)})
    return ev


@router.get("/admin/courier-cash/arqueo/expected")
async def admin_courier_arqueo_expected(request: Request, courier_id: str,
                                        currency: str) -> Any:
    """Arqueo — composición esperada de billetes y pendiente del mensajero,
    para contrastar contra el conteo físico."""
    await require_permission(request, "deliveries")
    if not courier_id or not currency:
        raise HTTPException(status_code=400,
                            detail="courier_id y currency requeridos")
    from services.courier_cash import courier_denomination_expectation
    return await courier_denomination_expectation(courier_id, currency)


@router.post("/admin/courier-cash/arqueo")
async def admin_courier_arqueo_create(payload: dict, request: Request) -> Any:
    """Registra un arqueo físico: cruza el conteo real de billetes contra el
    desglose esperado para detectar faltantes/sobrantes por denominación. No
    ajusta saldos; si hay diferencia, avisa a los admins."""
    actor = await require_permission(request, "deliveries")
    courier_id = (payload.get("courier_id") or "").strip()
    currency = (payload.get("currency") or "").strip()
    if not courier_id or not currency:
        raise HTTPException(status_code=400,
                            detail="courier_id y currency requeridos")
    counted = payload.get("counted") or {}
    if not isinstance(counted, dict):
        raise HTTPException(status_code=400, detail="counted inválido")
    c = await db.users.find_one({"user_id": courier_id},
                                {"_id": 0, "name": 1, "email": 1})
    if not c:
        raise HTTPException(status_code=404, detail="Mensajero no encontrado")
    courier_name = c.get("name") or c.get("email") or ""
    from services.courier_cash import record_courier_arqueo
    doc = await record_courier_arqueo(
        courier_id=courier_id, courier_name=courier_name, currency=currency,
        counted=counted, note=(payload.get("note") or ""),
        by=actor["user_id"], by_name=actor.get("name") or "")
    if doc["total_diff"] != 0 or doc["pending_diff"] != 0:
        try:
            from admin_alerts import notify_all_admins
            await notify_all_admins(
                db,
                title="⚠️ Diferencia en arqueo de efectivo de mensajero",
                body=(f"Arqueo de {courier_name} ({doc['currency']}): contado "
                      f"{doc['counted_total']}, esperado {doc['expected_total']}"
                      f", pendiente {doc['pending']}. Diferencia vs pendiente: "
                      f"{doc['pending_diff']}."),
                url_path="/admin/deliveries")
        except Exception as e:
            logger.error(f"arqueo discrepancy notify failed: {e}")
    await log_action(db, actor, "courier.arqueo", "user", courier_id,
                     details={"currency": doc["currency"],
                              "counted_total": doc["counted_total"],
                              "pending_diff": doc["pending_diff"],
                              "total_diff": doc["total_diff"]})
    return doc


@router.get("/admin/courier-cash/arqueo/history")
async def admin_courier_arqueo_history(request: Request,
                                       courier_id: Optional[str] = None,
                                       currency: Optional[str] = None,
                                       limit: int = 20) -> Any:
    """Historial de arqueos físicos (auditoría)."""
    await require_permission(request, "deliveries")
    q: dict = {}
    if courier_id:
        q["courier_id"] = courier_id
    if currency:
        q["currency"] = (currency or "").strip().upper()
    limit = max(1, min(int(limit or 20), 100))
    items = await db.courier_cash_arqueos.find(q, {"_id": 0}).sort(
        "at", -1).limit(limit).to_list(limit)
    return {"items": items}


@router.get("/admin/courier-cash/arqueo/export.csv")
async def admin_courier_arqueo_export(request: Request,
                                      courier_id: Optional[str] = None,
                                      currency: Optional[str] = None) -> Any:
    """Exporta a CSV el historial de arqueos físicos para auditoría contable."""
    await require_permission(request, "deliveries")
    import csv
    import io
    from fastapi.responses import StreamingResponse
    q: dict = {}
    if courier_id:
        q["courier_id"] = courier_id
    if currency:
        q["currency"] = (currency or "").strip().upper()
    rows = await db.courier_cash_arqueos.find(q, {"_id": 0}).sort(
        "at", -1).to_list(20000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Fecha", "Mensajero", "Moneda", "Total contado",
                "Total esperado", "Pendiente", "Diferencia vs esperado",
                "Diferencia vs pendiente", "Diferencias por billete",
                "Nota", "Registrado por"])
    for r in rows:
        diffs = r.get("diff_by_denom") or {}
        diff_str = "; ".join(f"{k}:{'+' if v > 0 else ''}{v}"
                             for k, v in diffs.items())
        w.writerow([r.get("at", ""),
                    r.get("courier_name") or r.get("courier_id") or "",
                    r.get("currency", ""), r.get("counted_total", ""),
                    r.get("expected_total", ""), r.get("pending", ""),
                    r.get("total_diff", ""), r.get("pending_diff", ""),
                    diff_str, r.get("note", ""),
                    r.get("by_name") or r.get("by") or ""])
    buf.seek(0)
    fname = f"arqueos_{(courier_id or 'todos')}_{(currency or 'todas')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


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

@router.get("/admin/deliveries/attention")
async def admin_deliveries_attention(request: Request) -> Any:
    """Mejora #4 — reservas sin respuesta y trabajos detenidos, para el
    banner de atención del operador."""
    await require_permission(request, "deliveries")
    from services.deliveries import find_attention_items
    return await find_attention_items()


@router.put("/admin/deliveries/sla-hours")
async def admin_set_sla_hours(payload: dict, request: Request) -> Any:
    """Protocolo SLA — define el máximo de horas que una mensajería puede
    tardar antes de escalarse para cancelación y devolución al origen."""
    actor = await require_permission(request, "deliveries")
    raw = payload.get("hours")
    if raw is None:
        raise HTTPException(status_code=400, detail="Horas inválidas")
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Horas inválidas")
    if not (1 <= hours <= 720):
        raise HTTPException(status_code=400,
                            detail="Las horas deben estar entre 1 y 720")
    await db.settings.update_one(
        {"id": "global"}, {"$set": {"delivery_sla_hours": hours}}, upsert=True)
    await log_action(db, actor, "delivery.sla_update", "settings", "global",
                     summary=f"SLA de mensajería fijado en {hours} h",
                     details={"delivery_sla_hours": hours})
    return {"ok": True, "delivery_sla_hours": hours}


@router.get("/admin/deliveries/sla-compliance")
async def admin_sla_compliance(request: Request,
                               date_from: Optional[str] = None,
                               date_to: Optional[str] = None,
                               courier_id: Optional[str] = None) -> Any:
    """Cumplimiento del SLA: porcentaje de entregas COMPLETADAS dentro del
    límite de horas, por mensajero y por semana (ISO). El tiempo se mide desde
    la creación hasta la entrega (timeline `delivered`, o la confirmación si no
    hubiera marca de entrega)."""
    await require_permission(request, "deliveries")
    from datetime import datetime, timedelta
    from services.deliveries import get_delivery_sla_hours
    sla_hours = await get_delivery_sla_hours()
    q: dict = {"status": {"$in": ["delivered", "confirmed"]}}
    if date_from:
        q.setdefault("created_at", {})["$gte"] = date_from[:10]
    if date_to:
        try:
            nxt = (datetime.strptime(date_to[:10], "%Y-%m-%d")
                   + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400,
                                detail="fecha inválida (YYYY-MM-DD)")
        q.setdefault("created_at", {})["$lt"] = nxt
    if courier_id:
        q["courier_id"] = courier_id
    cursor = db.deliveries.find(q, {
        "_id": 0, "id": 1, "created_at": 1, "updated_at": 1, "timeline": 1,
        "courier_id": 1, "courier_name": 1, "status": 1}).batch_size(1000)

    def _parse(s: Any) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def _completion_at(d: dict) -> Any:
        tl = d.get("timeline") or []
        for want in ("delivered", "confirmed"):
            for e in tl:
                if e.get("status") == want:
                    return e.get("at")
        return d.get("updated_at")

    sla_seconds = sla_hours * 3600.0
    total = 0
    within = 0
    per_courier: dict = {}
    per_week: dict = {}
    async for d in cursor:
        created = _parse(d.get("created_at"))
        done = _parse(_completion_at(d))
        if not created or not done:
            continue
        ok = (done - created).total_seconds() <= sla_seconds
        total += 1
        within += 1 if ok else 0
        cid = d.get("courier_id") or "—"
        pc = per_courier.setdefault(
            cid, {"courier_id": cid, "courier_name": d.get("courier_name") or "—",
                  "total": 0, "within": 0})
        pc["total"] += 1
        pc["within"] += 1 if ok else 0
        iso_year, iso_week, _ = created.isocalendar()
        wk = f"{iso_year}-W{iso_week:02d}"
        pw = per_week.setdefault(wk, {"week": wk, "total": 0, "within": 0})
        pw["total"] += 1
        pw["within"] += 1 if ok else 0

    def _pct(w: int, t: int) -> float:
        return round(w * 100.0 / t, 1) if t else 0.0

    courier_rows = sorted(per_courier.values(),
                          key=lambda r: r["total"], reverse=True)
    for r in courier_rows:
        r["pct"] = _pct(r["within"], r["total"])
    week_rows = sorted(per_week.values(), key=lambda r: r["week"])
    for r in week_rows:
        r["pct"] = _pct(r["within"], r["total"])
    return {
        "sla_hours": sla_hours,
        "total_completed": total,
        "within_sla": within,
        "breached": total - within,
        "pct_within": _pct(within, total),
        "by_courier": courier_rows,
        "by_week": week_rows,
    }


_INCIDENT_ORIGIN_COLL = {"withdrawal": "withdrawals",
                         "redemption": "redemptions",
                         "company_delivery": "company_delivery_requests"}
_INCIDENT_ORIGIN_FIELDS = [
    "status", "created_at", "product_name", "quantity", "total_usd",
    "amount_usd", "currency", "method", "user_name", "user_email",
    "company_name", "receiver_name", "receiver_phone", "municipality",
    "province", "package_label", "delivery_address"]


async def _incident_origin_summary(kind: str, ref_id: str) -> Dict[str, Any]:
    """Resumen curado del documento de origen (canje/retiro/envío Empresa)
    para que el admin verifique el efectivo/producto sin salir del panel."""
    coll = _INCIDENT_ORIGIN_COLL.get(kind)
    if not coll or not ref_id:
        return {}
    doc = await db[coll].find_one({"id": ref_id}, {"_id": 0})
    if not doc:
        return {"missing": True}
    return {k: doc[k] for k in _INCIDENT_ORIGIN_FIELDS if k in doc}


async def _incident_reassign_info(oc: dict) -> Dict[str, Any]:
    """Para incidencias de envío Empresa cuya devolución de inventario quedó
    PENDIENTE (`inv_return_incident`), devuelve los datos para reasignar la
    mercancía a una tienda existente: producto, cantidad, si el producto aún
    existe y la lista de tiendas activas de la empresa. `{}` si no aplica."""
    if oc.get("kind") != "company_delivery":
        return {}
    req = await db.company_delivery_requests.find_one(
        {"id": oc.get("ref_id")},
        {"_id": 0, "company_id": 1, "product_id": 1, "quantity": 1,
         "inv_return_incident": 1, "inv_returned": 1})
    if not req or not req.get("inv_return_incident") or req.get("inv_returned"):
        return {}
    company_id = req.get("company_id")
    pid = req.get("product_id")
    prod = await db.products.find_one(
        {"id": pid, "company_id": company_id}, {"_id": 0, "name": 1})
    stores = await db.stores.find(
        {"company_id": company_id, "status": {"$ne": "closing"},
         "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1}).to_list(100)
    return {
        "pending": True,
        "product_id": pid,
        "product_name": (prod or {}).get("name"),
        "product_exists": prod is not None,
        "quantity": req.get("quantity"),
        "stores": stores,
    }


async def _list_incidents(resolved: bool) -> list:
    flt = {"origin_conflict": {"$exists": True},
           "origin_conflict.resolved": (True if resolved else {"$ne": True})}
    rows = await db.deliveries.find(flt, {"_id": 0}).sort(
        "origin_conflict.at", -1).to_list(200)
    for r in rows:
        oc = r.get("origin_conflict") or {}
        r["origin"] = await _incident_origin_summary(
            oc.get("kind") or r.get("kind") or "",
            oc.get("ref_id") or r.get("ref_id") or "")
        r["reassign"] = await _incident_reassign_info(oc)
    return rows


@router.get("/admin/delivery-incidents")
async def admin_delivery_incidents(request: Request,
                                   resolved: bool = False) -> Any:
    """Incidencias de mensajería: entregas con MOVIMIENTO FÍSICO (entregadas/
    confirmadas) cuyo origen quedó rechazado/cancelado (`origin_conflict`).
    Por defecto lista las ABIERTAS; `resolved=true` devuelve el historial de
    resueltas. Cada fila incluye un resumen del origen para gestión manual."""
    await require_permission(request, "deliveries")
    return await _list_incidents(resolved)


class _IncidentResolvePayload(BaseModel):
    note: str = Field("", max_length=500)


@router.post("/admin/delivery-incidents/{did}/resolve")
async def admin_resolve_origin_conflict(did: str, payload: _IncidentResolvePayload,
                                        request: Request) -> Any:
    """Marca una incidencia como resuelta tras gestionarla manualmente
    (idempotente: solo afecta incidencias abiertas)."""
    actor = await require_permission(request, "deliveries")
    now = iso(now_utc())
    note = payload.note.strip()
    res = await db.deliveries.update_one(
        {"id": did, "origin_conflict": {"$exists": True},
         "origin_conflict.resolved": {"$ne": True}},
        {"$set": {"origin_conflict.resolved": True,
                  "origin_conflict.resolved_by": actor["user_id"],
                  "origin_conflict.resolved_at": now,
                  "origin_conflict.resolution_note": note},
         "$push": {"timeline": {"status": "incident_resolved", "at": now,
                                "by": actor["user_id"], "note": note}}})
    if res.modified_count == 0:
        raise HTTPException(status_code=404,
                            detail="Incidencia no encontrada o ya resuelta")
    await log_action(db, actor, "delivery.incident_resolved", "delivery", did,
                     details={"note": note})
    return {"ok": True}


class _IncidentReassignPayload(BaseModel):
    store_id: str = Field(..., min_length=1, max_length=120)
    note: str = Field("", max_length=500)


@router.post("/admin/delivery-incidents/{did}/reassign-inventory")
async def admin_reassign_incident_inventory(
        did: str, payload: _IncidentReassignPayload, request: Request) -> Any:
    """Reasigna a una TIENDA EXISTENTE la mercancía que quedó pendiente tras una
    incidencia de envío Empresa (devolución que no se pudo aplicar). Suma la
    cantidad al inventario de la tienda elegida (idempotente) y resuelve la
    incidencia. Si el producto ya no existe, NO se puede reasignar (usar
    'resolver')."""
    actor = await require_permission(request, "deliveries")
    d = await db.deliveries.find_one(
        {"id": did, "origin_conflict": {"$exists": True},
         "origin_conflict.resolved": {"$ne": True}}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404,
                            detail="Incidencia no encontrada o ya resuelta")
    oc = d.get("origin_conflict") or {}
    if oc.get("kind") != "company_delivery":
        raise HTTPException(status_code=400,
                            detail="La incidencia no corresponde a un envío Empresa.")
    req = await db.company_delivery_requests.find_one(
        {"id": oc.get("ref_id")}, {"_id": 0})
    if not req or not req.get("inv_return_incident") or req.get("inv_returned"):
        raise HTTPException(status_code=409,
                            detail="La incidencia no tiene inventario pendiente de reasignar.")
    company_id = req["company_id"]
    pid = req["product_id"]
    qty = float(req.get("quantity") or 0)
    prod = await db.products.find_one({"id": pid, "company_id": company_id}, {"_id": 0, "name": 1})
    if not prod:
        raise HTTPException(
            status_code=409,
            detail=("El producto ya no existe; no se puede reasignar su stock. "
                    "Usa 'Resolver' para cerrar la incidencia."))
    store = await db.stores.find_one(
        {"id": payload.store_id, "company_id": company_id,
         "status": {"$ne": "closing"}, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1})
    if not store:
        raise HTTPException(status_code=400,
                            detail="Tienda no encontrada o no disponible.")
    # Coloca la cantidad en la tienda elegida (sube total + distribuido + by_store).
    # op_id propio de la reasignación → no colisiona con la devolución fallida.
    from services import company_inventory
    status = await company_inventory.return_dispatch(
        company_id, pid, payload.store_id, qty,
        op_id=f"cdeliv-reassign:{req['id']}",
        actor={"user_id": actor["user_id"]})
    if status != "applied":
        raise HTTPException(status_code=409,
                            detail=f"No se pudo reasignar el inventario ({status}).")
    now = iso(now_utc())
    note = (f"Inventario reasignado a '{store.get('name', '')}' "
            f"({qty:g} uds). {payload.note.strip()}").strip()
    await db.company_delivery_requests.update_one(
        {"id": req["id"]},
        {"$set": {"inv_returned": True, "inv_reassigned_store_id": payload.store_id,
                  "updated_at": now}})
    await db.deliveries.update_one(
        {"id": did, "origin_conflict.resolved": {"$ne": True}},
        {"$set": {"origin_conflict.resolved": True,
                  "origin_conflict.resolved_by": actor["user_id"],
                  "origin_conflict.resolved_at": now,
                  "origin_conflict.resolution_note": note},
         "$push": {"timeline": {"status": "incident_reassigned", "at": now,
                                "by": actor["user_id"], "note": note}}})
    await company_inventory.maybe_alert_store_out_of_stock(company_id, pid, payload.store_id)
    await log_action(db, actor, "delivery.incident_reassigned", "delivery", did,
                     details={"store_id": payload.store_id, "product_id": pid, "qty": qty})
    return {"ok": True, "store_name": store.get("name", "")}


@router.post("/admin/deliveries/{did}/retry-sync")
async def admin_retry_sync(did: str, request: Request) -> Any:
    """Mejora #6 — reintento SEGURO de las sincronizaciones vinculadas a la
    entrega: misma identidad de acción (handlers idempotentes), jamás duplica
    dinero. Cubre la liquidación pendiente (settlement_pending) y la tarea
    cobro↔reparto del documento de origen (delivery_sync_pending)."""
    actor = await require_permission(request, "deliveries")
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="No encontrada.")
    result: Dict[str, Any] = {"settlement": None, "fee_sync": None}
    sp = d.get("settlement_pending")
    if sp:
        from services.delivery_settlement import (settle_linked_operation,
                                                  OriginConflict)
        from services.deliveries import flag_origin_conflict
        try:
            await settle_linked_operation(sp.get("kind") or d["kind"],
                                          sp.get("ref_id") or d["ref_id"],
                                          actor)
            await db.deliveries.update_one(
                {"id": did, "settlement_pending.at": sp.get("at")},
                {"$unset": {"settlement_pending": ""}})
            result["settlement"] = "ok"
        except OriginConflict as oc:
            await db.deliveries.update_one(
                {"id": did, "settlement_pending.at": sp.get("at")},
                {"$unset": {"settlement_pending": ""}})
            await flag_origin_conflict(did, d["kind"], d["ref_id"], str(oc))
            result["settlement"] = "conflict"
    coll_name = {"withdrawal": "withdrawals",
                 "redemption": "redemptions"}.get(d.get("kind"))
    if coll_name:
        ref = await db[coll_name].find_one(
            {"id": d["ref_id"]}, {"_id": 0, "delivery_sync_pending": 1})
        if ref and ref.get("delivery_sync_pending"):
            from services.deliveries import sync_delivery_from_doc
            await sync_delivery_from_doc(coll_name, d["ref_id"],
                                         actor_id=actor["user_id"])
            result["fee_sync"] = "ok"
    if result["settlement"] is None and result["fee_sync"] is None:
        result["status"] = "nothing_pending"
    await log_action(db, actor, "delivery.retry_sync", "delivery", did,
                     details=result)
    updated = await db.deliveries.find_one({"id": did}, {"_id": 0})
    return {"result": result, "delivery": updated}


@router.get("/admin/deliveries")
async def admin_list_deliveries(request: Request, response: Response,
                                status: Optional[str] = None,
                                courier_id: Optional[str] = None,
                                incident: Optional[str] = None,
                                search: Optional[str] = None,
                                reassigned_only: bool = False,
                                skip: int = 0, limit: int = 200) -> Any:
    await require_permission(request, "deliveries")
    q: dict = {}
    if status == "assigned":
        # MEN-02 — estado DERIVADO: reservadas pendientes de aceptación.
        q["status"] = "available"
        q["needs_origin_check"] = {"$ne": True}
        q["assigned_to_courier_id"] = {"$nin": [None, ""]}
    elif status == "available":
        # MEN-02 — "Disponible" = SOLO las realmente libres (excluye las
        # reservadas, que ahora viven en el filtro "Asignada").
        q["status"] = "available"
        q["$or"] = [{"assigned_to_courier_id": {"$in": [None, ""]}},
                    {"assigned_to_courier_id": {"$exists": False}}]
    elif status == "active":
        # MEN-04 — "Activas" = EN CURSO: excluye entregadas (pendientes de
        # confirmación), confirmadas y canceladas.
        q["status"] = {"$nin": ["delivered", "confirmed", "cancelled"]}
    elif status == "pending_confirmation":
        # MEN-04 — "Pendientes de confirmación": entregas ya realizadas que aún
        # requieren confirmación y pago de comisión. Sacarlas de "Activas" NO
        # ejecuta ninguna comisión; siguen visibles y accionables aquí.
        q["status"] = "delivered"
    elif status == "history":
        # MEN-04 — "Historial": solo completadas (confirmadas) y canceladas.
        q["status"] = {"$in": ["confirmed", "cancelled"]}
    elif status:
        q["status"] = status
    if courier_id:
        q["courier_id"] = courier_id
    if incident == "open":
        q["has_open_incident"] = True
    # Filtro por Reasignadas — solo entregas con auditoría de reasignación/
    # liberación (`reassign_audit`), ya sea de una entrega aceptada o de una
    # reserva aún no aceptada. Útil en el Historial para revisar cambios de
    # mensajero.
    if reassigned_only:
        q["reassign_audit"] = {"$exists": True}
    # Buscador — por cliente, mensajero, referencia o fecha (YYYY-MM[-DD]).
    term = (search or "").strip()
    if term:
        rx = {"$regex": re.escape(term), "$options": "i"}
        search_or = [{"client_name": rx}, {"courier_name": rx},
                     {"assigned_to_courier_name": rx}, {"ref_id": rx}]
        if re.match(r"^\d{4}-\d{2}(-\d{2})?$", term):
            search_or.append({"created_at": {"$regex": "^" + re.escape(term)}})
        q = {"$and": [q, {"$or": search_or}]} if q else {"$or": search_or}
    # MEN-04 — paginación de SERVIDOR (no recortar en el frontend). Se expone el
    # total vía cabecera X-Total-Count para los controles de página.
    skip = max(0, skip)
    limit = max(1, min(limit, 200))
    total = await db.deliveries.count_documents(q)
    response.headers["X-Total-Count"] = str(total)
    rows = await db.deliveries.find(q, {"_id": 0}).sort(
        "created_at", -1).skip(skip).limit(limit).to_list(limit)
    # MEN-02 — marcar el estado derivado y resolver el nombre del mensajero
    # reservado para las reservas ANTIGUAS que no lo tengan persistido.
    missing_ids = {d.get("assigned_to_courier_id") for d in rows
                   if _is_reserved(d) and not d.get("assigned_to_courier_name")}
    missing_ids.discard(None)
    missing_ids.discard("")
    name_by_id: dict = {}
    if missing_ids:
        async for u in db.users.find(
                {"user_id": {"$in": list(missing_ids)}},
                {"_id": 0, "user_id": 1, "name": 1, "email": 1}):
            name_by_id[u["user_id"]] = u.get("name") or u.get("email")
    for d in rows:
        d["display_status"] = _derive_display_status(d)
        if d["display_status"] == "assigned" and not d.get("assigned_to_courier_name"):
            d["assigned_to_courier_name"] = name_by_id.get(
                d.get("assigned_to_courier_id"))
    return rows


@router.get("/admin/couriers")
async def admin_list_couriers(request: Request) -> Any:
    await require_permission(request, "deliveries")
    users = await db.users.find(
        {"$or": [{"is_courier": True}, {"role": {"$in": ["admin", "employee"]}}]},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1,
         "is_courier": 1, "phone": 1, "courier_last_gps_at": 1},
    ).to_list(200)
    stats = await db.deliveries.aggregate([
        {"$match": {"status": "confirmed"}},
        {"$group": {"_id": "$courier_id",
                    "earned": {"$sum": "$courier_share_usdt"},
                    "count": {"$sum": 1}}},
    ]).to_list(500)
    by_id = {s["_id"]: s for s in stats}
    # Mejora #4 — carga activa (trabajos en curso) por mensajero.
    active = await db.deliveries.aggregate([
        {"$match": {"status": {"$in": ["accepted", "on_the_way",
                                       "arrived", "delivered"]}}},
        {"$group": {"_id": "$courier_id", "n": {"$sum": 1}}},
    ]).to_list(500)
    active_by_id = {a["_id"]: int(a["n"]) for a in active}
    for u in users:
        s = by_id.get(u["user_id"], {})
        u["earned_usdt"] = round(float(s.get("earned") or 0), 2)
        u["deliveries_count"] = int(s.get("count") or 0)
        u["active_load"] = active_by_id.get(u["user_id"], 0)
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
    # MEN23 — `ref_id` debe ser escalar antes de consultar por él.
    _require_scalar_str(ref_id, "ref_id")
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


# MEN23 — estados desde los que el operador puede ordenar una cancelación.
_CANCELABLE_STATUSES = {"available", "accepted", "on_the_way", "arrived", "delivered"}


def _validate_expected_uid(payload: dict) -> None:
    """MEN23 — `expected_uid` debe ser una CADENA o null. Rechaza objetos,
    arrays, números y booleanos ANTES de construir el filtro Mongo, para que no
    puedan colarse como operadores de consulta y debilitar la igualdad de ciclo."""
    if "expected_uid" in payload:
        v = payload["expected_uid"]
        if v is not None and not isinstance(v, str):
            raise HTTPException(
                status_code=400,
                detail="expected_uid inválido: debe ser una cadena o null.")


def _require_scalar_str(value: Any, field: str) -> None:
    """MEN23 — exige que un identificador tomado del body sea una CADENA antes
    de usarlo como valor de filtro Mongo. Rechaza objetos/arrays/números/
    booleanos para que no se interpreten como operadores de consulta."""
    if not isinstance(value, str):
        raise HTTPException(
            status_code=400,
            detail=f"{field} inválido: debe ser una cadena.")


@router.post("/admin/deliveries/{did}/assign")
async def admin_assign_delivery(did: str, payload: dict, request: Request) -> Any:
    """iter208 — El admin *reserva* la entrega para un mensajero pero NO la
    acepta en su nombre: la deja como `available` con `assigned_to_courier_id`
    apuntando al mensajero elegido. El mensajero recibe la notificación y
    push, y luego tiene que tocar 'Aceptar' en su panel para pasar a
    `accepted`. Así el mensajero confirma antes de que la orden se le
    contabilice como en curso."""
    actor = await require_permission(request, "deliveries_assign")
    courier_id = payload.get("courier_id")
    if not courier_id:
        raise HTTPException(status_code=400, detail="courier_id requerido")
    # MEN23 — `courier_id` debe ser escalar antes de usarse en find/CAS.
    _require_scalar_str(courier_id, "courier_id")
    courier = await db.users.find_one({"user_id": courier_id}, {"_id": 0})
    if not courier or not (courier.get("is_courier")
                           or courier.get("role") in ("admin", "employee")):
        raise HTTPException(status_code=400, detail="Ese usuario no es mensajero")
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="No encontrado")
    # Mejora mensajería #2 — una entrega YA ACEPTADA por un mensajero no se
    # reasigna (ni siquiera por un admin): un mensajero no puede «rechazar» lo
    # que ya aceptó (`reject_reservation` solo opera sobre reservas `available`
    # propias), así que la ÚNICA vía para cambiarla es cancelarla por completo.
    # Evita quitarle el trabajo a alguien que ya lo tomó.
    if d["status"] == "accepted":
        cname = d.get("courier_name") or "un mensajero"
        raise HTTPException(
            status_code=409,
            detail=(f"Esta entrega ya fue aceptada por {cname}. Un mensajero "
                    "no puede «rechazar» una entrega que ya aceptó, por lo que "
                    "no es posible reasignarla directamente. Si de verdad "
                    "necesitas cambiar de mensajero, debes cancelar la entrega "
                    "por completo: quedará cancelada, se avisará al mensajero y "
                    "tendrás que crearla de nuevo."))
    if d["status"] != "available":
        raise HTTPException(status_code=409,
                            detail=f"No se puede asignar en estado {d['status']}")
    # Mejora mensajería #2 — si YA está reservada para otro mensajero (y aún no
    # la rechazó), por defecto NO se reasigna a un tercero (el mensajero
    # reservado debe rechazarla primero). EXCEPCIÓN — "Acción Rápida Reserva":
    # el admin puede FORZAR la reasignación de una reserva LENTA aún no aceptada
    # con `override_reservation`; se re-reserva al nuevo mensajero con un CICLO
    # nuevo (uid), y el `expected_uid` garantiza que una aceptación del
    # mensajero anterior que llegue en paralelo pierda con 409.
    current_reserved = d.get("assigned_to_courier_id")
    override_reservation = bool(payload.get("override_reservation"))
    if current_reserved and current_reserved != courier_id \
            and not override_reservation:
        other = await db.users.find_one({"user_id": current_reserved},
                                        {"_id": 0, "name": 1, "email": 1})
        oname = (other or {}).get("name") or (other or {}).get("email") \
            or "otro mensajero"
        raise HTTPException(
            status_code=409,
            detail=(f"Esta entrega ya está asignada a {oname}. Debe rechazarla "
                    "antes de poder asignarla a otro mensajero."))
    # Reserva reasignada (override): recordamos al mensajero anterior para la
    # auditoría y el aviso.
    prev_reserved_id = (current_reserved
                        if current_reserved and current_reserved != courier_id
                        else None)
    prev_reserved_name = (d.get("assigned_to_courier_name")
                          if prev_reserved_id else None)
    reason = (payload.get("reason") or "").strip()[:300]
    now = iso(now_utc())
    courier_display = courier.get("name") or courier.get("email")
    # ABA (A08 / M01-A) — CONCURRENCIA OPTIMISTA sobre el ciclo de asignación.
    # La escritura se condiciona (CAS) al `assignment_uid` que ESTA invocación
    # leyó (o al `expected_uid` que el admin declaró ver). Así:
    #   - un reintento REAL al mismo mensajero sobre el ciclo vigente conserva
    #     el uid (idempotente) y no invalida la vista del mensajero;
    #   - una orden ATRASADA que leyó un uid viejo (U1) pierde con 409 y NO
    #     reescribe U1 sobre el ciclo nuevo (U3): la identidad no retrocede, y
    #     el rechazo viejo con U1 sigue siendo inválido.
    _validate_expected_uid(payload)
    expected_uid = payload.get("expected_uid")
    observed_uid = expected_uid if expected_uid is not None \
        else d.get("assignment_uid")
    cas: Dict[str, Any] = {}
    if current_reserved == courier_id and observed_uid:
        assignment_uid = observed_uid
        cas = {"assigned_to_courier_id": courier_id,
               "assignment_uid": observed_uid}
    else:
        assignment_uid = uuid.uuid4().hex
        if expected_uid is not None:
            cas = {"assignment_uid": expected_uid}
        else:
            cas = {"$or": [{"assigned_to_courier_id": {"$in": [None, ""]}},
                           {"assigned_to_courier_id": {"$exists": False}},
                           {"assigned_to_courier_id": courier_id,
                            "assignment_uid": {"$exists": False}}]}
    # MSG08 — la ubicación GPS del mensajero anterior se INVALIDA al reasignar.
    set_fields: Dict[str, Any] = {
        "status": "available",
        "assigned_to_courier_id": courier_id,
        "assigned_to_courier_name": courier_display,
        "assignment_uid": assignment_uid,
        "assigned_by": actor["user_id"],
        "assigned_by_name": actor.get("name") or actor.get("email"),
        "assigned_at": now,
        "courier_id": None,
        "courier_name": None,
        "updated_at": now,
    }
    timeline_note = f"Reservada para {courier_display} — pendiente de aceptación"
    if prev_reserved_id:
        # Acción Rápida Reserva — la reasignación de una RESERVA aún no aceptada
        # queda AUDITADA igual que la de una aceptada (`reassign_audit`), con
        # `stage=reservation` para distinguirla. Así aparece en el filtro
        # "Solo reasignadas" del Historial.
        set_fields["reassign_audit"] = {
            "mode": "reassigned",
            "by": actor["user_id"],
            "by_name": actor.get("name") or actor.get("email"),
            "at": now,
            "from_courier_id": prev_reserved_id,
            "from_courier_name": prev_reserved_name or "el mensajero reservado",
            "to_courier_id": courier_id,
            "to_courier_name": courier_display,
            "reason": reason or None,
            "stage": "reservation",
        }
        timeline_note = (
            f"Reserva reasignada de {prev_reserved_name or 'otro mensajero'} a "
            f"{courier_display} — pendiente de aceptación."
            + (f" Motivo: {reason}" if reason else ""))
    res = await db.deliveries.update_one(
        {"id": did, "status": "available",
         # MV02 — no reservar repartos pendientes de validar.
         "needs_origin_check": {"$ne": True}, **cas}, {
            "$set": set_fields,
            "$unset": {"courier_location": ""},
            "$push": {"timeline": {"status": "available", "at": now,
                                   "by": actor["user_id"],
                                   "note": timeline_note}},
        })
    if res.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail=("La asignación cambió mientras se procesaba (otro ciclo, "
                    "otro mensajero o cambió de estado); recarga."))
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
                url=f"/dashboard/deliveries?delivery={did}",
                tag=f"delivery-assigned-{did}",
            )
            await send_push_to_user(db, courier_id, payload)
        except Exception as e:
            logger.error(f"assign push failed: {e}")
    except Exception as e:
        logger.error(f"assign notify failed: {e}")
    # Acción Rápida Reserva — avisa al mensajero ANTERIOR que su reserva (aún no
    # aceptada) fue reasignada por el equipo.
    if prev_reserved_id:
        try:
            from routes.notifications import _insert_notification
            from push_service import (send_push_to_user,
                                      build_generic_admin_alert_payload)
            rtitle = "Tu reserva fue reasignada"
            rbody = (f"La entrega de {d.get('client_name', '')} "
                     f"({d.get('amount_label', '')}) que tenías reservada fue "
                     f"reasignada por el equipo."
                     + (f" Motivo: {reason}" if reason else ""))
            await _insert_notification(
                recipient_user_id=prev_reserved_id,
                type="delivery_reassigned", title=rtitle, message=rbody,
                data={"delivery_id": did})
            await send_push_to_user(
                db, prev_reserved_id, build_generic_admin_alert_payload(
                    title=rtitle, body=rbody,
                    url="/dashboard/deliveries",
                    tag=f"delivery-reassigned-{did}"))
        except Exception as e:
            logger.error(f"reservation reassign notify failed: {e}")
    return await db.deliveries.find_one({"id": did}, {"_id": 0})


@router.post("/admin/deliveries/{did}/reassign")
async def admin_reassign_delivery(did: str, payload: dict,
                                  request: Request) -> Any:
    """Reasignar SIN cancelar — libera una entrega ya ACEPTADA sin destruir la
    operación de origen. Dos modos en el mismo paso:
      - sin `courier_id` → vuelve a DISPONIBLE libre (cualquier mensajero la toma)
      - con `courier_id`  → se RE-RESERVA al mensajero elegido (pendiente de que
        él acepte, igual que una asignación normal)
    Solo aplica a `accepted` (aún no salió). El motivo es OPCIONAL y queda en el
    timeline + auditoría; se avisa al mensajero anterior (y al nuevo si procede).
    Mismo permiso que asignar (`deliveries_assign`); no requiere 2FA."""
    actor = await require_permission(request, "deliveries_assign")
    reason = (payload.get("reason") or "").strip()[:300]
    new_courier_id = (payload.get("courier_id") or "").strip() or None
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="No encontrada.")
    if d.get("status") != "accepted":
        raise HTTPException(
            status_code=409,
            detail=("Solo se puede reasignar sin cancelar una entrega ya "
                    "ACEPTADA que aún no salió. Si ya está en camino o "
                    "entregada, usa cancelar."))
    prev_courier_id = d.get("courier_id")
    prev_courier_name = d.get("courier_name") or "el mensajero anterior"
    # M01-B — CAS sobre el CICLO que ESTA invocación examinó: una reasignación
    # atrasada que vio el ciclo viejo (C1) NO debe actuar sobre un ciclo
    # aceptado POSTERIOR (C3) solo porque la entrega vuelva a estar aceptada por
    # el mismo mensajero. El `assignment_uid` persiste al aceptar (ver
    # claim_delivery), así distinguimos ciclos aceptados.
    _validate_expected_uid(payload)
    expected_uid = payload.get("expected_uid")
    observed_uid = expected_uid if expected_uid is not None \
        else d.get("assignment_uid")
    new_display = None
    if new_courier_id:
        if new_courier_id == prev_courier_id:
            raise HTTPException(
                status_code=400,
                detail=("Ya está aceptada por ese mensajero; elige otro o "
                        "libérala a disponible."))
        new_courier = await db.users.find_one({"user_id": new_courier_id},
                                              {"_id": 0})
        if not new_courier or not (new_courier.get("is_courier")
                                   or new_courier.get("role")
                                   in ("admin", "employee")):
            raise HTTPException(status_code=400,
                                detail="Ese usuario no es mensajero")
        new_display = new_courier.get("name") or new_courier.get("email")
    now = iso(now_utc())
    reason_suffix = f" Motivo: {reason}" if reason else ""
    # Auditoría de reasignación (cierre MEN-08): el detalle muestra quién
    # liberó/reasignó, cuándo, de quién a quién y el motivo. Se guarda SIEMPRE
    # (ambos modos) en el documento para trazabilidad, además del timeline.
    reassign_audit = {
        "mode": "reassigned" if new_courier_id else "freed",
        "by": actor["user_id"],
        "by_name": actor.get("name") or actor.get("email"),
        "at": now,
        "from_courier_id": prev_courier_id,
        "from_courier_name": prev_courier_name,
        "to_courier_id": new_courier_id,
        "to_courier_name": new_display,
        "reason": reason or None,
    }
    set_doc: Dict[str, Any] = {"status": "available", "courier_id": None,
                               "courier_name": None, "updated_at": now,
                               "reassign_audit": reassign_audit}
    unset_doc: Dict[str, Any] = {"courier_location": ""}
    if new_courier_id:
        set_doc.update({"assigned_to_courier_id": new_courier_id,
                        "assigned_to_courier_name": new_display,
                        # ABA (A08) — ciclo de asignación NUEVO: uid nuevo.
                        "assignment_uid": uuid.uuid4().hex,
                        "assigned_by": actor["user_id"],
                        "assigned_by_name": actor.get("name")
                        or actor.get("email"),
                        "assigned_at": now})
        note = (f"Reasignada de {prev_courier_name} a {new_display} — "
                f"pendiente de aceptación.{reason_suffix}")
    else:
        unset_doc.update({"assigned_to_courier_id": "",
                          "assigned_to_courier_name": "",
                          # ABA (A08) — liberada: sin ciclo de asignación activo.
                          "assignment_uid": "",
                          "assigned_by": "", "assigned_by_name": "",
                          "assigned_at": ""})
        note = (f"Liberada (estaba aceptada por {prev_courier_name}) a "
                f"DISPONIBLE por el equipo.{reason_suffix}")
    # Guardado ATÓMICO condicionado al estado, mensajero y CICLO leídos: una
    # petición atrasada (el mensajero avanzó a on_the_way, se canceló, o es un
    # ciclo aceptado posterior) pierde con 409.
    cas_filter: Dict[str, Any] = {"id": did, "status": "accepted",
                                  "courier_id": prev_courier_id}
    cas_filter["assignment_uid"] = (observed_uid if observed_uid is not None
                                    else {"$exists": False})
    res = await db.deliveries.update_one(
        cas_filter,
        {"$set": set_doc, "$unset": unset_doc,
         "$push": {"timeline": {"status": "available", "at": now,
                                "by": actor["user_id"], "note": note}}})
    if res.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail=("La entrega cambió de estado, de mensajero o de ciclo "
                    "mientras reasignabas — recarga tu panel."))
    try:
        from services.deliveries import publish_delivery_event
        await publish_delivery_event(
            did, "available",
            courier_ids=None if not new_courier_id
            else [prev_courier_id, new_courier_id])
    except Exception:
        pass
    # Aviso al mensajero ANTERIOR (perdió el trabajo).
    if prev_courier_id:
        try:
            from routes.notifications import _insert_notification
            from push_service import (send_push_to_user,
                                      build_generic_admin_alert_payload)
            title = "La entrega fue reasignada"
            body = (f"La entrega de {d.get('client_name', '')} "
                    f"({d.get('amount_label', '')}) fue reasignada por el "
                    f"equipo.{reason_suffix}")
            await _insert_notification(
                recipient_user_id=prev_courier_id, type="delivery_reassigned",
                title=title, message=body, data={"delivery_id": did})
            await send_push_to_user(
                db, prev_courier_id,
                build_generic_admin_alert_payload(
                    title=title, body=body, url="/dashboard/deliveries",
                    tag=f"delivery-reassigned-{did}"))
        except Exception as e:
            logger.error(f"reassign prev-courier notify failed: {e}")
    # Aviso al mensajero NUEVO (si se re-reservó) — mismo copy que una asignación.
    if new_courier_id:
        try:
            from routes.notifications import _insert_notification
            from push_service import (send_push_to_user,
                                      build_generic_admin_alert_payload)
            is_pickup = d.get("kind") == "deposit"
            title = ("Nueva recogida asignada" if is_pickup
                     else "Nueva entrega asignada")
            verb = "recoger" if is_pickup else "entregar"
            share = float(d.get("courier_share_usdt") or 0)
            share_line = f" Tu parte: {share} USDT." if share > 0 else ""
            msg = (f"Te asignaron {verb} para {d.get('client_name', '')} "
                   f"({d.get('amount_label', '')}).{share_line}")
            await _insert_notification(
                recipient_user_id=new_courier_id, type="delivery_assigned",
                title=title, message=msg,
                data={"delivery_id": did, "kind": d.get("kind")})
            await send_push_to_user(
                db, new_courier_id,
                build_generic_admin_alert_payload(
                    title=title, body=msg,
                    url=f"/dashboard/deliveries?delivery={did}",
                    tag=f"delivery-assigned-{did}"))
        except Exception as e:
            logger.error(f"reassign new-courier notify failed: {e}")
    await log_action(
        db, actor, "delivery.reassign", "delivery", did,
        summary=(f"Reasignada {did[:8]} "
                 + (f"a {new_display}" if new_display else "a disponible")),
        details={"from_courier_id": prev_courier_id,
                 "to_courier_id": new_courier_id, "reason": reason or None})
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


async def _execute_cancel(did: str, d: dict, actor: dict, *, note: str,
                          expected_status: str, euid: Any) -> Any:
    """Núcleo de la cancelación (CAS por estado+ciclo), reutilizado por la
    cancelación individual y la cancelación masiva por SLA. Devuelve el
    documento actualizado o lanza 409 si el estado/ciclo cambió. Para envíos de
    empresa reconcilia la devolución de tarifa+inventario al origen."""
    now = iso(now_utc())
    flt: Dict[str, Any] = {
        "id": did,
        "status": expected_status,
        "payout_credited": {"$ne": True},
        "assignment_uid": euid if euid else {"$exists": False},
    }
    res = await db.deliveries.update_one(
        flt, {
            "$set": {"status": "cancelled", "updated_at": now},
            "$unset": {"active_key": ""},
            "$push": {"timeline": {"status": "cancelled", "at": now,
                                   "by": actor["user_id"],
                                   "note": note}},
        })
    if res.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail=("La entrega cambió de estado, de mensajero o de ciclo "
                    "(¿reasignada o aceptada?); recarga y vuelve a decidir."))
    if d.get("kind") == "company_delivery":
        try:
            from services.company_delivery_recovery import reconcile_cancelled_request
            creq = await db.company_delivery_requests.find_one(
                {"id": d.get("ref_id")}, {"_id": 0})
            if creq and creq.get("status") != "cancelled":
                await reconcile_cancelled_request(creq)
        except Exception as e:
            logger.error(f"company_delivery admin-cancel reconcile failed: {e}")
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
    recipient = d.get("courier_id") or d.get("assigned_to_courier_id")
    if recipient:
        try:
            from routes.notifications import _insert_notification
            from push_service import (send_push_to_user,
                                      build_generic_admin_alert_payload)
            ctitle = "Entrega cancelada"
            cbody = (f"La entrega de {d.get('client_name', '')} "
                     f"({d.get('amount_label', '')}) fue cancelada por el equipo.")
            await _insert_notification(
                recipient_user_id=recipient, type="delivery_cancelled",
                title=ctitle, message=cbody, data={"delivery_id": did})
            await send_push_to_user(
                db, recipient, build_generic_admin_alert_payload(
                    title=ctitle, body=cbody, url="/dashboard/deliveries",
                    tag=f"delivery-cancelled-{did}"))
        except Exception as e:
            logger.error(f"cancel notify failed: {e}")
    return await db.deliveries.find_one({"id": did}, {"_id": 0})


@router.post("/admin/deliveries/{did}/cancel")
async def admin_cancel_delivery(did: str, payload: dict, request: Request) -> Any:
    actor = await require_permission(request, "deliveries")
    d = await db.deliveries.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="No encontrado")
    if d["status"] in ("confirmed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Ya está {d['status']}")
    # OP01/MEN22 — la cancelación debe ligarse al CICLO y ESTADO que VIO el
    # operador, no al que lee el servidor. Por eso AMBOS campos son OBLIGATORIOS:
    #  - `expected_status`: el estado observado en la tarjeta (p. ej. available).
    #  - `expected_uid`: el ciclo observado (puede ser null si la entrega no
    #    tenía ciclo). La AUSENCIA de la clave NO es válida: sin declarar lo que
    #    se vio no se puede autorizar una escritura condicionada. Esto cierra el
    #    hueco por el que un cliente podía omitir los campos y saltarse el CAS.
    # Una reasignación de reserva conserva status=available pero cambia
    # `assignment_uid`; y una aceptación cambia el estado conservando el uid.
    # Se conserva la protección contra confirmación/comisión (`payout_credited`).
    expected_status = payload.get("expected_status")
    if not isinstance(expected_status, str) or expected_status not in _CANCELABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=("expected_status inválido o ausente: declara el estado "
                    "observado en la tarjeta (available, accepted, on_the_way, "
                    "arrived o delivered)."))
    if "expected_uid" not in payload:
        raise HTTPException(
            status_code=400,
            detail=("Falta expected_uid: la cancelación debe declarar el ciclo "
                    "observado (o null si la entrega no tenía ciclo)."))
    # MEN23 — rechaza no-escalares ANTES de construir el filtro: un objeto/array
    # (p. ej. {"$ne": "confirmed"}) se interpretaría como OPERADOR de consulta y
    # debilitaría la igualdad de estado/ciclo que el CAS debe exigir.
    _validate_expected_uid(payload)
    euid = payload.get("expected_uid")
    note_raw = payload.get("note")
    if note_raw is not None and not isinstance(note_raw, str):
        raise HTTPException(status_code=400,
                            detail="note inválido: debe ser texto.")
    note = (note_raw or "")[:200]
    return await _execute_cancel(did, d, actor, note=note,
                                 expected_status=expected_status, euid=euid)


@router.post("/admin/deliveries/cancel-overdue")
async def admin_cancel_overdue(request: Request) -> Any:
    """Cancelación masiva de las entregas que superan el SLA: tras la
    confirmación del admin, cancela cada entrega vencida y devuelve el
    dinero/mercancía al origen (reusa el núcleo de cancelación individual).
    Omite las que cambiaron de estado/ciclo entre tanto (409) sin abortar."""
    actor = await require_permission(request, "deliveries")
    from services.deliveries import find_attention_items
    items = await find_attention_items()
    overdue = items.get("overdue", [])
    sla_hours = items["thresholds"]["sla_hours"]
    sla_label = (f"{int(sla_hours)}" if float(sla_hours).is_integer()
                 else f"{sla_hours:g}")
    cancelled = 0
    skipped: list = []
    for od in overdue:
        d = await db.deliveries.find_one({"id": od["id"]}, {"_id": 0})
        if not d:
            skipped.append({"id": od["id"], "reason": "not_found"})
            continue
        if d["status"] not in _CANCELABLE_STATUSES:
            skipped.append({"id": od["id"], "reason": f"status_{d['status']}"})
            continue
        try:
            await _execute_cancel(
                d["id"], d, actor,
                note=f"Cancelación automática por superar el SLA de {sla_label} h",
                expected_status=d["status"], euid=d.get("assignment_uid"))
            cancelled += 1
        except HTTPException as e:
            skipped.append({"id": od["id"], "reason": f"conflict_{e.status_code}"})
        except Exception as e:
            logger.error(f"cancel-overdue failed for {od['id']}: {e}")
            skipped.append({"id": od["id"], "reason": "error"})
    await log_action(db, actor, "delivery.cancel_overdue_bulk", "delivery", "",
                     summary=f"Cancelación masiva por SLA: {cancelled} entrega(s)",
                     details={"cancelled": cancelled, "skipped": len(skipped),
                              "sla_hours": sla_hours})
    return {"cancelled": cancelled, "skipped": skipped, "total": len(overdue)}
