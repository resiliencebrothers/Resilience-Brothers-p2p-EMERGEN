"""Mejora #1 auditoría eeed556 — Control de efectivo por mensajero.

Ledger `courier_cash_events`: cada movimiento de efectivo, vinculado al
reparto cuando aplica. Pendiente de rendición por mensajero+moneda =
(issued + collected) − (delivered_to_recipient + returned).
Eventos automáticos idempotentes por `op_key` (índice único sparse).
"""
import logging
import math
import uuid
from typing import Any, Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import iso, now_utc

logger = logging.getLogger("courier_cash")

EVENT_KINDS = ("issued", "collected", "delivered_to_recipient", "returned")


async def ensure_indexes() -> None:
    await db.courier_cash_events.create_index("op_key", unique=True,
                                              sparse=True)
    await db.courier_cash_events.create_index([("courier_id", 1), ("at", -1)])


async def record_cash_event(*, courier_id: str, courier_name: str, kind: str,
                            currency: str, amount: Any,
                            delivery_id: Optional[str] = None,
                            note: str = "", by: Optional[str] = None,
                            by_name: str = "", op_key: Optional[str] = None,
                            discrepancy: bool = False) -> Optional[dict]:
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
        "discrepancy": bool(discrepancy), "at": iso(now_utc()),
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
                {"id": d["ref_id"]}, {"_id": 0, "amount": 1, "currency": 1})
            if ref and float(ref.get("amount") or 0) > 0:
                await record_cash_event(
                    courier_id=cid, courier_name=d.get("courier_name") or "",
                    kind="collected", currency=ref.get("currency") or "",
                    amount=float(ref["amount"]), delivery_id=did,
                    note="Recogida de depósito en efectivo", by=actor_id,
                    op_key=f"auto:{did}:collected")
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
