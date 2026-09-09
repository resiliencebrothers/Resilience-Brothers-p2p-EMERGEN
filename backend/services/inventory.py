"""Inventario de la tienda física — iter217.

Réplica del Excel `Inventario_flujo_caja_CORREGIDO`:
- Movimientos (Entrada / Venta / Ajuste + / Ajuste −) → `inventory_movements`.
- Control en tiempo real por producto (existencia, valor, ventas hoy, estado).
- Dashboard del período (unidades vendidas, ingresos, COGS, ganancia, flujo).

Solo aplica a productos de la EMPRESA (owner_id vacío). Los productos de
vendedores VIP no entran al inventario físico de la compañía.
"""
import uuid
import logging
from typing import Optional

from fastapi import HTTPException

from db_client import db
from auth_utils import now_utc, iso

logger = logging.getLogger(__name__)

MOVEMENT_TYPES = ("entrada", "venta", "ajuste_pos", "ajuste_neg")
LOW_STOCK_THRESHOLD = 5

_COMPANY_FILTER = {"$or": [{"owner_id": {"$in": [None, ""]}},
                           {"owner_id": {"$exists": False}}]}


def _day_bounds(day: str) -> tuple:
    """iter254(R10) — el 'día' del negocio es el de Cuba (America/Havana),
    convertido a UTC. Devuelve [inicio, fin) — fin EXCLUSIVO."""
    from zoneinfo import ZoneInfo
    from datetime import datetime, timedelta, timezone
    tz = ZoneInfo("America/Havana")
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=tz)
    start = d.astimezone(timezone.utc).isoformat()
    end = (d + timedelta(days=1)).astimezone(timezone.utc).isoformat()
    return start, end


def today_havana() -> str:
    """iter256(S11) — el 'hoy' del negocio es la fecha de Cuba, no la UTC
    (a las 22:30 de Cuba la fecha UTC ya es la del día siguiente)."""
    from zoneinfo import ZoneInfo
    from datetime import datetime
    return datetime.now(ZoneInfo("America/Havana")).strftime("%Y-%m-%d")


async def _rejected_marketplace_refs() -> set:
    """iter256(S11) — ids de canjes RECHAZADOS: sus movimientos de venta (y
    sus reversos) no deben contar en control/rotación/dashboard."""
    rows = await db.redemptions.find({"status": "rejected"},
                                     {"_id": 0, "id": 1}).to_list(100000)
    return {d["id"] for d in rows}


def movement_delta(mtype: str, quantity: int) -> int:
    """Delta de stock que implica un movimiento (compartido con el healer)."""
    if mtype in ("venta", "ajuste_neg"):
        return -quantity
    return quantity


async def apply_stock_idempotent(product_id: str, delta_qty: int, op_id: str,
                                 require_available: bool = True,
                                 extra_filter: Optional[dict] = None) -> str:
    """iter254(R03) — cambio de stock atómico, condicional e IDEMPOTENTE por
    op_id (registro embebido en el producto + log duradero iter256/S07).
    Devuelve 'applied' | 'duplicate' | 'insufficient'."""
    state = await _stock_ops_ensure(op_id, product_id, delta_qty)
    if state == "applied":
        return "duplicate"
    filt: dict = {"id": product_id, "applied_stock_ops": {"$ne": op_id}}
    if extra_filter:
        filt.update(extra_filter)
    if delta_qty < 0 and require_available:
        filt["stock"] = {"$gte": -delta_qty}
    res = await db.products.update_one(
        filt,
        {"$inc": {"stock": delta_qty},
         "$push": {"applied_stock_ops": {"$each": [op_id], "$slice": -500}}},
    )
    if res.matched_count:
        await _stock_ops_mark_applied(op_id)
        return "applied"
    if await db.products.find_one({"id": product_id, "applied_stock_ops": op_id},
                                  {"_id": 1}):
        await _stock_ops_mark_applied(op_id)
        return "duplicate"
    # insuficiente: liberar el intento pendiente del log duradero.
    await db.stock_ops.delete_one({"op_id": op_id, "state": "pending"})
    return "insufficient"


_STOCK_OPS_READY = False


