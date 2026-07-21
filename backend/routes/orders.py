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
from services.user_verification import assert_user_fully_verified
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
    await assert_user_fully_verified(db, user, action_label="crear una orden de intercambio")
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
    await assert_user_fully_verified(db, user, action_label="canjear productos del marketplace")
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
    # iter55.36o — full verification (email + phone + KYC) required for withdrawals.
    # Supersedes the previous phone-only check.
    await assert_user_fully_verified(db, user, action_label="retirar fondos")
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
    await assert_user_fully_verified(db, user, action_label="convertir saldos entre monedas")
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
    # iter77 — Fee model: the 0.01 USDT fee is charged as a **separate**
    # additional debit from the client's USDT balance. Destination receives
    # the FULL equivalent `amount_from × rate_used` (no fee subtraction).
    #
    #   USDT → X   : USDT balance must be ≥ amount_from + 0.01 (same account).
    #   Y → X      : USDT balance must be ≥ 0.01 (separate from source).
    #   Y → USDT   : USDT balance requirement of 0.01 is trivially met if the
    #                client has ANY USDT — otherwise refuse. Client must top
    #                up USDT first (buy 0.01 USDT from another currency).
    #
    # The frontend displays the fee as a clean "0.01 USDT" line — never
    # converted to destination-currency spread.
    CONVERT_FEE_USDT = 0.01
    CONVERT_MIN_USDT = 1.00
    from services.balances import build_rate_lookup, convert_to_usdt
    rates_lookup = await build_rate_lookup()
    # Minimum-source guard: reject if `amount_from` is worth < 1.00 USDT.
    amount_from_usdt = convert_to_usdt(payload.amount_from, from_code, rates_lookup)
    if amount_from_usdt is None:
        raise HTTPException(
            status_code=400,
            detail=(f"No hay ruta de valoración USDT para {from_code}. "
                    "Contacta a soporte para habilitar la tasa."),
        )
    if amount_from_usdt < CONVERT_MIN_USDT:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Monto insuficiente: {payload.amount_from:.4f} {from_code} "
                f"equivale a {amount_from_usdt:.4f} USDT. El mínimo por "
                f"conversión es el equivalente a {CONVERT_MIN_USDT:.2f} USDT."
            ),
        )
    # iter77 — USDT-balance-for-fee guard (always applies, both source cases).
    usdt_balance = float(get_user_balance(user, "USDT") or 0)
    required_usdt = CONVERT_FEE_USDT + (payload.amount_from if from_code == "USDT" else 0.0)
    if usdt_balance < required_usdt:
        if from_code == "USDT":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Saldo insuficiente en USDT: necesitas al menos "
                    f"{required_usdt:.2f} USDT ({payload.amount_from:.2f} para "
                    f"convertir + {CONVERT_FEE_USDT:.2f} de comisión). Tienes "
                    f"{usdt_balance:.4f} USDT."
                ),
            )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Necesitas al menos {CONVERT_FEE_USDT:.2f} USDT en tu saldo "
                f"para pagar la comisión de la conversión. Tienes "
                f"{usdt_balance:.4f} USDT — recárgalos antes de continuar."
            ),
        )
    # Destination receives the FULL equivalent, no fee subtraction.
    amount_to = round(payload.amount_from * rate_used, 4)
    amount_to_gross = amount_to  # kept for backwards compat in the response
    fee = CONVERT_FEE_USDT
    # Atomic ledger update:
    #   1. Debit `amount_from` from the source currency.
    #   2. Debit `0.01` from USDT (fee). If source is USDT, this is the same
    #      currency — decrement_balance handles both calls independently.
    #   3. Credit `amount_to` to the destination currency.
    await decrement_balance(user["user_id"], from_code, payload.amount_from)
    await decrement_balance(user["user_id"], "USDT", CONVERT_FEE_USDT)
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
                f" (fee {fee} USDT charged separately)"
            ),
            details={
                "from_code": from_code, "to_code": to_code,
                "amount_from": payload.amount_from,
                "amount_to": amount_to,
                "rate": rate_used,
                "usdt_fee": fee,
                "amount_from_usdt": round(amount_from_usdt, 4),
            },
        )
    except Exception as e:
        logger.error(f"vip.convert audit log failed: {e}")
    return {
        "ok": True,
        "from_code": from_code, "to_code": to_code,
        "amount_from": payload.amount_from,
        "amount_to": amount_to,
        "usdt_fee": fee,
        "rate": rate_used,
    }


# ============================================================
# iter79 — Dust converter (batch-clean small balances → USDT)
# ============================================================

