"""Control de inventario de la tienda física — iter217.

Endpoints (todos staff con permiso 'products'):
- GET  /admin/inventory/control              tabla en tiempo real por producto
- GET  /admin/inventory/movements            registro de entradas y salidas
- POST /admin/inventory/movements            registrar movimiento manual
- GET  /admin/inventory/dashboard            KPIs del período
"""
import logging
from typing import Optional, Literal, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import require_permission, now_utc, iso, _enforce_totp_step_up
from audit_log import log_action
from services.inventory import (record_movement, record_price_change,
                                _day_bounds, today_havana,
                                build_control_rows, build_dashboard,
                                build_rotation, qnum, UNIT_ABBR)
from services.inventory_ipv import (record_physical_count, clear_physical_count,
                                     authorize_count_adjustment,
                                     build_close_review, save_close_review,
                                     build_count_sheet)
from services.proof_upload import maybe_upload_proof

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Inventory"])

_TYPE_LABELS = {"entrada": "Entrada", "venta": "Venta",
                "ajuste_pos": "Ajuste +", "ajuste_neg": "Ajuste −",
                "merma": "Merma", "consumo": "Consumo interno",
                "otra_salida": "Otra salida"}


class MovementCreate(BaseModel):
    # iter219 — los ajustes manuales se retiraron a pedido del operador:
    # solo Entrada y Venta (los reversos internos siguen usando ajuste_pos).
    # iter320 (IPV) — además, salidas NO-venta: merma, consumo interno y otras
    # salidas (traslado / devolución a proveedor).
    product_id: str
    type: Literal["entrada", "venta", "merma", "consumo", "otra_salida"]
    quantity: float = Field(..., gt=0, le=1_000_000)
    unit_price: Optional[float] = Field(None, ge=0)
    unit_cost: Optional[float] = Field(None, ge=0)
    # iter219 — en una Entrada permite actualizar el precio de venta del
    # producto (ficha de costo del Excel). Queda auditado como tipo 'precio'.
    sale_price: Optional[float] = Field(None, ge=0)
    note: str = Field("", max_length=300)
    # iter219 — foto opcional del producto en oferta (base64 data URL → R2).
    photo_url: str = ""


@router.get("/admin/inventory/control")
async def inventory_control(request: Request) -> Any:
    await require_permission(request, "products")
    return await build_control_rows()


@router.get("/admin/inventory/movements")
async def list_movements(request: Request, product_id: Optional[str] = None,
                         type: Optional[str] = None,
                         start: Optional[str] = None,
                         end: Optional[str] = None,
                         limit: int = 200) -> Any:
    await require_permission(request, "products")
    q: dict = {}
    if product_id:
        q["product_id"] = product_id
    if type:
        q["type"] = type
    created: dict = {}
    if start:
        created["$gte"] = _day_bounds(start)[0]
    if end:
        created["$lt"] = _day_bounds(end)[1]
    if created:
        q["created_at"] = created
    limit = max(1, min(int(limit), 500))
    return await db.inventory_movements.find(q, {"_id": 0}) \
        .sort("created_at", -1).to_list(limit)


@router.post("/admin/inventory/movements")
async def create_movement(payload: MovementCreate, request: Request) -> Any:
    actor = await require_permission(request, "products")
    product = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if product.get("owner_id"):
        raise HTTPException(
            status_code=400,
            detail="Los productos de vendedores VIP no entran al inventario de la empresa")
    from services.inventory import sells_fraction
    if not sells_fraction(product) and float(payload.quantity) != int(payload.quantity):
        raise HTTPException(
            status_code=400,
            detail="Este producto se vende por unidad: la cantidad debe ser un número entero.")
    photo = maybe_upload_proof(payload.photo_url, "inventory") or "" if payload.photo_url else ""
    doc = await record_movement(
        product=product, mtype=payload.type, quantity=payload.quantity,
        unit_price=payload.unit_price, unit_cost=payload.unit_cost,
        note=payload.note, source="manual", actor=actor, photo_url=photo)
    # iter219 — una Entrada puede actualizar el precio de venta del producto.
    # iter327 (IPV-R02) — el COSTO promedio (WAC) ya se funde ATÓMICAMENTE junto
    # con el stock dentro de record_movement (no se recalcula aquí con lecturas
    # viejas). iter327 (IPV-R01) — el precio y el retiro de la oferta se escriben
    # en un pipeline CONDICIONAL atómico: la oferta solo se retira si el precio
    # ALMACENADO cambia tras el redondeo (una liquidación concurrente no queda
    # con un descuento obsoleto; y 400.001→400.00 no retira la oferta).
    if payload.type == "entrada":
        from services.inventory_lots import record_lot
        old_cost = float(product.get("cost_usd") or 0)
        entry_cost = (float(payload.unit_cost) if payload.unit_cost is not None
                      else old_cost)
        if payload.sale_price is not None:
            new_price = round(float(payload.sale_price), 2)
            changed = {"$ne": [{"$round": [{"$ifNull": ["$price_usd", 0]}, 2]},
                               new_price]}
            await db.products.update_one(
                {"id": product["id"]},
                [{"$set": {
                    "price_usd": {"$cond": [changed, new_price, {"$ifNull": ["$price_usd", 0]}]},
                    "on_offer": {"$cond": [changed, False, {"$ifNull": ["$on_offer", False]}]},
                    "offer_original_price": {"$cond": [changed, "$$REMOVE", "$offer_original_price"]},
                    "offer_discount_pct": {"$cond": [changed, "$$REMOVE", "$offer_discount_pct"]},
                    "offer_at": {"$cond": [changed, "$$REMOVE", "$offer_at"]},
                }}])
            # Auditoría best-effort del cambio de precio (solo si cambió).
            after = await db.products.find_one({"id": product["id"]},
                                               {"_id": 0, "price_usd": 1})
            old_price = float(product.get("price_usd") or 0)
            if after and abs(float(after.get("price_usd") or 0) - old_price) > 1e-9:
                await record_price_change(
                    product=product, field_label="Precio venta",
                    old=old_price, new=float(after["price_usd"]), actor=actor)
        # Auditoría del WAC (re-leído tras el fundido atómico en record_movement).
        after_cost = await db.products.find_one({"id": product["id"]},
                                                {"_id": 0, "cost_usd": 1})
        new_wac = float((after_cost or {}).get("cost_usd") or 0)
        if abs(new_wac - old_cost) > 1e-9:
            await record_price_change(
                product=product, field_label="Costo promedio ponderado",
                old=old_cost, new=new_wac, actor=actor, change_kind="cost")
        try:
            await record_lot(product, payload.quantity, entry_cost, doc["id"],
                             source=doc.get("source") or "manual", actor=actor)
        except Exception as e:  # noqa: BLE001
            logger.error(f"record_lot failed: {e}")
    await log_action(
        db, actor, f"inventory.{payload.type}", "inventory_movement", doc["id"],
        summary=(f"{_TYPE_LABELS[payload.type]} {payload.quantity}× "
                 f"{product.get('name', '')}"),
        details={"product_id": product["id"], "quantity": payload.quantity,
                 "total": doc["total"], "note": payload.note})
    try:
        from services.live_bus import publish
        await publish("products_changed", {"product_id": product["id"]})
    except Exception as e:  # noqa: BLE001
        logger.error(f"products_changed publish failed: {e}")
    return doc


