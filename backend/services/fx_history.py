"""iter329 — Histórico de la tasa CUP↔USDT (IPV Fase 1+).

El inventario físico se CONTROLA en CUP, pero el capital de la empresa se mide
en USDT. El valor en USDT del mismo inventario depende de la tasa VIGENTE en
cada fecha. Para poder valorar el histórico en USDT de forma REPRODUCIBLE (y
medir el efecto de la variación de la tasa), se congela un snapshot de la tasa
USDT→CUP por fecha: cada día (job programado) y cada vez que un admin cambia la
tasa. Un snapshot por (par, fecha); el último cambio del día gana.
"""
from typing import Optional

from db_client import db
from auth_utils import now_utc, iso
from services.inventory import today_havana

_INDEX_READY = False


async def _ensure_index() -> None:
    global _INDEX_READY
    if not _INDEX_READY:
        await db.fx_rate_history.create_index(
            [("from_code", 1), ("to_code", 1), ("date", 1)], unique=True)
        _INDEX_READY = True


async def capture_fx_snapshot(date: Optional[str] = None,
                              source: str = "auto") -> Optional[dict]:
    """Congela la tasa USDT→CUP vigente para `date` (hoy en Cuba por defecto).
    Idempotente por (par, fecha)."""
    await _ensure_index()
    day = (date or today_havana())[:10]
    rate_doc = await db.rates.find_one(
        {"from_code": "USDT", "to_code": "CUP"}, {"_id": 0})
    if not rate_doc:
        return None
    rn = float(rate_doc.get("rate_normal") or 0)
    rv = float(rate_doc.get("rate_vip") or 0)
    await db.fx_rate_history.update_one(
        {"from_code": "USDT", "to_code": "CUP", "date": day},
        {"$set": {"rate_normal": rn, "rate_vip": rv,
                  "captured_at": iso(now_utc()), "source": source},
         "$setOnInsert": {"from_code": "USDT", "to_code": "CUP", "date": day}},
        upsert=True)
    return {"date": day, "rate_normal": rn, "rate_vip": rv}


async def get_fx_at(date: str) -> dict:
    """Tasa USDT→CUP VIGENTE a la fecha `date`: el último snapshot con
    date ≤ fecha. Si no hay (fecha anterior al histórico) usa el más antiguo
    disponible; si no hay histórico, la tasa actual. En esos casos `estimated`
    = True (la tasa de esa fecha no fue registrada)."""
    day = (date or today_havana())[:10]
    snap = await db.fx_rate_history.find_one(
        {"from_code": "USDT", "to_code": "CUP", "date": {"$lte": day}},
        {"_id": 0}, sort=[("date", -1)])
    if snap:
        return {"rate_normal": float(snap.get("rate_normal") or 0),
                "rate_vip": float(snap.get("rate_vip") or 0),
                "rate_date": snap["date"], "estimated": False}
    snap = await db.fx_rate_history.find_one(
        {"from_code": "USDT", "to_code": "CUP"},
        {"_id": 0}, sort=[("date", 1)])
    if snap:
        return {"rate_normal": float(snap.get("rate_normal") or 0),
                "rate_vip": float(snap.get("rate_vip") or 0),
                "rate_date": snap["date"], "estimated": True}
    cur = await db.rates.find_one(
        {"from_code": "USDT", "to_code": "CUP"}, {"_id": 0})
    if cur:
        return {"rate_normal": float(cur.get("rate_normal") or 0),
                "rate_vip": float(cur.get("rate_vip") or 0),
                "rate_date": None, "estimated": True}
    return {"rate_normal": 0.0, "rate_vip": 0.0, "rate_date": None,
            "estimated": True}
