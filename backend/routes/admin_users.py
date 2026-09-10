"""Admin router — user management (list, update, manual email verification).

Extracted from routes/admin.py during the iter39 split.
"""
import re
import uuid
from datetime import timedelta
from typing import Dict, List, Literal, Optional, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import (require_staff, require_permission,
                        _enforce_totp_step_up, iso, now_utc,
                        strip_credential_fields)
from audit_log import log_action
from services.balances import build_rate_lookup, convert_to_usdt


router = APIRouter(tags=["Admin"])


class UserUpdate(BaseModel):
    role: Optional[Literal["normal", "vip", "employee", "admin"]] = None
    is_courier: Optional[bool] = None  # iter199 — courier panel access
    vip_balance_usd: Optional[float] = None
    vip_balances: Optional[Dict[str, float]] = None
    allowed_currencies: Optional[List[str]] = None
    allowed_permissions: Optional[List[str]] = None  # iter55.16 — capability-based access
    allowed_batch_pairs: Optional[List[str]] = None  # iter113 — VIP batch pair RBAC ("EUR->USDT")
    can_edit_product_prices: Optional[bool] = None
    can_upload_product_images: Optional[bool] = None
    can_delete_products: Optional[bool] = None
    can_manage_blocklist: Optional[bool] = None
    can_manage_company_funds: Optional[bool] = None  # iter54 — capital de trabajo
    account_status: Optional[Literal["active", "under_review", "blocked"]] = None
    # iter252 — registro de plantillas aplicadas: {id: {added_perms, prev_currencies,
    # set_currencies, currencies_changed, applied_at}} para revertir exactamente
    # lo que cada plantilla sumó sin tocar el resto.
    applied_templates: Optional[Dict[str, Any]] = None
    totp_code: Optional[str] = Field(None, max_length=11, description="Código 2FA requerido")


def _build_users_query(q: Optional[str], role: Optional[str]) -> Dict[str, Any]:
    """Compose the Mongo filter for GET /admin/users."""
    mongo_q: Dict[str, Any] = {}
    if q:
        # SEC-003 — escape user input so crafted patterns can't ReDoS Mongo.
        rx = {"$regex": re.escape(q), "$options": "i"}
        mongo_q["$or"] = [{"name": rx}, {"email": rx}]
    if role and role in ("normal", "vip", "employee", "admin"):
        mongo_q["role"] = role
    return mongo_q


async def _fetch_effective_kyc_map(user_ids: List[str]) -> Dict[str, str]:
    """iter106 — fetch the latest KYC status per user in a single aggregation.

    Mirrors the fallback logic used by `admin_user_stats`:
      - If a `kyc_verifications` doc exists, use its `status`.
      - Else caller falls back to `user.kyc_status` (or `not_started`).
      - `unverified` is normalized to `not_started` for UI consistency.
    """
    if not user_ids:
        return {}
    pipeline = [
        {"$match": {"user_id": {"$in": user_ids}}},
        {"$sort": {"created_at": -1}},
        {"$group": {"_id": "$user_id", "status": {"$first": "$status"}}},
    ]
    rows = await db.kyc_verifications.aggregate(pipeline).to_list(len(user_ids))
    out: Dict[str, str] = {}
    for r in rows:
        st = r.get("status") or ""
        out[r["_id"]] = "not_started" if st == "unverified" else st
    return out


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
    requester = await require_permission(request, "users")
    mongo_q = _build_users_query(q, role)
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    total = await db.users.count_documents(mongo_q)
    docs = await db.users.find(mongo_q, {"_id": 0}).sort("created_at", -1).skip(offset).to_list(limit)
    rates = await build_rate_lookup()
    kyc_map = await _fetch_effective_kyc_map([d["user_id"] for d in docs])
    for d in docs:
        # iter257(D01) — CRÍTICO: los campos de credenciales (hashes, tokens
        # de restablecimiento, secretos TOTP, códigos de recuperación) no
        # salen NUNCA, ni siquiera para administradores.
        strip_credential_fields(d)
        _enrich_user_with_usdt_total(d, rates)
        # iter106 — mirror the fallback used by /admin/users/:id/stats so the
        # list badge and the stats page stay in sync when Bug iter55.35 fixed.
        raw = kyc_map.get(d["user_id"]) or d.get("kyc_status") or "not_started"
        d["effective_kyc_status"] = "not_started" if raw == "unverified" else raw
    # iter55.33 — strip sensitive fields when the requester lacks the
    # `view_user_sensitive` permission. Kept as an additive filter so
    # existing admins and employees with allowed_permissions=[] keep the
    # legacy full view.
    from services.permissions import _has_permission
    if not _has_permission(requester, "view_user_sensitive"):
        for d in docs:
            # Wipe every field the operator explicitly listed as sensitive.
            for k in ("phone", "phone_verified_at", "vip_balances",
                      "vip_balance_usd", "vip_balance_usdt",
                      "allowed_currencies", "allowed_permissions",
                      "applied_templates", "market_perms"):
                d.pop(k, None)
    return JSONResponse(
        content=docs,
        headers={
            "X-Total-Count": str(total),
            "X-Offset": str(offset),
            "X-Limit": str(limit),
            "Access-Control-Expose-Headers": "X-Total-Count, X-Offset, X-Limit",
        },
    )


