"""iter199 — courier deliveries (Fase 2).

One `deliveries` document per physical delivery job (cash withdrawal or
marketplace redemption). Created automatically when a courier fee is charged
and manually (admin) for FREE deliveries (≥ free threshold).

Earnings split: courier gets `courier_share_pct` (default 80%) of the fee,
platform keeps the rest. The courier share is credited to the courier's
in-platform USDT balance when STAFF confirms the delivered job.
"""
import logging
import secrets
import uuid
from typing import Any, Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import iso, now_utc

logger = logging.getLogger("deliveries")

ACTIVE_STATUSES = ("available", "accepted", "on_the_way", "arrived", "delivered")

# MSG03 — colecciones de origen y estados terminales que cierran mensajería.
REF_COLLS = {"withdrawal": "withdrawals", "redemption": "redemptions",
             "deposit": "deposits"}
TERMINAL_REF_STATUSES = ("rejected", "cancelled")

# Mejora #4 — umbrales de atención del despacho (minutos).
RESERVATION_STALL_MIN = 30
ACTIVE_STALL_MIN = 90


async def find_attention_items() -> dict:
    """Mejora #4 — reservas sin respuesta y trabajos detenidos que necesitan
    intervención del operador."""
    from datetime import timedelta
    now_dt = now_utc()
    res_cutoff = iso(now_dt - timedelta(minutes=RESERVATION_STALL_MIN))
    act_cutoff = iso(now_dt - timedelta(minutes=ACTIVE_STALL_MIN))
    fields = {"_id": 0, "id": 1, "kind": 1, "client_name": 1,
              "amount_label": 1, "status": 1, "assigned_to_courier_id": 1,
              "courier_name": 1, "courier_id": 1, "updated_at": 1,
              "created_at": 1}
    unanswered = await db.deliveries.find(
        {"status": "available",
         "assigned_to_courier_id": {"$nin": [None, ""]},
         "updated_at": {"$lt": res_cutoff}},
        fields).sort("updated_at", 1).to_list(50)
    stalled = await db.deliveries.find(
        {"status": {"$in": ["accepted", "on_the_way", "arrived"]},
         "updated_at": {"$lt": act_cutoff}},
        fields).sort("updated_at", 1).to_list(50)
    return {"unanswered_reservations": unanswered, "stalled": stalled,
            "thresholds": {"reservation_min": RESERVATION_STALL_MIN,
                           "active_min": ACTIVE_STALL_MIN}}


async def alert_attention_items() -> int:
    """Mejora #4 — alerta a los admins UNA sola vez por entrega y condición
    (claim atómico por flag); corre en el scheduler cada 10 min."""
    items = await find_attention_items()
    n = 0
    try:
        from admin_alerts import notify_all_admins
    except Exception:
        return 0
    for d in items["unanswered_reservations"]:
        claim = await db.deliveries.update_one(
            {"id": d["id"], "status": "available",
             "reservation_alerted": {"$ne": True}},
            {"$set": {"reservation_alerted": True}})
        if claim.modified_count:
            try:
                await notify_all_admins(
                    db,
                    title="⏰ Reserva de mensajería sin respuesta",
                    body=(f"La entrega #{d['id'][:8]} de {d.get('client_name', '')} "
                          f"lleva más de {RESERVATION_STALL_MIN} min reservada "
                          "sin que el mensajero la acepte. Reasígnala o libérala."),
                    url_path="/admin/deliveries")
            except Exception as e:
                logger.error(f"reservation alert failed: {e}")
            n += 1
    for d in items["stalled"]:
        claim = await db.deliveries.update_one(
            {"id": d["id"], "stall_alerted": {"$ne": True}},
            {"$set": {"stall_alerted": True}})
        if claim.modified_count:
            try:
                await notify_all_admins(
                    db,
                    title="🛑 Entrega detenida",
                    body=(f"La entrega #{d['id'][:8]} de {d.get('client_name', '')} "
                          f"({d.get('courier_name') or 'sin nombre'}) lleva más de "
                          f"{ACTIVE_STALL_MIN} min sin avanzar de "
                          f"«{d.get('status')}». Contacta al mensajero."),
                    url_path="/admin/deliveries")
            except Exception as e:
                logger.error(f"stall alert failed: {e}")
            n += 1
    return n


