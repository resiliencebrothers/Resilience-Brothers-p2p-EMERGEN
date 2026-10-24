"""Mejora #1 auditoría eeed556 — Control de efectivo por mensajero.

Ledger `courier_cash_events`: cada movimiento de efectivo, vinculado al
reparto cuando aplica. Pendiente de rendición por mensajero+moneda =
(issued + collected) − (delivered_to_recipient + returned).
Eventos automáticos idempotentes por `op_key` (índice único sparse).
"""
import logging
import math
import re
import uuid
from typing import Any, Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import iso, now_utc

logger = logging.getLogger("courier_cash")

EVENT_KINDS = ("issued", "collected", "delivered_to_recipient", "returned")

# EF01 — fecha a partir de la cual entregar/devolver efectivo al mensajero
# MUEVE la caja física (traslado de custodia). Lo anterior se liquidó fuera
# del sistema; no se reproduce contra la caja para no duplicar ajustes ya
# hechos (decisión del operador: "solo de aquí en adelante").
CUSTODY_EPOCH = "2026-10-24"


async def physical_cash_currencies() -> set:
    """EF04 — monedas de efectivo FÍSICO configuradas (con denominaciones).
    El formulario de efectivo solo acepta estas; evita texto libre como 'XYZ'."""
    from services.denominations import get_cash_denominations
    return set((await get_cash_denominations()).keys())


async def get_or_create_courier_custody_account(courier_id: str,
                                                courier_name: str,
                                                currency: str) -> dict:
    """EF01 — cuenta de fondos que representa el efectivo EN TRÁNSITO en poder
    de un mensajero, por moneda. No es la caja de la empresa (no lleva
    `system_purpose`), así que un traslado caja→custodia baja la caja física y
    sube la custodia conservando el total. Idempotente por (mensajero, moneda)."""
    from services.currency_utils import norm_code as _norm_code
    code = _norm_code(currency)
    safe = re.sub(r"[^A-Za-z0-9]", "", str(courier_id))[:20]
    acc_id = f"facc_cc_{safe}_{code}"
    fa = await db.fund_accounts.find_one(
        {"courier_custody_id": courier_id, "currency": code}, {"_id": 0})
    if fa:
        if not fa.get("is_active", True):
            await db.fund_accounts.update_one(
                {"id": fa["id"]}, {"$set": {"is_active": True}})
        return {"id": fa["id"], "label": fa.get("name") or fa["id"]}
    doc = {
        "id": acc_id,
        "name": f"Custodia mensajero · {courier_name or courier_id}",
        "currency": code,
        "method": "cash",
        "courier_custody_id": courier_id,
        "note": "Efectivo en tránsito en poder del mensajero (auto-creada)",
        "is_active": True,
        "created_at": iso(now_utc()),
        "created_by_id": "system",
        "created_by_name": "Sistema",
    }
    await db.fund_accounts.update_one(
        {"courier_custody_id": courier_id, "currency": code},
        {"$setOnInsert": doc}, upsert=True)
    fa = await db.fund_accounts.find_one(
        {"courier_custody_id": courier_id, "currency": code}, {"_id": 0})
    return {"id": fa["id"], "label": fa.get("name") or fa["id"]}


