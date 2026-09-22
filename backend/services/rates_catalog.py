"""FX06/FX07 (auditoría de monedas 22/09/2026) — integridad del catálogo al
arrancar: normalización de códigos, consolidación de duplicados e índices
únicos para `currencies.code` y `rates(from_code, to_code)`."""
import logging
from typing import Any

from db_client import db

logger = logging.getLogger(__name__)


def _sel(doc: dict) -> dict:
    """Selector robusto: filas legadas pueden carecer del campo `id`."""
    return {"id": doc["id"]} if doc.get("id") else {"_id": doc["_id"]}


async def ensure_market_integrity() -> None:
    # 1) Tasas — normalizar códigos heredados con espacios/minúsculas.
    rows: list[Any] = await db.rates.find(
        {}, {"id": 1, "from_code": 1, "to_code": 1,
             "updated_at": 1}).to_list(5000)
    for r in rows:
        nf = str(r.get("from_code") or "").strip().upper()
        nt = str(r.get("to_code") or "").strip().upper()
        if nf != r.get("from_code") or nt != r.get("to_code"):
            await db.rates.update_one(
                _sel(r), {"$set": {"from_code": nf, "to_code": nt}})
            r["from_code"], r["to_code"] = nf, nt
            logger.warning("rates: códigos normalizados → %s→%s", nf, nt)
    # 2) Tasas — consolidar pares duplicados: se conserva la fila con
    #    `updated_at` más reciente (criterio revisable; queda en el log).
    rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    seen: dict = {}
    for r in rows:
        k = (r.get("from_code"), r.get("to_code"))
        if k in seen:
            await db.rates.delete_one(_sel(r))
            logger.warning(
                "rates: par duplicado %s→%s consolidado (se retira %s)",
                k[0], k[1], r.get("id") or r.get("_id"))
        else:
            seen[k] = r.get("id") or r.get("_id")
    await db.rates.create_index([("from_code", 1), ("to_code", 1)],
                                unique=True)
    # 2b) Tasas — limpiar ruido float legado en los valores (p.ej.
    #     183.96700000000044 guardado por aritmética previa → 183.967).
    from services.conversions import snap_value
    val_rows: list[Any] = await db.rates.find(
        {}, {"id": 1, "rate_normal": 1, "rate_vip": 1, "real_rate": 1,
             "rate_sell": 1, "tiers": 1}).to_list(5000)
    for r in val_rows:
        upd: dict = {}
        for f in ("rate_normal", "rate_vip", "real_rate", "rate_sell"):
            v = r.get(f)
            if isinstance(v, (int, float)) and snap_value(v) != v:
                upd[f] = snap_value(v)
        tiers = r.get("tiers")
        if isinstance(tiers, list):
            snapped = [
                {**t, **{f: snap_value(t[f]) for f in
                         ("min_amount", "rate_normal", "rate_vip",
                          "real_rate")
                         if isinstance(t.get(f), (int, float))}}
                for t in tiers if isinstance(t, dict)]
            if snapped != tiers:
                upd["tiers"] = snapped
        if upd:
            await db.rates.update_one(_sel(r), {"$set": upd})
            logger.warning("rates: ruido float normalizado en %s → %s",
                           r.get("id") or r.get("_id"), list(upd))
    # 3) Monedas — normalizar códigos y deduplicar (se conserva la más
    #    antigua, que es la que acumuló referencias financieras).
    cur: list[Any] = await db.currencies.find(
        {}, {"id": 1, "code": 1, "created_at": 1}).to_list(2000)
    for c in cur:
        nc = str(c.get("code") or "").strip().upper()
        if nc != c.get("code"):
            await db.currencies.update_one(_sel(c), {"$set": {"code": nc}})
            c["code"] = nc
            logger.warning("currencies: código normalizado → %s", nc)
    cur.sort(key=lambda c: str(c.get("created_at") or ""))
    seen_c: dict = {}
    for c in cur:
        k = c.get("code")
        if k in seen_c:
            await db.currencies.delete_one(_sel(c))
            logger.warning(
                "currencies: código duplicado %s consolidado (se retira %s)",
                k, c.get("id") or c.get("_id"))
        else:
            seen_c[k] = c.get("id") or c.get("_id")
    await db.currencies.create_index("code", unique=True)
