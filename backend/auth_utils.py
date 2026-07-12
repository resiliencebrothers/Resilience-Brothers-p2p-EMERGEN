"""Shared auth utilities — extracted from server.py during iter27 refactor.
Used by both server.py (legacy callers) and routes/* modules (auth, blocklist, etc.).

All helpers consume the shared `db` from db_client. No circular imports.
"""
import re
import json
import base64
import uuid
import bcrypt
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException, Request, Response

from db_client import db
import totp_service
from services.permissions import (
    VALID_CODES as _PERM_VALID_CODES,
    _has_permission as _has_perm,
    permission_label as _perm_label,
)


# ---------- Time helpers ----------

def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else dt


# ---------- Password helpers ----------

def _hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---------- Session helpers ----------

# iter55.37 — Security policy: ALL sessions are capped at 24 hours regardless
# of what the caller requests. Financial platform requirement: session tokens
# must expire within 24h to limit exposure of leaked cookies / device theft.
# Users re-authenticate daily (custom Google OAuth or email/password re-login).
SESSION_MAX_HOURS = 24


async def _create_session(user_id: str, response: Response, ttl_hours: int = SESSION_MAX_HOURS,
                          session_token: Optional[str] = None):
    """Issue a session_token + set cookie. Hard-capped at 24 hours by policy.

    Legacy callers may pass ttl_hours > 24 (e.g. 168 for "remember me 7d") —
    those get silently clamped to 24 to enforce the security policy across
    every entry point (Google OAuth, email login, Emergent OAuth bridge).

    `session_token` (optional): when the caller already has a token from an
    upstream provider (Emergent OAuth), pass it here. Otherwise a fresh 64-char
    hex token is generated. Either way the DB row + cookie are written the
    exact same way — one place enforces the TTL cap for all auth flows.
    """
    ttl_hours = max(1, min(int(ttl_hours), SESSION_MAX_HOURS))  # clamp 1h..24h
    if not session_token:
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
    # Tag Sentry with the actor so errors surface user context.
    if user:
        try:
            import sentry_sdk
            sentry_sdk.set_user({
                "id": user.get("user_id"),
                "email": user.get("email"),
                "role": user.get("role"),
            })
        except Exception:
            pass
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


# iter55.16 — HTTP gate for per-staff permissions. The catalog + pure
# predicate live in `services.permissions` (data-only, zero FastAPI deps);
# the actual HTTP gate lives HERE so we don't cycle with `require_user`.
async def require_permission(request: Request, code: str) -> dict:
    """Gate an admin/staff endpoint by a specific permission code.

    Admins bypass. Employees pass if their `allowed_permissions` is empty OR
    contains the code. Everything else → 403 with a message that names the
    missing permission (so the admin can grant it in 1 click).

    Usage:
        actor = await require_permission(request, "kyc")
    """
    if code not in _PERM_VALID_CODES:
        # Programmer error — refuse silently in prod, loud in tests.
        raise HTTPException(status_code=500, detail=f"unknown_permission_code:{code}")

    user = await require_user(request)
    if _has_perm(user, code):
        return user

    role = user.get("role")
    if role not in ("admin", "employee"):
        raise HTTPException(status_code=403, detail="Staff only")

    # Employee without the required permission — explain clearly.
    raise HTTPException(
        status_code=403,
        detail=(
            f"No tienes el permiso '{_perm_label(code)}' asignado. "
            f"Contacta al admin para que te lo habilite."
        ),
    )


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


# ---------- Brute-force protection ----------

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


# ---------- Phone helpers (iter23) ----------

PHONE_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str) -> str:
    """Strip spaces, dashes, parens. Result must match E.164 (+1234567890)."""
    cleaned = re.sub(r"[\s\-\(\)\.]", "", raw or "")
    if not PHONE_E164_RE.match(cleaned):
        raise HTTPException(
            status_code=422,
            detail="Formato de teléfono inválido. Usa formato internacional: +<código país><número>, ej. +5350123456",
        )
    return cleaned


async def assert_not_blocked(*, email: Optional[str] = None, phone: Optional[str] = None):
    """iter23 — reject registration if email OR phone match any entry in blocked_contacts."""
    or_clauses = []
    if email:
        or_clauses.append({"email": email.lower().strip()})
    if phone:
        or_clauses.append({"phone": phone})
    if not or_clauses:
        return
    hit = await db.blocked_contacts.find_one({"$or": or_clauses})
    if hit:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "BLOCKED_CONTACT",
                "message": "Esta cuenta no puede ser creada. Si crees que es un error, contacta a soporte.",
            },
        )


# ---------- Google OAuth helpers (iter22) ----------

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


# ---------- 2FA / TOTP step-up (iter12) ----------

async def _try_recovery_code(user: dict, submitted: str) -> bool:
    """Return True if `submitted` matched and was consumed as a recovery code.
    False means it doesn't look like a recovery code — caller should try TOTP.
    Raises 401 only when it looks like a recovery code but fails to match."""
    if len(submitted) < 10 or not any(c.isalpha() for c in submitted):
        return False
    ok, remaining = totp_service.consume_recovery_code(
        user.get("totp_recovery_codes", []) or [], submitted,
    )
    if ok:
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"totp_recovery_codes": remaining}},
        )
        return True
    raise HTTPException(
        status_code=401,
        detail={"code": "TOTP_INVALID", "message": "Código de recuperación inválido."},
    )


def _verify_totp_code(user: dict, submitted: str) -> None:
    """Verify a 6-digit TOTP against the user's encrypted secret. Raises on failure."""
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


async def _enforce_totp_step_up(user: dict, code: Optional[str], action_label: str = "esta acción"):
    """Raise HTTPException if user has no 2FA enabled OR submitted code is invalid.
    Consumes a recovery code if `code` matches one. Otherwise verifies TOTP."""
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
    if await _try_recovery_code(user, submitted):
        return
    _verify_totp_code(user, submitted)
