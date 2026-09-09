"""iter198 — free OSM stack: Nominatim geocoding + OSRM road routing.

Used to auto-quote courier deliveries (office → client) per the operator's
spec. NEVER bill straight-line distance: when the route can't be computed the
caller must fall back to REQUIRES_MANUAL_REVIEW and let staff enter the km.
"""
import asyncio
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger("geo_routing")

_UA = {"User-Agent": "ResilienceBrothersP2P/1.0 (courier quotes)"}
_NOMINATIM = "https://nominatim.openstreetmap.org/search"
_OSRM = "https://router.project-osrm.org/route/v1/driving"

# iter204 — direcciones cubanas: Nominatim no entiende "entre X y Y" (también
# escrito "e/" o "%"), "esquina a Z" ni números de casa. Se degrada
# progresivamente conservando los segmentos tras la coma (barrio/municipio).
_BETWEEN_RE = re.compile(
    r"(?:\bentre\b|\be\s*/|%|\besq(?:\.|uina)?(?:\s+a)?)[^,]*", re.IGNORECASE)
_HOUSENUM_RE = re.compile(
    r"(?:\b(?:no|nro|num)\.?\s*|#\s*)?\b\d+\s*[a-z]?\b", re.IGNORECASE)


def _tidy(s: str) -> str:
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"(, )+", ", ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" ,.-")


async def geocode(q: str, limit: int = 5, worldwide_fallback: bool = True) -> list:
    """Address → candidate coordinates (Cuba-first, worldwide fallback)."""
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(_NOMINATIM, headers=_UA, params={
            "q": q, "format": "json", "limit": limit,
            "countrycodes": "cu", "addressdetails": 0,
        })
        r.raise_for_status()
        rows = r.json()
        if not rows and worldwide_fallback:
            r = await client.get(_NOMINATIM, headers=_UA, params={
                "q": q, "format": "json", "limit": limit, "addressdetails": 0,
            })
            r.raise_for_status()
            rows = r.json()
    return [
        {"display_name": row.get("display_name", ""),
         "lat": float(row["lat"]), "lon": float(row["lon"])}
        for row in rows
        if row.get("lat") and row.get("lon")
    ]


def _query_variants(q: str, province: str = "") -> list:
    """Variantes progresivamente simplificadas de una dirección cubana:
    1) tal cual  2) sin "entre X y Y" + provincia  3) sin números de casa."""
    q = (q or "").strip()
    province = (province or "").strip()
    variants = [q]

    def _add(v: str) -> None:
        v = _tidy(v or "")
        if v and len(v) >= 3 and all(v.lower() != x.lower() for x in variants):
            variants.append(v)

    no_between = _tidy(_BETWEEN_RE.sub(" ", q))
    street_only = re.sub(r"[#/]+", " ", _HOUSENUM_RE.sub(" ", no_between or q))
    for base in (no_between, _tidy(street_only)):
        if not base:
            continue
        if province and province.lower() not in base.lower():
            _add(f"{base}, {province}")
        _add(base)
    return variants[:4]


async def reverse_geocode(lat: float, lon: float) -> str:
    """iter206 — coords GPS del cliente → dirección legible (best-effort)."""
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(
            "https://nominatim.openstreetmap.org/reverse",
            headers=_UA,
            params={"lat": lat, "lon": lon, "format": "json", "zoom": 17},
        )
        r.raise_for_status()
        return (r.json() or {}).get("display_name", "") or ""


async def geocode_smart(q: str, province: str = "", limit: int = 5) -> dict:
    """Cadena de fallback para direcciones cubanas. Devuelve
    {results, approximate, matched_query} — approximate=True cuando el
    resultado salió de una variante simplificada (calle/zona)."""
    variants = _query_variants(q, province)
    for i, v in enumerate(variants):
        if i > 0:
            await asyncio.sleep(1.1)  # política Nominatim: máx 1 req/s
        try:
            rows = await geocode(v, limit=limit, worldwide_fallback=(i == 0))
        except Exception as e:
            logger.error(f"geocode variant {v!r} failed: {e}")
            rows = []
        if rows:
            return {"results": rows, "approximate": i > 0, "matched_query": v}
    return {"results": [], "approximate": False, "matched_query": None}


async def route_km(from_lat: float, from_lon: float,
                   to_lat: float, to_lon: float) -> Optional[float]:
    """Real driving distance in km (unrounded). None if no route found."""
    url = f"{_OSRM}/{from_lon},{from_lat};{to_lon},{to_lat}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers=_UA, params={"overview": "false"})
        r.raise_for_status()
        data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    return float(data["routes"][0]["distance"]) / 1000.0