async def _stock_ops_ensure(op_id: str, product_id: str, delta_qty: int) -> str:
    """iter256(S07) — log duradero insert-first de operaciones de stock (índice
    único por op_id): aunque el op salga del registro embebido del producto
    (cap 500), este log bloquea cualquier replay. Si Mongo falla aquí, el
    stock NO se toca. Devuelve 'new' | 'pending' | 'applied'."""
    global _STOCK_OPS_READY
    if not _STOCK_OPS_READY:
        await db.stock_ops.create_index("op_id", unique=True)
        _STOCK_OPS_READY = True
    existing = await db.stock_ops.find_one({"op_id": op_id},
                                           {"_id": 0, "state": 1})
    if existing is None:
        try:
            await db.stock_ops.insert_one({
                "op_id": op_id, "product_id": product_id,
                "delta": int(delta_qty), "state": "pending",
                "at": iso(now_utc())})
            return "new"
        except Exception:
            existing = await db.stock_ops.find_one({"op_id": op_id},
                                                   {"_id": 0, "state": 1})
            if existing is None:
                raise
    return "applied" if existing.get("state", "applied") == "applied" \
        else "pending"


async def _stock_ops_mark_applied(op_id: str) -> None:
    await db.stock_ops.update_one({"op_id": op_id},
                                  {"$set": {"state": "applied"}})


async def stock_op_was_applied(product_id: str, op_id: str) -> bool:
    """¿Este op de stock llegó a aplicarse? (embebido O log duradero)."""
    if await db.products.find_one({"id": product_id, "applied_stock_ops": op_id},
                                  {"_id": 1}):
        return True
    doc = await db.stock_ops.find_one({"op_id": op_id}, {"_id": 0, "state": 1})
    return bool(doc) and doc.get("state", "applied") == "applied"


async def get_low_stock_threshold() -> int:
    """Umbral 'stock bajo' configurable en settings.global (default 5)."""
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
    raw = doc.get("low_stock_threshold")
    try:
        return max(0, int(raw)) if raw is not None else LOW_STOCK_THRESHOLD
    except (TypeError, ValueError):
        return LOW_STOCK_THRESHOLD


async def maybe_alert_low_stock(product_id: str) -> None:
    """iter218 — avisa a los admins (push + email + campana in-app) cuando un
    producto de la empresa cae al umbral de stock bajo o se agota.

    Dedup por nivel via flag `low_stock_alert_level` en el producto: 'bajo'
    avisa una vez, 'agotado' avisa de nuevo. Reponer por encima del umbral
    limpia el flag para que la próxima caída vuelva a avisar."""
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product or product.get("owner_id"):
        return
    threshold = await get_low_stock_threshold()
    stock = int(product.get("stock") or 0)
    if stock > threshold:
        if product.get("low_stock_alert_level"):
            await db.products.update_one(
                {"id": product_id}, {"$unset": {"low_stock_alert_level": ""}})
        return
    level = "agotado" if stock <= 0 else "bajo"
    if product.get("low_stock_alert_level") == level:
        return
    await db.products.update_one(
        {"id": product_id}, {"$set": {"low_stock_alert_level": level}})
    name = product.get("name", "")
    if level == "agotado":
        title = "Producto AGOTADO en inventario"
        body = f"«{name}» se quedó sin existencias. Repón el stock para seguir vendiendo."
    else:
        title = "Stock bajo en inventario"
        body = (f"«{name}» quedó con {stock} unidades (mínimo configurado: "
                f"{threshold}). Considera reponer a tiempo.")
    try:
        from admin_alerts import notify_all_admins
        await notify_all_admins(db, title=title, body=body,
                                url_path="/admin/inventory")
    except Exception as e:  # noqa: BLE001
        logger.error(f"low stock admin alert failed: {e}")
    try:
        from routes.notifications import _insert_notification
        admins = await db.users.find({"role": "admin"},
                                     {"_id": 0, "user_id": 1}).to_list(50)
        for a in admins:
            await _insert_notification(
                recipient_user_id=a["user_id"], type="low_stock",
                title=title, message=body,
                data={"product_id": product_id, "stock": stock,
                      "threshold": threshold, "level": level})
    except Exception as e:  # noqa: BLE001
        logger.error(f"low stock in-app notify failed: {e}")


