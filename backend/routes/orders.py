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
from services.live_events import emit_balance_changed
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
    # iter254(R07) — moneda de liquidación del canje: 'USDT' para canjes
    # nuevos (la UI muestra USDT); docs antiguos sin el campo = 'USD'.
    settlement_currency: str = "USDT"
    delivery_address: str = ""
    status: Literal["pending", "approved", "delivered", "rejected"] = "pending"
    admin_note: str = ""
    created_at: str = Field(default_factory=lambda: iso(now_utc()))
    # iter198 — courier fee (per-km) for marketplace deliveries.
    delivery_latitude: Optional[float] = None
    delivery_longitude: Optional[float] = None
    courier_km: float = 0.0
    courier_fee_usdt: float = 0.0
    courier_fee_usd: float = 0.0
    courier_fee_status: Literal["none", "free", "charged", "manual_review"] = "none"
    courier_municipality: Optional[str] = None
    courier_rate_snapshot: float = 0.0
    courier_min_fee_snapshot: float = 0.0
    # iter217 — canjes de productos de vendedores VIP: snapshot del dueño y
    # estado del pago al vendedor (se acredita al marcar 'delivered').
    vendor_owner_id: str = ""
    vendor_owner_name: str = ""
    vendor_credited_at: str = ""
    vendor_credit_net: float = 0.0
    vendor_commission_pct: float = 0.0
    vendor_credit_reversed_at: str = ""
    # iter229 — entrada automática del capital de la venta al fondo empresa.
    fund_inflow_at: str = ""
    fund_inflow_amount: float = 0.0
    fund_inflow_currency: str = ""
    fund_inflow_reversed_at: str = ""
    # iter229 — snapshot de conversión tienda física (CUP efectivo) → USDT.
    total_store: float = 0.0
    cost_store: float = 0.0
    store_currency: str = ""
    fx_rate: float = 0.0
    # iter236 — recogida en tienda física (sin mensajería).
    fulfillment: Literal["delivery", "store_pickup"] = "delivery"
    store_id: str = ""
    store_name: str = ""
    store_address: str = ""
    pickup_ready_at: str = ""
    on_my_way_at: str = ""
    # iter238 — código corto que el cliente muestra en la tienda.
    pickup_code: str = ""


class RedemptionCreate(BaseModel):
    product_id: str
    # iter247 — gt=0 bloquea canjes con cantidad negativa (inflar saldo/stock).
    quantity: int = Field(..., gt=0, le=1_000_000)
    delivery_address: str = ""
    delivery_latitude: Optional[float] = Field(None, ge=-90, le=90)
    delivery_longitude: Optional[float] = Field(None, ge=-180, le=180)
    # iter212 — municipio elegido por el cliente cuando el mapa falló.
    courier_municipality: Optional[str] = Field(None, max_length=60)
    # iter236 — recogida en tienda física.
    fulfillment: Literal["delivery", "store_pickup"] = "delivery"
    store_id: Optional[str] = None


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
    # iter192 — cash deliveries record the province so ops route the courier;
    # empty string for non-cash flows.
    province: str = ""
    status: Literal["pending", "approved", "paid", "rejected", "cancelled"] = "pending"
    admin_note: str = ""
    payout_proof_image: str = ""
    payout_tx_hash: str = ""
    created_at: str = Field(default_factory=lambda: iso(now_utc()))


# iter192 — Cuba's 15 provinces + Isla de la Juventud (special municipality).
CUBA_PROVINCES = [
    "Pinar del Río", "Artemisa", "La Habana", "Mayabeque", "Matanzas",
    "Cienfuegos", "Villa Clara", "Sancti Spíritus", "Ciego de Ávila",
    "Camagüey", "Las Tunas", "Holguín", "Granma", "Santiago de Cuba",
    "Guantánamo", "Isla de la Juventud",
]


async def _available_cash_provinces() -> list:
    """Provinces with cash availability. Missing config = all available."""
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0, "cash_provinces": 1})
    configured = (doc or {}).get("cash_provinces")
    if configured is None:
        return list(CUBA_PROVINCES)
    return [p for p in configured if p in CUBA_PROVINCES]


