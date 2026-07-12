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
    OrderCreate,
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
    # iter55.19c — crypto withdrawals persist the declared network so admins
    # know which chain to release on (and audit trail is preserved). Empty
    # string for non-crypto flows.
    crypto_network: str = ""
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
    # iter55.19c — only required (and validated) when method == "crypto".
    crypto_network: Optional[str] = Field(None, description="Red on-chain (TRC20 / BEP20)")
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
    # iter55.27 — fetch destination currency type so we can apply the fiat-cash
    # floor rule and credit the residue to the client's balance.
    to_currency_doc = await db.currencies.find_one(
        {"code": payload.to_code}, {"_id": 0, "type": 1}
    ) or {}
    to_currency_type = to_currency_doc.get("type", "")
    order = build_order_from_payload(payload, user, rate, to_currency_type)
    residue = getattr(order, "_residue_to_credit", 0.0)
    await db.orders.insert_one(order.model_dump())
    # If cash-to-fiat produced sub-unit residue, credit it to the client's
    # on-platform balance in the SAME currency. Client can accumulate across
    # trades or convert to USDT (with 0.01 USDT fee) later.
    if residue > 0:
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$inc": {f"vip_balances.{payload.to_code}": residue}},
        )
        try:
            from audit_log import log_action
            await log_action(
                db, actor=user, action="order.residue_credited",
                entity_type="order", entity_id=order.id,
                summary=f"Residuo {residue:.6f} {payload.to_code} acreditado al saldo",
                details={
                    "order_id": order.id,
                    "user_id": user["user_id"],
                    "currency": payload.to_code,
                    "residue": residue,
                    "reason": "fiat_cash_floor",
                },
            )
        except Exception as e:
            logger.error(f"residue audit log failed: {e}")
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
    # iter55.19 — reject method↔currency mismatches (e.g. requesting a bank
    # transfer for a cash-only USD balance). Reuses the shared helper that
    # also gates order creation, so both flows stay in sync.
    await _assert_delivery_method_matches_currency(currency, payload.method)
    # iter55.19b — cash withdrawals require receiver's name+ID+phone in the
    # details field so staff can coordinate the physical hand-off. Mirrors
    # the frontend validation for defense-in-depth (API-direct callers can't
    # skip it). 20 chars is a good proxy: "Juan Pérez 12345678 +53555..."
    # already exceeds it.
    if payload.method == "cash":
        details_trimmed = (payload.details or "").strip()
        if len(details_trimmed) < 20:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Para retiros en efectivo incluye nombre y apellidos, "
                    "número de ID/carné y teléfono celular del receptor "
                    "(mínimo 20 caracteres en Detalles)."
                ),
            )
    # iter55.19c — crypto withdrawals must declare the on-chain network and
    # the details field must contain an address that matches that network.
    # Mirrors the BingX "No coinciden" flow to prevent irrecoverable fund loss.
    crypto_network = ""
    if payload.method == "crypto":
        from services.crypto_networks import (
            SUPPORTED_NETWORKS, is_supported_network,
            is_address_valid_for_network, mismatch_reason,
        )
        network = (payload.crypto_network or "").strip().upper()
        if not is_supported_network(network):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Debes elegir la red on-chain del retiro. "
                    f"Redes soportadas: {', '.join(SUPPORTED_NETWORKS)}."
                ),
            )
        # Address is stored in `details` (same field the client fills in the UI).
        if not is_address_valid_for_network(payload.details or "", network):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "CRYPTO_NETWORK_MISMATCH",
                    "message": mismatch_reason(payload.details or "", network),
                    "network": network,
                },
            )
        crypto_network = network
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
        crypto_network=crypto_network,
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
# iter52 — Balance ledger (per-currency drill-down)
# ============================================================

