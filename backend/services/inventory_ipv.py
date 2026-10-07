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
from pymongo.errors import DuplicateKeyError, OperationFailure

from db_client import db
from auth_utils import now_utc, iso
from services.inventory import (record_movement, today_havana, _day_bounds,
                                _COMPANY_FILTER, OUTPUT_TYPES, MOVEMENT_TYPES,
                                qnum, product_unit, norm_qty)

logger = logging.getLogger(__name__)

_COUNTS_INDEX_READY = False
_SNAP_INDEX_READY = False


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


async def _dedupe_close_snapshots() -> None:
    """iter343 (H06) — red de seguridad para datos heredados del bug: si ya
    existen versiones duplicadas por fecha (p. ej. [1, 1] de dos cierres
    concurrentes), se renumeran por orden cronológico de congelación
    conservando TODAS las actas (evidencia inmutable, sin pérdida) para que el
    índice único pueda crearse. La referencia de `inventory_closes` se re-apunta
    al acta de mayor versión resultante."""
    pipe = [{"$group": {"_id": {"d": "$close_date", "v": "$version"},
                        "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
            {"$group": {"_id": "$_id.d"}}]
    dirty_days = [r["_id"] async for r in
                  db.inventory_close_snapshots.aggregate(pipe)]
    for day in dirty_days:
        snaps = await db.inventory_close_snapshots.find(
            {"close_date": day}, {"_id": 0, "id": 1, "version": 1,
                                  "frozen_at": 1}).to_list(10000)
        snaps.sort(key=lambda s: (s.get("frozen_at") or "",
                                  s.get("version") or 0, s.get("id") or ""))
        last_id, last_ver = "", 0
        for i, s in enumerate(snaps, start=1):
            if s.get("version") != i:
                await db.inventory_close_snapshots.update_one(
                    {"id": s["id"]}, {"$set": {"version": i}})
            last_id, last_ver = s["id"], i
        if last_id:
            await db.inventory_closes.update_one(
                {"close_date": day},
                {"$set": {"snapshot_version": last_ver, "snapshot_id": last_id}})


async def _ensure_close_snapshot_index() -> None:
    global _SNAP_INDEX_READY
    if _SNAP_INDEX_READY:
        return
    try:
        await db.inventory_close_snapshots.create_index(
            [("close_date", 1), ("version", 1)], unique=True)
    except (DuplicateKeyError, OperationFailure):
        await _dedupe_close_snapshots()
        await db.inventory_close_snapshots.create_index(
            [("close_date", 1), ("version", 1)], unique=True)
    _SNAP_INDEX_READY = True


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
        "auth_state": "idle",
        "adjustment_movement_id": None,
        "updated_at": now,
    }
    # iter327 (IPV-R03) — escritura CONDICIONADA a que el conteo NO esté
    # autorizado NI con una autorización en curso (auth_state="claiming"): si
    # una autorización concurrente lo reclamó/marcó entre la lectura y esta
    # escritura, el filtro no casa y el upsert intenta insertar →
    # DuplicateKeyError (índice único product_id+count_date) → 409. Así un
    # recuento atrasado nunca sobrescribe ni desautoriza un ajuste.
    # iter336 (IPV-R03-A) — `version` se incrementa en CADA cambio de contenido;
    # la autorización la reclama de forma atómica, de modo que un recuento
    # concurrente invalida una autorización que leyó una versión anterior.
    try:
        await db.inventory_counts.update_one(
            {"product_id": product["id"], "count_date": day,
             "authorized": {"$ne": True}, "auth_state": {"$ne": "claiming"}},
            {"$set": doc, "$inc": {"version": 1},
             "$setOnInsert": {"created_at": now}}, upsert=True)
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
    # iter327 (IPV-R03) — borrado CONDICIONADO a authorized!=true Y sin
    # autorización en curso (auth_state!="claiming"): si una autorización
    # concurrente reclamó/marcó el conteo entre la lectura anterior y este
    # borrado, el filtro no casa (deleted_count==0) → 409 y la evidencia
    # autorizada se preserva. Evita la micro-ventana read-then-delete (R03-B).
    res = await db.inventory_counts.delete_one(
        {"product_id": product_id, "count_date": day,
         "authorized": {"$ne": True}, "auth_state": {"$ne": "claiming"}})
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
    # iter336 (IPV-R03-A/B) — RECLAMAR atómicamente la versión del contenido
    # ANTES de aplicar el movimiento. El claim casa solo si la versión que
    # leímos sigue vigente y el conteo no está autorizado. Si un recuento
    # concurrente cambió el contenido (version++) o un borrado eliminó el doc,
    # matched_count==0 → 409 y NO se aplica ningún ajuste. Mientras dura el
    # claim (auth_state="claiming"), recuentos y borrados quedan bloqueados.
    version = count.get("version")
    now = iso(now_utc())
    claim = await db.inventory_counts.update_one(
        {"id": count_id, "version": version, "authorized": {"$ne": True}},
        {"$set": {"auth_state": "claiming",
                  "claimed_by": actor.get("user_id", ""),
                  "claimed_at": now,
                  # iter349 — persistimos el respaldo para que el RECUPERADOR
                  # automático pueda completar un ajuste interrumpido con el
                  # mismo documento, sin esperar a que un admin reintente.
                  "adjustment_document": (document or "").strip(),
                  "adjustment_note": note or ""}})
    if claim.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="El conteo cambió o fue autorizado mientras se procesaba. "
                   "Recarga el conteo y vuelve a intentarlo.")
    reason = (f"Ajuste por conteo físico {count['count_date']} · doc: "
              f"{document.strip()}" + (f" · {note.strip()}" if note else ""))
    # Idempotencia del movimiento LIGADA a la versión aprobada (recuperable:
    # un reintento tras interrupción reclama la misma versión y reaplica sin
    # duplicar el ajuste).
    mov = await record_movement(
        product=product, mtype=mtype, quantity=abs(diff), note=reason,
        source="conteo", ref_id=count_id, actor=actor,
        dedupe_key=f"count-adjust:{count_id}:v{version}")
    # H01 (RV-01) — NUNCA finalizar como 'ajustado' si el stock no se aplicó.
    # record_movement ya completa de forma idempotente un ajuste interrumpido;
    # si aun así sigue pendiente (p.ej. stock insuficiente ahora mismo), dejamos
    # el conteo EN CURSO (recuperable) y devolvemos 409 para reintentar, en vez
    # de dar por resuelta una diferencia todavía no aplicada.
    if not mov.get("stock_applied"):
        await db.inventory_counts.update_one(
            {"id": count_id, "version": version, "auth_state": "claiming"},
            {"$set": {"auth_state": "pending_apply",
                      "adjustment_movement_id": mov["id"],
                      "updated_at": iso(now_utc())}})
        raise HTTPException(
            status_code=409,
            detail="El ajuste quedó pendiente de aplicarse al stock. "
                   "Reintenta en unos segundos.")
    await db.inventory_counts.update_one(
        {"id": count_id, "version": version, "auth_state": "claiming"},
        {"$set": {"authorized": True, "status": "ajustado",
                  "auth_state": "authorized", "authorized_version": version,
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


async def _notify_count_recovered(product: dict, count: dict, diff: float,
                                  document: str) -> None:
    """iter350b — avisa a los admins (campana + push) que el Recuperador
    Automático completó un ajuste de conteo tras una interrupción. Sin email
    para no generar ruido: es un evento de sanación operativa, no una alerta."""
    name = product.get("name") or product.get("id")
    unit = product_unit(product)
    sign = "+" if diff > 0 else "−"
    qty = abs(round(diff, 3))
    title = "Ajuste de conteo recuperado"
    body = (f"El ajuste del conteo físico de «{name}» "
            f"({count.get('count_date')}) se aplicó automáticamente tras una "
            f"interrupción: {sign}{qty} {unit} · doc: {document}.")
    url_path = "/admin/inventory"
    admins = await db.users.find({"role": "admin"}, {"_id": 0}).to_list(50)
    if not admins:
        return
    try:
        from admin_alerts import APP_URL, _push_fanout_to_admins
        target_url = f"{APP_URL}{url_path}" if APP_URL else url_path
        payload = {"title": title, "body": body,
                   "icon": "/icons/icon-192.png",
                   "badge": "/icons/icon-192.png",
                   "tag": f"ipv-recover-{(count.get('id') or '')[:20]}",
                   "url": target_url}
        _, dead_ids = await _push_fanout_to_admins(db, admins, payload)
        if dead_ids:
            await db.push_subscriptions.delete_many({"id": {"$in": dead_ids}})
    except Exception as e:  # noqa: BLE001
        logger.error(f"[ipv-recover] push a admins falló: {e}")
    try:
        from routes.notifications import _insert_notification
        for a in admins:
            await _insert_notification(
                recipient_user_id=a["user_id"], type="ipv_count_recovered",
                title=title, message=body,
                data={"product_id": product.get("id"),
                      "count_id": count.get("id"),
                      "count_date": count.get("count_date"),
                      "difference": round(diff, 3), "document": document})
    except Exception as e:  # noqa: BLE001
        logger.error(f"[ipv-recover] campana a admins falló: {e}")


async def _recover_one_count(count: dict) -> bool:
    """Completa, de forma idempotente, UN conteo cuyo ajuste quedó a medias.

    Reusa el mismo `dedupe_key` del movimiento (identidad única y persistente del
    efecto) y el `adjustment_document` ya guardado en el claim, por lo que puede
    invocarse cualquier número de veces sin duplicar el ajuste. Devuelve True si
    el conteo quedó finalmente AUTORIZADO (stock aplicado)."""
    count_id = count["id"]
    version = count.get("version")
    document = (count.get("adjustment_document") or "").strip()
    note = count.get("adjustment_note") or ""
    # Sin el respaldo persistido (claims anteriores a iter349) no podemos
    # completar el ajuste automáticamente; se deja para reintento manual.
    if not document:
        return False
    diff = qnum(count.get("difference"))
    if abs(diff) < 1e-9:
        return False
    product = await db.products.find_one({"id": count["product_id"]}, {"_id": 0})
    if not product:
        return False
    mtype = "ajuste_pos" if diff > 0 else "ajuste_neg"
    actor = {"user_id": count.get("claimed_by") or "system.recoverer",
             "email": count.get("authorized_by_email")
             or "system@resiliencebrothers.com"}
    reason = (f"Ajuste por conteo físico {count['count_date']} · doc: "
              f"{document}" + (f" · {note.strip()}" if note else ""))
    mov = await record_movement(
        product=product, mtype=mtype, quantity=abs(diff), note=reason,
        source="conteo", ref_id=count_id, actor=actor,
        dedupe_key=f"count-adjust:{count_id}:v{version}")
    now = iso(now_utc())
    if not mov.get("stock_applied"):
        # Aún no se pudo aplicar (p.ej. stock insuficiente ahora mismo): se deja
        # PENDIENTE para el siguiente ciclo del recuperador.
        await db.inventory_counts.update_one(
            {"id": count_id, "version": version, "authorized": {"$ne": True}},
            {"$set": {"auth_state": "pending_apply",
                      "adjustment_movement_id": mov["id"],
                      "updated_at": now}})
        return False
    res = await db.inventory_counts.update_one(
        {"id": count_id, "version": version, "authorized": {"$ne": True}},
        {"$set": {"authorized": True, "status": "ajustado",
                  "auth_state": "authorized", "authorized_version": version,
                  "adjustment_movement_id": mov["id"],
                  "adjustment_document": document,
                  "adjustment_note": note,
                  "authorized_by": actor["user_id"],
                  "authorized_by_email": actor["email"],
                  "recovered_at": now, "authorized_at": now, "updated_at": now}})
    if not res.modified_count:
        return False
    # La diferencia quedó ajustada → resolver la incidencia asociada.
    try:
        from services.inventory_incidents import on_count_authorized
        await on_count_authorized(count_id)
    except Exception as e:  # noqa: BLE001
        logger.error(f"incident on_count_authorized (recover) failed: {e}")
    # Aviso a los admins (campana + push) de que la red de seguridad actuó.
    try:
        await _notify_count_recovered(product, count, diff, document)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[ipv-recover] aviso a admins falló: {e}")
    return True


async def recover_pending_count_adjustments(stale_seconds: int = 60) -> int:
    """RECUPERADOR AUTOMÁTICO (iter350) — completa ajustes de conteo físico que
    quedaron a medio aplicar tras una interrupción (crash entre el claim/registro
    del movimiento y la aplicación del stock), sin esperar a que un admin
    reintente manualmente.

    Busca conteos NO autorizados en dos estados:
    - `pending_apply`: el movimiento ya se registró pero el stock no se aplicó;
      se procesa de inmediato (la petición del admin ya devolvió 409).
    - `claiming` estancado (claim más viejo que `stale_seconds`): el claim quedó
      colgado; se completa sin competir con una autorización de admin en curso.

    Idempotente por `dedupe_key` del movimiento: nunca duplica el ajuste.
    Devuelve el número de conteos sanados."""
    from datetime import timedelta
    cutoff = iso(now_utc() - timedelta(seconds=stale_seconds))
    stuck = await db.inventory_counts.find(
        {"authorized": {"$ne": True},
         "$or": [
             {"auth_state": "pending_apply"},
             {"auth_state": "claiming", "claimed_at": {"$lt": cutoff}},
         ]},
        {"_id": 0}).to_list(500)
    healed = 0
    for count in stuck:
        try:
            if await _recover_one_count(count):
                healed += 1
        except Exception as e:  # noqa: BLE001
            logger.error(f"[ipv-recover] conteo {count.get('id')} falló: {e}")
    if healed:
        logger.info("[ipv-recover] %s ajuste(s) de conteo completados", healed)
    return healed



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
    """iter340 (H05) — datos del acta de cierre BASADOS EN LA RECONSTRUCCIÓN
    HISTÓRICA del día `day` (no en el stock/costo VIVO de hoy). Antes leía
    `products` en el presente, de modo que el acta de una fecha pasada congelaba
    la existencia/WAC actuales y no coincidía con el corte histórico de ese día.
    Ahora toma existencia, costo WAC, valor CUP/USDT y tasa de la fecha efectiva
    del corte, para que pantalla histórica, exportación y acta concuerden."""
    from services.inventory_history import build_cutoff_report
    rep = await build_cutoff_report(day)
    fxr = rep.get("fx") or {}
    rate = float(fxr.get("rate") or 0)
    rows = []
    tot_cup = 0.0
    # H12 (iter345) — cantidades físicas agregadas por unidad (u/lb/kg), nunca
    # mezcladas en un único número sin significado.
    units_by_unit: dict = {}
    partials = 0
    for p in rep.get("products", []):
        stock = float(p.get("final_stock") or 0)
        cost = float(p.get("wac") or 0)
        val = float(p.get("value") or 0)
        if stock == 0 and val == 0:
            continue
        if p.get("coverage") == "parcial":
            partials += 1
        unit = p.get("unit", "unidad")
        rows.append({
            "product_id": p["product_id"], "name": p.get("name", ""),
            "category": p.get("category", ""), "stock": stock, "unit": unit,
            "cost_usd": round(cost, 4), "value_cup": val,
            "value_usdt": p.get("value_usdt"),
            "coverage": p.get("coverage", "completa"),
            "undocumented_base": bool(p.get("undocumented_base")),
        })
        tot_cup += val
        if stock > 0:
            units_by_unit[unit] = units_by_unit.get(unit, 0.0) + stock
    rows.sort(key=lambda r: -r["value_cup"])
    return {
        # Fecha EFECTIVA del corte (lo que valora el acta) vs momento de captura
        # (frozen_at del snapshot): el acta refleja la situación de `day`.
        "cutoff": day,
        "basis": "historico",
        "fx": {"rate_vip": rate, "rate_date": fxr.get("rate_date"),
               "estimated": bool(fxr.get("estimated"))},
        "totals": {
            "num_products": len(rows),
            "units_by_unit": {u: round(v, 3) for u, v in units_by_unit.items()},
            "value_cup": round(tot_cup, 2),
            "value_usdt": round(tot_cup / rate, 2) if rate > 0 else None,
            "partial_count": partials,
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
    # iter343 (H06) — asignación ATÓMICA de versión por fecha. El índice único
    # (close_date, version) arbitra: si dos cierres concurrentes calculan la
    # misma versión, solo uno inserta y el perdedor REINTENTA con la siguiente,
    # de modo que ambas actas quedan con versiones inequívocas (nunca [1,1]).
    await _ensure_close_snapshot_index()
    snap_id = str(uuid.uuid4())
    version = 0
    snap: dict = {}
    for _ in range(50):
        last = await db.inventory_close_snapshots.find_one(
            {"close_date": day}, {"_id": 0, "version": 1},
            sort=[("version", -1)])
        version = ((last or {}).get("version") or 0) + 1
        snap = {
            "id": snap_id, "close_date": day, "version": version,
            "responsable": doc["responsable"],
            "revisado_por": doc["revisado_por"],
            "folio": doc["folio"], "note": doc["note"], "resultado": resultado,
            "cutoff": acta.get("cutoff"), "basis": acta.get("basis"),
            "fx": acta["fx"], "totals": acta["totals"],
            "products": acta["products"],
            "alerts_snapshot": acta["alerts_snapshot"],
            "frozen_by": actor.get("user_id", ""),
            "frozen_by_email": actor.get("email", ""),
            "frozen_at": now, "immutable": True,
        }
        try:
            await db.inventory_close_snapshots.insert_one(snap)
            break
        except DuplicateKeyError:
            continue
    else:
        raise HTTPException(
            status_code=409,
            detail=("No se pudo asignar una versión única del acta por "
                    "concurrencia; vuelve a intentarlo."))
    # iter343 (H06) — la referencia de `inventory_closes` solo avanza: una
    # operación atrasada (versión menor) NUNCA sustituye el puntero a una
    # revisión posterior ya registrada; su acta queda archivada igual.
    await db.inventory_closes.update_one(
        {"close_date": day,
         "$or": [{"snapshot_version": {"$exists": False}},
                 {"snapshot_version": {"$lt": version}}]},
        {"$set": {"snapshot_version": version, "snapshot_id": snap["id"],
                  "value_cup": acta["totals"]["value_cup"],
                  "value_usdt": acta["totals"]["value_usdt"],
                  "fx_rate_vip": acta["fx"]["rate_vip"]}})
    return await db.inventory_closes.find_one({"close_date": day}, {"_id": 0})



# ═══════════════ IPV H04 — Apertura auditada de base legacy ═══════════════
async def _documented_stock_delta(product_id: str) -> float:
    """iter341 (H04) — suma de deltas de TODOS los movimientos de stock
    CONFIRMADOS del producto (incluida la 'alta'). Mide cuánta existencia está
    DOCUMENTADA por el log; la diferencia con el stock real es la base SIN
    documentar que la apertura auditada viene a registrar."""
    pipe = [
        {"$match": {"product_id": product_id,
                    "type": {"$in": list(MOVEMENT_TYPES)},
                    "$or": [{"needs_stock": {"$ne": True}},
                            {"stock_applied": True}]}},
        {"$group": {"_id": None, "delta": {"$sum": {"$switch": {
            "branches": [{"case": {"$in": ["$type", ["entrada", "ajuste_pos"]]},
                          "then": {"$ifNull": ["$quantity", 0]}}],
            "default": {"$multiply": [{"$ifNull": ["$quantity", 0]}, -1]}}}}}},
    ]
    rows = await db.inventory_movements.aggregate(pipe).to_list(1)
    return round(float(rows[0]["delta"]) if rows else 0.0, 3)


async def _undocumented_gap(product: dict) -> float:
    """Existencia real − existencia documentada (≥0 cuando falta base)."""
    documented = await _documented_stock_delta(product["id"])
    return round(qnum(product.get("stock")) - documented, 3)


async def register_audited_opening(product_id: str,
                                   cost_usd: Optional[float] = None,
                                   note: str = "",
                                   actor: Optional[dict] = None) -> dict:
    """iter341 (H04) — Registra una APERTURA AUDITADA que documenta la base sin
    documentar de un producto legacy (existencia real sin movimiento de origen).
    Crea un movimiento 'entrada' (source='apertura_auditada', apply_stock=False:
    el stock YA existe) y su lote, SIN tocar el fondo de la empresa. Tras esto, el
    stock real queda explicado por el log y el corte deja de marcarlo parcial."""
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if product.get("owner_id"):
        raise HTTPException(
            status_code=400,
            detail="Solo los productos de la empresa admiten apertura auditada.")
    gap = await _undocumented_gap(product)
    if abs(gap) < 0.001:
        raise HTTPException(
            status_code=400,
            detail="Este producto ya tiene su existencia documentada; no "
                   "requiere apertura auditada.")
    if gap < 0:
        raise HTTPException(
            status_code=400,
            detail="La existencia documentada supera a la real; revisa los "
                   "movimientos antes de registrar una apertura.")
    cost = float(cost_usd if cost_usd is not None
                 else (product.get("cost_usd") or 0))
    mov = await record_movement(
        product=product, mtype="entrada", quantity=gap, unit_cost=cost,
        note=((note or "").strip()
              or "Apertura auditada: existencia inicial sin movimiento de origen."),
        source="apertura_auditada", actor=actor, apply_stock=False)
    from services.inventory_lots import record_lot
    await record_lot(product, gap, cost, (mov or {}).get("id", ""),
                     source="apertura_auditada", actor=actor)
    return {
        "product_id": product_id, "name": product.get("name", ""),
        "opening_qty": gap, "unit": product_unit(product),
        "cost_usd": round(cost, 4), "value_cup": round(gap * cost, 2),
        "movement_id": (mov or {}).get("id", ""),
    }


async def register_audited_openings_bulk(actor: Optional[dict] = None) -> dict:
    """Registra la apertura auditada de TODOS los productos de la empresa con
    base sin documentar. Idempotente: los ya documentados se omiten."""
    products = await db.products.find(
        _COMPANY_FILTER,
        {"_id": 0, "id": 1, "name": 1, "stock": 1, "cost_usd": 1,
         "owner_id": 1, "unit": 1}).to_list(5000)
    items = []
    total_cup = 0.0
    for p in products:
        if p.get("owner_id"):
            continue
        try:
            r = await register_audited_opening(p["id"], None, "", actor)
        except HTTPException:
            continue  # ya documentado / gap inválido
        items.append(r)
        total_cup += r["value_cup"]
    return {"processed": len(items), "value_cup": round(total_cup, 2),
            "items": items}
