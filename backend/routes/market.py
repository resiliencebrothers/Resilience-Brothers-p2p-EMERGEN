"""Market router — iter31. Currencies + Exchange rates + Products.

Endpoints:
- GET    /currencies                       (public)
- GET    /currencies/{code}/delivery-methods (public, iter43)
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
from typing import Optional, Literal, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from db_client import db
from auth_utils import (
    require_staff, require_permission,
    _enforce_employee_currency_scope, _enforce_totp_step_up,
    now_utc, iso,
)
from audit_log import log_action
from services.delivery_rules import allowed_delivery_methods


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Market"])


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
    # iter44 — admin-controlled override of the heuristic in
    # `services/delivery_rules.allowed_delivery_methods`. When set (non-empty),
    # this list wins over the name-based detection. Empty/None falls back to
    # the heuristic so existing currencies keep their behaviour.
    delivery_methods: Optional[list[Literal["transfer", "cash", "crypto"]]] = None
    created_at: str = Field(default_factory=lambda: iso(now_utc()))

    @field_validator("code", mode="before")
    @classmethod
    def _strip_code(cls, v: Any) -> Any:
        # iter55.3 — defensively trim whitespace so data-entry mistakes never
        # break catalog lookups downstream (see admin_company_funds validation).
        return v.strip().upper() if isinstance(v, str) else v


class CurrencyCreate(BaseModel):
    code: str
    name: str
    type: Literal["crypto", "fiat"]
    symbol: Optional[str] = ""
    country: Optional[str] = ""
    is_active: bool = True
    payment_account: Optional[str] = ""
    delivery_methods: Optional[list[Literal["transfer", "cash", "crypto"]]] = None

    @field_validator("code", mode="before")
    @classmethod
    def _strip_code(cls, v: Any) -> Any:
        return v.strip().upper() if isinstance(v, str) else v


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
async def list_currencies() -> Any:
    # iter55.3 — normalise stored codes on read so legacy rows with trailing
    # spaces (e.g. `"CUP "`) do not break frontend dropdowns or downstream
    # lookups (see admin_company_funds.create_company_fund_adjustment).
    rows = await db.currencies.find({}, {"_id": 0}).to_list(500)
    for r in rows:
        if isinstance(r.get("code"), str):
            r["code"] = r["code"].strip().upper()
    return rows


@router.get("/currencies/{code}/delivery-methods")
async def get_currency_delivery_methods(code: str) -> Any:
    """Public — source of truth for the frontend dropdown filter.

    Returns the list of physical delivery methods allowed for receiving the
    given destination currency, computed via `services.delivery_rules`:
      1. explicit `delivery_methods=[…]` set on the currency document, OR
      2. heuristic by `type` + name (`CUPT — transferencia` → `["transfer"]`).

    `accumulate` is intentionally NOT included in the response — it is always
    permitted (role-gated to VIP at order-creation time) and represents the
    "keep as balance" branch with no physical delivery.

    404 if the currency code does not exist.
    """
    norm = code.strip().upper()
    currency = await _find_currency_lenient(norm)
    if not currency:
        raise HTTPException(status_code=404, detail=f"Currency '{code}' not found")
    return {
        "code": norm,
        "type": currency.get("type"),
        "name": currency.get("name"),
        "allowed": allowed_delivery_methods(currency),
    }


async def _find_currency_lenient(code: str) -> Optional[dict]:
    """iter55.3 — resilient currency lookup that survives trailing-whitespace
    data corruption in the `code` column. Falls back to a case-insensitive
    regex that also matches ` code ` (surrounding whitespace)."""
    norm = code.strip().upper()
    hit = await db.currencies.find_one({"code": norm}, {"_id": 0})
    if hit:
        return hit
    # Escape regex special chars and match trimmed
    import re
    pattern = f"^\\s*{re.escape(norm)}\\s*$"
    return await db.currencies.find_one(
        {"code": {"$regex": pattern, "$options": "i"}}, {"_id": 0}
    )


@router.post("/admin/currencies")
async def create_currency(payload: CurrencyCreate, request: Request) -> Any:
    await require_permission(request, "currencies")
    c = Currency(**payload.model_dump())
    await db.currencies.insert_one(c.model_dump())
    return c.model_dump()


@router.put("/admin/currencies/{currency_id}")
async def update_currency(currency_id: str, payload: CurrencyCreate, request: Request) -> Any:
    await require_permission(request, "currencies")
    await db.currencies.update_one({"id": currency_id}, {"$set": payload.model_dump()})
    return await db.currencies.find_one({"id": currency_id}, {"_id": 0})


@router.delete("/admin/currencies/{currency_id}")
async def delete_currency(currency_id: str, request: Request) -> Any:
    await require_permission(request, "currencies")
    await db.currencies.delete_one({"id": currency_id})
    return {"ok": True}


# ============================================================
# Exchange rates
# ============================================================

@router.get("/rates")
async def list_rates() -> Any:
    return await db.rates.find({}, {"_id": 0}).to_list(500)


@router.post("/admin/rates")
async def create_rate(payload: ExchangeRateCreate, request: Request) -> Any:
    actor = await require_staff(request)
    _enforce_employee_currency_scope(actor, payload.from_code, payload.to_code)
    existing = await db.rates.find_one(
        {"from_code": payload.from_code, "to_code": payload.to_code}, {"_id": 0}
    )
    if existing:
        rate_data = payload.model_dump(exclude={"totp_code"})
        await db.rates.update_one(
            {"id": existing["id"]},
            {"$set": {**rate_data, "updated_at": iso(now_utc())}},
        )
        fresh = await db.rates.find_one({"id": existing["id"]}, {"_id": 0})
        # iter55.5 — mirror PUT: fanout push when the customer-facing rate moves
        # so this alternate upsert path notifies clients too.
        try:
            await _fanout_rate_change_push(existing, fresh)
        except Exception as e:
            logger.error(f"Rate upsert push fanout failed: {e}")
        return fresh
    r = ExchangeRate(**payload.model_dump(exclude={"totp_code"}))
    await db.rates.insert_one(r.model_dump())
    # New rate: fanout with old=None → first-ever normal/vip values count as a change
    try:
        await _fanout_rate_change_push(None, r.model_dump())
    except Exception as e:
        logger.error(f"Rate create push fanout failed: {e}")
    return r.model_dump()


@router.put("/admin/rates/{rate_id}")
async def update_rate(rate_id: str, payload: ExchangeRateCreate, request: Request) -> Any:
    actor = await require_permission(request, "rates")
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
    # iter55 — fanout push notification to all clients when the customer-facing
    # rate actually changed (ignore no-op saves like updating only real_rate).
    try:
        await _fanout_rate_change_push(old, fresh)
    except Exception as e:
        logger.error(f"Rate change push fanout failed: {e}")
    await log_action(
        db, actor, "rate.update", "rate", rate_id,
        summary=f"Tasa {fresh['from_code']}→{fresh['to_code']} actualizada",
        details={"old": old, "new": fresh},
    )
    return fresh


async def _rate_fanout_inapp(
    clients: list, from_code: str, to_code: str,
    old_normal: float, old_vip: float, new_normal: float, new_vip: float,
) -> int:
    """Insert an in-app `rate_change` notification for every active client.
    Returns the number of notifications successfully inserted."""
    from routes.notifications import _insert_notification
    inapp_created = 0
    for u in clients:
        rate = new_vip if u["role"] == "vip" else new_normal
        try:
            await _insert_notification(
                recipient_user_id=u["user_id"],
                type="rate_change",
                title=f"Nueva tasa {from_code} → {to_code}",
                message=(
                    f"1 {from_code} = {rate:g} {to_code}"
                    + (" (tarifa VIP)" if u["role"] == "vip" else "")
                    + "."
                ),
                data={
                    "from_code": from_code, "to_code": to_code,
                    "rate_normal": new_normal, "rate_vip": new_vip,
                    "old_rate_normal": old_normal, "old_rate_vip": old_vip,
                },
            )
            inapp_created += 1
        except Exception as e:  # noqa: BLE001
            logger.error(f"[rate-fanout] inapp insert failed for {u.get('user_id')}: {e}")
    return inapp_created


async def _rate_fanout_push(
    role_by_id: dict, from_code: str, to_code: str,
    new_normal: float, new_vip: float,
) -> tuple[int, int, int]:
    """Push the new rate to every subscribed device belonging to an active
    vip/normal client. Prunes dead subscriptions. Returns (sent, skipped, dead)."""
    from push_service import build_rate_changed_payload, send_push
    subs = await db.push_subscriptions.find({}, {"_id": 0}).to_list(5000)
    dead_ids: list[str] = []
    sent, skipped, dead = 0, 0, 0
    for sub in subs:
        role = role_by_id.get(sub.get("user_id"))
        if role not in ("vip", "normal"):
            skipped += 1
            continue
        payload = build_rate_changed_payload(
            from_code, to_code, new_normal, new_vip, for_role=role,
        )
        result = send_push(sub.get("subscription"), payload)
        if result == "dead":
            dead_ids.append(sub["id"])
            dead += 1
        elif result == "ok":
            sent += 1
        else:  # disabled / transient
            skipped += 1
    if dead_ids:
        await db.push_subscriptions.delete_many({"id": {"$in": dead_ids}})
    return sent, skipped, dead


async def _fanout_rate_change_push(old: Optional[dict], fresh: Optional[dict]) -> None:
    """Notify every client (role vip/normal) about the rate change via BOTH:
    1) In-app notification (`db.notifications`) — every active client gets it,
       whether or not they subscribed to push.
    2) Web Push — only devices that opted in through the bell toggle.
    Skipped when neither `rate_normal` nor `rate_vip` moved."""
    if not fresh:
        logger.info("[rate-fanout] skipped: no fresh rate")
        return
    pair = f"{fresh.get('from_code')}→{fresh.get('to_code')}"
    old_normal = float((old or {}).get("rate_normal") or 0.0)
    old_vip = float((old or {}).get("rate_vip") or 0.0)
    new_normal = float(fresh.get("rate_normal") or 0.0)
    new_vip = float(fresh.get("rate_vip") or 0.0)
    if new_normal == old_normal and new_vip == old_vip:
        logger.info(f"[rate-fanout] {pair}: no-op (rates unchanged)")
        return

    from_code, to_code = fresh["from_code"], fresh["to_code"]
    clients = await db.users.find(
        {"role": {"$in": ["vip", "normal"]}, "account_status": {"$ne": "suspended"}},
        {"_id": 0, "user_id": 1, "role": 1},
    ).to_list(20000)

    inapp_created = await _rate_fanout_inapp(
        clients, from_code, to_code, old_normal, old_vip, new_normal, new_vip,
    )
    role_by_id = {u["user_id"]: u["role"] for u in clients}
    sent, skipped, dead = await _rate_fanout_push(
        role_by_id, from_code, to_code, new_normal, new_vip,
    )
    logger.info(
        f"[rate-fanout] {pair}: clients={len(clients)} inapp={inapp_created} "
        f"push_sent={sent} push_dead_pruned={dead} push_skipped={skipped} "
        f"delta_normal={old_normal}→{new_normal} delta_vip={old_vip}→{new_vip}"
    )


async def _scan_rate_change_margin(old: Optional[dict], fresh: Optional[dict]) -> Any:
    """When the real_rate of a pair changes, fan out a warning if any pending
    orders for that pair would now generate a loss."""
    if not fresh or fresh.get("real_rate") is None:
        return
    old_rr = old.get("real_rate") if old else None
    if fresh.get("real_rate") == old_rr:
        return
    from services.orders_helpers import compute_order_profit
    from admin_alerts import notify_all_admins
    pending = await db.orders.find(
        {"from_code": fresh["from_code"], "to_code": fresh["to_code"], "status": "pending"},
        {"_id": 0},
    ).to_list(500)
    losers, total_loss = [], 0.0
    for o in pending:
        p = await compute_order_profit(o, fresh)
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
async def delete_rate(rate_id: str, request: Request) -> Any:
    actor = await require_permission(request, "rates")
    existing = await db.rates.find_one({"id": rate_id}, {"_id": 0})
    if existing:
        _enforce_employee_currency_scope(actor, existing["from_code"], existing["to_code"])
    await db.rates.delete_one({"id": rate_id})
    return {"ok": True}


# ============================================================
# Products
# ============================================================

@router.get("/products")
async def list_products() -> Any:
    return await db.products.find({"is_active": True}, {"_id": 0}) \
        .sort("created_at", -1).to_list(500)


def _check_employee_product_perms(actor: dict, *, editing_price: bool, editing_image: bool) -> Any:
    """iter21 — admin bypasses. Employees need explicit toggles set in /admin/users."""
    if actor.get("role") == "admin":
        return
    if editing_price and not actor.get("can_edit_product_prices"):
        raise HTTPException(status_code=403, detail="No tienes permiso para modificar precios de productos")
    if editing_image and not actor.get("can_upload_product_images"):
        raise HTTPException(status_code=403, detail="No tienes permiso para subir imágenes de productos")


@router.post("/admin/products")
async def create_product(payload: ProductCreate, request: Request) -> Any:
    actor = await require_permission(request, "products")
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
async def update_product(product_id: str, payload: ProductCreate, request: Request) -> Any:
    actor = await require_permission(request, "products")
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
async def delete_product(product_id: str, request: Request) -> Any:
    actor = await require_permission(request, "products")
    if actor.get("role") != "admin" and not actor.get("can_delete_products"):
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar productos")
    await db.products.delete_one({"id": product_id})
    return {"ok": True}