async def _build_balance_ledger(user_id: str) -> dict:
    """Group all credited `accumulate` orders for the given user by `to_code`.

    Returns:
        {
          "by_currency": {
             "CUPT": {
                "total": 1565000.0,
                "orders": [{id, from_code, amount_from, amount_to,
                            status, accumulated_at, created_at}, ...]
             },
             ...
          },
          "total_orders": N,
        }

    Only orders carrying `accumulated_at` (i.e. money already credited via
    iter51's idempotent helper) are included. Manual balance adjustments
    made via admin DB tools won't appear here — that's by design (ledger
    reflects observable order activity).
    """
    cursor = db.orders.find(
        {
            "user_id": user_id,
            "delivery_method": "accumulate",
            "accumulated_at": {"$exists": True},
        },
        {
            "_id": 0, "id": 1, "from_code": 1, "to_code": 1,
            "amount_from": 1, "amount_to": 1, "status": 1,
            "accumulated_at": 1, "created_at": 1, "sender_name": 1,
        },
    ).sort("accumulated_at", -1)
    by_currency: dict[str, dict[str, Any]] = {}
    total = 0
    async for o in cursor:
        code = o["to_code"]
        bucket = by_currency.setdefault(code, {"total": 0.0, "orders": []})
        bucket["total"] += float(o.get("amount_to") or 0)
        bucket["orders"].append(o)
        total += 1
    # Round totals for clean display
    for code in by_currency:
        by_currency[code]["total"] = round(by_currency[code]["total"], 4)
    return {"by_currency": by_currency, "total_orders": total}


@router.get("/vip/balance-ledger")
async def vip_balance_ledger(request: Request) -> Any:
    """Self-service ledger for the calling user. Returns the same payload as
    the admin endpoint below but scoped to the caller's own user_id."""
    user = await require_user(request)
    if user["role"] == "employee":
        raise HTTPException(
            status_code=403,
            detail="Empleados no tienen saldos de cliente",
        )
    return await _build_balance_ledger(user["user_id"])


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
    # iter55.29 — enforce admin-controlled "convertible destination" flag.
    # If the destination currency has `is_convertible_to=False` the platform
    # cannot SEND funds in that currency (e.g. USD/Zelle is receive-only), so
    # we must not let clients accumulate a converted balance the platform
    # cannot ever disburse. Missing flag → treat as True for backward compat.
    to_currency_doc = await db.currencies.find_one(
        {"code": to_code}, {"_id": 0, "is_convertible_to": 1, "name": 1}
    )
    if to_currency_doc is not None and to_currency_doc.get("is_convertible_to", True) is False:
        raise HTTPException(
            status_code=400,
            detail=(
                f"La plataforma no puede enviar {to_code} — no está disponible "
                "como destino de conversión. Elige otra moneda de destino."
            ),
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
    amount_to_gross = round(payload.amount_from * rate_used, 4)
    # iter55.27 — flat 0.01 USDT service fee for ANY conversion to USDT.
    # Enforced when to_code == "USDT" only; other pairs stay fee-free.
    # Also enforce a 1.00 USDT minimum NET (post-fee) to prevent dust
    # conversions that would leave the client with < 1 USDT after the fee.
    USDT_CONVERT_FEE = 0.01
    USDT_MIN_NET = 1.00
    fee = 0.0
    amount_to = amount_to_gross
    if to_code == "USDT":
        fee = USDT_CONVERT_FEE
        amount_to = round(amount_to_gross - fee, 4)
        if amount_to < USDT_MIN_NET:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Conversión insuficiente: recibirías {amount_to:.4f} USDT "
                    f"después de la comisión de {USDT_CONVERT_FEE} USDT. "
                    f"El mínimo neto para convertir es {USDT_MIN_NET:.2f} USDT — "
                    f"acumula más saldo antes de convertir."
                ),
            )
    # Atomic swap: decrement from + increment to (net of fee)
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
            summary=(
                f"{payload.amount_from} {from_code} → {amount_to} {to_code}"
                + (f" (fee {fee} USDT)" if fee > 0 else "")
            ),
            details={
                "from_code": from_code, "to_code": to_code,
                "amount_from": payload.amount_from,
                "amount_to_gross": amount_to_gross,
                "amount_to": amount_to, "rate": rate_used,
                "usdt_fee": fee,
            },
        )
    except Exception as e:
        logger.error(f"vip.convert audit log failed: {e}")
    return {
        "ok": True,
        "from_code": from_code, "to_code": to_code,
        "amount_from": payload.amount_from,
        "amount_to": amount_to,
        "amount_to_gross": amount_to_gross,
        "usdt_fee": fee,
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
