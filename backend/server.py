from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, Cookie, Response, Request
from fastapi.responses import JSONResponse, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import requests
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal, Dict
from datetime import datetime, timezone, timedelta
from io import BytesIO


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from email_service import notify_order_approved, notify_order_rejected
from pdf_service import generate_vip_closing_pdf
from push_service import (
    send_push,
    build_order_approved_payload,
    build_order_rejected_payload,
    VAPID_PUBLIC_KEY,
)
from admin_alerts import notify_all_admins, get_vip_threshold

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="Resilience Brothers P2P")
api_router = APIRouter(prefix="/api")

ADMIN_EMAILS = [e.strip().lower() for e in os.environ.get('ADMIN_EMAILS', '').split(',') if e.strip()]

# ============== MODELS ==============

def now_utc():
    return datetime.now(timezone.utc)

def iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else dt

class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    role: Literal["normal", "vip", "employee", "admin"] = "normal"
    vip_balance_usd: float = 0.0  # legacy USD balance, used for redemptions
    vip_balances: Dict[str, float] = {}  # per-currency balances {"USD": 100, "CUP": 38000}
    created_at: str

class Currency(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    code: str  # USDT, BTC, USD, CUP, BRL, MXN
    name: str
    type: Literal["crypto", "fiat"]
    symbol: Optional[str] = ""
    country: Optional[str] = ""
    is_active: bool = True
    payment_account: Optional[str] = ""  # Account info for deposits (Zelle, bank, etc)
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

class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    user_email: str
    user_name: str
    user_role: str
    from_code: str
    to_code: str
    amount_from: float
    amount_to: float
    rate_applied: float
    commission_percent: float
    delivery_method: Literal["transfer", "cash", "crypto", "accumulate"]
    delivery_details: str = ""  # bank info, address, wallet
    sender_name: str = ""  # name of person who sent payment
    proof_image: str = ""  # base64 data URL
    status: Literal["pending", "approved", "rejected", "completed"] = "pending"
    admin_note: str = ""
    created_at: str = Field(default_factory=lambda: iso(now_utc()))
    updated_at: str = Field(default_factory=lambda: iso(now_utc()))

class OrderCreate(BaseModel):
    from_code: str
    to_code: str
    amount_from: float
    delivery_method: Literal["transfer", "cash", "crypto", "accumulate"]
    delivery_details: str = ""
    sender_name: str = ""
    proof_image: str = ""

class Product(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    image_url: str = ""
    price_usd: float
    stock: int = 0
    category: str = "general"
    is_active: bool = True
    created_at: str = Field(default_factory=lambda: iso(now_utc()))

class ProductCreate(BaseModel):
    name: str
    description: str = ""
    image_url: str = ""
    price_usd: float
    stock: int = 0
    category: str = "general"
    is_active: bool = True

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
    status: Literal["pending", "approved", "paid", "rejected"] = "pending"
    admin_note: str = ""
    created_at: str = Field(default_factory=lambda: iso(now_utc()))

class WithdrawalCreate(BaseModel):
    amount_usd: float
    currency: str = "USD"
    method: Literal["transfer", "cash", "crypto"]
    details: str

class UserUpdate(BaseModel):
    role: Optional[Literal["normal", "vip", "employee", "admin"]] = None
    vip_balance_usd: Optional[float] = None
    vip_balances: Optional[Dict[str, float]] = None

# ============== AUTH ==============

async def get_session_user(request: Request) -> Optional[dict]:
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        return None
    sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not sess:
        return None
    expires_at = sess.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now_utc():
        return None
    user = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
    return user

async def require_user(request: Request) -> dict:
    user = await get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

async def require_admin(request: Request) -> dict:
    user = await require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user

async def require_staff(request: Request) -> dict:
    """Allow both admin and employee roles for most management endpoints."""
    user = await require_user(request)
    if user.get("role") not in ("admin", "employee"):
        raise HTTPException(status_code=403, detail="Staff only")
    return user

@api_router.post("/auth/session")
async def auth_session(payload: dict, response: Response):
    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    resp = requests.get(
        "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
        headers={"X-Session-ID": session_id},
        timeout=15,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session")
    data = resp.json()
    email = data["email"].lower()
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        # Update name/picture
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": data.get("name", existing["name"]), "picture": data.get("picture", existing.get("picture", ""))}}
        )
        user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        role = "admin" if email in ADMIN_EMAILS else "normal"
        # If this is the first user, make them admin
        count = await db.users.count_documents({})
        if count == 0:
            role = "admin"
        user_doc = {
            "user_id": user_id,
            "email": email,
            "name": data.get("name", ""),
            "picture": data.get("picture", ""),
            "role": role,
            "vip_balance_usd": 0.0,
            "created_at": iso(now_utc()),
        }
        await db.users.insert_one(user_doc)

    session_token = data["session_token"]
    expires_at = now_utc() + timedelta(days=7)
    await db.user_sessions.insert_one({
        "user_id": user_doc["user_id"],
        "session_token": session_token,
        "expires_at": iso(expires_at),
        "created_at": iso(now_utc()),
    })
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=7 * 24 * 3600,
    )
    user_doc.pop("_id", None)
    return user_doc

@api_router.get("/auth/me")
async def auth_me(request: Request):
    user = await require_user(request)
    user.pop("_id", None)
    return user

@api_router.post("/auth/logout")
async def auth_logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}

