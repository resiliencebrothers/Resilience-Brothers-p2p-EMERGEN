"""Auth router — extracted from server.py during iter27 refactor.

Endpoints:
- POST /auth/session              (Emergent legacy OAuth bridge — kept for backwards compat)
- GET  /auth/me
- GET  /auth/google/login
- GET  /auth/google/callback
- POST /auth/logout
- POST /auth/register
- GET  /auth/verify-email/{token}
- POST /auth/resend-verification
- POST /auth/login
- POST /auth/forgot-password
- POST /auth/reset-password

`_assert_not_defensive` and `ADMIN_EMAILS` remain in server.py (system domain).
They are imported lazily inside the two endpoints that need them to avoid
circular imports while routes/auth.py loads.
"""
import os
import uuid
import json
import base64
import logging
from datetime import timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx
import requests
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, EmailStr

from db_client import db
from auth_utils import (
    now_utc, iso,
    _hash_password, _verify_password,
    _create_session, require_user,
    _too_many_failed_attempts, _record_login_attempt,
    normalize_phone, assert_not_blocked,
    _decode_jwt_payload,
)
import email_service


logger = logging.getLogger(__name__)
router = APIRouter()


GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

ADMIN_EMAILS = [e.strip().lower() for e in os.environ.get('ADMIN_EMAILS', '').split(',') if e.strip()]

# Rate-limit for resend verification email: 1 every 60s per user.
RESEND_COOLDOWN_SECONDS = 60


# ============================================================
# Models
# ============================================================

class AuthRegisterPayload(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=200)
    name: str = Field(..., min_length=2, max_length=120)
    phone: str = Field(..., min_length=8, max_length=20)  # iter23 — E.164: +<countrycode><number>


class AuthLoginPayload(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=200)
    remember_hours: Optional[int] = None  # if set (e.g. 24), session = ttl_hours; else 7d default


class AuthResendVerificationPayload(BaseModel):
    email: EmailStr


class ForgotPasswordPayload(BaseModel):
    email: EmailStr


class ResetPasswordPayload(BaseModel):
    token: str
    password: str = Field(..., min_length=8, max_length=200)


# ============================================================
# Legacy Emergent OAuth bridge — keeps old session cookies working
# ============================================================

@router.post("/auth/session")
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
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": data.get("name", existing["name"]), "picture": data.get("picture", existing.get("picture", ""))}}
        )
        user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        role = "admin" if email in ADMIN_EMAILS else "normal"
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
        key="session_token", value=session_token, httponly=True, secure=True,
        samesite="none", path="/", max_age=7 * 24 * 3600,
    )
    user_doc.pop("_id", None)
    return user_doc


@router.get("/auth/me")
async def auth_me(request: Request):
    user = await require_user(request)
    user.pop("_id", None)
    return user


# ============================================================
# Custom Google OAuth 2.0 (iter22) — replaces Emergent Google Auth
# REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
# ============================================================

@router.get("/auth/google/login")
async def google_login(request: Request, redirect: Optional[str] = None):
    """Build the Google OAuth URL and 302-redirect the browser to it."""
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not configured")
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


@router.get("/auth/google/callback")
async def google_callback(request: Request, code: Optional[str] = None,
                          state: Optional[str] = None, error: Optional[str] = None):
    """Exchange the code for tokens, lookup/create the user by email, issue a session cookie,
    and bounce the browser to the SPA's post-login page."""
    if error:
        return RedirectResponse(url=f"/?auth_error={error}", status_code=302)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    state_doc = await db.oauth_states.find_one_and_delete({"state": state})
    if not state_doc:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    async with httpx.AsyncClient(timeout=15) as cli:
        token_resp = await cli.post(
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
        await assert_not_blocked(email=email)
        # iter24 — block new account creation in defensive mode (existing users still log in)
        # Lazy import avoids circular dep with server.py
        from server import _assert_not_defensive
        await _assert_not_defensive("nuevos registros")
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
            "phone": None,
            "phone_verified": False,
            # iter28 — Google users still need phone verification before operating.
            # Admin/employee bypass via _assert_account_active.
            "account_status": "active" if role in ("admin", "employee") else "under_review",
            "created_at": iso(now_utc()),
        })

    # iter28 — blocklist re-check on every Google login.
    if existing:
        u = await db.users.find_one({"user_id": user_id}, {"_id": 0})
        if u and u.get("phone") and u.get("role") in ("normal", "vip"):
            blocked = await db.blocked_contacts.find_one({"phone": u["phone"]}, {"_id": 0})
            if blocked:
                await db.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"phone_verified": False, "account_status": "under_review"}},
                )

    response = RedirectResponse(url=state_doc.get("redirect", "/dashboard"), status_code=302)
    await _create_session(user_id, response, ttl_hours=168)
    return response


# ============================================================
# Logout
# ============================================================

@router.post("/auth/logout")
async def auth_logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# ============================================================
# Email/password auth (iter16+) — register, verify, resend, login, reset
# ============================================================