# SEC-001 (auditoría 28/7/2026) — balance & staff-capability fields are
# STRICTLY admin-only. A scoped employee (even with `user_functions`)
# must never mint spendable balance nor grant capability booleans.
ADMIN_ONLY_FIELDS = {
    "vip_balance_usd", "vip_balances",
    "can_edit_product_prices", "can_upload_product_images",
    "can_delete_products", "can_manage_blocklist",
    "can_manage_company_funds",
}
# iter55.33 — modifying "functions" fields requires the dedicated
# `user_functions` permission on top of the `users` gate.
FUNCTIONS_FIELDS = {"role", "allowed_currencies", "allowed_permissions",
                    "market_perms", "account_status", "allowed_batch_pairs",
                    "applied_templates"}


def _assert_user_update_authz(requester: dict, update: dict) -> None:
    """Gates de autorización del PUT /admin/users/{id} (solo lanza 403)."""
    from services.permissions import _has_permission
    touched_admin_only = sorted(ADMIN_ONLY_FIELDS & set(update))
    if touched_admin_only and requester.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail=("Solo un admin puede modificar saldos o capacidades de staff "
                    f"({', '.join(touched_admin_only)})."),
        )
    if any(k in update for k in FUNCTIONS_FIELDS) \
            and not _has_permission(requester, "user_functions"):
        raise HTTPException(
            status_code=403,
            detail=("Acceso restringido. Necesitas el permiso 'Funciones de usuario' "
                    "para modificar rol, permisos, monedas o accesos del marketplace."),
        )
    # iter202 — designar mensajeros requiere el permiso dedicado 'Mensajería'.
    if "is_courier" in update and not _has_permission(requester, "deliveries"):
        raise HTTPException(
            status_code=403,
            detail="Acceso restringido. Necesitas el permiso 'Mensajería' para designar mensajeros.",
        )
    if requester.get("role") == "employee" and update.get("role") in ("admin", "employee"):
        raise HTTPException(status_code=403, detail="Solo un admin puede asignar este rol")


def _clean_applied_templates(raw: Any) -> dict:
    """iter252 — saneado del registro de plantillas aplicadas."""
    raw = raw or {}
    if not isinstance(raw, dict) or len(raw) > 20:
        raise HTTPException(status_code=422, detail="applied_templates inválido")
    clean: dict = {}
    for tid, rec in raw.items():
        if not isinstance(rec, dict):
            continue
        clean[str(tid)[:40]] = {
            "added_perms": [str(p)[:60] for p in (rec.get("added_perms") or [])][:60],
            "prev_currencies": [str(c)[:20] for c in (rec.get("prev_currencies") or [])][:60],
            "set_currencies": [str(c)[:20] for c in (rec.get("set_currencies") or [])][:60],
            "currencies_changed": bool(rec.get("currencies_changed")),
            "applied_at": str(rec.get("applied_at") or "")[:40],
        }
    return clean


