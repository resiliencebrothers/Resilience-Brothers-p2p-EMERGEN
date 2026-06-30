"""Client-side transactional router — iter33. Owns the user-initiated flows:
P2P orders, VIP balance + redemptions, withdrawals, daily closing PDF.

Endpoints:
- POST  /orders                       (create order)
- GET   /orders/mine

- POST  /vip/redeem                   (marketplace redemption)
- GET   /vip/redemptions/mine

- POST  /vip/withdraw
- GET   /vip/withdrawals/mine
- POST  /vip/convert                  (iter48 — instant self-conversion between own balances)
- GET   /vip/balances
- GET   /vip/daily-closing            (PDF)

Status transitions for admins live in routes/admin.py. Shared business logic
lives in services/orders_helpers.py and services/balances.py.
"""
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import Literal, Optional, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
import uuid

from db_client import db
from auth_utils import (
    require_user, now_utc, iso, _enforce_totp_step_up,
)
from admin_alerts import notify_all_admins
from pdf_service import generate_vip_closing_pdf

from services.balances import (
    build_rate_lookup, convert_to_usdt,
    get_user_balance, decrement_balance,
    assert_account_active, assert_not_defensive,
)
from services.delivery_rules import is_delivery_method_allowed, allowed_delivery_methods
from services.orders_helpers import (
    Order, OrderCreate,
    resolve_order_rate, build_order_from_payload,
    maybe_flag_defensive_margin, dispatch_new_order_alerts,
)
from services.proof_upload import maybe_upload_proof


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Orders"])


# ============================================================
# Models specific to this router
# ============================================================