# ============== CURRENCIES ==============

@api_router.get("/currencies")
async def list_currencies():
    docs = await db.currencies.find({}, {"_id": 0}).to_list(500)
    return docs

@api_router.post("/admin/currencies")
async def create_currency(payload: CurrencyCreate, request: Request):
    await require_staff(request)
    c = Currency(**payload.model_dump())
    await db.currencies.insert_one(c.model_dump())
    return c.model_dump()

@api_router.put("/admin/currencies/{currency_id}")
async def update_currency(currency_id: str, payload: CurrencyCreate, request: Request):
    await require_staff(request)
    await db.currencies.update_one({"id": currency_id}, {"$set": payload.model_dump()})
    doc = await db.currencies.find_one({"id": currency_id}, {"_id": 0})
    return doc

@api_router.delete("/admin/currencies/{currency_id}")
async def delete_currency(currency_id: str, request: Request):
    await require_staff(request)
    await db.currencies.delete_one({"id": currency_id})
    return {"ok": True}

# ============== EXCHANGE RATES ==============

@api_router.get("/rates")
async def list_rates():
    docs = await db.rates.find({}, {"_id": 0}).to_list(500)
    return docs

@api_router.post("/admin/rates")
async def create_rate(payload: ExchangeRateCreate, request: Request):
    await require_staff(request)
    existing = await db.rates.find_one({"from_code": payload.from_code, "to_code": payload.to_code}, {"_id": 0})
    if existing:
        await db.rates.update_one(
            {"id": existing["id"]},
            {"$set": {**payload.model_dump(), "updated_at": iso(now_utc())}}
        )
        return await db.rates.find_one({"id": existing["id"]}, {"_id": 0})
    r = ExchangeRate(**payload.model_dump())
    await db.rates.insert_one(r.model_dump())
    return r.model_dump()

@api_router.put("/admin/rates/{rate_id}")
async def update_rate(rate_id: str, payload: ExchangeRateCreate, request: Request):
    await require_staff(request)
    await db.rates.update_one(
        {"id": rate_id},
        {"$set": {**payload.model_dump(), "updated_at": iso(now_utc())}}
    )
    return await db.rates.find_one({"id": rate_id}, {"_id": 0})

@api_router.delete("/admin/rates/{rate_id}")
async def delete_rate(rate_id: str, request: Request):
    await require_staff(request)
    await db.rates.delete_one({"id": rate_id})
    return {"ok": True}

# ============== ORDERS ==============

@api_router.post("/orders")
async def create_order(payload: OrderCreate, request: Request):
    user = await require_user(request)
    rate_doc = await db.rates.find_one({"from_code": payload.from_code, "to_code": payload.to_code}, {"_id": 0})
    if not rate_doc:
        raise HTTPException(status_code=400, detail="Tasa de cambio no disponible para ese par")
    is_vip = user["role"] in ("vip", "admin")
    rate = rate_doc["rate_vip"] if is_vip else rate_doc["rate_normal"]
    commission = 0.0 if is_vip else 5.0
    gross = payload.amount_from * rate
    amount_to = gross * (1 - commission / 100)
    order = Order(
        user_id=user["user_id"],
        user_email=user["email"],
        user_name=user["name"],
        user_role=user["role"],
        from_code=payload.from_code,
        to_code=payload.to_code,
        amount_from=payload.amount_from,
        amount_to=round(amount_to, 4),
        rate_applied=rate,
        commission_percent=commission,
        delivery_method=payload.delivery_method,
        delivery_details=payload.delivery_details,
        sender_name=payload.sender_name,
        proof_image=payload.proof_image,
    )
    await db.orders.insert_one(order.model_dump())
    # Notify admins of new order (push + email)
    try:
        await notify_all_admins(
            db,
            title="Nueva orden P2P pendiente",
            body=f"{user['name']} envió {order.amount_from} {order.from_code} → {order.amount_to} {order.to_code} ({user['role'].upper()}).",
            url_path="/admin/orders",
        )
    except Exception as e:
        logger.error(f"Admin notify (new order) failed: {e}")
    return order.model_dump()