def gen_delivery_pin() -> str:
    """Mejora #2 auditoría — PIN de entrega de un solo uso (4 dígitos),
    visible solo para el cliente; el mensajero lo pide al entregar."""
    return f"{secrets.randbelow(10000):04d}"


async def ensure_indexes() -> None:
    """MSG02 — identidad única de trabajo ACTIVO por (kind, ref_id).
    `active_key` existe solo mientras el trabajo no está cancelado; el índice
    único (sparse) cierra atómicamente la ventana buscar→insertar. La
    migración marca duplicados históricos sin romperlos."""
    rows = await db.deliveries.find(
        {"status": {"$ne": "cancelled"}, "active_key": {"$exists": False}},
        {"_id": 0, "id": 1, "kind": 1, "ref_id": 1, "updated_at": 1},
    ).to_list(5000)
    groups: dict = {}
    for r in rows:
        groups.setdefault(f"{r.get('kind')}:{r.get('ref_id')}", []).append(r)
    for key, docs in groups.items():
        docs.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
        await db.deliveries.update_one({"id": docs[0]["id"]},
                                       {"$set": {"active_key": key}})
        for dup in docs[1:]:
            logger.warning("[deliveries] duplicado activo histórico "
                           "detectado en migración: %s (%s)", dup["id"], key)
            await db.deliveries.update_one(
                {"id": dup["id"]}, {"$set": {"dup_active_legacy": True}})
    await db.deliveries.create_index("active_key", unique=True, sparse=True)
    # Mejora #2 — backfill de PIN para trabajos activos previos a la feature.
    rows2 = await db.deliveries.find(
        {"status": {"$in": ["available", "accepted", "on_the_way", "arrived"]},
         "delivery_pin": {"$exists": False}},
        {"_id": 0, "id": 1}).to_list(2000)
    for r2 in rows2:
        await db.deliveries.update_one(
            {"id": r2["id"], "delivery_pin": {"$exists": False}},
            {"$set": {"delivery_pin": gen_delivery_pin(),
                      "pin_verified": False}})
    # Mejora #1 — índices del ledger de efectivo por mensajero.
    from services.courier_cash import ensure_indexes as cash_indexes
    await cash_indexes()


async def publish_delivery_event(delivery_id: str, status: str,
                                 courier_ids: Optional[list] = None) -> None:
    """MSG10 — evento SSE `delivery_changed` para que los paneles de
    mensajería se refresquen sin recarga manual. Best-effort."""
    try:
        from services.live_bus import publish as live_publish
        ids = courier_ids
        if ids is None:
            rows = await db.users.find({"is_courier": True},
                                       {"_id": 0, "user_id": 1}).to_list(500)
            ids = [r["user_id"] for r in rows]
        for uid in set(x for x in ids if x):
            await live_publish("delivery_changed",
                               {"delivery_id": delivery_id, "status": status},
                               user_id=uid)
    except Exception as e:
        logger.error(f"delivery event publish failed: {e}")


async def get_share_pct() -> float:
    doc = await db.settings.find_one({"id": "global"},
                                     {"_id": 0, "courier_share_pct": 1}) or {}
    raw = doc.get("courier_share_pct")
    return float(raw) if raw is not None else 80.0


def compute_shares(fee_usdt: float, share_pct: float) -> tuple:
    courier = round(float(fee_usdt) * share_pct / 100.0, 2)
    platform = round(float(fee_usdt) - courier, 2)
    return courier, platform


