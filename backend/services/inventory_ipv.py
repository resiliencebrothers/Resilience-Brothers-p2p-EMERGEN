"""IPV (Inventario Físico de Ventas) — Fase 1: conteo físico, revisión del
cierre y resumen de alertas. Reutiliza el inventario de la tienda física
(`products` + `inventory_movements`) y añade:

- `inventory_counts`   conteo físico diario por producto (vacío ≠ 0: SIN CONTEO).
- `inventory_closes`   cierre formal del día con responsable / revisor / folio.

Reglas del IPV respetadas:
- El conteo NUNCA altera el arrastre por sí solo; solo un ajuste AUTORIZADO con
  documento cambia el stock (ajuste_pos / ajuste_neg, idempotente por conteo).
- Merma / consumo interno / otras salidas descuentan stock pero no son ingreso
  ni tocan el fondo de la empresa (ver services.inventory).
- El cierre deja constancia (no bloquea el día).
"""
import logging
import uuid
from typing import Optional

from fastapi import HTTPException

from db_client import db
from auth_utils import now_utc, iso
from services.inventory import (record_movement, today_havana, _day_bounds,
                                _COMPANY_FILTER, OUTPUT_TYPES)

logger = logging.getLogger(__name__)

_COUNTS_INDEX_READY = False


def _count_status(difference: int) -> str:
    if difference == 0:
        return "cuadra"
    return "faltante" if difference < 0 else "sobrante"


async def _ensure_counts_index() -> None:
    global _COUNTS_INDEX_READY
    if not _COUNTS_INDEX_READY:
        await db.inventory_counts.create_index(
            [("product_id", 1), ("count_date", 1)], unique=True)
        _COUNTS_INDEX_READY = True


