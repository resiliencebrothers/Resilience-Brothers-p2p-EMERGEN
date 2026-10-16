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
import json
import hashlib
import logging
from datetime import timedelta
from typing import Any, Literal, Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

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
from services import company_delivery_billing as billing
from services.company_delivery_recovery import (
    reconcile_cancelled_request, return_delivery_inventory)

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
        "delivery_fee_usdt": await billing.get_company_delivery_fee(),
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
    # 5) R06 — barrido final: reubica al central cualquier existencia residual
    #    que una devolución concurrente pudiera haber dejado en by_store durante
    #    el cierre. Idempotente; evita estanterías huérfanas tras el borrado.
    await company_inventory.reclaim_store_shelf_to_central(user["user_id"], store_id)
    return {"ok": True}


# ============================================================
# Catálogo de productos (publica al marketplace tras aprobación admin)
# ============================================================

class CompanyProductCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    description: str = Field("", max_length=500)
    image_url: str = ""
    price_usd: float = Field(..., gt=0)
    # F2-04 — el stock es DECIMAL de extremo a extremo (coherente con el
    # inventario Fase 2). El stock inicial se registra como un movimiento
    # auditado 'receive' (no un $set silencioso).
    stock: float = Field(0, ge=0)
    # F2-04 — unidad de medida: "unidad" NO admite fracciones; "libra"/"kg" sí.
    unit: Literal["unidad", "libra", "kg"] = "unidad"
    # Alerta de stock bajo: umbral del almacén central (0 = sin alerta).
    min_stock: float = Field(0, ge=0)
    category: str = Field("general", max_length=40)
    is_active: bool = True
    available_store_ids: list[str] = Field(default_factory=list)


class CompanyProductUpdate(BaseModel):
    # F2-04 — SOLO metadatos. El `stock` NUNCA se edita por aquí (lo gestionan
    # los movimientos auditados de inventario: recibir/distribuir/devolver/ajustar),
    # para no sobrescribir el stock vigente ni perder decimales.
    name: Optional[str] = Field(None, min_length=2, max_length=80)
    description: Optional[str] = Field(None, max_length=500)
    image_url: Optional[str] = None
    price_usd: Optional[float] = Field(None, gt=0)
    category: Optional[str] = Field(None, max_length=40)
    is_active: Optional[bool] = None
    available_store_ids: Optional[list[str]] = None
    # Umbral de alerta de stock bajo del almacén central (0 = desactiva).
    min_stock: Optional[float] = Field(None, ge=0)


