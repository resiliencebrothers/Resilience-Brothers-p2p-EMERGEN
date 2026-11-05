"""Estadísticas de empresas (Fondo de empresa > Ingresos).

Módulo de SOLO LECTURA. No crea, confirma, cancela ni recalcula operaciones;
no mueve saldos ni inventario.

CONTRATO DE DATOS (verificado):
  - Comisiones = `db.redemptions` (Marketplace Empresas):
      fund_inflow_amount / fund_inflow_at (fecha del ingreso financiero),
      fund_inflow_reversed_at (fecha de la reversión, si la hay),
      fund_inflow_currency (sólo USDT; None se trata como USDT),
      vendor_owner_id / vendor_owner_name (empresa; puede faltar → "Sin atribuir"),
      product_id / product_name / unit / quantity, total_usd (bruto),
      vendor_credit_net (neto liquidado a la empresa).
  - Servicios = `db.service_bookings` (status settled = completado).
  - Mensajería/municipios = `db.deliveries` (status delivered|confirmed =
      entrega realizada), province/municipality del destino, fee_usdt,
      platform_share_usdt (parte propia), courier_share_usdt (pago mensajero);
      si existen los importes *_paid_usdt (efectivos) se prefieren.

VISTA FINANCIERA vs ACTIVIDAD (EST-R01):
  - Un ingreso cuenta como POSITIVO en el período de `fund_inflow_at`.
  - Su reversión cuenta como NEGATIVO en el período de `fund_inflow_reversed_at`.
  - Comisión NETA del período = positivos(en fecha de ingreso) − negativos(en
    fecha de reversión). Una consulta histórica con corte NO incorpora
    reversiones posteriores a ese corte.
  - La actividad (ventas brutas, nº de operaciones) se cuenta por fecha de
    ingreso (fecha de pedido financiero).

ZONA HORARIA DE NEGOCIO (EST-R07): las fechas sin hora se interpretan como días
de `America/Havana` y se convierten a instantes UTC con intervalo medio-abierto
[inicio, fin+1día). Las comparaciones se hacen sobre fechas reales (no texto).
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from auth_utils import now_utc, require_permission
from db_client import db

router = APIRouter(tags=["Admin"])

PERM = "company_funds"
COMMISSION_CCY = "USDT"
BUSINESS_TZ_NAME = "America/Havana"
BUSINESS_TZ = ZoneInfo(BUSINESS_TZ_NAME)

_UNATTRIBUTED = "__unattributed__"
_DELIVERED = ["delivered", "confirmed"]  # entrega realizada (EST-R02)
_SERVICE_DONE = ["settled"]

# Comisión denominada en USDT (None se trata como USDT) — EST-R10.
_CCY_OK: Dict[str, Any] = {
    "$in": [{"$ifNull": ["$fund_inflow_currency", COMMISSION_CCY]}, [COMMISSION_CCY]],
}


# ---------------------------------------------------------------------------
# Fechas: día de negocio → instante UTC; comparación por fecha real (EST-R07)
# ---------------------------------------------------------------------------
def _parse_bound(s: Optional[str], is_end: bool) -> Optional[datetime]:
    """Convierte un límite (fecha o fecha-hora ISO) a un `datetime` UTC.

    - Fecha `YYYY-MM-DD`: se interpreta como día de negocio (America/Havana).
      `since` → medianoche de ese día (inclusive); `until` → medianoche del día
      SIGUIENTE (exclusive), para un intervalo medio-abierto estable.
    - Fecha-hora ISO (con 'T'): se usa el instante tal cual.
    Devuelve None si vacío; 400 si es inválida."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        d = datetime.fromisoformat(s).date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Fecha inválida: {s}")
    local = datetime(d.year, d.month, d.day, tzinfo=BUSINESS_TZ)
    if is_end:
        local = local + timedelta(days=1)  # fin siguiente excluido
    return local.astimezone(timezone.utc)


