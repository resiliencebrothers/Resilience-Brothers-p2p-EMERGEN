"""IPV Fase 1 — Corte histórico del inventario (iter328).

Reconstruye, a una FECHA DE CORTE, la existencia y el valor del inventario de
la empresa a partir de los MOVIMIENTOS inmutables (no del estado actual del
producto). Así, un cambio posterior de costo/precio/nombre/estado NO altera la
evidencia del pasado: la consulta solo considera movimientos con fecha ≤ corte.

El valor se expresa en la moneda de control de la tienda (CUP). El costo al
corte es el promedio ponderado (WAC) RECONSTRUIDO replicando las entradas
cronológicamente hasta el corte (una compra posterior no cambia el valor del
pasado).

Reglas de cálculo (del "Plan por Fases IPV"):
- Existencia final = inicial + entradas − ventas − merma − consumo − otras
  salidas + ajustes netos (ajuste_pos − ajuste_neg).
- Valor del inventario = existencia al corte × costo (WAC) al corte.
- Diferencia de conteo = física − teórica.
- Valor de la diferencia = diferencia × costo de referencia GUARDADO en el
  conteo (no el costo de hoy).

Cobertura: si al reconstruir la existencia cae por debajo de cero, significa
que falta una base inicial auditada (p. ej. stock cargado antes de la Fase 2);
ese producto se marca como `parcial` y su valor se identifica como no fiable,
sin rellenarlo con el stock/costo de hoy.
"""
from typing import Optional

from services.inventory import (_COMPANY_FILTER, _day_bounds, OUTPUT_TYPES)
from db_client import db

STORE_CURRENCY = "CUP"

# Tipos que afectan la existencia (y por tanto la reconstrucción del stock/WAC).
_STOCK_TYPES = ("entrada", "venta", "ajuste_pos", "ajuste_neg", *OUTPUT_TYPES)
_FLOW_KEYS = ("entrada", "venta", "merma", "consumo", "otra_salida",
              "ajuste_pos", "ajuste_neg")


def _r(n: float, d: int = 2) -> float:
    """Redondeo que colapsa −0.0 a 0.0 para una presentación limpia."""
    v = round(float(n or 0), d)
    return 0.0 if v == 0 else v


def _effect_order_key(m: dict) -> tuple:
    """iter349 (RV-02/H03) — orden REAL de aplicación de los efectos: la
    SECUENCIA EFECTIVA por producto (`effect_seq`), asignada ATÓMICAMENTE junto
    al cambio de stock/WAC, manda sobre cualquier marca de tiempo (`applied_at`
    puede sellarse fuera de orden en un reintento/recuperación). Los movimientos
    heredados sin secuencia se ordenan por su instante efectivo y van ANTES de
    los que ya llevan secuencia (ocurrieron antes de esta mejora)."""
    seq = m.get("effect_seq")
    if seq is not None:
        return (1, int(seq), "")
    eff = m.get("_eff") or m.get("applied_at") or m.get("created_at") or ""
    # iter351 (RV-02/H03) — un movimiento YA aplicado cuya secuencia no pudo
    # reconstruirse (incertidumbre señalada por el recuperador) NO es heredado:
    # anteponerlo a los secuenciados provocaría infravaloración. Se ordena al
    # FINAL por su instante efectivo (conservador + evidencia de la caída).
    if m.get("effect_seq_uncertain"):
        return (2, 0, eff)
    # Movimiento heredado real (anterior a la secuencia efectiva) → va ANTES,
    # ordenado por su instante efectivo (ocurrió antes de esta mejora).
    return (0, 0, eff)


async def _documented_totals(pids: list) -> dict:
    """iter350b (RV-03/H04) — delta de stock DOCUMENTADO (neto) de TODOS los
    movimientos confirmados por producto, SIN filtro de fecha. Replica el cálculo
    de services.inventory_ipv._documented_stock_delta pero agrupado: la base sin
    documentar es un INVARIANTE = existencia_real − este total (no depende de la
    fecha del corte)."""
    if not pids:
        return {}
    pipe = [
        {"$match": {"product_id": {"$in": pids},
                    "type": {"$in": list(_STOCK_TYPES)},
                    "$or": [{"needs_stock": {"$ne": True}},
                            {"stock_applied": True}]}},
        {"$group": {"_id": "$product_id", "delta": {"$sum": {"$switch": {
            "branches": [{"case": {"$in": ["$type", ["entrada", "ajuste_pos"]]},
                          "then": {"$ifNull": ["$quantity", 0]}}],
            "default": {"$multiply": [{"$ifNull": ["$quantity", 0]}, -1]}}}}}},
    ]
    rows = await db.inventory_movements.aggregate(pipe).to_list(500000)
    return {r["_id"]: round(float(r["delta"] or 0), 3) for r in rows}


