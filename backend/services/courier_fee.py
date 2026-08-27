"""iter198 — courier fee engine for cash withdrawals AND marketplace deliveries.

Business rules (operator PDF, Ago 2026):
- Fixed origin: the Resilience Brothers office (address + lat/lon in settings).
- fee = MAX(minimum_delivery_fee, route_km × price_per_km)   [USDT]
- Initial tariffs: 0.50 USDT/km, minimum 2.00 USDT (covers first 4 km).
- FREE when the operation's USDT equivalent ≥ `courier_free_min_usdt` (1000).
- Fee is deducted from the client's balance SEPARATELY from the amount.
- Km are never rounded before the calculation; money shown with 2 decimals.
- All tariffs configurable from the admin panel; each charge stores a
  tariff snapshot so later changes never rewrite history.
"""
from typing import Optional

from fastapi import HTTPException

from db_client import db
from services.balances import build_rate_lookup, convert_to_usdt, convert_from_usdt

DEFAULT_RATE_USDT_PER_KM = 0.50
DEFAULT_MIN_FEE_USDT = 2.00
DEFAULT_FREE_MIN_USDT = 1000.0


async def get_courier_config() -> dict:
    doc = await db.settings.find_one(
        {"id": "global"},
        {"_id": 0, "courier_rate_usdt_per_km": 1, "courier_free_min_usdt": 1,
         "courier_min_fee_usdt": 1, "office_latitude": 1, "office_longitude": 1},
    ) or {}
    raw_rate = doc.get("courier_rate_usdt_per_km")
    raw_min_fee = doc.get("courier_min_fee_usdt")
    raw_free = doc.get("courier_free_min_usdt")
    return {
        "rate_usdt_per_km": float(raw_rate) if raw_rate is not None else DEFAULT_RATE_USDT_PER_KM,
        "min_fee_usdt": float(raw_min_fee) if raw_min_fee is not None else DEFAULT_MIN_FEE_USDT,
        "free_min_usdt": float(raw_free) if raw_free is not None else DEFAULT_FREE_MIN_USDT,
        "office_lat": doc.get("office_latitude"),
        "office_lon": doc.get("office_longitude"),
    }


def compute_fee_usdt(km: float, rate: float, min_fee: float) -> float:
    """MAX(minimum, km × rate) — 0 km means no charge at all."""
    if km <= 0 or rate <= 0:
        return 0.0
    return round(max(min_fee, km * rate), 2)


async def quote_courier_fee(currency: str, amount: float) -> dict:
    """Tariff + free-threshold preview for a (currency, amount) operation."""
    cfg = await get_courier_config()
    rates = await build_rate_lookup()
    code = (currency or "USD").upper()
    amt = float(amount or 0.0)
    usdt_eq = convert_to_usdt(amt, code, rates)
    per_usdt = convert_from_usdt(1.0, code, rates)
    free = bool(usdt_eq is not None and cfg["free_min_usdt"] > 0
                and usdt_eq >= cfg["free_min_usdt"])
    return {
        "rate_usdt_per_km": cfg["rate_usdt_per_km"],
        "min_fee_usdt": cfg["min_fee_usdt"],
        "free_min_usdt": cfg["free_min_usdt"],
        "enabled": cfg["rate_usdt_per_km"] > 0,
        "currency": code,
        "amount": amt,
        "usdt_equivalent": round(usdt_eq, 2) if usdt_eq is not None else None,
        "currency_per_usdt": round(per_usdt, 4) if per_usdt is not None else None,
        "free": free,
    }


async def fee_in_currency(fee_usdt: float, currency: str) -> Optional[float]:
    """Convert a USDT fee into the operation currency. None if no rate path."""
    rates = await build_rate_lookup()
    v = convert_from_usdt(float(fee_usdt), (currency or "USD").upper(), rates)
    return None if v is None else round(float(v), 2)


def parse_km_payload(payload: dict) -> float:
    """Staff-provided km: required, numeric, 0–5000 (0 = annul the charge)."""
    raw_km = payload.get("km")
    if raw_km is None:
        raise HTTPException(status_code=400, detail="km requerido")
    try:
        km = round(float(raw_km), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="km inválido")
    if km < 0 or km > 5000:
        raise HTTPException(status_code=400, detail="km fuera de rango (0-5000)")
    return km


