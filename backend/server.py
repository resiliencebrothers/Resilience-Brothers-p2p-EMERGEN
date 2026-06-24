from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, Cookie, Response, Request
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import base64
import json
import httpx
import requests
from urllib.parse import urlencode
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Literal, Dict
from datetime import datetime, timezone, timedelta
from io import BytesIO


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from email_service import notify_order_approved, notify_order_rejected
import email_service
from pdf_service import generate_vip_closing_pdf
from push_service import (
    send_push,
    build_order_approved_payload,
    build_order_rejected_payload,
    VAPID_PUBLIC_KEY,
)
from admin_alerts import notify_all_admins, get_vip_threshold
from audit_log import log_action
import totp_service
from audit_pdf import generate_audit_pdf
from transactions_pdf import generate_transactions_pdf
from revenue_report import build_buckets, revenue_monthly_csv, revenue_monthly_pdf
import csv
import json as _json

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
    # iter21 — granular marketplace permissions for `employee` role. Admin bypasses all checks.
    can_edit_product_prices: bool = False
    can_upload_product_images: bool = False
    can_delete_products: bool = False
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
    totp_code: Optional[str] = Field(None, max_length=11, description="Código 2FA requerido al editar")

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
    status: Literal["pending", "requires_double_approval", "approved", "rejected", "completed"] = "pending"
    admin_note: str = ""
    created_at: str = Field(default_factory=lambda: iso(now_utc()))
    updated_at: str = Field(default_factory=lambda: iso(now_utc()))

class OrderCreate(BaseModel):
    from_code: str
    to_code: str
    amount_from: float
    delivery_method: Literal["transfer", "cash", "crypto", "accumulate"]
    delivery_details: str = ""
    sender_name: str = Field(..., min_length=2, description="Nombre del titular de la cuenta que hizo la transferencia")
    proof_image: str = ""

class Product(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    image_url: str = ""
    price_usd: float
    cost_usd: float = 0.0  # admin's acquisition cost; price_usd - cost_usd = profit per unit
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
    cost_usd: float = 0.0  # snapshot of admin cost at redemption time
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
    beneficiary_name: str = ""  # holder name of the receiving account
    status: Literal["pending", "approved", "paid", "rejected"] = "pending"
    admin_note: str = ""
    # Iter14 — fulfillment evidence (uploaded when admin marks paid/entregado)
    payout_proof_image: str = ""  # base64 image of the bank/crypto transfer made BY the platform
    payout_tx_hash: str = ""      # blockchain hash for crypto payouts
    created_at: str = Field(default_factory=lambda: iso(now_utc()))

class WithdrawalCreate(BaseModel):
    amount_usd: float
    currency: str = "USD"
    method: Literal["transfer", "cash", "crypto"]
    details: str
    beneficiary_name: str = Field(..., min_length=2, description="Nombre del titular de la cuenta beneficiaria")
    totp_code: Optional[str] = Field(None, min_length=6, max_length=11, description="Código TOTP (6 dígitos) o código de recuperación (XXXXX-XXXXX)")

class UserUpdate(BaseModel):
    role: Optional[Literal["normal", "vip", "employee", "admin"]] = None
    vip_balance_usd: Optional[float] = None  # admin-only correction (not editable from new UI)
    vip_balances: Optional[Dict[str, float]] = None
    allowed_currencies: Optional[List[str]] = None   # iter14 — employee currency scope
    # iter21 — employee marketplace permissions
    can_edit_product_prices: Optional[bool] = None
    can_upload_product_images: Optional[bool] = None
    can_delete_products: Optional[bool] = None
    totp_code: Optional[str] = Field(None, max_length=11, description="Código 2FA requerido")


# Iter15 — Company fund withdrawals (platform working capital outflows)
class CompanyWithdrawal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    amount: float
    currency: str
    beneficiary: str            # destination account / person
    authorized_by_id: str       # logged user id
    authorized_by_name: str
    authorized_by_email: str
    concept: str = ""           # purpose / category
    invoice_image: str = ""     # base64 receipt (optional)
    note: str = ""
    status: Literal["pending", "approved", "paid", "rejected"] = "pending"
    created_at: str = Field(default_factory=lambda: iso(now_utc()))


class CompanyWithdrawalCreate(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str
    beneficiary: str = Field(..., min_length=2)
    concept: str = ""
    invoice_image: str = ""
    note: str = ""
    totp_code: Optional[str] = Field(None, max_length=11)

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


def _enforce_employee_currency_scope(actor: dict, *codes: str) -> None:
    """Iter14: employees may only act on entities involving currencies they're
    authorized for. Admins bypass. Empty `allowed_currencies` = unrestricted."""
    if actor.get("role") != "employee":
        return
    allowed = actor.get("allowed_currencies") or []
    if not allowed:
        return
    codes = [c for c in codes if c]
    if not codes:
        return
    if not any(c in allowed for c in codes):
        raise HTTPException(
            status_code=403,
            detail=f"No estás autorizado a gestionar las monedas: {', '.join(codes)}",
        )

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
            "onboarding_completed": False,
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


# ============================================================
# iter22 — Custom Google OAuth 2.0 (replaces Emergent Google Auth)
# REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
# ============================================================
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")


def _decode_jwt_payload(token: str) -> dict:
    """Parse the payload of a JWT obtained directly from Google's token endpoint
    over TLS. Signature verification is unnecessary here because the token was
    delivered through an authenticated server-to-server channel (we hold the
    client_secret) — not from an untrusted client."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed id_token")
    payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64))


@api_router.get("/auth/google/login")
async def google_login(request: Request, redirect: Optional[str] = None):
    """Build the Google OAuth URL and 302-redirect the browser to it."""
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not configured")
    # Origin where the user came from (preview vs production). Trust the Host header set by ingress.
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    proto = request.headers.get("x-forwarded-proto", "https")
    origin = f"{proto}://{host}"
    redirect_uri = f"{origin}/api/auth/google/callback"
    state_token = uuid.uuid4().hex
    post_login_redirect = redirect or "/dashboard"
    await db.oauth_states.insert_one({
        "state": state_token,
        "redirect": post_login_redirect,
        "redirect_uri": redirect_uri,
        "created_at": iso(now_utc()),
        "expires_at": iso(now_utc() + timedelta(minutes=10)),
    })
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state_token,
        "access_type": "online",
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(url=url, status_code=302)


@api_router.get("/auth/google/callback")
async def google_callback(request: Request, code: Optional[str] = None,
                           state: Optional[str] = None, error: Optional[str] = None):
    """Exchange the code for tokens, lookup/create the user by email, issue a session cookie,
    and bounce the browser to the SPA's post-login page."""
    if error:
        # User declined consent — bounce back to landing with a flag the SPA can read
        return RedirectResponse(url=f"/?auth_error={error}", status_code=302)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    state_doc = await db.oauth_states.find_one_and_delete({"state": state})
    if not state_doc:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    # Exchange the authorization code for tokens (server-side, requires client_secret)
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": state_doc["redirect_uri"],
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if token_resp.status_code != 200:
        raise HTTPException(status_code=401, detail=f"Token exchange failed: {token_resp.text}")
    tokens = token_resp.json()
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=401, detail="No id_token returned by Google")
    claims = _decode_jwt_payload(id_token)
    if claims.get("aud") != GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=401, detail="id_token audience mismatch")
    email = (claims.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=401, detail="Google id_token missing email claim")
    if claims.get("email_verified") is False:
        raise HTTPException(status_code=401, detail="Google account email not verified")

    name = claims.get("name") or ""
    picture = claims.get("picture") or ""

    # Option A — match by email (links to legacy Emergent Google Auth users automatically)
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": name or existing.get("name", ""),
                       "picture": picture or existing.get("picture", ""),
                       "email_verified": True,
                       "auth_provider": existing.get("auth_provider") or "google"}},
        )
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        role = "admin" if email in ADMIN_EMAILS else "normal"
        if await db.users.count_documents({}) == 0:
            role = "admin"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "role": role,
            "auth_provider": "google",
            "email_verified": True,
            "vip_balance_usd": 0.0,
            "onboarding_completed": False,
            "created_at": iso(now_utc()),
        })

    # Issue session cookie (default 7d, same as Emergent Auth had)
    response = RedirectResponse(url=state_doc.get("redirect", "/dashboard"), status_code=302)
    await _create_session(user_id, response, ttl_hours=168)
    return response


@api_router.post("/me/onboarding/complete")
async def complete_onboarding(request: Request):
    """Mark the current user's first-visit onboarding tour as completed."""
    user = await require_user(request)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"onboarding_completed": True}},
    )
    return {"ok": True}