def _ref_display(kind: str, ref: dict) -> dict:
    if kind == "withdrawal":
        # `details` is a formatted string on modern cash withdrawals but a
        # dict on some older/imported docs — support both (iter199 bugfix).
        raw = ref.get("details")
        if isinstance(raw, dict):
            parts = [raw.get("receiver_name"), raw.get("address"),
                     raw.get("phone")]
            address = " — ".join(str(p) for p in parts if p)
        else:
            address = str(raw or "")
        return {
            "user_id": ref.get("user_id"),
            "client_name": ref.get("user_name") or "",
            "address": address,
            "province": ref.get("province"),
            # Mejora #7 (Fase C) — destino estructurado: receptor, teléfono y
            # municipio por separado, sin deducirlos del texto concatenado.
            "receiver_name": (ref.get("receiver_name")
                              or ref.get("beneficiary_name") or ""),
            "receiver_phone": ref.get("receiver_phone") or "",
            "municipality": ref.get("courier_municipality"),
            "amount_label": f"{ref.get('amount_usd', 0)} {ref.get('currency', '')}",
        }
    if kind == "deposit":
        # iter208 — cash-courier deposit: the courier goes to the client's
        # address to PICK UP the cash. Compose the same address block used
        # for withdrawals so the courier gets everything in one glance.
        parts = [ref.get("contact_name"), ref.get("pickup_address"),
                 ref.get("pickup_phone")]
        address = " — ".join(str(p) for p in parts if p)
        return {
            "user_id": ref.get("user_id"),
            "client_name": ref.get("user_name") or "",
            "address": address,
            "province": None,
            "receiver_name": ref.get("contact_name") or "",
            "receiver_phone": ref.get("pickup_phone") or "",
            "municipality": ref.get("courier_municipality"),
            "amount_label": (
                f"Recoger {ref.get('amount', 0)} {ref.get('currency', '')}"
            ),
        }
    return {
        "user_id": ref.get("user_id"),
        "client_name": ref.get("user_name") or "",
        "address": ref.get("delivery_address") or "",
        "province": None,
        "receiver_name": (ref.get("receiver_name")
                          or ref.get("user_name") or ""),
        "receiver_phone": ref.get("receiver_phone") or "",
        "municipality": ref.get("courier_municipality"),
        "amount_label": f"{ref.get('product_name', '')} ×{ref.get('quantity', 1)}",
    }


async def build_delivery_doc(kind: str, ref: dict, *, km: float, fee_usdt: float,
                             created_by: Optional[str] = None) -> dict:
    share_pct = await get_share_pct()
    courier_share, platform_share = compute_shares(fee_usdt, share_pct)
    disp = _ref_display(kind, ref)
    now = iso(now_utc())
    return {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "ref_id": ref["id"],
        "active_key": f"{kind}:{ref['id']}",
        "user_id": disp["user_id"],
        "client_name": disp["client_name"],
        "address": disp["address"],
        "province": disp["province"],
        "municipality": disp.get("municipality"),
        "receiver_name": disp.get("receiver_name") or "",
        "receiver_phone": disp.get("receiver_phone") or "",
        "amount_label": disp["amount_label"],
        "delivery_latitude": ref.get("delivery_latitude"),
        "delivery_longitude": ref.get("delivery_longitude"),
        "km": float(km or 0),
        "fee_usdt": float(fee_usdt or 0),
        "share_pct_snapshot": share_pct,
        "courier_share_usdt": courier_share,
        "platform_share_usdt": platform_share,
        "status": "available",
        "courier_id": None,
        "courier_name": None,
        "delivery_pin": gen_delivery_pin(),
        "pin_verified": False,
        "payout_credited": False,
        "payout_credited_at": None,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
        "timeline": [{"status": "available", "at": now, "by": created_by}],
    }


async def _broadcast_new_delivery_to_couriers(doc: dict) -> None:
    """iter208 — Cuando aparece una NUEVA entrega disponible, hace push a
    todos los mensajeros activos para que vean al toque el trabajo y puedan
    aceptarlo antes que otro. Best-effort, nunca rompe el flujo principal."""
    try:
        from push_service import (
            send_push_to_user, build_generic_admin_alert_payload,
        )
        share = float(doc.get("courier_share_usdt") or 0)
        is_pickup = doc.get("kind") == "deposit"
        title = ("🛵 Nueva recogida disponible" if is_pickup
                 else "🛵 Nueva entrega disponible")
        share_line = (f" · Ganas {share} USDT" if share > 0 else "")
        body = (f"{doc.get('client_name', '')} · {doc.get('amount_label', '')}"
                f"{share_line}")
        payload = build_generic_admin_alert_payload(
            title=title, body=body,
            url="/dashboard/deliveries",
            tag=f"delivery-new-{doc['id']}",
        )
        couriers = await db.users.find(
            {"is_courier": True},
            {"_id": 0, "user_id": 1},
        ).to_list(500)
        for c in couriers:
            try:
                await send_push_to_user(db, c["user_id"], payload)
            except Exception:
                pass
        # MSG10 — evento en vivo para que el panel abierto se refresque solo.
        await publish_delivery_event(doc["id"], "available",
                                     courier_ids=[c["user_id"] for c in couriers])
    except Exception as e:
        # Nunca dejamos que un error de push impida crear la entrega.
        import logging
        logging.error(f"broadcast new delivery push failed: {e}")


