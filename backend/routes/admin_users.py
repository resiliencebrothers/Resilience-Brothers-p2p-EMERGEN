"""Admin router — user management (list, update, manual email verification).

Extracted from routes/admin.py during the iter39 split.
"""
from typing import Dict, List, Literal, Optional, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import require_staff, require_permission, _enforce_totp_step_up
from audit_log import log_action
from services.balances import build_rate_lookup, convert_to_usdt


router = APIRouter(tags=["Admin"])


class UserUpdate(BaseModel):
    role: Optional[Literal["normal", "vip", "employee", "admin"]] = None
    vip_balance_usd: Optional[float] = None
    vip_balances: Optional[Dict[str, float]] = None
    allowed_currencies: Optional[List[str]] = None
    allowed_permissions: Optional[List[str]] = None  # iter55.16 — capability-based access
    can_edit_product_prices: Optional[bool] = None
    can_upload_product_images: Optional[bool] = None
    can_delete_products: Optional[bool] = None
    can_manage_blocklist: Optional[bool] = None
    can_manage_company_funds: Optional[bool] = None  # iter54 — capital de trabajo
    account_status: Optional[Literal["active", "under_review", "blocked"]] = None
    totp_code: Optional[str] = Field(None, max_length=11, description="Código 2FA requerido")


@router.get("/admin/users")
async def list_users(request: Request, q: Optional[str] = None,
                     role: Optional[str] = None,
                     limit: int = 1000, offset: int = 0) -> Any:
    await require_permission(request, "users")
    mongo_q: Dict[str, Any] = {}
    if q:
        rx = {"$regex": q, "$options": "i"}
        mongo_q["$or"] = [{"name": rx}, {"email": rx}]
    if role and role in ("normal", "vip", "employee", "admin"):
        mongo_q["role"] = role
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    total = await db.users.count_documents(mongo_q)
    docs = await db.users.find(mongo_q, {"_id": 0}).sort("created_at", -1).skip(offset).to_list(limit)
    # iter47 — enrich each non-staff user with a server-side USDT-equivalent
    # so the admin list can render a multi-currency total without an extra
    # rates roundtrip on the frontend.
    rates = await build_rate_lookup()
    for d in docs:
        if d.get("role") in ("normal", "vip"):
            bals: Dict[str, float] = dict(d.get("vip_balances") or {})
            legacy = float(d.get("vip_balance_usd") or 0.0)
            if legacy:
                bals["USD"] = bals.get("USD", 0.0) + legacy
            total_usdt = 0.0
            for code, amount in bals.items():
                amt = float(amount or 0.0)
                if amt == 0:
                    continue
                u = convert_to_usdt(amt, code, rates)
                if u is not None:
                    total_usdt += u
            d["vip_balance_usdt"] = round(total_usdt, 4)
    return JSONResponse(
        content=docs,
        headers={
            "X-Total-Count": str(total),
            "X-Offset": str(offset),
            "X-Limit": str(limit),
            "Access-Control-Expose-Headers": "X-Total-Count, X-Offset, X-Limit",
        },
    )


@router.put("/admin/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdate, request: Request) -> Any:
    requester = await require_permission(request, "users")
    await _enforce_totp_step_up(requester, payload.totp_code, action_label="actualizar usuario")
    update = {k: v for k, v in payload.model_dump(exclude={"totp_code"}).items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Nada para actualizar")
    if requester.get("role") == "employee" and "role" in update and update["role"] in ("admin", "employee"):
        raise HTTPException(status_code=403, detail="Solo un admin puede asignar este rol")
    # iter55.16 — only admins can grant/revoke capabilities to other staff.
    if "allowed_permissions" in update:
        if requester.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Solo un admin puede modificar los permisos de staff")
        from services.permissions import sanitize_permissions
        update["allowed_permissions"] = sanitize_permissions(update["allowed_permissions"])
    old_user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    await db.users.update_one({"user_id": user_id}, {"$set": update})
    new_user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    await log_action(db, requester, "user.update", "user", user_id,
                     summary=f"Usuario {new_user.get('email', '')} actualizado",
                     details={"changes": update,
                              "prev_role": old_user.get("role") if old_user else None})
    return new_user


# iter55.16 — Permission catalog endpoint. Any staff can read the catalog to
# render the selector; only admins can modify user assignments (see PUT above).
@router.get("/admin/permissions/catalog")
async def get_permissions_catalog(request: Request) -> Any:
    await require_staff(request)
    from services.permissions import PERMISSION_CATALOG
    return {"items": PERMISSION_CATALOG}


@router.post("/admin/users/{user_id}/verify-email")
async def admin_verify_user_email(user_id: str, request: Request) -> Any:
    """Manually mark a user's email as verified. Requires staff role + 2FA step-up."""
    requester = await require_staff(request)
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    await _enforce_totp_step_up(requester, payload.get("totp_code"),
                                 action_label="verificar email manualmente")
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


# ============================================================
# iter52 — Balance ledger (admin variant — drill-down on any user)
# ============================================================

@router.get("/admin/users/{user_id}/balance-ledger")
async def admin_user_balance_ledger(user_id: str, request: Request) -> Any:
    """Admin/staff drill-down: list every `accumulate` order that contributed
    to this user's balance, grouped by destination currency. Useful to resolve
    disputes (e.g. "I sent Zelle twice but only one was credited")."""
    await require_staff(request)
    from routes.orders import _build_balance_ledger
    return await _build_balance_ledger(user_id)