@api_router.post("/auth/logout")
async def auth_logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# ============== EMAIL / PASSWORD AUTH (iter16 — geo-restricted users) ==============
import bcrypt


def _hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


async def _create_session(user_id: str, response: Response, ttl_hours: int = 168):
    """Issue a session_token + set cookie. Default TTL = 7 days (168h).
    Pass ttl_hours=24 for a 'remember me 24h' short-lived session."""
    ttl_hours = max(1, min(int(ttl_hours), 168))  # clamp 1h..7d
    session_token = uuid.uuid4().hex + uuid.uuid4().hex  # 64 chars
    expires_at = now_utc() + timedelta(hours=ttl_hours)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": iso(expires_at),
        "created_at": iso(now_utc()),
    })
    response.set_cookie(
        key="session_token", value=session_token, httponly=True, secure=True,
        samesite="none", path="/", max_age=ttl_hours * 3600,
    )


class AuthRegisterPayload(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=200)
    name: str = Field(..., min_length=2, max_length=120)


class AuthLoginPayload(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=200)
    remember_hours: Optional[int] = None  # if set (e.g. 24), session = ttl_hours; else 7d default


async def _too_many_failed_attempts(identifier: str) -> bool:
    """Return True if user/IP is currently locked out (5 fails in 15 min)."""
    cutoff = (now_utc() - timedelta(minutes=15)).isoformat()
    n = await db.login_attempts.count_documents(
        {"identifier": identifier, "created_at": {"$gte": cutoff}, "success": False}
    )
    return n >= 5


async def _record_login_attempt(identifier: str, success: bool):
    await db.login_attempts.insert_one({
        "identifier": identifier,
        "success": success,
        "created_at": iso(now_utc()),
    })
    if success:
        # Clear failed attempts on success
        await db.login_attempts.delete_many(
            {"identifier": identifier, "success": False}
        )


@api_router.post("/auth/register")
async def auth_register(payload: AuthRegisterPayload, response: Response):
    email = payload.email.lower().strip()
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese email")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    role = "admin" if email in ADMIN_EMAILS else "normal"
    if await db.users.count_documents({}) == 0:
        role = "admin"
    verification_token = uuid.uuid4().hex + uuid.uuid4().hex
    user_doc = {
        "user_id": user_id,
        "email": email,
        "name": payload.name.strip(),
        "picture": "",
        "role": role,
        "auth_provider": "password",
        "password_hash": _hash_password(payload.password),
        "email_verified": False,
        "verification_token": verification_token,
        "verification_expires_at": iso(now_utc() + timedelta(hours=24)),
        "vip_balance_usd": 0.0,
        "onboarding_completed": False,
        "created_at": iso(now_utc()),
    }
    await db.users.insert_one(user_doc)
    # Send verification email (best effort)
    try:
        email_service.notify_email_verification(email, payload.name.strip(), verification_token)
    except Exception as e:
        logger.error(f"Verification email failed: {e}")
    return {
        "ok": True,
        "email": email,
        "message": "Cuenta creada. Revisa tu correo para verificar tu email antes de iniciar sesión.",
    }


@api_router.get("/auth/verify-email/{token}")
async def auth_verify_email(token: str, response: Response):
    user = await db.users.find_one({"verification_token": token}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=400, detail="Token inválido o ya usado")
    expires = user.get("verification_expires_at")
    if expires and expires < iso(now_utc()):
        raise HTTPException(status_code=400, detail="El enlace expiró. Solicita uno nuevo.")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"email_verified": True},
         "$unset": {"verification_token": "", "verification_expires_at": ""}},
    )
    await _create_session(user["user_id"], response)
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0, "password_hash": 0})
    return fresh


@api_router.post("/auth/login")
async def auth_login(payload: AuthLoginPayload, request: Request, response: Response):
    email = payload.email.lower().strip()
    identifier = email
    if await _too_many_failed_attempts(identifier):
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos fallidos. Espera 15 minutos.",
        )
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        await _record_login_attempt(identifier, False)
        raise HTTPException(
            status_code=404,
            detail={"code": "USER_NOT_FOUND",
                    "message": "No existe una cuenta con este email. Crea una cuenta para acceder a la plataforma."},
        )
    if not user.get("password_hash"):
        # Account exists but was created via Google OAuth (no password set)
        await _record_login_attempt(identifier, False)
        raise HTTPException(
            status_code=401,
            detail={"code": "USE_GOOGLE_LOGIN",
                    "message": "Esta cuenta fue creada con Google. Usa el botón \"Continuar con Google\"."},
        )
    if not _verify_password(payload.password, user["password_hash"]):
        await _record_login_attempt(identifier, False)
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_PASSWORD",
                    "message": "Contraseña incorrecta. Si la olvidaste, usa \"¿Olvidaste tu contraseña?\"."},
        )
    # Iter17: block password login until email is verified
    if user.get("auth_provider") == "password" and not user.get("email_verified", False):
        raise HTTPException(
            status_code=403,
            detail={"code": "EMAIL_NOT_VERIFIED",
                    "message": "Verifica tu correo antes de iniciar sesión. Revisa tu bandeja."},
        )
    await _record_login_attempt(identifier, True)
    ttl = payload.remember_hours if payload.remember_hours else 168
    await _create_session(user["user_id"], response, ttl_hours=ttl)
    user.pop("password_hash", None)
    user.pop("verification_token", None)
    return user


class ForgotPasswordPayload(BaseModel):
    email: EmailStr


@api_router.post("/auth/forgot-password")
async def auth_forgot_password(payload: ForgotPasswordPayload):
    """Send reset link if account exists. Always returns 200 to avoid email enumeration."""
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if user and user.get("password_hash"):
        token = uuid.uuid4().hex + uuid.uuid4().hex
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {
                "password_reset_token": token,
                "password_reset_expires_at": iso(now_utc() + timedelta(hours=2)),
            }},
        )
        try:
            email_service.notify_password_reset(email, user.get("name", ""), token)
        except Exception as e:
            logger.error(f"Password reset email failed: {e}")
    return {"ok": True, "message": "Si la cuenta existe, recibirás un correo con el enlace."}


class ResetPasswordPayload(BaseModel):
    token: str
    password: str = Field(..., min_length=8, max_length=200)


@api_router.post("/auth/reset-password")
async def auth_reset_password(payload: ResetPasswordPayload, response: Response):
    user = await db.users.find_one({"password_reset_token": payload.token}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=400, detail="Token inválido")
    expires = user.get("password_reset_expires_at")
    if expires and expires < iso(now_utc()):
        raise HTTPException(status_code=400, detail="El enlace expiró. Solicita uno nuevo.")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "password_hash": _hash_password(payload.password),
            "email_verified": True,  # password reset via email proves ownership
        },
         "$unset": {"password_reset_token": "", "password_reset_expires_at": ""}},
    )
    await _create_session(user["user_id"], response)
    return {"ok": True, "message": "Contraseña actualizada"}


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
    actor = await require_staff(request)
    _enforce_employee_currency_scope(actor, payload.from_code, payload.to_code)
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
    actor = await require_staff(request)
    await _enforce_totp_step_up(actor, payload.totp_code, action_label="actualizar tasa")
    _enforce_employee_currency_scope(actor, payload.from_code, payload.to_code)
    old = await db.rates.find_one({"id": rate_id}, {"_id": 0})
    if old:
        _enforce_employee_currency_scope(actor, old["from_code"], old["to_code"])
    rate_data = payload.model_dump(exclude={"totp_code"})
    await db.rates.update_one(
        {"id": rate_id},
        {"$set": {**rate_data, "updated_at": iso(now_utc())}}
    )
    fresh = await db.rates.find_one({"id": rate_id}, {"_id": 0})
    # If real_rate changed, scan pending orders for negative margin
    try:
        old_rr = old.get("real_rate") if old else None
        if fresh and fresh.get("real_rate") is not None and fresh.get("real_rate") != old_rr:
            pending = await db.orders.find(
                {"from_code": fresh["from_code"], "to_code": fresh["to_code"], "status": "pending"},
                {"_id": 0},
            ).to_list(500)
            losers = []
            total_loss = 0.0
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
    except Exception as e:
        logger.error(f"Rate update margin scan failed: {e}")
    await log_action(db, actor, "rate.update", "rate", rate_id,
                     summary=f"Tasa {fresh['from_code']}→{fresh['to_code']} actualizada",
                     details={"old": old, "new": fresh})
    return fresh