async def ensure_delivery_job(kind: str, ref: dict, *, km: float,
                              fee_usdt: float,
                              actor_id: Optional[str] = None) -> Any:
    """iter205 — crea el trabajo si no existe (permite fee 0: las entregas
    GRATIS ≥ umbral siguen requiriendo mensajero). No toca trabajos activos."""
    active = await db.deliveries.find_one(
        {"kind": kind, "ref_id": ref["id"], "status": {"$ne": "cancelled"}},
        {"_id": 0},
    )
    if active:
        return active
    doc = await build_delivery_doc(kind, ref, km=km, fee_usdt=fee_usdt,
                                   created_by=actor_id)
    try:
        await db.deliveries.insert_one(dict(doc))
    except DuplicateKeyError:
        # MSG02 — otra petición ganó la creación: devolver el MISMO trabajo.
        return await db.deliveries.find_one(
            {"active_key": doc["active_key"]}, {"_id": 0})
    # iter208 — broadcast a mensajeros disponibles.
    await _broadcast_new_delivery_to_couriers(doc)
    return doc


async def cancel_active_delivery(kind: str, ref_id: str,
                                 actor_id: Optional[str] = None,
                                 note: str = "") -> None:
    """iter205 — cancela el trabajo activo (no confirmado) cuando la
    operación origen muere (retiro/canje rechazado o cancelado)."""
    now = iso(now_utc())
    await db.deliveries.update_one(
        {"kind": kind, "ref_id": ref_id,
         "status": {"$nin": ["cancelled", "confirmed"]},
         "payout_credited": {"$ne": True}},
        {"$set": {"status": "cancelled", "updated_at": now},
         "$unset": {"active_key": ""},
         "$push": {"timeline": {"status": "cancelled", "at": now,
                                "by": actor_id, "note": note}}},
    )


async def handle_origin_rejected(kind: str, ref_id: str,
                                 actor_id: Optional[str] = None,
                                 note: str = "") -> Optional[str]:
    """MSG03 — propaga el rechazo/cancelación del origen a su trabajo de
    mensajería. Antes del movimiento físico → cancela el trabajo; si el
    mensajero ya entregó/recogió → NO se oculta el movimiento: queda una
    incidencia visible que exige resolución."""
    d = await db.deliveries.find_one(
        {"kind": kind, "ref_id": ref_id, "status": {"$ne": "cancelled"}},
        {"_id": 0, "id": 1, "status": 1, "courier_id": 1,
         "assigned_to_courier_id": 1})
    if not d:
        return None
    if d["status"] in ("delivered", "confirmed"):
        await flag_origin_conflict(d["id"], kind, ref_id,
                                   note or "origen rechazado")
        return "conflict"
    await cancel_active_delivery(kind, ref_id, actor_id=actor_id, note=note)
    await publish_delivery_event(
        d["id"], "cancelled",
        courier_ids=None if d["status"] == "available"
        else [d.get("courier_id"), d.get("assigned_to_courier_id")])
    return "cancelled"


async def flag_origin_conflict(did: str, kind: str, ref_id: str,
                               note: str) -> None:
    """MSG03 — incidencia única y trazable: la entrega tuvo movimiento
    físico pero su origen quedó rechazado/cancelado."""
    now = iso(now_utc())
    res = await db.deliveries.update_one(
        {"id": did, "origin_conflict": {"$exists": False}},
        {"$set": {"origin_conflict": {"kind": kind, "ref_id": ref_id,
                                      "note": note, "at": now}},
         "$push": {"timeline": {"status": "origin_conflict", "at": now,
                                "by": None, "note": note}}})
    if res.modified_count:
        try:
            from admin_alerts import notify_all_admins
            await notify_all_admins(
                db,
                title="⚠️ Incidencia: entrega con origen incompatible",
                body=(f"La entrega {did[:8]} ({kind} {ref_id[:8]}) registra "
                      "un movimiento físico pero su operación de origen fue "
                      f"rechazada/cancelada ({note}). Revisa el efectivo/"
                      "producto y resuelve la incidencia."),
                url_path="/admin/deliveries")
        except Exception as e:
            logger.error(f"origin conflict notify failed: {e}")