class WithdrawalCreate(BaseModel):
    # iter247 — gt=0 bloquea el exploit de retiros negativos (inflar saldo).
    amount_usd: float = Field(..., gt=0, le=10_000_000)
    currency: str = "USD"
    method: Literal["transfer", "cash", "crypto"]
    details: str
    # iter182 — optional for crypto (the on-chain address identifies the
    # destination); required (min 2 chars) for transfer/cash, enforced in-route.
    beneficiary_name: Optional[str] = Field(None,
                                    description="Nombre del titular de la cuenta beneficiaria")
    # iter55.19c — only required (and validated) when method == "crypto".
    crypto_network: Optional[str] = Field(None, description="Red on-chain (TRC20 / BEP20)")
    # iter192 — required when method == "cash": delivery province (must have
    # cash availability configured by the admin).
    province: Optional[str] = Field(None, max_length=40)
    # iter198 — optional delivery coordinates (picked from the OSM
    # autocomplete). The server recomputes the road distance itself.
    delivery_latitude: Optional[float] = Field(None, ge=-90, le=90)
    delivery_longitude: Optional[float] = Field(None, ge=-180, le=180)
    # iter205 — cash: entrega a domicilio (mensajería) o recogida en oficina.
    cash_delivery_mode: Optional[Literal["courier", "office_pickup"]] = None
    # iter212 — municipio elegido por el cliente cuando el mapa falló.
    courier_municipality: Optional[str] = Field(None, max_length=60)
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
    # iter143 — tiered payment accounts: enforce the per-currency minimum and
    # resolve WHICH account the client was told to pay (snapshotted below).
    from services.payment_accounts import assert_amount_meets_minimum
    payment_account = await assert_amount_meets_minimum(
        payload.from_code, payload.amount_from)
    rate, _rate_doc = await resolve_order_rate(
        payload.from_code, payload.to_code, user, payload.amount_from)
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
    if payment_account:
        order.payment_account_id = payment_account.get("id", "")
        order.payment_account_label = payment_account.get("label", "")
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
        await emit_balance_changed(user["user_id"], "order_residue",
                                   currency=payload.to_code, order_id=order.id)
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
    # iter98 — SSE push to admins so /admin/queue prepends the new order
    # in real-time (staff sees the ticker without hammering F5).
    try:
        from services.live_bus import publish as live_publish
        fresh = await db.orders.find_one({"id": order.id}, {"_id": 0}) or order.model_dump()
        await live_publish(
            "order_created",
            {
                "id": fresh.get("id"),
                "user_id": fresh.get("user_id"),
                "user_name": user.get("name") or user.get("email"),
                "from_code": fresh.get("from_code"),
                "to_code": fresh.get("to_code"),
                "amount_from": fresh.get("amount_from"),
                "amount_to": fresh.get("amount_to"),
                "delivery_method": fresh.get("delivery_method"),
                "status": fresh.get("status"),
                "created_at": fresh.get("created_at"),
            },
            roles=("admin", "employee"),
        )
    except Exception as e:
        logger.error(f"order_created SSE publish failed: {e}")
    # iter174 — match this order against already-imported bank movements.
    from services.reconciliation_matcher import schedule_rematch
    schedule_rematch(order.from_code)
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

PICKUP_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


async def _new_pickup_code() -> str:
    """iter238 — código corto único (6 chars sin ambiguos) por recogida."""
    import secrets
    for _ in range(8):
        code = "".join(secrets.choice(PICKUP_CODE_ALPHABET) for _ in range(6))
        clash = await db.redemptions.find_one(
            {"pickup_code": code, "status": {"$in": ["pending", "approved"]}},
            {"_id": 0, "id": 1})
        if not clash:
            return code
    return "".join(secrets.choice(PICKUP_CODE_ALPHABET) for _ in range(8))