@api_router.delete("/admin/rates/{rate_id}")
async def delete_rate(rate_id: str, request: Request):
    actor = await require_staff(request)
    existing = await db.rates.find_one({"id": rate_id}, {"_id": 0})
    if existing:
        _enforce_employee_currency_scope(actor, existing["from_code"], existing["to_code"])
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
    # iter19: commission removed. Differentiation by status now lives entirely in rate_normal vs rate_vip
    # (admins set both rates in /admin/rates). New orders carry commission_percent = 0.0; existing
    # historical orders keep their original 5% value untouched.
    commission = 0.0
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
    # Defensive mode: if profit pct below configured threshold, mark for double approval
    try:
        rate_doc = await db.rates.find_one(
            {"from_code": order.from_code, "to_code": order.to_code}, {"_id": 0}
        )
        settings_doc = await db.settings.find_one({"id": "global"}, {"_id": 0})
        defensive_pct = settings_doc.get("defensive_margin_pct") if settings_doc else None
        if defensive_pct is not None and rate_doc and rate_doc.get("real_rate"):
            p = await _compute_order_profit(order.model_dump(), rate_doc)
            if p and p["pct"] < float(defensive_pct):
                await db.orders.update_one(
                    {"id": order.id},
                    {"$set": {"status": "requires_double_approval"}}
                )
    except Exception as e:
        logger.error(f"Defensive mode check failed: {e}")
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
    # Negative margin alert
    try:
        await _check_negative_margin_alert(order.model_dump())
    except Exception as e:
        logger.error(f"Negative margin check failed: {e}")
    return await db.orders.find_one({"id": order.id}, {"_id": 0}) or order.model_dump()


async def _check_negative_margin_alert(order: dict):
    """Notify admins if an order would generate a loss given the current real_rate."""
    rate_doc = await db.rates.find_one(
        {"from_code": order["from_code"], "to_code": order["to_code"]}, {"_id": 0}
    )
    if not rate_doc or rate_doc.get("real_rate") is None:
        return
    profit = await _compute_order_profit(order, rate_doc)
    if profit and profit["amount"] < 0:
        loss_amount = abs(profit["amount"])
        await notify_all_admins(
            db,
            title="🚨 Orden con margen negativo",
            body=(
                f"Orden #{order['id'][:8]} de {order.get('user_name', '')} "
                f"({order['from_code']}→{order['to_code']}) generaría pérdida estimada "
                f"de {loss_amount:.2f} {order['to_code']} ({profit['pct']:.2f}%). Revisa antes de aprobar."
            ),
            url_path="/admin/orders",
        )

@api_router.get("/orders/mine")
async def my_orders(request: Request):
    user = await require_user(request)
    docs = await db.orders.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs

@api_router.get("/admin/orders")
async def all_orders(request: Request, status: Optional[str] = None,
                     user_q: Optional[str] = None, currency: Optional[str] = None,
                     limit: int = 1000, offset: int = 0):
    actor = await require_staff(request)
    q = {}
    if status:
        q["status"] = status
    if currency:
        currency = currency.upper()
        q["$or"] = [{"from_code": currency}, {"to_code": currency}]
    if user_q:
        rx = {"$regex": user_q, "$options": "i"}
        # Combine with currency filter via $and if both present
        user_clause = {"$or": [{"user_name": rx}, {"user_email": rx}]}
        if "$or" in q:
            q["$and"] = [{"$or": q.pop("$or")}, user_clause]
        else:
            q["$or"] = user_clause["$or"]
    # iter14: employee currency scope — restrict listing to allowed currencies
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            scope_clause = {"$or": [{"from_code": {"$in": allowed}}, {"to_code": {"$in": allowed}}]}
            if "$and" in q:
                q["$and"].append(scope_clause)
            elif "$or" in q:
                q["$and"] = [{"$or": q.pop("$or")}, scope_clause]
            else:
                q["$or"] = scope_clause["$or"]
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    total = await db.orders.count_documents(q)
    docs = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).skip(offset).to_list(limit)
    return JSONResponse(
        content=docs,
        headers={
            "X-Total-Count": str(total),
            "X-Offset": str(offset),
            "X-Limit": str(limit),
            "Access-Control-Expose-Headers": "X-Total-Count, X-Offset, X-Limit",
        },
    )


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
    actor = await require_staff(request)
    new_status = payload.get("status")
    note = payload.get("admin_note", "")
    if new_status not in ("approved", "rejected", "completed", "pending", "requires_double_approval"):
        raise HTTPException(status_code=400, detail="status inválido")
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    # iter14: once an order is confirmed (approved), only an admin can change its status
    if (order.get("status") == "approved"
            and new_status != "approved"
            and actor.get("role") != "admin"):
        raise HTTPException(
            status_code=403,
            detail="Esta transferencia ya fue confirmada. Solo un admin puede cambiar su estado.",
        )
    # iter14: employee currency scope — only act on orders touching authorized currencies
    _enforce_employee_currency_scope(actor, order["from_code"], order["to_code"])
    # Defensive: only admin can approve orders that require double-approval
    if (order.get("status") == "requires_double_approval"
            and new_status == "approved"
            and actor.get("role") != "admin"):
        raise HTTPException(status_code=403, detail="Solo un admin puede aprobar órdenes con margen bajo")
    # 2FA step-up: approving a requires_double_approval order is high-risk
    if order.get("status") == "requires_double_approval" and new_status == "approved":
        await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                    action_label="aprobar orden con margen bajo")

    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"status": new_status, "admin_note": note, "updated_at": iso(now_utc())}}
    )

    is_first_approval = new_status == "approved" and order["status"] != "approved"
    if (is_first_approval
            and order["delivery_method"] == "accumulate"):
        # iter14: normal users may also accumulate balance (no longer VIP-only)
        await _accumulate_vip_balance(order)
        if order["user_role"] in ("vip", "admin"):
            await _check_vip_threshold_alert(order)

    updated = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if new_status in ("approved", "rejected") and order["status"] != new_status:
        target_user = await db.users.find_one({"user_id": order["user_id"]}, {"_id": 0})
        if target_user:
            await _send_client_order_email(updated, new_status, target_user)
            await _send_client_order_push(updated, new_status)
    await log_action(db, actor, f"order.{new_status}", "order", order_id,
                     summary=f"Orden {order['from_code']}→{order['to_code']} {new_status}",
                     details={"prev": order["status"], "new": new_status, "note": note,
                              "amount_from": order["amount_from"], "amount_to": order["amount_to"]})
    return updated

# ============== PRODUCTS ==============

@api_router.get("/products")
async def list_products():
    docs = await db.products.find({"is_active": True}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs

def _check_employee_product_perms(actor: dict, *, editing_price: bool, editing_image: bool):
    """iter21 — admin bypasses. Employees need explicit toggles set in /admin/users."""
    if actor.get("role") == "admin":
        return
    if editing_price and not actor.get("can_edit_product_prices"):
        raise HTTPException(status_code=403, detail="No tienes permiso para modificar precios de productos")
    if editing_image and not actor.get("can_upload_product_images"):
        raise HTTPException(status_code=403, detail="No tienes permiso para subir imágenes de productos")


@api_router.post("/admin/products")
async def create_product(payload: ProductCreate, request: Request):
    actor = await require_staff(request)
    _check_employee_product_perms(
        actor,
        editing_price=(payload.price_usd is not None and payload.price_usd != 0) or (payload.cost_usd is not None and payload.cost_usd != 0),
        editing_image=bool((payload.image_url or "").strip()),
    )
    p = Product(**payload.model_dump())
    await db.products.insert_one(p.model_dump())
    return p.model_dump()

@api_router.put("/admin/products/{product_id}")
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

@api_router.delete("/admin/products/{product_id}")
async def delete_product(product_id: str, request: Request):
    actor = await require_staff(request)
    if actor.get("role") != "admin" and not actor.get("can_delete_products"):
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar productos")
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
    cost = float(product.get("cost_usd") or 0) * payload.quantity
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
        cost_usd=cost,
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
    # iter14: opens to all client roles (normal + vip + admin). Staff cannot withdraw to themselves.
    if user["role"] == "employee":
        raise HTTPException(status_code=403, detail="Empleados no pueden retirar")
    # 2FA mandatory: must be set up AND a valid code provided
    await _enforce_totp_step_up(user, payload.totp_code, action_label="retiro")
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
        beneficiary_name=payload.beneficiary_name,
    )
    await db.withdrawals.insert_one(w.model_dump())
    await _decrement_balance(user["user_id"], currency, payload.amount_usd)
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


# ============== 2FA / TOTP MANAGEMENT ==============

