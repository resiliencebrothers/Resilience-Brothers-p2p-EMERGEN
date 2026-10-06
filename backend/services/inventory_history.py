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
from auth_utils import now_utc, iso
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


async def build_cutoff_report(cutoff: str,
                              start: Optional[str] = None) -> dict:
    """Reporte de inventario a la FECHA DE CORTE `cutoff` (YYYY-MM-DD, hora de
    Cuba). Si se indica `start`, los flujos del período se acumulan en
    [start, cutoff] y la existencia inicial es la del día anterior a `start`;
    si no, la inicial es 0 y todo el histórico es flujo."""
    _, cutoff_end = _day_bounds(cutoff)          # fin EXCLUSIVO del día de corte
    period_start = _day_bounds(start)[0] if start else None  # inicio del período
    # iter339 (H04) — un corte es VIGENTE si abarca el presente (hoy/futuro). Solo
    # entonces la existencia reconstruida puede contrastarse con la real actual.
    is_current_cutoff = cutoff_end > iso(now_utc())

    # Productos de la empresa (incluye inactivos: un producto desactivado tras
    # el corte sigue en su reporte histórico).
    products = await db.products.find(
        _COMPANY_FILTER,
        {"_id": 0, "id": 1, "name": 1, "category": 1,
         "is_active": 1, "stock": 1}).to_list(5000)
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
         "quantity": 1, "unit_cost": 1, "unit_price": 1,
         "change_kind": 1, "note": 1,
         "created_at": 1, "applied_at": 1,
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
        lst.sort(key=lambda x: (x["_eff"], x["created_at"]))

    pids = allowed

    # iter329 — tasa USDT→CUP vigente a la fecha de corte (VIP) para valorar el
    # inventario también en USDT de forma reproducible.
    from services.fx_history import get_fx_at
    fx = await get_fx_at(cutoff)
    rate_vip = float(fx.get("rate_vip") or 0)

    rows = []
    coverage_from = None
    tot_value = 0.0
    tot_units = 0.0
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
        # iter339 (H04) — Integridad de la base: en un corte VIGENTE (incluye el
        # presente) la existencia reconstruida debe igualar la existencia REAL
        # del producto. Si no coincide, hay una base SIN DOCUMENTAR (p. ej. stock
        # cargado antes de la Fase 2, sin movimiento de apertura) y el histórico
        # de ese producto NO es fiable → PARCIAL. La ausencia de saldo negativo
        # no prueba integridad; y NO se rellena el pasado con la existencia de hoy.
        current_stock = _r(float(pmap.get(pid, {}).get("stock") or 0), 3)
        base_gap = (_r(current_stock - final_stock, 3)
                    if (is_current_cutoff and pid in pmap) else 0.0)
        undocumented = abs(base_gap) > 1e-9
        value = _r(final_stock * wac, 2)
        # Incluir solo filas con actividad/saldo, con conteo del día, o con una
        # base sin documentar que haya que señalar (H04).
        has_flow = any(flows[k] for k in _FLOW_KEYS)
        c = counts.get(pid)
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
            "count": count_block,
        })
        tot_value += value
        tot_units += final_stock if final_stock > 0 else 0
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
            "units": _r(tot_units, 3),
            "value": _r(tot_value, 2),
            "value_usdt": _r(tot_value / rate_vip, 2) if rate_vip > 0 else None,
            "diff_value": _r(tot_diff_value, 2),
            "diff_value_usdt": _r(tot_diff_value / rate_vip, 2) if rate_vip > 0 else None,
            "partial_count": partials,
            "undocumented_count": undoc_count,
        },
    }