def _clean_batch_pairs(raw: Any) -> list:
    """iter113/iter202 — normaliza "FROM->TO"; sentinel "none" = sin acceso."""
    raw_pairs = [str(p).strip() for p in raw or []]
    if any(p.lower() == "none" for p in raw_pairs):
        return ["none"]
    clean_pairs: list = []
    for p in raw_pairs:
        p = p.upper().replace("→", "->")
        if re.match(r"^[A-Z0-9_]{1,16}->[A-Z0-9_]{1,16}$", p) and p not in clean_pairs:
            clean_pairs.append(p)
    return clean_pairs


def _sanitize_staff_grants(requester: dict, update: dict) -> None:
    """iter55.16/252/113 — los campos de concesiones de staff son admin-only
    y se normalizan in-place antes de persistir."""
    admin_only_msgs = {
        "allowed_permissions": "Solo un admin puede modificar los permisos de staff",
        "applied_templates": "Solo un admin puede modificar las plantillas de staff",
        "allowed_batch_pairs": "Solo un admin puede modificar los pares de lotes autorizados",
    }
    for field, msg in admin_only_msgs.items():
        if field in update and requester.get("role") != "admin":
            raise HTTPException(status_code=403, detail=msg)
    if "allowed_permissions" in update:
        from services.permissions import sanitize_permissions
        update["allowed_permissions"] = sanitize_permissions(update["allowed_permissions"])
    if "applied_templates" in update:
        update["applied_templates"] = _clean_applied_templates(update["applied_templates"])
    if "allowed_batch_pairs" in update:
        update["allowed_batch_pairs"] = _clean_batch_pairs(update["allowed_batch_pairs"])


@router.put("/admin/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdate, request: Request) -> Any:
    requester = await require_permission(request, "users")
    await _enforce_totp_step_up(requester, payload.totp_code, action_label="actualizar usuario")
    update = {k: v for k, v in payload.model_dump(exclude={"totp_code"}).items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Nada para actualizar")
    _assert_user_update_authz(requester, update)
    _sanitize_staff_grants(requester, update)
    old_user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    await db.users.update_one({"user_id": user_id}, {"$set": update})
    new_user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    await log_action(db, requester, "user.update", "user", user_id,
                     summary=f"Usuario {new_user.get('email', '')} actualizado",
                     details={"changes": update,
                              "prev_role": old_user.get("role") if old_user else None,
                              "balance_edit": any(k in update for k in ("vip_balance_usd", "vip_balances"))})
    return strip_credential_fields(new_user)


# iter55.16 — Permission catalog endpoint. Any staff can read the catalog to
# render the selector; only admins can modify user assignments (see PUT above).
@router.get("/admin/permissions/catalog")
async def get_permissions_catalog(request: Request) -> Any:
    await require_staff(request)
    from services.permissions import PERMISSION_CATALOG
    return {"items": PERMISSION_CATALOG}


@router.post("/admin/users/{user_id}/verify-email")
async def admin_verify_user_email(user_id: str, request: Request) -> Any:
    """Manually mark a user's email as verified. Requires the `users`
    permission + 2FA step-up (iter260/E01 — antes bastaba cualquier staff)."""
    requester = await require_permission(request, "users")
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    await _enforce_totp_step_up(requester, payload.get("totp_code"),
                                 action_label="verificar email manualmente")
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target.get("email_verified"):
        # iter260(E01) — NUNCA devolver credenciales en respuestas anidadas.
        return {"ok": True, "already_verified": True,
                "user": strip_credential_fields(target)}
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"email_verified": True},
         "$unset": {"verification_token": "", "verification_expires_at": ""}},
    )
    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    await log_action(db, requester, "user.verify_email_manual", "user", user_id,
                     summary=f"Email verificado manualmente para {target.get('email', '')}",
                     details={"email": target.get("email")})
    return {"ok": True, "already_verified": False,
            "user": strip_credential_fields(fresh)}


