"""Marketplace multivendedor — iter217. Los clientes VIP publican sus propios
productos (con aprobación previa del admin) y reciben el importe de cada venta
en su saldo VIP menos una comisión configurable (settings.vendor_commission_pct).

Endpoints VIP:
- GET    /vendor/commission          % de comisión vigente
- GET    /vip/my-products            mis productos (todos los estados) + ventas
- POST   /vip/my-products            crear (queda 'pending' hasta aprobación)
- PUT    /vip/my-products/{pid}      editar en tiempo real (si estaba rechazado
                                     vuelve a 'pending' para re-revisión)
- DELETE /vip/my-products/{pid}

Endpoints staff (permiso 'products'):
- GET  /admin/vendor-products?status=
- POST /admin/vendor-products/{pid}/approve
- POST /admin/vendor-products/{pid}/reject   {reason}
"""
import logging
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import require_user, require_permission, now_utc, iso
from audit_log import log_action
from admin_alerts import notify_all_admins
from routes.market import Product
from services.proof_upload import maybe_upload_proof

logger = logging.getLogger(__name__)
router = APIRouter(tags=["VendorProducts"])

DEFAULT_COMMISSION_PCT = 5.0
MAX_PRODUCTS_PER_VENDOR = 50

_VENDOR_FILTER = {"owner_id": {"$nin": [None, ""]}}


async def get_commission_pct() -> float:
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
    raw = doc.get("vendor_commission_pct")
    return float(raw) if raw is not None else DEFAULT_COMMISSION_PCT


async def _publish_products_changed(product_id: str) -> None:
    try:
        from services.live_bus import publish
        await publish("products_changed", {"product_id": product_id})
    except Exception as e:  # noqa: BLE001
        logger.error(f"products_changed publish failed: {e}")


def _require_vip(user: dict) -> None:
    if user["role"] not in ("vip", "admin"):
        raise HTTPException(status_code=403, detail="Solo clientes VIP pueden publicar productos")


