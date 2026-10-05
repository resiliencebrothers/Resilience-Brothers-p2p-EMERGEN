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
from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import now_utc, iso
from services.inventory import (record_movement, today_havana, _day_bounds,
                                _COMPANY_FILTER, OUTPUT_TYPES, qnum,
                                product_unit, norm_qty)

logger = logging.getLogger(__name__)

_COUNTS_INDEX_READY = False


def _count_status(difference: float) -> str:
    if abs(difference) < 1e-9:
        return "cuadra"
    return "faltante" if difference < 0 else "sobrante"


async def _ensure_counts_index() -> None:
    global _COUNTS_INDEX_READY
    if not _COUNTS_INDEX_READY:
        await db.inventory_counts.create_index(
            [("product_id", 1), ("count_date", 1)], unique=True)
        _COUNTS_INDEX_READY = True


async def record_physical_count(product: dict, counted_qty: float,
                                actor: Optional[dict] = None,
                                note: str = "") -> dict:
    """Registra/actualiza el conteo físico del día (hora de Cuba) de un
    producto. Calcula diferencia = contado − stock teórico y su estado. NO
    modifica el stock. Un conteo ya AUTORIZADO (ajustado) no se sobrescribe."""
    await _ensure_counts_index()
    day = today_havana()
    theoretical = qnum(product.get("stock"))
    counted_qty = norm_qty(product, counted_qty)
    difference = round(counted_qty - theoretical, 3)
    existing = await db.inventory_counts.find_one(
        {"product_id": product["id"], "count_date": day}, {"_id": 0})
    if existing and existing.get("authorized"):
        raise HTTPException(
            status_code=409,
            detail="Este conteo ya tiene un ajuste autorizado; no puede "
                   "modificarse. Vuelve a contar en otra jornada si procede.")
    now = iso(now_utc())
    # iter328 (IPV Fase 1) — se CONGELA el costo de referencia (WAC vigente del
    # producto), la unidad, la moneda y el momento de valoración. Así el valor
    # de la diferencia queda fijado al conteo y un costo posterior no lo altera.
    ref_cost = round(float(product.get("cost_usd") or 0), 4)
    doc = {
        "id": (existing or {}).get("id") or str(uuid.uuid4()),
        "product_id": product["id"],
        "product_name": product.get("name", ""),
        "count_date": day,
        "counted_qty": counted_qty,
        "theoretical_stock": theoretical,
        "difference": difference,
        "difference_value": round(difference * ref_cost, 2),
        "reference_cost": ref_cost,
        "unit": product_unit(product),
        "currency": "CUP",
        "valued_at": now,
        "status": _count_status(difference),
        "note": note or "",
        "counted_by": (actor or {}).get("user_id", ""),
        "counted_by_email": (actor or {}).get("email", ""),
        "counted_at": now,
        "authorized": False,
        "adjustment_movement_id": None,
        "updated_at": now,
    }
    # iter327 (IPV-R03) — escritura CONDICIONADA a que el conteo NO esté
    # autorizado: si una autorización concurrente lo marcó entre la lectura y
    # esta escritura, el filtro no casa el doc autorizado y el upsert intenta
    # insertar → DuplicateKeyError (índice único product_id+count_date) → 409.
    # Así un recuento atrasado nunca sobrescribe ni desautoriza un ajuste.
    try:
        await db.inventory_counts.update_one(
            {"product_id": product["id"], "count_date": day,
             "authorized": {"$ne": True}},
            {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Este conteo ya tiene un ajuste autorizado; no puede "
                   "modificarse. Vuelve a contar en otra jornada si procede.")
    # iter333 (IPV Fase 3) — sincroniza incidencias: resuelve el conteo
    # pendiente y crea/resuelve la diferencia según el descuadre.
    try:
        from services.inventory_incidents import on_count_recorded
        await on_count_recorded(doc)
    except Exception as e:  # noqa: BLE001
        logger.error(f"incident on_count_recorded failed: {e}")
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
    # iter327 (IPV-R03) — borrado CONDICIONADO a authorized!=true: si una
    # autorización concurrente marcó el conteo entre la lectura anterior y este
    # borrado, el filtro no casa (deleted_count==0) → 409 y la evidencia
    # autorizada se preserva. Evita la micro-ventana de carrera read-then-delete.
    res = await db.inventory_counts.delete_one(
        {"product_id": product_id, "count_date": day,
         "authorized": {"$ne": True}})
    if res.deleted_count == 0:
        raise HTTPException(
            status_code=409,
            detail="No se puede borrar un conteo con ajuste autorizado.")


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
    diff = qnum(count.get("difference"))
    if abs(diff) < 1e-9:
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
    # iter333 (IPV Fase 3) — la diferencia quedó ajustada → resolver incidencia.
    try:
        from services.inventory_incidents import on_count_authorized
        await on_count_authorized(count_id)
    except Exception as e:  # noqa: BLE001
        logger.error(f"incident on_count_authorized failed: {e}")
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
             if abs(qnum(c.get("difference"))) > 1e-9 and not c.get("authorized")]
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
        b["unidades"] += qnum(m.get("quantity"))
        b["valor_costo"] = round(b["valor_costo"] + float(m.get("total") or 0), 2)
        b["num"] += 1
    # iter327 (IPV-R04) — tres estados con prioridad a las ANOMALÍAS:
    # DESCUADRA si hay diferencias sin ajustar o salidas sin documento (se
    # destapa la incidencia aunque falten conteos); PENDIENTE si falta contar
    # productos activos y NO hay anomalías aún; CUADRA solo si está completo y
    # sin incidencias (elegible para "revisado" al firmar con responsable y
    # revisor). Prioriza la señal de fraude/descuadre sobre el avance del conteo.
    if diffs or salidas_sin_doc:
        resultado = "descuadra"
    elif sin_conteo:
        resultado = "pendiente"
    else:
        resultado = "cuadra"
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
              "difference": qnum(c.get("difference")),
              "unit": c.get("unit", "unidad"),
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