async def record_physical_count(product: dict, counted_qty: int,
                                actor: Optional[dict] = None,
                                note: str = "") -> dict:
    """Registra/actualiza el conteo físico del día (hora de Cuba) de un
    producto. Calcula diferencia = contado − stock teórico y su estado. NO
    modifica el stock. Un conteo ya AUTORIZADO (ajustado) no se sobrescribe."""
    await _ensure_counts_index()
    day = today_havana()
    theoretical = int(product.get("stock") or 0)
    difference = int(counted_qty) - theoretical
    existing = await db.inventory_counts.find_one(
        {"product_id": product["id"], "count_date": day}, {"_id": 0})
    if existing and existing.get("authorized"):
        raise HTTPException(
            status_code=409,
            detail="Este conteo ya tiene un ajuste autorizado; no puede "
                   "modificarse. Vuelve a contar en otra jornada si procede.")
    now = iso(now_utc())
    doc = {
        "id": (existing or {}).get("id") or str(uuid.uuid4()),
        "product_id": product["id"],
        "product_name": product.get("name", ""),
        "count_date": day,
        "counted_qty": int(counted_qty),
        "theoretical_stock": theoretical,
        "difference": difference,
        "status": _count_status(difference),
        "note": note or "",
        "counted_by": (actor or {}).get("user_id", ""),
        "counted_by_email": (actor or {}).get("email", ""),
        "counted_at": now,
        "authorized": False,
        "adjustment_movement_id": None,
        "updated_at": now,
    }
    await db.inventory_counts.update_one(
        {"product_id": product["id"], "count_date": day},
        {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True)
    return doc


async def clear_physical_count(product_id: str, day: Optional[str] = None) -> None:
    """Borra el conteo del día (vuelve a SIN CONTEO). No se puede si ya tiene
    un ajuste autorizado."""
    day = day or today_havana()
    existing = await db.inventory_counts.find_one(
        {"product_id": product_id, "count_date": day}, {"_id": 0})
    if not existing:
        return
    if existing.get("authorized"):
        raise HTTPException(
            status_code=409,
            detail="No se puede borrar un conteo con ajuste autorizado.")
    await db.inventory_counts.delete_one(
        {"product_id": product_id, "count_date": day})


async def list_counts(day: str) -> dict:
    rows = await db.inventory_counts.find(
        {"count_date": day}, {"_id": 0}).to_list(20000)
    return {r["product_id"]: r for r in rows}


async def authorize_count_adjustment(count_id: str, document: str,
                                      note: str, actor: dict) -> dict:
    """ADMIN — aplica la diferencia del conteo como ajuste de stock AUTORIZADO
    (ajuste_pos / ajuste_neg), exigiendo documento. Idempotente por conteo."""
    if not (document or "").strip():
        raise HTTPException(status_code=400,
                            detail="El ajuste exige un documento de respaldo.")
    count = await db.inventory_counts.find_one({"id": count_id}, {"_id": 0})
    if not count:
        raise HTTPException(status_code=404, detail="Conteo no encontrado")
    if count.get("authorized"):
        raise HTTPException(status_code=409,
                            detail="Este conteo ya fue ajustado.")
    diff = int(count.get("difference") or 0)
    if diff == 0:
        raise HTTPException(
            status_code=400,
            detail="El conteo cuadra (diferencia 0): no requiere ajuste.")
    product = await db.products.find_one({"id": count["product_id"]},
                                         {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    mtype = "ajuste_pos" if diff > 0 else "ajuste_neg"
    reason = (f"Ajuste por conteo físico {count['count_date']} · doc: "
              f"{document.strip()}" + (f" · {note.strip()}" if note else ""))
    mov = await record_movement(
        product=product, mtype=mtype, quantity=abs(diff), note=reason,
        source="conteo", ref_id=count_id, actor=actor,
        dedupe_key=f"count-adjust:{count_id}")
    now = iso(now_utc())
    await db.inventory_counts.update_one(
        {"id": count_id, "authorized": {"$ne": True}},
        {"$set": {"authorized": True, "status": "ajustado",
                  "adjustment_movement_id": mov["id"],
                  "adjustment_document": document.strip(),
                  "adjustment_note": note or "",
                  "authorized_by": actor.get("user_id", ""),
                  "authorized_by_email": actor.get("email", ""),
                  "authorized_at": now, "updated_at": now}})
    return await db.inventory_counts.find_one({"id": count_id}, {"_id": 0})


async def build_close_review(day: str) -> dict:
    """Resumen de revisión del cierre del día: alertas (SIN CONTEO,
    diferencias sin ajustar, salidas sin documento), desglose de salidas no-venta
    y el cierre formal guardado (si existe). Resultado sugerido CUADRA/DESCUADRA.
    No bloquea el día."""
    products = await db.products.find(
        _COMPANY_FILTER, {"_id": 0, "id": 1, "name": 1,
                          "is_active": 1}).to_list(5000)
    active = [p for p in products if p.get("is_active", True)]
    counts = await list_counts(day)
    counted_ids = set(counts.keys())
    sin_conteo = [{"product_id": p["id"], "name": p.get("name", "")}
                  for p in active if p["id"] not in counted_ids]
    diffs = [c for c in counts.values()
             if int(c.get("difference") or 0) != 0 and not c.get("authorized")]
    # Salidas no-venta del día sin documento (nota vacía).
    start, end = _day_bounds(day)
    outs = await db.inventory_movements.find(
        {"type": {"$in": list(OUTPUT_TYPES)},
         "created_at": {"$gte": start, "$lt": end}}, {"_id": 0}).to_list(20000)
    salidas_sin_doc = [m for m in outs if not (m.get("note") or "").strip()]
    breakdown = {t: {"unidades": 0, "valor_costo": 0.0, "num": 0}
                 for t in OUTPUT_TYPES}
    for m in outs:
        b = breakdown[m["type"]]
        b["unidades"] += int(m.get("quantity") or 0)
        b["valor_costo"] = round(b["valor_costo"] + float(m.get("total") or 0), 2)
        b["num"] += 1
    resultado = "cuadra" if not diffs and not salidas_sin_doc else "descuadra"
    close = await db.inventory_closes.find_one({"close_date": day}, {"_id": 0})
    return {
        "date": day,
        "resultado_sugerido": resultado,
        "alerts": {
            "sin_conteo": len(sin_conteo),
            "diferencias": len(diffs),
            "salidas_sin_documento": len(salidas_sin_doc),
        },
        "sin_conteo_sample": sin_conteo[:50],
        "diferencias": sorted(
            ({"product_id": c["product_id"], "name": c.get("product_name", ""),
              "difference": int(c.get("difference") or 0),
              "status": c.get("status"), "count_id": c.get("id")}
             for c in diffs), key=lambda x: x["difference"]),
        "salidas": {
            "merma": breakdown["merma"],
            "consumo": breakdown["consumo"],
            "otra_salida": breakdown["otra_salida"],
            "sin_documento": len(salidas_sin_doc),
        },
        "productos_contados": len(counted_ids),
        "productos_activos": len(active),
        "close": close,
    }


async def save_close_review(day: str, responsable: str, revisado_por: str,
                            folio: str, note: str, actor: dict) -> dict:
    """ADMIN — guarda el cierre formal del día (constancia). No bloquea nuevos
    movimientos. El resultado se calcula con las alertas vigentes al cerrar."""
    review = await build_close_review(day)
    now = iso(now_utc())
    doc = {
        "close_date": day,
        "responsable": (responsable or "").strip(),
        "revisado_por": (revisado_por or "").strip(),
        "folio": (folio or "").strip(),
        "note": (note or "").strip(),
        "resultado": review["resultado_sugerido"],
        "alerts_snapshot": review["alerts"],
        "closed_by": actor.get("user_id", ""),
        "closed_by_email": actor.get("email", ""),
        "closed_at": now,
    }
    await db.inventory_closes.update_one(
        {"close_date": day},
        {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True)
    return await db.inventory_closes.find_one({"close_date": day}, {"_id": 0})
