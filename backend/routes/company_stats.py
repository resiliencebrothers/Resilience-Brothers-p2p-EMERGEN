"""Estadísticas de empresas (Fondo de empresa > Ingresos) — FASE 1.

Módulo de SOLO LECTURA. No crea, confirma, cancela ni recalcula operaciones;
no mueve saldos ni inventario. Responde:
  - ¿Qué empresas aportan más comisión neta a Resilience?
  - ¿Qué productos/servicios se venden más y aportan más comisión?
  - ¿A qué municipios se completan más entregas?

CONTRATO DE DATOS (mapa real verificado en FASE 0):
  - Fuente de verdad de comisiones = `db.redemptions` (Marketplace Empresas):
      fund_inflow_amount / fund_inflow_at / fund_inflow_reversed_at (reversión),
      fund_inflow_currency (USDT; None se trata como USDT),
      vendor_owner_id / vendor_owner_name (empresa; puede faltar → "Sin atribuir"),
      product_id / product_name / quantity, total_usd (bruto),
      vendor_credit_net (neto liquidado a la empresa).
    Una comisión es ACTIVA si no tiene fund_inflow_reversed_at.
  - Servicios = `db.service_bookings` (status settled = completado).
  - Mensajería/municipios = `db.deliveries` (status 'delivered' = completada),
      province/municipality del destino, fee_usdt (recaudación), platform_share_usdt
      (parte propia de Resilience), courier_share_usdt (pago al mensajero).

CONCILIACIÓN (plan §8): como las empresas y "Sin atribuir" salen del MISMO filtro
de redemptions, se cumple por construcción:
    Σ comisión por empresa + comisión sin atribuir = total comisiones elegibles.

LÍMITES DE COBERTURA declarados al cliente en cada respuesta (`coverage`):
  - moneda: comisiones denominadas en USDT.
  - fecha de comisión = fund_inflow_at (fecha financiera del movimiento).
  - fecha de entrega completada = updated_at del delivery 'delivered' (mejor dato
    disponible; no se inventan marcas prometidas).
"""
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from auth_utils import now_utc, require_permission
from db_client import db

router = APIRouter(tags=["Admin"])

PERM = "company_funds"
COMMISSION_CCY = "USDT"

# Comisión activa = no revertida (misma definición que el panel de comisiones).
_ACTIVE = {"$in": [{"$ifNull": ["$fund_inflow_reversed_at", ""]}, ["", None]]}
_UNATTRIBUTED = "__unattributed__"
_DELIVERED = "delivered"
_SERVICE_DONE = ["settled"]