def _window(since: Optional[str], until: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    lo = _parse_bound(since, False)
    hi = _parse_bound(until, True)
    if lo is not None and hi is not None and lo >= hi:
        raise HTTPException(status_code=400, detail="Rango de fechas inválido: 'desde' debe ser ≤ 'hasta'.")
    return lo, hi


def _win(field: str, lo: Optional[datetime], hi: Optional[datetime]) -> Dict[str, Any]:
    """Expresión booleana: `field` (string/fecha) cae dentro de [lo, hi).
    Convierte a fecha real (tolera null/''/offset/precisión). Si no hay límites,
    exige que el campo exista como fecha."""
    conv = {"$convert": {"input": f"${field}", "to": "date", "onError": None, "onNull": None}}
    conds: List[Dict[str, Any]] = [{"$ne": [conv, None]}]
    if lo is not None:
        conds.append({"$gte": [conv, lo]})
    if hi is not None:
        conds.append({"$lt": [conv, hi]})
    return {"$and": conds}


def _round(x: Any, p: int = 2) -> float:
    return round(float(x or 0), p)


def _company_filter(company_id: Optional[str]) -> Dict[str, Any]:
    if company_id and str(company_id).strip():
        return {"vendor_owner_id": str(company_id).strip()}
    return {}


# ---------------------------------------------------------------------------
# Comisiones por empresa — vista financiera (positivos por ingreso, negativos
# por reversión), EST-R01. Sin límite de grupos (EST-R03).
# ---------------------------------------------------------------------------
async def _companies_agg(
    since: Optional[str], until: Optional[str], company_id: Optional[str] = None,
) -> List[dict]:
    lo, hi = _window(since, until)
    win_in = _win("fund_inflow_at", lo, hi)
    win_rev = _win("fund_inflow_reversed_at", lo, hi)
    amount = {"$ifNull": ["$fund_inflow_amount", 0]}
    gross = {"$ifNull": ["$total_usd", 0]}
    net_vendor = {"$ifNull": ["$vendor_credit_net", 0]}
    match: Dict[str, Any] = {"$expr": {"$and": [_CCY_OK, {"$or": [win_in, win_rev]}]}}
    match.update(_company_filter(company_id))
    group_id = {"$cond": [
        {"$in": [{"$ifNull": ["$vendor_owner_id", ""]}, ["", None]]},
        _UNATTRIBUTED, "$vendor_owner_id",
    ]}
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": group_id,
            "company": {"$first": "$vendor_owner_name"},
            "gross": {"$sum": {"$cond": [win_in, gross, 0]}},
            "pos": {"$sum": {"$cond": [win_in, amount, 0]}},
            "neg": {"$sum": {"$cond": [win_rev, amount, 0]}},
            "net_vendor": {"$sum": {"$cond": [win_in, net_vendor, 0]}},
            "orders": {"$sum": {"$cond": [win_in, 1, 0]}},
            "reversed_orders": {"$sum": {"$cond": [win_rev, 1, 0]}},
        }},
    ]
    rows = await db.redemptions.aggregate(pipeline).to_list(None)
    for r in rows:
        r["net"] = _round(r.get("pos")) - _round(r.get("neg"))
    return rows


async def _eligible_total(
    since: Optional[str], until: Optional[str], company_id: Optional[str] = None,
) -> float:
    """Total NETO elegible calculado de forma INDEPENDIENTE del desglose por
    empresa (sin agrupar), para contrastar el cuadre (EST-R04)."""
    lo, hi = _window(since, until)
    win_in = _win("fund_inflow_at", lo, hi)
    win_rev = _win("fund_inflow_reversed_at", lo, hi)
    amount = {"$ifNull": ["$fund_inflow_amount", 0]}
    match: Dict[str, Any] = {"$expr": {"$and": [_CCY_OK, {"$or": [win_in, win_rev]}]}}
    match.update(_company_filter(company_id))
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "pos": {"$sum": {"$cond": [win_in, amount, 0]}},
            "neg": {"$sum": {"$cond": [win_rev, amount, 0]}},
        }},
    ]
    agg = await db.redemptions.aggregate(pipeline).to_list(1)
    g = agg[0] if agg else {}
    return _round(_round(g.get("pos")) - _round(g.get("neg")))


