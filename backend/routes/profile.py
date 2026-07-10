"""iter55.20 — Client-side profile management.

Consolidates the client's ability to view + change the data they registered
with. Complements the read-only KYC + 2FA views that already exist under
`/dashboard/kyc` and `/dashboard/security`.

Endpoints (client-facing, all under /api/profile):
- GET  /me                     — full profile snapshot + change-request state
- POST /email/request-change   — send OTP to NEW email, alert OLD email
- POST /email/confirm-change   — validate OTP, apply the change
- POST /phone/request-change   — 2FA-guarded; stores as pending_admin_review
- POST /country/change         — instant; resets KYC to pending if was approved

Design decisions (operator-approved 2026-07-10):
- EMAIL: dual-notification (code to new + alert to old) — matches Google/Apple UX
- PHONE: 2FA-required + admin approval — same rigor as the initial verification
- COUNTRY: no friction, but a verified KYC re-enters the review queue
"""
from __future__ import annotations

import hashlib
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, ConfigDict

from db_client import db
from auth_utils import require_user, _enforce_totp_step_up, now_utc, iso


router = APIRouter(tags=["Profile"])


# ============================================================
# Helpers
# ============================================================

_CODE_LEN = 6
_CODE_TTL_MIN = 15  # OTP for email change is valid for 15 minutes


def _generate_otp() -> str:
    """Return a 6-digit numeric code (compatible with SMS/email UX)."""
    return "".join(secrets.choice(string.digits) for _ in range(_CODE_LEN))