async def _enforce_totp_step_up(user: dict, code: Optional[str], action_label: str = "esta acción"):
    """Raise HTTPException if user has no 2FA enabled OR submitted code is invalid.
    Consumes a recovery code if `code` matches one. Otherwise verifies TOTP.
    """
    if not user.get("totp_enabled"):
        raise HTTPException(
            status_code=412,  # Precondition Required
            detail={
                "code": "TOTP_SETUP_REQUIRED",
                "message": f"Debes configurar la verificación en dos pasos (2FA) antes de realizar {action_label}.",
                "setup_url": "/dashboard/security",
            },
        )
    if not code:
        raise HTTPException(
            status_code=401,
            detail={"code": "TOTP_CODE_REQUIRED", "message": f"Se requiere código 2FA para {action_label}."},
        )
    submitted = code.strip()
    # Try recovery code first if it has hyphen or len 10/11
    if len(submitted) >= 10 and any(c.isalpha() for c in submitted):
        ok, remaining = totp_service.consume_recovery_code(
            user.get("totp_recovery_codes", []) or [], submitted
        )
        if ok:
            await db.users.update_one(
                {"user_id": user["user_id"]},
                {"$set": {"totp_recovery_codes": remaining}},
            )
            return
        raise HTTPException(
            status_code=401,
            detail={"code": "TOTP_INVALID", "message": "Código de recuperación inválido."},
        )
    # Otherwise treat as TOTP
    if not user.get("totp_secret_encrypted"):
        raise HTTPException(status_code=409, detail="Estado 2FA inconsistente. Re-configura tu autenticador.")
    try:
        secret = totp_service.decrypt_secret(user["totp_secret_encrypted"])
    except Exception:
        raise HTTPException(status_code=500, detail="No se pudo verificar el código 2FA.")
    if not totp_service.verify_totp(secret, submitted):
        raise HTTPException(
            status_code=401,
            detail={"code": "TOTP_INVALID", "message": "Código 2FA inválido o expirado."},
        )


@api_router.get("/me/2fa/status")
async def totp_status(request: Request):
    user = await require_user(request)
    return {
        "enabled": bool(user.get("totp_enabled")),
        "setup_at": user.get("totp_setup_at"),
        "recovery_codes_remaining": len(user.get("totp_recovery_codes") or []),
    }


@api_router.post("/me/2fa/setup")
async def totp_setup(request: Request):
    """Generates a pending TOTP secret + QR. NOT enabled until /verify-setup confirms a valid code."""
    user = await require_user(request)
    if user.get("totp_enabled"):
        raise HTTPException(status_code=409, detail="2FA ya está habilitado. Desactívalo primero para reconfigurar.")
    secret = totp_service.generate_secret()
    encrypted = totp_service.encrypt_secret(secret)
    # Store as pending (separate from active secret); cleared once enabled
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"totp_pending_secret_encrypted": encrypted}},
    )
    uri = totp_service.provisioning_uri(secret, user["email"])
    return {
        "qr_data_url": totp_service.qr_data_url(uri),
        "secret": secret,  # shown so user can paste into authenticator if QR fails
        "provisioning_uri": uri,
        "issuer": totp_service.ISSUER,
    }


@api_router.post("/me/2fa/verify-setup")
async def totp_verify_setup(request: Request, payload: dict):
    """Verify the first TOTP code; on success, enable 2FA and return one-time recovery codes."""
    user = await require_user(request)
    code = (payload.get("code") or "").strip()
    pending = user.get("totp_pending_secret_encrypted")
    if not pending:
        raise HTTPException(status_code=400, detail="No hay configuración pendiente. Inicia el setup primero.")
    try:
        secret = totp_service.decrypt_secret(pending)
    except Exception:
        raise HTTPException(status_code=500, detail="No se pudo leer el secreto pendiente.")
    if not totp_service.verify_totp(secret, code):
        raise HTTPException(status_code=401, detail="Código inválido. Vuelve a intentarlo.")
    plain_codes, hashed_codes = totp_service.generate_recovery_codes(10)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {
            "$set": {
                "totp_secret_encrypted": pending,
                "totp_enabled": True,
                "totp_setup_at": iso(now_utc()),
                "totp_recovery_codes": hashed_codes,
            },
            "$unset": {"totp_pending_secret_encrypted": ""},
        },
    )
    return {
        "enabled": True,
        "recovery_codes": plain_codes,
        "message": "2FA activado. Guarda los códigos de recuperación en un lugar seguro: solo se muestran una vez.",
    }


@api_router.post("/me/2fa/disable")
async def totp_disable(request: Request, payload: dict):
    user = await require_user(request)
    if not user.get("totp_enabled"):
        return {"enabled": False, "already_disabled": True}
    code = (payload.get("code") or "").strip()
    await _enforce_totp_step_up(user, code, action_label="desactivar 2FA")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {
            "$set": {"totp_enabled": False},
            "$unset": {
                "totp_secret_encrypted": "",
                "totp_pending_secret_encrypted": "",
                "totp_recovery_codes": "",
                "totp_setup_at": "",
            },
        },
    )
    return {"enabled": False}


@api_router.post("/me/2fa/regenerate-recovery-codes")
async def totp_regenerate_recovery(request: Request, payload: dict):
    """Issue a fresh set of 10 recovery codes (invalidates the old ones). Requires current TOTP."""
    user = await require_user(request)
    code = (payload.get("code") or "").strip()
    await _enforce_totp_step_up(user, code, action_label="regenerar códigos de recuperación")
    plain_codes, hashed_codes = totp_service.generate_recovery_codes(10)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"totp_recovery_codes": hashed_codes}},
    )
    return {"recovery_codes": plain_codes}

@api_router.get("/vip/withdrawals/mine")
async def my_withdrawals(request: Request):
    user = await require_user(request)
    docs = await db.withdrawals.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs

@api_router.get("/admin/withdrawals")
async def all_withdrawals(request: Request,
                          status: Optional[str] = None,
                          user_q: Optional[str] = None,
                          currency: Optional[str] = None):
    actor = await require_staff(request)
    q = {}
    if status:
        q["status"] = status
    if currency:
        q["currency"] = currency.upper()
    if user_q:
        rx = {"$regex": user_q, "$options": "i"}
        q["$or"] = [{"user_name": rx}, {"user_email": rx}]
    # iter14: employee scope — narrow currency to allowed list (intersect with explicit filter)
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            if "currency" in q:
                # If admin filtered by currency outside their scope, return empty
                if q["currency"] not in allowed:
                    return []
            else:
                q["currency"] = {"$in": allowed}
    docs = await db.withdrawals.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs

@api_router.put("/admin/withdrawals/{wid}/status")
async def update_withdrawal(wid: str, payload: dict, request: Request):
    actor = await require_staff(request)
    new_status = payload.get("status")
    note = payload.get("admin_note", "")
    if new_status not in ("approved", "paid", "rejected", "pending"):
        raise HTTPException(status_code=400, detail="status inválido")
    # 2FA step-up: any change to a withdrawal status moves real money / refunds balance
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                action_label="gestionar retiro")
    w = await db.withdrawals.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(status_code=404, detail="No encontrado")
    # iter14: once a withdrawal is paid (entregado), only an admin can re-open it
    if w["status"] == "paid" and new_status != "paid" and actor.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Este retiro ya fue entregado. Solo un admin puede modificarlo.",
        )
    # iter14: employees only act on currencies they're authorized for
    _enforce_employee_currency_scope(actor, w.get("currency"))
    if new_status == "rejected" and w["status"] != "rejected":
        refund_currency = w.get("currency", "USD")
        await db.users.update_one(
            {"user_id": w["user_id"]},
            {"$inc": {f"vip_balances.{refund_currency}": w["amount_usd"]}}
        )
    update_doc = {"status": new_status, "admin_note": note}
    # iter14: capture fulfillment proof when marking as paid/entregado
    proof = payload.get("payout_proof_image")
    if proof:
        update_doc["payout_proof_image"] = proof
    tx_hash = payload.get("payout_tx_hash")
    if tx_hash:
        update_doc["payout_tx_hash"] = tx_hash
    # Require proof when marking as paid (entregado) for transfer/crypto methods
    if new_status == "paid" and w["status"] != "paid":
        method = w.get("method")
        existing_proof = w.get("payout_proof_image") or update_doc.get("payout_proof_image")
        if method == "transfer" and not existing_proof:
            raise HTTPException(
                status_code=400,
                detail="Adjunta la captura de la transferencia realizada al cliente antes de marcar como entregado",
            )
        if method == "crypto":
            existing_hash = w.get("payout_tx_hash") or update_doc.get("payout_tx_hash")
            if not existing_hash and not existing_proof:
                raise HTTPException(
                    status_code=400,
                    detail="Adjunta hash de transacción y/o captura del envío antes de marcar como entregado",
                )
    await db.withdrawals.update_one({"id": wid}, {"$set": update_doc})
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
    if user["role"] == "employee":
        raise HTTPException(status_code=403, detail="Empleados no tienen saldo de cliente")
    # iter14: normal users may also accumulate balance — only employees blocked.
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
    defensive_margin_pct: Optional[float] = Field(default=None)  # null = disabled. Otherwise orders with profit_pct < this require admin double-approval
    totp_code: Optional[str] = Field(default=None, max_length=11, description="Código 2FA requerido")


