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
    # F2-03 — cierre RECUPERABLE (no deja carrera entre comprobación y borrado):
    # 1) Marca la tienda como "closing" (cerrada a nuevos movimientos) SIN borrar
    #    su identidad. Así, si el proceso se interrumpe, un nuevo DELETE la vuelve
    #    a encontrar y REANUDA el cierre en vez de devolver 404.
    marked = await db.stores.find_one_and_update(
        {"id": store_id, "company_id": user["user_id"]},
        {"$set": {"status": "closing", "closing_at": iso(now_utc())}},
        projection={"_id": 0, "id": 1})
    if marked is None:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    # 2) Devuelve TODA la mercancía distribuida al almacén central (atómico por
    #    producto, idempotente y reanudable; conserva distributed == suma(by_store)).
    await company_inventory.release_store(user["user_id"], store_id)
    # 3) Quita la tienda de la disponibilidad de los productos que la referenciaban.
    await db.products.update_many(
        {"company_id": user["user_id"]},
        {"$pull": {"available_store_ids": store_id}})
    # 4) Solo cuando el cierre terminó por completo, elimina la identidad.
    await db.stores.delete_one(
        {"id": store_id, "company_id": user["user_id"]})
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
    # F2-02 — clave estable de operación (el cliente la conserva en reintentos).
    op_id: Optional[str] = Field(None, max_length=80)


class InvMovePayload(BaseModel):
    product_id: str
    store_id: str
    qty: float = Field(..., gt=0)
    op_id: Optional[str] = Field(None, max_length=80)


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
        {"id": sid, "company_id": company_id}, {"_id": 1, "status": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    # F2-03 — una tienda en cierre no admite nuevos movimientos de inventario.
    if doc.get("status") == "closing":
        raise HTTPException(
            status_code=409,
            detail="La tienda se está cerrando; no admite nuevos movimientos.")


@router.post("/inventory/receive")
async def inventory_receive(payload: InvReceivePayload, request: Request) -> Any:
    user = await require_company(request)
    await _ensure_owned_product(payload.product_id, user["user_id"])
    status = await company_inventory.receive_central(
        user["user_id"], payload.product_id, payload.qty,
        op_key=payload.op_id, actor=user)
    if status == "conflict":
        raise HTTPException(
            status_code=409,
            detail="La clave de operación ya se usó con datos distintos.")
    if status != "applied":
        raise HTTPException(status_code=400, detail="No se pudo recibir el stock")
    return {"ok": True}


@router.post("/inventory/distribute")
async def inventory_distribute(payload: InvMovePayload, request: Request) -> Any:
    user = await require_company(request)
    await _ensure_owned_product(payload.product_id, user["user_id"])
    await _ensure_owned_store(payload.store_id, user["user_id"])
    status = await company_inventory.distribute(
        user["user_id"], payload.product_id, payload.store_id, payload.qty,
        op_key=payload.op_id, actor=user)
    if status == "conflict":
        raise HTTPException(
            status_code=409,
            detail="La clave de operación ya se usó con datos distintos.")
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
        user["user_id"], payload.product_id, payload.store_id, payload.qty,
        op_key=payload.op_id, actor=user)
    if status == "conflict":
        raise HTTPException(
            status_code=409,
            detail="La clave de operación ya se usó con datos distintos.")
    if status == "insufficient":
        raise HTTPException(
            status_code=409,
            detail="La tienda no tiene esa cantidad para devolver al central.")
    if status != "applied":
        raise HTTPException(status_code=400, detail="No se pudo devolver el stock")
    return {"ok": True}



# ============================================================
# Solicitar mensajería (Fase 4): la Empresa PIDE un envío; Resilience asigna
# el mensajero. La Empresa NO puede elegir/asignar mensajeros.
# ============================================================

class CompanyDeliveryCreate(BaseModel):
    receiver_name: str = Field(..., min_length=2, max_length=120)
    receiver_phone: str = Field(..., min_length=5, max_length=40)
    delivery_address: str = Field(..., min_length=5, max_length=400)
    province: str = Field("", max_length=80)
    municipality: str = Field("", max_length=80)
    note: str = Field("", max_length=300)
    # Origen opcional en inventario: despachar un producto DESDE una tienda
    # (descuenta esa tienda). Si se omite, es un envío sin vínculo de inventario.
    product_id: Optional[str] = None
    origin_store_id: Optional[str] = None
    quantity: Optional[float] = Field(None, gt=0)


async def _reconcile_delivery_inventory(company_id: str, req: dict,
                                        delivery_status: str) -> bool:
    """Si la entrega quedó CANCELADA (p. ej. por el admin) y había inventario
    reservado sin devolver, lo devuelve al origen EXACTAMENTE UNA VEZ."""
    if (req.get("inv_reserved") and not req.get("inv_returned")
            and delivery_status == "cancelled"):
        await company_inventory.return_dispatch(
            company_id, req["product_id"], req["origin_store_id"],
            req["quantity"], op_id=f"cdeliv-ret:{req['id']}")
        await db.company_delivery_requests.update_one(
            {"id": req["id"]},
            {"$set": {"inv_returned": True, "status": "cancelled",
                      "updated_at": iso(now_utc())}})
        return True
    return False