# ══════════════════ IPV: Conteo físico + Revisión del cierre (iter320) ═══════
async def _require_admin_products(request: Request) -> dict:
    """Solo un administrador revisa/cierra y autoriza ajustes de conteo
    (separación de funciones: cualquier staff con 'products' puede contar)."""
    actor = await require_permission(request, "products")
    if actor.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Solo un administrador puede revisar/cerrar el día o "
                   "autorizar un ajuste por conteo.")
    return actor


class CountCreate(BaseModel):
    product_id: str
    counted_qty: float = Field(..., ge=0, le=100_000_000)
    note: str = Field("", max_length=300)


class CountAdjust(BaseModel):
    document: str = Field(..., min_length=2, max_length=300)
    note: str = Field("", max_length=300)


class CloseReviewSave(BaseModel):
    date: str = Field(..., min_length=10, max_length=10)
    responsable: str = Field("", max_length=120)
    revisado_por: str = Field("", max_length=120)
    folio: str = Field("", max_length=60)
    note: str = Field("", max_length=300)


class MinStockUpdate(BaseModel):
    # iter332 (IPV Fase 2) — None limpia el mínimo propio (vuelve al global).
    # iter335 (IPV Fase 4) — admite decimales para productos por fracción (lb/kg).
    min_stock: float | None = Field(None, ge=0, le=1_000_000)


class TargetStockUpdate(BaseModel):
    # iter333 — None limpia el objetivo (usa el mínimo como objetivo).
    target_stock: float | None = Field(None, ge=0, le=1_000_000)


class IncidentStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(pendiente|en_revision|resuelta)$")
    note: str = Field("", max_length=400)


@router.post("/admin/inventory/counts")
async def create_count(payload: CountCreate, request: Request) -> Any:
    """Registra/actualiza el conteo físico de hoy de un producto (staff con
    permiso 'products'). No altera el stock."""
    actor = await require_permission(request, "products")
    product = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if product.get("owner_id"):
        raise HTTPException(
            status_code=400,
            detail="Los productos de vendedores VIP no entran al inventario de la empresa")
    from services.inventory import sells_fraction
    if not sells_fraction(product) and float(payload.counted_qty) != int(payload.counted_qty):
        raise HTTPException(
            status_code=400,
            detail="Este producto se cuenta por unidad: usa un número entero.")
    doc = await record_physical_count(product, payload.counted_qty, actor,
                                      payload.note)
    await log_action(
        db, actor, "inventory.count", "inventory_count", doc["id"],
        summary=f"Conteo {product.get('name', '')}: {payload.counted_qty} "
                f"(dif {doc['difference']})",
        details={"product_id": product["id"],
                 "counted_qty": payload.counted_qty,
                 "difference": doc["difference"], "status": doc["status"]})
    return doc


@router.delete("/admin/inventory/counts/{product_id}")
async def delete_count(product_id: str, request: Request,
                       date: Optional[str] = None) -> Any:
    """Borra el conteo del día (vuelve a SIN CONTEO)."""
    await require_permission(request, "products")
    await clear_physical_count(product_id, date)
    return {"ok": True}


@router.post("/admin/inventory/counts/{count_id}/adjust")
async def adjust_count(count_id: str, payload: CountAdjust,
                       request: Request) -> Any:
    """ADMIN — aplica la diferencia del conteo como ajuste de stock
    AUTORIZADO, exigiendo documento de respaldo."""
    actor = await _require_admin_products(request)
    doc = await authorize_count_adjustment(count_id, payload.document,
                                           payload.note, actor)
    await log_action(
        db, actor, "inventory.count_adjust", "inventory_count", count_id,
        summary=f"Ajuste por conteo {doc.get('product_name', '')} "
                f"(dif {doc.get('difference')})",
        details={"product_id": doc.get("product_id"),
                 "document": payload.document,
                 "movement_id": doc.get("adjustment_movement_id")})
    try:
        from services.live_bus import publish
        await publish("products_changed", {"product_id": doc.get("product_id")})
    except Exception as e:  # noqa: BLE001
        logger.error(f"products_changed publish failed: {e}")
    return doc


@router.get("/admin/inventory/close-review")
async def close_review(request: Request, date: Optional[str] = None) -> Any:
    """Resumen de revisión del cierre del día: alertas (SIN CONTEO,
    diferencias, salidas sin documento), salidas no-venta y cierre guardado."""
    from datetime import datetime
    await require_permission(request, "products")
    day = (date or today_havana())[:10]
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="Fecha inválida (formato YYYY-MM-DD)")
    return await build_close_review(day)