def _split_rows(rows: List[dict]) -> Tuple[List[dict], dict, dict]:
    companies: List[dict] = []
    unattributed: Optional[dict] = None
    for r in rows:
        if r["_id"] == _UNATTRIBUTED:
            unattributed = r
        else:
            companies.append(r)
    totals = {
        "commission": _round(sum(r["net"] for r in rows)),
        "reversed_commission": _round(sum(_round(r["neg"]) for r in rows)),
        "reversed_orders": sum(int(r.get("reversed_orders") or 0) for r in rows),
        "gross": _round(sum(_round(r["gross"]) for r in rows)),
        "orders": sum(int(r.get("orders") or 0) for r in rows),
    }
    unatt = {
        "commission": _round(unattributed["net"]) if unattributed else 0.0,
        "reversed_commission": _round(unattributed["neg"]) if unattributed else 0.0,
        "reversed_orders": int(unattributed.get("reversed_orders") or 0) if unattributed else 0,
        "orders": int(unattributed.get("orders") or 0) if unattributed else 0,
        "gross": _round(unattributed["gross"]) if unattributed else 0.0,
    }
    return companies, unatt, totals


# ---------------------------------------------------------------------------
# Mensajería y servicios (entrega realizada = delivered|confirmed), EST-R02.
# ---------------------------------------------------------------------------
def _paid(planned: str, paid: str) -> Dict[str, Any]:
    """Importe efectivo si existe (*_paid_usdt), si no el previsto."""
    return {"$ifNull": [f"${paid}", {"$ifNull": [f"${planned}", 0]}]}


async def _deliveries_summary(since: Optional[str], until: Optional[str]) -> dict:
    lo, hi = _window(since, until)
    match = {"status": {"$in": _DELIVERED}, "$expr": _win("updated_at", lo, hi)}
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "completed": {"$sum": 1},
            "fee": {"$sum": _paid("fee_usdt", "fee_paid_usdt")},
            "platform_share": {"$sum": _paid("platform_share_usdt", "platform_share_paid_usdt")},
            "courier_share": {"$sum": _paid("courier_share_usdt", "courier_share_paid_usdt")},
        }},
    ]
    agg = await db.deliveries.aggregate(pipeline).to_list(1)
    g = agg[0] if agg else {}
    return {
        "completed": int(g.get("completed") or 0),
        "fee_usdt": _round(g.get("fee")),
        "platform_share_usdt": _round(g.get("platform_share")),
        "courier_share_usdt": _round(g.get("courier_share")),
    }


async def _services_summary(since: Optional[str], until: Optional[str]) -> dict:
    lo, hi = _window(since, until)
    match = {"status": {"$in": _SERVICE_DONE}, "$expr": _win("updated_at", lo, hi)}
    pipeline = [
        {"$match": match},
        {"$group": {"_id": None, "completed": {"$sum": 1},
                    "amount": {"$sum": {"$ifNull": ["$amount_usdt", 0]}}}},
    ]
    agg = await db.service_bookings.aggregate(pipeline).to_list(1)
    g = agg[0] if agg else {}
    return {"completed": int(g.get("completed") or 0), "amount_usdt": _round(g.get("amount"))}