@api_router.get("/orders/mine")
async def my_orders(request: Request):
    user = await require_user(request)
    docs = await db.orders.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs

@api_router.get("/admin/orders")
async def all_orders(request: Request, status: Optional[str] = None):
    await require_staff(request)
    q = {}
    if status:
        q["status"] = status
    docs = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


async def _accumulate_vip_balance(order: dict):
    """Increment VIP per-currency balance for an approved accumulate order."""
    await db.users.update_one(
        {"user_id": order["user_id"]},
        {"$inc": {f"vip_balances.{order['to_code']}": order["amount_to"]}}
    )


async def _compute_total_usdt(user_doc: dict) -> float:
    rates = await _build_rate_lookup()
    balances = dict(user_doc.get("vip_balances") or {})
    legacy = float(user_doc.get("vip_balance_usd") or 0.0)
    if legacy > 0:
        balances["USD"] = balances.get("USD", 0.0) + legacy
    return sum((_convert_to_usdt(amt, code, rates) or 0) for code, amt in balances.items())


async def _check_vip_threshold_alert(order: dict):
    """If user's total_usdt crossed the configured threshold, notify admins once."""
    try:
        threshold = await get_vip_threshold(db)
        fresh = await db.users.find_one({"user_id": order["user_id"]}, {"_id": 0})
        if not fresh:
            return
        total_usdt = await _compute_total_usdt(fresh)
        last_alert = fresh.get("last_vip_alert_threshold", 0)
        if total_usdt >= threshold and total_usdt > last_alert:
            await notify_all_admins(
                db,
                title="⚠️ Cliente VIP supera umbral",
                body=f"{fresh['name']} acumula ${total_usdt:,.2f} USDT (umbral ${threshold:,.0f}). Considera proponerle cierre o canje.",
                url_path="/admin/users",
            )
            await db.users.update_one(
                {"user_id": order["user_id"]},
                {"$set": {"last_vip_alert_threshold": total_usdt}}
            )
    except Exception as e:
        logger.error(f"VIP threshold alert failed: {e}")


async def _send_client_order_email(order: dict, new_status: str, target_user: dict):
    try:
        if new_status == "approved":
            notify_order_approved(order, target_user)
        else:
            notify_order_rejected(order, target_user)
    except Exception as e:
        logger.error(f"Email notification failed: {e}")


async def _send_client_order_push(order: dict, new_status: str):
    try:
        push_payload = (
            build_order_approved_payload(order)
            if new_status == "approved"
            else build_order_rejected_payload(order)
        )
        subs = await db.push_subscriptions.find({"user_id": order["user_id"]}, {"_id": 0}).to_list(50)
        dead_ids = [s["id"] for s in subs if send_push(s["subscription"], push_payload) == "dead"]
        if dead_ids:
            await db.push_subscriptions.delete_many({"id": {"$in": dead_ids}})
    except Exception as e:
        logger.error(f"Push notification failed: {e}")


@api_router.put("/admin/orders/{order_id}/status")
async def update_order_status(order_id: str, payload: dict, request: Request):
    await require_staff(request)
    new_status = payload.get("status")
    note = payload.get("admin_note", "")
    if new_status not in ("approved", "rejected", "completed", "pending"):
        raise HTTPException(status_code=400, detail="status inválido")
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"status": new_status, "admin_note": note, "updated_at": iso(now_utc())}}
    )

    is_first_approval = new_status == "approved" and order["status"] != "approved"
    if (is_first_approval
            and order["delivery_method"] == "accumulate"
            and order["user_role"] in ("vip", "admin")):
        await _accumulate_vip_balance(order)
        await _check_vip_threshold_alert(order)

    updated = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if new_status in ("approved", "rejected") and order["status"] != new_status:
        target_user = await db.users.find_one({"user_id": order["user_id"]}, {"_id": 0})
        if target_user:
            await _send_client_order_email(updated, new_status, target_user)
            await _send_client_order_push(updated, new_status)
    return updated

# ============== PRODUCTS ==============