@router.post("/auth/register")
async def auth_register(payload: AuthRegisterPayload, response: Response):
    email = payload.email.lower().strip()
    phone = normalize_phone(payload.phone)
    # iter24 — block new registrations entirely when in defensive mode
    from server import _assert_not_defensive
    await _assert_not_defensive("nuevos registros")
    # iter23 — block scammers by email or phone
    await assert_not_blocked(email=email, phone=phone)
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese email")
    # iter23 — phone uniqueness so the same number can't open multiple accounts
    if await db.users.find_one({"phone": phone}, {"_id": 0}):
        raise HTTPException(
            status_code=409,
            detail={"code": "PHONE_IN_USE",
                    "message": "Este número de teléfono ya está asociado a otra cuenta."},
        )
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
        "phone": phone,
        "phone_verified": False,
        # iter28 — new accounts start under_review; staff must verify phone first.
        # Admin/employee role bypasses the check inside _assert_account_active.
        "account_status": "active" if role in ("admin", "employee") else "under_review",
        "created_at": iso(now_utc()),
    }
    await db.users.insert_one(user_doc)
    try:
        email_service.notify_email_verification(email, payload.name.strip(), verification_token)
    except Exception as e:
        logger.error(f"Verification email failed: {e}")
    return {
        "ok": True,
        "email": email,
        "message": "Cuenta creada. Revisa tu correo para verificar tu email antes de iniciar sesión.",
    }


@router.get("/auth/verify-email/{token}")
async def auth_verify_email(token: str, response: Response):
    user = await db.users.find_one({"verification_token": token}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=400, detail="Token inválido o ya usado")
    expires = user.get("verification_expires_at")
    if expires and expires < iso(now_utc()):
        raise HTTPException(status_code=400, detail="El enlace expiró. Solicita uno nuevo.")
    if not user.get("email_verified"):
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"email_verified": True},
             "$unset": {"verification_token": "", "verification_expires_at": ""}},
        )
    # Do NOT auto-login. User should sign in manually with their credentials.
    return {"verified": True, "email": user["email"], "name": user.get("name", "")}


@router.post("/auth/resend-verification")
async def auth_resend_verification(payload: AuthResendVerificationPayload):
    """Resend the email verification link. Always returns a generic 200 to avoid
    leaking which emails are registered. Rate-limited to 1 request per 60s per user."""
    from datetime import datetime
    email = payload.email.lower().strip()
    generic_response = {
        "ok": True,
        "message": "Si la cuenta existe y no está verificada, te reenviamos el correo. Revisa tu bandeja (y spam).",
    }
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        return generic_response
    if user.get("auth_provider") != "password":
        return generic_response
    if user.get("email_verified"):
        return generic_response
    last_resend = user.get("last_resend_at")
    if last_resend:
        try:
            last_dt = datetime.fromisoformat(last_resend.replace("Z", "+00:00"))
            elapsed = (now_utc() - last_dt).total_seconds()
            if elapsed < RESEND_COOLDOWN_SECONDS:
                wait = int(RESEND_COOLDOWN_SECONDS - elapsed)
                raise HTTPException(
                    status_code=429,
                    detail=f"Por favor espera {wait}s antes de solicitar otro correo.",
                )
        except HTTPException:
            raise
        except Exception:
            pass
    new_token = uuid.uuid4().hex + uuid.uuid4().hex
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "verification_token": new_token,
            "verification_expires_at": iso(now_utc() + timedelta(hours=24)),
            "last_resend_at": iso(now_utc()),
        }},
    )
    try:
        email_service.notify_email_verification(email, user.get("name", ""), new_token)
    except Exception as e:
        logger.error(f"Resend verification email failed for {email}: {e}")
    return generic_response


@router.post("/auth/login")
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
    if user.get("auth_provider") == "password" and not user.get("email_verified", False):
        raise HTTPException(
            status_code=403,
            detail={"code": "EMAIL_NOT_VERIFIED",
                    "message": "Verifica tu correo antes de iniciar sesión. Revisa tu bandeja."},
        )
    await _record_login_attempt(identifier, True)
    # iter28 — every login re-checks the blocklist: if the user's phone is now blocked,
    # freeze the account (under_review) so they cannot operate even with a valid session.
    if user.get("phone"):
        blocked = await db.blocked_contacts.find_one({"phone": user["phone"]}, {"_id": 0})
        if blocked and user.get("role") in ("normal", "vip"):
            await db.users.update_one(
                {"user_id": user["user_id"]},
                {"$set": {"phone_verified": False, "account_status": "under_review"}},
            )
            user["phone_verified"] = False
            user["account_status"] = "under_review"
    ttl = payload.remember_hours if payload.remember_hours else 168
    await _create_session(user["user_id"], response, ttl_hours=ttl)
    user.pop("password_hash", None)
    user.pop("verification_token", None)
    return user


@router.post("/auth/forgot-password")
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


@router.post("/auth/reset-password")
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
