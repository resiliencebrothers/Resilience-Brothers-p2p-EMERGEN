"""iter211 — Tarifas de mensajería por municipio: CRUD admin + consulta.

- GET  /courier/municipality-rates          → lista activa (usuarios auth)
- GET  /vip/courier-municipality-quote      → cotización por texto de dirección
- GET  /admin/courier/municipality-rates    → lista completa (perm deliveries)
- POST /admin/courier/municipality-rates    → crear
- PUT  /admin/courier/municipality-rates/{mid} → editar precio/alias/activo
- DELETE /admin/courier/municipality-rates/{mid}
"""
import logging
import math
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from db_client import db
from auth_utils import require_user, require_permission
from audit_log import log_action
from services.municipality_rates import get_rates, get_provinces, normalize_text
from services.cuba_admin_divisions import CUBA_PROVINCES

logger = logging.getLogger("municipality_rates")

router = APIRouter(tags=["MunicipalityRates"])


def _parse_price(raw: Any) -> float:
    try:
        price = round(float(raw), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Precio inválido.")
    # MSG11 — NaN/Infinity superan las comparaciones de rango y romperían la
    # serialización JSON: exigir un número finito ANTES de escribir.
    if not math.isfinite(price):
        raise HTTPException(status_code=400, detail="Precio inválido.")
    if price <= 0 or price > 1000:
        raise HTTPException(status_code=400,
                            detail="Precio fuera de rango (0–1000 USDT).")
    return price


def _parse_aliases(raw: Any) -> list:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = raw.split(",")
    return [a.strip() for a in raw if a and a.strip()][:15]


@router.get("/courier/delivery-provinces")
async def list_delivery_provinces(request: Request) -> Any:
    """Provincias con cobertura de mensajería (para el selector de entrega)."""
    await require_user(request)
    return await get_provinces(active_only=True)


@router.get("/courier/municipality-rates")
async def list_active_rates(request: Request, province: str = "") -> Any:
    await require_user(request)
    rows = await get_rates(active_only=True, province=province.strip() or None)
    return [{"id": r["id"], "municipality": r["municipality"],
             "province": r.get("province") or "La Habana",
             "price_usdt": r["price_usdt"]} for r in rows]


@router.get("/vip/courier-municipality-quote")
async def municipality_quote(request: Request, address: str = "",
                             currency: str = "USD",
                             amount: float = 0.0,
                             municipality: str = "",
                             province: str = "") -> Any:
    await require_user(request)
    from services.courier_fee import municipality_fallback_quote
    mq = await municipality_fallback_quote(
        address, currency, amount,
        municipality_key=municipality.strip() or None,
        province=province.strip() or None)
    if not mq:
        return {"matched": False}
    return {"matched": True, **mq}


@router.get("/admin/courier/municipality-rates")
async def admin_list_rates(request: Request) -> Any:
    await require_permission(request, "deliveries")
    return await get_rates()


@router.post("/admin/courier/municipality-rates")
async def admin_create_rate(payload: dict, request: Request) -> Any:
    actor = await require_permission(request, "deliveries")
    name = (payload.get("municipality") or "").strip()
    if len(name) < 3:
        raise HTTPException(status_code=400,
                            detail="Nombre del municipio requerido (mín. 3).")
    province = (payload.get("province") or "La Habana").strip() or "La Habana"
    # Unicidad por (provincia, municipio): el mismo nombre puede existir en
    # provincias distintas, pero no dos veces en la misma provincia.
    if await db.courier_municipality_rates.find_one(
            {"municipality": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
             "province": {"$regex": f"^{re.escape(province)}$", "$options": "i"}}):
        raise HTTPException(status_code=409,
                            detail="Ese municipio ya existe en esa provincia.")
    doc: dict = {
        "id": f"muni_{uuid.uuid4().hex[:10]}",
        "municipality": name,
        "province": province,
        "price_usdt": _parse_price(payload.get("price_usdt")),
        "aliases": _parse_aliases(payload.get("aliases")),
        "active": True,
    }
    await db.courier_municipality_rates.insert_one(dict(doc))
    await log_action(db, actor, "courier_muni_rate.create", "muni_rate", doc["id"],
                     summary=(f"Tarifa {province} / {name} = "
                              f"{doc['price_usdt']} USDT"),
                     details=doc)
    return doc


@router.get("/admin/courier/province-catalog")
async def admin_province_catalog(request: Request) -> Any:
    """Catálogo de provincias de Cuba para activar una provincia completa."""
    await require_permission(request, "deliveries")
    return {"provinces": sorted(CUBA_PROVINCES.keys(),
                                key=lambda p: normalize_text(p))}


@router.get("/admin/courier/province-catalog/municipalities")
async def admin_province_catalog_munis(request: Request,
                                       province: str = "") -> Any:
    """Municipios del catálogo de una provincia, anotados con la tarifa ya
    configurada (si existe) para no duplicar al activarlos en lote."""
    await require_permission(request, "deliveries")
    prov = (province or "").strip()
    catalog_prov = next(
        (p for p in CUBA_PROVINCES if normalize_text(p) == normalize_text(prov)),
        None)
    if not catalog_prov:
        raise HTTPException(status_code=404,
                            detail="Provincia no encontrada en el catálogo.")
    existing: dict = {}
    async for r in db.courier_municipality_rates.find(
            {"province": {"$regex": f"^{re.escape(catalog_prov)}$",
                          "$options": "i"}}, {"_id": 0}):
        existing[normalize_text(r["municipality"])] = r
    munis = []
    for m in CUBA_PROVINCES[catalog_prov]:
        ex = existing.get(normalize_text(m))
        munis.append({
            "municipality": m,
            "configured": bool(ex),
            "rate_id": ex["id"] if ex else None,
            "price_usdt": ex.get("price_usdt") if ex else None,
            "active": ex.get("active") if ex else None,
        })
    return {"province": catalog_prov, "municipalities": munis}


@router.post("/admin/courier/municipality-rates/bulk")
async def admin_bulk_create_rates(payload: dict, request: Request) -> Any:
    """Activa en lote los municipios de una provincia. Cada ítem trae su PRECIO
    (uno a uno): los que ya existen en esa provincia se actualizan y reactivan;
    los nuevos se crean. Los municipios sin precio no se envían (se omiten)."""
    actor = await require_permission(request, "deliveries")
    province = (payload.get("province") or "").strip()
    if len(province) < 3:
        raise HTTPException(status_code=400, detail="Provincia requerida.")
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400,
                            detail="Sin municipios para activar.")
    if len(items) > 200:
        raise HTTPException(status_code=400,
                            detail="Demasiados municipios en una sola operación.")
    existing: dict = {}
    async for r in db.courier_municipality_rates.find(
            {"province": {"$regex": f"^{re.escape(province)}$",
                          "$options": "i"}}, {"_id": 0}):
        existing[normalize_text(r["municipality"])] = r
    created: list = []
    updated: list = []
    for it in items:
        name = (it.get("municipality") or "").strip()
        if len(name) < 3:
            continue
        price = _parse_price(it.get("price_usdt"))
        ex = existing.get(normalize_text(name))
        if ex:
            await db.courier_municipality_rates.update_one(
                {"id": ex["id"]},
                {"$set": {"price_usdt": price, "active": True}})
            updated.append(name)
        else:
            doc = {
                "id": f"muni_{uuid.uuid4().hex[:10]}",
                "municipality": name,
                "province": province,
                "price_usdt": price,
                "aliases": [],
                "active": True,
            }
            await db.courier_municipality_rates.insert_one(dict(doc))
            created.append(name)
    if not created and not updated:
        raise HTTPException(status_code=400,
                            detail="Pon al menos un precio válido para activar.")
    await log_action(db, actor, "courier_muni_rate.bulk", "muni_rate", province,
                     summary=(f"Provincia {province}: {len(created)} creados, "
                              f"{len(updated)} actualizados"),
                     details={"province": province, "created": created,
                              "updated": updated})
    return {"created": len(created), "updated": len(updated),
            "created_names": created, "updated_names": updated}