async def upsert_delivery_for_charge(kind: str, ref: dict, *, km: float,
                                     fee_usdt: float,
                                     actor_id: Optional[str] = None) -> Any:
    """Keep the delivery job in sync with its courier-fee charge.
    fee > 0 → create/update the active job. fee == 0 (annulled) → cancel it.
    A confirmed job is history and is never rewritten."""
    active = await db.deliveries.find_one(
        {"kind": kind, "ref_id": ref["id"], "status": {"$ne": "cancelled"}},
        {"_id": 0},
    )
    now = iso(now_utc())
    if fee_usdt <= 0:
        if active and active["status"] != "confirmed":
            await db.deliveries.update_one(
                {"id": active["id"],
                 "status": {"$nin": ["confirmed", "cancelled"]}}, {
                    "$set": {"status": "cancelled", "updated_at": now},
                    "$unset": {"active_key": ""},
                    "$push": {"timeline": {"status": "cancelled", "at": now,
                                           "by": actor_id, "note": "cobro anulado"}},
                })
        return None
    if active:
        if active["status"] == "confirmed":
            return active
        share_pct = await get_share_pct()
        courier_share, platform_share = compute_shares(fee_usdt, share_pct)
        # MSG05 — la actualización exige que el trabajo NO haya sido
        # confirmado/cancelado después de la lectura: una sincronización
        # atrasada jamás reescribe un pago histórico.
        res = await db.deliveries.update_one(
            {"id": active["id"],
             "status": {"$nin": ["confirmed", "cancelled"]}}, {"$set": {
                "km": float(km or 0), "fee_usdt": float(fee_usdt),
                "share_pct_snapshot": share_pct,
                "courier_share_usdt": courier_share,
                "platform_share_usdt": platform_share,
                "updated_at": now,
            }})
        if res.matched_count == 0:
            cur = await db.deliveries.find_one({"id": active["id"]}, {"_id": 0})
            if (cur or {}).get("status") == "confirmed" \
                    and float((cur or {}).get("courier_share_usdt") or 0) != courier_share:
                # El cobro de la tarifa ya ganó pero la confirmación pagó con
                # el dato anterior: registrar el conflicto como ajuste
                # separado, sin tocar el pago.
                await _flag_fee_conflict(active["id"], float(fee_usdt),
                                         courier_share, now)
            return cur
        return await db.deliveries.find_one({"id": active["id"]}, {"_id": 0})
    doc = await build_delivery_doc(kind, ref, km=km, fee_usdt=fee_usdt,
                                   created_by=actor_id)
    try:
        await db.deliveries.insert_one(dict(doc))
    except DuplicateKeyError:
        # MSG02 — otra petición creó el trabajo primero: converger sobre él.
        return await upsert_delivery_for_charge(kind, ref, km=km,
                                                fee_usdt=fee_usdt,
                                                actor_id=actor_id)
    # iter208 — broadcast a mensajeros cuando aparece una nueva disponible.
    await _broadcast_new_delivery_to_couriers(doc)
    return doc


async def _flag_fee_conflict(did: str, fee_usdt: float, courier_share: float,
                             now: str) -> None:
    """MSG05 — la tarifa cambió después de confirmar y pagar: el pago
    histórico se conserva y la diferencia queda como ajuste pendiente
    trazable (una sola vez), con aviso a los admins."""
    res = await db.deliveries.update_one(
        {"id": did, "fee_adjustment_pending": {"$exists": False}},
        {"$set": {"fee_adjustment_pending": {
            "fee_usdt": float(fee_usdt),
            "courier_share_usdt": float(courier_share), "at": now}},
         "$push": {"timeline": {
             "status": "fee_conflict", "at": now, "by": None,
             "note": (f"La tarifa cambió a {fee_usdt} USDT después de "
                      "confirmar y pagar — requiere ajuste manual.")}}})
    if res.modified_count:
        try:
            from admin_alerts import notify_all_admins
            await notify_all_admins(
                db,
                title="⚠️ Conflicto de tarifa en entrega confirmada",
                body=(f"La entrega {did[:8]} ya estaba confirmada y pagada "
                      f"cuando llegó una tarifa nueva de {fee_usdt} USDT. "
                      "El pago histórico NO fue modificado; revisa si "
                      "corresponde un ajuste."),
                url_path="/admin/deliveries")
        except Exception as e:
            logger.error(f"fee conflict notify failed: {e}")