def _hash_code(code: str) -> str:
    """SHA-256 hex of the code — we never store plain OTPs at rest."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _redact_email(email: str) -> str:
    """`juan@example.com` → `j***@e*******.com` — safe to expose in UI."""
    if not email or "@" not in email:
        return "***"
    local, _, dom = email.partition("@")
    def _mask(s: str) -> str:
        if len(s) <= 1:
            return s + "***"
        return s[0] + "*" * (len(s) - 1)
    domain_head, dot, tld = dom.partition(".")
    return f"{_mask(local)}@{_mask(domain_head)}{dot}{tld}"


def _redact_phone(phone: str) -> str:
    """`+5355559999` → `+5355***9999` — enough to recognize but not to leak."""
    if not phone or len(phone) < 6:
        return "***"
    return phone[:5] + "***" + phone[-4:]


# ============================================================
# GET /profile/me
# ============================================================

@router.get("/profile/me")
async def get_my_profile(request: Request) -> Any:
    user = await require_user(request)
    doc = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    kyc = await db.kyc_verifications.find_one(
        {"user_id": user["user_id"]}, {"_id": 0},
        sort=[("created_at", -1)],
    )
    pending_email = doc.get("pending_email_change") or {}
    pending_phone = doc.get("pending_phone_change") or {}
    return {
        "user_id": doc.get("user_id"),
        "name": doc.get("name", ""),
        "email": doc.get("email", ""),
        "phone": doc.get("phone", ""),
        "phone_verified": bool(doc.get("phone_verified", False)),
        "country": doc.get("country", ""),
        "role": doc.get("role", ""),
        "created_at": doc.get("created_at", ""),
        "twofa_enabled": bool(doc.get("twofa_enabled", False)),
        "kyc_status": (kyc or {}).get("status", "not_started"),
        "pending_email_change": {
            "new_email_masked": _redact_email(pending_email.get("new_email", "")),
            "requested_at": pending_email.get("requested_at", ""),
        } if pending_email else None,
        "pending_phone_change": {
            "new_phone_masked": _redact_phone(pending_phone.get("new_phone", "")),
            "requested_at": pending_phone.get("requested_at", ""),
            "status": pending_phone.get("status", "pending_admin_review"),
        } if pending_phone else None,
    }


# ============================================================
# POST /profile/email/request-change
# ============================================================

class EmailChangeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    new_email: EmailStr
    totp_code: Optional[str] = Field(None, min_length=6, max_length=11)


@router.post("/profile/email/request-change")
async def request_email_change(payload: EmailChangeRequest, request: Request) -> Any:
    user = await require_user(request)
    await _enforce_totp_step_up(user, payload.totp_code,
                                 action_label="cambiar tu email")
    new_email = payload.new_email.lower().strip()
    if new_email == (user.get("email") or "").lower().strip():
        raise HTTPException(status_code=400, detail="El email nuevo es igual al actual.")
    existing = await db.users.find_one({"email": new_email}, {"_id": 0, "user_id": 1})
    if existing:
        # Same wording as normal-user leak protection — don't confirm registration
        raise HTTPException(status_code=400, detail="Ese email ya está en uso.")

    code = _generate_otp()
    expires_at = now_utc() + timedelta(minutes=_CODE_TTL_MIN)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"pending_email_change": {
            "new_email": new_email,
            "code_hash": _hash_code(code),
            "code_expires_at": iso(expires_at),
            "requested_at": iso(now_utc()),
        }}},
    )

    # Fan-out: code to new inbox + heads-up to old inbox (dual-notification)
    from email_service import notify_email_change_code, notify_email_change_alert
    notify_email_change_code(new_email, user.get("name", ""), code)
    if user.get("email"):
        notify_email_change_alert(user["email"], user.get("name", ""),
                                   _redact_email(new_email))
    return {
        "ok": True,
        "sent_to_masked": _redact_email(new_email),
        "expires_in_minutes": _CODE_TTL_MIN,
    }


class EmailConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str = Field(..., min_length=_CODE_LEN, max_length=_CODE_LEN)


@router.post("/profile/email/confirm-change")
async def confirm_email_change(payload: EmailConfirmRequest, request: Request) -> Any:
    user = await require_user(request)
    doc = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    pending = (doc or {}).get("pending_email_change") or {}
    if not pending or not pending.get("new_email"):
        raise HTTPException(status_code=400, detail="No hay cambio de email pendiente.")
    # Validate expiry
    try:
        exp = datetime.fromisoformat(pending["code_expires_at"])
    except Exception:
        exp = None
    if not exp or now_utc() > exp:
        await db.users.update_one({"user_id": user["user_id"]},
                                    {"$unset": {"pending_email_change": ""}})
        raise HTTPException(status_code=400, detail="El código expiró. Solicita otro.")
    if _hash_code(payload.code.strip()) != pending.get("code_hash"):
        raise HTTPException(status_code=400, detail="Código incorrecto.")

    new_email = pending["new_email"]
    old_email = doc.get("email", "")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"email": new_email},
         "$unset": {"pending_email_change": ""}},
    )
    # Post-change confirmation to both inboxes (best effort)
    from email_service import notify_email_change_success
    notify_email_change_success(new_email, doc.get("name", ""),
                                 _redact_email(old_email))
    if old_email:
        notify_email_change_success(old_email, doc.get("name", ""),
                                     _redact_email(new_email))
    # Audit log — every email change should be traceable
    from audit_log import log_action
    await log_action(db, user, "profile.email_change", "user", user["user_id"],
                      summary=f"Email cambiado {_redact_email(old_email)} → {_redact_email(new_email)}",
                      details={"old_email": old_email, "new_email": new_email})
    return {"ok": True, "email": new_email}


# ============================================================
# POST /profile/phone/request-change
# ============================================================

class PhoneChangeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    new_phone: str = Field(..., min_length=6, max_length=25)
    totp_code: Optional[str] = Field(None, min_length=6, max_length=11)


@router.post("/profile/phone/request-change")
async def request_phone_change(payload: PhoneChangeRequest, request: Request) -> Any:
    user = await require_user(request)
    await _enforce_totp_step_up(user, payload.totp_code,
                                 action_label="cambiar tu teléfono")
    new_phone = payload.new_phone.strip()
    if new_phone == (user.get("phone") or "").strip():
        raise HTTPException(status_code=400, detail="El teléfono nuevo es igual al actual.")
    # Uniqueness guard (same as registration)
    existing = await db.users.find_one({"phone": new_phone}, {"_id": 0, "user_id": 1})
    if existing and existing["user_id"] != user["user_id"]:
        raise HTTPException(status_code=400, detail="Ese teléfono ya está en uso por otro usuario.")

    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"pending_phone_change": {
            "new_phone": new_phone,
            "requested_at": iso(now_utc()),
            "status": "pending_admin_review",
        }}},
    )

    # Notify staff via the same fan-out pattern as new registrations
    from routes.notifications import _insert_notification
    async for admin in db.users.find(
        {"$or": [{"role": "admin"},
                 {"role": "employee", "can_manage_blocklist": True}]},
        {"_id": 0, "user_id": 1},
    ):
        await _insert_notification(
            recipient_user_id=admin["user_id"],
            type="profile_phone_change_pending",
            title="Cambio de teléfono solicitado",
            message=f"{user.get('name', 'Cliente')} pidió cambiar su celular a {_redact_phone(new_phone)}.",
            data={"target_user_id": user["user_id"], "new_phone_masked": _redact_phone(new_phone)},
        )

    from audit_log import log_action
    await log_action(db, user, "profile.phone_change_requested", "user", user["user_id"],
                      summary=f"Solicitó cambio de celular a {_redact_phone(new_phone)}",
                      details={"new_phone": new_phone})

    return {"ok": True, "status": "pending_admin_review",
            "new_phone_masked": _redact_phone(new_phone)}


@router.delete("/profile/phone/pending")
async def cancel_pending_phone_change(request: Request) -> Any:
    user = await require_user(request)
    r = await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$unset": {"pending_phone_change": ""}},
    )
    return {"ok": True, "cancelled": bool(r.modified_count)}


# ============================================================
# POST /profile/country/change
# ============================================================

class CountryChangeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    new_country: str = Field(..., min_length=2, max_length=60)


@router.post("/profile/country/change")
async def change_country(payload: CountryChangeRequest, request: Request) -> Any:
    user = await require_user(request)
    new_country = payload.new_country.strip()
    if new_country == (user.get("country") or "").strip():
        raise HTTPException(status_code=400, detail="El país nuevo es igual al actual.")
    old_country = user.get("country", "")

    # Persist the country immediately (frictionless UX).
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"country": new_country}},
    )

    # If the client had an APPROVED KYC, put it back into the queue so the
    # operator can re-verify (country affects AML risk).
    kyc = await db.kyc_verifications.find_one(
        {"user_id": user["user_id"]}, {"_id": 0},
        sort=[("created_at", -1)],
    )
    kyc_reset = False
    if kyc and kyc.get("status") == "approved":
        await db.kyc_verifications.update_one(
            {"id": kyc["id"]},
            {"$set": {
                "status": "pending_review",
                "reset_reason": f"country_change:{old_country}→{new_country}",
                "reset_at": iso(now_utc()),
            }},
        )
        kyc_reset = True

    from audit_log import log_action
    await log_action(db, user, "profile.country_change", "user", user["user_id"],
                      summary=f"País cambiado {old_country or '—'} → {new_country}"
                              + (" (KYC re-entered review)" if kyc_reset else ""),
                      details={"old_country": old_country, "new_country": new_country,
                               "kyc_reset": kyc_reset})

    return {"ok": True, "country": new_country, "kyc_reset": kyc_reset}


# ============================================================
# Admin — approve/reject phone-change requests
# ============================================================

@router.get("/admin/profile-change-requests")
async def list_pending_profile_changes(request: Request) -> Any:
    from services.permissions import require_permission
    await require_permission(request, "profile_changes")
    cursor = db.users.find(
        {"pending_phone_change": {"$exists": True, "$ne": None}},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "phone": 1,
         "country": 1, "pending_phone_change": 1},
    )
    items = []
    async for u in cursor:
        pc = u.get("pending_phone_change") or {}
        items.append({
            "user_id": u["user_id"],
            "name": u.get("name", ""),
            "email": u.get("email", ""),
            "current_phone": u.get("phone", ""),
            "country": u.get("country", ""),
            "new_phone": pc.get("new_phone", ""),
            "requested_at": pc.get("requested_at", ""),
        })
    return {"items": items, "count": len(items)}


class ApprovePhoneChange(BaseModel):
    model_config = ConfigDict(extra="ignore")
    totp_code: Optional[str] = Field(None, min_length=6, max_length=11)


@router.post("/admin/profile-change-requests/{target_user_id}/approve-phone")
async def approve_phone_change(target_user_id: str, payload: ApprovePhoneChange,
                                request: Request) -> Any:
    from services.permissions import require_permission
    actor = await require_permission(request, "profile_changes")
    await _enforce_totp_step_up(actor, payload.totp_code,
                                 action_label="aprobar cambio de teléfono")
    target = await db.users.find_one({"user_id": target_user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    pc = target.get("pending_phone_change") or {}
    if not pc.get("new_phone"):
        raise HTTPException(status_code=400, detail="No hay cambio pendiente para este usuario.")

    old_phone = target.get("phone", "")
    new_phone = pc["new_phone"]
    await db.users.update_one(
        {"user_id": target_user_id},
        {"$set": {"phone": new_phone, "phone_verified": True},
         "$unset": {"pending_phone_change": ""}},
    )
    # Ping the client
    from routes.notifications import _insert_notification
    await _insert_notification(
        recipient_user_id=target_user_id,
        type="profile_phone_change_approved",
        title="Tu nuevo teléfono fue verificado",
        message=f"El equipo aprobó tu cambio a {_redact_phone(new_phone)}.",
        data={"new_phone_masked": _redact_phone(new_phone)},
    )
    # iter55.20b — also email the client so the notification isn't missed.
    if target.get("email"):
        import email_service
        email_service.notify_phone_change_approved(
            target["email"], target.get("name", ""), _redact_phone(new_phone),
        )
    from audit_log import log_action
    await log_action(db, actor, "profile.phone_change_approved", "user", target_user_id,
                      summary=f"Aprobó cambio de teléfono {_redact_phone(old_phone)} → {_redact_phone(new_phone)}",
                      details={"target_user_id": target_user_id,
                               "old_phone": old_phone, "new_phone": new_phone})
    return {"ok": True, "phone": new_phone}


class RejectPhoneChange(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reason: str = Field(..., min_length=3, max_length=300)
    totp_code: Optional[str] = Field(None, min_length=6, max_length=11)


@router.post("/admin/profile-change-requests/{target_user_id}/reject-phone")
async def reject_phone_change(target_user_id: str, payload: RejectPhoneChange,
                               request: Request) -> Any:
    from services.permissions import require_permission
    actor = await require_permission(request, "profile_changes")
    await _enforce_totp_step_up(actor, payload.totp_code,
                                 action_label="rechazar cambio de teléfono")
    target = await db.users.find_one({"user_id": target_user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    pc = target.get("pending_phone_change") or {}
    if not pc.get("new_phone"):
        raise HTTPException(status_code=400, detail="No hay cambio pendiente para este usuario.")

    new_phone = pc["new_phone"]
    await db.users.update_one(
        {"user_id": target_user_id},
        {"$unset": {"pending_phone_change": ""}},
    )
    from routes.notifications import _insert_notification
    await _insert_notification(
        recipient_user_id=target_user_id,
        type="profile_phone_change_rejected",
        title="Tu cambio de teléfono fue rechazado",
        message=payload.reason[:200],
        data={"new_phone_masked": _redact_phone(new_phone), "reason": payload.reason},
    )
    # iter55.20b — email the rejection so the client sees the reason even
    # outside the app.
    if target.get("email"):
        import email_service
        email_service.notify_phone_change_rejected(
            target["email"], target.get("name", ""),
            _redact_phone(new_phone), payload.reason,
        )
    from audit_log import log_action
    await log_action(db, actor, "profile.phone_change_rejected", "user", target_user_id,
                      summary=f"Rechazó cambio a {_redact_phone(new_phone)}: {payload.reason[:80]}",
                      details={"target_user_id": target_user_id,
                               "new_phone": new_phone, "reason": payload.reason})
    return {"ok": True}