async def _audited_openings_after(pids: list, cutoff_end: str) -> dict:
    """iter350b (RV-03/H04) — cantidad de APERTURAS AUDITADAS
    (source='apertura_auditada') cuyo efecto cae DESPUÉS del corte
    (created_at ≥ cutoff_end). En esa fecha esa base aún no estaba documentada,
    así que se reintegra al hueco: el histórico ANTERIOR a la apertura no es
    fiable y debe seguir marcándose parcial."""
    if not pids:
        return {}
    pipe = [
        {"$match": {"product_id": {"$in": pids},
                    "source": "apertura_auditada",
                    "created_at": {"$gte": cutoff_end},
                    "$or": [{"needs_stock": {"$ne": True}},
                            {"stock_applied": True}]}},
        {"$group": {"_id": "$product_id",
                    "qty": {"$sum": {"$ifNull": ["$quantity", 0]}}}},
    ]
    rows = await db.inventory_movements.aggregate(pipe).to_list(500000)
    return {r["_id"]: round(float(r["qty"] or 0), 3) for r in rows}


async def _audited_opening_dates(pids: list) -> dict:
    """iter350b (RV-03/H04) — fecha (YYYY-MM-DD) de la PRIMERA apertura auditada
    por producto; desde ella el histórico queda documentado y es fiable."""
    if not pids:
        return {}
    pipe = [
        {"$match": {"product_id": {"$in": pids},
                    "source": "apertura_auditada"}},
        {"$group": {"_id": "$product_id", "first": {"$min": "$created_at"}}},
    ]
    rows = await db.inventory_movements.aggregate(pipe).to_list(500000)
    return {r["_id"]: (r["first"] or "")[:10] for r in rows if r.get("first")}