async def _load_pickup_store(store_id: Optional[str], product: dict) -> dict:
    """iter236 — valida la sucursal elegida para recogida en tienda."""
    if product.get("owner_id"):
        raise HTTPException(
            status_code=400,
            detail="Los productos de vendedores VIP no admiten recogida en tienda")
    if not store_id:
        raise HTTPException(
            status_code=400,
            detail="Selecciona la tienda donde recogerás tu pedido")
    store = await db.stores.find_one({"id": store_id, "active": True}, {"_id": 0})
    if not store:
        raise HTTPException(status_code=404,
                            detail="Tienda no encontrada o inactiva")
    allowed = product.get("available_store_ids") or []
    if allowed and store_id not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Este producto no está disponible en esa sucursal")
    return store


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
    # iter254(R06) — ocultar del catálogo no es autorización: nadie puede
    # canjear productos inactivos o no aprobados aunque conozca el ID.
    if product.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Producto no disponible")
    if product.get("owner_id") and \
            product.get("approval_status") not in (None, "approved"):
        raise HTTPException(status_code=400, detail="Producto no disponible")
    if product["stock"] < payload.quantity:
        raise HTTPException(status_code=400, detail="Stock insuficiente")
    # iter217 — un vendedor VIP no puede canjear su propio producto.
    if product.get("owner_id") and product["owner_id"] == user["user_id"]:
        raise HTTPException(status_code=400, detail="No puedes canjear tu propio producto")
    # iter229 — los productos de la EMPRESA tienen precios en la moneda de la
    # tienda física (CUP efectivo); en la web se cobran en USDT a la tasa
    # vigente. Los productos de vendedores VIP ya están en USDT.
    store_total = 0.0
    store_cost = 0.0
    fx_rate = 0.0
    store_currency = ""
    if product.get("owner_id"):
        total = product["price_usd"] * payload.quantity
        cost = float(product.get("cost_usd") or 0) * payload.quantity
    else:
        from services.marketplace_fx import get_store_fx, to_usdt
        fx = await get_store_fx(role=user["role"])
        if not fx["configured"]:
            raise HTTPException(
                status_code=400,
                detail=(f"No hay tasa USDT→{fx['store_currency']} configurada; "
                        "no se puede calcular el precio en USDT. Contacta al administrador."))
        fx_rate = fx["rate"]
        store_currency = fx["store_currency"]
        store_total = round(float(product["price_usd"]) * payload.quantity, 2)
        store_cost = round(float(product.get("cost_usd") or 0) * payload.quantity, 2)
        total = to_usdt(store_total, fx_rate)
        cost = to_usdt(store_cost, fx_rate) or 0.0
    # iter236 — recogida en tienda: sin mensajería ni costo de envío.
    pickup_store = None
    if payload.fulfillment == "store_pickup":
        pickup_store = await _load_pickup_store(payload.store_id, product)
    # iter198 — courier fee for the physical delivery. Free when the redeem
    # value reaches the USDT threshold; auto-quoted from the office when the
    # client picked coordinates; otherwise flagged for manual staff review.
    courier_km = 0.0
    courier_fee_usdt = 0.0
    courier_fee_usd = 0.0
    courier_status: Literal["none", "free", "charged", "manual_review"] = "none"
    courier_muni = None
    cq = {"rate_usdt_per_km": 0.0, "min_fee_usdt": 0.0}
    if pickup_store is None:
        from services.courier_fee import quote_courier_fee, route_quote
        # iter256(S09) — la tarifa se cotiza en la MONEDA DE LIQUIDACIÓN del
        # canje (USDT): el número cobrado y el umbral gratis usan esa unidad.
        cq = await quote_courier_fee("USDT", total)
        if cq["free"]:
            courier_status = "free"
        elif not cq["enabled"]:
            courier_status = "none"
        elif payload.delivery_latitude is not None and payload.delivery_longitude is not None:
            rq = await route_quote(payload.delivery_latitude,
                                   payload.delivery_longitude, "USDT", total)
            if rq.get("requires_manual_review") or rq.get("km") is None:
                courier_status = "manual_review"
            else:
                courier_status = "charged"
                courier_km = rq["km"]
                courier_fee_usdt = rq["fee_usdt"]
                courier_fee_usd = rq["fee_currency_amount"]
        else:
            courier_status = "manual_review"
        # iter211 — fallback por municipio para canjes (mapa no ubicó la dirección).
        if courier_status == "manual_review":
            from services.courier_fee import municipality_fallback_quote
            mq = await municipality_fallback_quote(
                payload.delivery_address or "", "USDT", total,
                municipality_key=payload.courier_municipality)
            if mq and mq.get("fee_usdt", 0) > 0:
                courier_status = "charged"
                courier_km = 0.0
                courier_fee_usdt = mq["fee_usdt"]
                courier_fee_usd = mq["fee_currency_amount"]
                courier_muni = mq["municipality"]
    # iter254(R07) — el marketplace liquida en USDT (la UI muestra USDT): el
    # cobro, los reembolsos y los pagos a vendedores usan el saldo USDT.
    if get_user_balance(user, "USDT") < total + courier_fee_usd:
        raise HTTPException(
            status_code=400,
            detail=("Saldo USDT insuficiente"
                    + (f" (incluye {courier_fee_usd} USDT de mensajería)"
                       if courier_fee_usd > 0 else "")))
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
        delivery_latitude=payload.delivery_latitude,
        delivery_longitude=payload.delivery_longitude,
        courier_km=courier_km,
        courier_fee_usdt=courier_fee_usdt,
        courier_fee_usd=courier_fee_usd,
        courier_fee_status=courier_status,
        courier_municipality=courier_muni,
        courier_rate_snapshot=cq["rate_usdt_per_km"],
        courier_min_fee_snapshot=cq["min_fee_usdt"],
        vendor_owner_id=product.get("owner_id") or "",
        vendor_owner_name=product.get("owner_name") or "",
        total_store=store_total,
        cost_store=store_cost,
        store_currency=store_currency,
        fx_rate=fx_rate,
        fulfillment=payload.fulfillment,
        store_id=(pickup_store or {}).get("id") or "",
        store_name=(pickup_store or {}).get("name") or "",
        store_address=(pickup_store or {}).get("address") or "",
        pickup_code=(await _new_pickup_code()) if pickup_store else "",
        settlement_currency="USDT",
    )
    # iter254(R03) — protocolo reserva/operación/activación recuperable:
    # 1) doc en 'initializing' con los op_ids del intento; 2) reserva de stock
    # idempotente (con condiciones R06 en el filtro); 3) cobro idempotente;
    # 4) activación. Si el proceso muere en medio, heal_initializing_ops
    # revierte de forma determinista (los op_ids dicen qué llegó a aplicarse).
    from services.balances import debit_balance_idempotent
    from services.inventory import apply_stock_idempotent
    rdoc = r.model_dump()
    stock_op = f"redeem-stock:{r.id}"
    debit_op = f"redeem-debit:{r.id}"
    rdoc.update({"status": "initializing", "init_op_id": debit_op,
                 "stock_op_id": stock_op})
    await db.redemptions.insert_one(rdoc)
    stock_status = await apply_stock_idempotent(
        product["id"], -payload.quantity, stock_op,
        extra_filter={"is_active": {"$ne": False},
                      "$or": [{"owner_id": {"$in": [None, ""]}},
                              {"owner_id": {"$exists": False}},
                              {"approval_status": "approved"}]})
    if stock_status == "insufficient":
        await db.redemptions.delete_one({"id": r.id, "status": "initializing"})
        raise HTTPException(status_code=400, detail="Stock insuficiente")
    debit_status = await debit_balance_idempotent(
        user["user_id"], "USDT", total + courier_fee_usd, debit_op)
    if debit_status == "insufficient":
        await apply_stock_idempotent(product["id"], payload.quantity,
                                     f"{stock_op}:undo",
                                     require_available=False)
        await db.redemptions.delete_one({"id": r.id, "status": "initializing"})
        raise HTTPException(
            status_code=409,
            detail={"code": "INSUFFICIENT_BALANCE",
                    "message": "Saldo USDT insuficiente"})
    act = await db.redemptions.update_one(
        {"id": r.id, "status": "initializing"},
        {"$set": {"status": "pending"},
         "$unset": {"init_op_id": "", "stock_op_id": ""}})
    if act.matched_count == 0:
        # iter256(S03) — el healer revirtió este intento (tardó demasiado):
        # deshacer nuestros efectos con los MISMOS op_ids de undo del healer
        # (idempotentes ⇒ un solo reverso total, gane quien gane la carrera).
        from services.balances import credit_balance_idempotent
        await credit_balance_idempotent(
            user["user_id"], "USDT", total + courier_fee_usd,
            f"{debit_op}:undo")
        await apply_stock_idempotent(product["id"], payload.quantity,
                                     f"{stock_op}:undo",
                                     require_available=False)
        raise HTTPException(
            status_code=409,
            detail=("La solicitud tardó demasiado y fue revertida por "
                    "seguridad; tu saldo está intacto. Inténtalo de nuevo."))
    # iter199 — auto-charged deliveries create their courier job right away.
    if courier_status == "charged":
        try:
            from services.deliveries import upsert_delivery_for_charge
            await upsert_delivery_for_charge("redemption", r.model_dump(),
                                             km=courier_km,
                                             fee_usdt=courier_fee_usdt,
                                             actor_id=user["user_id"])
        except Exception as e:
            logger.error(f"redeem delivery sync failed: {e}")
    await emit_balance_changed(user["user_id"], "marketplace_redeem",
                               redemption_id=r.id)
    # iter217 — inventario tienda física: cada canje de un producto de la
    # EMPRESA queda registrado como movimiento de Venta. Los productos de
    # vendedores VIP no entran al inventario; se notifica al dueño.
    if not product.get("owner_id"):
        try:
            from services.inventory import record_movement
            await record_movement(
                product=product, mtype="venta", quantity=payload.quantity,
                note=f"Canje marketplace de {user['name']}",
                source="marketplace", ref_id=r.id, actor=user,
                apply_stock=False)
        except Exception as e:
            logger.error(f"inventory venta record failed: {e}")
        # iter219/iter229 — el capital de la venta web entra al fondo de la
        # empresa en USDT (el cliente paga en USDT); se revierte si se rechaza.
        try:
            from services.company_funds_common import record_auto_fund_adjustment
            await db.redemptions.update_one(
                {"id": r.id},
                {"$set": {"fund_inflow_at": iso(now_utc()),
                          "fund_inflow_amount": round(total, 2),
                          "fund_inflow_currency": "USDT"}})
            await record_auto_fund_adjustment(
                adjustment_type="inflow", currency="USDT",
                amount=round(total, 2), source_name="Marketplace tienda",
                note=(f"Venta web: {payload.quantity}× {product['name']} = "
                      f"{total:.2f} USDT"
                      + (f" (≈ {store_total:g} {store_currency})"
                         if store_currency else "")
                      + f" (canje {r.id[:8]})"),
                ref_id=r.id)
        except Exception as e:
            logger.error(f"marketplace fund inflow failed: {e}")
    else:
        try:
            from routes.notifications import _insert_notification
            await _insert_notification(
                recipient_user_id=product["owner_id"],
                type="vendor_product_sold",
                title="¡Tu producto se vendió!",
                message=(f"{user['name']} canjeó {payload.quantity}× "
                         f"{product['name']} ({total:.2f} USDT). Se te "
                         "acreditará al confirmarse la entrega."),
                data={"redemption_id": r.id, "product_id": product["id"]})
        except Exception as e:
            logger.error(f"vendor sold notify failed: {e}")
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
        {"user_id": user["user_id"],
         "status": {"$nin": ["initializing", "failed_init"]}}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return docs