def _bound(s: Optional[str], is_end: bool) -> Optional[str]:
    """Fecha/fecha-hora ISO → límite ISO. Fecha sin hora se expande al día
    completo. Devuelve None si vacío. 400 si es inválida."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        if "T" in s:
            datetime.fromisoformat(s.replace("Z", "+00:00"))
            return s
        datetime.fromisoformat(s)
        return f"{s}T23:59:59.999999+00:00" if is_end else f"{s}T00:00:00.000000+00:00"
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Fecha inválida: {s}")


def _range(field: str, since: Optional[str], until: Optional[str]) -> Dict[str, Any]:
    """Filtro de rango sobre un campo de fecha ISO (string). Si no hay límites,
    exige simplemente que el campo exista (no vacío/None)."""
    lo, hi = _bound(since, False), _bound(until, True)
    cond: Dict[str, Any] = {}
    if lo:
        cond["$gte"] = lo
    if hi:
        cond["$lte"] = hi
    return cond or {"$nin": [None, ""]}


def _commission_match(since, until, company_id=None) -> Dict[str, Any]:
    m: Dict[str, Any] = {"fund_inflow_at": _range("fund_inflow_at", since, until)}
    if company_id and str(company_id).strip():
        m["vendor_owner_id"] = str(company_id).strip()
    return m


def _round(x: Any, p: int = 6) -> float:
    return round(float(x or 0), p)


async def _companies_agg(since, until, company_id=None) -> list:
    """Agrega redemptions por empresa (vendor_owner_id); las que no tienen empresa
    caen en `_UNATTRIBUTED`. Devuelve filas con bruto/comisión/neto/órdenes y sus
    reversiones (importe y nº de movimientos)."""
    match = _commission_match(since, until, company_id)
    group_id = {"$cond": [
        {"$in": [{"$ifNull": ["$vendor_owner_id", ""]}, ["", None]]},
        _UNATTRIBUTED, "$vendor_owner_id",
    ]}
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": group_id,
            "company": {"$first": "$vendor_owner_name"},
            "gross": {"$sum": {"$cond": [_ACTIVE, {"$ifNull": ["$total_usd", 0]}, 0]}},
            "commission": {"$sum": {"$cond": [_ACTIVE, {"$ifNull": ["$fund_inflow_amount", 0]}, 0]}},
            "net_vendor": {"$sum": {"$cond": [_ACTIVE, {"$ifNull": ["$vendor_credit_net", 0]}, 0]}},
            "orders": {"$sum": {"$cond": [_ACTIVE, 1, 0]}},
            "reversed_commission": {"$sum": {"$cond": [_ACTIVE, 0, {"$ifNull": ["$fund_inflow_amount", 0]}]}},
            "reversed_orders": {"$sum": {"$cond": [_ACTIVE, 0, 1]}},
        }},
    ]
    return await db.redemptions.aggregate(pipeline).to_list(5000)


def _split_rows(rows: list) -> tuple[list, dict, dict]:
    """Separa filas de empresa y la fila 'Sin atribuir'; calcula totales."""
    companies, unattributed = [], None
    for r in rows:
        if r["_id"] == _UNATTRIBUTED:
            unattributed = r
        else:
            companies.append(r)
    totals = {
        "commission": sum(_round(r["commission"]) for r in rows),
        "reversed_commission": sum(_round(r["reversed_commission"]) for r in rows),
        "reversed_orders": sum(int(r["reversed_orders"] or 0) for r in rows),
        "gross": sum(_round(r["gross"]) for r in rows),
        "orders": sum(int(r["orders"] or 0) for r in rows),
    }
    unatt = {
        "commission": _round(unattributed["commission"]) if unattributed else 0.0,
        "reversed_commission": _round(unattributed["reversed_commission"]) if unattributed else 0.0,
        "orders": int(unattributed["orders"]) if unattributed else 0,
        "gross": _round(unattributed["gross"]) if unattributed else 0.0,
    }
    return companies, unatt, totals


async def _deliveries_summary(since, until) -> dict:
    match = {"status": _DELIVERED, "updated_at": _range("updated_at", since, until)}
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "completed": {"$sum": 1},
            "fee": {"$sum": {"$ifNull": ["$fee_usdt", 0]}},
            "platform_share": {"$sum": {"$ifNull": ["$platform_share_usdt", 0]}},
            "courier_share": {"$sum": {"$ifNull": ["$courier_share_usdt", 0]}},
        }},
    ]
    agg = await db.deliveries.aggregate(pipeline).to_list(1)
    g = agg[0] if agg else {}
    return {
        "completed": int(g.get("completed") or 0),
        "fee_usdt": _round(g.get("fee"), 2),
        "platform_share_usdt": _round(g.get("platform_share"), 2),
        "courier_share_usdt": _round(g.get("courier_share"), 2),
    }


async def _services_summary(since, until) -> dict:
    match = {"status": {"$in": _SERVICE_DONE}, "updated_at": _range("updated_at", since, until)}
    pipeline = [
        {"$match": match},
        {"$group": {"_id": None, "completed": {"$sum": 1},
                    "amount": {"$sum": {"$ifNull": ["$amount_usdt", 0]}}}},
    ]
    agg = await db.service_bookings.aggregate(pipeline).to_list(1)
    g = agg[0] if agg else {}
    return {"completed": int(g.get("completed") or 0), "amount_usdt": _round(g.get("amount"), 2)}


async def _products_rows(since, until, kind, company_id=None) -> list:
    """Filas de productos/servicios (sin orden ni límite) — reutilizado por el
    endpoint JSON y la exportación CSV para que coincidan (EST-11)."""
    if kind == "products":
        match = _commission_match(since, until, company_id)
        pipeline = [
            {"$match": match},
            {"$group": {
                "_id": "$product_id",
                "product": {"$first": "$product_name"},
                "company": {"$first": "$vendor_owner_name"},
                "company_id": {"$first": "$vendor_owner_id"},
                "quantity": {"$sum": {"$cond": [_ACTIVE, {"$ifNull": ["$quantity", 0]}, 0]}},
                "gross_usdt": {"$sum": {"$cond": [_ACTIVE, {"$ifNull": ["$total_usd", 0]}, 0]}},
                "commission_usdt": {"$sum": {"$cond": [_ACTIVE, {"$ifNull": ["$fund_inflow_amount", 0]}, 0]}},
                "orders": {"$sum": {"$cond": [_ACTIVE, 1, 0]}},
            }},
        ]
        rows = await db.redemptions.aggregate(pipeline).to_list(5000)
        return [{
            "id": r["_id"] or "—",
            "name": r.get("product") or "—",
            "company": r.get("company") or "Sin atribuir",
            "company_id": r.get("company_id") or "",
            "quantity": _round(r["quantity"], 2),
            "gross_usdt": _round(r["gross_usdt"], 2),
            "commission_usdt": _round(r["commission_usdt"], 2),
            "orders": int(r["orders"] or 0),
        } for r in rows]
    match = {"status": {"$in": _SERVICE_DONE}, "updated_at": _range("updated_at", since, until)}
    if company_id and str(company_id).strip():
        match["company_id"] = str(company_id).strip()
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": "$service_id",
            "name": {"$first": "$service_title"},
            "company": {"$first": "$company_name"},
            "company_id": {"$first": "$company_id"},
            "quantity": {"$sum": {"$ifNull": ["$quantity", 1]}},
            "gross_usdt": {"$sum": {"$ifNull": ["$amount_usdt", 0]}},
            "orders": {"$sum": 1},
        }},
    ]
    rows = await db.service_bookings.aggregate(pipeline).to_list(5000)
    return [{
        "id": r["_id"] or "—",
        "name": r.get("name") or "—",
        "company": r.get("company") or "—",
        "company_id": r.get("company_id") or "",
        "quantity": _round(r["quantity"], 2),
        "gross_usdt": _round(r["gross_usdt"], 2),
        "commission_usdt": None,
        "orders": int(r["orders"] or 0),
    } for r in rows]


async def _municipalities_rows(since, until) -> tuple[list, int]:
    match = {"status": _DELIVERED, "updated_at": _range("updated_at", since, until)}
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {
                "province": {"$ifNull": ["$province", ""]},
                "municipality": {"$ifNull": ["$municipality", ""]},
            },
            "completed": {"$sum": 1},
            "fee_usdt": {"$sum": {"$ifNull": ["$fee_usdt", 0]}},
            "platform_share_usdt": {"$sum": {"$ifNull": ["$platform_share_usdt", 0]}},
            "courier_share_usdt": {"$sum": {"$ifNull": ["$courier_share_usdt", 0]}},
        }},
    ]
    rows = await db.deliveries.aggregate(pipeline).to_list(5000)
    total = sum(int(r["completed"] or 0) for r in rows)
    out = []
    for r in rows:
        prov = (r["_id"].get("province") or "").strip()
        muni = (r["_id"].get("municipality") or "").strip()
        completed = int(r["completed"] or 0)
        out.append({
            "province": prov or "—",
            "municipality": muni or "Municipio no registrado",
            "registered": bool(muni),
            "completed": completed,
            "fee_usdt": _round(r["fee_usdt"], 2),
            "platform_share_usdt": _round(r["platform_share_usdt"], 2),
            "courier_share_usdt": _round(r["courier_share_usdt"], 2),
            "share_pct": (_round(completed / total * 100, 2) if total > 0 else None),
        })
    out.sort(key=lambda x: x["completed"], reverse=True)
    return out, total


def _previous_range(since, until) -> Optional[dict]:
    """Intervalo anterior de duración comparable (termina el día antes de `since`).
    Sólo si hay fechas explícitas (plan §2: comparar contra duración comparable)."""
    from datetime import timedelta
    s, u = (since or "").strip(), (until or "").strip()
    if not s or not u:
        return None
    try:
        sd = datetime.fromisoformat(s[:10]).date()
        ud = datetime.fromisoformat(u[:10]).date()
    except ValueError:
        return None
    span = (ud - sd).days
    if span < 0:
        return None
    prev_until = sd - timedelta(days=1)
    prev_since = prev_until - timedelta(days=span)
    return {"since": prev_since.isoformat(), "until": prev_until.isoformat()}


async def _comparison_block(since, until, current_net: float) -> Optional[dict]:
    prev = _previous_range(since, until)
    if not prev:
        return None
    rows = await _companies_agg(prev["since"], prev["until"])
    _, _, ptot = _split_rows(rows)
    prev_net = _round(ptot["commission"], 2)
    delta = _round(current_net - prev_net, 2)
    return {
        "previous_since": prev["since"], "previous_until": prev["until"],
        "previous_net_commission_usdt": prev_net,
        "delta_usdt": delta,
        "delta_pct": (_round(delta / prev_net * 100, 2) if prev_net > 0 else None),
    }


def _concentration_block(companies: list, total: float) -> Optional[dict]:
    """Concentración del aporte en las 5/10 principales empresas (plan §7).
    Sólo interpretable con total neto positivo."""
    if total <= 0 or not companies:
        return None
    comms = sorted((_round(c["commission"]) for c in companies), reverse=True)
    return {
        "top5_share_pct": _round(sum(comms[:5]) / total * 100, 2),
        "top10_share_pct": _round(sum(comms[:10]) / total * 100, 2),
        "companies_count": len(companies),
    }


def _coverage() -> dict:
    return {
        "currency": COMMISSION_CCY,
        "commission_date_field": "fund_inflow_at",
        "delivery_date_field": "updated_at (status=delivered)",
        "notes": [
            "Comisiones denominadas en USDT (fund_inflow_amount).",
            "Entrega completada = status 'delivered'; su fecha usa updated_at.",
            "Comisiones sin empresa identificable se muestran como 'Sin atribuir'.",
            "Entregas sin municipio fiable se agrupan en 'Municipio no registrado'.",
        ],
    }


# ---------------------------------------------------------------------------
# 1) RESUMEN
# ---------------------------------------------------------------------------
@router.get("/admin/company-stats/summary")
async def company_stats_summary(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
    company_id: Optional[str] = None,
) -> Any:
    await require_permission(request, PERM)
    rows = await _companies_agg(since, until, company_id)
    companies, unatt, totals = _split_rows(rows)
    deliveries = await _deliveries_summary(since, until)
    services = await _services_summary(since, until)

    companies_contributing = sum(1 for r in companies if _round(r["commission"]) > 0)
    companies_sum = sum(_round(r["commission"]) for r in companies)
    comparison = await _comparison_block(since, until, _round(totals["commission"], 2))
    concentration = _concentration_block(companies, _round(totals["commission"], 2))

    return {
        "currency": COMMISSION_CCY,
        "updated_at": now_utc().isoformat(),
        "filters": {"since": since, "until": until, "company_id": company_id},
        "economic": {
            # A — comisión comercial neta (activa) de Resilience
            "net_commission_usdt": _round(totals["commission"], 2),
            # B — reversiones (importe y nº), visibles por separado
            "reversed_commission_usdt": _round(totals["reversed_commission"], 2),
            "reversed_count": totals["reversed_orders"],
            # C — ingreso propio por mensajería (parte registrada de Resilience)
            "messaging_own_income_usdt": deliveries["platform_share_usdt"],
            "unattributed_commission_usdt": unatt["commission"],
        },
        "operational": {
            # D — ventas brutas finalizadas de empresas (≠ ingreso de Resilience)
            "gross_sales_usdt": _round(totals["gross"], 2),
            "orders_completed": totals["orders"],
            "deliveries_completed": deliveries["completed"],
            "services_completed": services["completed"],
            "companies_contributing": companies_contributing,
        },
        "messaging": {
            "fee_collected_usdt": deliveries["fee_usdt"],
            "platform_share_usdt": deliveries["platform_share_usdt"],
            "courier_share_usdt": deliveries["courier_share_usdt"],
        },
        # Identidad de conciliación (plan §8)
        "reconciliation": {
            "companies_commission_usdt": _round(companies_sum, 2),
            "unattributed_commission_usdt": unatt["commission"],
            "total_eligible_commission_usdt": _round(totals["commission"], 2),
            "balanced": abs((companies_sum + unatt["commission"]) - totals["commission"]) < 1e-6,
        },
        # FASE 2 — comparativa con período anterior comparable y concentración
        "comparison": comparison,
        "concentration": concentration,
        "coverage": _coverage(),
    }


# ---------------------------------------------------------------------------
# 2) EMPRESAS — ranking por comisión neta
# ---------------------------------------------------------------------------
@router.get("/admin/company-stats/companies")
async def company_stats_companies(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
    limit: int = 50, sort: str = "commission",
) -> Any:
    await require_permission(request, PERM)
    limit = max(1, min(int(limit), 500))
    rows = await _companies_agg(since, until)
    companies, unatt, totals = _split_rows(rows)

    total_comm = totals["commission"]
    sort_key = {"commission": "commission", "gross": "gross", "orders": "orders"}.get(sort, "commission")

    out = []
    for r in companies:
        comm = _round(r["commission"], 2)
        out.append({
            "company_id": r["_id"],
            "company": r.get("company") or "—",
            "commission_usdt": comm,
            "gross_usdt": _round(r["gross"], 2),
            "net_vendor_usdt": _round(r["net_vendor"], 2),
            "orders": int(r["orders"] or 0),
            "reversed_commission_usdt": _round(r["reversed_commission"], 2),
            "reversed_orders": int(r["reversed_orders"] or 0),
            # Participación sobre el TOTAL del conjunto filtrado (no solo top-N).
            # Si el total es 0 o negativo no se muestra un % engañoso.
            "share_pct": (_round(comm / total_comm * 100, 2) if total_comm > 0 else None),
        })
    out.sort(key=lambda x: x.get({"commission": "commission_usdt", "gross": "gross_usdt",
                                  "orders": "orders"}[sort_key]) or 0, reverse=True)

    return {
        "currency": COMMISSION_CCY,
        "updated_at": now_utc().isoformat(),
        "rows": out[:limit],
        "shown": min(len(out), limit),
        "total_companies": len(out),
        # Fila especial: comisiones válidas sin empresa identificable.
        "unattributed": {
            "commission_usdt": unatt["commission"],
            "gross_usdt": unatt["gross"],
            "orders": unatt["orders"],
            "reversed_commission_usdt": unatt["reversed_commission"],
            "share_pct": (_round(unatt["commission"] / total_comm * 100, 2) if total_comm > 0 else None),
        },
        "totals": {
            "commission_usdt": _round(totals["commission"], 2),
            "gross_usdt": _round(totals["gross"], 2),
            "reversed_commission_usdt": _round(totals["reversed_commission"], 2),
        },
        "coverage": _coverage(),
    }


# ---------------------------------------------------------------------------
# 3) PRODUCTOS Y SERVICIOS
# ---------------------------------------------------------------------------
@router.get("/admin/company-stats/products")
async def company_stats_products(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
    kind: str = "products", limit: int = 50, sort: str = "commission",
    company_id: Optional[str] = None,
) -> Any:
    await require_permission(request, PERM)
    limit = max(1, min(int(limit), 500))
    kind = "services" if str(kind).lower() == "services" else "products"
    out = await _products_rows(since, until, kind, company_id)
    if kind == "products":
        sort_field = {"quantity": "quantity", "gross": "gross_usdt",
                      "commission": "commission_usdt"}.get(sort, "commission_usdt")
    else:
        sort_field = {"quantity": "quantity", "gross": "gross_usdt",
                      "commission": "gross_usdt"}.get(sort, "gross_usdt")

    out.sort(key=lambda x: x.get(sort_field) or 0, reverse=True)
    return {
        "currency": COMMISSION_CCY,
        "kind": kind,
        "updated_at": now_utc().isoformat(),
        "rows": out[:limit],
        "shown": min(len(out), limit),
        "total": len(out),
        "coverage": _coverage(),
    }


# ---------------------------------------------------------------------------
# 4) MENSAJERÍA Y MUNICIPIOS
# ---------------------------------------------------------------------------
@router.get("/admin/company-stats/municipalities")
async def company_stats_municipalities(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
    limit: int = 50,
) -> Any:
    await require_permission(request, PERM)
    limit = max(1, min(int(limit), 500))
    out, total_completed = await _municipalities_rows(since, until)

    return {
        "currency": COMMISSION_CCY,
        "updated_at": now_utc().isoformat(),
        "rows": out[:limit],
        "shown": min(len(out), limit),
        "total_municipalities": len(out),
        "total_completed": total_completed,
        "coverage": _coverage(),
    }


# ---------------------------------------------------------------------------
# 5) TENDENCIA (evolución de comisiones por día/semana/mes) — FASE 2
# ---------------------------------------------------------------------------
@router.get("/admin/company-stats/trend")
async def company_stats_trend(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
    bucket: str = "month", company_id: Optional[str] = None,
) -> Any:
    await require_permission(request, PERM)
    unit = {"day": "day", "week": "week", "month": "month"}.get(str(bucket).lower(), "month")
    match = _commission_match(since, until, company_id)
    pipeline = [
        {"$match": match},
        {"$addFields": {"_d": {"$toDate": "$fund_inflow_at"}}},
        {"$addFields": {"_bin": {"$dateTrunc": {"date": "$_d", "unit": unit, "startOfWeek": "mon"}}}},
        {"$group": {
            "_id": "$_bin",
            "commission": {"$sum": {"$cond": [_ACTIVE, {"$ifNull": ["$fund_inflow_amount", 0]}, 0]}},
            "reversed": {"$sum": {"$cond": [_ACTIVE, 0, {"$ifNull": ["$fund_inflow_amount", 0]}]}},
            "orders": {"$sum": {"$cond": [_ACTIVE, 1, 0]}},
        }},
        {"$sort": {"_id": 1}},
        {"$project": {
            "_id": 0,
            "label": {"$dateToString": {"date": "$_id", "format": "%Y-%m-%d"}},
            "commission_usdt": "$commission", "reversed_usdt": "$reversed", "orders": "$orders",
        }},
    ]
    rows = await db.redemptions.aggregate(pipeline).to_list(2000)
    for r in rows:
        r["commission_usdt"] = _round(r["commission_usdt"], 2)
        r["reversed_usdt"] = _round(r["reversed_usdt"], 2)
        r["orders"] = int(r["orders"] or 0)
    return {
        "currency": COMMISSION_CCY, "bucket": unit,
        "updated_at": now_utc().isoformat(),
        "filters": {"since": since, "until": until, "company_id": company_id},
        "rows": rows, "coverage": _coverage(),
    }


# ---------------------------------------------------------------------------
# EXPORTACIÓN CSV (FASE 2) — dataset COMPLETO (no sólo la página visible),
# con cabecera de metadatos (corte, moneda, filtros, cobertura). Misma
# autorización que las vistas (EST-13) y de solo lectura (EST-14).
# ---------------------------------------------------------------------------
def _csv_response(title: str, since, until, header: list, data_rows: list, filename: str):
    import csv
    import io
    from fastapi.responses import StreamingResponse

    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    w.writerow([f"Resilience - Estadisticas de empresas - {title}"])
    w.writerow(["Generado (corte UTC)", now_utc().isoformat()])
    w.writerow(["Moneda", COMMISSION_CCY])
    w.writerow(["Desde", since or "Todo", "Hasta", until or "Todo"])
    for n in _coverage()["notes"]:
        w.writerow(["Cobertura", n])
    w.writerow([])
    w.writerow(header)
    for row in data_rows:
        w.writerow(row)
    # BOM utf-8-sig para que Excel reconozca acentos.
    payload = buf.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(payload), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _ts_name() -> str:
    return now_utc().strftime("%Y%m%d_%H%M%S")


@router.get("/admin/company-stats/export/companies.csv")
async def export_companies_csv(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
) -> Any:
    await require_permission(request, PERM)
    rows = await _companies_agg(since, until)
    companies, unatt, totals = _split_rows(rows)
    total_comm = totals["commission"]
    companies.sort(key=lambda r: _round(r["commission"]), reverse=True)

    header = ["Empresa", "ID empresa", "Comision neta (USDT)", "Ventas brutas (USDT)",
              "Neto empresa (USDT)", "Operaciones", "Reversiones (USDT)",
              "Mov. revertidos", "Participacion %"]
    data = []
    for r in companies:
        comm = _round(r["commission"], 2)
        data.append([
            r.get("company") or "—", r["_id"], comm, _round(r["gross"], 2),
            _round(r["net_vendor"], 2), int(r["orders"] or 0),
            _round(r["reversed_commission"], 2), int(r["reversed_orders"] or 0),
            (_round(comm / total_comm * 100, 2) if total_comm > 0 else ""),
        ])
    if unatt["commission"] != 0 or unatt["orders"] != 0:
        data.append(["Sin atribuir", "", unatt["commission"], unatt["gross"], "",
                     unatt["orders"], unatt["reversed_commission"], "",
                     (_round(unatt["commission"] / total_comm * 100, 2) if total_comm > 0 else "")])
    data.append(["TOTAL", "", _round(totals["commission"], 2), _round(totals["gross"], 2),
                 "", totals["orders"], _round(totals["reversed_commission"], 2),
                 totals["reversed_orders"], "100" if total_comm > 0 else ""])
    return _csv_response("Empresas", since, until, header, data,
                         f"empresas_{_ts_name()}.csv")


@router.get("/admin/company-stats/export/products.csv")
async def export_products_csv(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
    kind: str = "products",
) -> Any:
    await require_permission(request, PERM)
    kind = "services" if str(kind).lower() == "services" else "products"
    rows = await _products_rows(since, until, kind)
    sort_field = "commission_usdt" if kind == "products" else "gross_usdt"
    rows.sort(key=lambda x: x.get(sort_field) or 0, reverse=True)

    label = "Servicio" if kind == "services" else "Producto"
    header = [label, "ID", "Empresa", "Cantidad", "Ventas brutas (USDT)",
              "Comision neta (USDT)", "Operaciones"]
    data = [[
        r["name"], r["id"], r["company"], r["quantity"], r["gross_usdt"],
        ("sin desglose" if r["commission_usdt"] is None else r["commission_usdt"]),
        r["orders"],
    ] for r in rows]
    title = "Servicios" if kind == "services" else "Productos"
    return _csv_response(title, since, until, header, data,
                         f"{kind}_{_ts_name()}.csv")


@router.get("/admin/company-stats/export/municipalities.csv")
async def export_municipalities_csv(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
) -> Any:
    await require_permission(request, PERM)
    rows, total = await _municipalities_rows(since, until)
    header = ["Provincia", "Municipio", "Municipio registrado", "Entregas completadas",
              "Participacion %", "Recaudacion (USDT)", "Parte propia (USDT)",
              "Pago mensajero (USDT)"]
    data = [[
        r["province"], r["municipality"], "si" if r["registered"] else "no",
        r["completed"], (r["share_pct"] if r["share_pct"] is not None else ""),
        r["fee_usdt"], r["platform_share_usdt"], r["courier_share_usdt"],
    ] for r in rows]
    data.append(["TOTAL", "", "", total, "100" if total > 0 else "", "", "", ""])
    return _csv_response("Mensajeria por municipio", since, until, header, data,
                         f"municipios_{_ts_name()}.csv")