@router.get("/admin/email-health")
async def admin_email_health(request: Request) -> Any:
    """iter197 — one-glance diagnosis of the email subsystem for THIS server.
    Answers 'why are no emails arriving?' directly from the admin UI:
    is real sending enabled, is the Resend key present, and what did the
    last 7 days of delivery attempts look like."""
    await require_staff(request)
    import email_service
    week_ago = iso(now_utc() - timedelta(days=7))
    rows = await db.email_events.aggregate([
        {"$match": {"created_at": {"$gte": week_ago}}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]).to_list(10)
    counts = {r["_id"]: r["n"] for r in rows}
    last = await db.email_events.find_one(
        {}, {"_id": 0, "created_at": 1, "status": 1},
        sort=[("created_at", -1)],
    )
    return {
        "send_enabled": email_service.EMAIL_SEND_ENABLED,
        "api_key_set": bool(email_service.resend.api_key),
        "sender": email_service.SENDER,
        "counts_7d": {
            "sent": counts.get("sent", 0),
            "failed": counts.get("failed", 0),
            "suppressed": counts.get("suppressed", 0),
        },
        "last_event_at": (last or {}).get("created_at"),
        "last_event_status": (last or {}).get("status"),
    }


@router.get("/admin/users/{user_id}/email-events")
async def admin_user_email_events(user_id: str, request: Request,
                                  limit: int = 10) -> Any:
    """iter147 — delivery ledger for support: what emails did we (try to)
    send this user and did the provider accept them?"""
    await require_staff(request)
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    events = await db.email_events.find(
        {"to": (target.get("email") or "").lower().strip()},
        {"_id": 0, "id": 1, "subject": 1, "kind": 1, "status": 1, "error": 1,
         "attempts": 1, "created_at": 1,
         "html_body": 1},  # iter196 — presence-only signal; stripped below
    ).sort("created_at", -1).to_list(max(1, min(limit, 50)))
    # iter196 — surface a boolean the UI can key off (`can_resend`) without
    # shipping the full HTML body (5-20KB per row) on every list call.
    for e in events:
        e["can_resend"] = bool(e.pop("html_body", None))
    return {"email": target.get("email"), "events": events}


@router.post("/admin/email-events/{event_id}/resend")
async def admin_resend_email_event(event_id: str, request: Request) -> Any:
    """iter196 — 1-click resend of any historical email that still has its
    rendered HTML persisted. Staff-only. Records a new `email_events` row
    with a `retried_from` reference so the ledger keeps the causal chain."""
    requester = await require_staff(request)
    ev = await db.email_events.find_one({"id": event_id}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Email no encontrado")

    from email_service import resend_email_event
    ok, msg = resend_email_event(ev)

    # Chain the fresh row to the original so support can see the retry
    # provenance (the new row was written by _send inside resend_email_event).
    if ok or msg:  # a new row exists whenever resend attempted (sent | failed)
        await db.email_events.find_one_and_update(
            {"to": ev["to"], "subject": ev["subject"], "id": {"$ne": event_id},
             "retried_from": {"$exists": False}},
            {"$set": {"retried_from": event_id}},
            sort=[("created_at", -1)],
        )

    await log_action(
        db=db, actor=requester, action="RESEND_EMAIL",
        entity_type="email_event", entity_id=event_id,
        details={"to": ev.get("to"), "subject": ev.get("subject"),
                 "ok": ok, "message": msg},
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.post("/admin/users/{user_id}/resend-verification")
async def admin_resend_verification(user_id: str, request: Request) -> Any:
    """iter147 — staff-triggered resend of the verification email (support
    flow for 'no me llegó el correo'). 60s cooldown shared with the
    user-initiated resend."""
    requester = await require_staff(request)
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target.get("auth_provider") != "password":
        raise HTTPException(status_code=400,
                            detail="Este usuario no usa login con contraseña.")
    if target.get("email_verified"):
        raise HTTPException(status_code=400, detail="El email ya está verificado.")
    last_resend = target.get("last_resend_at")
    if last_resend:
        try:
            from datetime import datetime as _dt
            elapsed = (now_utc() - _dt.fromisoformat(
                last_resend.replace("Z", "+00:00"))).total_seconds()
            if elapsed < 60:
                raise HTTPException(
                    status_code=429,
                    detail=f"Espera {int(60 - elapsed)}s antes de reenviar.",
                )
        except HTTPException:
            raise
        except Exception:
            pass
    new_token = uuid.uuid4().hex + uuid.uuid4().hex
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "verification_token": new_token,
            "verification_expires_at": iso(now_utc() + timedelta(hours=24)),
            "last_resend_at": iso(now_utc()),
        }},
    )
    import email_service
    sent = email_service.notify_email_verification(
        target.get("email", ""), target.get("name", ""), new_token,
        lang=target.get("preferred_language") or "es",
    )
    await log_action(db, requester, "user.resend_verification", "user", user_id,
                     summary=f"Reenvío de verificación a {target.get('email', '')} "
                             f"({'aceptado' if sent else 'FALLÓ'})",
                     details={"email": target.get("email"), "sent": sent})
    return {"ok": True, "sent": sent}


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


