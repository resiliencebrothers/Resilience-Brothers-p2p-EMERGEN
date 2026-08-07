"""Client deposits — deposit assets into the on-platform per-currency balance.

Business rules (owner, 30 Jul 2026):
  - Deposits credit the SAME currency deposited (no conversion) once staff
    confirms the money was received. Conversion happens via the converter or
    VIP batch pairs.
  - Allowed methods derive from the currency's delivery methods (same source
    of truth as withdrawals): transfer → proof + account holder required;
    crypto → tx hash required; cash → two sub-modes:
      * courier: only for amounts > COURIER_MIN_USDT (USDT equivalent) —
        requires pickup address + phone + contact name of the person handing
        over the money.
      * office: any amount — the client brings the cash to the company
        offices (address configurable via settings.global.office_address).

Collection `deposits`:
  { id, user_id, user_email, user_name, user_role,
    currency, amount, method, cash_mode?, usdt_equivalent?,
    account_holder?, tx_hash?, proof_url?,
    pickup_address?, pickup_phone?, contact_name?, note?,
    status: pending|confirmed|rejected,
    admin_note?, reviewed_at?, reviewed_by?, created_at, updated_at }
"""
from __future__ import annotations

import re
import uuid
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import require_user, require_permission, iso, now_utc
from audit_log import log_action
from services.balances import (
    build_rate_lookup, convert_to_usdt,
    assert_account_active, assert_not_defensive,
)
from services.delivery_rules import allowed_delivery_methods
from services.proof_upload import maybe_upload_proof

logger = logging.getLogger("deposits")

router = APIRouter(tags=["Deposits"])

COURIER_MIN_USDT = 1000.0
ALLOWED_METHODS = {"transfer", "crypto", "cash"}


class DepositCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    currency: str = Field(..., min_length=1, max_length=16)
    amount: float = Field(..., gt=0, le=10_000_000)
    method: str = Field(..., min_length=2, max_length=16)
    account_holder: Optional[str] = Field(default=None, max_length=120)
    tx_hash: Optional[str] = Field(default=None, max_length=200)
    network: Optional[str] = Field(default=None, max_length=16)
    proof_image: Optional[str] = None
    pickup_address: Optional[str] = Field(default=None, max_length=300)
    pickup_phone: Optional[str] = Field(default=None, max_length=40)
    contact_name: Optional[str] = Field(default=None, max_length=120)
    note: Optional[str] = Field(default=None, max_length=300)


class RejectPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    admin_note: str = Field(default="", max_length=300)


def _require_client(user: dict) -> None:
    if user.get("role") == "employee":
        raise HTTPException(status_code=403, detail="Empleados no pueden depositar saldo de cliente.")


async def _get_office_address() -> str:
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0, "office_address": 1})
    return (doc or {}).get("office_address") or ""


async def _notify_staff_new_deposit(doc: dict) -> None:
    try:
        from routes.notifications import _insert_notification
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] notif import failed: {e}")
        return
    cursor = db.users.find(
        {"$or": [
            {"role": "admin"},
            {"role": "employee", "allowed_permissions": "withdrawals"},
            {"role": "employee", "allowed_permissions": {"$in": [[], None]}},
        ]},
        {"_id": 0, "user_id": 1},
    )
    async for r in cursor:
        try:
            await _insert_notification(
                recipient_user_id=r["user_id"],
                type="new_deposit",
                title="Nuevo depósito de cliente",
                message=f"{doc.get('user_name') or doc.get('user_email')} depositó {doc['amount']} {doc['currency']} ({doc['method']}).",
                data={"id": doc["id"], "user_id": doc["user_id"]},
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[deposits] staff notify failed: {e}")


async def _notify_client_decision(doc: dict, approved: bool, admin_note: str = "") -> None:
    """iter156 — in-app + Web Push to the deposit owner, localised to their
    preferred language. Rejections include the staff note as the reason."""
    try:
        from routes.notifications import _insert_notification
        from push_service import send_push_to_user, build_deposit_decision_payload
        from services.notification_i18n import t as _t, resolve_lang
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] notif import failed: {e}")
        return
    key = "deposit_confirmed" if approved else "deposit_rejected"
    try:
        lang = await resolve_lang(db, doc["user_id"])
        note = (admin_note or "").strip()
        if note:
            reason = f" Reason: {note}." if lang == "en" else f" Motivo: {note}."
        else:
            reason = ""
        await _insert_notification(
            recipient_user_id=doc["user_id"],
            type=key,
            title=_t(key, lang, "title"),
            message=_t(key, lang, "message",
                       amt=doc["amount"], code=doc["currency"], reason=reason),
            data={"id": doc["id"], "amount": doc["amount"],
                  "currency": doc["currency"]},
        )
        await send_push_to_user(
            db, doc["user_id"],
            build_deposit_decision_payload(doc, approved, lang=lang),
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] client notify failed: {e}")