async def _owned_product_or_404(pid: str, user: dict) -> dict:
    doc = await db.products.find_one({"id": pid, "owner_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return doc


class VendorProductCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    description: str = Field("", max_length=500)
    image_url: str = ""
    price_usd: float = Field(..., gt=0)
    stock: int = Field(0, ge=0)
    category: str = Field("general", max_length=40)
    is_active: bool = True


class VendorProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=80)
    description: Optional[str] = Field(None, max_length=500)
    image_url: Optional[str] = None
    price_usd: Optional[float] = Field(None, gt=0)
    stock: Optional[int] = Field(None, ge=0)
    category: Optional[str] = Field(None, max_length=40)
    is_active: Optional[bool] = None


class VendorRejectPayload(BaseModel):
    reason: str = Field("", max_length=300)


# ============================================================
# VIP (self-service)
# ============================================================

@router.get("/vendor/commission")
async def vendor_commission(request: Request) -> Any:
    await require_user(request)
    return {"commission_pct": await get_commission_pct()}


@router.get("/vip/my-products")
async def my_products(request: Request) -> Any:
    user = await require_user(request)
    _require_vip(user)
    docs = await db.products.find(
        {"owner_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
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
        d["sold_qty"] = int(st.get("sold_qty", 0))
        d["earned_usd"] = round(float(st.get("earned") or 0), 2)
    return docs


@router.post("/vip/my-products")
async def create_my_product(payload: VendorProductCreate, request: Request) -> Any:
    user = await require_user(request)
    _require_vip(user)
    count = await db.products.count_documents({"owner_id": user["user_id"]})
    if count >= MAX_PRODUCTS_PER_VENDOR:
        raise HTTPException(status_code=400,
                            detail=f"Límite de {MAX_PRODUCTS_PER_VENDOR} productos alcanzado")
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
    )
    await db.products.insert_one(p.model_dump())
    try:
        await notify_all_admins(
            db,
            title="Nuevo producto VIP por aprobar",
            body=f"{user['name']} envió «{p.name}» ({p.price_usd} USDT) al marketplace.",
            url_path="/admin/products",
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"vendor product notify failed: {e}")
    return p.model_dump()


@router.put("/vip/my-products/{pid}")
async def update_my_product(pid: str, payload: VendorProductUpdate, request: Request) -> Any:
    user = await require_user(request)
    _require_vip(user)
    doc = await _owned_product_or_404(pid, user)
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        return doc
    if "image_url" in updates:
        updates["image_url"] = maybe_upload_proof(updates["image_url"], "products") or ""
    if "price_usd" in updates:
        updates["price_usd"] = round(float(updates["price_usd"]), 2)
    resubmitted = doc.get("approval_status") == "rejected"
    if resubmitted:
        updates["approval_status"] = "pending"
        updates["rejection_reason"] = ""
    await db.products.update_one({"id": pid}, {"$set": updates})
    if resubmitted:
        try:
            await notify_all_admins(
                db,
                title="Producto VIP re-enviado",
                body=f"{user['name']} corrigió «{updates.get('name', doc['name'])}» y espera aprobación.",
                url_path="/admin/products",
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"vendor resubmit notify failed: {e}")
    await _publish_products_changed(pid)
    return await db.products.find_one({"id": pid}, {"_id": 0})


@router.delete("/vip/my-products/{pid}")
async def delete_my_product(pid: str, request: Request) -> Any:
    user = await require_user(request)
    _require_vip(user)
    await _owned_product_or_404(pid, user)
    await db.products.delete_one({"id": pid})
    await _publish_products_changed(pid)
    return {"ok": True}


# ============================================================
# Staff (aprobación)
# ============================================================

@router.get("/admin/vendor-products")
async def admin_vendor_products(request: Request, status: Optional[str] = None) -> Any:
    await require_permission(request, "products")
    q: dict = dict(_VENDOR_FILTER)
    if status in ("pending", "approved", "rejected"):
        q["approval_status"] = status
    return await db.products.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


async def _vendor_product_or_404(pid: str) -> dict:
    doc = await db.products.find_one({"id": pid, **_VENDOR_FILTER}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Producto de vendedor no encontrado")
    return doc


async def _notify_owner(doc: dict, *, type: str, title: str, message: str) -> None:
    try:
        from routes.notifications import _insert_notification
        await _insert_notification(
            recipient_user_id=doc["owner_id"], type=type, title=title,
            message=message, data={"product_id": doc["id"]})
    except Exception as e:  # noqa: BLE001
        logger.error(f"vendor owner notify failed: {e}")


@router.post("/admin/vendor-products/{pid}/approve")
async def approve_vendor_product(pid: str, request: Request) -> Any:
    actor = await require_permission(request, "products")
    doc = await _vendor_product_or_404(pid)
    await db.products.update_one(
        {"id": pid},
        {"$set": {"approval_status": "approved", "rejection_reason": "",
                  "approved_at": iso(now_utc())}})
    await log_action(db, actor, "vendor_product.approve", "product", pid,
                     summary=f"Producto VIP aprobado: {doc['name']} ({doc.get('owner_name', '')})")
    await _notify_owner(doc, type="vendor_product_approved",
                        title="Producto aprobado",
                        message=f"Tu producto «{doc['name']}» ya está publicado en el marketplace.")
    await _publish_products_changed(pid)
    return await db.products.find_one({"id": pid}, {"_id": 0})


@router.post("/admin/vendor-products/{pid}/reject")
async def reject_vendor_product(pid: str, payload: VendorRejectPayload, request: Request) -> Any:
    actor = await require_permission(request, "products")
    doc = await _vendor_product_or_404(pid)
    reason = payload.reason.strip()
    await db.products.update_one(
        {"id": pid},
        {"$set": {"approval_status": "rejected", "rejection_reason": reason}})
    await log_action(db, actor, "vendor_product.reject", "product", pid,
                     summary=f"Producto VIP rechazado: {doc['name']}",
                     details={"reason": reason})
    await _notify_owner(
        doc, type="vendor_product_rejected", title="Producto rechazado",
        message=(f"Tu producto «{doc['name']}» fue rechazado."
                 + (f" Motivo: {reason}" if reason else "")
                 + " Puedes editarlo y se re-enviará a revisión."))
    await _publish_products_changed(pid)
    return await db.products.find_one({"id": pid}, {"_id": 0})