@api_router.get("/products")
async def list_products():
    docs = await db.products.find({"is_active": True}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs

@api_router.post("/admin/products")
async def create_product(payload: ProductCreate, request: Request):
    await require_staff(request)
    p = Product(**payload.model_dump())
    await db.products.insert_one(p.model_dump())
    return p.model_dump()

@api_router.put("/admin/products/{product_id}")
async def update_product(product_id: str, payload: ProductCreate, request: Request):
    await require_staff(request)
    await db.products.update_one({"id": product_id}, {"$set": payload.model_dump()})
    return await db.products.find_one({"id": product_id}, {"_id": 0})

@api_router.delete("/admin/products/{product_id}")
async def delete_product(product_id: str, request: Request):
    await require_staff(request)
    await db.products.delete_one({"id": product_id})
    return {"ok": True}

# ============== VIP - REDEMPTIONS & WITHDRAWALS ==============

def _get_user_balance(user: dict, code: str) -> float:
    """Get user's balance in a specific currency. Merges legacy vip_balance_usd into USD."""
    bal = float((user.get("vip_balances") or {}).get(code, 0.0))
    if code == "USD":
        bal += float(user.get("vip_balance_usd") or 0.0)
    return bal


async def _decrement_balance(user_id: str, code: str, amount: float):
    """Decrement a currency balance. For USD, prefer vip_balance_usd legacy field first."""
    if code == "USD":
        # Try legacy field first, then dict
        user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
        legacy = float(user.get("vip_balance_usd") or 0.0)
        if legacy >= amount:
            await db.users.update_one({"user_id": user_id}, {"$inc": {"vip_balance_usd": -amount}})
            return
        remainder = amount - legacy
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"vip_balance_usd": 0.0}, "$inc": {f"vip_balances.{code}": -remainder}}
        )
    else:
        await db.users.update_one({"user_id": user_id}, {"$inc": {f"vip_balances.{code}": -amount}})


@api_router.post("/vip/redeem")
async def redeem_product(payload: RedemptionCreate, request: Request):
    user = await require_user(request)
    if user["role"] not in ("vip", "admin"):
        raise HTTPException(status_code=403, detail="Solo clientes VIP")
    product = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if product["stock"] < payload.quantity:
        raise HTTPException(status_code=400, detail="Stock insuficiente")
    total = product["price_usd"] * payload.quantity
    if _get_user_balance(user, "USD") < total:
        raise HTTPException(status_code=400, detail="Saldo USD insuficiente")
    r = Redemption(
        user_id=user["user_id"],
        user_email=user["email"],
        user_name=user["name"],
        product_id=product["id"],
        product_name=product["name"],
        quantity=payload.quantity,
        total_usd=total,
        delivery_address=payload.delivery_address,
    )
    await db.redemptions.insert_one(r.model_dump())
    await _decrement_balance(user["user_id"], "USD", total)
    await db.products.update_one({"id": product["id"]}, {"$inc": {"stock": -payload.quantity}})
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

@api_router.get("/vip/redemptions/mine")
async def my_redemptions(request: Request):
    user = await require_user(request)
    docs = await db.redemptions.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs

@api_router.get("/admin/redemptions")
async def all_redemptions(request: Request):
    await require_staff(request)
    docs = await db.redemptions.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs

@api_router.put("/admin/redemptions/{rid}/status")
async def update_redemption(rid: str, payload: dict, request: Request):
    await require_staff(request)
    new_status = payload.get("status")
    note = payload.get("admin_note", "")
    if new_status not in ("approved", "delivered", "rejected", "pending"):
        raise HTTPException(status_code=400, detail="status inválido")
    r = await db.redemptions.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="No encontrado")
    # If rejected, refund balance + stock
    if new_status == "rejected" and r["status"] != "rejected":
        await db.users.update_one({"user_id": r["user_id"]}, {"$inc": {"vip_balance_usd": r["total_usd"]}})
        await db.products.update_one({"id": r["product_id"]}, {"$inc": {"stock": r["quantity"]}})
    await db.redemptions.update_one({"id": rid}, {"$set": {"status": new_status, "admin_note": note}})
    return await db.redemptions.find_one({"id": rid}, {"_id": 0})

@api_router.post("/vip/withdraw")
async def create_withdrawal(payload: WithdrawalCreate, request: Request):
    user = await require_user(request)
    if user["role"] not in ("vip", "admin"):
        raise HTTPException(status_code=403, detail="Solo clientes VIP")
    currency = payload.currency or "USD"
    if _get_user_balance(user, currency) < payload.amount_usd:
        raise HTTPException(status_code=400, detail=f"Saldo insuficiente en {currency}")
    w = WithdrawalRequest(
        user_id=user["user_id"],
        user_email=user["email"],
        user_name=user["name"],
        amount_usd=payload.amount_usd,
        currency=currency,
        method=payload.method,
        details=payload.details,
    )
    await db.withdrawals.insert_one(w.model_dump())
    await _decrement_balance(user["user_id"], currency, payload.amount_usd)
    try:
        await notify_all_admins(
            db,
            title="Nuevo retiro VIP",
            body=f"{user['name']} solicitó retiro de {payload.amount_usd} {currency} ({payload.method}).",
            url_path="/admin/withdrawals",
        )
    except Exception as e:
        logger.error(f"Admin notify (withdrawal) failed: {e}")
    return w.model_dump()