def _reject_fraction(unit: str, qty: float) -> None:
    """F2-04 — coherencia de unidades: un producto 'unidad' no admite fracciones."""
    if unit == "unidad" and not float(qty).is_integer():
        raise HTTPException(
            status_code=400,
            detail="Este producto se maneja por unidades enteras (sin fracciones).")


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
    _reject_fraction(payload.unit, payload.stock)
    store_ids = await _validate_store_ids(
        payload.available_store_ids, user["user_id"])
    image = maybe_upload_proof(payload.image_url, "products") or ""
    p = Product(
        name=payload.name.strip(),
        description=payload.description.strip(),
        image_url=image,
        price_usd=round(float(payload.price_usd), 2),
        cost_usd=0.0,
        stock=0.0,  # el stock inicial entra como movimiento auditado (abajo)
        unit=payload.unit,
        min_stock=payload.min_stock,
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
    # F2-04 — el stock inicial se registra como una entrada auditada en el
    # almacén central (traza en movimientos), nunca como un valor crudo.
    if payload.stock > 0:
        await company_inventory.receive_central(
            user["user_id"], p.id, payload.stock,
            op_key=f"init:{p.id}", actor=user)
        doc["stock"] = company_inventory._q(payload.stock)
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
    # E34-05 — no permitir borrado destructivo si hay envíos ACTIVOS que
    # reservan stock de este producto (mercancía en tránsito que aún debe poder
    # devolverse a una ubicación existente). Hay que cancelar/completar antes.
    active = await db.company_delivery_requests.find_one({
        "company_id": user["user_id"], "product_id": pid,
        "inv_reserved": True, "inv_returned": {"$ne": True},
        "status": {"$nin": ["cancelled", "confirmed"]}}, {"_id": 1})
    if active:
        raise HTTPException(
            status_code=409,
            detail=("No puedes borrar este producto: tiene envíos activos que "
                    "reservan su stock. Cancela o completa esos envíos primero."))
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


class InvAdjustPayload(BaseModel):
    product_id: str
    new_total: float = Field(..., ge=0)
    # CAS: total que el cliente VE al ajustar (control de versión F2-04).
    expected_total: float = Field(..., ge=0)
    op_id: Optional[str] = Field(None, max_length=80)


class StoreMinPayload(BaseModel):
    product_id: str
    store_id: str
    # Umbral POR TIENDA (0 = avisar solo al agotarse). Igual que el mínimo
    # central pero por sucursal, para avisar ANTES de que se agote.
    min_stock: float = Field(0, ge=0)


@router.get("/inventory")
async def get_inventory(request: Request) -> Any:
    user = await require_company(request)
    return await company_inventory.build_inventory_rows(user["user_id"])


@router.get("/inventory/moves")
async def get_inventory_moves(request: Request) -> Any:
    user = await require_company(request)
    return await company_inventory.list_moves(user["user_id"])


async def _ensure_owned_product(pid: str, company_id: str) -> dict:
    doc = await db.products.find_one(
        {"id": pid, "company_id": company_id}, {"_id": 0, "id": 1, "unit": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return doc


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
    prod = await _ensure_owned_product(payload.product_id, user["user_id"])
    _reject_fraction(prod.get("unit", "unidad"), payload.qty)
    status = await company_inventory.receive_central(
        user["user_id"], payload.product_id, payload.qty,
        op_key=payload.op_id, actor=user)
    if status == "conflict":
        raise HTTPException(
            status_code=409,
            detail="La clave de operación ya se usó con datos distintos.")
    if status != "applied":
        raise HTTPException(status_code=400, detail="No se pudo recibir el stock")
    await company_inventory.maybe_alert_low_stock(user["user_id"], payload.product_id)
    return {"ok": True}


@router.post("/inventory/distribute")
async def inventory_distribute(payload: InvMovePayload, request: Request) -> Any:
    user = await require_company(request)
    prod = await _ensure_owned_product(payload.product_id, user["user_id"])
    _reject_fraction(prod.get("unit", "unidad"), payload.qty)
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
    await company_inventory.maybe_alert_low_stock(user["user_id"], payload.product_id)
    await company_inventory.maybe_alert_store_out_of_stock(
        user["user_id"], payload.product_id, payload.store_id)
    return {"ok": True}


@router.post("/inventory/return")
async def inventory_return(payload: InvMovePayload, request: Request) -> Any:
    user = await require_company(request)
    prod = await _ensure_owned_product(payload.product_id, user["user_id"])
    _reject_fraction(prod.get("unit", "unidad"), payload.qty)
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
    await company_inventory.maybe_alert_low_stock(user["user_id"], payload.product_id)
    await company_inventory.maybe_alert_store_out_of_stock(
        user["user_id"], payload.product_id, payload.store_id)
    return {"ok": True}


@router.post("/inventory/adjust")
async def inventory_adjust(payload: InvAdjustPayload, request: Request) -> Any:
    """F2-04 — ajuste ABSOLUTO del total con control de versión y traza."""
    user = await require_company(request)
    prod = await _ensure_owned_product(payload.product_id, user["user_id"])
    _reject_fraction(prod.get("unit", "unidad"), payload.new_total)
    status = await company_inventory.adjust_total(
        user["user_id"], payload.product_id, payload.new_total,
        payload.expected_total, op_key=payload.op_id, actor=user)
    if status == "conflict":
        raise HTTPException(
            status_code=409,
            detail="La clave de operación ya se usó con datos distintos.")
    if status == "stale":
        raise HTTPException(
            status_code=409,
            detail="El stock cambió mientras ajustabas; recarga y vuelve a intentarlo.")
    if status == "below_distributed":
        raise HTTPException(
            status_code=409,
            detail="El total no puede ser menor que lo ya distribuido a tus tiendas.")
    if status != "applied":
        raise HTTPException(status_code=400, detail="No se pudo ajustar el stock")
    await company_inventory.maybe_alert_low_stock(user["user_id"], payload.product_id)
    return {"ok": True}


@router.post("/inventory/store-min")
async def set_store_min(payload: StoreMinPayload, request: Request) -> Any:
    """Configura el UMBRAL de stock bajo POR TIENDA de un producto. Al caer la
    estantería a/por debajo del umbral, la Empresa recibe un aviso (re-armable).
    0 = avisar solo cuando se agote."""
    user = await require_company(request)
    await _ensure_owned_product(payload.product_id, user["user_id"])
    await _ensure_owned_store(payload.store_id, user["user_id"])
    await db.products.update_one(
        {"id": payload.product_id, "company_id": user["user_id"]},
        {"$set": {f"store_min.{payload.store_id}": round(float(payload.min_stock), 3)}})
    # Re-evaluar la alerta con el nuevo umbral (puede disparar o re-armar).
    await company_inventory.maybe_alert_store_out_of_stock(
        user["user_id"], payload.product_id, payload.store_id)
    return {"ok": True, "min_stock": round(float(payload.min_stock), 3)}


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
    # E34-02 — clave de idempotencia por envío LÓGICO (la genera el cliente una
    # vez y la reusa en los reintentos). Misma clave ⇒ misma solicitud.
    client_key: Optional[str] = Field(None, max_length=100)


async def _return_delivery_inventory(company_id: str, req: dict) -> bool:
    """Delegado a services.company_delivery_recovery (E34-05/E34-06)."""
    return await return_delivery_inventory(req)


async def _reconcile_delivery_inventory(company_id: str, req: dict,
                                        delivery_status: str) -> bool:
    """Reconcilia la solicitud si su entrega quedó CANCELADA. Delegado al
    servicio recuperable (E34-06) para compartir la misma lógica idempotente
    con la cancelación admin y el worker del scheduler."""
    if delivery_status != "cancelled":
        return False
    return await reconcile_cancelled_request(req)


_CDELIV_IDX_READY = False


async def _ensure_cdeliv_index() -> None:
    """Índice único (empresa, client_key) para deduplicar el alta de envíos.
    R01 — PARCIAL (no meramente sparse): solo indexa documentos cuyo `client_key`
    es una CADENA. Un índice sparse compuesto SÍ indexa los documentos antiguos
    que tienen `company_id` pero `client_key` ausente (con client_key=null), de
    modo que DOS documentos antiguos de la misma empresa sin clave colisionan
    ('A', null) e impiden crear el índice. El filtro parcial los EXCLUYE por
    completo, por lo que el índice se construye sobre datos antiguos reales sin
    colisiones y sigue garantizando unicidad de las claves válidas nuevas."""
    global _CDELIV_IDX_READY
    if _CDELIV_IDX_READY:
        return
    # R01 — MIGRACIÓN: elimina el índice sparse compuesto ANTIGUO
    # (`company_id_1_client_key_1`). Un sparse compuesto SÍ indexa los documentos
    # que tienen `company_id` pero `client_key` ausente (como client_key=null),
    # de modo que dos documentos antiguos sin clave colisionan ('A', null) e
    # impiden siquiera crear/usar el índice. Se sustituye por un índice PARCIAL
    # que solo indexa `client_key` de tipo cadena (excluye los nulos antiguos).
    try:
        await db.company_delivery_requests.drop_index("company_id_1_client_key_1")
    except Exception:
        pass
    await db.company_delivery_requests.create_index(
        [("company_id", 1), ("client_key", 1)], unique=True,
        partialFilterExpression={"client_key": {"$type": "string"}},
        name="uniq_company_client_key_str")
    _CDELIV_IDX_READY = True


async def _delivery_status_for(req: dict) -> str:
    did = req.get("delivery_id")
    if not did:
        return req.get("status", "requested")
    d = await db.deliveries.find_one({"id": did}, {"_id": 0, "status": 1})
    return (d or {}).get("status", req.get("status", "requested"))


@router.post("/deliveries")
async def create_company_delivery(payload: CompanyDeliveryCreate,
                                  request: Request) -> Any:
    """E34-02 — alta de envío IDEMPOTENTE y RECUPERABLE de extremo a extremo.

    Una `client_key` ESTABLE por envío lógico deduplica reintentos y POSTs
    simultáneos: la MISMA clave ⇒ la MISMA solicitud, un ÚNICO cargo y una
    ÚNICA reserva. Se guarda primero una INTENCIÓN duradera ('initializing') y
    luego se ejecutan fases idempotentes por op_id ligado al reqid: (1) retener
    tarifa, (2) reservar inventario, (3) crear/enlazar el trabajo, (4) activar.
    Un crash a mitad se RETOMA en el reintento (misma clave) o lo COMPENSA el
    recuperador `heal_initializing_company_deliveries` con decisión duradera."""
    user = await require_company(request)
    cid = user["user_id"]
    await _ensure_cdeliv_index()

    # --- Validación PURA (sin escrituras ni cargos): errores limpios sin efectos.
    pid_, sid_, qty_ = payload.product_id, payload.origin_store_id, payload.quantity
    has_inv = bool(pid_ or sid_ or qty_)
    prod = None
    if has_inv:
        if not (pid_ and sid_ and qty_):
            raise HTTPException(
                status_code=400,
                detail="Para despachar desde una tienda indica producto, tienda y cantidad.")
        prod = await db.products.find_one({"id": pid_, "company_id": cid}, {"_id": 0})
        if not prod:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        _reject_fraction(prod.get("unit", "unidad"), qty_)
        await _ensure_owned_store(sid_, cid)

    fee = await billing.get_company_delivery_fee()
    now = iso(now_utc())
    client_key = (payload.client_key or str(uuid.uuid4())).strip()
    package_label = (f"{prod['name']} ×{company_inventory._q(qty_)}" if prod
                     else (payload.note.strip() or "Envío de empresa"))
    # R09 — HUELLA del payload económicamente relevante: una misma `client_key`
    # DEBE corresponder al MISMO envío lógico. Si se reusa la clave con un
    # payload distinto (otro destinatario/dirección/producto/cantidad) se
    # rechaza con conflicto, en vez de reutilizar en silencio la solicitud
    # anterior (que podría cobrar/reservar algo distinto a lo pedido).
    fingerprint = hashlib.sha256(json.dumps({
        "r": payload.receiver_name.strip(), "p": payload.receiver_phone.strip(),
        "a": payload.delivery_address.strip(), "pv": payload.province.strip(),
        "m": payload.municipality.strip(), "pid": pid_, "sid": sid_,
        "q": company_inventory._q(qty_) if qty_ else None,
    }, sort_keys=True).encode()).hexdigest()

    # --- INTENCIÓN duradera (dedup de reintentos y POSTs simultáneos).
    reqid = str(uuid.uuid4())
    intent = {
        "id": reqid, "company_id": cid, "client_key": client_key,
        "payload_fingerprint": fingerprint,
        "company_name": user.get("name", ""),
        "receiver_name": payload.receiver_name.strip(),
        "receiver_phone": payload.receiver_phone.strip(),
        "delivery_address": payload.delivery_address.strip(),
        "province": payload.province.strip(), "municipality": payload.municipality.strip(),
        "note": payload.note.strip(),
        "product_id": pid_, "origin_store_id": sid_, "quantity": qty_,
        "package_label": package_label,
        "inv_reserved": False, "inv_returned": False,
        "fee_usdt": fee, "fee_status": "pending" if fee > 0 else "none",
        "status": "initializing", "delivery_id": None,
        "created_at": now, "updated_at": now,
    }
    try:
        await db.company_delivery_requests.insert_one(dict(intent))
        req = intent
    except DuplicateKeyError:
        req = await db.company_delivery_requests.find_one(
            {"company_id": cid, "client_key": client_key}, {"_id": 0})
        if not req:
            raise HTTPException(status_code=409, detail="Conflicto de clave; reintenta.")
        # R09 — misma clave, payload DISTINTO ⇒ conflicto explícito (nunca se
        # reutiliza la solicitud previa como si fuera este envío).
        if req.get("payload_fingerprint") and req["payload_fingerprint"] != fingerprint:
            raise HTTPException(
                status_code=409,
                detail=("Esa clave de envío ya se usó para una solicitud distinta. "
                        "Crea un envío nuevo (no reutilices una operación anterior)."))
        st = req.get("status")
        if st == "initializing":
            # Reintento/concurrencia: RETOMAR con el MISMO reqid y payload guardado.
            reqid = req["id"]
            fee = float(req.get("fee_usdt") or 0)
            pid_, sid_, qty_ = req.get("product_id"), req.get("origin_store_id"), req.get("quantity")
            has_inv = bool(pid_ and sid_ and qty_)
        elif st == "failed_init":
            # El recuperador ya compensó este envío → pide crear uno nuevo.
            raise HTTPException(
                status_code=409,
                detail="Ese envío no se completó y fue revertido. Vuelve a crearlo.")
        else:
            # Ya creado → devolver el MISMO (idempotente, sin doble efecto).
            return {**req, "delivery_status": await _delivery_status_for(req)}

    # --- FASE 1: retener la tarifa (idempotente por reqid).
    if fee > 0 and req.get("fee_status") != "held":
        hold = await billing.hold_fee(cid, reqid, fee)
        if hold == "insufficient":
            # Aún no hay inventario reservado → elimina la intención (si es nuestra).
            await db.company_delivery_requests.delete_one(
                {"id": reqid, "status": "initializing"})
            raise HTTPException(
                status_code=402,
                detail=(f"Saldo insuficiente: la mensajería cuesta {fee} USDT. "
                        "Recarga tu sub-saldo para solicitar el envío."))
        await db.company_delivery_requests.update_one(
            {"id": reqid}, {"$set": {"fee_status": "held", "updated_at": iso(now_utc())}})

    # --- FASE 2: reservar inventario (idempotente por op cdeliv:{reqid}).
    if has_inv and not req.get("inv_reserved"):
        assert pid_ and sid_ and qty_  # garantizado por has_inv
        status = await company_inventory.dispatch_from_store(
            cid, pid_, sid_, qty_, op_id=f"cdeliv:{reqid}", actor=user)
        if status not in ("applied", "duplicate"):
            # No se pudo reservar → reembolsa la tarifa y elimina la intención.
            await billing.refund_fee(cid, reqid, fee)
            await db.company_delivery_requests.delete_one(
                {"id": reqid, "status": "initializing"})
            detail = ("La tienda no tiene suficiente stock para este envío."
                      if status == "insufficient" else "No se pudo reservar el stock")
            raise HTTPException(
                status_code=409 if status == "insufficient" else 400, detail=detail)
        await db.company_delivery_requests.update_one(
            {"id": reqid}, {"$set": {"inv_reserved": True, "updated_at": iso(now_utc())}})
        await company_inventory.maybe_alert_store_out_of_stock(cid, pid_, sid_)

    # --- FASE 3: crear/enlazar el trabajo (idempotente por active_key).
    from services.deliveries import ensure_delivery_job
    req_for_job = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
    job = await ensure_delivery_job(
        "company_delivery", req_for_job, km=0, fee_usdt=fee, actor_id=cid)

    # --- FASE 4: activar (initializing → requested) y enlazar la entrega.
    # R03 — CAS sobre 'initializing': la ACTIVACIÓN y la COMPENSACIÓN comparten
    # la MISMA decisión terminal. Si el recuperador ya reclamó la fila
    # (initializing → failed_init) y la compensó, este update NO modifica nada
    # y NO resucitamos una solicitud ya revertida: deshacemos el trabajo recién
    # creado y pedimos recrear el envío. Las fases son idempotentes ⇒ dos POSTs
    # con la misma clave convergen al MISMO envío/cargo/reserva.
    activated = await db.company_delivery_requests.update_one(
        {"id": reqid, "status": "initializing"},
        {"$set": {"status": "requested", "delivery_id": job["id"],
                  "updated_at": iso(now_utc())}})
    if activated.modified_count == 0:
        from services.deliveries import cancel_active_delivery
        await cancel_active_delivery(
            "company_delivery", reqid, actor_id="system",
            note="alta de envío revertida (carrera con el recuperador)")
        current = await db.company_delivery_requests.find_one(
            {"id": reqid}, {"_id": 0, "status": 1})
        if (current or {}).get("status") == "requested":
            # Un POST concurrente con la MISMA clave ya la activó → idempotente.
            final = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
            return {**final, "delivery_status": await _delivery_status_for(final)}
        raise HTTPException(
            status_code=409,
            detail="Ese envío no se completó y fue revertido. Vuelve a crearlo.")
    final = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
    return {**final, "delivery_status": job.get("status", "available")}


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
        # Reconcilia in situ: `r` queda con el estado real (inv_returned solo si
        # la mercancía se devolvió efectivamente — E34-05).
        await _reconcile_delivery_inventory(user["user_id"], r, dstatus)
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
    from services.deliveries import publish_delivery_event
    now = iso(now_utc())
    did = req.get("delivery_id")
    won = False
    courier_ids = None
    if did:
        # E34-01 — transición ATÓMICA específica de Empresa. Solo se puede
        # cancelar si la entrega sigue SIN aceptar por un mensajero
        # (available/assigned). El estado se DECIDE EN la escritura, no en una
        # lectura previa: así una aceptación/entrega intercalada hace perder la
        # cancelación en lugar de sobrescribirla.
        res = await db.deliveries.update_one(
            {"id": did, "kind": "company_delivery", "ref_id": req_id,
             "status": {"$in": ["available", "assigned"]},
             "payout_credited": {"$ne": True}},
            {"$set": {"status": "cancelled", "updated_at": now},
             "$unset": {"active_key": ""},
             "$push": {"timeline": {"status": "cancelled", "at": now,
                                    "by": user["user_id"],
                                    "note": "Cancelada por la empresa"}}})
        if res.matched_count:
            won = True  # ganamos la cancelación ahora mismo
        else:
            # No ganamos la escritura: releemos para distinguir conflicto real
            # de EVIDENCIA DURADERA de una cancelación ya ganada (reintento tras
            # caída). Para company_delivery, este handler es el ÚNICO que cancela
            # ⇒ delivery.status=='cancelled' prueba que ya ganó esta solicitud.
            d = await db.deliveries.find_one({"id": did}, {"_id": 0, "status": 1})
            if d and d.get("status") == "cancelled":
                won = True
            else:
                # Aceptada/en camino/entregada/confirmada → CONFLICTO real:
                # 409 SIN ningún efecto económico ni de inventario.
                raise HTTPException(
                    status_code=409,
                    detail="La entrega ya fue aceptada por un mensajero; "
                           "contacta a Resilience para cancelarla.")
        d2 = await db.deliveries.find_one(
            {"id": did}, {"_id": 0, "courier_id": 1, "assigned_to_courier_id": 1})
        if d2 and (d2.get("courier_id") or d2.get("assigned_to_courier_id")):
            courier_ids = [d2.get("courier_id"), d2.get("assigned_to_courier_id")]
    else:
        won = True  # sin entrega asociada (no debería ocurrir)

    # A PARTIR DE AQUÍ la cancelación está GANADA (ahora o por evidencia
    # duradera). Toda compensación es IDEMPOTENTE ⇒ efecto económico único,
    # recuperable ante reintento tras caída.
    if did:
        await publish_delivery_event(did, "cancelled", courier_ids=courier_ids)
    # Reembolsa la tarifa retenida (idempotente, exactamente una vez).
    if req.get("fee_status") == "held":
        await billing.refund_fee(user["user_id"], req_id,
                                 float(req.get("fee_usdt") or 0))
    # Devuelve el inventario reservado y VERIFICA el resultado (E34-05): si la
    # tienda ya no existe, vuelve al central; si no se pudo devolver (producto
    # borrado), NO se sella éxito y queda incidencia pendiente.
    inv_returned = bool(req.get("inv_returned"))
    if req.get("inv_reserved") and not inv_returned:
        inv_returned = await _return_delivery_inventory(user["user_id"], req)
    await db.company_delivery_requests.update_one(
        {"id": req_id},
        {"$set": {"status": "cancelled", "inv_returned": inv_returned,
                  "fee_status": ("refunded" if float(req.get("fee_usdt") or 0) > 0
                                 else req.get("fee_status", "none")),
                  "updated_at": iso(now_utc())}})
    return {"ok": True}


async def _settle_company_delivery(ref_id: str, actor: dict) -> None:
    """Liquidación al CONFIRMARSE la entrega: la tarifa retenida se consume (el
    mensajero ya cobró su parte y Resilience la comisión, por el mecanismo de
    entregas). Marca la solicitud como confirmada y la tarifa como cobrada.

    E34-01 — NUNCA liquida una solicitud CANCELADA: ambos efectos están
    condicionados a status != cancelled, de modo que un origen cancelado no se
    trata como liquidación correcta (si hubiera una contradicción
    entrega-confirmada/solicitud-cancelada, no se borra: la tarifa no se cobra
    sobre lo ya reembolsado)."""
    now = iso(now_utc())
    await db.company_delivery_requests.update_one(
        {"id": ref_id, "status": {"$ne": "cancelled"}},
        {"$set": {"status": "confirmed", "updated_at": now}})
    await db.company_delivery_requests.update_one(
        {"id": ref_id, "status": {"$ne": "cancelled"}, "fee_status": "held"},
        {"$set": {"fee_status": "charged"}})


from services.delivery_settlement import register_settlement_handler  # noqa: E402
register_settlement_handler("company_delivery", _settle_company_delivery)
