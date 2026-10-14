"""Empresa (rol business) — Fase 1: perfil, tiendas y catálogo propio.

Una Empresa es un rol INDEPENDIENTE (no VIP, no staff). Se auto-registra y
queda `under_review` hasta que un admin la aprueba. A partir de ahí puede:
- Administrar sus propias tiendas (1:N) — colección `stores` con `company_id`.
- Publicar productos al marketplace (como antes los VIP) que quedan `pending`
  hasta que un admin los aprueba en /admin/vendor-products (owner_id presente).

Todo se aísla por `company_id` (= user_id de la Empresa en esta fase). Las
fases siguientes añadirán inventario por tienda/almacén central, sub-saldo y
solicitud de mensajería.
"""
import uuid
import logging
from typing import Any, Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import require_company, now_utc, iso
from admin_alerts import notify_all_admins
from routes.market import Product
from routes.vendor_products import (
    MAX_PRODUCTS_PER_VENDOR,
    get_commission_pct,
    _publish_products_changed,
)
from services.proof_upload import maybe_upload_proof
from services import company_inventory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/company", tags=["Company"])


# ============================================================
# Perfil
# ============================================================

@router.get("/me")
async def company_me(request: Request) -> Any:
    user = await require_company(request)
    stores_count = await db.stores.count_documents({"company_id": user["user_id"]})
    products_count = await db.products.count_documents({"company_id": user["user_id"]})
    return {
        "user_id": user["user_id"],
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "account_status": user.get("account_status"),
        "stores_count": stores_count,
        "products_count": products_count,
        "commission_pct": await get_commission_pct(),
    }


# ============================================================
# Tiendas (1:N) — aisladas por company_id
# ============================================================