async def sync_delivery_from_doc(coll_name: str, doc_id: str,
                                 actor_id: Optional[str] = None) -> None:
    """MSG04 — sincronización durable cobro↔reparto: lee SIEMPRE el estado
    vigente del documento (tarifa/km actuales) y converge el trabajo de
    mensajería a ese estado. Idempotente; al terminar limpia la tarea
    `delivery_sync_pending` publicada junto con la decisión del cobro."""
    kind = {"withdrawals": "withdrawal", "redemptions": "redemption"}[coll_name]
    doc = await db[coll_name].find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return
    pending_op = (doc.get("delivery_sync_pending") or {}).get("op_id")
    if doc.get("status") in TERMINAL_REF_STATUSES:
        await handle_origin_rejected(kind, doc_id, actor_id=actor_id,
                                     note=f"origen {doc.get('status')}")
    else:
        km = float(doc.get("courier_km") or 0)
        fee = float(doc.get("courier_fee_usdt") or 0)
        await upsert_delivery_for_charge(kind, doc, km=km, fee_usdt=fee,
                                         actor_id=actor_id)
    # Solo se cierra la tarea que ESTA sincronización leyó: una tarea más
    # nueva (otro cobro concurrente) queda viva para su propio sync/healer.
    if pending_op:
        await db[coll_name].update_one(
            {"id": doc_id, "delivery_sync_pending.op_id": pending_op},
            {"$unset": {"delivery_sync_pending": ""}})


async def heal_delivery_sync(cutoff: str) -> int:
    """MSG04 — completa sincronizaciones de reparto interrumpidas: tras
    cualquier corte, crea o actualiza exactamente un reparto con la tarifa
    vigente, sin volver a cobrar."""
    n = 0
    for coll_name in ("withdrawals", "redemptions"):
        rows = await db[coll_name].find(
            {"delivery_sync_pending.at": {"$lt": cutoff}},
            {"_id": 0, "id": 1}).to_list(100)
        for row in rows:
            try:
                await sync_delivery_from_doc(coll_name, row["id"])
                n += 1
                logger.warning("sincronización de reparto completada por el "
                               "healer: %s %s", coll_name, row["id"])
            except Exception as e:
                logger.error("delivery sync heal %s/%s: %s",
                             coll_name, row["id"], e)
    return n