async def build_count_sheet(day: str) -> dict:
    """IPV Fase 2 — datos del acta de conteo físico firmable del día: una fila
    por producto de la empresa con stock teórico, conteo físico, diferencia y
    estado. Si el día ya tiene cierre guardado, adjunta responsable/revisor/
    folio para rellenar el acta; si no, el PDF deja líneas para firmar a mano."""
    products = await db.products.find(
        _COMPANY_FILTER, {"_id": 0, "id": 1, "name": 1, "stock": 1,
                          "category": 1, "is_active": 1, "unit": 1}).to_list(5000)
    active = [p for p in products if p.get("is_active", True)]
    counts = await list_counts(day)
    rows = []
    for p in sorted(active, key=lambda x: (x.get("name") or "").lower()):
        c = counts.get(p["id"])
        if c:
            rows.append({
                "name": p.get("name", ""),
                "category": p.get("category", ""),
                "unit": c.get("unit", product_unit(p)),
                "theoretical": qnum(c.get("theoretical_stock")),
                "counted": c.get("counted_qty"),
                "difference": qnum(c.get("difference")),
                "status": c.get("status") or "sin_conteo",
            })
        else:
            rows.append({
                "name": p.get("name", ""),
                "category": p.get("category", ""),
                "unit": product_unit(p),
                "theoretical": qnum(p.get("stock")),
                "counted": None,
                "difference": None,
                "status": "sin_conteo",
            })
    close = await db.inventory_closes.find_one({"close_date": day}, {"_id": 0})
    return {
        "date": day,
        "rows": rows,
        "close": close,
        "productos_contados": len(counts),
        "productos_activos": len(active),
    }