async def record_movement(*, product: dict, mtype: str, quantity: int,
                          unit_price: Optional[float] = None,
                          unit_cost: Optional[float] = None,
                          note: str = "", source: str = "manual",
                          ref_id: str = "", actor: Optional[dict] = None,
                          apply_stock: bool = True,
                          photo_url: str = "") -> dict:
    """Inserta un movimiento y (opcionalmente) aplica el delta al stock.

    `apply_stock=False` para flujos donde el stock ya fue tocado (canjes)."""
    if mtype not in MOVEMENT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de movimiento inválido")
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="La cantidad debe ser mayor que 0")
    price = float(unit_price if unit_price is not None else product.get("price_usd") or 0)
    cost = float(unit_cost if unit_cost is not None else product.get("cost_usd") or 0)
    total = 0.0
    cost_of_sale = 0.0
    profit = 0.0
    if mtype == "venta":
        total = round(price * quantity, 2)
        cost_of_sale = round(cost * quantity, 2)
        profit = round(total - cost_of_sale, 2)
        delta = -quantity
    elif mtype == "entrada":
        total = round(cost * quantity, 2)
        delta = quantity
    elif mtype == "ajuste_pos":
        delta = quantity
    else:  # ajuste_neg
        delta = -quantity
    doc = {
        "id": str(uuid.uuid4()),
        "product_id": product["id"],
        "product_name": product.get("name", ""),
        "type": mtype,
        "quantity": int(quantity),
        "unit_price": price,
        "unit_cost": cost,
        "total": total,
        "cost_of_sale": cost_of_sale,
        "profit": profit,
        "note": note,
        "photo_url": photo_url,
        "source": source,
        "ref_id": ref_id,
        "actor_id": (actor or {}).get("user_id", ""),
        "actor_email": (actor or {}).get("email", ""),
        "created_at": iso(now_utc()),
    }
    # iter254(R03) — registro-primero + aplicación de stock idempotente: si el
    # proceso muere entre el log y el stock, heal_initializing_ops completa la
    # aplicación (op_id determinista); nunca queda un cambio de stock sin su
    # movimiento ni un movimiento fantasma.
    if apply_stock and delta != 0:
        doc["needs_stock"] = True
        doc["stock_applied"] = False
        await db.inventory_movements.insert_one({**doc})
        status = await apply_stock_idempotent(
            product["id"], delta, f"invmov:{doc['id']}",
            require_available=(delta < 0))
        if status == "insufficient":
            await db.inventory_movements.delete_one({"id": doc["id"]})
            raise HTTPException(status_code=400,
                                detail="Stock insuficiente para este movimiento")
        await db.inventory_movements.update_one(
            {"id": doc["id"]}, {"$set": {"stock_applied": True}})
        doc["stock_applied"] = True
    else:
        await db.inventory_movements.insert_one({**doc})
    await _record_fund_flow(doc)
    await maybe_alert_low_stock(product["id"])
    return doc