@router.post("/admin/inventory/close-review")
async def post_close_review(payload: CloseReviewSave, request: Request) -> Any:
    """ADMIN — guarda el cierre formal del día (responsable/revisor/folio).
    Deja constancia, no bloquea nuevos movimientos."""
    from datetime import datetime
    actor = await _require_admin_products(request)
    try:
        datetime.strptime(payload.date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="Fecha inválida (formato YYYY-MM-DD)")
    if not (payload.responsable or "").strip():
        raise HTTPException(status_code=400,
                            detail="Indica el responsable del cierre.")
    doc = await save_close_review(payload.date, payload.responsable,
                                  payload.revisado_por, payload.folio,
                                  payload.note, actor)
    await log_action(
        db, actor, "inventory.close_review", "inventory_close", payload.date,
        summary=f"Cierre {payload.date}: {doc.get('resultado', '').upper()} "
                f"· folio {doc.get('folio') or '—'}",
        details={"resultado": doc.get("resultado"),
                 "alerts": doc.get("alerts_snapshot")})
    return doc


# ══════════════════ IPV Fase 1: Corte histórico del inventario ══════════════
def _valid_day(day: str, field: str = "date") -> str:
    from datetime import datetime
    day = (day or "")[:10]
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400,
                            detail=f"Fecha inválida en '{field}' (YYYY-MM-DD)")
    return day


@router.get("/admin/inventory/cutoff-report")
async def inventory_cutoff_report(request: Request, date: Optional[str] = None,
                                  start: Optional[str] = None) -> Any:
    """IPV Fase 1 — reporte histórico del inventario a una FECHA DE CORTE.
    Reconstruye existencia y valor (CUP) desde los movimientos hasta el corte;
    opcionalmente acumula flujos del período [start, corte]. Valora las
    diferencias de conteo del día al costo de referencia guardado."""
    await require_permission(request, "products")
    from services.inventory_history import build_cutoff_report
    cutoff = _valid_day(date or today_havana(), "date")
    period = _valid_day(start, "start") if start else None
    if period and period > cutoff:
        raise HTTPException(status_code=400,
                            detail="'start' no puede ser posterior a la fecha de corte")
    return await build_cutoff_report(cutoff, period)