@router.get("/admin/users/{user_id}/audit-trail")
async def admin_user_audit_trail(user_id: str, request: Request,
                                    days: int = 30, limit: int = 200) -> Any:
    """iter55.34 — chronological trail of staff actions targeting this user.

    Sources searched (in one query, deduped by id):
      1. `entity_type='user' AND entity_id=user_id` (direct edits: role,
         perms, currencies, verify-email, phone approve/reject, etc.)
      2. `details.user_id=user_id` (capital-request approvals/rejections
         and other actions where the user is the affected party but not
         the primary entity).

    Filtering:
      - `days` clamps the window (max 365 to keep the query cheap).
      - `limit` clamps the result set (max 500).

    Access: gated by the `user_stats` permission (same as the enclosing
    stats page) so operators don't need a separate grant.
    """
    await require_permission(request, "user_stats")
    if not await db.users.find_one({"user_id": user_id}, {"user_id": 1, "_id": 0}):
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    days = max(1, min(int(days or 30), 365))
    limit = max(1, min(int(limit or 200), 500))
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    query = {
        "created_at": {"$gte": cutoff},
        "$or": [
            {"entity_type": "user", "entity_id": user_id},
            {"details.user_id": user_id},
        ],
    }
    cursor = db.audit_log.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
    entries = await cursor.to_list(limit)
    return {
        "user_id": user_id,
        "window_days": days,
        "total": len(entries),
        "entries": entries,
    }


