"""iter229 — Conversión moneda de tienda física (CUP efectivo) ↔ USDT.

Los productos de la EMPRESA se compran/venden en la tienda física en CUP
efectivo: los campos price_usd/cost_usd del producto guardan montos en esa
moneda. En la web se muestran y cobran en USDT a la tasa vigente:
- clientes VIP (mercado mayorista) → rate_vip
- clientes normales / anónimos (minorista) → rate_normal
Los productos de vendedores VIP ya están en USDT (sin conversión).

Config (settings.global):
- store_currency_code: código de la moneda de la tienda (vacío = 'CUP').
"""
import logging
from typing import Optional

from db_client import db

logger = logging.getLogger(__name__)

DEFAULT_STORE_CURRENCY = "CUP"


def _rate_field_for(role: Optional[str]) -> str:
    return "rate_vip" if role in ("vip", "admin") else "rate_normal"


async def get_store_fx(role: Optional[str] = None) -> dict:
    settings = await db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
    code = (settings.get("store_currency_code") or "").strip().upper() \
        or DEFAULT_STORE_CURRENCY
    field = _rate_field_for(role)
    rate_doc = await db.rates.find_one(
        {"from_code": "USDT", "to_code": code}, {"_id": 0}) \
        or await db.rates.find_one(
            {"from_code": "USD", "to_code": code}, {"_id": 0})
    rate = 0.0
    if rate_doc:
        try:
            rate = float(rate_doc.get(field) or 0)
        except (TypeError, ValueError):
            rate = 0.0
    return {"store_currency": code, "rate": rate, "rate_field": field,
            "configured": rate > 0}


def to_usdt(amount_store: float, rate: float) -> Optional[float]:
    if not rate or rate <= 0:
        return None
    return round(float(amount_store) / rate, 2)


async def augment_products_fx(products: list,
                              role: Optional[str] = None) -> list:
    """Añade a cada producto los campos calculados para la web:
    price_usdt (precio a cobrar según el rol), price_store + store_currency
    (equivalente en efectivo de la tienda, solo productos de la empresa)."""
    fx = await get_store_fx(role=role)
    for p in products:
        if p.get("owner_id"):
            p["price_usdt"] = float(p.get("price_usd") or 0)
            p["price_store"] = None
            p["store_currency"] = None
            p["fx_rate"] = None
        else:
            p["price_store"] = float(p.get("price_usd") or 0)
            p["store_currency"] = fx["store_currency"]
            p["price_usdt"] = to_usdt(p["price_store"], fx["rate"])
            p["fx_rate"] = fx["rate"] or None
    return products
