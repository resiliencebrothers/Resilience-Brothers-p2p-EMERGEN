"""Mejora #1 auditoría eeed556 — Control de efectivo por mensajero.

Ledger `courier_cash_events`: cada movimiento de efectivo, vinculado al
reparto cuando aplica. Pendiente de rendición por mensajero+moneda =
(issued + collected) − (delivered_to_recipient + returned).
Eventos automáticos idempotentes por `op_key` (índice único sparse).
"""
import logging
import math
import uuid
from typing import Optional

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
                            currency: str, amount, delivery_id=None,
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
    op_key; best-effort (nunca rompe la transición de estado)."""
    try:
        kind = d.get("kind")
        cid = d.get("courier_id")
        if not cid:
            return
        if kind == "deposit":
            ref = await db.deposits.find_one(
                {"id": d["ref_id"]}, {"_id": 0, "amount": 1, "currency": 1})
            if ref and float(ref.get("amount") or 0) > 0:
                await record_cash_event(
                    courier_id=cid, courier_name=d.get("courier_name") or "",
                    kind="collected", currency=ref.get("currency") or "",
                    amount=float(ref["amount"]), delivery_id=d["id"],
                    note="Recogida de depósito en efectivo", by=actor_id,
                    op_key=f"auto:{d['id']}:collected")
        elif kind == "withdrawal":
            ref = await db.withdrawals.find_one(
                {"id": d["ref_id"]},
                {"_id": 0, "amount_usd": 1, "currency": 1, "method": 1})
            if ref and ref.get("method") == "cash" \
                    and float(ref.get("amount_usd") or 0) > 0:
                await record_cash_event(
                    courier_id=cid, courier_name=d.get("courier_name") or "",
                    kind="delivered_to_recipient",
                    currency=ref.get("currency") or "",
                    amount=float(ref["amount_usd"]), delivery_id=d["id"],
                    note="Entrega de retiro en efectivo", by=actor_id,
                    op_key=f"auto:{d['id']}:delivered")
    except HTTPException:
        pass
    except Exception as e:
        logger.error(f"auto cash event failed: {e}")


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
