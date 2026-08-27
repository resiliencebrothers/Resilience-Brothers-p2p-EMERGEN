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
    if await db.courier_municipality_rates.count_documents({}) > 0:
        return
    docs = [{
        "id": f"muni_{uuid.uuid4().hex[:10]}",
        "municipality": r["municipality"],
        "price_usdt": r["price_usdt"],
        "aliases": r["aliases"],
        "active": True,
    } for r in DEFAULT_RATES]
    await db.courier_municipality_rates.insert_many(docs)


async def get_rates(active_only: bool = False) -> list:
    await seed_if_empty()
    q = {"active": True} if active_only else {}
    rows = await db.courier_municipality_rates.find(q, {"_id": 0}).to_list(200)
    rows.sort(key=lambda r: (float(r.get("price_usdt") or 0),
                             normalize_text(r.get("municipality"))))
    return rows


async def get_rate_by_key(key: str) -> Optional[dict]:
    """Busca por id o por nombre normalizado (solo activas)."""
    await seed_if_empty()
    row = await db.courier_municipality_rates.find_one(
        {"id": key, "active": True}, {"_id": 0})
    if row:
        return row
    norm = normalize_text(key)
    for r in await get_rates(active_only=True):
        if normalize_text(r["municipality"]) == norm:
            return r
    return None


async def match_municipality(text: str) -> Optional[dict]:
    """Detecta el municipio dentro de un texto de dirección (normalizado,
    coincidencia por palabra completa, términos más largos primero)."""
    norm = normalize_text(text)
    if not norm:
        return None
    terms = []
    for r in await get_rates(active_only=True):
        for term in [r["municipality"], *(r.get("aliases") or [])]:
            nt = normalize_text(term)
            if nt:
                terms.append((nt, r))
    terms.sort(key=lambda x: len(x[0]), reverse=True)
    for nt, r in terms:
        if re.search(rf"(?<![a-z0-9]){re.escape(nt)}(?![a-z0-9])", norm):
            return r
    return None