async def build_cutoff_report(cutoff: str,
                              start: Optional[str] = None) -> dict:
    """Reporte de inventario a la FECHA DE CORTE `cutoff` (YYYY-MM-DD, hora de
    Cuba). Si se indica `start`, los flujos del período se acumulan en
    [start, cutoff] y la existencia inicial es la del día anterior a `start`;
    si no, la inicial es 0 y todo el histórico es flujo."""
    _, cutoff_end = _day_bounds(cutoff)          # fin EXCLUSIVO del día de corte
    period_start = _day_bounds(start)[0] if start else None  # inicio del período

    # Productos de la empresa (incluye inactivos: un producto desactivado tras
    # el corte sigue en su reporte histórico).
    products = await db.products.find(
        _COMPANY_FILTER,
        {"_id": 0, "id": 1, "name": 1, "category": 1,
         "is_active": 1, "stock": 1, "unit": 1}).to_list(5000)
    pmap = {p["id"]: p for p in products}

    # Conteos físicos del día de corte (para valorar diferencias).
    counts = {c["product_id"]: c for c in await db.inventory_counts.find(
        {"count_date": cutoff}, {"_id": 0}).to_list(50000)}

    # Solo productos que EXISTEN en la colección (incluye inactivos: un producto
    # desactivado tras el corte sigue en su histórico) o con conteo ese día. Los
    # movimientos de productos ya BORRADOS no generan filas (evita ruido).
    allowed = set(pmap.keys()) | set(counts.keys())

    # iter338 (H03) — Reconstrucción por ORDEN EFECTIVO de aplicación, no por
    # created_at. Un movimiento con `needs_stock` cuyo efecto aún NO aterrizó
    # (stock_applied != True) está PENDIENTE y no cuenta hasta aplicarse; su
    # tiempo efectivo es `applied_at` (puede ser posterior a otro movimiento
    # registrado después pero aplicado antes). Los flujos cuyo stock se toca
    # fuera de record_movement (canjes: sin `needs_stock`) sí cuentan, con su
    # created_at como tiempo efectivo. Así el WAC histórico concuerda con el
    # costo móvil efectivamente aplicado al producto.
    movs = await db.inventory_movements.find(
        {"product_id": {"$in": list(allowed)},
         "created_at": {"$lt": cutoff_end},
         "type": {"$in": [*_STOCK_TYPES, "precio"]}},
        {"_id": 0, "product_id": 1, "product_name": 1, "type": 1,
         "quantity": 1, "unit_cost": 1, "unit_price": 1, "unit": 1,
         "change_kind": 1, "note": 1,
         "created_at": 1, "applied_at": 1, "effect_seq": 1,
         "effect_seq_uncertain": 1,
         "needs_stock": 1, "stock_applied": 1}).to_list(500000)
    by_prod: dict = {}
    for m in movs:
        # Pendiente de aplicación (efecto no aterrizado) → se ignora.
        if m.get("needs_stock") and not m.get("stock_applied"):
            continue
        # Instante efectivo = cuando el stock/WAC cambió realmente (applied_at),
        # con created_at como respaldo (precios y flujos sin needs_stock).
        eff = m.get("applied_at") or m["created_at"]
        # Un efecto que aterrizó DESPUÉS del corte no pertenece al histórico.
        if eff >= cutoff_end:
            continue
        m["_eff"] = eff
        by_prod.setdefault(m["product_id"], []).append(m)
    for lst in by_prod.values():
        lst.sort(key=_effect_order_key)

    pids = allowed

    # iter350b (RV-03/H04) — datos de integridad de base (INVARIANTE en el
    # tiempo): el total documentado, las aperturas auditadas posteriores al corte
    # y la fecha de la primera apertura auditada por producto.
    documented_totals = await _documented_totals(list(allowed))
    openings_after = await _audited_openings_after(list(allowed), cutoff_end)
    opening_dates = await _audited_opening_dates(list(allowed))

    # iter329 — tasa USDT→CUP vigente a la fecha de corte (VIP) para valorar el
    # inventario también en USDT de forma reproducible.
    from services.fx_history import get_fx_at
    fx = await get_fx_at(cutoff)
    rate_vip = float(fx.get("rate_vip") or 0)

    rows = []
    coverage_from = None
    tot_value = 0.0
    # H12 (iter345) — las cantidades físicas NO se suman entre unidades distintas
    # (u/lb/kg): se agregan por unidad para no mezclar magnitudes sin sentido.
    units_by_unit: dict = {}
    tot_diff_value = 0.0
    partials = 0
    undoc_count = 0
    for pid in pids:
        mlist = by_prod.get(pid, [])
        if mlist:
            first_at = mlist[0]["created_at"]
            if coverage_from is None or first_at < coverage_from:
                coverage_from = first_at
        stock = 0.0
        wac = 0.0
        price = None
        opening = 0.0
        opening_captured = period_start is None
        negative_seen = False
        flows = {k: 0.0 for k in _FLOW_KEYS}
        name = pmap.get(pid, {}).get("name", "")
        for m in mlist:
            t = m["type"]
            created = m["_eff"]  # iter338 (H03) — orden/efecto por tiempo real
            name = m.get("product_name") or name
            if (period_start is not None and not opening_captured
                    and created >= period_start):
                opening = stock
                opening_captured = True
            if t == "precio":
                # H09 (iter343) — una auditoría de COSTO/WAC ('cost', o legado
                # con nota «Costo…») NO es un cambio de precio de venta: se
                # ignora para conservar el precio histórico vigente.
                kind = m.get("change_kind")
                is_cost = (kind == "cost" or
                           (kind is None and
                            (m.get("note") or "").startswith("Costo")))
                if is_cost:
                    continue
                price = float(m.get("unit_price") or 0)
                continue
            q = float(m.get("quantity") or 0)
            if t == "entrada":
                uc = float(m.get("unit_cost") or 0)
                new_stock = stock + q
                wac = round((stock * wac + q * uc) / new_stock, 4) \
                    if new_stock > 0 else uc
                stock = new_stock
            else:
                # ajuste_pos suma; venta/ajuste_neg/merma/consumo/otra_salida restan.
                stock += q if t == "ajuste_pos" else -q
            if stock < -1e-9:
                negative_seen = True
            if period_start is None or created >= period_start:
                flows[t] = flows.get(t, 0.0) + q
        if period_start is not None and not opening_captured:
            opening = stock  # el período empieza tras el último movimiento
        final_stock = stock
        # iter339 (H04) + iter350b (RV-03/H04) — Integridad de la base. La base
        # SIN DOCUMENTAR es un INVARIANTE del producto en el tiempo:
        #     base_gap = existencia_real − existencia_documentada_total
        # (cada movimiento real suma por igual a la existencia y a lo documentado,
        # así que su diferencia no cambia con el paso de los días). NO depende de
        # que el corte sea "vigente": por eso avanzar el reloj NO puede borrar la
        # marca de parcial de un corte pasado. Para un corte PASADO, una apertura
        # auditada registrada DESPUÉS todavía no documentaba la base en esa fecha,
        # así que se reintegra al hueco (el período anterior a la apertura sigue
        # sin base fiable). Un producto BORRADO (sin existencia real consultable)
        # no se puede verificar por este criterio → base_gap 0.
        current_stock = _r(float(pmap.get(pid, {}).get("stock") or 0), 3)
        if pid in pmap:
            base_gap = _r(current_stock - documented_totals.get(pid, 0.0)
                          + openings_after.get(pid, 0.0), 3)
        else:
            base_gap = 0.0
        undocumented = abs(base_gap) > 1e-9
        # Desde cuándo es fiable el histórico de este producto: tras una apertura
        # auditada, desde su fecha; si nunca hubo hueco, desde su primer
        # movimiento; si aún hay base sin documentar en este corte, no es fiable.
        if undocumented:
            reliable_from = None
        elif pid in opening_dates:
            reliable_from = opening_dates[pid]
        elif mlist:
            reliable_from = mlist[0]["created_at"][:10]
        else:
            reliable_from = None
        value = _r(final_stock * wac, 2)
        # Incluir solo filas con actividad/saldo, con conteo del día, o con una
        # base sin documentar que haya que señalar (H04).
        has_flow = any(flows[k] for k in _FLOW_KEYS)
        c = counts.get(pid)
        # H12 (iter345) + RV-05 (iter350c) — unidad del PERÍODO a partir de
        # evidencia HISTÓRICA (la unidad CONGELADA en los propios movimientos del
        # período o en el conteo del día), NO de la ficha viva: editar la unidad
        # del producto hoy NO debe reinterpretar cantidades de cortes pasados.
        # La ficha solo se usa como respaldo para productos aún sin historial.
        hist_unit = next(
            (m.get("unit") for m in reversed(mlist) if m.get("unit")), None)
        row_unit = (hist_unit or (c.get("unit") if c else None)
                    or pmap.get(pid, {}).get("unit") or "unidad")
        if (_r(final_stock, 3) == 0 and not has_flow and not c
                and not undocumented):
            continue
        partial = negative_seen or undocumented
        if partial:
            partials += 1
        if undocumented:
            undoc_count += 1
        count_block = None
        if c:
            # iter337 (H02) — conservar la precisión fraccionaria (lb/kg a 3
            # decimales) de la diferencia. El int() anterior truncaba −0,75 lb
            # a 0 y hacía desaparecer la diferencia y su valor del histórico/CSV.
            diff = _r(float(c.get("difference") or 0), 3)
            ref_cost = c.get("reference_cost")
            fallback = ref_cost is None
            if fallback:
                ref_cost = wac  # conteos antiguos sin costo de referencia
            diff_value = _r(diff * float(ref_cost or 0), 2)
            tot_diff_value += diff_value
            count_block = {
                "counted_qty": c.get("counted_qty"),
                "theoretical": c.get("theoretical_stock"),
                "difference": diff,
                "unit": c.get("unit") or "unidad",
                "reference_cost": _r(float(ref_cost or 0), 4),
                "difference_value": diff_value,
                "currency": c.get("currency") or STORE_CURRENCY,
                "authorized": bool(c.get("authorized")),
                "fallback_cost": fallback,
            }
        rows.append({
            "product_id": pid,
            "name": name,
            "unit": row_unit,
            "category": pmap.get(pid, {}).get("category", ""),
            "is_active": bool(pmap.get(pid, {}).get("is_active", True)),
            "exists": pid in pmap,
            "opening": _r(opening, 3),
            "entradas": _r(flows["entrada"], 3),
            "ventas": _r(flows["venta"], 3),
            "merma": _r(flows["merma"], 3),
            "consumo": _r(flows["consumo"], 3),
            "otra_salida": _r(flows["otra_salida"], 3),
            "ajuste_neto": _r(flows["ajuste_pos"] - flows["ajuste_neg"], 3),
            "final_stock": _r(final_stock, 3),
            "wac": _r(wac, 4),
            "price": _r(price, 2) if price is not None else None,
            "value": value,
            "value_usdt": _r(value / rate_vip, 2) if rate_vip > 0 else None,
            "currency": STORE_CURRENCY,
            "coverage": "parcial" if partial else "completa",
            "undocumented_base": undocumented,
            "base_gap": base_gap,
            "reliable_from": reliable_from,
            "count": count_block,
        })
        tot_value += value
        if final_stock > 0:
            units_by_unit[row_unit] = units_by_unit.get(row_unit, 0.0) + final_stock
    rows.sort(key=lambda r: (-r["value"], r["name"].lower()))
    return {
        "cutoff": cutoff,
        "start": start or None,
        "currency": STORE_CURRENCY,
        "coverage_from": (coverage_from or "")[:10] or None,
        "fx": {
            "rate_field": "rate_vip",
            "rate": rate_vip,
            "rate_normal": float(fx.get("rate_normal") or 0),
            "rate_date": fx.get("rate_date"),
            "estimated": bool(fx.get("estimated")),
            "quote_currency": "USDT",
        },
        "products": rows,
        "totals": {
            "num_products": len(rows),
            "units_by_unit": {u: _r(v, 3) for u, v in units_by_unit.items()},
            "value": _r(tot_value, 2),
            "value_usdt": _r(tot_value / rate_vip, 2) if rate_vip > 0 else None,
            "diff_value": _r(tot_diff_value, 2),
            "diff_value_usdt": _r(tot_diff_value / rate_vip, 2) if rate_vip > 0 else None,
            "partial_count": partials,
            "undocumented_count": undoc_count,
        },
    }
