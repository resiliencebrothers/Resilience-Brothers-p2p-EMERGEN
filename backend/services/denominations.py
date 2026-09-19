"""iter277 — Denominaciones de billetes configurables.

Las listas de fábrica son las de circulación; el admin puede AÑADIR nuevas
denominaciones (p. ej. un billete nuevo) que se guardan en `app_settings`
(clave `cash_denominations_extra`) y se fusionan con las de fábrica.
"""
from typing import Dict, List

from db_client import db

DEFAULT_CASH_DENOMINATIONS: Dict[str, List[int]] = {
    "CUP": [5000, 2000, 1000, 500, 200, 100, 50, 20, 10, 5, 3, 1],
    "USD": [100, 50, 20, 10, 5, 2, 1],
}

_SETTINGS_KEY = "cash_denominations_extra"


async def get_cash_denominations() -> Dict[str, List[int]]:
    """Listas vigentes por moneda: fábrica + extras del admin (descendente)."""
    merged = {c: sorted(v, reverse=True)
              for c, v in DEFAULT_CASH_DENOMINATIONS.items()}
    doc = await db.app_settings.find_one({"key": _SETTINGS_KEY}, {"_id": 0})
    for code, extra in ((doc or {}).get("value") or {}).items():
        if code not in merged:
            continue
        vals = set(merged[code])
        for d in extra or []:
            try:
                n = int(d)
            except (TypeError, ValueError):
                continue
            if n > 0:
                vals.add(n)
        merged[code] = sorted(vals, reverse=True)
    return merged


async def add_cash_denomination(code: str, value: int) -> Dict[str, List[int]]:
    """Registra una denominación extra (idempotente por $addToSet)."""
    await db.app_settings.update_one(
        {"key": _SETTINGS_KEY},
        {"$addToSet": {f"value.{code}": int(value)}},
        upsert=True)
    return await get_cash_denominations()