class CompanyStorePayload(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    address: str = Field(..., min_length=5, max_length=400)
    municipality: str = Field("", max_length=80)
    province: str = Field("", max_length=80)
    phone: str = Field("", max_length=40)
    hours: str = Field("", max_length=200)
    active: bool = True


async def _company_store_ids(company_id: str) -> set[str]:
    docs = await db.stores.find(
        {"company_id": company_id}, {"id": 1, "_id": 0}).to_list(500)
    return {d["id"] for d in docs}


@router.get("/stores")
async def list_my_stores(request: Request) -> Any:
    user = await require_company(request)
    return await db.stores.find(
        {"company_id": user["user_id"]}, {"_id": 0}) \
        .sort("created_at", 1).to_list(200)


@router.post("/stores")
async def create_my_store(payload: CompanyStorePayload, request: Request) -> Any:
    user = await require_company(request)
    doc = payload.model_dump()
    doc.update({
        "id": str(uuid.uuid4()),
        "company_id": user["user_id"],
        "created_at": iso(now_utc()),
        "updated_at": iso(now_utc()),
    })
    await db.stores.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/stores/{store_id}")
async def update_my_store(store_id: str, payload: CompanyStorePayload,
                          request: Request) -> Any:
    user = await require_company(request)
    existing = await db.stores.find_one(
        {"id": store_id, "company_id": user["user_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    data = payload.model_dump()
    data["updated_at"] = iso(now_utc())
    await db.stores.update_one(
        {"id": store_id, "company_id": user["user_id"]}, {"$set": data})
    return await db.stores.find_one(
        {"id": store_id, "company_id": user["user_id"]}, {"_id": 0})


@router.delete("/stores/{store_id}")
async def delete_my_store(store_id: str, request: Request) -> Any:
    user = await require_company(request)
    res = await db.stores.delete_one(
        {"id": store_id, "company_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    # Devuelve la mercancía distribuida a esa tienda al almacén central.
    await company_inventory.release_store(user["user_id"], store_id)
    # Quita la tienda de los productos que la referenciaban.
    await db.products.update_many(
        {"company_id": user["user_id"]},
        {"$pull": {"available_store_ids": store_id}})
    return {"ok": True}


# ============================================================
# Catálogo de productos (publica al marketplace tras aprobación admin)
# ============================================================

class CompanyProductCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    description: str = Field("", max_length=500)
    image_url: str = ""
    price_usd: float = Field(..., gt=0)
    stock: int = Field(0, ge=0)
    category: str = Field("general", max_length=40)
    is_active: bool = True
    available_store_ids: list[str] = Field(default_factory=list)


class CompanyProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=80)
    description: Optional[str] = Field(None, max_length=500)
    image_url: Optional[str] = None
    price_usd: Optional[float] = Field(None, gt=0)
    stock: Optional[int] = Field(None, ge=0)
    category: Optional[str] = Field(None, max_length=40)
    is_active: Optional[bool] = None
    available_store_ids: Optional[list[str]] = None


async def _validate_store_ids(ids: list[str], company_id: str) -> list[str]:
    """Las sucursales elegidas deben pertenecer a la propia Empresa."""
    clean = list(dict.fromkeys([s for s in (ids or []) if s]))
    if not clean:
        return []
    owned = await _company_store_ids(company_id)
    invalid = [s for s in clean if s not in owned]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail="Alguna sucursal seleccionada no pertenece a tu empresa.")
    return clean


async def _owned_product_or_404(pid: str, company_id: str) -> dict:
    doc = await db.products.find_one(
        {"id": pid, "company_id": company_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return doc


@router.get("/products")
async def list_my_products(request: Request) -> Any:
    user = await require_company(request)
    docs = await db.products.find(
        {"company_id": user["user_id"]}, {"_id": 0}) \
        .sort("created_at", -1).to_list(300)
    ids = [d["id"] for d in docs]
    stats: dict = {}
    if ids:
        agg = await db.redemptions.aggregate([
            {"$match": {"product_id": {"$in": ids},
                        "vendor_owner_id": user["user_id"],
                        "status": {"$ne": "rejected"}}},
            {"$group": {"_id": "$product_id",
                        "sold_qty": {"$sum": "$quantity"},
                        "earned": {"$sum": "$vendor_credit_net"}}},
        ]).to_list(500)
        stats = {a["_id"]: a for a in agg}
    for d in docs:
        st = stats.get(d["id"], {})
        d["sold_qty"] = round(float(st.get("sold_qty", 0) or 0), 3)
        d["earned_usd"] = round(float(st.get("earned") or 0), 2)
    return docs


@router.post("/products")
async def create_my_product(payload: CompanyProductCreate,
                            request: Request) -> Any:
    user = await require_company(request)
    count = await db.products.count_documents({"company_id": user["user_id"]})
    if count >= MAX_PRODUCTS_PER_VENDOR:
        raise HTTPException(
            status_code=400,
            detail=f"Límite de {MAX_PRODUCTS_PER_VENDOR} productos alcanzado")
    store_ids = await _validate_store_ids(
        payload.available_store_ids, user["user_id"])
    image = maybe_upload_proof(payload.image_url, "products") or ""
    p = Product(
        name=payload.name.strip(),
        description=payload.description.strip(),
        image_url=image,
        price_usd=round(float(payload.price_usd), 2),
        cost_usd=0.0,
        stock=payload.stock,
        category=payload.category.strip() or "general",
        is_active=payload.is_active,
        owner_id=user["user_id"],
        owner_name=user["name"],
        approval_status="pending",
        available_store_ids=store_ids,
    )
    doc = p.model_dump()
    doc["company_id"] = user["user_id"]
    await db.products.insert_one(doc)
    try:
        await notify_all_admins(
            db,
            title="Nuevo producto Empresa por aprobar",
            body=f"{user['name']} envió «{p.name}» ({p.price_usd} USDT) al marketplace.",
            url_path="/admin/products",
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"company product notify failed: {e}")
    doc.pop("_id", None)
    return doc


@router.put("/products/{pid}")
async def update_my_product(pid: str, payload: CompanyProductUpdate,
                            request: Request) -> Any:
    user = await require_company(request)
    doc = await _owned_product_or_404(pid, user["user_id"])
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "available_store_ids" in updates:
        updates["available_store_ids"] = await _validate_store_ids(
            updates["available_store_ids"], user["user_id"])
    if not updates:
        return doc
    if "image_url" in updates:
        updates["image_url"] = maybe_upload_proof(
            updates["image_url"], "products") or ""
    if "price_usd" in updates:
        updates["price_usd"] = round(float(updates["price_usd"]), 2)
    resubmitted = doc.get("approval_status") == "rejected"
    if resubmitted:
        updates["approval_status"] = "pending"
        updates["rejection_reason"] = ""
    await db.products.update_one(
        {"id": pid, "company_id": user["user_id"]}, {"$set": updates})
    if resubmitted:
        try:
            await notify_all_admins(
                db,
                title="Producto Empresa re-enviado",
                body=f"{user['name']} corrigió «{updates.get('name', doc['name'])}» y espera aprobación.",
                url_path="/admin/products",
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"company resubmit notify failed: {e}")
    await _publish_products_changed(pid)
    return await db.products.find_one(
        {"id": pid, "company_id": user["user_id"]}, {"_id": 0})


@router.delete("/products/{pid}")
async def delete_my_product(pid: str, request: Request) -> Any:
    user = await require_company(request)
    await _owned_product_or_404(pid, user["user_id"])
    await db.products.delete_one({"id": pid, "company_id": user["user_id"]})
    await _publish_products_changed(pid)
    return {"ok": True}


# ============================================================
# Inventario por ubicación: almacén central + distribución a tiendas (Fase 2)
# ============================================================

class InvReceivePayload(BaseModel):
    product_id: str
    qty: float = Field(..., gt=0)


class InvMovePayload(BaseModel):
    product_id: str
    store_id: str
    qty: float = Field(..., gt=0)


@router.get("/inventory")
async def get_inventory(request: Request) -> Any:
    user = await require_company(request)
    return await company_inventory.build_inventory_rows(user["user_id"])


@router.get("/inventory/moves")
async def get_inventory_moves(request: Request) -> Any:
    user = await require_company(request)
    return await company_inventory.list_moves(user["user_id"])


async def _ensure_owned_product(pid: str, company_id: str) -> None:
    doc = await db.products.find_one(
        {"id": pid, "company_id": company_id}, {"_id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Producto no encontrado")


async def _ensure_owned_store(sid: str, company_id: str) -> None:
    doc = await db.stores.find_one(
        {"id": sid, "company_id": company_id}, {"_id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")


@router.post("/inventory/receive")
async def inventory_receive(payload: InvReceivePayload, request: Request) -> Any:
    user = await require_company(request)
    await _ensure_owned_product(payload.product_id, user["user_id"])
    status = await company_inventory.receive_central(
        user["user_id"], payload.product_id, payload.qty, actor=user)
    if status != "applied":
        raise HTTPException(status_code=400, detail="No se pudo recibir el stock")
    return {"ok": True}


@router.post("/inventory/distribute")
async def inventory_distribute(payload: InvMovePayload, request: Request) -> Any:
    user = await require_company(request)
    await _ensure_owned_product(payload.product_id, user["user_id"])
    await _ensure_owned_store(payload.store_id, user["user_id"])
    status = await company_inventory.distribute(
        user["user_id"], payload.product_id, payload.store_id, payload.qty, actor=user)
    if status == "insufficient":
        raise HTTPException(
            status_code=409,
            detail="No hay suficiente stock en el almacén central para distribuir.")
    if status != "applied":
        raise HTTPException(status_code=400, detail="No se pudo distribuir el stock")
    return {"ok": True}


@router.post("/inventory/return")
async def inventory_return(payload: InvMovePayload, request: Request) -> Any:
    user = await require_company(request)
    await _ensure_owned_product(payload.product_id, user["user_id"])
    await _ensure_owned_store(payload.store_id, user["user_id"])
    status = await company_inventory.return_to_central(
        user["user_id"], payload.product_id, payload.store_id, payload.qty, actor=user)
    if status == "insufficient":
        raise HTTPException(
            status_code=409,
            detail="La tienda no tiene esa cantidad para devolver al central.")
    if status != "applied":
        raise HTTPException(status_code=400, detail="No se pudo devolver el stock")
    return {"ok": True}
