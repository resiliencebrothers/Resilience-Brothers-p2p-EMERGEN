"""Tiendas físicas (sucursales) — iter236.

CRUD admin + listado para la opción "Recogida en tienda" del marketplace.
Un producto puede limitarse a ciertas sucursales via `available_store_ids`
(lista vacía o ausente = disponible en todas).
"""
import uuid
import logging
from typing import Any, Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import require_user, require_permission, now_utc, iso
from audit_log import log_action

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Stores"])


class Store(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    address: str
    municipality: str = ""
    province: str = ""
    phone: str = ""
    hours: str = ""
    active: bool = True
    created_at: str = Field(default_factory=lambda: iso(now_utc()))
    updated_at: str = Field(default_factory=lambda: iso(now_utc()))


class StoreCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    address: str = Field(..., min_length=5, max_length=400)
    municipality: str = Field("", max_length=80)
    province: str = Field("", max_length=80)
    phone: str = Field("", max_length=40)
    hours: str = Field("", max_length=200)
    active: bool = True


@router.get("/stores")
async def list_active_stores(request: Request,
                             product_id: Optional[str] = None) -> Any:
    """Sucursales activas para elegir dónde recoger. Con `product_id` filtra
    por disponibilidad del producto (lista vacía = todas).

    F2-B — si el producto es de una EMPRESA (company_id, sin owner_id), se
    devuelven las tiendas de ESA Empresa que TIENEN existencias del producto
    en su estantería (`by_store[sid] > 0`), con `available_qty`, para que el
    comprador sólo pueda recoger donde hay stock real."""
    await require_user(request)
    if product_id:
        product = await db.products.find_one({"id": product_id}, {"_id": 0})
    else:
        product = None
    if product and product.get("company_id"):
        cid = product["company_id"]
        by_store = product.get("by_store") or {}
        allowed = product.get("available_store_ids") or []
        company_stores = await db.stores.find(
            {"company_id": cid, "active": True, "status": {"$ne": "closing"}},
            {"_id": 0}).sort("created_at", 1).to_list(200)
        result = []
        for s in company_stores:
            if allowed and s["id"] not in allowed:
                continue
            qty = round(float(by_store.get(s["id"]) or 0), 3)
            if qty <= 0:
                continue  # sólo tiendas con existencias reales del producto
            result.append({**s, "available_qty": qty})
        return result
    stores = await db.stores.find(
        {"active": True,
         "$or": [{"company_id": {"$exists": False}},
                 {"company_id": {"$in": [None, ""]}}]},
        {"_id": 0}) \
        .sort("created_at", 1).to_list(100)
    if product_id:
        allowed = (product or {}).get("available_store_ids") or []
        if allowed:
            stores = [s for s in stores if s["id"] in allowed]
    return stores


@router.get("/admin/stores")
async def admin_list_stores(request: Request) -> Any:
    await require_permission(request, "products")
    # Solo sucursales de Resilience (company_id vacío/ausente). Las tiendas de
    # cuentas Empresa se gestionan desde el panel de la propia Empresa.
    return await db.stores.find(
        {"$or": [{"company_id": {"$exists": False}},
                 {"company_id": {"$in": [None, ""]}}]},
        {"_id": 0}).sort("created_at", 1).to_list(200)


@router.get("/admin/pickups-today")
async def pickups_today(request: Request) -> Any:
    """iter237 — recogidas pendientes para el personal de tienda: quién va
    en camino ahora y quién tiene pedido listo/pendiente por recoger."""
    await require_permission(request, "products")
    rows = await db.redemptions.find(
        {"fulfillment": "store_pickup", "status": {"$in": ["pending", "approved"]}},
        {"_id": 0, "id": 1, "user_name": 1, "product_name": 1, "quantity": 1,
         "store_id": 1, "store_name": 1, "pickup_ready_at": 1,
         "on_my_way_at": 1, "created_at": 1, "status": 1},
    ).sort("created_at", -1).to_list(200)
    rows.sort(key=lambda r: r.get("on_my_way_at") or "", reverse=True)
    return rows


@router.post("/admin/stores")
async def create_store(payload: StoreCreate, request: Request) -> Any:
    actor = await require_permission(request, "products")
    s = Store(**payload.model_dump())
    await db.stores.insert_one(s.model_dump())
    await log_action(db, actor, "store.create", "store", s.id,
                     summary=f"Tienda creada: {s.name}")
    return s.model_dump()


@router.put("/admin/stores/{store_id}")
async def update_store(store_id: str, payload: StoreCreate,
                       request: Request) -> Any:
    actor = await require_permission(request, "products")
    existing = await db.stores.find_one({"id": store_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    data = payload.model_dump()
    data["updated_at"] = iso(now_utc())
    await db.stores.update_one({"id": store_id}, {"$set": data})
    await log_action(db, actor, "store.update", "store", store_id,
                     summary=f"Tienda editada: {payload.name}")
    return await db.stores.find_one({"id": store_id}, {"_id": 0})


@router.delete("/admin/stores/{store_id}")
async def delete_store(store_id: str, request: Request) -> Any:
    actor = await require_permission(request, "products")
    existing = await db.stores.find_one({"id": store_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    await db.stores.delete_one({"id": store_id})
    await log_action(db, actor, "store.delete", "store", store_id,
                     summary=f"Tienda eliminada: {existing.get('name', '')}")
    return {"ok": True}