async def _products_rows(
    since: Optional[str], until: Optional[str], kind: str, company_id: Optional[str] = None,
) -> List[dict]:
    """Filas de productos/servicios (sin orden ni límite) — reutilizado por el
    endpoint JSON y la exportación CSV para que coincidan (EST-R03/EST-11)."""
    lo, hi = _window(since, until)
    if kind == "products":
        win_in = _win("fund_inflow_at", lo, hi)
        win_rev = _win("fund_inflow_reversed_at", lo, hi)
        amount = {"$ifNull": ["$fund_inflow_amount", 0]}
        match: Dict[str, Any] = {"$expr": {"$and": [_CCY_OK, {"$or": [win_in, win_rev]}]}}
        match.update(_company_filter(company_id))
        pipeline = [
            {"$match": match},
            {"$group": {
                "_id": "$product_id",
                "product": {"$first": "$product_name"},
                "unit": {"$first": "$unit"},
                "company": {"$first": "$vendor_owner_name"},
                "company_id": {"$first": "$vendor_owner_id"},
                "quantity": {"$sum": {"$cond": [win_in, {"$ifNull": ["$quantity", 0]}, 0]}},
                "gross_usdt": {"$sum": {"$cond": [win_in, {"$ifNull": ["$total_usd", 0]}, 0]}},
                "pos": {"$sum": {"$cond": [win_in, amount, 0]}},
                "neg": {"$sum": {"$cond": [win_rev, amount, 0]}},
                "orders": {"$sum": {"$cond": [win_in, 1, 0]}},
            }},
        ]
        rows = await db.redemptions.aggregate(pipeline).to_list(None)
        return [{
            "id": r["_id"] or "—",
            "name": r.get("product") or "—",
            "unit": r.get("unit") or "unidad",
            "company": r.get("company") or "Sin atribuir",
            "company_id": r.get("company_id") or "",
            "quantity": _round(r["quantity"]),
            "gross_usdt": _round(r["gross_usdt"]),
            "commission_usdt": _round(_round(r["pos"]) - _round(r["neg"])),
            "orders": int(r["orders"] or 0),
        } for r in rows]
    smatch: Dict[str, Any] = {"status": {"$in": _SERVICE_DONE}, "$expr": _win("updated_at", lo, hi)}
    if company_id and str(company_id).strip():
        smatch["company_id"] = str(company_id).strip()
    pipeline = [
        {"$match": smatch},
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
    rows = await db.service_bookings.aggregate(pipeline).to_list(None)
    return [{
        "id": r["_id"] or "—",
        "name": r.get("name") or "—",
        "unit": "",
        "company": r.get("company") or "—",
        "company_id": r.get("company_id") or "",
        "quantity": _round(r["quantity"]),
        "gross_usdt": _round(r["gross_usdt"]),
        "commission_usdt": None,  # servicios: comisión no atribuible
        "orders": int(r["orders"] or 0),
    } for r in rows]


async def _municipalities_rows(
    since: Optional[str], until: Optional[str],
) -> Tuple[List[dict], int]:
    lo, hi = _window(since, until)
    match = {"status": {"$in": _DELIVERED}, "$expr": _win("updated_at", lo, hi)}
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {
                "province": {"$ifNull": ["$province", ""]},
                "municipality": {"$ifNull": ["$municipality", ""]},
            },
            "completed": {"$sum": 1},
            "fee_usdt": {"$sum": _paid("fee_usdt", "fee_paid_usdt")},
            "platform_share_usdt": {"$sum": _paid("platform_share_usdt", "platform_share_paid_usdt")},
            "courier_share_usdt": {"$sum": _paid("courier_share_usdt", "courier_share_paid_usdt")},
        }},
    ]
    rows = await db.deliveries.aggregate(pipeline).to_list(None)
    total = sum(int(r["completed"] or 0) for r in rows)
    out: List[dict] = []
    for r in rows:
        prov = (r["_id"].get("province") or "").strip()
        muni = (r["_id"].get("municipality") or "").strip()
        completed = int(r["completed"] or 0)
        out.append({
            "province": prov or "—",
            "municipality": muni or "Municipio no registrado",
            "registered": bool(muni),
            "completed": completed,
            "fee_usdt": _round(r["fee_usdt"]),
            "platform_share_usdt": _round(r["platform_share_usdt"]),
            "courier_share_usdt": _round(r["courier_share_usdt"]),
            "share_pct": (_round(completed / total * 100) if total > 0 else None),
        })
    out.sort(key=lambda x: x["completed"], reverse=True)
    return out, total


# ---------------------------------------------------------------------------
# Comparativa / concentración (EST-R05: la comparativa respeta company_id)
# ---------------------------------------------------------------------------
def _previous_range(since: Optional[str], until: Optional[str]) -> Optional[dict]:
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