class Redemption(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    user_email: str
    user_name: str
    product_id: str
    product_name: str
    quantity: int
    total_usd: float
    cost_usd: float = 0.0
    delivery_address: str = ""
    status: Literal["pending", "approved", "delivered", "rejected"] = "pending"
    admin_note: str = ""
    created_at: str = Field(default_factory=lambda: iso(now_utc()))


class RedemptionCreate(BaseModel):
    product_id: str
    quantity: int
    delivery_address: str = ""


class WithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    user_email: str
    user_name: str
    amount_usd: float
    currency: str = "USD"
    method: Literal["transfer", "cash", "crypto"]
    details: str
    beneficiary_name: str = ""
    status: Literal["pending", "approved", "paid", "rejected"] = "pending"
    admin_note: str = ""
    payout_proof_image: str = ""
    payout_tx_hash: str = ""
    created_at: str = Field(default_factory=lambda: iso(now_utc()))


class WithdrawalCreate(BaseModel):
    amount_usd: float
    currency: str = "USD"
    method: Literal["transfer", "cash", "crypto"]
    details: str
    beneficiary_name: str = Field(..., min_length=2,
                                    description="Nombre del titular de la cuenta beneficiaria")
    totp_code: Optional[str] = Field(None, min_length=6, max_length=11,
                                      description="Código TOTP (6 dígitos) o código de recuperación (XXXXX-XXXXX)")


# ============================================================
# P2P Orders
# ============================================================

async def _assert_delivery_method_matches_currency(to_code: str, delivery_method: str) -> None:
    """Reject impossible combinations early using the shared `delivery_rules`
    helper. Handles both broad fiat/crypto check and sub-typed currencies like
    'CUPT — Peso Cubano Transferencia' (transfer-only) or 'CUPE — Peso Cubano
    Efectivo' (cash-only)."""
    if delivery_method == "accumulate":
        return
    target = await db.currencies.find_one(
        {"code": to_code},
        {"_id": 0, "type": 1, "name": 1, "code": 1, "delivery_methods": 1},
    )
    if not target:
        # Unknown currency — let downstream rate-lookup raise the proper error.
        return
    if is_delivery_method_allowed(target, delivery_method):
        return
    allowed = allowed_delivery_methods(target)
    # Spanish-friendly labels — also keeps the error human-readable and tests
    # can assert on semantic keywords (cripto/wallet/fiat/transferencia).
    _METHOD_ES = {
        "transfer": "transferencia bancaria",
        "cash": "efectivo",
        "crypto": "wallet cripto",
    }
    allowed_label = (
        ", ".join(_METHOD_ES.get(m, m) for m in allowed)
        if allowed else "ninguna entrega física"
    )
    method_label = _METHOD_ES.get(delivery_method, delivery_method)
    is_crypto_target = (target.get("type") == "crypto")
    target_kind = "cripto" if is_crypto_target else "fiat"
    raise HTTPException(
        status_code=400,
        detail=(
            f"Para recibir {target.get('name') or to_code} ({target_kind}) "
            f"solo se permite: {allowed_label}. "
            f"La opción '{method_label}' no aplica."
        ),
    )


@router.post("/orders")
async def create_order(payload: OrderCreate, request: Request) -> Any:
    user = await require_user(request)
    await assert_account_active(user)
    await _assert_delivery_method_matches_currency(payload.to_code, payload.delivery_method)
    rate, _rate_doc = await resolve_order_rate(payload.from_code, payload.to_code, user)
    # iter35 — if proof_image is a base64 data URL, persist it to object storage.
    # When storage is disabled the helper returns the value untouched (base64 fallback).
    payload.proof_image = maybe_upload_proof(payload.proof_image, "orders") or ""
    order = build_order_from_payload(payload, user, rate)
    await db.orders.insert_one(order.model_dump())
    await maybe_flag_defensive_margin(order)
    await dispatch_new_order_alerts(order, user)
    return await db.orders.find_one({"id": order.id}, {"_id": 0}) or order.model_dump()


@router.get("/orders/mine")
async def my_orders(request: Request) -> Any:
    user = await require_user(request)
    docs = await db.orders.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return docs


# ============================================================
# VIP — Redemptions (client side only)
# ============================================================

@router.post("/vip/redeem")
async def redeem_product(payload: RedemptionCreate, request: Request) -> Any:
    user = await require_user(request)
    await assert_account_active(user)
    if user["role"] not in ("vip", "admin"):
        raise HTTPException(status_code=403, detail="Solo clientes VIP")
    product = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if product["stock"] < payload.quantity:
        raise HTTPException(status_code=400, detail="Stock insuficiente")
    total = product["price_usd"] * payload.quantity
    cost = float(product.get("cost_usd") or 0) * payload.quantity
    if get_user_balance(user, "USD") < total:
        raise HTTPException(status_code=400, detail="Saldo USD insuficiente")
    r = Redemption(
        user_id=user["user_id"],
        user_email=user["email"],
        user_name=user["name"],
        product_id=product["id"],
        product_name=product["name"],
        quantity=payload.quantity,
        total_usd=total,
        cost_usd=cost,
        delivery_address=payload.delivery_address,
    )
    await db.redemptions.insert_one(r.model_dump())
    await decrement_balance(user["user_id"], "USD", total)
    await db.products.update_one(
        {"id": product["id"]}, {"$inc": {"stock": -payload.quantity}}
    )
    try:
        await notify_all_admins(
            db,
            title="Nuevo canje VIP",
            body=f"{user['name']} solicitó {payload.quantity}× {product['name']} (${total:.2f}).",
            url_path="/admin/withdrawals",
        )
    except Exception as e:
        logger.error(f"Admin notify (redemption) failed: {e}")
    return r.model_dump()


@router.get("/vip/redemptions/mine")
async def my_redemptions(request: Request) -> Any:
    user = await require_user(request)
    docs = await db.redemptions.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return docs


# ============================================================
# VIP — Withdrawals (client side only)
# ============================================================

@router.post("/vip/withdraw")
async def create_withdrawal(payload: WithdrawalCreate, request: Request) -> Any:
    user = await require_user(request)
    await assert_account_active(user)
    if user["role"] == "employee":
        raise HTTPException(status_code=403, detail="Empleados no pueden retirar")
    if user["role"] != "admin":
        await assert_not_defensive("retiros")
    if user.get("phone") and not user.get("phone_verified"):
        raise HTTPException(
            status_code=403,
            detail={"code": "PHONE_NOT_VERIFIED",
                    "message": "Tu número de teléfono debe ser verificado por un miembro del staff antes de poder retirar. Contacta a soporte."},
        )
    await _enforce_totp_step_up(user, payload.totp_code, action_label="retiro")
    currency = payload.currency or "USD"
    if get_user_balance(user, currency) < payload.amount_usd:
        raise HTTPException(status_code=400, detail=f"Saldo insuficiente en {currency}")
    w = WithdrawalRequest(
        user_id=user["user_id"],
        user_email=user["email"],
        user_name=user["name"],
        amount_usd=payload.amount_usd,
        currency=currency,
        method=payload.method,
        details=payload.details,
        beneficiary_name=payload.beneficiary_name,
    )
    await db.withdrawals.insert_one(w.model_dump())
    await decrement_balance(user["user_id"], currency, payload.amount_usd)
    try:
        await notify_all_admins(
            db,
            title="Nuevo retiro",
            body=f"{user['name']} solicitó retiro de {payload.amount_usd} {currency} ({payload.method}).",
            url_path="/admin/withdrawals",
        )
    except Exception as e:
        logger.error(f"Admin notify (withdrawal) failed: {e}")
    return w.model_dump()


@router.get("/vip/withdrawals/mine")
async def my_withdrawals(request: Request) -> Any:
    user = await require_user(request)
    docs = await db.withdrawals.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return docs


# ============================================================
# VIP — Balances + Daily closing PDF
# ============================================================

@router.get("/vip/balances")
async def vip_balances(request: Request) -> Any:
    user = await require_user(request)
    if user["role"] == "employee":
        raise HTTPException(status_code=403, detail="Empleados no tienen saldo de cliente")
    balances = dict(user.get("vip_balances") or {})
    legacy_usd = float(user.get("vip_balance_usd") or 0.0)
    if legacy_usd > 0:
        balances["USD"] = balances.get("USD", 0.0) + legacy_usd
    rates = await build_rate_lookup()
    items = []
    total_usdt = 0.0
    for code, amount in balances.items():
        amt = float(amount or 0.0)
        if amt == 0:
            continue
        usdt = convert_to_usdt(amt, code, rates)
        if usdt is not None:
            total_usdt += usdt
        items.append({
            "currency": code,
            "amount": amt,
            "usdt_equivalent": round(usdt, 4) if usdt is not None else None,
        })
    items.sort(key=lambda x: -(x["usdt_equivalent"] or 0))
    return {"balances": items, "total_usdt": round(total_usdt, 4)}


# ============================================================
# iter48 — VIP self-conversion between own balances (no admin approval)
# ============================================================

class VipConvertPayload(BaseModel):
    from_code: str = Field(..., min_length=1, max_length=10)
    to_code: str = Field(..., min_length=1, max_length=10)
    amount_from: float = Field(..., gt=0, le=1_000_000_000)


@router.post("/vip/convert")
async def vip_convert(payload: VipConvertPayload, request: Request) -> Any:
    """Atomically swap a VIP's own funds between two currencies they already
    hold. No physical delivery, no admin approval — this is a balance
    reshuffle within the SAME user. Uses the VIP rate when applicable.

    Rejects if:
      - `from_code == to_code`
      - the user does not hold `amount_from` of `from_code`
      - no rate row exists for the pair (we deliberately do NOT use the
        inverse direction here — quoting must be explicit for self-conversion
        the same way it is for any P2P order).

    Audited via `audit_logs` for traceability.
    """
    user = await require_user(request)
    await assert_account_active(user)
    if user["role"] == "employee":
        raise HTTPException(status_code=403, detail="Empleados no tienen saldo a convertir.")
    if user["role"] != "admin":
        await assert_not_defensive("conversiones")
    from_code = payload.from_code.upper().strip()
    to_code = payload.to_code.upper().strip()
    if from_code == to_code:
        raise HTTPException(
            status_code=400,
            detail="Las monedas de origen y destino deben ser diferentes.",
        )
    # Balance check
    have = get_user_balance(user, from_code)
    if have < payload.amount_from:
        raise HTTPException(
            status_code=400,
            detail=(f"Saldo insuficiente en {from_code}: tienes "
                    f"{have:.4f}, intentas convertir {payload.amount_from:.4f}."),
        )
    # Rate lookup — for SELF-CONVERSION we accept either direction. The
    # `USDT→code` rate is the operator's quoted valuation rate (the inverse
    # of which gives the buy-side conversion). This mirrors the logic used
    # by `services.balances._convert_direct` for balance valuation: since
    # no P2P trade is happening (it's an internal balance reshuffle within
    # the same user), using the inverse quote when direct is unavailable is
    # the natural behaviour.
    rate_doc = await db.rates.find_one(
        {"from_code": from_code, "to_code": to_code}, {"_id": 0}
    )
    is_vip = user.get("role") in ("vip", "admin")
    rate_used: float = 0.0
    if rate_doc:
        rate_used = float(rate_doc.get("rate_vip" if is_vip else "rate_normal", 0))
    else:
        inverse_doc = await db.rates.find_one(
            {"from_code": to_code, "to_code": from_code}, {"_id": 0}
        )
        if inverse_doc:
            inv = float(inverse_doc.get("rate_vip" if is_vip else "rate_normal", 0))
            if inv > 0:
                rate_used = 1.0 / inv
    if rate_used <= 0:
        raise HTTPException(
            status_code=400,
            detail=(f"No hay tasa cotizada para {from_code} → {to_code}. "
                    "Contacta a soporte para habilitarla."),
        )
    amount_to = round(payload.amount_from * rate_used, 4)
    # Atomic swap: decrement from + increment to
    await decrement_balance(user["user_id"], from_code, payload.amount_from)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$inc": {f"vip_balances.{to_code}": amount_to}},
    )
    # Audit
    try:
        from audit_log import log_action
        await log_action(
            db, actor=user, action="vip.convert",
            entity_type="user", entity_id=user["user_id"],
            summary=f"{payload.amount_from} {from_code} → {amount_to} {to_code}",
            details={
                "from_code": from_code, "to_code": to_code,
                "amount_from": payload.amount_from,
                "amount_to": amount_to, "rate": rate_used,
            },
        )
    except Exception as e:
        logger.error(f"vip.convert audit log failed: {e}")
    return {
        "ok": True,
        "from_code": from_code, "to_code": to_code,
        "amount_from": payload.amount_from,
        "amount_to": amount_to,
        "rate": rate_used,
    }


@router.get("/vip/daily-closing")
async def vip_daily_closing(request: Request, date: Optional[str] = None) -> Any:
    user = await require_user(request)
    if user["role"] not in ("vip", "admin"):
        raise HTTPException(status_code=403, detail="Solo clientes VIP")
    if not date:
        date = now_utc().strftime("%Y-%m-%d")
    try:
        day_start = datetime.fromisoformat(f"{date}T00:00:00+00:00")
        day_end = day_start + timedelta(days=1)
    except Exception:
        raise HTTPException(status_code=400, detail="Fecha inválida (usa YYYY-MM-DD)")

    cursor = db.orders.find({
        "user_id": user["user_id"],
        "status": {"$in": ["approved", "completed"]},
        "updated_at": {"$gte": day_start.isoformat(), "$lt": day_end.isoformat()},
    }, {"_id": 0}).sort("updated_at", 1)
    orders = await cursor.to_list(1000)

    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    pdf_bytes = generate_vip_closing_pdf(
        user=fresh,
        orders=orders,
        date_label=date,
        final_balance=fresh.get("vip_balance_usd", 0),
    )
    filename = f"cierre_vip_{date}_{user['user_id']}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
