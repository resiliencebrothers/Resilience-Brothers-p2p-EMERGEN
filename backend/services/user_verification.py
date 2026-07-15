"""iter55.36o — Full-verification gate for exchange, conversion and marketplace flows.

Business rule (agreed with product, Feb 14 2026)
------------------------------------------------
A Normal/VIP client can create an order (POST /orders), do an internal
conversion (POST /vip/convert), redeem in the marketplace (POST /vip/redeem)
or withdraw funds (POST /vip/withdraw) **only if all three verifications
are complete**:

  1. Email verified   → `users.email_verified is True`
  2. Phone verified   → `users.phone_verified is True`
                         (staff-approved via `POST /admin/users/{id}/verify-phone`)
  3. KYC approved     → the user's latest `kyc_verifications` row has
                         `status = "verified"`.

Staff (`admin`, `employee`) always bypass — internal operations do not require
KYC. `account_status` gating (active / under_review / blocked) is enforced
separately by `services.balances.assert_account_active`.

The helper raises `HTTPException(403)` with a machine-readable `code`
(`EMAIL_NOT_VERIFIED`, `PHONE_NOT_VERIFIED`, `KYC_NOT_APPROVED`) and a
`missing` list so the SPA can highlight all pending steps in one shot
without triggering multiple round trips.
"""
from typing import Any, List, Optional

from fastapi import HTTPException


_CTA_MAP = {
    "email": "/dashboard/security",
    "phone": "/dashboard/security",
    "kyc": "/dashboard/kyc",
}


async def _kyc_is_verified(db: Any, user_id: str) -> bool:
    """Return True if the user has an approved KYC verification.

    Only `status = "verified"` counts — pending / needs_more_info / rejected
    all mean the user cannot operate.
    """
    doc = await db.kyc_verifications.find_one(
        {"user_id": user_id, "status": "verified"},
        {"_id": 0, "status": 1},
    )
    return doc is not None


async def get_user_verification_state(db: Any, user: dict) -> dict:
    """Snapshot the three verification flags for one user.

    Used by the frontend to render the verification banner without inferring
    from separate endpoints. Staff always returns `fully_verified=True`.
    """
    if user.get("role") in ("admin", "employee"):
        return {
            "fully_verified": True,
            "email_verified": True,
            "phone_verified": True,
            "kyc_verified": True,
            "missing": [],
        }
    email_ok = bool(user.get("email_verified"))
    phone_ok = bool(user.get("phone_verified"))
    kyc_ok = await _kyc_is_verified(db, user["user_id"])
    missing: List[str] = []
    if not email_ok:
        missing.append("email")
    if not phone_ok:
        missing.append("phone")
    if not kyc_ok:
        missing.append("kyc")
    return {
        "fully_verified": len(missing) == 0,
        "email_verified": email_ok,
        "phone_verified": phone_ok,
        "kyc_verified": kyc_ok,
        "missing": missing,
    }


async def assert_user_fully_verified(
    db: Any, user: dict, action_label: str = "esta acción",
) -> None:
    """Raise 403 if the user is not fully verified (email + phone + KYC).

    Args:
        db: motor database handle.
        user: user document (must have `role`, `user_id`, `email_verified`,
              `phone_verified`).
        action_label: user-facing label describing the blocked action, e.g.
              "crear una orden", "convertir saldos", "canjear productos".

    Staff (admin, employee) bypass unconditionally.
    """
    state = await get_user_verification_state(db, user)
    if state["fully_verified"]:
        return

    missing = state["missing"]
    first: Optional[str] = missing[0] if missing else None

    # Pick the most user-actionable code (first missing step in a natural
    # order: email → phone → KYC). All three codes are returned in the
    # `missing` list so the frontend can render every pending step.
    code_map = {
        "email": "EMAIL_NOT_VERIFIED",
        "phone": "PHONE_NOT_VERIFIED",
        "kyc": "KYC_NOT_APPROVED",
    }
    msg_map = {
        "email": ("Debes verificar tu email antes de poder "
                  f"{action_label}. Revisa tu bandeja de entrada o "
                  "reenvía el correo desde Perfil → Seguridad."),
        "phone": ("Tu número de teléfono debe ser verificado por un "
                  f"miembro del staff antes de poder {action_label}. "
                  "Contacta a soporte para acelerar la verificación."),
        "kyc": ("Debes completar la verificación de identidad (KYC) "
                f"antes de poder {action_label}. Sube tu documento de "
                "identidad y una selfie desde /dashboard/kyc."),
    }
    raise HTTPException(
        status_code=403,
        detail={
            "code": code_map[first],
            "message": msg_map[first],
            "missing": missing,
            "cta_url": _CTA_MAP[first],
        },
    )