async def _build_close_acta(day: str, review: dict) -> dict:
    """iter332 — datos del acta de cierre: valoración VIVA al cerrar (stock ×
    costo WAC) en CUP + equivalente USDT a la tasa VIP del día, con una fila por
    producto de la empresa. Es la fotografía del inventario al momento de cerrar."""
    products = await db.products.find(
        _COMPANY_FILTER,
        {"_id": 0, "id": 1, "name": 1, "category": 1, "stock": 1,
         "cost_usd": 1, "is_active": 1}).to_list(5000)
    from services.fx_history import get_fx_at
    fx = await get_fx_at(day)
    rate = float(fx.get("rate_vip") or 0)
    rows = []
    tot_cup = 0.0
    units = 0.0
    for p in products:
        stock = float(p.get("stock") or 0)
        cost = float(p.get("cost_usd") or 0)
        val = round(stock * cost, 2)
        if stock == 0 and val == 0:
            continue
        rows.append({
            "product_id": p["id"], "name": p.get("name", ""),
            "category": p.get("category", ""), "stock": stock,
            "cost_usd": round(cost, 4), "value_cup": val,
            "value_usdt": round(val / rate, 2) if rate > 0 else None,
        })
        tot_cup += val
        units += stock
    rows.sort(key=lambda r: -r["value_cup"])
    return {
        "fx": {"rate_vip": rate, "rate_date": fx.get("rate_date"),
               "estimated": bool(fx.get("estimated"))},
        "totals": {
            "num_products": len(rows), "units": round(units, 3),
            "value_cup": round(tot_cup, 2),
            "value_usdt": round(tot_cup / rate, 2) if rate > 0 else None,
        },
        "products": rows,
        "alerts_snapshot": review["alerts"],
    }


async def save_close_review(day: str, responsable: str, revisado_por: str,
                            folio: str, note: str, actor: dict) -> dict:
    """ADMIN — guarda el cierre formal del día (constancia). No bloquea nuevos
    movimientos. El resultado se calcula con las alertas vigentes al cerrar."""
    review = await build_close_review(day)
    now = iso(now_utc())
    # iter327 (IPV-R04) — el estado guardado solo es "cuadra" (conforme/revisado)
    # si el día está completo y sin incidencias Y hay revisor. Sin revisor o con
    # productos sin conteo, no puede presentarse como cierre plenamente revisado.
    resultado = review["resultado_sugerido"]
    if resultado == "cuadra" and not (revisado_por or "").strip():
        resultado = "pendiente"
    doc = {
        "close_date": day,
        "responsable": (responsable or "").strip(),
        "revisado_por": (revisado_por or "").strip(),
        "folio": (folio or "").strip(),
        "note": (note or "").strip(),
        "resultado": resultado,
        "alerts_snapshot": review["alerts"],
        "closed_by": actor.get("user_id", ""),
        "closed_by_email": actor.get("email", ""),
        "closed_at": now,
    }
    await db.inventory_closes.update_one(
        {"close_date": day},
        {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True)
    # iter332 — ACTA CONGELADA inmutable y VERSIONADA: cada cierre deja una copia
    # (existencia + valor CUP/USDT + tasa + firmas) que no se altera aunque luego
    # cambien datos. Una corrección posterior crea una NUEVA versión preservando
    # la anterior como evidencia (trazabilidad de revisiones).
    acta = await _build_close_acta(day, review)
    last = await db.inventory_close_snapshots.find_one(
        {"close_date": day}, {"_id": 0, "version": 1}, sort=[("version", -1)])
    version = ((last or {}).get("version") or 0) + 1
    snap = {
        "id": str(uuid.uuid4()), "close_date": day, "version": version,
        "responsable": doc["responsable"], "revisado_por": doc["revisado_por"],
        "folio": doc["folio"], "note": doc["note"], "resultado": resultado,
        "fx": acta["fx"], "totals": acta["totals"], "products": acta["products"],
        "alerts_snapshot": acta["alerts_snapshot"],
        "frozen_by": actor.get("user_id", ""),
        "frozen_by_email": actor.get("email", ""),
        "frozen_at": now, "immutable": True,
    }
    await db.inventory_close_snapshots.insert_one(snap)
    await db.inventory_closes.update_one(
        {"close_date": day},
        {"$set": {"snapshot_version": version, "snapshot_id": snap["id"],
                  "value_cup": acta["totals"]["value_cup"],
                  "value_usdt": acta["totals"]["value_usdt"],
                  "fx_rate_vip": acta["fx"]["rate_vip"]}})
    return await db.inventory_closes.find_one({"close_date": day}, {"_id": 0})
