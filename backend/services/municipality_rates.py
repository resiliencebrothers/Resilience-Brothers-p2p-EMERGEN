"""iter211 — Tarifas fijas de mensajería por municipio (La Habana).

Respaldo de precio cuando el mapa NO logra ubicar la dirección del cliente:
se detecta el municipio dentro del texto de la dirección y se cobra la
tarifa fija configurada automáticamente. Editable por el admin (colección
`courier_municipality_rates`); se auto-siembra con la tabla del operador
(Ago 2026). En municipios con dos precios por zona se usa el MÁS ALTO
(decisión del operador).
"""
import re
import unicodedata
import uuid
from typing import Optional

from db_client import db


class AmbiguousMunicipalityError(ValueError):
    """MUNI-02-R2 — un NOMBRE de municipio resolvió a varios territorios
    activos (homónimos en provincias distintas) sin provincia que desambigüe.
    Debe rechazarse ANTES de cualquier cobro: elegir el primero cobraría la
    tarifa de un territorio que el cliente no seleccionó."""

    def __init__(self, key: str) -> None:
        super().__init__(f"ambiguous municipality name: {key!r}")
        self.key = key


DEFAULT_RATES = [
    {"municipality": "10 de Octubre", "price_usdt": 2.0,
     "aliases": ["diez de octubre"]},
    {"municipality": "Vedado", "price_usdt": 3.0,
     "aliases": ["el vedado", "nuevo vedado"]},
    {"municipality": "Cerro", "price_usdt": 3.0, "aliases": ["el cerro"]},
    {"municipality": "Habana Vieja", "price_usdt": 3.0,
     "aliases": ["la habana vieja"]},
    {"municipality": "Centro Habana", "price_usdt": 3.0, "aliases": []},
    {"municipality": "Plaza", "price_usdt": 3.0,
     "aliases": ["plaza de la revolucion"]},
    {"municipality": "Regla", "price_usdt": 3.0, "aliases": []},
    # Rango 3–5 → se cobra el más alto (5).
    {"municipality": "Arroyo Naranjo", "price_usdt": 5.0, "aliases": []},
    {"municipality": "San Miguel del Padrón", "price_usdt": 5.0,
     "aliases": ["san miguel"]},
    {"municipality": "Guanabacoa", "price_usdt": 5.0, "aliases": []},
    # Rango 5–7 → se cobra el más alto (7).
    {"municipality": "Cotorro", "price_usdt": 7.0, "aliases": ["el cotorro"]},
    {"municipality": "Boyeros", "price_usdt": 7.0, "aliases": []},
    {"municipality": "Habana del Este", "price_usdt": 7.0,
     "aliases": ["la habana del este", "alamar", "cojimar", "guanabo"]},
    {"municipality": "Marianao", "price_usdt": 7.0, "aliases": []},
    {"municipality": "La Lisa", "price_usdt": 7.0, "aliases": []},
]