@api_router.get("/vip/withdrawals/mine")
async def my_withdrawals(request: Request):
    user = await require_user(request)
    docs = await db.withdrawals.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs

@api_router.get("/admin/withdrawals")
async def all_withdrawals(request: Request):
    await require_staff(request)
    docs = await db.withdrawals.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs

@api_router.put("/admin/withdrawals/{wid}/status")
async def update_withdrawal(wid: str, payload: dict, request: Request):
    await require_staff(request)
    new_status = payload.get("status")
    note = payload.get("admin_note", "")
    if new_status not in ("approved", "paid", "rejected", "pending"):
        raise HTTPException(status_code=400, detail="status inválido")
    w = await db.withdrawals.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(status_code=404, detail="No encontrado")
    if new_status == "rejected" and w["status"] != "rejected":
        refund_currency = w.get("currency", "USD")
        await db.users.update_one(
            {"user_id": w["user_id"]},
            {"$inc": {f"vip_balances.{refund_currency}": w["amount_usd"]}}
        )
    await db.withdrawals.update_one({"id": wid}, {"$set": {"status": new_status, "admin_note": note}})
    return await db.withdrawals.find_one({"id": wid}, {"_id": 0})

# ============== VIP DAILY CLOSING PDF ==============

@api_router.get("/vip/daily-closing")
async def vip_daily_closing(request: Request, date: Optional[str] = None):
    user = await require_user(request)
    if user["role"] not in ("vip", "admin"):
        raise HTTPException(status_code=403, detail="Solo clientes VIP")
    # Date in YYYY-MM-DD (UTC). Defaults to today.
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


# ============== VIP BALANCES & STATS ==============

async def _build_rate_lookup() -> dict:
    """Return rate lookup dict { (from,to): rate_normal } for conversion."""
    docs = await db.rates.find({}, {"_id": 0}).to_list(1000)
    return {(d["from_code"], d["to_code"]): float(d["rate_normal"]) for d in docs}


def _convert_direct(amount: float, code: str, rates: dict) -> Optional[float]:
    """Try direct or inverse conversion code↔USDT. Returns None if no path."""
    if (code, "USDT") in rates:
        return amount * rates[(code, "USDT")]
    inverse = rates.get(("USDT", code))
    if inverse and inverse > 0:
        return amount / inverse
    return None


def _convert_via_usd(amount: float, code: str, rates: dict) -> Optional[float]:
    """Convert code → USD → USDT. Returns None if no path."""
    usd_val = None
    if (code, "USD") in rates:
        usd_val = amount * rates[(code, "USD")]
    else:
        inv = rates.get(("USD", code))
        if inv and inv > 0:
            usd_val = amount / inv
    if usd_val is None:
        return None
    direct = _convert_direct(usd_val, "USD", rates)
    if direct is not None:
        return direct
    return usd_val  # assume 1 USD ≈ 1 USDT if no rate found


def _convert_to_usdt(amount: float, code: str, rates: dict) -> Optional[float]:
    """Convert amount in `code` to USDT using available rates. Returns None if no path."""
    if amount == 0:
        return 0.0
    if code == "USDT":
        return amount
    direct = _convert_direct(amount, code, rates)
    if direct is not None:
        return direct
    return _convert_via_usd(amount, code, rates)


@api_router.get("/vip/balances")
async def vip_balances(request: Request):
    user = await require_user(request)
    if user["role"] not in ("vip", "admin"):
        raise HTTPException(status_code=403, detail="Solo clientes VIP")
    # Merge legacy USD into dict
    balances = dict(user.get("vip_balances") or {})
    legacy_usd = float(user.get("vip_balance_usd") or 0.0)
    if legacy_usd > 0:
        balances["USD"] = balances.get("USD", 0.0) + legacy_usd
    rates = await _build_rate_lookup()
    items = []
    total_usdt = 0.0
    for code, amount in balances.items():
        amt = float(amount or 0.0)
        if amt == 0:
            continue
        usdt = _convert_to_usdt(amt, code, rates)
        if usdt is not None:
            total_usdt += usdt
        items.append({
            "currency": code,
            "amount": amt,
            "usdt_equivalent": round(usdt, 4) if usdt is not None else None,
        })
    items.sort(key=lambda x: -(x["usdt_equivalent"] or 0))
    return {"balances": items, "total_usdt": round(total_usdt, 4)}