# Reuse the same threshold that the transaction-registry uses to flag
# `small_balance` conversion subtypes. Anything below this USDT-equivalent
# is considered "dust" that the user can sweep in one shot.
from services.transactions import SMALL_BALANCE_THRESHOLD_USDT  # noqa: E402


async def _collect_dust(user: dict, rates: dict) -> list[dict]:
    """Return the list of the user's non-USDT balances whose USDT equivalent
    is strictly positive and strictly less than SMALL_BALANCE_THRESHOLD_USDT.

    Each entry:
        {
          "currency": str,
          "amount": float,
          "usdt_equivalent": float,   # rounded to 4 decimals
          "rate": float,              # code→USDT rate (client-preview)
        }
    """
    balances = dict(user.get("vip_balances") or {})
    dust: list[dict] = []
    for code, amount in balances.items():
        code = str(code).upper().strip()
        if code == "USDT":
            continue
        amt = float(amount or 0.0)
        if amt <= 0:
            continue
        eq = convert_to_usdt(amt, code, rates)
        if eq is None or eq <= 0:
            continue
        if eq >= SMALL_BALANCE_THRESHOLD_USDT:
            continue
        # Derive an effective code→USDT rate from the pair we just used so
        # the frontend can render "1 CUP ≈ 0.0025 USDT" cleanly.
        rate_used = eq / amt if amt > 0 else 0.0
        dust.append({
            "currency": code,
            "amount": round(amt, 8),
            "usdt_equivalent": round(eq, 4),
            "rate": round(rate_used, 8),
        })
    dust.sort(key=lambda d: -d["usdt_equivalent"])
    return dust


@router.get("/vip/dust")
async def vip_dust_preview(request: Request) -> Any:
    """Preview what a dust-conversion sweep would do RIGHT NOW.

    Response:
      {
        "items": [ { currency, amount, usdt_equivalent, rate }, ...],
        "total_usdt": float,           # sum of usdt_equivalent
        "fee_usdt": 0.01,              # flat single fee for the whole batch
        "net_usdt": float,             # total_usdt - fee_usdt (never < 0)
        "usdt_balance": float,         # current USDT balance (fee source)
        "threshold_usdt": 5.0,
        "can_convert": bool,           # false when items empty or fee guard fails
        "reason": str | null,
      }
    """
    user = await require_user(request)
    if user["role"] == "employee":
        raise HTTPException(
            status_code=403,
            detail="Empleados no tienen saldo a convertir.",
        )
    rates = await build_rate_lookup()
    dust = await _collect_dust(user, rates)
    total_usdt = round(sum(d["usdt_equivalent"] for d in dust), 4)
    fee = 0.01
    usdt_bal = float(get_user_balance(user, "USDT") or 0)
    reason = None
    can = True
    if not dust:
        can = False
        reason = "no_dust"
    elif usdt_bal < fee:
        can = False
        reason = "usdt_fee_required"
    return {
        "items": dust,
        "total_usdt": total_usdt,
        "fee_usdt": fee,
        "net_usdt": round(max(0.0, total_usdt - fee), 4),
        "usdt_balance": round(usdt_bal, 4),
        "threshold_usdt": SMALL_BALANCE_THRESHOLD_USDT,
        "can_convert": can,
        "reason": reason,
    }