@router.get("/deposits/config")
async def deposits_config(request: Request) -> Any:
    """Depositable currencies + their allowed methods + cash rules."""
    user = await require_user(request)
    _require_client(user)
    currencies = await db.currencies.find({}, {"_id": 0}).to_list(500)
    rates = await build_rate_lookup()
    items = []
    seen: set = set()
    for c in currencies:
        if c.get("is_active") is False:
            continue
        code = (c.get("code") or "").strip().upper()
        if not code or code in seen:
            continue
        methods = allowed_delivery_methods(c)
        if not methods:
            continue
        seen.add(code)
        per_unit = convert_to_usdt(1.0, code, rates)
        items.append({
            "code": code,
            "name": (c.get("name") or code).strip(),
            "type": c.get("type") or "",
            "methods": methods,
            "usdt_per_unit": round(float(per_unit), 6) if per_unit else None,
        })
    items.sort(key=lambda x: (x["code"] != "USDT", x["code"]))
    return {
        "currencies": items,
        "courier_min_usdt": COURIER_MIN_USDT,
        "office_address": await _get_office_address(),
    }


@router.post("/deposits")
async def create_deposit(payload: DepositCreate, request: Request) -> Any:
    user = await require_user(request)
    _require_client(user)
    await assert_account_active(user)
    if user["role"] != "admin":
        await assert_not_defensive("depósitos")

    code = payload.currency.strip().upper()
    currency = await db.currencies.find_one(
        {"code": code, "is_active": {"$ne": False}}, {"_id": 0},
    )
    if not currency:
        raise HTTPException(status_code=422, detail=f"Moneda {code} no disponible para depósitos.")
    method = payload.method.strip().lower()
    allowed = allowed_delivery_methods(currency)
    if method not in ALLOWED_METHODS or method not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Para depositar {code} usa: {', '.join(allowed)}.",
        )

    holder = (payload.account_holder or "").strip()
    tx_hash = (payload.tx_hash or "").strip()
    network = (payload.network or "").strip().upper() or None
    proof_raw = (payload.proof_image or "").strip()
    cash_mode = None

    rates = await build_rate_lookup()
    usdt_eq = convert_to_usdt(float(payload.amount), code, rates)
    usdt_eq = round(float(usdt_eq), 4) if usdt_eq is not None else None

    if method == "transfer":
        if not proof_raw:
            raise HTTPException(status_code=422, detail="Adjunta la captura de la transferencia realizada.")
        if len(holder) < 3:
            raise HTTPException(status_code=422, detail="Indica el titular de la cuenta que envió la transferencia.")
    elif method == "crypto":
        if len(tx_hash) < 10:
            raise HTTPException(status_code=422, detail="Indica el hash de la transacción on-chain.")
        from services.crypto_networks import (
            SUPPORTED_NETWORKS, is_supported_network,
            is_tx_hash_valid_for_network, tx_hash_mismatch_reason,
        )
        if network and not is_supported_network(network):
            raise HTTPException(
                status_code=422,
                detail=f"Red no soportada. Usa: {', '.join(SUPPORTED_NETWORKS)}.",
            )
        if network and not is_tx_hash_valid_for_network(tx_hash, network):
            raise HTTPException(status_code=422,
                                detail=tx_hash_mismatch_reason(tx_hash, network))
    else:  # cash
        if usdt_eq is not None and usdt_eq > COURIER_MIN_USDT:
            cash_mode = "courier"
            if len((payload.pickup_address or "").strip()) < 5:
                raise HTTPException(status_code=422, detail="Indica la dirección de recogida del efectivo.")
            if len((payload.pickup_phone or "").strip()) < 6:
                raise HTTPException(status_code=422, detail="Indica el celular de la persona que entrega el dinero.")
            if len((payload.contact_name or "").strip()) < 3:
                raise HTTPException(status_code=422, detail="Indica el nombre de la persona que entrega el dinero.")
        else:
            cash_mode = "office"

    proof_ref = maybe_upload_proof(proof_raw, "deposits") if proof_raw else None
    now = iso(now_utc())
    doc = {
        "id": f"dep_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "user_email": user.get("email", ""),
        "user_name": user.get("name", ""),
        "user_role": user.get("role", ""),
        "currency": code,
        "amount": round(float(payload.amount), 2),
        "method": method,
        "cash_mode": cash_mode,
        "network": network if method == "crypto" else None,
        "usdt_equivalent": usdt_eq,
        "account_holder": holder or None,
        "tx_hash": tx_hash or None,
        "proof_url": proof_ref,
        "pickup_address": (payload.pickup_address or "").strip() or None,
        "pickup_phone": (payload.pickup_phone or "").strip() or None,
        "contact_name": (payload.contact_name or "").strip() or None,
        "note": (payload.note or "").strip() or None,
        "status": "pending",
        "admin_note": None,
        "reviewed_at": None,
        "reviewed_by": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.deposits.insert_one(dict(doc))
    doc.pop("_id", None)
    await log_action(
        db=db, actor=user, action="deposit.create",
        entity_type="deposit", entity_id=doc["id"],
        details={"amount": doc["amount"], "currency": code, "method": method,
                 "cash_mode": cash_mode},
    )
    await _notify_staff_new_deposit(doc)
    try:
        from services.live_bus import publish as live_publish
        await live_publish("deposit_created", {"id": doc["id"], "user_name": doc["user_name"],
                                                "amount": doc["amount"], "currency": code},
                           roles=("admin", "employee"))
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] SSE publish failed: {e}")
    return doc