@router.get("/admin/inventory/cutoff-report.csv")
async def inventory_cutoff_report_csv(request: Request,
                                      date: Optional[str] = None,
                                      start: Optional[str] = None) -> Any:
    """IPV Fase 1 — CSV contable del corte histórico."""
    import csv
    import io
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from services.inventory_history import build_cutoff_report

    await require_permission(request, "products")
    cutoff = _valid_day(date or today_havana(), "date")
    period = _valid_day(start, "start") if start else None
    if period and period > cutoff:
        raise HTTPException(status_code=400,
                            detail="'start' no puede ser posterior a la fecha de corte")
    data = await build_cutoff_report(cutoff, period)
    fx = data.get("fx") or {}
    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    writer.writerow([
        "Producto", "Categoría", "Activo", "Existencia inicial", "Entradas",
        "Ventas", "Merma", "Consumo", "Otras salidas", "Ajuste neto",
        "Existencia final", f"Costo WAC ({data['currency']})",
        f"Valor ({data['currency']})", "Valor (USDT)", "Cobertura",
        "Conteo físico", "Teórico", "Diferencia", "Unidad", "Costo ref.",
        "Valor diferencia", "Autorizado"])
    for p in data["products"]:
        c = p.get("count") or {}
        writer.writerow([
            p["name"], p["category"], "Sí" if p["is_active"] else "No",
            p["opening"], p["entradas"], p["ventas"], p["merma"], p["consumo"],
            p["otra_salida"], p["ajuste_neto"], p["final_stock"], p["wac"],
            p["value"], p.get("value_usdt", "") if p.get("value_usdt") is not None else "",
            p["coverage"],
            c.get("counted_qty", "") if c else "",
            c.get("theoretical", "") if c else "",
            c.get("difference", "") if c else "",
            (UNIT_ABBR.get(c.get("unit", ""), c.get("unit", "")) if c else ""),
            c.get("reference_cost", "") if c else "",
            c.get("difference_value", "") if c else "",
            ("Sí" if c.get("authorized") else "No") if c else ""])
    t = data["totals"]
    writer.writerow([])
    writer.writerow(["TOTALES", "", "", "", "", "", "", "", "", "",
                     t["units"], "", t["value"],
                     t.get("value_usdt", "") if t.get("value_usdt") is not None else "",
                     f"{t['partial_count']} parcial(es)",
                     "", "", "", "", "", t["diff_value"], ""])
    writer.writerow([])
    writer.writerow([f"Tasa USDT→CUP (VIP) al corte: {fx.get('rate') or '—'}"
                     + (f" (estimada, {fx.get('rate_date') or 's/d'})"
                        if fx.get("estimated") else f" ({fx.get('rate_date') or ''})")])
    buf = BytesIO()
    buf.write(text_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    fname = f"inventario_corte_{cutoff}.csv"
    return StreamingResponse(
        buf, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/admin/inventory/fx-variation")
async def inventory_fx_variation(request: Request, cut: Optional[str] = None,
                                 ref: Optional[str] = None) -> Any:
    """IPV Fase 1+ — efecto de la variación de la tasa USDT↔CUP sobre el valor
    del inventario. El inventario se controla en CUP; su valor en USDT depende
    de la tasa VIGENTE. Compara la tasa VIP de la fecha de corte `cut` contra la
    de una fecha de referencia `ref` y calcula cuánto se gana/pierde en USDT (y
    su %) sobre el valor ACTUAL del inventario, por el solo movimiento de la
    tasa (el CUP se mantiene constante en la comparación)."""
    from services.fx_history import get_fx_at
    from services.inventory import _COMPANY_FILTER
    await require_permission(request, "products")
    cut_d = _valid_day(cut or today_havana(), "cut")
    if not ref:
        raise HTTPException(status_code=400,
                            detail="Indica una fecha de referencia")
    ref_d = _valid_day(ref, "ref")
    products = await db.products.find(
        _COMPANY_FILTER, {"_id": 0, "stock": 1, "cost_usd": 1}).to_list(5000)
    value_cup = round(sum(float(p.get("stock") or 0) * float(p.get("cost_usd") or 0)
                          for p in products), 2)
    fx_cut = await get_fx_at(cut_d)
    fx_ref = await get_fx_at(ref_d)
    rc = float(fx_cut.get("rate_vip") or 0)
    rr = float(fx_ref.get("rate_vip") or 0)
    usdt_cut = round(value_cup / rc, 2) if rc > 0 else None
    usdt_ref = round(value_cup / rr, 2) if rr > 0 else None
    delta_usdt = (round(usdt_cut - usdt_ref, 2)
                  if (usdt_cut is not None and usdt_ref is not None) else None)
    delta_pct = round((rr / rc - 1) * 100, 2) if (rc > 0 and rr > 0) else None
    direction = "flat"
    if delta_usdt is not None:
        direction = "loss" if delta_usdt < 0 else "gain" if delta_usdt > 0 else "flat"
    return {
        "cut_date": cut_d,
        "ref_date": ref_d,
        "currency_store": "CUP",
        "quote_currency": "USDT",
        "rate_field": "rate_vip",
        "value_cup": value_cup,
        "cut": {"rate": rc, "rate_date": fx_cut.get("rate_date"),
                "estimated": bool(fx_cut.get("estimated")), "value_usdt": usdt_cut},
        "ref": {"rate": rr, "rate_date": fx_ref.get("rate_date"),
                "estimated": bool(fx_ref.get("estimated")), "value_usdt": usdt_ref},
        "delta_usdt": delta_usdt,
        "delta_pct": delta_pct,
        "direction": direction,
    }


@router.patch("/admin/inventory/products/{product_id}/min-stock")
async def set_product_min_stock(product_id: str, payload: MinStockUpdate,
                                request: Request) -> Any:
    """IPV Fase 2 — fija (o limpia con null) el stock mínimo de un producto de
    la empresa. Dispara la re-evaluación de la alerta de existencias bajas."""
    await require_permission(request, "products")
    existing = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not existing or existing.get("owner_id"):
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    from services.inventory import sells_fraction
    val = payload.min_stock
    if val is not None:
        val = qnum(val) if sells_fraction(existing) else float(round(qnum(val)))
    await db.products.update_one(
        {"id": product_id}, {"$set": {"min_stock": val}})
    from services.inventory import maybe_alert_low_stock
    await maybe_alert_low_stock(product_id)
    return {"ok": True, "product_id": product_id, "min_stock": val}


@router.get("/admin/inventory/close-snapshot")
async def inventory_close_snapshot(request: Request, date: Optional[str] = None,
                                   version: Optional[int] = None) -> Any:
    """IPV — acta de cierre CONGELADA de un día (existencia + valor CUP/USDT +
    tasa + firmas). Devuelve la última versión (o la pedida) y el listado de
    versiones para auditar correcciones posteriores."""
    await require_permission(request, "products")
    day = _valid_day(date or today_havana(), "date")
    q: dict = {"close_date": day}
    if version is not None:
        q["version"] = version
    snap = await db.inventory_close_snapshots.find_one(
        q, {"_id": 0}, sort=[("version", -1)])
    versions = await db.inventory_close_snapshots.find(
        {"close_date": day},
        {"_id": 0, "version": 1, "frozen_at": 1, "resultado": 1,
         "frozen_by_email": 1, "responsable": 1, "revisado_por": 1,
         "totals": 1, "fx": 1}).sort("version", -1).to_list(100)
    return {"date": day, "snapshot": snap, "versions": versions}


# ═══════════ IPV H04 — Apertura auditada de base legacy sin documentar ══════
class OpeningRegister(BaseModel):
    cost_usd: Optional[float] = Field(None, ge=0, le=100_000_000)
    note: str = Field("", max_length=300)


class OpeningBulk(BaseModel):
    totp_code: Optional[str] = Field(None, max_length=11)


@router.post("/admin/inventory/products/{product_id}/register-opening")
async def register_opening(product_id: str, payload: OpeningRegister,
                           request: Request) -> Any:
    """IPV (H04) — documenta la existencia inicial de un producto legacy cuyo
    stock no estaba respaldado por movimientos (corte lo marcaba PARCIAL)."""
    actor = await require_permission(request, "products")
    from services.inventory_ipv import register_audited_opening
    res = await register_audited_opening(
        product_id, payload.cost_usd, payload.note, actor)
    await log_action(
        db, actor, "inventory.audited_opening", "product", product_id,
        summary=(f"Apertura auditada {res['name']}: {res['opening_qty']} "
                 f"{res['unit']} @ {res['cost_usd']} ({res['value_cup']} CUP)"),
        details=res)
    return res


@router.post("/admin/inventory/register-openings-bulk")
async def register_openings_bulk(payload: OpeningBulk, request: Request) -> Any:
    """IPV (H04) — registra la apertura auditada de TODOS los productos de la
    empresa con base sin documentar. Requiere 2FA (acción masiva sensible)."""
    actor = await require_permission(request, "products")
    await _enforce_totp_step_up(
        actor, payload.totp_code,
        action_label="registrar aperturas auditadas en bloque")
    from services.inventory_ipv import register_audited_openings_bulk
    res = await register_audited_openings_bulk(actor)
    await log_action(
        db, actor, "inventory.audited_opening_bulk", "inventory", "bulk",
        summary=(f"Aperturas auditadas en bloque: {res['processed']} "
                 f"productos ({res['value_cup']} CUP)"),
        details={"processed": res["processed"], "value_cup": res["value_cup"]})
    return res


# ══════════════════ IPV Fase 2+: reposición y nivel objetivo ════════════════
@router.get("/admin/inventory/reorder")
async def inventory_reorder(request: Request) -> Any:
    """IPV — lista de reposición: productos en/bajo su mínimo con la cantidad
    sugerida para volver al nivel objetivo."""
    await require_permission(request, "products")
    from services.inventory import build_reorder_list
    rows = await build_reorder_list()
    return {
        "products": rows,
        "totals": {
            "num_products": len(rows),
            "out_of_stock": sum(1 for r in rows if r["out_of_stock"]),
            "suggested_units": round(sum(r["suggested"] for r in rows), 3),
            "restock_cost": round(sum(r["restock_cost"] for r in rows), 2),
        },
    }


@router.patch("/admin/inventory/products/{product_id}/target-stock")
async def set_product_target_stock(product_id: str, payload: TargetStockUpdate,
                                   request: Request) -> Any:
    """IPV — fija (o limpia con null) el nivel objetivo de reposición."""
    await require_permission(request, "products")
    existing = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not existing or existing.get("owner_id"):
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    from services.inventory import sells_fraction
    val = payload.target_stock
    if val is not None:
        val = qnum(val) if sells_fraction(existing) else float(round(qnum(val)))
    await db.products.update_one(
        {"id": product_id}, {"$set": {"target_stock": val}})
    return {"ok": True, "product_id": product_id,
            "target_stock": val}


# ══════════════════ IPV Fase 3: incidencias del inventario ══════════════════
@router.get("/admin/inventory/incidents")
async def inventory_incidents(request: Request, status: Optional[str] = None,
                              type: Optional[str] = None) -> Any:
    """IPV Fase 3 — listado de incidencias (conteo pendiente, diferencia, venta
    bajo costo) con filtros por estado/tipo + resumen."""
    await require_permission(request, "products")
    from services.inventory_incidents import list_incidents, incident_summary
    rows = await list_incidents(status=status, itype=type)
    summary = await incident_summary()
    return {"incidents": rows, "summary": summary}


@router.post("/admin/inventory/incidents/{incident_id}/status")
async def inventory_incident_status(incident_id: str,
                                    payload: IncidentStatusUpdate,
                                    request: Request) -> Any:
    """IPV Fase 3 — cambia el estado de una incidencia (ciclo pendiente →
    en_revision → resuelta) dejando traza de autor y nota."""
    actor = await require_permission(request, "products")
    from services.inventory_incidents import transition_incident
    return await transition_incident(incident_id, payload.status,
                                     payload.note, actor)


@router.post("/admin/inventory/incidents/sync")
async def inventory_incidents_sync(request: Request,
                                   date: Optional[str] = None) -> Any:
    """IPV Fase 3 — sincroniza las incidencias de 'conteo pendiente' del día."""
    await require_permission(request, "products")
    from services.inventory_incidents import sync_pending_count_incidents
    day = _valid_day(date or today_havana(), "date")
    return await sync_pending_count_incidents(day)




# ══════════════════ IPV Fase 2: Valoración (WAC + lotes) + Acta PDF ══════════
@router.get("/admin/inventory/valuation")
async def inventory_valuation(request: Request, window: int = 30) -> Any:
    """IPV Fase 2 — valoración del inventario: por producto existencia, costo
    promedio ponderado (WAC), valor por WAC/lotes (FIFO), margen esperado y
    rotación del período para detectar capital inmovilizado."""
    await require_permission(request, "products")
    from services.inventory_lots import build_valuation
    return await build_valuation(window_days=window)


@router.get("/admin/inventory/valuation.csv")
async def inventory_valuation_csv(request: Request, window: int = 30) -> Any:
    """IPV Fase 2 — CSV contable de la valoración (producto + lotes)."""
    import csv
    import io
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from services.inventory_lots import build_valuation

    await require_permission(request, "products")
    data = await build_valuation(window_days=window)
    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    writer.writerow(["Producto", "Categoría", "Existencia", "WAC (costo prom.)",
                     "Precio venta", "Margen %", "Valor WAC", "Valor por lotes",
                     "Margen esperado", "Stock sin lote", "Vendidas (período)",
                     "Días p/agotar", "Estado capital", "Lote fecha",
                     "Lote costo unit.", "Lote cantidad", "Lote restante",
                     "Lote valor restante", "Lote margen %",
                     "Lote margen restante", "Días"])
    cap_es = {"activo": "Activo", "lento": "Lento", "sin_ventas": "Sin ventas",
              "vacio": "Sin stock"}
    for p in data["products"]:
        base = [p["name"], p["category"], p["stock"], p["wac"], p["price_usd"],
                p["margin_pct_wac"] if p["margin_pct_wac"] is not None else "",
                p["inventory_value_wac"], p["inventory_value_lots"],
                p["expected_margin"], p["stock_sin_lote"], p["sold_window"],
                p["sellout_days"] if p["sellout_days"] is not None else "",
                cap_es.get(p["capital_status"], p["capital_status"])]
        if p["lots"]:
            for lot in p["lots"]:
                writer.writerow(base + [
                    (lot.get("received_at") or "")[:10], lot["unit_cost"],
                    lot["qty"], lot["remaining"], lot["remaining_value"],
                    lot["margin_pct"] if lot["margin_pct"] is not None else "",
                    lot["remaining_margin"],
                    lot["age_days"] if lot["age_days"] is not None else ""])
        else:
            writer.writerow(base + ["", "", "", "", "", "", "", ""])
    buf = BytesIO()
    buf.write(text_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    ts = iso(now_utc())[:16].replace("-", "").replace(":", "").replace("T", "_")
    return StreamingResponse(
        buf, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="inventario_valoracion_{ts}.csv"'})


@router.post("/admin/inventory/products/{product_id}/apply-liquidation")
async def apply_liquidation(product_id: str, request: Request,
                            window: int = 30) -> Any:
    """IPV — aplica el precio de liquidación sugerido (libera caja). El precio
    se recalcula en el servidor (no se confía en el cliente) y queda auditado."""
    actor = await require_permission(request, "products")
    from services.inventory_lots import build_valuation
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    # IPV-FINAL-01 — un producto ya en oferta no se vuelve a liquidar (evita
    # acumular descuentos sobre el precio ya rebajado). Hay que quitar la
    # oferta antes de aplicar otra.
    if product.get("on_offer"):
        raise HTTPException(
            status_code=409,
            detail="El producto ya está en oferta; quítala antes de aplicar otra liquidación.")
    base_price = float(product.get("price_usd") or 0)
    base_cost = float(product.get("cost_usd") or 0)
    # H08 (iter343) — conservar la cantidad EXACTA tal como está almacenada
    # (puede ser fraccionaria, p. ej. 10.5 lb). Truncar a entero rompía la
    # escritura condicionada: buscaba stock=10 cuando seguía siendo 10.5 y
    # devolvía 409 aunque nada hubiera cambiado. `base_stock` solo se usa como
    # guarda de concurrencia, por lo que debe igualar el valor normalizado.
    base_stock = product.get("stock") or 0
    data = await build_valuation(window_days=window)
    row = next((p for p in data["products"]
                if p["product_id"] == product_id), None)
    liq = (row or {}).get("liquidation")
    if not liq or liq.get("loss") or float(liq.get("discount_pct") or 0) <= 0:
        raise HTTPException(
            status_code=400,
            detail="Este producto no tiene un descuento de liquidación sugerido.")
    new_price = float(liq["suggested_price"])
    if abs(new_price - base_price) < 1e-9:
        raise HTTPException(status_code=400,
                            detail="El precio ya está en el valor sugerido.")
    # IPV-FINAL-01 — escritura ATÓMICA condicionada al estado base: solo aplica
    # si el producto NO está en oferta y precio/costo/stock siguen siendo los
    # usados para calcular la sugerencia. Así, reintentos y solicitudes
    # simultáneas aplican el descuento una sola vez, y un cambio concurrente de
    # la ficha no se sobrescribe con una sugerencia desactualizada.
    result = await db.products.update_one(
        {"id": product_id, "on_offer": {"$ne": True},
         "price_usd": base_price, "cost_usd": base_cost, "stock": base_stock},
        {"$set": {"price_usd": new_price,
                  "on_offer": True,
                  "offer_original_price": base_price,
                  "offer_discount_pct": liq["discount_pct"],
                  "offer_at": iso(now_utc())}})
    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="El estado del producto cambió; recarga la valoración e inténtalo de nuevo.")
    # Auditoría solo cuando la escritura aplicó realmente el cambio.
    await record_price_change(product=product,
                              field_label="Precio de liquidación",
                              old=base_price, new=new_price, actor=actor)
    try:
        from services.live_bus import publish
        await publish("products_changed", {"product_id": product_id})
    except Exception as e:  # noqa: BLE001
        logger.error(f"products_changed publish failed: {e}")
    return {"applied": True, "old_price": base_price, "new_price": new_price,
            "discount_pct": liq["discount_pct"]}


@router.post("/admin/inventory/products/{product_id}/clear-offer")
async def clear_offer(product_id: str, request: Request) -> Any:
    """IPV — retira la etiqueta de oferta de la tienda web (mantiene el precio
    rebajado; el admin ya decidió venderlo a ese precio)."""
    await require_permission(request, "products")
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if not product.get("on_offer"):
        raise HTTPException(status_code=400,
                            detail="El producto no está en oferta.")
    await db.products.update_one(
        {"id": product_id},
        {"$set": {"on_offer": False},
         "$unset": {"offer_original_price": "", "offer_discount_pct": "",
                    "offer_at": ""}})
    try:
        from services.live_bus import publish
        await publish("products_changed", {"product_id": product_id})
    except Exception as e:  # noqa: BLE001
        logger.error(f"products_changed publish failed: {e}")
    return {"ok": True}


@router.get("/admin/inventory/count-sheet.pdf")
async def count_sheet_pdf(request: Request, date: Optional[str] = None) -> Any:
    """IPV Fase 2 — acta de conteo físico firmable del día (PDF)."""
    from datetime import datetime
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from store_count_sheet_pdf import build_count_sheet_pdf

    await require_permission(request, "products")
    day = (date or today_havana())[:10]
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="Fecha inválida (formato YYYY-MM-DD)")
    pdf = build_count_sheet_pdf(await build_count_sheet(day))
    return StreamingResponse(
        BytesIO(pdf), media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="acta_conteo_{day}.pdf"'})


class BarcodeAssign(BaseModel):
    product_id: str
    barcode: str = Field(..., min_length=3, max_length=64)


class BarcodeGenerate(BaseModel):
    product_ids: list = Field(..., min_length=1, max_length=500)


def _ean13_check_digit(d12: str) -> str:
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d12))
    return str((10 - s % 10) % 10)


async def _generate_internal_ean13() -> str:
    """iter228 — EAN-13 interno (prefijo 20x, reservado para uso en tienda)."""
    import secrets
    for _ in range(25):
        body = "200" + "".join(secrets.choice("0123456789") for _ in range(9))
        code = body + _ean13_check_digit(body)
        if not await db.products.find_one({"barcode": code}, {"_id": 1}):
            return code
    raise HTTPException(status_code=500,
                        detail="No se pudo generar un código único")


_COMPANY_Q = {"$or": [{"owner_id": {"$in": [None, ""]}},
                      {"owner_id": {"$exists": False}}]}


@router.get("/admin/inventory/barcode/{code}")
async def lookup_barcode(code: str, request: Request) -> Any:
    """iter227 — escáner: busca el producto vinculado a un código de barras."""
    await require_permission(request, "products")
    code = code.strip()
    p = await db.products.find_one({"barcode": code, **_COMPANY_Q}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404,
                            detail="Código no vinculado a ningún producto")
    return {"product_id": p["id"], "name": p.get("name", ""),
            "stock": qnum(p.get("stock")),
            "unit": p.get("unit") or "unidad",
            "price_usd": float(p.get("price_usd") or 0),
            "cost_usd": float(p.get("cost_usd") or 0),
            "image_url": p.get("image_url", ""),
            "is_active": bool(p.get("is_active", True)),
            "barcode": code}


@router.post("/admin/inventory/barcode/assign")
async def assign_barcode(payload: BarcodeAssign, request: Request) -> Any:
    """iter227 — vincula un código de barras a un producto de la empresa."""
    actor = await require_permission(request, "products")
    code = payload.barcode.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Código de barras vacío")
    product = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if product.get("owner_id"):
        raise HTTPException(
            status_code=400,
            detail="Los productos de vendedores VIP no entran al inventario de la empresa")
    other = await db.products.find_one(
        {"barcode": code, "id": {"$ne": product["id"]}, **_COMPANY_Q}, {"_id": 0})
    if other:
        raise HTTPException(status_code=409, detail=(
            f"Este código ya está vinculado a «{other.get('name', '')}»"))
    await db.products.update_one({"id": product["id"]},
                                 {"$set": {"barcode": code}})
    await log_action(
        db, actor, "inventory.barcode_assign", "product", product["id"],
        summary=f"Código {code} → {product.get('name', '')}",
        details={"barcode": code})
    return {"ok": True, "product_id": product["id"], "barcode": code,
            "name": product.get("name", "")}


@router.post("/admin/inventory/barcode/generate")
async def generate_barcodes(payload: BarcodeGenerate, request: Request) -> Any:
    """iter228 — genera códigos internos para productos sin código de barras."""
    actor = await require_permission(request, "products")
    out = []
    for pid in payload.product_ids:
        product = await db.products.find_one({"id": str(pid)}, {"_id": 0})
        if not product or product.get("owner_id"):
            continue
        if product.get("barcode"):
            out.append({"product_id": product["id"],
                        "barcode": product["barcode"], "generated": False})
            continue
        code = await _generate_internal_ean13()
        await db.products.update_one({"id": product["id"]},
                                     {"$set": {"barcode": code}})
        await log_action(
            db, actor, "inventory.barcode_generate", "product", product["id"],
            summary=f"Código interno {code} → {product.get('name', '')}",
            details={"barcode": code})
        out.append({"product_id": product["id"], "barcode": code,
                    "generated": True})
    return out


@router.get("/admin/inventory/labels.pdf")
async def labels_pdf(request: Request, product_ids: str,
                     copies: int = 1) -> Any:
    """iter228 — PDF A4 (rejilla 3×8) de etiquetas con código de barras."""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from services.label_pdf import build_labels_pdf

    await require_permission(request, "products")
    ids = [x.strip() for x in product_ids.split(",") if x.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="Sin productos seleccionados")
    copies = max(1, min(int(copies), 50))
    prods = await db.products.find(
        {"id": {"$in": ids}, **_COMPANY_Q}, {"_id": 0}).to_list(500)
    items = sorted([p for p in prods if p.get("barcode")],
                   key=lambda p: (p.get("name") or "").lower())
    if not items:
        raise HTTPException(
            status_code=400,
            detail="Ninguno de los productos seleccionados tiene código de barras")
    pdf = build_labels_pdf(items, copies)
    ts = iso(now_utc())[:10]
    return StreamingResponse(
        BytesIO(pdf), media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="etiquetas_{ts}.pdf"'})


@router.get("/admin/inventory/daily-close")
async def daily_close(request: Request, date: Optional[str] = None) -> Any:
    """iter230 — resumen de caja del día para cuadrar al cerrar la tienda."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from services.inventory import build_daily_close

    await require_permission(request, "products")
    if not date:
        date = datetime.now(ZoneInfo("America/Havana")).strftime("%Y-%m-%d")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="Fecha inválida (formato YYYY-MM-DD)")
    return await build_daily_close(date)


@router.get("/admin/inventory/daily-close.pdf")
async def daily_close_pdf(request: Request, date: Optional[str] = None) -> Any:
    """iter231 — cierre del día en PDF para archivar o compartir con socios."""
    from datetime import datetime
    from io import BytesIO
    from zoneinfo import ZoneInfo
    from fastapi.responses import StreamingResponse
    from services.inventory import build_daily_close
    from store_close_pdf import build_store_close_pdf

    await require_permission(request, "products")
    if not date:
        date = datetime.now(ZoneInfo("America/Havana")).strftime("%Y-%m-%d")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="Fecha inválida (formato YYYY-MM-DD)")
    pdf = build_store_close_pdf(await build_daily_close(date))
    return StreamingResponse(
        BytesIO(pdf), media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="cierre_tienda_{date}.pdf"'})


@router.get("/admin/inventory/dashboard")
async def inventory_dashboard(request: Request, start: Optional[str] = None,
                              end: Optional[str] = None,
                              product_id: Optional[str] = None,
                              product_ids: Optional[str] = None) -> Any:
    """iter224 — `product_ids` (separados por coma) permite analizar varias
    mercancías a la vez; `product_id` se mantiene por compatibilidad."""
    await require_permission(request, "products")
    today = today_havana()
    start = (start or today)[:10]
    end = (end or today)[:10]
    if start > end:
        raise HTTPException(status_code=400, detail="Rango de fechas inválido")
    ids = [x.strip() for x in (product_ids or "").split(",") if x.strip()]
    if not ids and product_id:
        ids = [product_id]
    return await build_dashboard(start, end, product_ids=ids or None)


@router.get("/admin/inventory/rotation")
async def inventory_rotation(request: Request, start: Optional[str] = None,
                             end: Optional[str] = None,
                             product_ids: Optional[str] = None) -> Any:
    """iter225 — rotación por mercancía: cuánto tarda cada producto en
    venderse (ritmo/día, días para agotarse) y en reponerse (ciclo entre
    entradas)."""
    await require_permission(request, "products")
    today = today_havana()
    start = (start or today)[:10]
    end = (end or today)[:10]
    if start > end:
        raise HTTPException(status_code=400, detail="Rango de fechas inválido")
    ids = [x.strip() for x in (product_ids or "").split(",") if x.strip()]
    return await build_rotation(start, end, product_ids=ids or None)


async def _movement_rows(product_id: Optional[str], type: Optional[str],
                         start: Optional[str], end: Optional[str]) -> list:
    q: dict = {}
    if product_id:
        q["product_id"] = product_id
    if type:
        q["type"] = type
    created: dict = {}
    if start:
        created["$gte"] = _day_bounds(start)[0]
    if end:
        created["$lt"] = _day_bounds(end)[1]
    if created:
        q["created_at"] = created
    return await db.inventory_movements.find(q, {"_id": 0}) \
        .sort("created_at", -1).to_list(20000)


@router.get("/admin/inventory/export.csv")
async def export_inventory_csv(request: Request, dataset: str = "movements",
                               product_id: Optional[str] = None,
                               type: Optional[str] = None,
                               start: Optional[str] = None,
                               end: Optional[str] = None) -> Any:
    """iter220 — CSV contable del control de inventario o del registro de
    movimientos (con filtros de producto/tipo/fechas)."""
    import csv
    import io
    from io import BytesIO
    from fastapi.responses import StreamingResponse

    await require_permission(request, "products")
    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    if dataset == "control":
        writer.writerow(["Producto", "Categoría", "Activo", "Existencia",
                         "Precio venta", "Costo unitario", "Entradas",
                         "Ventas", "Valor inventario", "Vendido hoy",
                         "Ingresos hoy", "Estado"])
        for r in await build_control_rows():
            writer.writerow([
                r["name"], r["category"], "sí" if r["is_active"] else "no",
                r["stock"], r["price_usd"], r["cost_usd"], r["entradas"],
                r["ventas"], r["inventory_value"], r["sold_today"],
                r["revenue_today"], r["estado"].upper()])
        prefix = "inventario_control"
    elif dataset == "movements":
        writer.writerow(["Fecha", "Tipo", "Producto", "Cantidad",
                         "Precio unitario", "Costo unitario", "Total",
                         "Costo de venta", "Ganancia", "Fuente", "Usuario",
                         "Nota", "Foto"])
        for m in await _movement_rows(product_id, type, start, end):
            writer.writerow([
                m["created_at"], _TYPE_LABELS.get(m["type"], m["type"]),
                m["product_name"], m["quantity"], m["unit_price"],
                m["unit_cost"], m["total"], m["cost_of_sale"], m["profit"],
                m.get("source", ""), m.get("actor_email", ""),
                m.get("note", ""), m.get("photo_url", "")])
        prefix = "inventario_movimientos"
    else:
        raise HTTPException(status_code=400, detail="dataset inválido (control|movements)")

    buf = BytesIO()
    buf.write(text_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    ts = iso(now_utc())[:16].replace("-", "").replace(":", "").replace("T", "_")
    return StreamingResponse(
        buf, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{prefix}_{ts}.csv"'})


@router.get("/admin/inventory/export.xlsx")
async def export_inventory_xlsx(request: Request,
                                start: Optional[str] = None,
                                end: Optional[str] = None) -> Any:
    """iter220 — Excel contable completo: Control Inventario + Movimientos
    del período + Dashboard (por defecto: mes en curso)."""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook
    from openpyxl.styles import Font

    await require_permission(request, "products")
    today = today_havana()
    start = (start or f"{today[:7]}-01")[:10]
    end = (end or today)[:10]
    if start > end:
        raise HTTPException(status_code=400, detail="Rango de fechas inválido")

    wb = Workbook()
    bold = Font(bold=True)

    ws = wb.active
    ws.title = "Control Inventario"
    ws.append(["Producto", "Categoría", "Activo", "Existencia", "Precio venta",
               "Costo unitario", "Entradas", "Ventas", "Valor inventario",
               "Vendido hoy", "Ingresos hoy", "Estado"])
    for cell in ws[1]:
        cell.font = bold
    for r in await build_control_rows():
        ws.append([r["name"], r["category"], "sí" if r["is_active"] else "no",
                   r["stock"], r["price_usd"], r["cost_usd"], r["entradas"],
                   r["ventas"], r["inventory_value"], r["sold_today"],
                   r["revenue_today"], r["estado"].upper()])
    ws.column_dimensions["A"].width = 32

    ws2 = wb.create_sheet("Movimientos")
    ws2.append(["Fecha", "Tipo", "Producto", "Cantidad", "Precio unitario",
                "Costo unitario", "Total", "Costo de venta", "Ganancia",
                "Fuente", "Usuario", "Nota"])
    for cell in ws2[1]:
        cell.font = bold
    for m in await _movement_rows(None, None, start, end):
        ws2.append([m["created_at"], _TYPE_LABELS.get(m["type"], m["type"]),
                    m["product_name"], m["quantity"], m["unit_price"],
                    m["unit_cost"], m["total"], m["cost_of_sale"], m["profit"],
                    m.get("source", ""), m.get("actor_email", ""),
                    m.get("note", "")])
    ws2.column_dimensions["A"].width = 28
    ws2.column_dimensions["C"].width = 32

    ws3 = wb.create_sheet("Dashboard")
    d = await build_dashboard(start, end)
    kpis = [
        ("Período", f"{start} → {end}"),
        ("Unidades vendidas", d["units_sold"]),
        ("Ingresos por ventas", d["sales_revenue"]),
        ("Costo mercancía vendida", d["cogs"]),
        ("Ganancia realizada", d["profit"]),
        ("Margen realizado %", d["margin_pct"]),
        ("Rentabilidad s/ costo %", d["profitability_pct"]),
        ("Salidas por compras", d["purchases_out"]),
        ("Flujo neto de caja", d["net_cash_flow"]),
        ("Valor inventario actual", d["inventory_value"]),
        ("Unidades en existencia", d["units_in_stock"]),
        ("Comisión ventas VIP", d["vip_commission_earned"] or 0),
    ]
    for label, value in kpis:
        ws3.append([label, value])
    for row in ws3.iter_rows(min_col=1, max_col=1):
        row[0].font = bold
    ws3.column_dimensions["A"].width = 30

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="inventario_{start}_a_{end}.xlsx"'})