@router.put("/admin/courier/municipality-rates/{mid}")
async def admin_update_rate(mid: str, payload: dict, request: Request) -> Any:
    actor = await require_permission(request, "deliveries")
    row = await db.courier_municipality_rates.find_one({"id": mid}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="No encontrado.")
    update: dict = {}
    if "price_usdt" in payload:
        update["price_usdt"] = _parse_price(payload.get("price_usdt"))
    if "aliases" in payload:
        update["aliases"] = _parse_aliases(payload.get("aliases"))
    if "active" in payload:
        update["active"] = bool(payload.get("active"))
    if "municipality" in payload:
        name = (payload.get("municipality") or "").strip()
        if len(name) < 3:
            raise HTTPException(status_code=400, detail="Nombre inválido.")
        update["municipality"] = name
    if "province" in payload:
        prov = (payload.get("province") or "").strip()
        if len(prov) < 3:
            raise HTTPException(status_code=400, detail="Provincia inválida.")
        update["province"] = prov
    if not update:
        raise HTTPException(status_code=400, detail="Nada que actualizar.")
    await db.courier_municipality_rates.update_one({"id": mid}, {"$set": update})
    await log_action(db, actor, "courier_muni_rate.update", "muni_rate", mid,
                     summary=f"Tarifa municipio {row['municipality']} actualizada",
                     details={"before": row, "changes": update})
    return await db.courier_municipality_rates.find_one({"id": mid}, {"_id": 0})


@router.delete("/admin/courier/municipality-rates/{mid}")
async def admin_delete_rate(mid: str, request: Request) -> Any:
    actor = await require_permission(request, "deliveries")
    row = await db.courier_municipality_rates.find_one({"id": mid}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="No encontrado.")
    await db.courier_municipality_rates.delete_one({"id": mid})
    await log_action(db, actor, "courier_muni_rate.delete", "muni_rate", mid,
                     summary=f"Tarifa municipio {row['municipality']} eliminada",
                     details=row)
    return {"ok": True}
