"""iter55.32 — VIP capital request flow.

Operator ask (12 Feb 2026): allow VIPs to formally request working capital
from the platform's own funds ("solicitud de fondos"). When approved and
disbursed, the amount is credited to the VIP's balance and tracked as a
DEBT that is auto-repaid by deducting a configurable percentage from every
accumulated order the VIP subsequently completes.

Data model — one collection: `capital_requests`
    {
      id, user_id, user_email, user_name, role,
      amount, currency_code, reason, estimated_return_date,
      status: pending|approved|disbursed|rejected|paid_off,
      created_at, updated_at,
      # admin decisions
      reviewed_by, reviewed_at, admin_notes, reject_reason,
      # disbursement + auto-discount
      disbursed_at, discount_pct, debt_original, debt_remaining,
      paid_off_at, repayment_events: [{order_id, amount, at}]
    }

Endpoints:
    POST /api/vip/capital-requests          (VIP creates, status=pending)
    GET  /api/vip/capital-requests          (VIP lists own)
    GET  /api/admin/capital-requests        (admin/staff w/ company_funds perm)
    POST /api/admin/capital-requests/{id}/approve
    POST /api/admin/capital-requests/{id}/reject

Auto-discount hook lives in `services/balances.py::_credit_accumulated_order`
so every path that credits an accumulated order (P2P confirm, direct
"Completar", legacy backfill) automatically pays down the debt.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import require_user, require_permission, _enforce_totp_step_up, iso, now_utc
from audit_log import log_action

logger = logging.getLogger("capital_requests")

router = APIRouter(tags=["Capital Requests"])


# ============================================================
# Payloads
# ============================================================

class CapitalRequestCreate(BaseModel):
    """VIP-facing payload."""
    model_config = ConfigDict(extra="ignore")
    amount: float = Field(..., gt=0, le=1_000_000)
    currency_code: str = Field(..., min_length=2, max_length=12)
    reason: str = Field(..., min_length=8, max_length=500)
    estimated_return_date: Optional[str] = Field(default=None, max_length=32)


class CapitalRequestApprove(BaseModel):
    """Admin-facing payload — sets the auto-discount % applied to every
    future accumulated order until the debt is paid off."""
    model_config = ConfigDict(extra="ignore")
    discount_pct: float = Field(..., ge=1.0, le=100.0)
    admin_notes: str = Field(default="", max_length=500)
    totp_code: Optional[str] = Field(default=None, max_length=11)


class CapitalRequestReject(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reject_reason: str = Field(..., min_length=5, max_length=500)
    totp_code: Optional[str] = Field(default=None, max_length=11)


# ============================================================
# Helpers
# ============================================================

def _serialize(doc: dict) -> dict:
    """Strip the Mongo `_id`; everything else is already JSON-serializable."""
    d = dict(doc)
    d.pop("_id", None)
    return d


async def _ensure_currency_active(code: str) -> dict:
    """Reject if the currency doesn't exist or is deactivated. Returns the
    currency doc for name lookup."""
    curr = await db.currencies.find_one({"code": code, "is_active": True}, {"_id": 0})
    if not curr:
        raise HTTPException(status_code=400,
                            detail=f"La moneda {code} no está disponible.")
    return curr


# ============================================================
# VIP endpoints
# ============================================================

@router.post("/vip/capital-requests")
async def create_capital_request(payload: CapitalRequestCreate, request: Request) -> Any:
    """A VIP client creates a pending request for working capital.
    Non-VIP roles are rejected; multiple simultaneous pending/disbursed
    requests are allowed (operator policy — see plan)."""
    user = await require_user(request)
    if user.get("role") != "vip":
        raise HTTPException(status_code=403,
                            detail="Solo los clientes VIP pueden solicitar fondos operativos.")
    await _ensure_currency_active(payload.currency_code.upper())

    doc = {
        "id": f"cr_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "user_email": user.get("email", ""),
        "user_name": user.get("name", ""),
        "amount": round(float(payload.amount), 4),
        "currency_code": payload.currency_code.upper(),
        "reason": payload.reason.strip(),
        "estimated_return_date": payload.estimated_return_date or None,
        "status": "pending",
        "created_at": iso(now_utc()),
        "updated_at": iso(now_utc()),
        "repayment_events": [],
    }
    await db.capital_requests.insert_one(doc)
    await log_action(db, user, "capital_request.created", "capital_request", doc["id"],
                      summary=f"Solicitó {doc['amount']} {doc['currency_code']} de capital operativo",
                      details={"amount": doc["amount"], "currency": doc["currency_code"],
                               "reason": doc["reason"]})
    return _serialize(doc)


@router.get("/vip/capital-requests")
async def list_own_capital_requests(request: Request) -> Any:
    """VIP sees only their own requests. Newest first."""
    user = await require_user(request)
    if user.get("role") != "vip":
        raise HTTPException(status_code=403,
                            detail="Solo los clientes VIP pueden ver esta información.")
    cursor = db.capital_requests.find({"user_id": user["user_id"]}, {"_id": 0})
    cursor = cursor.sort("created_at", -1)
    items = await cursor.to_list(500)
    return items


# ============================================================
# Admin endpoints
# ============================================================

@router.get("/admin/capital-requests")
async def admin_list_capital_requests(request: Request,
                                       status: Optional[str] = None,
                                       user_id: Optional[str] = None) -> Any:
    """Admin/staff with `company_funds` permission lists all requests,
    optionally filtered by status or user. Newest first."""
    await require_permission(request, "withdrawals")
    mongo_q: dict = {}
    if status:
        mongo_q["status"] = status
    if user_id:
        mongo_q["user_id"] = user_id
    cursor = db.capital_requests.find(mongo_q, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(2000)
    return items


@router.post("/admin/capital-requests/{req_id}/approve")
async def admin_approve_capital_request(req_id: str, payload: CapitalRequestApprove,
                                          request: Request) -> Any:
    """Approve + disburse in a single action: credit the VIP's balance in
    the requested currency AND mark the request as `disbursed` with the
    given discount %. Subsequent accumulated orders will auto-repay."""
    actor = await require_permission(request, "withdrawals")
    await _enforce_totp_step_up(actor, payload.totp_code,
                                 action_label="aprobar solicitud de fondos")
    doc = await db.capital_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
    if doc["status"] != "pending":
        raise HTTPException(status_code=400,
                            detail=f"Solo se pueden aprobar solicitudes en estado 'pending' (actual: {doc['status']}).")

    now_iso = iso(now_utc())
    amount = float(doc["amount"])
    currency = doc["currency_code"]

    # iter249 — claim atómico del estado + intención de abono en el MISMO
    # update: dos aprobaciones simultáneas no pueden desembolsar dos veces, y
    # si el proceso muere antes de acreditar, el healer completa el abono.
    from services.credit_recovery import pending_marker, apply_and_clear
    marker = pending_marker(doc["user_id"], currency, amount, "capital-disburse")
    claim = await db.capital_requests.update_one(
        {"id": req_id, "status": "pending"},
        {"$set": {
            "status": "disbursed",
            "reviewed_by": actor.get("user_id", ""),
            "reviewed_at": now_iso,
            "disbursed_at": now_iso,
            "admin_notes": payload.admin_notes.strip(),
            "discount_pct": round(float(payload.discount_pct), 2),
            "debt_original": amount,
            "debt_remaining": amount,
            "updated_at": now_iso,
            "credit_pending": marker,
        }},
    )
    if claim.modified_count == 0:
        raise HTTPException(status_code=409,
                            detail="Esta solicitud ya fue procesada por otro admin.")
    await apply_and_clear("capital_requests", req_id, marker)
    from services.live_events import emit_balance_changed
    await emit_balance_changed(doc["user_id"], "capital_request_disbursed",
                               request_id=req_id, currency=currency)
    await log_action(db, actor, "capital_request.approved", "capital_request", req_id,
                      summary=(f"Aprobó y desembolsó {amount} {currency} a "
                               f"{doc.get('user_email', doc['user_id'])} "
                               f"(descuento {payload.discount_pct}% por orden)"),
                      details={"amount": amount, "currency": currency,
                               "discount_pct": payload.discount_pct,
                               "user_id": doc["user_id"]})
    # Return the refreshed doc
    fresh = await db.capital_requests.find_one({"id": req_id}, {"_id": 0})
    # iter197 — email mirror of the disbursement decision. Best-effort.
    try:
        from email_service import notify_capital_request_decision
        target = await db.users.find_one(
            {"user_id": doc["user_id"]},
            {"_id": 0, "email": 1, "name": 1, "preferred_language": 1},
        )
        if target and target.get("email"):
            notify_capital_request_decision(fresh or doc, target, approved=True)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[capital_requests] approve email failed: {e}")
    return _serialize(fresh or {})


@router.post("/admin/capital-requests/{req_id}/reject")
async def admin_reject_capital_request(req_id: str, payload: CapitalRequestReject,
                                         request: Request) -> Any:
    """Reject a pending request with a required reason. No money moves."""
    actor = await require_permission(request, "withdrawals")
    await _enforce_totp_step_up(actor, payload.totp_code,
                                 action_label="rechazar solicitud de fondos")
    doc = await db.capital_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
    if doc["status"] != "pending":
        raise HTTPException(status_code=400,
                            detail=f"Solo se pueden rechazar solicitudes en estado 'pending' (actual: {doc['status']}).")

    now_iso = iso(now_utc())
    # iter260(E03) — claim atómico: si una aprobación/desembolso concurrente
    # ganó, este rechazo pierde (409) en vez de dejar una solicitud con
    # dinero desembolsado en estado 'rejected' (invisible a la amortización).
    claim = await db.capital_requests.update_one(
        {"id": req_id, "status": "pending"},
        {"$set": {
            "status": "rejected",
            "reviewed_by": actor.get("user_id", ""),
            "reviewed_at": now_iso,
            "reject_reason": payload.reject_reason.strip(),
            "updated_at": now_iso,
        }},
    )
    if claim.matched_count == 0:
        raise HTTPException(status_code=409,
                            detail="La solicitud ya fue procesada por otro operador.")
    await log_action(db, actor, "capital_request.rejected", "capital_request", req_id,
                      summary=(f"Rechazó solicitud de {doc['amount']} {doc['currency_code']} "
                               f"de {doc.get('user_email', doc['user_id'])}"),
                      details={"reason": payload.reject_reason,
                               "user_id": doc["user_id"]})
    fresh = await db.capital_requests.find_one({"id": req_id}, {"_id": 0})
    # iter197 — email mirror of the rejection decision. Best-effort.
    try:
        from email_service import notify_capital_request_decision
        target = await db.users.find_one(
            {"user_id": doc["user_id"]},
            {"_id": 0, "email": 1, "name": 1, "preferred_language": 1},
        )
        if target and target.get("email"):
            notify_capital_request_decision(fresh or doc, target, approved=False)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[capital_requests] reject email failed: {e}")
    return _serialize(fresh or {})
