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


def _build_users_query(q: Optional[str], role: Optional[str]) -> Dict[str, Any]:
    """Compose the Mongo filter for GET /admin/users."""
    mongo_q: Dict[str, Any] = {}
    if q:
        rx = {"$regex": q, "$options": "i"}
        mongo_q["$or"] = [{"name": rx}, {"email": rx}]
    if role and role in ("normal", "vip", "employee", "admin"):
        mongo_q["role"] = role
    return mongo_q


def _enrich_user_with_usdt_total(user_doc: dict, rates: dict) -> None:
    """Iter47 enrichment — attaches `vip_balance_usdt` to any non-staff user
    by summing every currency in `vip_balances` (plus the legacy USD balance)
    converted to USDT via the shared rates snapshot. Mutates in place."""
    if user_doc.get("role") not in ("normal", "vip"):
        return
    bals: Dict[str, float] = dict(user_doc.get("vip_balances") or {})
    legacy = float(user_doc.get("vip_balance_usd") or 0.0)
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
    user_doc["vip_balance_usdt"] = round(total_usdt, 4)


@router.get("/admin/users")
async def list_users(request: Request, q: Optional[str] = None,
                     role: Optional[str] = None,
                     limit: int = 1000, offset: int = 0) -> Any:
    await require_permission(request, "users")
    mongo_q = _build_users_query(q, role)
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    total = await db.users.count_documents(mongo_q)
    docs = await db.users.find(mongo_q, {"_id": 0}).sort("created_at", -1).skip(offset).to_list(limit)
    rates = await build_rate_lookup()
    for d in docs:
        _enrich_user_with_usdt_total(d, rates)
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


@router.get("/admin/users/{user_id}/stats")
async def admin_user_stats(user_id: str, request: Request) -> Any:
    """iter55.32 — aggregated per-user dashboard used by the new
    `/admin/users/:id/stats` frontend page. Returns:
      - user identity (name, email, role, status, created_at)
      - vip_balances breakdown + total in USDT
      - order stats (total lifetime, last 30d volume, count)
      - active capital debts summary
      - net platform ⇄ client position (positive = platform owes client)
    """
    await require_staff(request)
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    rates = await build_rate_lookup()
    _enrich_user_with_usdt_total(user, rates)

    # Order counts + volume (last 30d)
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    total_orders = await db.orders.count_documents({"user_id": user_id})
    orders_30d_cursor = db.orders.find(
        {"user_id": user_id, "created_at": {"$gte": cutoff},
         "status": {"$in": ["approved", "completed"]}},
        {"_id": 0, "amount_from": 1, "from_code": 1, "amount_to": 1, "to_code": 1},
    )
    orders_30d = await orders_30d_cursor.to_list(2000)
    volume_30d_usdt = 0.0
    for o in orders_30d:
        u = convert_to_usdt(float(o.get("amount_from") or 0), o.get("from_code", ""), rates)
        if u:
            volume_30d_usdt += u

    # Active capital requests + total debt
    active_debts_cursor = db.capital_requests.find(
        {"user_id": user_id, "status": "disbursed"}, {"_id": 0},
    ).sort("disbursed_at", 1)
    active_debts = await active_debts_cursor.to_list(500)
    total_debt_by_currency: Dict[str, float] = {}
    for d in active_debts:
        code = d["currency_code"]
        total_debt_by_currency[code] = total_debt_by_currency.get(code, 0.0) + float(d.get("debt_remaining") or 0.0)

    # Net position: platform_owes_client = sum(vip_balances[c] * rate_to_usdt)
    # client_owes_platform = sum(debt_remaining[c] * rate_to_usdt)
    balances = dict(user.get("vip_balances") or {})
    legacy = float(user.get("vip_balance_usd") or 0.0)
    if legacy:
        balances["USD"] = balances.get("USD", 0.0) + legacy
    platform_owes_usdt = 0.0
    for code, amount in balances.items():
        u = convert_to_usdt(float(amount or 0), code, rates)
        if u:
            platform_owes_usdt += u
    client_owes_usdt = 0.0
    for code, amount in total_debt_by_currency.items():
        u = convert_to_usdt(amount, code, rates)
        if u:
            client_owes_usdt += u
    net_usdt = round(platform_owes_usdt - client_owes_usdt, 4)

    return {
        "user": {
            "user_id": user["user_id"],
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "role": user.get("role", ""),
            "account_status": user.get("account_status", "active"),
            "phone": user.get("phone", ""),
            "created_at": user.get("created_at", ""),
        },
        "balances": {k: round(float(v), 4) for k, v in balances.items() if float(v) != 0},
        "balance_total_usdt": user.get("vip_balance_usdt", 0.0),
        "orders": {
            "total_lifetime": total_orders,
            "count_last_30d": len(orders_30d),
            "volume_last_30d_usdt": round(volume_30d_usdt, 4),
        },
        "capital": {
            "active_requests": active_debts,
            "debt_by_currency": {k: round(v, 4) for k, v in total_debt_by_currency.items()},
            "total_debt_usdt": round(client_owes_usdt, 4),
        },
        "net_position": {
            "platform_owes_client_usdt": round(platform_owes_usdt, 4),
            "client_owes_platform_usdt": round(client_owes_usdt, 4),
            "net_usdt": net_usdt,
            "direction": (
                "platform_owes_client" if net_usdt > 0.01
                else "client_owes_platform" if net_usdt < -0.01
                else "even"
            ),
        },
    }
