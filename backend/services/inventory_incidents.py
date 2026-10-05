"""IPV Fase 3 — Seguimiento de incidencias del inventario (iter333).

Registra y da ciclo de vida (pendiente → en_revision → resuelta) a las
incidencias del control físico:
  - conteo_pendiente: producto activo sin contar en la jornada.
  - diferencia: conteo con descuadre aún no ajustado.
  - venta_bajo_costo: venta a un precio por debajo del costo.

Dedup por `dedupe_key` (type + referencia) para no duplicar. Auto-resolución
cuando desaparece la causa (se cuenta el producto, se autoriza el ajuste de la
diferencia, el conteo queda sin descuadre). Una incidencia ya resuelta NO se
reabre: queda como constancia histórica.
"""
import uuid
import logging
from typing import Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import now_utc, iso
from services.inventory import _COMPANY_FILTER, today_havana, UNIT_ABBR

logger = logging.getLogger(__name__)

STATUSES = ("pendiente", "en_revision", "resuelta")
TYPES = ("conteo_pendiente", "diferencia", "venta_bajo_costo")
_INDEX_READY = False


async def _ensure_index() -> None:
    global _INDEX_READY
    if not _INDEX_READY:
        await db.inventory_incidents.create_index(
            "dedupe_key", unique=True, sparse=True)
        await db.inventory_incidents.create_index(
            [("status", 1), ("type", 1), ("created_at", -1)])
        _INDEX_READY = True


async def _upsert_incident(*, itype: str, product_id: str, product_name: str,
                           detail: str, amount: float, ref_id: str,
                           ref_date: str, dedupe_key: str) -> str:
    """Crea la incidencia (pendiente) si no existe. Si existe abierta, refresca
    detalle/monto. Si ya está resuelta, NO la reabre."""
    await _ensure_index()
    now = iso(now_utc())
    existing = await db.inventory_incidents.find_one(
        {"dedupe_key": dedupe_key}, {"_id": 0})
    if existing:
        if existing["status"] != "resuelta":
            await db.inventory_incidents.update_one(
                {"id": existing["id"]},
                {"$set": {"detail": detail, "amount": round(float(amount or 0), 2),
                          "updated_at": now}})
        return existing["id"]
    doc = {
        "id": str(uuid.uuid4()), "type": itype, "product_id": product_id,
        "product_name": product_name, "status": "pendiente", "detail": detail,
        "amount": round(float(amount or 0), 2), "ref_id": ref_id,
        "ref_date": ref_date, "dedupe_key": dedupe_key, "source": "auto",
        "created_at": now, "updated_at": now, "auto_resolved": False,
        "history": [{"status": "pendiente", "note": "Generada automáticamente",
                     "by": "", "by_email": "sistema", "at": now}],
    }
    try:
        await db.inventory_incidents.insert_one({**doc})
    except DuplicateKeyError:
        found = await db.inventory_incidents.find_one(
            {"dedupe_key": dedupe_key}, {"_id": 0})
        return found["id"] if found else doc["id"]
    return doc["id"]


async def _auto_resolve(dedupe_key: str, note: str) -> None:
    now = iso(now_utc())
    inc = await db.inventory_incidents.find_one(
        {"dedupe_key": dedupe_key}, {"_id": 0})
    if not inc or inc["status"] == "resuelta":
        return
    await db.inventory_incidents.update_one(
        {"id": inc["id"]},
        {"$set": {"status": "resuelta", "updated_at": now, "resolved_at": now,
                  "resolved_by": "", "resolved_by_email": "sistema",
                  "resolution_note": note, "auto_resolved": True},
         "$push": {"history": {"status": "resuelta", "note": note, "by": "",
                               "by_email": "sistema", "at": now}}})


# ───────────────────── detectores (hooks automáticos) ─────────────────────
async def on_sale_below_cost(movement: dict) -> None:
    """Hook en record_movement: una venta cuyo total < costo de venta genera
    una incidencia de venta bajo costo (pérdida = costo − total)."""
    if movement.get("type") != "venta":
        return
    total = float(movement.get("total") or 0)
    cost_of_sale = float(movement.get("cost_of_sale") or 0)
    if cost_of_sale <= 0 or total >= cost_of_sale:
        return
    loss = round(cost_of_sale - total, 2)
    await _upsert_incident(
        itype="venta_bajo_costo", product_id=movement["product_id"],
        product_name=movement.get("product_name", ""),
        detail=(f"Venta a {total} CUP por debajo del costo {cost_of_sale} CUP "
                f"({movement.get('quantity')} ud) · pérdida {loss} CUP."),
        amount=loss, ref_id=movement.get("id", ""),
        ref_date=(movement.get("created_at") or "")[:10],
        dedupe_key=f"venta_bajo_costo:{movement.get('id', '')}")