async def build_daily_close(date_str: str) -> dict:
    """iter230 — resumen de caja del día de la tienda física (hora de Cuba).

    Ventas físicas (manual/escáner) y compras de mercancía en la moneda de
    la tienda (CUP efectivo); ventas web aparte (USDT), excluyendo canjes
    rechazados. Ganancia = suma del profit de cada venta."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Havana")
    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    start = day.astimezone(timezone.utc).isoformat()
    end = (day + timedelta(days=1)).astimezone(timezone.utc).isoformat()
    movs = await db.inventory_movements.find(
        {"created_at": {"$gte": start, "$lt": end}}, {"_id": 0}).to_list(20000)

    fis_v = [m for m in movs if m["type"] == "venta" and m.get("source") == "manual"
             and not m.get("stock_apply_failed")]
    web_v = [m for m in movs if m["type"] == "venta" and m.get("source") == "marketplace"
             and not m.get("stock_apply_failed")]
    compras = [m for m in movs if m["type"] == "entrada"
               and m.get("source") in ("manual", "alta")]

    red_ids = [m.get("ref_id") for m in web_v if m.get("ref_id")]
    reds = await db.redemptions.find(
        {"id": {"$in": red_ids}},
        {"_id": 0, "id": 1, "status": 1, "total_usd": 1}).to_list(5000)
    rmap = {r["id"]: r for r in reds}
    web_ok = [m for m in web_v
              if rmap.get(m.get("ref_id"), {}).get("status") != "rejected"]
    web_usdt = round(sum(float(rmap.get(m.get("ref_id"), {}).get("total_usd") or 0)
                         for m in web_ok), 2)

    def _tot(rows: list, field: str = "total") -> float:
        return round(sum(float(r.get(field) or 0) for r in rows), 2)

    def _units(rows: list) -> int:
        return sum(int(r.get("quantity") or 0) for r in rows)

    productos: dict = {}
    for m in fis_v:
        e = productos.setdefault(m["product_id"], {
            "product_id": m["product_id"], "name": m.get("product_name", ""),
            "unidades": 0, "unidades_web": 0, "total": 0.0, "ganancia": 0.0})
        e["unidades"] += int(m.get("quantity") or 0)
        e["total"] = round(e["total"] + float(m.get("total") or 0), 2)
        e["ganancia"] = round(e["ganancia"] + float(m.get("profit") or 0), 2)
    for m in web_ok:
        e = productos.setdefault(m["product_id"], {
            "product_id": m["product_id"], "name": m.get("product_name", ""),
            "unidades": 0, "unidades_web": 0, "total": 0.0, "ganancia": 0.0})
        e["unidades_web"] += int(m.get("quantity") or 0)
        e["total"] = round(e["total"] + float(m.get("total") or 0), 2)
        e["ganancia"] = round(e["ganancia"] + float(m.get("profit") or 0), 2)

    compras_det: dict = {}
    for m in compras:
        e = compras_det.setdefault(m["product_id"], {
            "product_id": m["product_id"], "name": m.get("product_name", ""),
            "unidades": 0, "total": 0.0})
        e["unidades"] += int(m.get("quantity") or 0)
        e["total"] = round(e["total"] + float(m.get("total") or 0), 2)

    # iter240 — entregas en tienda del día (recogidas web confirmadas), para
    # que el conteo físico del día cuadre: la mercancía sale del estante el
    # día de la ENTREGA, no del canje.
    pickups = await db.redemptions.find(
        {"fulfillment": "store_pickup", "status": "delivered",
         "delivered_at": {"$gte": start, "$lt": end}},
        {"_id": 0, "id": 1, "user_name": 1, "product_name": 1, "quantity": 1,
         "store_name": 1, "total_usd": 1, "delivered_at": 1}).to_list(5000)
    pickups.sort(key=lambda p: p.get("delivered_at") or "")
    recogidas = {
        "num": len(pickups),
        "unidades": sum(int(p.get("quantity") or 0) for p in pickups),
        "total_usdt": round(sum(float(p.get("total_usd") or 0)
                                for p in pickups), 2),
        "detalle": pickups,
    }

    from services.marketplace_fx import get_store_fx
    fx = await get_store_fx()
    ventas_fis = _tot(fis_v)
    compras_tot = _tot(compras)
    return {
        "date": date_str,
        "store_currency": fx["store_currency"],
        "fisica": {
            "ventas": ventas_fis,
            "unidades_vendidas": _units(fis_v),
            "num_ventas": len(fis_v),
            "compras": compras_tot,
            "unidades_compradas": _units(compras),
            "num_compras": len(compras),
            "ganancia": _tot(fis_v, "profit"),
            "caja_neta": round(ventas_fis - compras_tot, 2),
        },
        "web": {
            "ventas_store": _tot(web_ok),
            "ventas_usdt": web_usdt,
            "unidades": _units(web_ok),
            "num_ventas": len(web_ok),
            "ganancia": _tot(web_ok, "profit"),
        },
        "productos": sorted(productos.values(),
                            key=lambda x: -x["total"]),
        "compras_detalle": sorted(compras_det.values(),
                                  key=lambda x: -x["total"]),
        "recogidas": recogidas,
    }


async def _record_fund_flow(mov: dict) -> None:
    """iter229 — contabilidad automática del fondo de la empresa:
    - Entrada (compra de mercancía, manual/alta) → SALE del fondo en la
      moneda de la tienda física (CUP efectivo) por el costo total.
    - Venta en tienda física (manual/escáner) → ENTRA al fondo en la moneda
      de la tienda por el total cobrado.
    Las ventas web (source=marketplace) entran en USDT desde routes/orders."""
    try:
        mtype, source = mov["type"], mov.get("source", "")
        amount = float(mov.get("total") or 0)
        if amount <= 0:
            return
        if mtype == "entrada" and source in ("manual", "alta"):
            adjustment_type = "outflow"
            note = f"Compra mercancía: {mov['quantity']}× {mov.get('product_name', '')}"
        elif mtype == "venta" and source == "manual":
            adjustment_type = "inflow"
            note = f"Venta tienda física: {mov['quantity']}× {mov.get('product_name', '')}"
        else:
            return
        # iter256(S10) — claim idempotente: reejecutable desde el healer sin
        # duplicar el asiento contable.
        claim = await db.inventory_movements.update_one(
            {"id": mov["id"], "fund_flow_recorded": {"$ne": True}},
            {"$set": {"fund_flow_recorded": True}})
        if claim.modified_count == 0:
            return
        from services.marketplace_fx import get_store_fx
        from services.company_funds_common import record_auto_fund_adjustment
        fx = await get_store_fx()
        await record_auto_fund_adjustment(
            adjustment_type=adjustment_type, currency=fx["store_currency"],
            amount=round(amount, 2), source_name="Inventario tienda física",
            note=note, ref_id=mov["id"])
    except Exception as e:  # noqa: BLE001
        logger.error(f"inventory fund flow failed: {e}")


async def record_price_change(*, product: dict, field_label: str,
                              old: float, new: float,
                              actor: Optional[dict] = None,
                              source: str = "manual") -> None:
    """iter219 — auditoría de cambios de precio/costo en el registro de
    movimientos (tipo 'precio', cantidad 0, no afecta stock ni KPIs)."""
    doc = {
        "id": str(uuid.uuid4()),
        "product_id": product["id"],
        "product_name": product.get("name", ""),
        "type": "precio",
        "quantity": 0,
        "unit_price": float(new),
        "unit_cost": 0.0,
        "total": 0.0,
        "cost_of_sale": 0.0,
        "profit": 0.0,
        "note": f"{field_label}: {float(old):g} → {float(new):g}",
        "photo_url": "",
        "source": source,
        "ref_id": "",
        "actor_id": (actor or {}).get("user_id", ""),
        "actor_email": (actor or {}).get("email", ""),
        "created_at": iso(now_utc()),
    }
    await db.inventory_movements.insert_one({**doc})


async def build_control_rows() -> list:
    """Tabla 'Control Inventario' en tiempo real (una fila por producto)."""
    products = await db.products.find(_COMPANY_FILTER, {"_id": 0}).to_list(1000)
    threshold = await get_low_stock_threshold()
    # iter256(S11) — mismo criterio de venta efectiva que el dashboard:
    # excluir canjes rechazados (y sus reversos) y movimientos fallidos.
    refs = await _rejected_marketplace_refs()
    ok_match = {"stock_apply_failed": {"$ne": True},
                "$or": [{"source": {"$ne": "marketplace"}},
                        {"ref_id": {"$nin": list(refs)}}]}
    agg = await db.inventory_movements.aggregate([
        {"$match": ok_match},
        {"$group": {"_id": {"p": "$product_id", "t": "$type"},
                    "qty": {"$sum": "$quantity"}}}
    ]).to_list(5000)
    by_product: dict = {}
    for a in agg:
        by_product.setdefault(a["_id"]["p"], {})[a["_id"]["t"]] = a["qty"]
    today = today_havana()
    start, end = _day_bounds(today)
    today_agg = await db.inventory_movements.aggregate([
        {"$match": {"type": "venta",
                    "created_at": {"$gte": start, "$lt": end}, **ok_match}},
        {"$group": {"_id": "$product_id", "qty": {"$sum": "$quantity"},
                    "revenue": {"$sum": "$total"}}}
    ]).to_list(2000)
    today_by = {a["_id"]: a for a in today_agg}
    rows = []
    for p in products:
        m = by_product.get(p["id"], {})
        stock = int(p.get("stock") or 0)
        cost = float(p.get("cost_usd") or 0)
        if stock <= 0:
            estado = "agotado"
        elif stock <= threshold:
            estado = "bajo"
        else:
            estado = "ok"
        td = today_by.get(p["id"], {})
        rows.append({
            "product_id": p["id"],
            "name": p.get("name", ""),
            "category": p.get("category", ""),
            "barcode": p.get("barcode", ""),
            "is_active": bool(p.get("is_active", True)),
            "price_usd": float(p.get("price_usd") or 0),
            "cost_usd": cost,
            "stock": stock,
            "entradas": int(m.get("entrada", 0)),
            "ventas": int(m.get("venta", 0)),
            "ajustes_pos": int(m.get("ajuste_pos", 0)),
            "ajustes_neg": int(m.get("ajuste_neg", 0)),
            "inventory_value": round(stock * cost, 2),
            "sold_today": int(td.get("qty", 0)),
            "revenue_today": round(float(td.get("revenue", 0)), 2),
            "estado": estado,
        })
    rows.sort(key=lambda r: r["name"].lower())
    return rows


async def build_rotation(start: str, end: str,
                         product_ids: Optional[list] = None) -> list:
    """iter225 — rotación por mercancía: ritmo de venta del período, días
    para agotar la existencia actual, rotación (veces que gira el stock) y
    ciclo de reposición (días entre entradas)."""
    from datetime import datetime
    s, _ = _day_bounds(start)
    _, e = _day_bounds(end)
    days = (datetime.strptime(end, "%Y-%m-%d") -
            datetime.strptime(start, "%Y-%m-%d")).days + 1
    prod_filter: dict = dict(_COMPANY_FILTER)
    if product_ids:
        prod_filter = {"id": {"$in": product_ids}}
    products = await db.products.find(prod_filter, {"_id": 0}).to_list(1000)
    ids = [p["id"] for p in products]
    # iter256(S11) — excluir canjes rechazados y movimientos fallidos.
    refs = await _rejected_marketplace_refs()
    sold_agg = await db.inventory_movements.aggregate([
        {"$match": {"type": "venta", "product_id": {"$in": ids},
                    "created_at": {"$gte": s, "$lt": e},
                    "stock_apply_failed": {"$ne": True},
                    "$or": [{"source": {"$ne": "marketplace"}},
                            {"ref_id": {"$nin": list(refs)}}]}},
        {"$group": {"_id": "$product_id", "qty": {"$sum": "$quantity"}}},
    ]).to_list(2000)
    sold_by = {a["_id"]: int(a["qty"]) for a in sold_agg}
    entradas = await db.inventory_movements.find(
        {"type": "entrada", "product_id": {"$in": ids}},
        {"_id": 0, "product_id": 1, "created_at": 1}).sort("created_at", 1).to_list(20000)
    entradas_by: dict = {}
    for m in entradas:
        entradas_by.setdefault(m["product_id"], []).append(m["created_at"])
    now = now_utc()
    rows = []
    for p in products:
        pid = p["id"]
        stock = int(p.get("stock") or 0)
        sold = sold_by.get(pid, 0)
        daily = round(sold / days, 2) if days > 0 else 0.0
        sellout_days = round(stock / daily, 1) if daily > 0 and stock > 0 else None
        avg_inv = stock + sold / 2.0
        rotation = round(sold / avg_inv, 2) if avg_inv > 0 else 0.0
        fechas = entradas_by.get(pid, [])
        days_since_restock = None
        restock_cycle = None
        if fechas:
            try:
                last = datetime.fromisoformat(fechas[-1])
                days_since_restock = max(0, (now - last).days)
            except ValueError:
                pass
            if len(fechas) >= 2:
                try:
                    parsed = [datetime.fromisoformat(f) for f in fechas[-10:]]
                    gaps = [(b - a).total_seconds() / 86400.0
                            for a, b in zip(parsed, parsed[1:])]
                    restock_cycle = round(sum(gaps) / len(gaps), 1)
                except ValueError:
                    pass
        # iter226 — sugerencia de reposición según el ritmo de venta:
        # 'ya' si está agotado con demanda o se agota antes del ciclo de
        # reposición (mín. 3 días); 'pronto' si se agota en ≤7 días.
        suggestion = None
        suggested_qty = 0
        if sold > 0:
            lead = restock_cycle if restock_cycle else 0.0
            if stock <= 0:
                suggestion = "ya"
            elif sellout_days is not None and sellout_days <= max(3.0, lead):
                suggestion = "ya"
            elif sellout_days is not None and sellout_days <= max(7.0, lead * 1.5):
                suggestion = "pronto"
            if suggestion:
                import math
                suggested_qty = max(1, math.ceil(daily * 14 - stock))
        rows.append({
            "product_id": pid,
            "name": p.get("name", ""),
            "stock": stock,
            "sold": sold,
            "daily_rate": daily,
            "sellout_days": sellout_days,
            "rotation": rotation,
            "days_since_restock": days_since_restock,
            "restock_cycle_days": restock_cycle,
            "restock_suggestion": suggestion,
            "suggested_qty": suggested_qty,
        })
    _prio = {"ya": 0, "pronto": 1}
    rows.sort(key=lambda r: (_prio.get(r["restock_suggestion"], 2),
                             -r["sold"], r["name"].lower()))
    return rows


async def build_dashboard(start: str, end: str,
                          product_ids: Optional[list] = None) -> dict:
    """KPIs del período (hoja 'Dashboard' del Excel). Con `product_ids`
    devuelve los números de una o varias mercancías específicas."""
    s, _ = _day_bounds(start)
    _, e = _day_bounds(end)
    match: dict = {"created_at": {"$gte": s, "$lt": e}}
    if product_ids:
        match["product_id"] = {"$in": product_ids}
    movs = await db.inventory_movements.find(match, {"_id": 0}).to_list(20000)
    # iter256(S10) — un movimiento cuyo stock NO llegó a aplicarse (fallo en
    # la recuperación) no cuenta como venta efectiva.
    ventas = [m for m in movs if m["type"] == "venta"
              and not m.get("stock_apply_failed")]
    # iter254(R09) — excluir ventas de canjes RECHAZADOS: el reverso ya
    # restituyó el stock, así que ingresos/ganancia no deben contarlas.
    red_ids = list({m.get("ref_id") for m in ventas
                    if m.get("source") == "marketplace" and m.get("ref_id")})
    rejected_ids: set = set()
    if red_ids:
        rej = await db.redemptions.find(
            {"id": {"$in": red_ids}, "status": "rejected"},
            {"_id": 0, "id": 1}).to_list(len(red_ids))
        rejected_ids = {d["id"] for d in rej}
    ventas = [m for m in ventas
              if not (m.get("source") == "marketplace"
                      and m.get("ref_id") in rejected_ids)]
    entradas = [m for m in movs if m["type"] == "entrada"]
    units_sold = sum(m["quantity"] for m in ventas)
    revenue = round(sum(float(m.get("total") or 0) for m in ventas), 2)
    cogs = round(sum(float(m.get("cost_of_sale") or 0) for m in ventas), 2)
    profit = round(revenue - cogs, 2)
    purchases = round(sum(float(m.get("total") or 0) for m in entradas), 2)
    prod_filter: dict = dict(_COMPANY_FILTER)
    if product_ids:
        prod_filter = {"id": {"$in": product_ids}}
    products = await db.products.find(prod_filter, {"_id": 0}).to_list(1000)
    inv_value = round(sum(
        float(p.get("stock") or 0) * float(p.get("cost_usd") or 0)
        for p in products), 2)
    units_in_stock = int(sum(int(p.get("stock") or 0) for p in products))
    # iter219 — ganancia por comisiones de ventas de productos VIP (global,
    # no aplica al filtro por producto de la empresa).
    vip_commission = None
    if not product_ids:
        agg = await db.redemptions.aggregate([
            {"$match": {"vendor_credited_at": {"$gte": s, "$lt": e},
                        "vendor_credit_reversed_at": {"$in": [None, ""]}}},
            {"$group": {"_id": None,
                        "gross": {"$sum": "$total_usd"},
                        "net": {"$sum": "$vendor_credit_net"}}},
        ]).to_list(1)
        if agg:
            vip_commission = round(float(agg[0]["gross"]) - float(agg[0]["net"]), 2)
        else:
            vip_commission = 0.0
    return {
        "start": start,
        "end": end,
        "product_id": product_ids[0] if product_ids and len(product_ids) == 1 else "",
        "product_ids": product_ids or [],
        "units_sold": int(units_sold),
        "sales_revenue": revenue,
        "cogs": cogs,
        "profit": profit,
        "margin_pct": round(profit / revenue * 100, 2) if revenue else 0.0,
        # iter219 — rentabilidad sobre el costo de la mercancía vendida.
        "profitability_pct": round(profit / cogs * 100, 2) if cogs else 0.0,
        "purchases_out": purchases,
        "net_cash_flow": round(revenue - purchases, 2),
        "inventory_value": inv_value,
        "units_in_stock": units_in_stock,
        "vip_commission_earned": vip_commission,
        "movements_count": len(movs),
    }