@router.get("/deposits/mine")
async def my_deposits(request: Request, limit: int = 50) -> Any:
    user = await require_user(request)
    _require_client(user)
    rows = await db.deposits.find(
        {"user_id": user["user_id"]}, {"_id": 0},
    ).sort("created_at", -1).to_list(min(max(1, limit), 200))
    return {"items": rows}


@router.get("/admin/deposits")
async def admin_list_deposits(request: Request, status: Optional[str] = None,
                               method: Optional[str] = None,
                               user_q: Optional[str] = None,
                               limit: int = 200) -> Any:
    # iter163 — deposits moved from the `orders` gate to `withdrawals` so the
    # designated money-in/money-out staff handles both flows.
    await require_permission(request, "withdrawals")
    q: dict[str, Any] = {}
    if status in ("pending", "confirmed", "rejected"):
        q["status"] = status
    # iter164 — method filter (cash / transfer / crypto) to speed up review.
    if method in ALLOWED_METHODS:
        q["method"] = method
    # iter165 — client search by name or email (same UX as withdrawals).
    if user_q:
        rx = {"$regex": re.escape(user_q.strip()), "$options": "i"}
        q["$or"] = [{"user_name": rx}, {"user_email": rx}]
    rows = await db.deposits.find(q, {"_id": 0}).sort("created_at", -1).to_list(min(max(1, limit), 500))
    pending = await db.deposits.count_documents({"status": "pending"})
    return {"items": rows, "pending": pending}


@router.get("/admin/deposits-hub/pending-count")
async def admin_deposits_hub_pending_count(request: Request) -> Any:
    """iter163 — badges for the Deposits & Withdrawals hub tabs.
    iter166 — capital deposits retired; capital REQUESTS joined the hub."""
    await require_permission(request, "withdrawals")
    deposits_pending = await db.deposits.count_documents({"status": "pending"})
    requests_pending = await db.capital_requests.count_documents({"status": "pending"})
    withdrawals_pending = await db.withdrawals.count_documents({"status": "pending"})
    return {
        "deposits_pending": deposits_pending,
        "requests_pending": requests_pending,
        "withdrawals_pending": withdrawals_pending,
    }


@router.post("/admin/deposits/{dep_id}/confirm")
async def admin_confirm_deposit(dep_id: str, request: Request) -> Any:
    staff = await require_permission(request, "withdrawals")
    doc = await db.deposits.find_one({"id": dep_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Depósito no encontrado.")
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail="Este depósito ya fue procesado.")
    now = iso(now_utc())
    # Idempotency: flip status first so a double-click can't double-credit.
    res = await db.deposits.update_one(
        {"id": dep_id, "status": "pending"},
        {"$set": {"status": "confirmed", "updated_at": now,
                  "reviewed_at": now, "reviewed_by": staff["user_id"]}},
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Este depósito ya fue procesado.")
    await db.users.update_one(
        {"user_id": doc["user_id"]},
        {"$inc": {f"vip_balances.{doc['currency']}": float(doc["amount"])}},
    )
    fresh = await db.deposits.find_one({"id": dep_id}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="deposit.confirm",
        entity_type="deposit", entity_id=dep_id,
        details={"user_id": doc["user_id"], "amount": doc["amount"],
                 "currency": doc["currency"]},
    )
    await _notify_client_decision(fresh, approved=True)
    try:
        from services.live_bus import publish as live_publish
        await live_publish("balance_updated", {"reason": "deposit", "deposit_id": dep_id},
                           user_id=doc["user_id"])
        await live_publish("ledger_changed",
                           {"reason": "deposit", "deposit_id": dep_id,
                            "user_id": doc["user_id"]},
                           roles=("admin", "employee"))
    except Exception as e:  # noqa: BLE001
        logger.error(f"[deposits] SSE publish failed: {e}")
    return fresh


@router.post("/admin/deposits/{dep_id}/reject")
async def admin_reject_deposit(dep_id: str, payload: RejectPayload, request: Request) -> Any:
    staff = await require_permission(request, "withdrawals")
    doc = await db.deposits.find_one({"id": dep_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Depósito no encontrado.")
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail="Este depósito ya fue procesado.")
    now = iso(now_utc())
    await db.deposits.update_one(
        {"id": dep_id},
        {"$set": {"status": "rejected", "updated_at": now, "reviewed_at": now,
                  "reviewed_by": staff["user_id"],
                  "admin_note": payload.admin_note.strip() or None}},
    )
    fresh = await db.deposits.find_one({"id": dep_id}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="deposit.reject",
        entity_type="deposit", entity_id=dep_id,
        details={"user_id": doc["user_id"], "note": payload.admin_note.strip()},
    )
    await _notify_client_decision(fresh, approved=False, admin_note=payload.admin_note.strip())
    return fresh