async def on_count_recorded(count: dict) -> None:
    """Hook en record_physical_count: resuelve el 'conteo pendiente' del
    producto y crea/resuelve la 'diferencia' según el descuadre."""
    pid = count["product_id"]
    day = count["count_date"]
    await _auto_resolve(f"conteo_pendiente:{pid}:{day}",
                        "El producto fue contado en la jornada.")
    # iter337 (H02) — conservar la precisión fraccionaria. El int() anterior
    # truncaba −0,75 lb a 0 y la incidencia de diferencia se auto-resolvía como
    # si el conteo cuadrara. Se usa el mismo criterio de cero que _count_status.
    diff = round(float(count.get("difference") or 0), 3)
    unit = UNIT_ABBR.get(count.get("unit") or "", count.get("unit") or "ud")
    dk = f"diferencia:{count.get('id', '')}"
    if abs(diff) > 1e-9 and not count.get("authorized"):
        await _upsert_incident(
            itype="diferencia", product_id=pid,
            product_name=count.get("product_name", ""),
            detail=(f"Descuadre de {diff:+g} {unit} (contado "
                    f"{count.get('counted_qty')} vs teórico "
                    f"{count.get('theoretical_stock')})."),
            amount=count.get("difference_value") or 0,
            ref_id=count.get("id", ""), ref_date=day, dedupe_key=dk)
    else:
        await _auto_resolve(dk, "El conteo quedó sin diferencia.")


async def on_count_authorized(count_id: str) -> None:
    """Hook en authorize_count_adjustment: la diferencia queda ajustada."""
    await _auto_resolve(f"diferencia:{count_id}",
                        "Diferencia ajustada y autorizada.")


async def sync_pending_count_incidents(day: Optional[str] = None) -> dict:
    """Sincroniza incidencias 'conteo_pendiente' de una jornada: crea una por
    cada producto activo de la empresa SIN conteo ese día y resuelve las de los
    que ya se contaron. Pensada para correr a diario (y bajo demanda)."""
    d = (day or today_havana())[:10]
    products = await db.products.find(
        {**_COMPANY_FILTER, "is_active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1}).to_list(5000)
    counted = {c["product_id"] for c in await db.inventory_counts.find(
        {"count_date": d}, {"_id": 0, "product_id": 1}).to_list(50000)}
    created = 0
    resolved = 0
    for p in products:
        dk = f"conteo_pendiente:{p['id']}:{d}"
        if p["id"] in counted:
            inc = await db.inventory_incidents.find_one(
                {"dedupe_key": dk}, {"_id": 0, "status": 1})
            if inc and inc["status"] != "resuelta":
                await _auto_resolve(dk, "El producto fue contado en la jornada.")
                resolved += 1
        else:
            before = await db.inventory_incidents.find_one(
                {"dedupe_key": dk}, {"_id": 0, "id": 1})
            await _upsert_incident(
                itype="conteo_pendiente", product_id=p["id"],
                product_name=p.get("name", ""),
                detail=f"Producto activo sin conteo en la jornada {d}.",
                amount=0, ref_id="", ref_date=d, dedupe_key=dk)
            if not before:
                created += 1
    return {"date": d, "created": created, "resolved": resolved}


# ───────────────────────── ciclo de vida / consulta ──────────────────────
async def transition_incident(incident_id: str, status: str, note: str,
                              actor: dict) -> dict:
    if status not in STATUSES:
        raise HTTPException(status_code=400, detail="Estado inválido")
    inc = await db.inventory_incidents.find_one({"id": incident_id}, {"_id": 0})
    if not inc:
        raise HTTPException(status_code=404, detail="Incidencia no encontrada")
    now = iso(now_utc())
    upd = {"status": status, "updated_at": now}
    if status == "resuelta":
        upd.update({"resolved_at": now, "resolved_by": actor.get("user_id", ""),
                    "resolved_by_email": actor.get("email", ""),
                    "resolution_note": note or "", "auto_resolved": False})
    await db.inventory_incidents.update_one(
        {"id": incident_id},
        {"$set": upd,
         "$push": {"history": {"status": status, "note": note or "",
                               "by": actor.get("user_id", ""),
                               "by_email": actor.get("email", ""), "at": now}}})
    return await db.inventory_incidents.find_one({"id": incident_id}, {"_id": 0})


async def list_incidents(status: Optional[str] = None,
                         itype: Optional[str] = None, limit: int = 500) -> list:
    q: dict = {}
    if status:
        q["status"] = status
    if itype:
        q["type"] = itype
    return await db.inventory_incidents.find(
        q, {"_id": 0}).sort([("status", 1), ("created_at", -1)]).to_list(limit)


async def incident_summary() -> dict:
    agg = await db.inventory_incidents.aggregate([
        {"$group": {"_id": {"s": "$status", "t": "$type"},
                    "n": {"$sum": 1}}}]).to_list(100)
    by_status: dict = {}
    by_type: dict = {}
    open_total = 0
    for a in agg:
        s = a["_id"]["s"]
        t = a["_id"]["t"]
        n = a["n"]
        by_status[s] = by_status.get(s, 0) + n
        by_type[t] = by_type.get(t, 0) + n
        if s != "resuelta":
            open_total += n
    return {"by_status": by_status, "by_type": by_type, "open": open_total}