async def issue_or_return_cash(*, courier_id: str, courier_name: str,
                               kind: str, currency: str, amount: Any,
                               account_id: str, note: str = "",
                               discrepancy_note: str = "",
                               actor_id: str, actor_name: str = "",
                               op_key: Optional[str] = None) -> dict:
    """EF01/EF02/EF03 — entrega (`issued`) o rendición (`returned`) de efectivo
    como TRASLADO DE CUSTODIA entre la cuenta de caja elegida y la custodia del
    mensajero, conservando el total. Valida disponibilidad de forma atómica
    (bloquea si no alcanza) e idempotente por `op_key`."""
    if kind not in ("issued", "returned"):
        raise HTTPException(status_code=400, detail="kind inválido")
    try:
        amt = round(float(amount), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Importe inválido")
    if not math.isfinite(amt) or amt <= 0 or amt > 100_000_000:
        raise HTTPException(status_code=400, detail="Importe inválido")

    from services.currency_utils import norm_code as _norm_code
    code = _norm_code(currency)
    if not code:
        raise HTTPException(status_code=400, detail="Moneda inválida")
    if code not in await physical_cash_currencies():
        raise HTTPException(
            status_code=400,
            detail=f"«{code}» no es una moneda de efectivo física configurada")

    from services.fund_accounts import (resolve_payout_account,
                                         account_assigned_balances)
    account = await resolve_payout_account(account_id, code)  # existe/activa/moneda
    custody = await get_or_create_courier_custody_account(
        courier_id, courier_name, code)
    if account["id"] == custody["id"]:
        raise HTTPException(status_code=400,
                            detail="Cuenta de caja inválida")

    # EF03 — idempotencia: si el traslado de este op_key ya existe, no se
    # repite (reintento tras respuesta perdida).
    if op_key:
        dup = await db.fund_account_transfers.find_one(
            {"operation_id": op_key, "currency": code,
             "status": {"$nin": ["pending", "aborted"]}}, {"_id": 0})
        existing_ev = await db.courier_cash_events.find_one(
            {"op_key": op_key}, {"_id": 0})
        if dup and existing_ev:
            return {"event": existing_ev, "transfer": dup}

    from services import company_fund_budget as fund_budget
    from services.cash_box_sync import mirror_fund_transfer_to_cash_box
    lock = await fund_budget.acquire_pay_lock_wait(code)
    if not lock:
        raise HTTPException(
            status_code=409,
            detail=(f"Otra operación del fondo {code} está en curso; "
                    "inténtalo de nuevo en unos segundos."))
    try:
        if kind == "issued":
            frm, to = account["id"], custody["id"]
            frm_label, to_label = account["label"], custody["label"]
            assigned = await account_assigned_balances(code)
            avail = round(assigned.get(account["id"], 0.0), 2)
            if amt > avail + 1e-9:
                raise HTTPException(
                    status_code=400,
                    detail=(f"Saldo insuficiente en «{account['label']}»: "
                            f"disponible {avail:.2f} {code}"))
        else:  # returned
            frm, to = custody["id"], account["id"]
            frm_label, to_label = custody["label"], account["label"]
            held = 0.0
            for row in await cash_pending(courier_id):
                if row["currency"] == code:
                    held = round(float(row["pending"]), 2)
                    break
            if amt > held + 1e-9:
                raise HTTPException(
                    status_code=400,
                    detail=(f"El mensajero solo tiene {held:.2f} {code} "
                            "por rendir; no puede devolver más."))

        doc = {
            "id": str(uuid.uuid4()), "currency": code,
            "from_account_id": frm, "from_label": frm_label,
            "to_account_id": to, "to_label": to_label,
            "amount": amt,
            "note": (f"Efectivo mensajero: {note}".strip())[:200],
            "denominations": None,
            "actor_id": actor_id, "actor_name": actor_name or "",
            "created_at": iso(now_utc()), "status": "pending",
            "operation_id": op_key or "",
            "courier_cash_kind": kind, "courier_id": courier_id,
        }
        if not doc["operation_id"]:
            doc["operation_id"] = doc["id"]
        await db.fund_account_transfers.insert_one({**doc})
        if not await fund_budget.assert_spend_authority(code, lock, doc["id"]):
            await db.fund_account_transfers.update_one(
                {"id": doc["id"]},
                {"$set": {"status": "aborted",
                          "aborted_reason": "cerrojo de gasto perdido"}})
            raise HTTPException(
                status_code=409,
                detail="La operación perdió su turno; inténtalo de nuevo.")
        confirmed = await db.fund_account_transfers.update_one(
            {"id": doc["id"], "status": "pending"},
            {"$set": {"status": "confirmed", "confirmed_at": iso(now_utc())}})
        if confirmed.matched_count == 0:
            persisted = await db.fund_account_transfers.find_one(
                {"id": doc["id"]}, {"_id": 0})
            if not persisted or persisted.get("status") != "confirmed":
                raise HTTPException(
                    status_code=409,
                    detail=("La operación fue revocada antes de confirmarse; "
                            "inténtalo de nuevo."))
        doc["status"] = "confirmed"
    finally:
        await fund_budget.release_pay_lock(code, lock)

    try:
        mov_id = await mirror_fund_transfer_to_cash_box(doc)
        if mov_id:
            doc["cash_box_movement_id"] = mov_id
    except Exception as exc:  # el job periódico lo sana
        logger.error("espejo de caja del traslado %s falló: %s", doc["id"], exc)

    ev = await record_cash_event(
        courier_id=courier_id, courier_name=courier_name, kind=kind,
        currency=code, amount=amt, note=note, by=actor_id, by_name=actor_name,
        op_key=op_key, discrepancy=bool(discrepancy_note),
        discrepancy_note=discrepancy_note, transfer_id=doc["id"])
    if ev is None:  # el evento ya existía (reintento): devuelve el persistido
        ev = await db.courier_cash_events.find_one(
            {"op_key": op_key} if op_key else {"id": doc["id"]}, {"_id": 0})
    return {"event": ev, "transfer": doc}


async def ensure_indexes() -> None:
    await db.courier_cash_events.create_index("op_key", unique=True,
                                              sparse=True)
    await db.courier_cash_events.create_index([("courier_id", 1), ("at", -1)])
    # EF01 — identidad de la cuenta de custodia por (mensajero, moneda).
    await db.fund_accounts.create_index(
        [("courier_custody_id", 1), ("currency", 1)], unique=True,
        sparse=True)


async def record_cash_event(*, courier_id: str, courier_name: str, kind: str,
                            currency: str, amount: Any,
                            delivery_id: Optional[str] = None,
                            note: str = "", by: Optional[str] = None,
                            by_name: str = "", op_key: Optional[str] = None,
                            discrepancy: bool = False,
                            discrepancy_note: str = "",
                            transfer_id: Optional[str] = None) -> Optional[dict]:
    if kind not in EVENT_KINDS:
        raise HTTPException(status_code=400, detail="Tipo de evento inválido")
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Importe inválido")
    if not math.isfinite(amt) or amt <= 0 or amt > 100_000_000:
        raise HTTPException(status_code=400, detail="Importe inválido")
    cur = (currency or "").strip().upper()
    if not cur or len(cur) > 8:
        raise HTTPException(status_code=400, detail="Moneda inválida")
    doc = {
        "id": str(uuid.uuid4()), "courier_id": courier_id,
        "courier_name": courier_name or "", "kind": kind,
        "currency": cur, "amount": round(amt, 2),
        "delivery_id": delivery_id, "note": (note or "")[:300],
        "by": by, "by_name": by_name or "",
        "discrepancy": bool(discrepancy),
        "discrepancy_note": (discrepancy_note or "")[:300],
        "transfer_id": transfer_id, "at": iso(now_utc()),
    }
    if op_key:
        doc["op_key"] = op_key
    try:
        await db.courier_cash_events.insert_one(dict(doc))
    except DuplicateKeyError:
        return None  # evento automático ya registrado (reintento)
    doc.pop("_id", None)
    return doc


async def auto_events_for_delivered(d: dict, actor_id: str) -> None:
    """Al marcar 'delivered': depósito → el mensajero RECOGIÓ efectivo del
    cliente; retiro cash → ENTREGÓ efectivo al destinatario. Idempotente por
    op_key. N04 — procesa la tarea durable `cash_event_pending` sellada en el
    MISMO update de la transición: registra el evento y SOLO entonces limpia
    la tarea. Un fallo de escritura la deja viva para el healer; un dato de
    origen no registrable deja rastro visible (`cash_event_error`)."""
    kind = d.get("kind")
    cid = d.get("courier_id")
    did = d.get("id")
    try:
        if cid and kind == "deposit":
            ref = await db.deposits.find_one(
                {"id": d["ref_id"]},
                {"_id": 0, "amount": 1, "currency": 1, "method": 1})
            if ref and float(ref.get("amount") or 0) > 0:
                await record_cash_event(
                    courier_id=cid, courier_name=d.get("courier_name") or "",
                    kind="collected", currency=ref.get("currency") or "",
                    amount=float(ref["amount"]), delivery_id=did,
                    note="Recogida de depósito en efectivo", by=actor_id,
                    op_key=f"auto:{did}:collected")
                # EF01 fase 2 — el efectivo recogido queda en la CUSTODIA del
                # mensajero hasta que lo rinda; se atribuye ahí (no a la caja ni
                # a "sin asignar"). Reconocido una sola vez: el depósito ya
                # cuenta en el total al confirmarse. Solo efectivo, forward-only.
                if ref.get("method") == "cash" and \
                        (d.get("updated_at") or d.get("created_at") or "") \
                        >= CUSTODY_EPOCH:
                    custody = await get_or_create_courier_custody_account(
                        cid, d.get("courier_name") or "",
                        ref.get("currency") or "")
                    await db.deposits.update_one(
                        {"id": d["ref_id"],
                         "courier_custody_inflow": {"$ne": True}},
                        {"$set": {"courier_custody_inflow": True,
                                  "courier_custody_account_id": custody["id"]}})
        elif cid and kind == "withdrawal":
            ref = await db.withdrawals.find_one(
                {"id": d["ref_id"]},
                {"_id": 0, "amount_usd": 1, "currency": 1, "method": 1})
            if ref and ref.get("method") == "cash" \
                    and float(ref.get("amount_usd") or 0) > 0:
                await record_cash_event(
                    courier_id=cid, courier_name=d.get("courier_name") or "",
                    kind="delivered_to_recipient",
                    currency=ref.get("currency") or "",
                    amount=float(ref["amount_usd"]), delivery_id=did,
                    note="Entrega de retiro en efectivo", by=actor_id,
                    op_key=f"auto:{did}:delivered")
                # EF01/test B — el pago al destinatario CONSUME el efectivo en
                # tránsito del mensajero: la salida externa se reconoce sobre la
                # custodia (no vuelve a bajar la caja, que ya bajó al entregar
                # el efectivo al mensajero). Forward-only (era de custodia).
                if (d.get("updated_at") or d.get("created_at") or "") \
                        >= CUSTODY_EPOCH:
                    custody = await get_or_create_courier_custody_account(
                        cid, d.get("courier_name") or "",
                        ref.get("currency") or "")
                    await db.withdrawals.update_one(
                        {"id": d["ref_id"],
                         "courier_custody_outflow": {"$ne": True}},
                        {"$set": {"courier_custody_outflow": True,
                                  "courier_custody_account_id": custody["id"]}})
    except HTTPException as e:
        # Dato de origen inválido: reintentar no lo arregla — el pendiente se
        # cierra con un error visible para que el operador lo resuelva.
        logger.error("evento de efectivo no registrable en %s: %s",
                     did, e.detail)
        await db.deliveries.update_one(
            {"id": did},
            {"$set": {"cash_event_error": str(e.detail)},
             "$unset": {"cash_event_pending": ""}})
        return
    await db.deliveries.update_one(
        {"id": did}, {"$unset": {"cash_event_pending": ""}})


# N04 — inicio del ledger de efectivo (Mejora #1, iter290): la reconciliación
# solo repone eventos de entregas realizadas DESPUÉS de esta fecha; las
# anteriores se liquidaron fuera del sistema y no deben inflar pendientes.
CASH_LEDGER_EPOCH = "2026-09-20"


async def reconcile_missing_cash_events(batch: int = 200) -> int:
    """N04 — entregas ya realizadas (dentro de la era del ledger) cuyo evento
    automático falta: se repone de forma idempotente (op_key) y el doc queda
    marcado para no re-escanearse."""
    rows = await db.deliveries.find(
        {"status": {"$in": ["delivered", "confirmed"]},
         "kind": {"$in": ["deposit", "withdrawal"]},
         "courier_id": {"$nin": [None, ""]},
         "updated_at": {"$gte": CASH_LEDGER_EPOCH},
         "cash_event_checked": {"$exists": False},
         "cash_event_pending": {"$exists": False}},
        {"_id": 0}).to_list(batch)
    n = 0
    for d in rows:
        try:
            await auto_events_for_delivered(d, "system-reconcile")
            await db.deliveries.update_one(
                {"id": d["id"]}, {"$set": {"cash_event_checked": True}})
            n += 1
        except Exception as e:
            logger.error("reconciliación de efectivo %s: %s", d["id"], e)
    return n


async def cash_pending(courier_id: Optional[str] = None) -> list:
    """Pendiente de rendición por mensajero y moneda. Positivo = el mensajero
    tiene efectivo de la empresa/clientes por rendir; negativo = falta
    registrar una entrega de caja al mensajero (diferencia visible)."""
    match: dict = {}
    if courier_id:
        match["courier_id"] = courier_id
    rows = await db.courier_cash_events.aggregate([
        {"$match": match},
        {"$group": {"_id": {"c": "$courier_id", "cur": "$currency",
                            "k": "$kind"},
                    "total": {"$sum": "$amount"},
                    "name": {"$last": "$courier_name"}}},
    ]).to_list(4000)
    acc: dict = {}
    for r in rows:
        key = (r["_id"]["c"], r["_id"]["cur"])
        e = acc.setdefault(key, {"courier_id": r["_id"]["c"],
                                 "courier_name": r.get("name") or "",
                                 "currency": r["_id"]["cur"],
                                 "issued": 0.0, "collected": 0.0,
                                 "delivered_to_recipient": 0.0,
                                 "returned": 0.0})
        e[r["_id"]["k"]] = round(float(r["total"]), 2)
        if r.get("name"):
            e["courier_name"] = r["name"]
    out = []
    for e in acc.values():
        e["pending"] = round(e["issued"] + e["collected"]
                             - e["delivered_to_recipient"] - e["returned"], 2)
        out.append(e)
    out.sort(key=lambda x: (-abs(x["pending"]), x["courier_name"]))
    return out