@router.post("/vip/convert-dust")
async def vip_convert_dust(request: Request) -> Any:
    """Sweep ALL dust balances (each < 5 USDT equivalent) into USDT in a
    single batch with a FLAT 0.01 USDT fee for the whole operation.

    Rules:
      • Requires full identity verification (same gate as /vip/convert).
      • Requires ≥ 0.01 USDT balance to pay the flat fee.
      • Rejects when the user has no dust balances (nothing to sweep).
      • Each currency swept is audit-logged separately under
        `vip.convert.dust` so the History section shows one row per swept
        currency with `conversion_subtype: "small_balance"`. The FIRST
        audited row carries the flat 0.01 USDT fee; subsequent rows carry
        `usdt_fee: 0.00`.

    Response mirrors the preview shape with the ACTUAL swept items:
      { ok, items, total_usdt, fee_usdt, credited_usdt }
    """
    user = await require_user(request)
    await assert_account_active(user)
    if user["role"] == "employee":
        raise HTTPException(
            status_code=403,
            detail="Empleados no tienen saldo a convertir.",
        )
    if user["role"] != "admin":
        await assert_not_defensive("conversiones")
    await assert_user_fully_verified(
        db, user, action_label="convertir saldos pequeños a USDT"
    )
    rates = await build_rate_lookup()
    dust = await _collect_dust(user, rates)
    if not dust:
        raise HTTPException(
            status_code=400,
            detail=(
                "No tienes saldos pequeños para convertir "
                f"(monedas con equivalente < {SMALL_BALANCE_THRESHOLD_USDT:.2f} USDT)."
            ),
        )
    FLAT_FEE = 0.01
    usdt_bal = float(get_user_balance(user, "USDT") or 0)
    if usdt_bal < FLAT_FEE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Necesitas al menos {FLAT_FEE:.2f} USDT en tu saldo "
                f"para pagar la comisión del barrido. Tienes {usdt_bal:.4f} USDT."
            ),
        )
    # 1) Debit the flat fee ONCE from USDT.
    await decrement_balance(user["user_id"], "USDT", FLAT_FEE)
    # 2) For each dust currency: debit the full balance, credit the USDT
    #    equivalent. We recompute the USDT equivalent from `rates` here to
    #    guarantee the amount we actually credit matches what _collect_dust
    #    said (same rate table, called once).
    credited_total = 0.0
    from audit_log import log_action
    for idx, d in enumerate(dust):
        code = d["currency"]
        amt = d["amount"]
        eq_usdt = float(d["usdt_equivalent"])
        await decrement_balance(user["user_id"], code, amt)
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$inc": {"vip_balances.USDT": eq_usdt}},
        )
        credited_total += eq_usdt
        # Audit one row per swept currency so History shows one line per
        # currency. The first row carries the shared 0.01 USDT fee; the
        # rest carry 0.00 to avoid double-counting the fee.
        try:
            await log_action(
                db, actor=user, action="vip.convert.dust",
                entity_type="user", entity_id=user["user_id"],
                summary=(
                    f"Dust sweep: {amt} {code} → {round(eq_usdt, 4)} USDT"
                    + (f" (fee {FLAT_FEE} USDT charged once)" if idx == 0 else "")
                ),
                details={
                    "from_code": code, "to_code": "USDT",
                    "amount_from": amt,
                    "amount_to": round(eq_usdt, 4),
                    "rate": d["rate"],
                    "usdt_fee": FLAT_FEE if idx == 0 else 0.0,
                    "amount_from_usdt": round(eq_usdt, 4),
                    "batch": True,
                    "batch_size": len(dust),
                    "batch_index": idx,
                },
            )
        except Exception as e:
            logger.error(f"vip.convert.dust audit log failed: {e}")
    return {
        "ok": True,
        "items": dust,
        "total_usdt": round(credited_total, 4),
        "fee_usdt": FLAT_FEE,
        "credited_usdt": round(credited_total, 4),
    }


@router.get("/vip/daily-closing")
async def vip_daily_closing(request: Request,
                             date: Optional[str] = None,
                             since: Optional[str] = None,
                             until: Optional[str] = None) -> Any:
    """iter90 — Range-aware closing PDF. Any signed-in client (normal,
    vip, admin) can download their own closing report over an
    arbitrary date range. The old `date=YYYY-MM-DD` single-day query
    still works for back-compat: it collapses to since=until=date.
    Employees remain excluded (they don't run an operating balance).
    """
    user = await require_user(request)
    if user["role"] == "employee":
        raise HTTPException(
            status_code=403,
            detail="Staff members do not have an operating balance to close.",
        )

    # Back-compat: legacy callers still pass just `?date=YYYY-MM-DD`.
    if date and not since and not until:
        since = date
        until = date

    from services.transactions import build_transactions
    entries = await build_transactions(
        direction=None, currency=None, holder=None,
        since=since, until=until,
        min_amount=None, max_amount=None,
        user_id=user["user_id"],
    )

    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    is_vip = (fresh or {}).get("role") == "vip"
    pdf_bytes = generate_vip_closing_pdf(
        user=fresh,
        entries=entries,
        since=since or "",
        until=until or "",
        final_balance=(fresh or {}).get("vip_balance_usd", 0) or 0,
        is_vip=is_vip,
    )
    # Filename mirrors the range so a user downloading multiple closings
    # doesn't end up with 3× cierre_2026-07-18.pdf overwriting each other.
    if since and until and since != until:
        range_slug = f"{since}_{until}"
    else:
        range_slug = since or until or now_utc().strftime("%Y-%m-%d")
    slug_kind = "cierre_vip" if is_vip else "cierre_contable"
    filename = f"{slug_kind}_{range_slug}_{user['user_id']}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