async def _comparison_block(
    since: Optional[str], until: Optional[str], current_net: float,
    company_id: Optional[str] = None,
) -> Optional[dict]:
    prev = _previous_range(since, until)
    if not prev:
        return None
    # EST-R05 — el período anterior se filtra por la MISMA empresa.
    prev_net = await _eligible_total(prev["since"], prev["until"], company_id)
    delta = _round(current_net - prev_net)
    return {
        "previous_since": prev["since"], "previous_until": prev["until"],
        "previous_net_commission_usdt": prev_net,
        "delta_usdt": delta,
        "delta_pct": (_round(delta / prev_net * 100) if prev_net > 0 else None),
    }


def _concentration_block(companies: List[dict], total: float) -> Optional[dict]:
    if total <= 0 or not companies:
        return None
    comms = sorted((_round(c["net"]) for c in companies), reverse=True)
    return {
        "top5_share_pct": _round(sum(comms[:5]) / total * 100),
        "top10_share_pct": _round(sum(comms[:10]) / total * 100),
        "companies_count": len(companies),
    }


def _coverage(company_id: Optional[str] = None) -> dict:
    notes = [
        f"Zona horaria de negocio: {BUSINESS_TZ_NAME}. Las fechas sin hora son días de esa zona.",
        "Comisiones denominadas en USDT (otras monedas se excluyen).",
        "Vista financiera: ingresos por fecha de ingreso; reversiones por su fecha de reversión.",
        "Entrega realizada = status 'delivered' o 'confirmed'; su fecha usa updated_at (mejor dato disponible, puede variar al confirmar).",
        "Importes de mensajería: se usa el importe efectivo (*_paid) si existe; si no, el previsto.",
        "Comisiones sin empresa identificable se muestran como 'Sin atribuir'.",
        "Entregas sin municipio fiable se agrupan en 'Municipio no registrado'.",
        "Totales calculados sobre el conjunto completo; el ranking visible se pagina (offset/limit).",
        "Pendiente: detalle navegable por operación y desglose por tienda.",
    ]
    if company_id and str(company_id).strip():
        notes.append("Filtro por empresa: comisiones/productos filtrados; mensajería y servicios se muestran GLOBALES (sin vínculo fiable empresa→entrega).")
    return {
        "currency": COMMISSION_CCY,
        "business_timezone": BUSINESS_TZ_NAME,
        "commission_date_field": "fund_inflow_at (+ fund_inflow_reversed_at para reversiones)",
        "delivery_date_field": "updated_at (status delivered|confirmed)",
        "notes": notes,
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
    scoped = bool(company_id and str(company_id).strip())
    # EST-R05 — mensajería/servicios NO tienen vínculo fiable con la empresa:
    # se muestran globales y se marca el ámbito (no se presentan como filtrados).
    deliveries = await _deliveries_summary(since, until)
    services = await _services_summary(since, until)

    companies_contributing = sum(1 for r in companies if _round(r["net"]) > 0)
    companies_sum = _round(sum(_round(r["net"]) for r in companies))
    net_total = _round(totals["commission"])
    comparison = await _comparison_block(since, until, net_total, company_id)
    # EST-R05 — la concentración entre empresas no aplica si se filtra a una sola.
    concentration = None if scoped else _concentration_block(companies, net_total)

    # EST-R04 — cuadre contra un total elegible INDEPENDIENTE (sin agrupar).
    independent_total = await _eligible_total(since, until, company_id)
    distributed = _round(companies_sum + _round(unatt["commission"]))
    balanced = abs(distributed - independent_total) < 0.01

    return {
        "currency": COMMISSION_CCY,
        "business_timezone": BUSINESS_TZ_NAME,
        "updated_at": now_utc().isoformat(),
        "filters": {"since": since, "until": until, "company_id": company_id},
        "economic": {
            "net_commission_usdt": net_total,
            "reversed_commission_usdt": _round(totals["reversed_commission"]),
            "reversed_count": totals["reversed_orders"],
            "messaging_own_income_usdt": deliveries["platform_share_usdt"],
            "unattributed_commission_usdt": _round(unatt["commission"]),
        },
        "operational": {
            "gross_sales_usdt": _round(totals["gross"]),
            "orders_completed": totals["orders"],
            "deliveries_completed": deliveries["completed"],
            "services_completed": services["completed"],
            "companies_contributing": companies_contributing,
        },
        "messaging": {
            "scope": "global" if scoped else "all",
            "fee_collected_usdt": deliveries["fee_usdt"],
            "platform_share_usdt": deliveries["platform_share_usdt"],
            "courier_share_usdt": deliveries["courier_share_usdt"],
        },
        # Comprobación de DISTRIBUCIÓN (no es evidencia de cuadre contable):
        # el desglose debe reconstruir el total elegible independiente.
        "reconciliation": {
            "check_type": "distribution",
            "companies_commission_usdt": companies_sum,
            "unattributed_commission_usdt": _round(unatt["commission"]),
            "distributed_commission_usdt": distributed,
            "independent_total_eligible_usdt": independent_total,
            "total_eligible_commission_usdt": independent_total,
            "balanced": balanced,
        },
        "comparison": comparison,
        "concentration": concentration,
        "coverage": _coverage(company_id),
    }


# ---------------------------------------------------------------------------
# 2) EMPRESAS — ranking por comisión neta
# ---------------------------------------------------------------------------
@router.get("/admin/company-stats/companies")
async def company_stats_companies(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
    limit: int = 50, offset: int = 0, sort: str = "commission",
    company_id: Optional[str] = None,
) -> Any:
    await require_permission(request, PERM)
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    rows = await _companies_agg(since, until, company_id)
    companies, unatt, totals = _split_rows(rows)

    total_comm = totals["commission"]
    out: List[dict] = []
    for r in companies:
        comm = _round(r["net"])
        out.append({
            "company_id": r["_id"],
            "company": r.get("company") or "—",
            "commission_usdt": comm,
            "gross_usdt": _round(r["gross"]),
            "net_vendor_usdt": _round(r["net_vendor"]),
            "orders": int(r["orders"] or 0),
            "reversed_commission_usdt": _round(r["neg"]),
            "reversed_orders": int(r.get("reversed_orders") or 0),
            "share_pct": (_round(comm / total_comm * 100) if total_comm > 0 else None),
        })
    sort_field = {"commission": "commission_usdt", "gross": "gross_usdt",
                  "orders": "orders"}.get(sort, "commission_usdt")
    out.sort(key=lambda x: x.get(sort_field) or 0, reverse=True)
    window = out[offset:offset + limit]

    return {
        "currency": COMMISSION_CCY,
        "updated_at": now_utc().isoformat(),
        "rows": window,
        "shown": len(window),
        "offset": offset,
        "total_companies": len(out),
        "unattributed": {
            "commission_usdt": _round(unatt["commission"]),
            "gross_usdt": _round(unatt["gross"]),
            "orders": unatt["orders"],
            "reversed_commission_usdt": _round(unatt["reversed_commission"]),
            "reversed_orders": unatt["reversed_orders"],
            "share_pct": (_round(unatt["commission"] / total_comm * 100) if total_comm > 0 else None),
        },
        "totals": {
            "commission_usdt": _round(totals["commission"]),
            "gross_usdt": _round(totals["gross"]),
            "reversed_commission_usdt": _round(totals["reversed_commission"]),
        },
        "coverage": _coverage(company_id),
    }


# ---------------------------------------------------------------------------
# 3) PRODUCTOS Y SERVICIOS
# ---------------------------------------------------------------------------
@router.get("/admin/company-stats/products")
async def company_stats_products(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
    kind: str = "products", limit: int = 50, offset: int = 0, sort: str = "commission",
    company_id: Optional[str] = None,
) -> Any:
    await require_permission(request, PERM)
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    kind = "services" if str(kind).lower() == "services" else "products"
    out = await _products_rows(since, until, kind, company_id)
    if kind == "products":
        sort_field = {"quantity": "quantity", "gross": "gross_usdt",
                      "commission": "commission_usdt"}.get(sort, "commission_usdt")
    else:
        # Servicios: la comisión no es atribuible; cantidad y ventas sí son calculables.
        sort_field = {"quantity": "quantity", "gross": "gross_usdt"}.get(sort, "gross_usdt")
    out.sort(key=lambda x: x.get(sort_field) or 0, reverse=True)
    window = out[offset:offset + limit]
    return {
        "currency": COMMISSION_CCY,
        "kind": kind,
        "updated_at": now_utc().isoformat(),
        "rows": window,
        "shown": len(window),
        "offset": offset,
        "total": len(out),
        "sort_applied": sort_field,
        "coverage": _coverage(company_id),
    }


# ---------------------------------------------------------------------------
# 4) MENSAJERÍA Y MUNICIPIOS
# ---------------------------------------------------------------------------
@router.get("/admin/company-stats/municipalities")
async def company_stats_municipalities(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
    limit: int = 50, offset: int = 0,
) -> Any:
    await require_permission(request, PERM)
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    out, total_completed = await _municipalities_rows(since, until)
    window = out[offset:offset + limit]

    return {
        "currency": COMMISSION_CCY,
        "updated_at": now_utc().isoformat(),
        "rows": window,
        "shown": len(window),
        "offset": offset,
        "total_municipalities": len(out),
        "total_completed": total_completed,
        "coverage": _coverage(),
    }


# ---------------------------------------------------------------------------
# 5) TENDENCIA — positivos por fecha de ingreso, negativos por reversión (R01)
# ---------------------------------------------------------------------------
async def _trend_side(
    date_field: str, since: Optional[str], until: Optional[str],
    unit: str, company_id: Optional[str],
) -> Dict[str, dict]:
    """Agrega comisión por bucket usando `date_field` como fecha efectiva."""
    lo, hi = _window(since, until)
    amount = {"$ifNull": ["$fund_inflow_amount", 0]}
    match: Dict[str, Any] = {"$expr": {"$and": [_CCY_OK, _win(date_field, lo, hi)]}}
    match.update(_company_filter(company_id))
    conv = {"$convert": {"input": f"${date_field}", "to": "date", "onError": None, "onNull": None}}
    pipeline = [
        {"$match": match},
        {"$addFields": {"_bin": {"$dateTrunc": {
            "date": conv, "unit": unit, "startOfWeek": "mon", "timezone": BUSINESS_TZ_NAME}}}},
        {"$group": {"_id": "$_bin", "amount": {"$sum": amount}, "orders": {"$sum": 1}}},
        {"$project": {"_id": 0,
                      "label": {"$dateToString": {"date": "$_id", "format": "%Y-%m-%d",
                                                  "timezone": BUSINESS_TZ_NAME}},
                      "amount": "$amount", "orders": "$orders"}},
    ]
    rows = await db.redemptions.aggregate(pipeline).to_list(None)
    return {r["label"]: r for r in rows}


@router.get("/admin/company-stats/trend")
async def company_stats_trend(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
    bucket: str = "month", company_id: Optional[str] = None,
) -> Any:
    await require_permission(request, PERM)
    unit = {"day": "day", "week": "week", "month": "month"}.get(str(bucket).lower(), "month")
    pos = await _trend_side("fund_inflow_at", since, until, unit, company_id)
    neg = await _trend_side("fund_inflow_reversed_at", since, until, unit, company_id)
    labels = sorted(set(pos) | set(neg))
    rows = []
    for lb in labels:
        p = pos.get(lb, {})
        n = neg.get(lb, {})
        commission = _round(_round(p.get("amount")) - _round(n.get("amount")))
        rows.append({
            "label": lb,
            "commission_usdt": commission,
            "reversed_usdt": _round(n.get("amount")),
            "orders": int(p.get("orders") or 0),
        })
    return {
        "currency": COMMISSION_CCY, "bucket": unit,
        "business_timezone": BUSINESS_TZ_NAME,
        "updated_at": now_utc().isoformat(),
        "filters": {"since": since, "until": until, "company_id": company_id},
        "rows": rows, "coverage": _coverage(company_id),
    }


# ---------------------------------------------------------------------------
# EXPORTACIÓN CSV — dataset COMPLETO (no sólo la página), con metadatos.
# Misma autorización que las vistas (EST-13) y de solo lectura (EST-14).
# ---------------------------------------------------------------------------
def _csv_response(
    title: str, since: Optional[str], until: Optional[str],
    header: List[Any], data_rows: List[List[Any]], filename: str,
) -> Any:
    import csv
    import io
    from fastapi.responses import StreamingResponse

    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    w.writerow([f"Resilience - Estadisticas de empresas - {title}"])
    w.writerow(["Generado (hora de generacion UTC)", now_utc().isoformat()])
    w.writerow(["Zona horaria de negocio", BUSINESS_TZ_NAME])
    w.writerow(["Moneda", COMMISSION_CCY])
    w.writerow(["Desde", since or "Todo", "Hasta", until or "Todo"])
    for n in _coverage()["notes"]:
        w.writerow(["Cobertura", n])
    w.writerow([])
    w.writerow(header)
    for row in data_rows:
        w.writerow(row)
    payload = buf.getvalue().encode("utf-8-sig")  # BOM para Excel
    return StreamingResponse(
        io.BytesIO(payload), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _ts_name() -> str:
    return now_utc().strftime("%Y%m%d_%H%M%S")


@router.get("/admin/company-stats/export/companies.csv")
async def export_companies_csv(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
    company_id: Optional[str] = None,
) -> Any:
    await require_permission(request, PERM)
    rows = await _companies_agg(since, until, company_id)
    companies, unatt, totals = _split_rows(rows)
    total_comm = totals["commission"]
    companies.sort(key=lambda r: _round(r["net"]), reverse=True)

    header = ["Empresa", "ID empresa", "Comision neta (USDT)", "Ventas brutas (USDT)",
              "Neto empresa (USDT)", "Operaciones", "Reversiones (USDT)",
              "Mov. revertidos", "Participacion %"]
    data: List[List[Any]] = []
    for r in companies:
        comm = _round(r["net"])
        data.append([
            r.get("company") or "—", r["_id"], comm, _round(r["gross"]),
            _round(r["net_vendor"]), int(r["orders"] or 0),
            _round(r["neg"]), int(r.get("reversed_orders") or 0),
            (_round(comm / total_comm * 100) if total_comm > 0 else ""),
        ])
    # EST-R08 — incluir la fila "Sin atribuir" también cuando SÓLO tiene
    # reversiones (comisión/órdenes activas en 0 pero reversión > 0).
    if (unatt["commission"] != 0 or unatt["orders"] != 0
            or unatt["reversed_commission"] != 0 or unatt["reversed_orders"] != 0):
        data.append(["Sin atribuir", "", _round(unatt["commission"]), _round(unatt["gross"]), "",
                     unatt["orders"], _round(unatt["reversed_commission"]), unatt["reversed_orders"],
                     (_round(unatt["commission"] / total_comm * 100) if total_comm > 0 else "")])
    data.append(["TOTAL", "", _round(totals["commission"]), _round(totals["gross"]),
                 "", totals["orders"], _round(totals["reversed_commission"]),
                 totals["reversed_orders"], "100" if total_comm > 0 else ""])
    return _csv_response("Empresas", since, until, header, data,
                         f"empresas_{_ts_name()}.csv")


@router.get("/admin/company-stats/export/products.csv")
async def export_products_csv(
    request: Request, since: Optional[str] = None, until: Optional[str] = None,
    kind: str = "products", company_id: Optional[str] = None,
) -> Any:
    await require_permission(request, PERM)
    kind = "services" if str(kind).lower() == "services" else "products"
    rows = await _products_rows(since, until, kind, company_id)
    sort_field = "commission_usdt" if kind == "products" else "gross_usdt"
    rows.sort(key=lambda x: x.get(sort_field) or 0, reverse=True)

    label = "Servicio" if kind == "services" else "Producto"
    header = [label, "ID", "Unidad", "Empresa", "Cantidad", "Ventas brutas (USDT)",
              "Comision neta (USDT)", "Operaciones"]
    data = [[
        r["name"], r["id"], r.get("unit") or "", r["company"], r["quantity"], r["gross_usdt"],
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