@api_router.get("/admin/settings")
async def get_admin_settings(request: Request):
    await require_staff(request)
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0})
    if not doc:
        return {
            "vip_threshold_usdt": float(os.environ.get("VIP_ALERT_THRESHOLD_USDT", 5000)),
            "defensive_margin_pct": None,
        }
    return {
        "vip_threshold_usdt": float(doc.get("vip_threshold_usdt", 5000)),
        "defensive_margin_pct": doc.get("defensive_margin_pct"),
    }


@api_router.put("/admin/settings")
async def update_admin_settings(payload: AdminSettings, request: Request):
    actor = await require_admin(request)
    await _enforce_totp_step_up(actor, payload.totp_code, action_label="actualizar configuración")
    data = payload.model_dump(exclude={"totp_code"})
    data["id"] = "global"
    await db.settings.update_one({"id": "global"}, {"$set": data}, upsert=True)
    await log_action(db, actor, "settings.update", "settings", "global",
                     summary=f"Settings actualizados", details=data)
    return {"ok": True, **data}


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


# ============== AUDIT LOG (ADMIN ONLY) ==============

def _normalize_audit_date(value: Optional[str], end_of_day: bool = False) -> Optional[str]:
    """Accept YYYY-MM-DD or full ISO; return ISO UTC string suitable for string compare."""
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    # Pure date → expand
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        try:
            datetime.fromisoformat(v)  # validate
        except Exception:
            raise HTTPException(status_code=400, detail=f"Fecha inválida: {value} (usa YYYY-MM-DD)")
        return f"{v}T23:59:59.999999+00:00" if end_of_day else f"{v}T00:00:00+00:00"
    # Otherwise assume ISO
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(status_code=400, detail=f"Fecha inválida: {value}")
    return v


def _build_audit_query(action: Optional[str], actor_id: Optional[str],
                       since: Optional[str], until: Optional[str]) -> dict:
    q = {}
    if action:
        q["action"] = action
    if actor_id:
        q["actor_id"] = actor_id
    s = _normalize_audit_date(since, end_of_day=False)
    u = _normalize_audit_date(until, end_of_day=True)
    if s or u:
        rng = {}
        if s:
            rng["$gte"] = s
        if u:
            rng["$lte"] = u
        q["created_at"] = rng
    return q


@api_router.get("/admin/audit")
async def list_audit_log(request: Request, limit: int = 100, offset: int = 0,
                         action: Optional[str] = None, actor_id: Optional[str] = None,
                         since: Optional[str] = None, until: Optional[str] = None):
    await require_admin(request)
    q = _build_audit_query(action, actor_id, since, until)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    total = await db.audit_log.count_documents(q)
    docs = await db.audit_log.find(q, {"_id": 0}).sort("created_at", -1).skip(offset).to_list(limit)
    return JSONResponse(
        content=docs,
        headers={
            "X-Total-Count": str(total),
            "X-Offset": str(offset),
            "X-Limit": str(limit),
            "Access-Control-Expose-Headers": "X-Total-Count, X-Offset, X-Limit",
        },
    )


async def _fetch_audit_entries(action: Optional[str], actor_id: Optional[str],
                               since: Optional[str], until: Optional[str],
                               limit: int) -> list:
    q = _build_audit_query(action, actor_id, since, until)
    limit = max(1, min(limit, 5000))
    return await db.audit_log.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)


@api_router.get("/admin/audit/export.csv")
async def export_audit_csv(request: Request, action: Optional[str] = None,
                           actor_id: Optional[str] = None,
                           since: Optional[str] = None, until: Optional[str] = None,
                           limit: int = 5000):
    await require_admin(request)
    entries = await _fetch_audit_entries(action, actor_id, since, until, limit)
    buf = BytesIO()
    # csv writer needs text mode; we'll write to a StringIO-like via bytes encode at the end
    import io
    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    writer.writerow(["created_at", "actor_id", "actor_email", "actor_name", "actor_role",
                     "action", "entity_type", "entity_id", "summary", "details"])
    for e in entries:
        writer.writerow([
            e.get("created_at", ""),
            e.get("actor_id", ""),
            e.get("actor_email", ""),
            e.get("actor_name", ""),
            e.get("actor_role", ""),
            e.get("action", ""),
            e.get("entity_type", ""),
            e.get("entity_id", ""),
            e.get("summary", ""),
            _json.dumps(e.get("details") or {}, ensure_ascii=False),
        ])
    buf.write(text_buf.getvalue().encode("utf-8-sig"))  # BOM for Excel compatibility
    buf.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"audit_log_{ts}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.get("/admin/audit/export.pdf")