@router.post("/deliveries")
async def create_company_delivery(payload: CompanyDeliveryCreate,
                                  request: Request) -> Any:
    user = await require_company(request)
    reqid = str(uuid.uuid4())
    inv_reserved = False
    package_label = payload.note.strip() or "Envío de empresa"
    pid_ = payload.product_id
    sid_ = payload.origin_store_id
    qty_ = payload.quantity
    if pid_ or sid_ or qty_:
        if not (pid_ and sid_ and qty_):
            raise HTTPException(
                status_code=400,
                detail="Para despachar desde una tienda indica producto, tienda y cantidad.")
        prod = await db.products.find_one(
            {"id": pid_, "company_id": user["user_id"]}, {"_id": 0})
        if not prod:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        await _ensure_owned_store(sid_, user["user_id"])
        status = await company_inventory.dispatch_from_store(
            user["user_id"], pid_, sid_, qty_,
            op_id=f"cdeliv:{reqid}", actor=user)
        if status == "insufficient":
            raise HTTPException(
                status_code=409,
                detail="La tienda no tiene suficiente stock para este envío.")
        if status != "applied":
            raise HTTPException(status_code=400, detail="No se pudo reservar el stock")
        inv_reserved = True
        package_label = f"{prod['name']} ×{company_inventory._q(qty_)}"

    now = iso(now_utc())
    req = {
        "id": reqid,
        "company_id": user["user_id"],
        "company_name": user.get("name", ""),
        "receiver_name": payload.receiver_name.strip(),
        "receiver_phone": payload.receiver_phone.strip(),
        "delivery_address": payload.delivery_address.strip(),
        "province": payload.province.strip(),
        "municipality": payload.municipality.strip(),
        "note": payload.note.strip(),
        "product_id": payload.product_id,
        "origin_store_id": payload.origin_store_id,
        "quantity": payload.quantity,
        "package_label": package_label,
        "inv_reserved": inv_reserved,
        "inv_returned": False,
        "status": "requested",
        "delivery_id": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.company_delivery_requests.insert_one(dict(req))
    # Crea el trabajo de mensajería (entra al pool de Resilience, sin mensajero).
    from services.deliveries import ensure_delivery_job
    job = await ensure_delivery_job(
        "company_delivery", req, km=0, fee_usdt=0, actor_id=user["user_id"])
    await db.company_delivery_requests.update_one(
        {"id": reqid}, {"$set": {"delivery_id": job["id"]}})
    req["delivery_id"] = job["id"]
    req.pop("_id", None)
    return {**req, "delivery_status": "available"}


@router.get("/deliveries")
async def list_company_deliveries(request: Request) -> Any:
    user = await require_company(request)
    reqs = await db.company_delivery_requests.find(
        {"company_id": user["user_id"]}, {"_id": 0}) \
        .sort("created_at", -1).to_list(200)
    dids = [r["delivery_id"] for r in reqs if r.get("delivery_id")]
    dmap = {}
    if dids:
        for d in await db.deliveries.find(
                {"id": {"$in": dids}},
                {"_id": 0, "id": 1, "status": 1, "courier_name": 1,
                 "delivery_pin": 1}).to_list(500):
            dmap[d["id"]] = d
    out = []
    for r in reqs:
        d = dmap.get(r.get("delivery_id")) or {}
        dstatus = d.get("status") or r.get("status")
        if await _reconcile_delivery_inventory(user["user_id"], r, dstatus):
            r["inv_returned"] = True
        out.append({**r, "delivery_status": dstatus,
                    "courier_name": d.get("courier_name"),
                    "delivery_pin": d.get("delivery_pin")})
    return out


@router.post("/deliveries/{req_id}/cancel")
async def cancel_company_delivery(req_id: str, request: Request) -> Any:
    user = await require_company(request)
    req = await db.company_delivery_requests.find_one(
        {"id": req_id, "company_id": user["user_id"]}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if req.get("status") == "cancelled":
        return {"ok": True}
    from services.deliveries import cancel_active_delivery, publish_delivery_event
    d = await db.deliveries.find_one(
        {"id": req.get("delivery_id")},
        {"_id": 0, "status": 1, "courier_id": 1, "assigned_to_courier_id": 1})
    if d and d["status"] not in ("available", "assigned"):
        raise HTTPException(
            status_code=409,
            detail="La entrega ya fue aceptada por un mensajero; contacta a Resilience para cancelarla.")
    res = await cancel_active_delivery(
        "company_delivery", req_id, actor_id=user["user_id"],
        note="Cancelada por la empresa")
    if res.matched_count and req.get("delivery_id"):
        await publish_delivery_event(
            req["delivery_id"], "cancelled",
            courier_ids=None if (not d or d["status"] == "available")
            else [d.get("courier_id"), d.get("assigned_to_courier_id")])
    # Devuelve el inventario reservado (idempotente, exactamente una vez).
    if req.get("inv_reserved") and not req.get("inv_returned"):
        await company_inventory.return_dispatch(
            user["user_id"], req["product_id"], req["origin_store_id"],
            req["quantity"], op_id=f"cdeliv-ret:{req_id}")
    await db.company_delivery_requests.update_one(
        {"id": req_id},
        {"$set": {"status": "cancelled", "inv_returned": True,
                  "updated_at": iso(now_utc())}})
    return {"ok": True}