def normalize_text(text: str) -> str:
    """minúsculas + sin acentos + espacios colapsados."""
    t = unicodedata.normalize("NFD", str(text or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t.lower()).strip()


async def seed_if_empty() -> None:
    if await db.courier_municipality_rates.count_documents({}) == 0:
        docs = [{
            "id": f"muni_{uuid.uuid4().hex[:10]}",
            "municipality": r["municipality"],
            "province": r.get("province") or "La Habana",
            "price_usdt": r["price_usdt"],
            "aliases": r["aliases"],
            "active": True,
        } for r in DEFAULT_RATES]
        await db.courier_municipality_rates.insert_many(docs)
    await _ensure_province_backfill()


_province_backfilled = False


async def _ensure_province_backfill() -> None:
    """Las tarifas antiguas no tenían provincia (todas eran La Habana). Se
    rellena una sola vez por proceso para no reescribir en cada consulta."""
    global _province_backfilled
    if _province_backfilled:
        return
    await db.courier_municipality_rates.update_many(
        {"$or": [{"province": {"$exists": False}}, {"province": None},
                 {"province": ""}]},
        {"$set": {"province": "La Habana"}})
    _province_backfilled = True


async def get_provinces(active_only: bool = True) -> list:
    """Provincias con al menos un municipio (activo) con tarifa, ordenadas."""
    await seed_if_empty()
    q = {"active": True} if active_only else {}
    provs = await db.courier_municipality_rates.distinct("province", q)
    return sorted(p for p in provs if p)


async def get_rates(active_only: bool = False,
                    province: Optional[str] = None) -> list:
    await seed_if_empty()
    q: dict = {}
    if active_only:
        q["active"] = True
    if province:
        q["province"] = {"$regex": f"^{re.escape(province)}$", "$options": "i"}
    rows = await db.courier_municipality_rates.find(q, {"_id": 0}).to_list(500)
    for r in rows:
        r.setdefault("province", "La Habana")
    rows.sort(key=lambda r: (normalize_text(r.get("province")),
                             float(r.get("price_usdt") or 0),
                             normalize_text(r.get("municipality"))))
    return rows


async def get_rate_by_key(key: str,
                          province: Optional[str] = None) -> Optional[dict]:
    """Busca por id (exacto) o por nombre normalizado (solo activas).
    Con municipios homónimos en provincias distintas, `province` desambigua
    la coincidencia por nombre. MUNI-02-R — si se pasa `province` y NO hay match
    en esa provincia, devuelve None (nunca cae a un homónimo de otra).
    MUNI-02-R2 — SIN `province`, un nombre solo resuelve si es inequívoco; con
    varios homónimos activos lanza AmbiguousMunicipalityError (rechazo previo
    al cobro). La búsqueda por id estable nunca es ambigua."""
    await seed_if_empty()
    pnorm = normalize_text(province) if province else None
    row = await db.courier_municipality_rates.find_one(
        {"id": key, "active": True}, {"_id": 0})
    if row:
        row.setdefault("province", "La Habana")
        # MUNI-02-R — la fila hallada por ID debe pertenecer a la provincia
        # indicada; con provincia incompatible NO se reinterpreta a la tarifa
        # de otro territorio: se rechaza (None). La validación de provincia ya
        # no vive solo en la búsqueda por nombre.
        if pnorm and normalize_text(row.get("province")) != pnorm:
            return None
        return row
    norm = normalize_text(key)
    matches = [r for r in await get_rates(active_only=True)
               if normalize_text(r["municipality"]) == norm]
    # MUNI-02 — con provincia indicada, la coincidencia por NOMBRE debe
    # pertenecer a ESA provincia: nunca se devuelve un homónimo de otra
    # provincia (eso cobraría una tarifa de otro territorio).
    if pnorm:
        for r in matches:
            if normalize_text(r.get("province")) == pnorm:
                return r
        return None
    # MUNI-02-R2 — SIN provincia, un NOMBRE solo resuelve si es inequívoco.
    # Con homónimos activos en provincias distintas NO se elige el primero
    # (cobraría la tarifa de un territorio que el cliente no eligió): se
    # señala ambigüedad para RECHAZAR antes de cualquier cobro. Un id estable
    # se resolvió arriba sin pasar por aquí, y un nombre único sigue valiendo.
    if len(matches) > 1:
        raise AmbiguousMunicipalityError(key)
    return matches[0] if matches else None


async def match_municipality(text: str,
                             province: Optional[str] = None) -> Optional[dict]:
    """Detecta el municipio dentro de un texto de dirección (normalizado,
    coincidencia por palabra completa, términos más largos primero).
    Si se pasa `province`, la detección se limita a esa provincia (si la
    provincia no tiene municipios, cae al conjunto completo)."""
    norm = normalize_text(text)
    if not norm:
        return None
    rows = await get_rates(active_only=True)
    pnorm = normalize_text(province) if province else None
    if pnorm:
        scoped = [r for r in rows if normalize_text(r.get("province")) == pnorm]
        rows = scoped or rows
    terms = []
    for r in rows:
        for term in [r["municipality"], *(r.get("aliases") or [])]:
            nt = normalize_text(term)
            if nt:
                terms.append((nt, r))
    terms.sort(key=lambda x: len(x[0]), reverse=True)
    for nt, r in terms:
        if re.search(rf"(?<![a-z0-9]){re.escape(nt)}(?![a-z0-9])", norm):
            return r
    return None