async def do_confirm_delivery(d: dict, actor: dict) -> Any:
    """Núcleo de la confirmación (payout + sello + sync). Compartido por el
    endpoint admin (routes/deliveries) y la sincronización al marcar el
    retiro 'Entregado' (routes/admin_withdrawals, iter215) — el TOTP ya fue
    verificado por el caller. Movido aquí para romper el ciclo de imports
    entre esos dos módulos de rutas."""
    from audit_log import log_action

    did = d["id"]
    now = iso(now_utc())
    share = float(d.get("courier_share_usdt") or 0)
    credited = False
    # iter249 — claim atómico del payout + intención de abono en el MISMO
    # update: dos confirmaciones simultáneas no pueden pagar dos veces al
    # mensajero, y si el proceso muere antes de abonar, el healer completa.
    # ME02 — el claim exige que la entrega SIGA en 'delivered': una
    # cancelación concurrente que ya la movió deja esta confirmación
    # obsoleta con conflicto (sin pagar comisión).
    if share > 0 and d.get("courier_id"):
        from services.credit_recovery import pending_marker, apply_and_clear
        marker = pending_marker(d["courier_id"], "USDT", share, "courier-share")
        # MSG05 — el claim también exige que la comisión leída siga vigente:
        # el importe liquidado queda CONGELADO en courier_share_paid_usdt.
        claim = await db.deliveries.update_one(
            {"id": did, "status": "delivered",
             "courier_share_usdt": share,
             "payout_credited": {"$ne": True}},
            {"$set": {"payout_credited": True, "payout_credited_at": now,
                      "courier_share_paid_usdt": share,
                      "credit_pending": marker}})
        if claim.modified_count:
            await apply_and_clear("deliveries", did, marker)
            credited = True
        else:
            cur_d = await db.deliveries.find_one(
                {"id": did}, {"_id": 0, "payout_credited": 1, "status": 1,
                              "courier_share_usdt": 1})
            if not (cur_d or {}).get("payout_credited"):
                if float((cur_d or {}).get("courier_share_usdt") or 0) != share:
                    raise HTTPException(
                        status_code=409,
                        detail=("La tarifa de esta entrega cambió mientras "
                                "confirmabas — recarga y vuelve a confirmar "
                                "con el importe vigente."))
                raise HTTPException(
                    status_code=409,
                    detail=("La entrega cambió de estado (¿cancelada?) — "
                            "no se confirmó ni se pagó la comisión."))
    # ME03 — la liquidación del documento vinculado (depósito/retiro) queda
    # registrada como TAREA PENDIENTE en el propio sello: si falla, el
    # recuperador la completa; la respuesta indica si quedó pendiente.
    seal_sets = {"status": "confirmed", "updated_at": now}
    kind = d.get("kind") or ""
    if d.get("ref_id"):
        seal_sets["settlement_pending"] = {"kind": kind,
                                           "ref_id": d["ref_id"], "at": now}
    seal = await db.deliveries.update_one(
        {"id": did, "status": "delivered"},
        {"$set": seal_sets,
         "$push": {"timeline": {"status": "confirmed", "at": now,
                                "by": actor["user_id"]}}})
    if seal.matched_count == 0:
        cur_d = await db.deliveries.find_one({"id": did},
                                             {"_id": 0, "status": 1})
        if (cur_d or {}).get("status") != "confirmed":
            raise HTTPException(
                status_code=409,
                detail=("La entrega ya no está en estado 'entregada' — "
                        "no se pudo confirmar."))
    await log_action(db, actor, "delivery.confirm", "delivery", did,
                     summary=(f"Entrega {did[:8]} confirmada — {share} USDT "
                              f"acreditados a {d.get('courier_name', '')}"),
                     details={"courier_id": d.get("courier_id"),
                              "courier_share_usdt": share, "credited": credited})
    # iter209b — Sincronizar la operación vinculada: al confirmar la entrega,
    # el retiro cash pasa a 'paid' y el depósito cash-courier se confirma
    # (acredita saldo). Así Depósitos y Retiros no queda "pendiente".
    # Vía registro de handlers para no importar routes desde services.
    try:
        from services.delivery_settlement import (settle_linked_operation,
                                                  OriginConflict)
        try:
            await settle_linked_operation(kind, d["ref_id"], actor)
            await db.deliveries.update_one(
                {"id": did, "settlement_pending.ref_id": d["ref_id"]},
                {"$unset": {"settlement_pending": ""}})
        except OriginConflict as oc:
            # MSG03 — el origen ya no es compatible: la sincronización NO se
            # cierra como resuelta; queda una incidencia visible.
            await db.deliveries.update_one(
                {"id": did, "settlement_pending.ref_id": d["ref_id"]},
                {"$unset": {"settlement_pending": ""}})
            await flag_origin_conflict(did, kind, d["ref_id"], str(oc))
    except Exception as e:
        logger.error(f"ref sync after delivery confirm failed (queda "
                     f"pendiente para el recuperador): {e}")
    # MSG10 — el panel del mensajero se entera de la confirmación en vivo.
    if d.get("courier_id"):
        await publish_delivery_event(did, "confirmed",
                                     courier_ids=[d["courier_id"]])
    if credited:
        try:
            from routes.notifications import _insert_notification
            await _insert_notification(
                recipient_user_id=d["courier_id"], type="delivery_confirmed",
                title="Entrega confirmada — pago acreditado",
                message=(f"Tu entrega de {d.get('client_name', '')} fue confirmada. "
                         f"Se acreditaron {share} USDT a tu saldo."),
                data={"delivery_id": did, "credited_usdt": share})
            from services.live_bus import publish as live_publish
            await live_publish("balance_updated",
                               {"reason": "delivery_payout", "delivery_id": did},
                               user_id=d["courier_id"])
        except Exception as e:
            logger.error(f"confirm notify failed: {e}")
    return await db.deliveries.find_one({"id": did}, {"_id": 0})