@router.post("/vip/redemptions/{rid}/on-my-way")
async def redemption_on_my_way(rid: str, request: Request) -> Any:
    """iter237 — el cliente avisa que va en camino a recoger su pedido.
    Idempotente (409). Notifica a los admins (campana + push + email)."""
    user = await require_user(request)
    r = await db.redemptions.find_one(
        {"id": rid, "user_id": user["user_id"]}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Canje no encontrado")
    if r.get("fulfillment") != "store_pickup":
        raise HTTPException(status_code=400,
                            detail="Este canje no es de recogida en tienda")
    if r.get("status") != "approved" or not r.get("pickup_ready_at"):
        raise HTTPException(
            status_code=400,
            detail="Tu pedido aún no está listo para recoger")
    if r.get("on_my_way_at"):
        raise HTTPException(status_code=409, detail="Ya avisaste que vas en camino")
    res = await db.redemptions.update_one(
        {"id": rid, "on_my_way_at": {"$in": [None, ""]}},
        {"$set": {"on_my_way_at": iso(now_utc())}})
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Ya avisaste que vas en camino")
    store_name = r.get("store_name") or "la tienda"
    title = "Cliente en camino a la tienda"
    body = (f"{user.get('name') or user.get('email')} va en camino a recoger "
            f"{r['quantity']}× {r['product_name']} en {store_name}.")
    try:
        from admin_alerts import notify_all_admins
        await notify_all_admins(db, title=title, body=body,
                                url_path="/admin/inventory")
        from routes.notifications import _insert_notification
        admins = await db.users.find({"role": "admin"},
                                     {"_id": 0, "user_id": 1}).to_list(50)
        for a in admins:
            await _insert_notification(
                recipient_user_id=a["user_id"], type="pickup_on_my_way",
                title=title, message=body,
                data={"redemption_id": rid, "store_id": r.get("store_id")})
    except Exception as e:
        logger.error(f"on-my-way admin notify failed: {e}")
    try:
        from services.live_bus import publish as live_publish
        await live_publish("pickups_changed", {"redemption_id": rid})
    except Exception as e:
        logger.error(f"pickups_changed publish failed: {e}")
    return await db.redemptions.find_one({"id": rid}, {"_id": 0})


# ============================================================
# VIP — Withdrawals (client side only)
# ============================================================

@router.get("/vip/cash-provinces")
async def list_cash_provinces(request: Request) -> Any:
    """iter192 — all provinces with their current cash-delivery availability
    so the withdrawal form can disable the ones without coverage."""
    await require_user(request)
    available = set(await _available_cash_provinces())
    return {"provinces": [{"name": p, "available": p in available}
                          for p in CUBA_PROVINCES]}


@router.get("/vip/courier-fee-quote")
async def courier_fee_quote(request: Request, currency: str = "USD",
                            amount: float = 0.0) -> Any:
    """iter198 — courier pricing preview for cash withdrawals (rate per km,
    free threshold and whether THIS amount qualifies for free delivery)."""
    await require_user(request)
    from services.courier_fee import quote_courier_fee
    return await quote_courier_fee(currency, amount)


@router.get("/vip/geo-reverse")
async def geo_reverse(request: Request, lat: float, lon: float) -> Any:
    """iter206 — el cliente comparte su ubicación GPS: devolvemos la
    dirección legible para que confirme antes de cotizar la mensajería."""
    await require_user(request)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Coordenadas inválidas.")
    try:
        from services.geo_routing import reverse_geocode
        name = await reverse_geocode(lat, lon)
        return {"display_name": name, "lat": lat, "lon": lon}
    except Exception as e:
        logger.error(f"geo_reverse failed: {e}")
        return {"display_name": "", "lat": lat, "lon": lon}


@router.get("/vip/geo-search")
async def geo_search(request: Request, q: str = "", province: str = "") -> Any:
    """iter198 — address autocomplete (OSM Nominatim, Cuba-first).
    iter204 — fallback para direcciones cubanas ("entre X y Y", números de
    casa) + contexto de provincia; `approximate` marca resultados de zona."""
    await require_user(request)
    term = (q or "").strip()
    if len(term) < 3:
        return {"results": []}
    try:
        from services.geo_routing import geocode_smart
        data = await geocode_smart(term, province=(province or "").strip())
        return {"results": data["results"], "approximate": data["approximate"],
                "matched_query": data["matched_query"]}
    except Exception as e:
        logger.error(f"geo_search failed: {e}")
        return {"results": [], "error": True}


@router.get("/vip/courier-route-quote")
async def courier_route_quote(request: Request, lat: float, lon: float,
                              currency: str = "USD", amount: float = 0.0) -> Any:
    """iter198 — automatic courier quote: office → destination road km + fee.
    Falls back to `requires_manual_review` when the route can't be computed
    (never bills straight-line distance)."""
    await require_user(request)
    from services.courier_fee import route_quote
    return await route_quote(lat, lon, currency, amount)


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
    # iter191 — holder name is no longer required for ANY method (the client
    # asked to drop it for transfers too; the account details already travel
    # in `details`). Kept when sent (cash auto-fills the receiver name).
    beneficiary_name = (payload.beneficiary_name or "").strip()
    if payload.method == "crypto":
        beneficiary_name = ""
    # iter192 — cash deliveries only in provinces with availability.
    # iter205 — el cliente puede elegir "recogida en oficina" (sin mensajero).
    province = (payload.province or "").strip()
    delivery_mode = ""
    if payload.method == "cash":
        delivery_mode = payload.cash_delivery_mode or "courier"
        if delivery_mode == "office_pickup":
            province = ""
        else:
            if province not in CUBA_PROVINCES:
                raise HTTPException(status_code=400,
                                    detail="Selecciona la provincia de entrega.")
            available = await _available_cash_provinces()
            if province not in available:
                raise HTTPException(
                    status_code=400,
                    detail=f"No hay disponibilidad de entrega de efectivo en {province} por el momento.",
                )
    else:
        province = ""
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
    if payload.method == "transfer":
        # iter158 — reject fake/placeholder account numbers server-side.
        from services.transfer_validation import validate_transfer_details
        err = validate_transfer_details(currency, payload.details)
        if err:
            raise HTTPException(status_code=422, detail=err)
    # iter205 — la mensajería se cobra al CREAR el retiro cash cuando la ruta
    # se calculó; si el mapa falló queda "manual_review" y el staff DEBE
    # cobrarla antes de poder marcar el retiro como entregado.
    courier_km = 0.0
    courier_fee_usdt = 0.0
    courier_fee_cur = 0.0
    courier_status = ""
    courier_rq = None
    if payload.method == "cash":
        if delivery_mode == "office_pickup":
            courier_status = "waived"
        else:
            from services.courier_fee import quote_courier_fee, route_quote
            cq = await quote_courier_fee(currency, payload.amount_usd)
            if not cq["enabled"]:
                courier_status = "none"
            elif cq["free"]:
                courier_status = "free"
            elif (payload.delivery_latitude is not None
                    and payload.delivery_longitude is not None):
                courier_rq = await route_quote(payload.delivery_latitude,
                                               payload.delivery_longitude,
                                               currency, payload.amount_usd)
                if courier_rq.get("requires_manual_review") or courier_rq.get("km") is None:
                    courier_status = "manual_review"
                else:
                    courier_status = "charged"
                    courier_km = courier_rq["km"]
                    courier_fee_usdt = courier_rq["fee_usdt"]
                    courier_fee_cur = courier_rq["fee_currency_amount"]
            else:
                courier_status = "manual_review"
    # iter211 — fallback por municipio: si el mapa no ubicó la dirección,
    # detecta el municipio en el texto y cobra su tarifa fija automáticamente.
    courier_muni = None
    if payload.method == "cash" and courier_status == "manual_review":
        from services.courier_fee import municipality_fallback_quote
        mq = await municipality_fallback_quote(
            f"{payload.details or ''} {province or ''}",
            currency, payload.amount_usd,
            municipality_key=payload.courier_municipality)
        if mq and mq.get("fee_usdt", 0) > 0:
            courier_status = "charged"
            courier_km = 0.0
            courier_fee_usdt = mq["fee_usdt"]
            courier_fee_cur = mq["fee_currency_amount"]
            courier_rq = mq
            courier_muni = mq["municipality"]
    if get_user_balance(user, currency) < payload.amount_usd + courier_fee_cur:
        raise HTTPException(
            status_code=400,
            detail=(f"Saldo insuficiente en {currency}"
                    + (f" (incluye {courier_fee_cur} {currency} de mensajería)"
                       if courier_fee_cur > 0 else "")))
    w = WithdrawalRequest(
        user_id=user["user_id"],
        user_email=user["email"],
        user_name=user["name"],
        amount_usd=payload.amount_usd,
        currency=currency,
        method=payload.method,
        details=payload.details,
        beneficiary_name=beneficiary_name,
        crypto_network=crypto_network,
        province=province,
    )
    doc = w.model_dump()
    # iter205 — persistir modalidad + cobro de mensajería hecho al crear.
    if payload.method == "cash":
        doc["cash_delivery_mode"] = delivery_mode
        doc["courier_km"] = courier_km
        doc["courier_fee_usdt"] = courier_fee_usdt
        doc["courier_fee_currency_amount"] = courier_fee_cur
        doc["courier_fee_currency"] = currency
        doc["courier_fee_status"] = courier_status
        if courier_muni:
            doc["courier_municipality"] = courier_muni
        if payload.delivery_latitude is not None \
                and payload.delivery_longitude is not None:
            doc["delivery_latitude"] = payload.delivery_latitude
            doc["delivery_longitude"] = payload.delivery_longitude
        if courier_status == "charged" and courier_rq is not None:
            doc["courier_fee_charged_at"] = iso(now_utc())
            doc["courier_fee_charged_by"] = user["user_id"]
            doc["courier_rate_snapshot"] = courier_rq["rate_usdt_per_km"]
            doc["courier_min_fee_snapshot"] = courier_rq["min_fee_usdt"]
    # iter254(R03) — protocolo recuperable: doc primero en 'initializing' con
    # el op_id del cobro; débito idempotente; activación a 'pending'. Si el
    # proceso muere en medio, heal_initializing_ops sabe (por el op_id) si el
    # cobro llegó a aplicarse y revierte o limpia de forma determinista.
    from services.balances import debit_balance_idempotent
    debit_op = f"withdraw-debit:{w.id}"
    doc["status"] = "initializing"
    doc["init_op_id"] = debit_op
    await db.withdrawals.insert_one(doc)
    st = await debit_balance_idempotent(
        user["user_id"], currency, payload.amount_usd + courier_fee_cur,
        debit_op)
    if st == "insufficient":
        await db.withdrawals.delete_one({"id": w.id, "status": "initializing"})
        raise HTTPException(
            status_code=409,
            detail={"code": "INSUFFICIENT_BALANCE",
                    "message": f"Saldo insuficiente en {currency}"})
    act = await db.withdrawals.update_one(
        {"id": w.id, "status": "initializing"},
        {"$set": {"status": "pending"}, "$unset": {"init_op_id": ""}})
    if act.matched_count == 0:
        # iter256(S03) — el healer revirtió este intento: deshacer nuestro
        # débito (mismo op de undo que el healer ⇒ un solo reverso total).
        from services.balances import credit_balance_idempotent
        await credit_balance_idempotent(
            user["user_id"], currency, payload.amount_usd + courier_fee_cur,
            f"{debit_op}:undo")
        raise HTTPException(
            status_code=409,
            detail=("La solicitud tardó demasiado y fue revertida por "
                    "seguridad; tu saldo está intacto. Inténtalo de nuevo."))
    doc["status"] = "pending"
    # iter205 — protocolo de mensajero: las entregas a domicilio (cobradas o
    # gratis por umbral) crean su trabajo de mensajería desde la creación.
    if payload.method == "cash" and delivery_mode == "courier" \
            and courier_status in ("charged", "free"):
        try:
            from services.deliveries import ensure_delivery_job
            await ensure_delivery_job("withdrawal", doc, km=courier_km,
                                      fee_usdt=courier_fee_usdt,
                                      actor_id=user["user_id"])
        except Exception as e:
            logger.error(f"withdrawal delivery job failed: {e}")
    # iter207 — mensajería SIN cobrar (mapa falló): avisar a los admins para
    # que nadie olvide cobrarla antes de entregar.
    if payload.method == "cash" and courier_status == "manual_review":
        try:
            from admin_alerts import notify_all_admins
            await notify_all_admins(
                db,
                title="⚠️ Mensajería pendiente de cobro",
                body=(f"El retiro cash de {user['name']} ({payload.amount_usd} {currency}) "
                      "quedó SIN costo de mensajería calculado (el mapa no encontró la "
                      "dirección). Cóbralo con el botón 'Mensajería' — el retiro no se "
                      "podrá marcar como entregado hasta cobrarlo."),
                url_path="/admin/withdrawals",
            )
            logger.info(f"manual_review admin alert sent for withdrawal {w.id}")
        except Exception as e:
            logger.error(f"manual_review admin notify failed: {e}")
    await emit_balance_changed(user["user_id"], "withdrawal_created",
                               withdrawal_id=w.id, currency=currency)
    try:
        await notify_all_admins(
            db,
            title="Nuevo retiro",
            body=f"{user['name']} solicitó retiro de {payload.amount_usd} {currency} ({payload.method}).",
            url_path="/admin/withdrawals",
        )
    except Exception as e:
        logger.error(f"Admin notify (withdrawal) failed: {e}")
    # iter155 — confirm receipt to the client (push + in-app) so they can
    # follow the withdrawal progress without opening the app.
    try:
        from routes.notifications import notify_user_withdrawal_step
        await notify_user_withdrawal_step(w.model_dump(), "received")
    except Exception as e:
        logger.error(f"withdrawal received push failed: {e}")
    # iter98 — SSE push to admins so /admin/queue prepends the pending
    # withdrawal in real-time.
    try:
        from services.live_bus import publish as live_publish
        await live_publish(
            "withdrawal_created",
            {
                "id": w.id,
                "user_id": w.user_id,
                "user_name": w.user_name,
                "amount_usd": w.amount_usd,
                "currency": w.currency,
                "method": w.method,
                "crypto_network": crypto_network,
                "created_at": w.created_at,
            },
            roles=("admin", "employee"),
        )
    except Exception as e:
        logger.error(f"withdrawal_created SSE publish failed: {e}")
    doc.pop("_id", None)
    return doc


@router.get("/vip/withdrawals/mine")
async def my_withdrawals(request: Request) -> Any:
    user = await require_user(request)
    docs = await db.withdrawals.find(
        {"user_id": user["user_id"],
         "status": {"$nin": ["initializing", "failed_init"]}}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return docs


@router.post("/vip/withdrawals/{wid}/cancel")
async def cancel_own_withdrawal(wid: str, request: Request) -> Any:
    """iter153 — the client cancels their own withdrawal while still pending.
    The frozen amount returns to the available balance. Conditional update
    makes double-clicks idempotent (second call gets 409)."""
    user = await require_user(request)
    w = await db.withdrawals.find_one({"id": wid}, {"_id": 0})
    if not w or w.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="Retiro no encontrado.")
    now = iso(now_utc())
    currency = w.get("currency") or "USD"
    amount = float(w.get("amount_usd") or 0.0)
    # iter198 — a courier fee charged while pending returns with the amount.
    fee_back = float(w.get("courier_fee_currency_amount") or 0.0)
    # iter249 — el guard balance_refunded evita el doble reembolso si un admin
    # rechaza el retiro en paralelo; la intención de abono viaja en el mismo
    # claim atómico y el abono es idempotente por op_id (healer ante crash).
    from services.credit_recovery import pending_marker, apply_and_clear
    marker = pending_marker(user["user_id"], currency, amount + fee_back,
                            "withdrawal-cancel-refund")
    res = await db.withdrawals.update_one(
        {"id": wid, "status": "pending", "balance_refunded": {"$ne": True}},
        {"$set": {"status": "cancelled", "cancelled_at": now,
                  "balance_refunded": True, "credit_pending": marker}},
    )
    if res.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Este retiro ya está en proceso y no puede cancelarse. Contacta a soporte.",
        )
    await apply_and_clear("withdrawals", wid, marker)
    # iter205 — el trabajo de mensajería activo muere con el retiro.
    try:
        from services.deliveries import cancel_active_delivery
        await cancel_active_delivery("withdrawal", wid, actor_id=user["user_id"],
                                     note="retiro cancelado por el cliente")
    except Exception as e:
        logger.error(f"delivery cancel failed: {e}")
    from audit_log import log_action
    await log_action(
        db, actor=user, action="withdrawal.cancelled_by_client",
        entity_type="withdrawal", entity_id=wid,
        summary=f"Retiro {amount} {currency} cancelado por el cliente",
        details={"amount_usd": amount, "currency": currency,
                 "method": w.get("method")},
    )
    try:
        await notify_all_admins(
            db,
            title="Retiro cancelado por el cliente",
            body=f"{user['name']} canceló su retiro de {amount} {currency}.",
            url_path="/admin/withdrawals",
        )
    except Exception as e:
        logger.error(f"Admin notify (withdrawal cancel) failed: {e}")
    try:
        from services.live_bus import publish as live_publish
        status_payload = {"withdrawal_id": wid, "status": "cancelled",
                          "prev_status": "pending", "amount_usd": amount,
                          "currency": currency}
        await live_publish("withdrawal_status_changed", status_payload,
                           user_id=user["user_id"])
        await live_publish("balance_updated",
                           {"reason": "withdrawal_cancelled", "withdrawal_id": wid},
                           user_id=user["user_id"])
        await live_publish("withdrawal_status_changed", status_payload,
                           roles=("admin", "employee"))
        await live_publish("ledger_changed",
                           {"reason": "withdrawal_cancelled", "withdrawal_id": wid,
                            "user_id": user["user_id"]},
                           roles=("admin", "employee"))
    except Exception as e:
        logger.error(f"withdrawal_cancelled SSE publish failed: {e}")
    return await db.withdrawals.find_one({"id": wid}, {"_id": 0})


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
    # iter153 — funds locked in pending/approved withdrawals are already
    # deducted from the available balance at creation time; expose them per
    # currency so the client SEES them as frozen instead of vanished.
    frozen: dict[str, float] = {}
    async for row in db.withdrawals.aggregate([
        {"$match": {"user_id": user["user_id"],
                    "status": {"$in": ["pending", "approved"]}}},
        {"$group": {"_id": "$currency", "total": {"$sum": "$amount_usd"}}},
    ]):
        f_code = (row["_id"] or "USD").strip().upper()
        if float(row["total"] or 0) > 0:
            frozen[f_code] = round(float(row["total"]), 4)
    rates = await build_rate_lookup()
    items = []
    total_usdt = 0.0
    frozen_total_usdt = 0.0
    for code in set(balances) | set(frozen):
        amt = float(balances.get(code) or 0.0)
        fro = float(frozen.get(code) or 0.0)
        if amt == 0 and fro == 0:
            continue
        usdt = convert_to_usdt(amt, code, rates)
        if usdt is not None:
            total_usdt += usdt
        if fro:
            f_usdt = convert_to_usdt(fro, code, rates)
            if f_usdt:
                frozen_total_usdt += f_usdt
        items.append({
            "currency": code,
            "amount": amt,
            "frozen": fro,
            "usdt_equivalent": round(usdt, 4) if usdt is not None else None,
        })
    items.sort(key=lambda x: -float(x["usdt_equivalent"] or 0))
    return {"balances": items, "total_usdt": round(total_usdt, 4),
            "frozen_total_usdt": round(frozen_total_usdt, 4)}


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
    #
    # iter101 — TIER pricing for self-conversion:
    #   • VIP  → `rate_vip`  (the VIP-tier client price)
    #   • NORMAL → `real_rate` (the operator's REAL market exit rate — the
    #                          same one used to compute platform revenue).
    #     Fallback to `rate_normal` only when a legacy rate row has no
    #     `real_rate` set.
    #
    # Why not `rate_normal` for normal clients? Because `rate_normal` on a
    # P2P direction is a promotional street price the client earns by
    # sending funds to the operator. Inverting it for a self-conversion
    # (where no external market trade happens) would give the client a
    # free 5% arbitrage the operator never intended to grant. `real_rate`
    # keeps the platform's true margin intact for every convertible pair —
    # and if admin edits `real_rate`, the conversion follows automatically.
    is_vip = user.get("role") in ("vip", "admin")

    def _pick_tier_rate(doc: dict) -> float:
        if is_vip:
            return float(doc.get("rate_vip") or 0.0)
        real = doc.get("real_rate")
        if real is not None and float(real) > 0:
            return float(real)
        return float(doc.get("rate_normal") or 0.0)

    rate_doc = await db.rates.find_one(
        {"from_code": from_code, "to_code": to_code}, {"_id": 0}
    )
    rate_used: float = 0.0
    if rate_doc:
        rate_used = _pick_tier_rate(rate_doc)
    else:
        inverse_doc = await db.rates.find_one(
            {"from_code": to_code, "to_code": from_code}, {"_id": 0}
        )
        if inverse_doc:
            inv = _pick_tier_rate(inverse_doc)
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
    fee = CONVERT_FEE_USDT
    # Atomic ledger update:
    #   1. Debit `amount_from` from the source currency.
    #   2. Debit `0.01` from USDT (fee). If source is USDT, this is the same
    #      currency — decrement_balance handles both calls independently.
    #   3. Credit `amount_to` to the destination currency.
    # iter254(R03) — TODO el asiento (débito origen + comisión USDT + crédito
    # destino) ocurre en UNA sola actualización condicional del doc del
    # usuario: no pueden quedar conversiones cobradas sin acreditar, comisiones
    # huérfanas ni carreras entre los tres movimientos.
    fee = CONVERT_FEE_USDT
    eps = 1e-6
    uid = user["user_id"]
    if from_code == "USD":
        usd_modern: dict = {"$subtract": [
            {"$ifNull": ["$vip_balances.USD", 0.0]},
            {"$subtract": [payload.amount_from, "$_legacy_take"]}]}
        if to_code == "USD":
            usd_modern = {"$add": [usd_modern, amount_to]}
        set_stage: dict = {
            "vip_balance_usd": {"$subtract": [
                {"$ifNull": ["$vip_balance_usd", 0.0]}, "$_legacy_take"]},
            "vip_balances.USD": usd_modern,
            "vip_balances.USDT": {"$add": [
                {"$ifNull": ["$vip_balances.USDT", 0.0]},
                -fee + (amount_to if to_code == "USDT" else 0.0)]},
        }
        if to_code not in ("USD", "USDT"):
            set_stage[f"vip_balances.{to_code}"] = {"$add": [
                {"$ifNull": [f"$vip_balances.{to_code}", 0.0]}, amount_to]}
        res = await db.users.update_one(
            {"user_id": uid, "$expr": {"$and": [
                {"$gte": [{"$add": [
                    {"$ifNull": ["$vip_balances.USD", 0.0]},
                    {"$ifNull": ["$vip_balance_usd", 0.0]}]},
                    payload.amount_from - eps]},
                {"$gte": [{"$ifNull": ["$vip_balances.USDT", 0.0]}, fee - eps]},
            ]}},
            [
                {"$set": {"_legacy_take": {"$min": [
                    {"$ifNull": ["$vip_balance_usd", 0.0]},
                    payload.amount_from]}}},
                {"$set": set_stage},
                {"$unset": "_legacy_take"},
            ],
        )
    else:
        inc: dict = {}
        inc[f"vip_balances.{from_code}"] = \
            inc.get(f"vip_balances.{from_code}", 0.0) - payload.amount_from
        inc["vip_balances.USDT"] = inc.get("vip_balances.USDT", 0.0) - fee
        inc[f"vip_balances.{to_code}"] = \
            inc.get(f"vip_balances.{to_code}", 0.0) + amount_to
        filt: dict = {"user_id": uid}
        need_from = payload.amount_from + (fee if from_code == "USDT" else 0.0)
        filt[f"vip_balances.{from_code}"] = {"$gte": need_from - eps}
        if from_code != "USDT":
            filt["vip_balances.USDT"] = {"$gte": fee - eps}
        res = await db.users.update_one(
            filt, {"$inc": {k: v for k, v in inc.items() if abs(v) > 1e-12}})
    if res.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail={"code": "INSUFFICIENT_BALANCE",
                    "message": ("Saldo insuficiente para completar la "
                                "conversión (el saldo cambió durante la "
                                "operación).")})
    await emit_balance_changed(user["user_id"], "convert",
                               from_code=from_code, to_code=to_code)
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
        try:
            await decrement_balance(user["user_id"], code, amt)
        except HTTPException:
            # iter248 — el saldo cambió concurrentemente; saltar esta moneda.
            continue
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
    await emit_balance_changed(user["user_id"], "dust_sweep",
                               credited_usdt=round(credited_total, 4))
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