async def price_charge_or_raise(km: float, currency: str, amount: float,
                                *, op_label: str) -> tuple:
    """Shared guards + pricing for staff courier charges (cash withdrawals
    and marketplace redemptions). Returns (quote, fee_usdt, fee_in_currency)."""
    q = await quote_courier_fee(currency, amount)
    if km > 0:
        if not q["enabled"]:
            raise HTTPException(
                status_code=422,
                detail="Tarifa de mensajería no configurada. Configúrala en Resumen → Alertas y configuración.")
        if q["free"]:
            raise HTTPException(
                status_code=400,
                detail=(f"{op_label} equivale a {q['usdt_equivalent']} USDT "
                        f"(≥ {q['free_min_usdt']}): la mensajería es GRATIS y no debe cobrarse."))
    fee = compute_fee_usdt(km, q["rate_usdt_per_km"], q["min_fee_usdt"])
    fee_cur = 0.0
    if fee > 0:
        converted = await fee_in_currency(fee, q["currency"])
        if converted is None:
            raise HTTPException(
                status_code=422,
                detail=f"No hay tasa configurada para convertir USDT → {q['currency']}.")
        fee_cur = converted
    return q, fee, fee_cur


async def route_quote(lat: float, lon: float, currency: str, amount: float) -> dict:
    """Full automatic quote: office → (lat, lon) road distance + fee.
    Backend is the pricing authority — clients never send km or prices."""
    q = await quote_courier_fee(currency, amount)
    cfg = await get_courier_config()
    base = {**q, "km": None, "fee_usdt": 0.0, "fee_currency_amount": 0.0,
            "requires_manual_review": False, "reason": None}
    if q["free"]:
        return base
    if not q["enabled"]:
        return base
    if cfg["office_lat"] is None or cfg["office_lon"] is None:
        return {**base, "requires_manual_review": True, "reason": "office_not_configured"}
    try:
        from services.geo_routing import route_km
        km = await route_km(float(cfg["office_lat"]), float(cfg["office_lon"]),
                            float(lat), float(lon))
    except Exception:
        km = None
    if km is None:
        return {**base, "requires_manual_review": True, "reason": "route_failed"}
    fee_usdt = compute_fee_usdt(km, q["rate_usdt_per_km"], q["min_fee_usdt"])
    fee_cur = await fee_in_currency(fee_usdt, q["currency"])
    if fee_cur is None:
        return {**base, "requires_manual_review": True, "reason": "no_rate"}
    return {**base, "km": round(km, 2), "fee_usdt": fee_usdt,
            "fee_currency_amount": fee_cur}


async def municipality_fallback_quote(address_text: str, currency: str,
                                      amount: float,
                                      municipality_key: Optional[str] = None) -> Optional[dict]:
    """iter211 — Tarifa fija por municipio detectado en el texto de la
    dirección. Se usa cuando el mapa no logró ubicar al cliente.
    iter212 — `municipality_key`: elección explícita del cliente (selector);
    gana sobre la detección por texto.
    None si no hay coincidencia (→ queda en revisión manual)."""
    from services.municipality_rates import match_municipality, get_rate_by_key
    m = None
    if municipality_key:
        m = await get_rate_by_key(municipality_key)
    if not m:
        m = await match_municipality(address_text or "")
    if not m:
        return None
    q = await quote_courier_fee(currency, amount)
    base = {**q, "km": 0.0, "fee_usdt": 0.0, "fee_currency_amount": 0.0,
            "requires_manual_review": False, "reason": None,
            "municipality": m["municipality"],
            "municipality_price_usdt": round(float(m["price_usdt"]), 2)}
    if q["free"] or not q["enabled"]:
        return base
    fee_usdt = round(float(m["price_usdt"]), 2)
    fee_cur = await fee_in_currency(fee_usdt, q["currency"])
    if fee_cur is None:
        return None
    return {**base, "fee_usdt": fee_usdt, "fee_currency_amount": fee_cur}


async def price_charge_municipality_or_raise(muni_key: str, currency: str,
                                             amount: float, *,
                                             op_label: str) -> tuple:
    """iter211 — cobro staff por tarifa fija de municipio.
    Returns (quote, fee_usdt, fee_in_currency, muni_doc)."""
    from services.municipality_rates import get_rate_by_key
    m = await get_rate_by_key(muni_key)
    if not m:
        raise HTTPException(
            status_code=404,
            detail="Municipio no encontrado en la tabla de tarifas.")
    q = await quote_courier_fee(currency, amount)
    if q["free"]:
        raise HTTPException(
            status_code=400,
            detail=(f"{op_label} equivale a {q['usdt_equivalent']} USDT "
                    f"(≥ {q['free_min_usdt']}): la mensajería es GRATIS y no debe cobrarse."))
    fee = round(float(m["price_usdt"]), 2)
    converted = await fee_in_currency(fee, q["currency"])
    if converted is None:
        raise HTTPException(
            status_code=422,
            detail=f"No hay tasa configurada para convertir USDT → {q['currency']}.")
    return q, fee, converted, m
