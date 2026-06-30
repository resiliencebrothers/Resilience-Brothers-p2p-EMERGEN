"""User self-service router — iter33. All `/me/*` endpoints that the
authenticated user can call to manage their own account.

Endpoints:
- POST /me/onboarding/complete
- POST /me/phone                              (set / update phone, kicks off staff review)
- GET  /me/2fa/status
- POST /me/2fa/setup                          (generate QR + pending secret)
- POST /me/2fa/verify-setup                   (confirm + enable 2FA)
- POST /me/2fa/disable
- POST /me/2fa/regenerate-recovery-codes
- GET  /me/transactions
- GET  /me/transactions/export.csv
- GET  /me/transactions/export.pdf
"""
import csv
import io
import logging
from io import BytesIO
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import (
    require_user, now_utc, iso,
    normalize_phone, assert_not_blocked,
    _enforce_totp_step_up,
)
import totp_service
from transactions_pdf import generate_transactions_pdf
from datetime import datetime, timezone

from services.transactions import build_transactions, compute_transaction_totals


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Me"])


# ============================================================
# Onboarding
# ============================================================

@router.post("/me/onboarding/complete")
async def complete_onboarding(request: Request) -> Any:
    """Mark the current user's first-visit onboarding tour as completed."""
    user = await require_user(request)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"onboarding_completed": True}},
    )
    return {"ok": True}


# ============================================================
# Phone management
# ============================================================

class PhoneSetPayload(BaseModel):
    phone: str = Field(..., min_length=8, max_length=20)


@router.post("/me/phone")
async def set_my_phone(payload: PhoneSetPayload, request: Request) -> Any:
    """Self-service for Google OAuth users (phone not collected at signup) or any
    user updating their number. Phone goes back to phone_verified=False; staff
    must re-verify before withdrawals are allowed."""
    user = await require_user(request)
    phone = normalize_phone(payload.phone)
    await assert_not_blocked(email=user["email"], phone=phone)
    other = await db.users.find_one(
        {"phone": phone, "user_id": {"$ne": user["user_id"]}}, {"_id": 0}
    )
    if other:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PHONE_IN_USE",
                "message": "Este número ya está asociado a otra cuenta.",
            },
        )
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"phone": phone, "phone_verified": False}},
    )
    # Notify staff that a new user is pending verification — only on the FIRST phone set.
    if not user.get("phone"):
        try:
            from routes.notifications import notify_staff_new_pending_user
            fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
            if fresh and fresh.get("role") in ("normal", "vip"):
                await notify_staff_new_pending_user(fresh)
        except Exception as e:
            logger.error(f"Notification fan-out failed for new pending user: {e}")
    return {"ok": True, "phone": phone, "phone_verified": False}


# ============================================================
# 2FA / TOTP
# ============================================================

@router.get("/me/2fa/status")
async def totp_status(request: Request) -> Any:
    user = await require_user(request)
    return {
        "enabled": bool(user.get("totp_enabled")),
        "setup_at": user.get("totp_setup_at"),
        "recovery_codes_remaining": len(user.get("totp_recovery_codes") or []),
    }


@router.post("/me/2fa/setup")
async def totp_setup(request: Request) -> Any:
    """Generates a pending TOTP secret + QR. NOT enabled until /verify-setup confirms a valid code."""
    user = await require_user(request)
    if user.get("totp_enabled"):
        raise HTTPException(
            status_code=409,
            detail="2FA ya está habilitado. Desactívalo primero para reconfigurar.",
        )
    secret = totp_service.generate_secret()
    encrypted = totp_service.encrypt_secret(secret)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"totp_pending_secret_encrypted": encrypted}},
    )
    uri = totp_service.provisioning_uri(secret, user["email"])
    return {
        "qr_data_url": totp_service.qr_data_url(uri),
        "secret": secret,
        "provisioning_uri": uri,
        "issuer": totp_service.ISSUER,
    }


@router.post("/me/2fa/verify-setup")
async def totp_verify_setup(request: Request, payload: dict) -> Any:
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


@router.post("/me/2fa/disable")
async def totp_disable(request: Request, payload: dict) -> Any:
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


@router.post("/me/2fa/regenerate-recovery-codes")
async def totp_regenerate_recovery(request: Request, payload: dict) -> Any:
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


# ============================================================
# My transactions (read-only own data)
# ============================================================

def _validate_txn_filters(direction: Optional[str], min_amount: Optional[float],
                          max_amount: Optional[float]) -> None:
    if direction and direction not in ("in", "out", "all"):
        raise HTTPException(status_code=400, detail="direction debe ser 'in', 'out' o 'all'")
    if min_amount is not None and min_amount < 0:
        raise HTTPException(status_code=400, detail="min_amount debe ser >= 0")
    if max_amount is not None and max_amount < 0:
        raise HTTPException(status_code=400, detail="max_amount debe ser >= 0")
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise HTTPException(status_code=400, detail="min_amount no puede ser mayor que max_amount")


@router.get("/me/transactions")
async def list_my_transactions(request: Request,
                               direction: Optional[str] = None,
                               currency: Optional[str] = None,
                               since: Optional[str] = None,
                               until: Optional[str] = None,
                               min_amount: Optional[float] = None,
                               max_amount: Optional[float] = None,
                               limit: int = 100, offset: int = 0) -> Any:
    user = await require_user(request)
    _validate_txn_filters(direction, min_amount, max_amount)
    items = await build_transactions(
        direction, currency, None, since, until, min_amount, max_amount,
        user_id=user["user_id"],
    )
    totals = compute_transaction_totals(items)
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


@router.get("/me/transactions/export.csv")
async def export_my_transactions_csv(request: Request,
                                     direction: Optional[str] = None,
                                     currency: Optional[str] = None,
                                     since: Optional[str] = None,
                                     until: Optional[str] = None,
                                     min_amount: Optional[float] = None,
                                     max_amount: Optional[float] = None) -> Any:
    user = await require_user(request)
    items = await build_transactions(
        direction, currency, None, since, until, min_amount, max_amount,
        user_id=user["user_id"],
    )
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


@router.get("/me/transactions/export.pdf")
async def export_my_transactions_pdf(request: Request,
                                     direction: Optional[str] = None,
                                     currency: Optional[str] = None,
                                     since: Optional[str] = None,
                                     until: Optional[str] = None,
                                     min_amount: Optional[float] = None,
                                     max_amount: Optional[float] = None) -> Any:
    user = await require_user(request)
    items = await build_transactions(
        direction, currency, None, since, until, min_amount, max_amount,
        user_id=user["user_id"],
    )
    totals = compute_transaction_totals(items)
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
