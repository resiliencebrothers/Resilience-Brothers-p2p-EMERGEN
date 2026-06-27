"""Market router — iter31. Currencies + Exchange rates + Products.

Endpoints:
- GET    /currencies                       (public)
- POST   /admin/currencies
- PUT    /admin/currencies/{currency_id}
- DELETE /admin/currencies/{currency_id}
- GET    /rates                            (public)
- POST   /admin/rates                      (upsert)
- PUT    /admin/rates/{rate_id}            (+ TOTP + margin-scan side effect)
- DELETE /admin/rates/{rate_id}
- GET    /products                         (active only)
- POST   /admin/products
- PUT    /admin/products/{product_id}
- DELETE /admin/products/{product_id}

Catalog models (Currency, ExchangeRate, Product) are defined here and
re-exported via server.py for legacy callers (the seed endpoint uses them).
"""
import uuid
import logging
from typing import Optional, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import (
    require_staff, _enforce_employee_currency_scope, _enforce_totp_step_up,
    now_utc, iso,
)
from audit_log import log_action


logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# Models
# ============================================================

class Currency(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    code: str
    name: str
    type: Literal["crypto", "fiat"]
    symbol: Optional[str] = ""
    country: Optional[str] = ""
    is_active: bool = True
    payment_account: Optional[str] = ""
    created_at: str = Field(default_factory=lambda: iso(now_utc()))


class CurrencyCreate(BaseModel):
    code: str
    name: str
    type: Literal["crypto", "fiat"]
    symbol: Optional[str] = ""
    country: Optional[str] = ""
    is_active: bool = True
    payment_account: Optional[str] = ""


class ExchangeRate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_code: str
    to_code: str
    rate_normal: float
    rate_vip: float
    real_rate: Optional[float] = None  # real market exit rate; used to compute revenue
    updated_at: str = Field(default_factory=lambda: iso(now_utc()))


class ExchangeRateCreate(BaseModel):
    from_code: str
    to_code: str
    rate_normal: float
    rate_vip: float
    real_rate: Optional[float] = None
    totp_code: Optional[str] = Field(None, max_length=11)


class Product(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    image_url: str = ""
    price_usd: float
    cost_usd: float = 0.0
    stock: int = 0
    category: str = "general"
    is_active: bool = True
    created_at: str = Field(default_factory=lambda: iso(now_utc()))


class ProductCreate(BaseModel):
    name: str
    description: str = ""
    image_url: str = ""
    price_usd: float
    cost_usd: float = 0.0
    stock: int = 0
    category: str = "general"
    is_active: bool = True


# ============================================================
# Currencies
# ============================================================

@router.get("/currencies")
async def list_currencies():
    return await db.currencies.find({}, {"_id": 0}).to_list(500)


@router.post("/admin/currencies")
async def create_currency(payload: CurrencyCreate, request: Request):
    await require_staff(request)
    c = Currency(**payload.model_dump())
    await db.currencies.insert_one(c.model_dump())
    return c.model_dump()


@router.put("/admin/currencies/{currency_id}")
async def update_currency(currency_id: str, payload: CurrencyCreate, request: Request):
    await require_staff(request)
    await db.currencies.update_one({"id": currency_id}, {"$set": payload.model_dump()})
    return await db.currencies.find_one({"id": currency_id}, {"_id": 0})


@router.delete("/admin/currencies/{currency_id}")
async def delete_currency(currency_id: str, request: Request):
    await require_staff(request)
    await db.currencies.delete_one({"id": currency_id})
    return {"ok": True}


# ============================================================
# Exchange rates
# ============================================================

@router.get("/rates")
async def list_rates():
    return await db.rates.find({}, {"_id": 0}).to_list(500)


@router.post("/admin/rates")
async def create_rate(payload: ExchangeRateCreate, request: Request):
    actor = await require_staff(request)
    _enforce_employee_currency_scope(actor, payload.from_code, payload.to_code)
    existing = await db.rates.find_one(
        {"from_code": payload.from_code, "to_code": payload.to_code}, {"_id": 0}
    )
    if existing:
        await db.rates.update_one(
            {"id": existing["id"]},
            {"$set": {**payload.model_dump(), "updated_at": iso(now_utc())}},
        )
        return await db.rates.find_one({"id": existing["id"]}, {"_id": 0})
    r = ExchangeRate(**payload.model_dump())
    await db.rates.insert_one(r.model_dump())
    return r.model_dump()


@router.put("/admin/rates/{rate_id}")
async def update_rate(rate_id: str, payload: ExchangeRateCreate, request: Request):
    actor = await require_staff(request)
    await _enforce_totp_step_up(actor, payload.totp_code, action_label="actualizar tasa")
    _enforce_employee_currency_scope(actor, payload.from_code, payload.to_code)
    old = await db.rates.find_one({"id": rate_id}, {"_id": 0})
    if old:
        _enforce_employee_currency_scope(actor, old["from_code"], old["to_code"])
    rate_data = payload.model_dump(exclude={"totp_code"})
    await db.rates.update_one(
        {"id": rate_id},
        {"$set": {**rate_data, "updated_at": iso(now_utc())}},
    )
    fresh = await db.rates.find_one({"id": rate_id}, {"_id": 0})
    # If real_rate changed, scan pending orders for negative margin and ping admins
    try:
        await _scan_rate_change_margin(old, fresh)
    except Exception as e:
        logger.error(f"Rate update margin scan failed: {e}")
    await log_action(
        db, actor, "rate.update", "rate", rate_id,
        summary=f"Tasa {fresh['from_code']}→{fresh['to_code']} actualizada",
        details={"old": old, "new": fresh},
    )
    return fresh


async def _scan_rate_change_margin(old: Optional[dict], fresh: Optional[dict]):
    """When the real_rate of a pair changes, fan out a warning if any pending
    orders for that pair would now generate a loss. Lazy-imports the helpers
    from server.py to avoid circular dependency at module load."""
    if not fresh or fresh.get("real_rate") is None:
        return
    old_rr = old.get("real_rate") if old else None
    if fresh.get("real_rate") == old_rr:
        return
    from server import _compute_order_profit, notify_all_admins
    pending = await db.orders.find(
        {"from_code": fresh["from_code"], "to_code": fresh["to_code"], "status": "pending"},
        {"_id": 0},
    ).to_list(500)
    losers, total_loss = [], 0.0
    for o in pending:
        p = await _compute_order_profit(o, fresh)
        if p and p["amount"] < 0:
            losers.append(o)
            total_loss += abs(p["amount"])
    if losers:
        await notify_all_admins(
            db,
            title=f"⚠️ {len(losers)} órdenes pendientes en pérdida",
            body=(
                f"Actualizaste la tasa real de {fresh['from_code']}→{fresh['to_code']} a "
                f"{fresh['real_rate']}. {len(losers)} órdenes pendientes generarían pérdida total "
                f"≈ {total_loss:.2f} {fresh['to_code']}."
            ),
            url_path="/admin/orders",
        )


@router.delete("/admin/rates/{rate_id}")
async def delete_rate(rate_id: str, request: Request):
    actor = await require_staff(request)
    existing = await db.rates.find_one({"id": rate_id}, {"_id": 0})
    if existing:
        _enforce_employee_currency_scope(actor, existing["from_code"], existing["to_code"])
    await db.rates.delete_one({"id": rate_id})
    return {"ok": True}


# ============================================================
# Products
# ============================================================

@router.get("/products")
async def list_products():
    return await db.products.find({"is_active": True}, {"_id": 0}) \
        .sort("created_at", -1).to_list(500)


def _check_employee_product_perms(actor: dict, *, editing_price: bool, editing_image: bool):
    """iter21 — admin bypasses. Employees need explicit toggles set in /admin/users."""
    if actor.get("role") == "admin":
        return
    if editing_price and not actor.get("can_edit_product_prices"):
        raise HTTPException(status_code=403, detail="No tienes permiso para modificar precios de productos")
    if editing_image and not actor.get("can_upload_product_images"):
        raise HTTPException(status_code=403, detail="No tienes permiso para subir imágenes de productos")


@router.post("/admin/products")
async def create_product(payload: ProductCreate, request: Request):
    actor = await require_staff(request)
    _check_employee_product_perms(
        actor,
        editing_price=(payload.price_usd is not None and payload.price_usd != 0)
                       or (payload.cost_usd is not None and payload.cost_usd != 0),
        editing_image=bool((payload.image_url or "").strip()),
    )
    p = Product(**payload.model_dump())
    await db.products.insert_one(p.model_dump())
    return p.model_dump()


@router.put("/admin/products/{product_id}")
async def update_product(product_id: str, payload: ProductCreate, request: Request):
    actor = await require_staff(request)
    existing = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    price_changed = (
        float(payload.price_usd) != float(existing.get("price_usd", 0))
        or float(payload.cost_usd) != float(existing.get("cost_usd", 0))
    )
    image_changed = (payload.image_url or "") != (existing.get("image_url") or "")
    _check_employee_product_perms(actor, editing_price=price_changed, editing_image=image_changed)
    await db.products.update_one({"id": product_id}, {"$set": payload.model_dump()})
    return await db.products.find_one({"id": product_id}, {"_id": 0})


@router.delete("/admin/products/{product_id}")
async def delete_product(product_id: str, request: Request):
    actor = await require_staff(request)
    if actor.get("role") != "admin" and not actor.get("can_delete_products"):
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar productos")
    await db.products.delete_one({"id": product_id})
    return {"ok": True}