async def _order_stats_30d(user_id: str, rates: Any) -> tuple[List[dict], float]:
    """Approved/completed orders in the last 30 days + their USDT-eq volume."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    orders_30d = await db.orders.find(
        {"user_id": user_id, "created_at": {"$gte": cutoff},
         "status": {"$in": ["approved", "completed"]}},
        {"_id": 0, "amount_from": 1, "from_code": 1, "amount_to": 1, "to_code": 1},
    ).to_list(2000)
    volume = 0.0
    for o in orders_30d:
        u = convert_to_usdt(float(o.get("amount_from") or 0), o.get("from_code", ""), rates)
        if u:
            volume += u
    return orders_30d, volume


async def _active_debts_summary(user_id: str) -> tuple[List[dict], Dict[str, float]]:
    """Disbursed capital requests + remaining debt grouped by currency."""
    active_debts = await db.capital_requests.find(
        {"user_id": user_id, "status": "disbursed"}, {"_id": 0},
    ).sort("disbursed_at", 1).to_list(500)
    total: Dict[str, float] = {}
    for d in active_debts:
        code = d["currency_code"]
        total[code] = total.get(code, 0.0) + float(d.get("debt_remaining") or 0.0)
    return active_debts, total


def _effective_balances(user: dict) -> Dict[str, float]:
    """vip_balances merged with the legacy single-currency USD balance."""
    balances = dict(user.get("vip_balances") or {})
    legacy = float(user.get("vip_balance_usd") or 0.0)
    if legacy:
        balances["USD"] = balances.get("USD", 0.0) + legacy
    return balances


def _sum_usdt(amount_by_code: Dict[str, float], rates: Any) -> float:
    total = 0.0
    for code, amount in amount_by_code.items():
        u = convert_to_usdt(float(amount or 0), code, rates)
        if u:
            total += u
    return total


async def _favorite_currencies(user_id: str) -> tuple[List[dict], Optional[str], int]:
    """Top-5 currency codes by lifetime order count (from_code + to_code)."""
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$project": {"codes": ["$from_code", "$to_code"]}},
        {"$unwind": "$codes"},
        {"$match": {"codes": {"$ne": None}}},
        {"$group": {"_id": "$codes", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    top_codes = await db.orders.aggregate(pipeline).to_list(5)
    if not top_codes:
        return [], None, 0
    return top_codes, top_codes[0]["_id"], top_codes[0]["count"]


async def _kyc_snapshot(user_id: str, user: dict) -> Dict[str, str]:
    kyc_doc = await db.kyc_verifications.find_one(
        {"user_id": user_id}, {"_id": 0},
        sort=[("created_at", -1)],
    ) or {}
    status = kyc_doc.get("status") or user.get("kyc_status") or "not_started"
    if status == "unverified":
        status = "not_started"
    return {
        "status": status,
        "submitted_at": kyc_doc.get("created_at", ""),
        "reviewed_at": kyc_doc.get("reviewed_at", ""),
        "reviewer_notes": kyc_doc.get("review_notes", ""),
    }


@router.get("/admin/users/{user_id}/stats")
async def admin_user_stats(user_id: str, request: Request) -> Any:
    """iter55.32 — aggregated per-user dashboard used by the new
    `/admin/users/:id/stats` frontend page. Returns:
      - user identity (name, email, role, status, created_at)
      - vip_balances breakdown + total in USDT
      - order stats (total lifetime, last 30d volume, count)
      - active capital debts summary
      - net platform ⇄ client position (positive = platform owes client)
      - most-used currency (iter55.33)
      - success rate % (iter55.33)
      - KYC status snapshot (iter55.33)

    iter55.33 — gated behind the `user_stats` permission. Staff without it
    receive a 403 Spanish message they can surface to the operator so the
    admin can grant the permission.
    """
    await require_permission(request, "user_stats")
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    rates = await build_rate_lookup()
    _enrich_user_with_usdt_total(user, rates)

    total_orders = await db.orders.count_documents({"user_id": user_id})
    orders_30d, volume_30d_usdt = await _order_stats_30d(user_id, rates)
    active_debts, total_debt_by_currency = await _active_debts_summary(user_id)

    balances = _effective_balances(user)
    platform_owes_usdt = _sum_usdt(balances, rates)
    client_owes_usdt = _sum_usdt(total_debt_by_currency, rates)
    net_usdt = round(platform_owes_usdt - client_owes_usdt, 4)

    completed_orders = await db.orders.count_documents(
        {"user_id": user_id, "status": {"$in": ["approved", "completed"]}},
    )
    success_rate = round((completed_orders / total_orders) * 100, 1) if total_orders else 0.0

    top_codes, favorite_currency, favorite_currency_count = await _favorite_currencies(user_id)

    kyc = await _kyc_snapshot(user_id, user)

    return {
        "user": {
            "user_id": user["user_id"],
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "email_verified": bool(user.get("email_verified", False)),
            "role": user.get("role", ""),
            "account_status": user.get("account_status", "active"),
            "phone": user.get("phone", ""),
            "phone_verified": bool(user.get("phone_verified")),
            "created_at": user.get("created_at", ""),
            "twofa_enabled": bool(user.get("totp_enabled", False)),
        },
        "kyc": kyc,
        "balances": {k: round(float(v), 4) for k, v in balances.items() if float(v) != 0},
        "balance_total_usdt": user.get("vip_balance_usdt", 0.0),
        "orders": {
            "total_lifetime": total_orders,
            "count_last_30d": len(orders_30d),
            "volume_last_30d_usdt": round(volume_30d_usdt, 4),
            "success_count": completed_orders,
            "success_rate_pct": success_rate,
            "favorite_currency": favorite_currency,
            "favorite_currency_count": favorite_currency_count,
            "top_currencies": [{"code": c["_id"], "count": c["count"]} for c in top_codes],
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
