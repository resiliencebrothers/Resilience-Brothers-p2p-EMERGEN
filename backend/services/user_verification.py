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


def _cta_url(step: str, role: Optional[str]) -> str:
    """Destino del CTA de verificación según el rol. La Empresa vive en
    /company/* (su router devuelve /dashboard/* a /company), así que sus CTA
    deben apuntar a /company/kyc y /company/security — E34-03."""
    base = "/company" if role == "empresa" else "/dashboard"
    screen = "kyc" if step == "kyc" else "security"
    return f"{base}/{screen}"


async def _kyc_is_verified(
    db: Any, user_id: str, role: Optional[str] = None,
) -> bool:
    """Return True if the user has an approved verification.

    Only `status = "verified"` counts — pending / needs_more_info / rejected
    / superseded all mean the user cannot operate. Para una cuenta Empresa la
    verificación debe ser EMPRESARIAL (`kind = "company"`): un KYC personal
    aprobado NO habilita los retiros de una Empresa (E34-03).

    R10 — para la Empresa se evalúa el expediente `company` MÁS RECIENTE: si el
    último está 'pending'/'needs_more_info'/'superseded' (p. ej. una
    revalidación en curso o un reenvío), la empresa NO está verificada aunque
    exista una aprobación anterior. Así el estado del guard es siempre coherente
    con la última decisión, sin depender de que el sellado 'superseded' se
    completara."""
    if role == "empresa":
        latest = await db.kyc_verifications.find_one(
            {"user_id": user_id, "kind": "company"},
            {"_id": 0, "status": 1}, sort=[("created_at", -1)])
        return bool(latest and latest.get("status") == "verified")
    doc = await db.kyc_verifications.find_one(
        {"user_id": user_id, "status": "verified"}, {"_id": 0, "status": 1})
    return doc is not None


async def verified_company_owner_ids(
    db: Any, owner_ids: List[str],
) -> set[str]:
    """Batch sibling of `_kyc_is_verified(role='empresa')`.

    Given a list of marketplace product owner ids, return the subset whose
    LATEST company (KYB) expediente is approved. Mirrors R10 — the most recent
    `kind='company'` verification decides, so a re-submission in progress
    (pending / needs_more_info) un-badges the company until re-approved. Used
    to show the "Empresa verificada" trust badge next to products.
    """
    ids = list({o for o in owner_ids if o})
    if not ids:
        return set()
    verified: set[str] = set()
    cursor = db.kyc_verifications.aggregate([
        {"$match": {"user_id": {"$in": ids}, "kind": "company"}},
        {"$sort": {"created_at": -1}},
        {"$group": {"_id": "$user_id", "status": {"$first": "$status"}}},
    ])
    async for row in cursor:
        if row.get("status") == "verified":
            verified.add(row["_id"])
    return verified


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
    kyc_ok = await _kyc_is_verified(db, user["user_id"], user.get("role"))
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
    # `fully_verified` was False, so `missing` is guaranteed non-empty and
    # `first` is a concrete string. Assign directly (no Optional) so the
    # code_map / msg_map / _CTA_MAP indexers below type-check cleanly.
    first: str = missing[0]

    role = user.get("role")
    is_company = role == "empresa"

    # Pick the most user-actionable code (first missing step in a natural
    # order: email → phone → KYC). All three codes are returned in the
    # `missing` list so the frontend can render every pending step.
    code_map = {
        "email": "EMAIL_NOT_VERIFIED",
        "phone": "PHONE_NOT_VERIFIED",
        "kyc": "KYC_NOT_APPROVED",
    }
    kyc_msg = (
        ("Debes completar la VERIFICACIÓN DE EMPRESA (código fiscal, "
         "licencia operativa y dirección legal) antes de poder "
         f"{action_label}. Ve a Empresa → Verificación. Un KYC personal "
         "no habilita los retiros de una cuenta Empresa.")
        if is_company else
        ("Debes completar la verificación de identidad (KYC) "
         f"antes de poder {action_label}. Sube tu documento de "
         "identidad y una selfie desde /dashboard/kyc.")
    )
    msg_map = {
        "email": ("Debes verificar tu email antes de poder "
                  f"{action_label}. Revisa tu bandeja de entrada o "
                  "reenvía el correo desde Perfil → Seguridad."),
        "phone": ("Tu número de teléfono debe ser verificado por un "
                  f"miembro del staff antes de poder {action_label}. "
                  "Contacta a soporte para acelerar la verificación."),
        "kyc": kyc_msg,
    }
    raise HTTPException(
        status_code=403,
        detail={
            "code": code_map[first],
            "message": msg_map[first],
            "missing": missing,
            "cta_url": _cta_url(first, role),
        },
    )