async def export_audit_pdf(request: Request, action: Optional[str] = None,
                           actor_id: Optional[str] = None,
                           since: Optional[str] = None, until: Optional[str] = None,
                           limit: int = 2000):
    await require_admin(request)
    entries = await _fetch_audit_entries(action, actor_id, since, until, limit)
    pdf_bytes = generate_audit_pdf(
        entries,
        {"action": action, "actor_id": actor_id, "since": since, "until": until},
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"audit_log_{ts}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============== TRANSACTIONS REGISTRY (ADMIN ONLY — accounting) ==============

def _date_range_query(since: Optional[str], until: Optional[str]) -> dict:
    """Build a created_at range filter using the same helper as audit log."""
    s = _normalize_audit_date(since, end_of_day=False)
    u = _normalize_audit_date(until, end_of_day=True)
    if not s and not u:
        return {}
    rng = {}
    if s:
        rng["$gte"] = s
    if u:
        rng["$lte"] = u
    return {"created_at": rng}


async def _build_transactions(direction: Optional[str], currency: Optional[str],
                              holder: Optional[str], since: Optional[str],
                              until: Optional[str],
                              min_amount: Optional[float] = None,
                              max_amount: Optional[float] = None,
                              user_id: Optional[str] = None) -> list:
    """Unified transaction list from approved/completed orders + approved/paid withdrawals.

    Each entry: {direction: 'in'|'out', currency, amount, holder_name, client_name,
                 method, status, ref_id, created_at}
    Only records with a non-empty holder/sender field are included (we omit pre-feature data).
    If user_id is provided, restricts to transactions owned by that user.
    """
    items: list = []
    date_q = _date_range_query(since, until)

    # ENTRADAS (orders): approved/completed only, sender_name required
    if direction in (None, "all", "in"):
        order_q: dict = {
            "status": {"$in": ["approved", "completed"]},
            "sender_name": {"$nin": [None, ""]},
            **date_q,
        }
        if user_id:
            order_q["user_id"] = user_id
        if currency:
            order_q["from_code"] = currency
        if holder:
            order_q["sender_name"] = {"$regex": holder, "$options": "i"}
        orders = await db.orders.find(order_q, {"_id": 0}).to_list(5000)
        for o in orders:
            items.append({
                "direction": "in",
                "currency": o["from_code"],
                "amount": float(o.get("amount_from", 0.0)),
                "holder_name": o.get("sender_name", ""),
                "client_name": o.get("user_name", ""),
                "client_email": o.get("user_email", ""),
                "method": o.get("delivery_method", ""),
                "status": o.get("status", ""),
                "ref_id": o.get("id", ""),
                "ref_type": "order",
                "created_at": o.get("created_at", ""),
                "proof_image": o.get("proof_image", ""),
                "delivery_details": o.get("delivery_details", ""),
                "admin_note": o.get("admin_note", ""),
            })

    # SALIDAS (withdrawals): approved/paid only, beneficiary_name required
    if direction in (None, "all", "out"):
        with_q: dict = {
            "status": {"$in": ["approved", "paid"]},
            "beneficiary_name": {"$nin": [None, ""]},
            **date_q,
        }
        if user_id:
            with_q["user_id"] = user_id
        if currency:
            with_q["currency"] = currency
        if holder:
            with_q["beneficiary_name"] = {"$regex": holder, "$options": "i"}
        withdrawals = await db.withdrawals.find(with_q, {"_id": 0}).to_list(5000)
        for w in withdrawals:
            items.append({
                "direction": "out",
                "currency": w.get("currency", "USD"),
                "amount": float(w.get("amount_usd", 0.0)),
                "holder_name": w.get("beneficiary_name", ""),
                "client_name": w.get("user_name", ""),
                "client_email": w.get("user_email", ""),
                "method": w.get("method", ""),
                "status": w.get("status", ""),
                "ref_id": w.get("id", ""),
                "ref_type": "withdrawal",
                "created_at": w.get("created_at", ""),
                "proof_image": "",
                "delivery_details": w.get("details", ""),
                "admin_note": w.get("admin_note", ""),
            })

    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    # Amount range filter (applied after building to support both directions consistently)
    if min_amount is not None:
        items = [it for it in items if it["amount"] >= min_amount]
    if max_amount is not None:
        items = [it for it in items if it["amount"] <= max_amount]
    return items


def _compute_transaction_totals(items: list) -> dict:
    by_currency: dict = {}
    for it in items:
        cur = it["currency"]
        slot = by_currency.setdefault(cur, {"in": 0.0, "out": 0.0, "count": 0})
        slot[it["direction"]] += it["amount"]
        slot["count"] += 1
    # Round
    for v in by_currency.values():
        v["in"] = round(v["in"], 4)
        v["out"] = round(v["out"], 4)
    return {
        "by_currency": by_currency,
        "total_count": len(items),
    }


@api_router.get("/admin/transactions")
async def list_transactions(request: Request,
                            direction: Optional[str] = None,
                            currency: Optional[str] = None,
                            holder: Optional[str] = None,
                            since: Optional[str] = None,
                            until: Optional[str] = None,
                            min_amount: Optional[float] = None,
                            max_amount: Optional[float] = None,
                            limit: int = 100, offset: int = 0):
    await require_staff(request)
    if direction and direction not in ("in", "out", "all"):
        raise HTTPException(status_code=400, detail="direction debe ser 'in', 'out' o 'all'")
    if min_amount is not None and min_amount < 0:
        raise HTTPException(status_code=400, detail="min_amount debe ser >= 0")
    if max_amount is not None and max_amount < 0:
        raise HTTPException(status_code=400, detail="max_amount debe ser >= 0")
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise HTTPException(status_code=400, detail="min_amount no puede ser mayor que max_amount")
    items = await _build_transactions(direction, currency, holder, since, until, min_amount, max_amount)
    totals = _compute_transaction_totals(items)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    window = items[offset:offset + limit]
    return JSONResponse(
        content={"items": window, "totals": totals},
        headers={
            "X-Total-Count": str(len(items)),
            "X-Offset": str(offset),
            "X-Limit": str(limit),
            "Access-Control-Expose-Headers": "X-Total-Count, X-Offset, X-Limit",
        },
    )


@api_router.get("/admin/transactions/export.csv")
async def export_transactions_csv(request: Request,
                                  direction: Optional[str] = None,
                                  currency: Optional[str] = None,
                                  holder: Optional[str] = None,
                                  since: Optional[str] = None,
                                  until: Optional[str] = None,
                                  min_amount: Optional[float] = None,
                                  max_amount: Optional[float] = None):
    await require_staff(request)
    items = await _build_transactions(direction, currency, holder, since, until, min_amount, max_amount)
    import io
    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    writer.writerow(["created_at", "direction", "currency", "amount",
                     "holder_name", "client_name", "client_email",
                     "method", "status", "ref_type", "ref_id"])
    for it in items:
        writer.writerow([
            it.get("created_at", ""),
            it.get("direction", ""),
            it.get("currency", ""),
            f"{it.get('amount', 0):.4f}",
            it.get("holder_name", ""),
            it.get("client_name", ""),
            it.get("client_email", ""),
            it.get("method", ""),
            it.get("status", ""),
            it.get("ref_type", ""),
            it.get("ref_id", ""),
        ])
    buf = BytesIO()
    buf.write(text_buf.getvalue().encode("utf-8-sig"))  # BOM for Excel
    buf.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"transacciones_{ts}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.get("/admin/transactions/export.pdf")
async def export_transactions_pdf(request: Request,
                                  direction: Optional[str] = None,
                                  currency: Optional[str] = None,
                                  holder: Optional[str] = None,
                                  since: Optional[str] = None,
                                  until: Optional[str] = None,
                                  min_amount: Optional[float] = None,
                                  max_amount: Optional[float] = None):
    await require_staff(request)
    items = await _build_transactions(direction, currency, holder, since, until, min_amount, max_amount)
    totals = _compute_transaction_totals(items)
    pdf_bytes = generate_transactions_pdf(
        items,
        {"direction": direction, "currency": currency, "holder": holder,
         "since": since, "until": until,
         "min_amount": min_amount, "max_amount": max_amount},
        totals,
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"transacciones_{ts}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============== MY TRANSACTIONS (any authenticated user — own data only) ==============

@api_router.get("/me/transactions")
async def list_my_transactions(request: Request,
                               direction: Optional[str] = None,
                               currency: Optional[str] = None,
                               since: Optional[str] = None,
                               until: Optional[str] = None,
                               min_amount: Optional[float] = None,
                               max_amount: Optional[float] = None,
                               limit: int = 100, offset: int = 0):
    user = await require_user(request)
    if direction and direction not in ("in", "out", "all"):
        raise HTTPException(status_code=400, detail="direction debe ser 'in', 'out' o 'all'")
    if min_amount is not None and min_amount < 0:
        raise HTTPException(status_code=400, detail="min_amount debe ser >= 0")
    if max_amount is not None and max_amount < 0:
        raise HTTPException(status_code=400, detail="max_amount debe ser >= 0")
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise HTTPException(status_code=400, detail="min_amount no puede ser mayor que max_amount")
    items = await _build_transactions(direction, currency, None, since, until,
                                       min_amount, max_amount, user_id=user["user_id"])
    totals = _compute_transaction_totals(items)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    window = items[offset:offset + limit]
    return JSONResponse(
        content={"items": window, "totals": totals},
        headers={
            "X-Total-Count": str(len(items)),
            "X-Offset": str(offset),
            "X-Limit": str(limit),
            "Access-Control-Expose-Headers": "X-Total-Count, X-Offset, X-Limit",
        },
    )


@api_router.get("/me/transactions/export.csv")
async def export_my_transactions_csv(request: Request,
                                     direction: Optional[str] = None,
                                     currency: Optional[str] = None,
                                     since: Optional[str] = None,
                                     until: Optional[str] = None,
                                     min_amount: Optional[float] = None,
                                     max_amount: Optional[float] = None):
    user = await require_user(request)
    items = await _build_transactions(direction, currency, None, since, until,
                                       min_amount, max_amount, user_id=user["user_id"])
    import io
    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    writer.writerow(["created_at", "direction", "currency", "amount",
                     "holder_name", "method", "status", "ref_type", "ref_id"])
    for it in items:
        writer.writerow([
            it.get("created_at", ""),
            it.get("direction", ""),
            it.get("currency", ""),
            f"{it.get('amount', 0):.4f}",
            it.get("holder_name", ""),
            it.get("method", ""),
            it.get("status", ""),
            it.get("ref_type", ""),
            it.get("ref_id", ""),
        ])
    buf = BytesIO()
    buf.write(text_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"mis_transacciones_{ts}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.get("/me/transactions/export.pdf")
async def export_my_transactions_pdf(request: Request,
                                     direction: Optional[str] = None,
                                     currency: Optional[str] = None,
                                     since: Optional[str] = None,
                                     until: Optional[str] = None,
                                     min_amount: Optional[float] = None,
                                     max_amount: Optional[float] = None):
    user = await require_user(request)
    items = await _build_transactions(direction, currency, None, since, until,
                                       min_amount, max_amount, user_id=user["user_id"])
    totals = _compute_transaction_totals(items)
    pdf_bytes = generate_transactions_pdf(
        items,
        {"direction": direction, "currency": currency,
         "holder": f"Cliente: {user.get('name', '')}",
         "since": since, "until": until,
         "min_amount": min_amount, "max_amount": max_amount},
        totals,
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"mis_transacciones_{ts}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

    marketplace = await _compute_marketplace_revenue(days)

    return {
        "total_profit_usdt": round(total_profit_usdt + marketplace["total_profit_usd"], 4),
        "p2p_profit_usdt": round(total_profit_usdt, 4),
        "marketplace_profit_usdt": round(marketplace["total_profit_usd"], 4),
        "total_volume_usdt": round(total_volume_usdt, 4),
        "profit_margin_pct": round((total_profit_usdt / total_volume_usdt * 100), 3) if total_volume_usdt > 0 else 0.0,
        "by_pair": pair_items,
        "by_role": by_role,
        "marketplace": marketplace,
        "missing_real_rate_pairs": sorted(missing_rate_pairs),
        "orders_total": len(orders),
    }


async def _compute_marketplace_revenue(days: Optional[int]) -> dict:
    """Profit from delivered redemptions: total_usd - cost_usd. USD ≈ USDT for simplicity."""
    q = {"status": "delivered"}
    if days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["created_at"] = {"$gte": cutoff}
    rows = await db.redemptions.find(q, {"_id": 0}).to_list(5000)
    total_revenue = 0.0
    total_cost = 0.0
    by_product: dict = {}
    for r in rows:
        rev = float(r.get("total_usd") or 0.0)
        cost = float(r.get("cost_usd") or 0.0)
        total_revenue += rev
        total_cost += cost
        key = r.get("product_name", "—")
        if key not in by_product:
            by_product[key] = {
                "product": key,
                "units": 0,
                "revenue_usd": 0.0,
                "cost_usd": 0.0,
                "profit_usd": 0.0,
                "redemptions": 0,
            }
        bp = by_product[key]
        bp["units"] += int(r.get("quantity") or 0)
        bp["revenue_usd"] += rev
        bp["cost_usd"] += cost
        bp["profit_usd"] += (rev - cost)
        bp["redemptions"] += 1
    items = []
    for v in by_product.values():
        v["revenue_usd"] = round(v["revenue_usd"], 2)
        v["cost_usd"] = round(v["cost_usd"], 2)
        v["profit_usd"] = round(v["profit_usd"], 2)
        v["margin_pct"] = round((v["profit_usd"] / v["revenue_usd"] * 100), 2) if v["revenue_usd"] > 0 else 0.0
        items.append(v)
    items.sort(key=lambda x: -x["profit_usd"])
    return {
        "total_revenue_usd": round(total_revenue, 2),
        "total_cost_usd": round(total_cost, 2),
        "total_profit_usd": round(total_revenue - total_cost, 2),
        "items": items,
        "deliveries": len(rows),
    }


# ============== REVENUE TIME SERIES (daily/monthly) ==============

async def _build_revenue_timeseries(granularity: str, days: Optional[int] = None,
                                      year: Optional[int] = None, month: Optional[int] = None):
    """Build per-day or per-month buckets for the admin revenue dashboard.

    Filters:
      - `days`: restrict to last N days (preferred for daily charts).
      - `year`/`month`: restrict to a specific calendar month (used for the monthly export).
    """
    order_q: dict = {"status": {"$in": ["approved", "completed"]}}
    redemption_q: dict = {"status": "delivered"}

    if year and month:
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
        order_q["updated_at"] = {"$gte": start.isoformat(), "$lt": end.isoformat()}
        redemption_q["created_at"] = {"$gte": start.isoformat(), "$lt": end.isoformat()}
    elif days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        order_q["updated_at"] = {"$gte": cutoff}
        redemption_q["created_at"] = {"$gte": cutoff}

    orders = await db.orders.find(order_q, {"_id": 0}).to_list(5000)
    redemptions = await db.redemptions.find(redemption_q, {"_id": 0}).to_list(5000)
    rates = await db.rates.find({}, {"_id": 0}).to_list(500)
    rate_by_pair = {(r["from_code"], r["to_code"]): r for r in rates}
    fx = await _build_rate_lookup()

    # Pre-compute USDT volume + USDT profit per order so bucket aggregator stays simple.
    profit_map: dict = {}
    for o in orders:
        o["_volume_usdt"] = _convert_to_usdt(o["amount_from"], o["from_code"], fx) or 0.0
        rate_doc = rate_by_pair.get((o["from_code"], o["to_code"]))
        prof = await _compute_order_profit(o, rate_doc)
        if prof is None:
            continue
        prof_usdt = _convert_to_usdt(prof["amount"], prof["currency"], fx) or 0.0
        profit_map[o["id"]] = prof_usdt

    return build_buckets(orders, redemptions, profit_map, granularity)


@api_router.get("/admin/revenue/timeseries")
async def admin_revenue_timeseries(request: Request, granularity: str = "day",
                                     days: Optional[int] = None):
    """Daily or monthly profit buckets. Used by the Ingresos page."""
    await require_admin(request)
    if granularity not in ("day", "month"):
        raise HTTPException(status_code=400, detail="granularity inválida (day|month)")
    rows = await _build_revenue_timeseries(granularity, days=days)
    return {"granularity": granularity, "rows": rows}


@api_router.get("/admin/revenue/monthly/export")
async def admin_revenue_monthly_export(request: Request, year: int, month: int,
                                          format: str = "csv"):
    """Export the daily breakdown of a calendar month as CSV or PDF."""
    await require_admin(request)
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="mes inválido")
    if format not in ("csv", "pdf"):
        raise HTTPException(status_code=400, detail="formato inválido (csv|pdf)")

    rows = await _build_revenue_timeseries("day", year=year, month=month)
    rows_asc = sorted(rows, key=lambda x: x["bucket"])
    period_label = f"{year}-{month:02d}"

    if format == "csv":
        payload = revenue_monthly_csv(rows_asc, period_label)
        headers = {"Content-Disposition": f'attachment; filename="ganancia-{period_label}.csv"'}
        return Response(content=payload, media_type="text/csv; charset=utf-8", headers=headers)

    totals = {
        "p2p": sum(r["p2p_profit_usdt"] for r in rows_asc),
        "marketplace": sum(r["marketplace_profit_usdt"] for r in rows_asc),
        "total": sum(r["total_profit_usdt"] for r in rows_asc),
        "volume": sum(r["volume_usdt"] for r in rows_asc),
        "orders": sum(r["orders"] for r in rows_asc),
    }
    payload = revenue_monthly_pdf(rows_asc, period_label, totals)
    headers = {"Content-Disposition": f'attachment; filename="ganancia-{period_label}.pdf"'}
    return Response(content=payload, media_type="application/pdf", headers=headers)


@api_router.post("/admin/revenue/monthly/send-now")
async def admin_revenue_send_now(payload: dict, request: Request):
    """Manually trigger the monthly revenue email for testing / on-demand sending.

    Body: {"year": YYYY, "month": MM, "totp_code": "123456"}.
    Sends the PDF to every admin via email_service.notify_monthly_revenue.
    """
    actor = await require_admin(request)
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                 action_label="enviar reporte mensual")
    year = int(payload.get("year") or 0)
    month = int(payload.get("month") or 0)
    if month < 1 or month > 12 or year < 2020:
        raise HTTPException(status_code=400, detail="año/mes inválido")
    rows = await _build_revenue_timeseries("day", year=year, month=month)
    rows_asc = sorted(rows, key=lambda x: x["bucket"])
    totals = {
        "p2p": sum(r["p2p_profit_usdt"] for r in rows_asc),
        "marketplace": sum(r["marketplace_profit_usdt"] for r in rows_asc),
        "total": sum(r["total_profit_usdt"] for r in rows_asc),
        "volume": sum(r["volume_usdt"] for r in rows_asc),
        "orders": sum(r["orders"] for r in rows_asc),
    }
    pdf_bytes = revenue_monthly_pdf(rows_asc, f"{year}-{month:02d}", totals)
    admins = await db.users.find({"role": "admin"},
                                  {"_id": 0, "email": 1}).to_list(200)
    sent = 0
    for a in admins:
        if a.get("email") and email_service.notify_monthly_revenue(
            a["email"], f"{year}-{month:02d}", totals, pdf_bytes
        ):
            sent += 1
    return {"ok": True, "sent": sent, "total_admins": len(admins),
            "period": f"{year}-{month:02d}"}


# ============== COMPANY FUNDS (Iter15) ==============

async def _compute_company_funds(scope: Optional[List[str]] = None) -> List[dict]:
    """Dynamic per-currency balance of the platform working capital.

    balance[c] = inflows_from_confirmed_orders[c]
                - outflows_to_clients_paid[c]
                - outflows_company_paid[c]
    `scope` (currency codes) optionally restricts the returned list.
    """
    inflow: dict = {}
    # Confirmed/completed orders → platform received `amount_from` of `from_code`
    async for o in db.orders.find(
        {"status": {"$in": ["approved", "completed"]}},
        {"_id": 0, "from_code": 1, "amount_from": 1},
    ):
        c = o.get("from_code")
        if c:
            inflow[c] = inflow.get(c, 0.0) + float(o.get("amount_from") or 0.0)

    out_clients: dict = {}
    async for w in db.withdrawals.find(
        {"status": "paid"}, {"_id": 0, "currency": 1, "amount_usd": 1}
    ):
        c = w.get("currency") or "USD"
        out_clients[c] = out_clients.get(c, 0.0) + float(w.get("amount_usd") or 0.0)

    out_company: dict = {}
    async for cw in db.company_withdrawals.find(
        {"status": "paid"}, {"_id": 0, "currency": 1, "amount": 1}
    ):
        c = cw.get("currency")
        if c:
            out_company[c] = out_company.get(c, 0.0) + float(cw.get("amount") or 0.0)

    codes = set(inflow) | set(out_clients) | set(out_company)
    rows = []
    for c in sorted(codes):
        if scope and c not in scope:
            continue
        rows.append({
            "currency": c,
            "inflow": round(inflow.get(c, 0.0), 4),
            "outflow_clients": round(out_clients.get(c, 0.0), 4),
            "outflow_company": round(out_company.get(c, 0.0), 4),
            "balance": round(inflow.get(c, 0.0) - out_clients.get(c, 0.0) - out_company.get(c, 0.0), 4),
        })
    return rows


@api_router.get("/admin/company-funds")
async def admin_company_funds(request: Request):
    actor = await require_staff(request)
    scope = None
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            scope = allowed
    return await _compute_company_funds(scope)


@api_router.post("/admin/company-withdrawals")
async def create_company_withdrawal(payload: CompanyWithdrawalCreate, request: Request):
    actor = await require_staff(request)
    currency = payload.currency.upper()
    _enforce_employee_currency_scope(actor, currency)
    await _enforce_totp_step_up(actor, payload.totp_code, action_label="retiro del fondo")
    # Reject if balance would go negative
    funds = await _compute_company_funds([currency])
    avail = next((f["balance"] for f in funds if f["currency"] == currency), 0.0)
    if payload.amount > avail:
        raise HTTPException(
            status_code=400,
            detail=f"Fondo insuficiente en {currency}: disponible {avail:.2f}",
        )
    cw = CompanyWithdrawal(
        amount=payload.amount,
        currency=currency,
        beneficiary=payload.beneficiary,
        authorized_by_id=actor["user_id"],
        authorized_by_name=actor.get("name", ""),
        authorized_by_email=actor.get("email", ""),
        concept=payload.concept,
        invoice_image=payload.invoice_image,
        note=payload.note,
    )
    await db.company_withdrawals.insert_one(cw.model_dump())
    await log_action(db, actor, "company_withdrawal.create", "company_withdrawal", cw.id,
                     summary=f"Retiro fondo {currency} {payload.amount} → {payload.beneficiary}",
                     details={"currency": currency, "amount": payload.amount,
                              "beneficiary": payload.beneficiary})
    return cw.model_dump()


@api_router.get("/admin/company-withdrawals")
async def list_company_withdrawals(request: Request,
                                     status: Optional[str] = None,
                                     currency: Optional[str] = None):
    actor = await require_staff(request)
    q = {}
    if status:
        q["status"] = status
    if currency:
        q["currency"] = currency.upper()
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            if "currency" in q and q["currency"] not in allowed:
                return []
            elif "currency" not in q:
                q["currency"] = {"$in": allowed}
    docs = await db.company_withdrawals.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@api_router.put("/admin/company-withdrawals/{cwid}/status")
async def update_company_withdrawal(cwid: str, payload: dict, request: Request):
    """Only admin can change status (approve/pay/reject). Staff with scope creates only."""
    actor = await require_admin(request)
    new_status = payload.get("status")
    if new_status not in ("approved", "paid", "rejected"):
        raise HTTPException(status_code=400, detail="status inválido")
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                 action_label="actualizar retiro de fondo")
    cw = await db.company_withdrawals.find_one({"id": cwid}, {"_id": 0})
    if not cw:
        raise HTTPException(status_code=404, detail="No encontrado")
    if cw["status"] == "paid" and new_status != "paid":
        raise HTTPException(status_code=403, detail="Ya fue pagado, no se puede revertir")
    update_doc = {"status": new_status}
    note = payload.get("note")
    if note is not None:
        update_doc["admin_note"] = note
    await db.company_withdrawals.update_one({"id": cwid}, {"$set": update_doc})
    await log_action(db, actor, "company_withdrawal.status", "company_withdrawal", cwid,
                     summary=f"Retiro fondo {cw['currency']} {cw['amount']} → {new_status}",
                     details={"from": cw["status"], "to": new_status})
    return await db.company_withdrawals.find_one({"id": cwid}, {"_id": 0})


# ============== STAFF QUEUE (Iter15) ==============

@api_router.get("/admin/queue")
async def staff_queue(request: Request):
    """Pending items in the actor's scope: orders + withdrawals.

    For admins → everything pending.
    For staff with allowed_currencies → only those touching their allowed list.
    """
    actor = await require_staff(request)
    order_q = {"status": {"$in": ["pending", "requires_double_approval"]}}
    wd_q = {"status": "pending"}
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            order_q["$or"] = [{"from_code": {"$in": allowed}}, {"to_code": {"$in": allowed}}]
            wd_q["currency"] = {"$in": allowed}
    orders = await db.orders.find(order_q, {"_id": 0}).sort("created_at", -1).to_list(500)
    withdrawals = await db.withdrawals.find(wd_q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"orders": orders, "withdrawals": withdrawals,
            "counts": {"orders": len(orders), "withdrawals": len(withdrawals)}}


# ============== USERS (ADMIN) ==============

@api_router.get("/admin/users")
async def list_users(request: Request, q: Optional[str] = None,
                     role: Optional[str] = None,
                     limit: int = 1000, offset: int = 0):
    await require_staff(request)
    mongo_q = {}
    if q:
        # case-insensitive search by name or email
        rx = {"$regex": q, "$options": "i"}
        mongo_q["$or"] = [{"name": rx}, {"email": rx}]
    if role and role in ("normal", "vip", "employee", "admin"):
        mongo_q["role"] = role
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    total = await db.users.count_documents(mongo_q)
    docs = await db.users.find(mongo_q, {"_id": 0}).sort("created_at", -1).skip(offset).to_list(limit)
    return JSONResponse(
        content=docs,
        headers={
            "X-Total-Count": str(total),
            "X-Offset": str(offset),
            "X-Limit": str(limit),
            "Access-Control-Expose-Headers": "X-Total-Count, X-Offset, X-Limit",
        },
    )

@api_router.put("/admin/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdate, request: Request):
    requester = await require_staff(request)
    await _enforce_totp_step_up(requester, payload.totp_code, action_label="actualizar usuario")
    update = {k: v for k, v in payload.model_dump(exclude={"totp_code"}).items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Nada para actualizar")
    # Employees can only assign 'normal' or 'vip' roles, not admin/employee
    if requester.get("role") == "employee" and "role" in update and update["role"] in ("admin", "employee"):
        raise HTTPException(status_code=403, detail="Solo un admin puede asignar este rol")
    old_user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    await db.users.update_one({"user_id": user_id}, {"$set": update})
    new_user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    await log_action(db, requester, "user.update", "user", user_id,
                     summary=f"Usuario {new_user.get('email', '')} actualizado",
                     details={"changes": update, "prev_role": old_user.get("role") if old_user else None})
    return new_user


@api_router.post("/admin/users/{user_id}/verify-email")
async def admin_verify_user_email(user_id: str, request: Request):
    """Manually mark a user's email as verified. Useful for support cases or while
    Resend domain is not yet verified. Requires staff role + 2FA step-up."""
    requester = await require_staff(request)
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    await _enforce_totp_step_up(requester, payload.get("totp_code"), action_label="verificar email manualmente")
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target.get("email_verified"):
        return {"ok": True, "already_verified": True, "user": target}
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"email_verified": True},
         "$unset": {"verification_token": "", "verification_expires_at": ""}},
    )
    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    await log_action(db, requester, "user.verify_email_manual", "user", user_id,
                     summary=f"Email verificado manualmente para {target.get('email', '')}",
                     details={"email": target.get("email")})
    return {"ok": True, "already_verified": False, "user": fresh}

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

@app.on_event("startup")
async def start_background_jobs():
    """Wire up APScheduler. Wrap build_timeseries to expose it to scheduler.py
    without importing server.py (which would be circular)."""
    from scheduler import start_scheduler

    async def _build_timeseries(granularity, year=None, month=None, days=None):
        return await _build_revenue_timeseries(granularity, days=days, year=year, month=month)

    start_scheduler(db, _build_timeseries)


@app.on_event("shutdown")
async def shutdown_db_client():
    from scheduler import stop_scheduler
    stop_scheduler()
    client.close()