async def _aggregate_flow(group_field: str, rates: dict) -> dict:
    """Aggregate approved/completed orders by a field with USDT conversion."""
    pipeline = [
        {"$match": {"status": {"$in": ["approved", "completed"]}}},
        {"$group": {"_id": f"${group_field}", "total": {"$sum": "$amount_from" if group_field == "from_code" else "$amount_to"}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(100)
    items = []
    total_usdt = 0.0
    for row in rows:
        code = row["_id"]
        amt = float(row["total"] or 0.0)
        usdt = _convert_to_usdt(amt, code, rates)
        if usdt is not None:
            total_usdt += usdt
        items.append({
            "currency": code,
            "total": amt,
            "count": row["count"],
            "usdt_equivalent": round(usdt, 4) if usdt is not None else None,
        })
    return {"items": items, "total_usdt": round(total_usdt, 4)}


async def _aggregate_vip_holdings(rates: dict) -> dict:
    """Sum vip_balances across all VIP/admin users and convert to USDT."""
    users = await db.users.find({"role": {"$in": ["vip", "admin"]}}, {"_id": 0}).to_list(1000)
    totals = {}
    for u in users:
        for code, amt in (u.get("vip_balances") or {}).items():
            totals[code] = totals.get(code, 0.0) + float(amt or 0.0)
        legacy = float(u.get("vip_balance_usd") or 0.0)
        if legacy > 0:
            totals["USD"] = totals.get("USD", 0.0) + legacy
    items = []
    total_usdt = 0.0
    for code, amt in totals.items():
        usdt = _convert_to_usdt(amt, code, rates)
        if usdt is not None:
            total_usdt += usdt
        items.append({
            "currency": code,
            "total": amt,
            "usdt_equivalent": round(usdt, 4) if usdt is not None else None,
        })
    items.sort(key=lambda x: -(x["usdt_equivalent"] or 0))
    return {"items": items, "total_usdt": round(total_usdt, 4)}


async def _platform_counters() -> dict:
    return {
        "users_total": await db.users.count_documents({}),
        "users_vip": await db.users.count_documents({"role": "vip"}),
        "orders_total": await db.orders.count_documents({}),
        "orders_pending": await db.orders.count_documents({"status": "pending"}),
        "withdrawals_pending": await db.withdrawals.count_documents({"status": "pending"}),
    }


@api_router.get("/admin/stats")
async def admin_platform_stats(request: Request):
    await require_staff(request)
    rates = await _build_rate_lookup()
    return {
        "inflow": await _aggregate_flow("from_code", rates),
        "outflow": await _aggregate_flow("to_code", rates),
        "vip_holdings": await _aggregate_vip_holdings(rates),
        "counters": await _platform_counters(),
    }


# ============== ADMIN SETTINGS ==============

class AdminSettings(BaseModel):
    vip_threshold_usdt: float = Field(default=5000.0, ge=0)


@api_router.get("/admin/settings")
async def get_admin_settings(request: Request):
    await require_staff(request)
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0})
    if not doc:
        return {"vip_threshold_usdt": float(os.environ.get("VIP_ALERT_THRESHOLD_USDT", 5000))}
    return {"vip_threshold_usdt": float(doc.get("vip_threshold_usdt", 5000))}


@api_router.put("/admin/settings")
async def update_admin_settings(payload: AdminSettings, request: Request):
    await require_admin(request)
    await db.settings.update_one(
        {"id": "global"},
        {"$set": {"id": "global", "vip_threshold_usdt": payload.vip_threshold_usdt}},
        upsert=True,
    )
    return {"ok": True, "vip_threshold_usdt": payload.vip_threshold_usdt}


# ============== PUSH NOTIFICATIONS ==============

class PushSubscriptionCreate(BaseModel):
    subscription: dict  # browser PushSubscription JSON
    user_agent: Optional[str] = ""


@api_router.get("/push/vapid-public-key")
async def push_vapid_public_key():
    return {"key": VAPID_PUBLIC_KEY}


@api_router.post("/push/subscribe")
async def push_subscribe(payload: PushSubscriptionCreate, request: Request):
    user = await require_user(request)
    endpoint = (payload.subscription or {}).get("endpoint", "")
    if not endpoint:
        raise HTTPException(status_code=400, detail="Subscription inválida")
    # Upsert by endpoint to avoid duplicates
    await db.push_subscriptions.update_one(
        {"endpoint": endpoint},
        {"$set": {
            "id": str(uuid.uuid4()),
            "user_id": user["user_id"],
            "endpoint": endpoint,
            "subscription": payload.subscription,
            "user_agent": payload.user_agent or "",
            "created_at": iso(now_utc()),
        }},
        upsert=True,
    )
    return {"ok": True}


@api_router.post("/push/unsubscribe")
async def push_unsubscribe(payload: dict, request: Request):
    user = await require_user(request)
    endpoint = payload.get("endpoint", "")
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint requerido")
    await db.push_subscriptions.delete_one({"endpoint": endpoint, "user_id": user["user_id"]})
    return {"ok": True}


@api_router.post("/push/test")
async def push_test(request: Request):
    """Send a test push to the current user's devices (helps the user verify it works)."""
    user = await require_user(request)
    subs = await db.push_subscriptions.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(50)
    if not subs:
        raise HTTPException(status_code=404, detail="No tienes dispositivos suscritos")
    payload = {
        "title": "Resilience Brothers",
        "body": "Notificaciones activadas correctamente ✓",
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": "test-notification",
        "url": "/dashboard",
    }
    delivered = 0
    for s in subs:
        if send_push(s["subscription"], payload) == "ok":
            delivered += 1
    return {"delivered": delivered, "total": len(subs)}


# ============== REVENUE (ADMIN ONLY) ==============

async def _compute_order_profit(order: dict, rate_doc: Optional[dict]) -> Optional[dict]:
    """Compute profit for a single approved/completed order in to_code currency.
    Profit logic: we receive amount_from in F, deliver amount_to in T.
    Real value of incoming = amount_from * real_rate (in T units).
    Profit (in T) = (amount_from * real_rate) - amount_to.
    """
    if not rate_doc or rate_doc.get("real_rate") is None:
        return None
    real_rate = float(rate_doc["real_rate"])
    if real_rate <= 0:
        return None
    real_value = order["amount_from"] * real_rate  # in to_code units
    profit_to = real_value - order["amount_to"]
    profit_pct = (profit_to / real_value * 100) if real_value > 0 else 0.0
    return {
        "amount": profit_to,
        "currency": order["to_code"],
        "pct": round(profit_pct, 3),
    }


@api_router.get("/admin/revenue")
async def admin_revenue(request: Request, days: Optional[int] = None):
    await require_admin(request)
    q = {"status": {"$in": ["approved", "completed"]}}
    if days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["updated_at"] = {"$gte": cutoff}

    orders = await db.orders.find(q, {"_id": 0}).to_list(5000)
    rates = await db.rates.find({}, {"_id": 0}).to_list(500)
    rate_by_pair = {(r["from_code"], r["to_code"]): r for r in rates}
    fx = await _build_rate_lookup()

    by_pair: dict = {}
    by_role = {"normal": {"profit_usdt": 0.0, "orders": 0, "volume_usdt": 0.0},
               "vip": {"profit_usdt": 0.0, "orders": 0, "volume_usdt": 0.0}}
    missing_rate_pairs = set()
    total_profit_usdt = 0.0
    total_volume_usdt = 0.0

    for o in orders:
        pair_key = (o["from_code"], o["to_code"])
        rate_doc = rate_by_pair.get(pair_key)
        profit = await _compute_order_profit(o, rate_doc)
        # Volume always counted
        volume_usdt = _convert_to_usdt(o["amount_from"], o["from_code"], fx) or 0.0
        total_volume_usdt += volume_usdt
        role_bucket = "vip" if o.get("user_role") in ("vip", "admin") else "normal"
        by_role[role_bucket]["orders"] += 1
        by_role[role_bucket]["volume_usdt"] += volume_usdt

        if profit is None:
            missing_rate_pairs.add(f"{o['from_code']}→{o['to_code']}")
            continue
        profit_usdt = _convert_to_usdt(profit["amount"], profit["currency"], fx) or 0.0
        total_profit_usdt += profit_usdt
        by_role[role_bucket]["profit_usdt"] += profit_usdt

        key = f"{o['from_code']}→{o['to_code']}"
        if key not in by_pair:
            by_pair[key] = {
                "pair": key,
                "from_code": o["from_code"],
                "to_code": o["to_code"],
                "orders": 0,
                "volume_from": 0.0,
                "volume_to": 0.0,
                "profit_to": 0.0,
                "profit_usdt": 0.0,
                "real_rate": rate_doc.get("real_rate"),
                "rate_normal": rate_doc.get("rate_normal"),
                "rate_vip": rate_doc.get("rate_vip"),
                "avg_profit_pct": 0.0,
            }
        bucket = by_pair[key]
        bucket["orders"] += 1
        bucket["volume_from"] += o["amount_from"]
        bucket["volume_to"] += o["amount_to"]
        bucket["profit_to"] += profit["amount"]
        bucket["profit_usdt"] += profit_usdt

    pair_items = []
    for k, b in by_pair.items():
        if b["volume_to"] > 0 and b["real_rate"]:
            real_value = b["volume_from"] * float(b["real_rate"])
            b["avg_profit_pct"] = round((real_value - b["volume_to"]) / real_value * 100, 3) if real_value > 0 else 0.0
        b["profit_to"] = round(b["profit_to"], 4)
        b["profit_usdt"] = round(b["profit_usdt"], 4)
        pair_items.append(b)
    pair_items.sort(key=lambda x: -x["profit_usdt"])

    for r in by_role.values():
        r["profit_usdt"] = round(r["profit_usdt"], 4)
        r["volume_usdt"] = round(r["volume_usdt"], 4)

    return {
        "total_profit_usdt": round(total_profit_usdt, 4),
        "total_volume_usdt": round(total_volume_usdt, 4),
        "profit_margin_pct": round((total_profit_usdt / total_volume_usdt * 100), 3) if total_volume_usdt > 0 else 0.0,
        "by_pair": pair_items,
        "by_role": by_role,
        "missing_real_rate_pairs": sorted(missing_rate_pairs),
        "orders_total": len(orders),
    }


# ============== USERS (ADMIN) ==============

@api_router.get("/admin/users")
async def list_users(request: Request):
    await require_staff(request)
    docs = await db.users.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs

@api_router.put("/admin/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdate, request: Request):
    requester = await require_staff(request)
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Nada para actualizar")
    # Employees can only assign 'normal' or 'vip' roles, not admin/employee
    if requester.get("role") == "employee" and "role" in update and update["role"] in ("admin", "employee"):
        raise HTTPException(status_code=403, detail="Solo un admin puede asignar este rol")
    await db.users.update_one({"user_id": user_id}, {"$set": update})
    return await db.users.find_one({"user_id": user_id}, {"_id": 0})

# ============== SEED ==============

@api_router.post("/admin/seed")
async def seed_data(request: Request):
    await require_staff(request)
    # Seed currencies if empty
    if await db.currencies.count_documents({}) == 0:
        defaults = [
            {"code": "USDT", "name": "Tether", "type": "crypto", "symbol": "₮", "country": "", "is_active": True, "payment_account": "Wallet TRC20: TXxxxxxxxxxxxx"},
            {"code": "BTC", "name": "Bitcoin", "type": "crypto", "symbol": "₿", "country": "", "is_active": True, "payment_account": "Wallet: bc1qxxxxxxxx"},
            {"code": "USD", "name": "US Dollar (Zelle)", "type": "fiat", "symbol": "$", "country": "USA", "is_active": True, "payment_account": "Zelle: pagos@resilience.com"},
            {"code": "CUP", "name": "Peso Cubano", "type": "fiat", "symbol": "₱", "country": "Cuba", "is_active": True, "payment_account": ""},
            {"code": "BRL", "name": "Real Brasileño", "type": "fiat", "symbol": "R$", "country": "Brasil", "is_active": True, "payment_account": ""},
            {"code": "MXN", "name": "Peso Mexicano", "type": "fiat", "symbol": "$", "country": "México", "is_active": True, "payment_account": ""},
        ]
        for d in defaults:
            await db.currencies.insert_one(Currency(**d).model_dump())
    if await db.rates.count_documents({}) == 0:
        rates_default = [
            {"from_code": "USD", "to_code": "CUP", "rate_normal": 380, "rate_vip": 395},
            {"from_code": "USD", "to_code": "BRL", "rate_normal": 4.9, "rate_vip": 5.05},
            {"from_code": "USD", "to_code": "MXN", "rate_normal": 17.2, "rate_vip": 17.6},
            {"from_code": "USDT", "to_code": "CUP", "rate_normal": 378, "rate_vip": 393},
            {"from_code": "USDT", "to_code": "USD", "rate_normal": 0.98, "rate_vip": 0.99},
        ]
        for d in rates_default:
            await db.rates.insert_one(ExchangeRate(**d).model_dump())
    if await db.products.count_documents({}) == 0:
        prods = [
            {"name": "Contenedor de Arroz (40 sacos)", "description": "Saco de 25kg, arroz blanco grado A.", "image_url": "https://images.unsplash.com/photo-1586201375761-83865001e31c?w=600", "price_usd": 1800, "stock": 5, "category": "alimentos"},
            {"name": "Contenedor de Harina (30 sacos)", "description": "Harina de trigo refinada, 25kg.", "image_url": "https://images.unsplash.com/photo-1574323347407-f5e1ad6d020b?w=600", "price_usd": 1200, "stock": 8, "category": "alimentos"},
            {"name": "Pallet de Refrescos (200 cajas)", "description": "Refrescos surtidos, lata 355ml.", "image_url": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=600", "price_usd": 900, "stock": 15, "category": "bebidas"},
            {"name": "Aceite Vegetal (Pallet 120L)", "description": "Aceite refinado en bidones.", "image_url": "https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?w=600", "price_usd": 550, "stock": 20, "category": "alimentos"},
        ]
        for d in prods:
            await db.products.insert_one(Product(**d).model_dump())
    return {"ok": True, "message": "Seed completado"}

@api_router.get("/")
async def root():
    return {"service": "Resilience Brothers P2P", "status": "ok"}

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
