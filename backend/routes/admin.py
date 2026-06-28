"""Admin router — iter33. Houses every `/admin/*` endpoint (orders/redemptions/
withdrawals management, settings, defensive mode, queue, users, audit log,
transactions registry, revenue reports, company funds tracker, marketplace
seed, platform stats).

This file is intentionally large because it mirrors the admin domain. Shared
helpers live in services/* so they can be unit-tested independently.
"""
import csv
import io
import json as _json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from io import BytesIO
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import (
    require_admin, require_staff,
    now_utc, iso,
    _enforce_employee_currency_scope, _enforce_totp_step_up,
)
from audit_log import log_action
from audit_pdf import generate_audit_pdf
from transactions_pdf import generate_transactions_pdf
from revenue_report import build_buckets, revenue_monthly_csv, revenue_monthly_pdf
import email_service

from services.balances import (
    build_rate_lookup, convert_to_usdt,
    get_defensive_mode, DEFENSIVE_MODE_KEY,
)
from services.orders_helpers import (
    VALID_ORDER_STATUSES, compute_order_profit,
    authorize_status_transition, run_post_status_side_effects,
)
from services.transactions import (
    build_transactions, compute_transaction_totals,
    build_audit_query, fetch_audit_entries,
)
from services.proof_upload import maybe_upload_proof
from services.health import build_health_summary


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Admin"])


# ============================================================
# Pydantic models
# ============================================================

class UserUpdate(BaseModel):
    role: Optional[Literal["normal", "vip", "employee", "admin"]] = None
    vip_balance_usd: Optional[float] = None
    vip_balances: Optional[Dict[str, float]] = None
    allowed_currencies: Optional[List[str]] = None
    can_edit_product_prices: Optional[bool] = None
    can_upload_product_images: Optional[bool] = None
    can_delete_products: Optional[bool] = None
    can_manage_blocklist: Optional[bool] = None
    account_status: Optional[Literal["active", "under_review", "blocked"]] = None
    totp_code: Optional[str] = Field(None, max_length=11, description="Código 2FA requerido")


class AdminSettings(BaseModel):
    vip_threshold_usdt: float = Field(default=5000.0, ge=0)
    defensive_margin_pct: Optional[float] = Field(default=None)
    totp_code: Optional[str] = Field(default=None, max_length=11,
                                       description="Código 2FA requerido")


class DefensiveModePayload(BaseModel):
    enabled: bool
    reason: Optional[str] = Field(None, max_length=500)
    totp_code: Optional[str] = Field(None, max_length=11)


class CompanyWithdrawal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    amount: float
    currency: str
    beneficiary: str
    authorized_by_id: str
    authorized_by_name: str
    authorized_by_email: str
    concept: str = ""
    invoice_image: str = ""
    note: str = ""
    status: Literal["pending", "approved", "paid", "rejected"] = "pending"
    created_at: str = Field(default_factory=lambda: iso(now_utc()))


class CompanyWithdrawalCreate(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str
    beneficiary: str = Field(..., min_length=2)
    concept: str = ""
    invoice_image: str = ""
    note: str = ""
    totp_code: Optional[str] = Field(None, max_length=11)


# ============================================================
# System / Defensive mode
# ============================================================

@router.get("/system/defensive-mode")
async def public_defensive_mode():
    """Public endpoint so the SPA can show the warning banner to everyone."""
    state = await get_defensive_mode()
    return {"enabled": bool(state.get("enabled")), "enabled_at": state.get("enabled_at")}


@router.post("/admin/defensive-mode/toggle")
async def admin_toggle_defensive_mode(payload: DefensiveModePayload, request: Request):
    actor = await require_admin(request)
    await _enforce_totp_step_up(
        actor, payload.totp_code,
        action_label=f"{'activar' if payload.enabled else 'desactivar'} modo defensivo",
    )
    update = {
        "key": DEFENSIVE_MODE_KEY,
        "enabled": payload.enabled,
        "reason": (payload.reason or "").strip(),
        "enabled_at": iso(now_utc()) if payload.enabled else None,
        "enabled_by_email": actor.get("email", "") if payload.enabled else "",
    }
    await db.system_config.update_one(
        {"key": DEFENSIVE_MODE_KEY}, {"$set": update}, upsert=True,
    )
    await log_action(db, actor, "system.defensive_mode", "system", DEFENSIVE_MODE_KEY,
                     summary=f"Modo defensivo {'activado' if payload.enabled else 'desactivado'}",
                     details={"reason": update["reason"]})
    return update


# ============================================================
# Orders — admin listing + status transitions
# ============================================================

@router.get("/admin/orders")
async def all_orders(request: Request, status: Optional[str] = None,
                     user_q: Optional[str] = None, currency: Optional[str] = None,
                     limit: int = 1000, offset: int = 0):
    actor = await require_staff(request)
    q = {}
    if status:
        q["status"] = status
    if currency:
        currency = currency.upper()
        q["$or"] = [{"from_code": currency}, {"to_code": currency}]
    if user_q:
        rx = {"$regex": user_q, "$options": "i"}
        user_clause = {"$or": [{"user_name": rx}, {"user_email": rx}]}
        if "$or" in q:
            q["$and"] = [{"$or": q.pop("$or")}, user_clause]
        else:
            q["$or"] = user_clause["$or"]
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            scope_clause = {"$or": [{"from_code": {"$in": allowed}}, {"to_code": {"$in": allowed}}]}
            if "$and" in q:
                q["$and"].append(scope_clause)
            elif "$or" in q:
                q["$and"] = [{"$or": q.pop("$or")}, scope_clause]
            else:
                q["$or"] = scope_clause["$or"]
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    total = await db.orders.count_documents(q)
    docs = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).skip(offset).to_list(limit)
    return JSONResponse(
        content=docs,
        headers={
            "X-Total-Count": str(total),
            "X-Offset": str(offset),
            "X-Limit": str(limit),
            "Access-Control-Expose-Headers": "X-Total-Count, X-Offset, X-Limit",
        },
    )


@router.put("/admin/orders/{order_id}/status")
async def update_order_status(order_id: str, payload: dict, request: Request):
    actor = await require_staff(request)
    new_status = payload.get("status")
    note = payload.get("admin_note", "")
    if new_status not in VALID_ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="status inválido")
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    await authorize_status_transition(actor, order, new_status, payload.get("totp_code"))

    prev_status = order["status"]
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"status": new_status, "admin_note": note, "updated_at": iso(now_utc())}},
    )
    updated = await db.orders.find_one({"id": order_id}, {"_id": 0})
    await run_post_status_side_effects(updated, new_status, prev_status)

    await log_action(
        db, actor, f"order.{new_status}", "order", order_id,
        summary=f"Orden {order['from_code']}→{order['to_code']} {new_status}",
        details={"prev": prev_status, "new": new_status, "note": note,
                  "amount_from": order["amount_from"], "amount_to": order["amount_to"]},
    )
    return updated


# ============================================================
# Redemptions — admin listing + status transitions
# ============================================================

@router.get("/admin/redemptions")
async def all_redemptions(request: Request):
    await require_staff(request)
    docs = await db.redemptions.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@router.put("/admin/redemptions/{rid}/status")
async def update_redemption(rid: str, payload: dict, request: Request):
    await require_staff(request)
    new_status = payload.get("status")
    note = payload.get("admin_note", "")
    if new_status not in ("approved", "delivered", "rejected", "pending"):
        raise HTTPException(status_code=400, detail="status inválido")
    r = await db.redemptions.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="No encontrado")
    if new_status == "rejected" and r["status"] != "rejected":
        await db.users.update_one(
            {"user_id": r["user_id"]}, {"$inc": {"vip_balance_usd": r["total_usd"]}}
        )
        await db.products.update_one(
            {"id": r["product_id"]}, {"$inc": {"stock": r["quantity"]}}
        )
    await db.redemptions.update_one(
        {"id": rid}, {"$set": {"status": new_status, "admin_note": note}}
    )
    return await db.redemptions.find_one({"id": rid}, {"_id": 0})


# ============================================================
# Withdrawals — admin listing + status transitions
# ============================================================

@router.get("/admin/withdrawals")
async def all_withdrawals(request: Request,
                          status: Optional[str] = None,
                          user_q: Optional[str] = None,
                          currency: Optional[str] = None):
    actor = await require_staff(request)
    q = {}
    if status:
        q["status"] = status
    if currency:
        q["currency"] = currency.upper()
    if user_q:
        rx = {"$regex": user_q, "$options": "i"}
        q["$or"] = [{"user_name": rx}, {"user_email": rx}]
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            if "currency" in q:
                if q["currency"] not in allowed:
                    return []
            else:
                q["currency"] = {"$in": allowed}
    docs = await db.withdrawals.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


def _assert_paid_lock(actor: dict, withdrawal: dict, new_status: str) -> None:
    """Block non-admins from un-marking an already-paid withdrawal."""
    if (withdrawal["status"] == "paid"
            and new_status != "paid"
            and actor.get("role") != "admin"):
        raise HTTPException(
            status_code=403,
            detail="Este retiro ya fue entregado. Solo un admin puede modificarlo.",
        )


async def _refund_balance_on_reject(withdrawal: dict, new_status: str) -> None:
    """Restore the VIP balance when a withdrawal moves into 'rejected'."""
    if new_status != "rejected" or withdrawal["status"] == "rejected":
        return
    refund_currency = withdrawal.get("currency", "USD")
    await db.users.update_one(
        {"user_id": withdrawal["user_id"]},
        {"$inc": {f"vip_balances.{refund_currency}": withdrawal["amount_usd"]}},
    )


def _collect_payout_evidence(payload: dict, update_doc: dict) -> None:
    """Persist optional payout proof image + tx hash on the update document."""
    proof = payload.get("payout_proof_image")
    if proof:
        update_doc["payout_proof_image"] = maybe_upload_proof(proof, "withdrawals") or proof
    tx_hash = payload.get("payout_tx_hash")
    if tx_hash:
        update_doc["payout_tx_hash"] = tx_hash


def _validate_paid_evidence(withdrawal: dict, update_doc: dict, new_status: str) -> None:
    """When marking as paid, ensure the required payout artefact is present."""
    if new_status != "paid" or withdrawal["status"] == "paid":
        return
    method = withdrawal.get("method")
    existing_proof = withdrawal.get("payout_proof_image") or update_doc.get("payout_proof_image")
    if method == "transfer" and not existing_proof:
        raise HTTPException(
            status_code=400,
            detail="Adjunta la captura de la transferencia realizada al cliente antes de marcar como entregado",
        )
    if method == "crypto":
        existing_hash = withdrawal.get("payout_tx_hash") or update_doc.get("payout_tx_hash")
        if not existing_hash and not existing_proof:
            raise HTTPException(
                status_code=400,
                detail="Adjunta hash de transacción y/o captura del envío antes de marcar como entregado",
            )


@router.put("/admin/withdrawals/{wid}/status")
async def update_withdrawal(wid: str, payload: dict, request: Request):
    actor = await require_staff(request)
    new_status = payload.get("status")
    if new_status not in ("approved", "paid", "rejected", "pending"):
        raise HTTPException(status_code=400, detail="status inválido")
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                 action_label="gestionar retiro")
    w = await db.withdrawals.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(status_code=404, detail="No encontrado")
    _assert_paid_lock(actor, w, new_status)
    _enforce_employee_currency_scope(actor, w.get("currency"))
    await _refund_balance_on_reject(w, new_status)
    update_doc = {"status": new_status, "admin_note": payload.get("admin_note", "")}
    _collect_payout_evidence(payload, update_doc)
    _validate_paid_evidence(w, update_doc, new_status)
    await db.withdrawals.update_one({"id": wid}, {"$set": update_doc})
    return await db.withdrawals.find_one({"id": wid}, {"_id": 0})


# ============================================================
# Platform stats
# ============================================================

async def _aggregate_flow(group_field: str, rates: dict) -> dict:
    """Aggregate approved/completed orders by a field with USDT conversion."""
    sum_field = "$amount_from" if group_field == "from_code" else "$amount_to"
    pipeline = [
        {"$match": {"status": {"$in": ["approved", "completed"]}}},
        {"$group": {"_id": f"${group_field}", "total": {"$sum": sum_field}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(100)
    items = []
    total_usdt = 0.0
    for row in rows:
        code = row["_id"]
        amt = float(row["total"] or 0.0)
        usdt = convert_to_usdt(amt, code, rates)
        if usdt is not None:
            total_usdt += usdt
        items.append({
            "currency": code,
            "total": amt,
            "count": row["count"],
            "usdt_equivalent": round(usdt, 4) if usdt is not None else None,
        })
    return {"items": items, "total_usdt": round(total_usdt, 4)}


async def _aggregate_vip_holdings(rates: dict) -> dict:
    """Sum vip_balances across all VIP/admin users and convert to USDT."""
    users = await db.users.find(
        {"role": {"$in": ["vip", "admin"]}}, {"_id": 0}
    ).to_list(1000)
    totals = {}
    for u in users:
        for code, amt in (u.get("vip_balances") or {}).items():
            totals[code] = totals.get(code, 0.0) + float(amt or 0.0)
        legacy = float(u.get("vip_balance_usd") or 0.0)
        if legacy > 0:
            totals["USD"] = totals.get("USD", 0.0) + legacy
    items = []
    total_usdt = 0.0
    for code, amt in totals.items():
        usdt = convert_to_usdt(amt, code, rates)
        if usdt is not None:
            total_usdt += usdt
        items.append({
            "currency": code,
            "total": amt,
            "usdt_equivalent": round(usdt, 4) if usdt is not None else None,
        })
    items.sort(key=lambda x: -(x["usdt_equivalent"] or 0))
    return {"items": items, "total_usdt": round(total_usdt, 4)}


async def _platform_counters() -> dict:
    return {
        "users_total": await db.users.count_documents({}),
        "users_vip": await db.users.count_documents({"role": "vip"}),
        "orders_total": await db.orders.count_documents({}),
        "orders_pending": await db.orders.count_documents({"status": "pending"}),
        "withdrawals_pending": await db.withdrawals.count_documents({"status": "pending"}),
    }


@router.get("/admin/stats")
async def admin_platform_stats(request: Request):
    await require_staff(request)
    rates = await build_rate_lookup()
    return {
        "inflow": await _aggregate_flow("from_code", rates),
        "outflow": await _aggregate_flow("to_code", rates),
        "vip_holdings": await _aggregate_vip_holdings(rates),
        "counters": await _platform_counters(),
    }


# ============================================================
# Health Dashboard (iter37)
# ============================================================

@router.get("/admin/health/summary")
async def admin_health_summary(request: Request):
    """Composite payload for the Admin Health Dashboard. Admin only — exposes
    R2 bucket size, Sentry env, throughput, defensive mode, negative-margin
    pending list and the staff queues. Each section is wrapped so one slow
    data source doesn't break the page."""
    await require_admin(request)
    return await build_health_summary()


# ============================================================
# Admin settings
# ============================================================

@router.get("/admin/settings")
async def get_admin_settings(request: Request):
    await require_staff(request)
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0})
    if not doc:
        return {
            "vip_threshold_usdt": float(os.environ.get("VIP_ALERT_THRESHOLD_USDT", 5000)),
            "defensive_margin_pct": None,
        }
    return {
        "vip_threshold_usdt": float(doc.get("vip_threshold_usdt", 5000)),
        "defensive_margin_pct": doc.get("defensive_margin_pct"),
    }


@router.put("/admin/settings")
async def update_admin_settings(payload: AdminSettings, request: Request):
    actor = await require_admin(request)
    await _enforce_totp_step_up(actor, payload.totp_code, action_label="actualizar configuración")
    data = payload.model_dump(exclude={"totp_code"})
    data["id"] = "global"
    await db.settings.update_one({"id": "global"}, {"$set": data}, upsert=True)
    await log_action(db, actor, "settings.update", "settings", "global",
                     summary="Settings actualizados", details=data)
    return {"ok": True, **data}


# ============================================================
# Audit log
# ============================================================

@router.get("/admin/audit")
async def list_audit_log(request: Request, limit: int = 100, offset: int = 0,
                         action: Optional[str] = None, actor_id: Optional[str] = None,
                         since: Optional[str] = None, until: Optional[str] = None):
    await require_admin(request)
    q = build_audit_query(action, actor_id, since, until)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    total = await db.audit_log.count_documents(q)
    docs = await db.audit_log.find(q, {"_id": 0}).sort("created_at", -1).skip(offset).to_list(limit)
    return JSONResponse(
        content=docs,
        headers={
            "X-Total-Count": str(total),
            "X-Offset": str(offset),
            "X-Limit": str(limit),
            "Access-Control-Expose-Headers": "X-Total-Count, X-Offset, X-Limit",
        },
    )


@router.get("/admin/audit/export.csv")
async def export_audit_csv(request: Request, action: Optional[str] = None,
                           actor_id: Optional[str] = None,
                           since: Optional[str] = None, until: Optional[str] = None,
                           limit: int = 5000):
    await require_admin(request)
    entries = await fetch_audit_entries(action, actor_id, since, until, limit)
    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    writer.writerow(["created_at", "actor_id", "actor_email", "actor_name", "actor_role",
                     "action", "entity_type", "entity_id", "summary", "details"])
    for e in entries:
        writer.writerow([
            e.get("created_at", ""),
            e.get("actor_id", ""),
            e.get("actor_email", ""),
            e.get("actor_name", ""),
            e.get("actor_role", ""),
            e.get("action", ""),
            e.get("entity_type", ""),
            e.get("entity_id", ""),
            e.get("summary", ""),
            _json.dumps(e.get("details") or {}, ensure_ascii=False),
        ])
    buf = BytesIO()
    buf.write(text_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"audit_log_{ts}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/audit/export.pdf")
async def export_audit_pdf(request: Request, action: Optional[str] = None,
                           actor_id: Optional[str] = None,
                           since: Optional[str] = None, until: Optional[str] = None,
                           limit: int = 2000):
    await require_admin(request)
    entries = await fetch_audit_entries(action, actor_id, since, until, limit)
    pdf_bytes = generate_audit_pdf(
        entries,
        {"action": action, "actor_id": actor_id, "since": since, "until": until},
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"audit_log_{ts}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================
# Transactions registry (admin view)
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


@router.get("/admin/transactions")
async def list_transactions(request: Request,
                            direction: Optional[str] = None,
                            currency: Optional[str] = None,
                            holder: Optional[str] = None,
                            since: Optional[str] = None,
                            until: Optional[str] = None,
                            min_amount: Optional[float] = None,
                            max_amount: Optional[float] = None,
                            limit: int = 100, offset: int = 0):
    await require_staff(request)
    _validate_txn_filters(direction, min_amount, max_amount)
    items = await build_transactions(
        direction, currency, holder, since, until, min_amount, max_amount
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


@router.get("/admin/transactions/export.csv")
async def export_transactions_csv(request: Request,
                                  direction: Optional[str] = None,
                                  currency: Optional[str] = None,
                                  holder: Optional[str] = None,
                                  since: Optional[str] = None,
                                  until: Optional[str] = None,
                                  min_amount: Optional[float] = None,
                                  max_amount: Optional[float] = None):
    await require_staff(request)
    items = await build_transactions(
        direction, currency, holder, since, until, min_amount, max_amount
    )
    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    writer.writerow(["created_at", "direction", "currency", "amount",
                     "holder_name", "client_name", "client_email",
                     "method", "status", "ref_type", "ref_id"])
    for it in items:
        writer.writerow([
            it.get("created_at", ""),
            it.get("direction", ""),
            it.get("currency", ""),
            f"{it.get('amount', 0):.4f}",
            it.get("holder_name", ""),
            it.get("client_name", ""),
            it.get("client_email", ""),
            it.get("method", ""),
            it.get("status", ""),
            it.get("ref_type", ""),
            it.get("ref_id", ""),
        ])
    buf = BytesIO()
    buf.write(text_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"transacciones_{ts}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/transactions/export.pdf")
async def export_transactions_pdf(request: Request,
                                  direction: Optional[str] = None,
                                  currency: Optional[str] = None,
                                  holder: Optional[str] = None,
                                  since: Optional[str] = None,
                                  until: Optional[str] = None,
                                  min_amount: Optional[float] = None,
                                  max_amount: Optional[float] = None):
    await require_staff(request)
    items = await build_transactions(
        direction, currency, holder, since, until, min_amount, max_amount
    )
    totals = compute_transaction_totals(items)
    pdf_bytes = generate_transactions_pdf(
        items,
        {"direction": direction, "currency": currency, "holder": holder,
         "since": since, "until": until,
         "min_amount": min_amount, "max_amount": max_amount},
        totals,
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"transacciones_{ts}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================
# Revenue (admin only)
# ============================================================

async def _compute_marketplace_revenue(days: Optional[int]) -> dict:
    """Profit from delivered redemptions: total_usd - cost_usd. USD ≈ USDT for simplicity."""
    q = {"status": "delivered"}
    if days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["created_at"] = {"$gte": cutoff}
    rows = await db.redemptions.find(q, {"_id": 0}).to_list(5000)
    total_revenue = 0.0
    total_cost = 0.0
    by_product: dict = {}
    for r in rows:
        rev = float(r.get("total_usd") or 0.0)
        cost = float(r.get("cost_usd") or 0.0)
        total_revenue += rev
        total_cost += cost
        key = r.get("product_name", "—")
        if key not in by_product:
            by_product[key] = {
                "product": key, "units": 0, "revenue_usd": 0.0,
                "cost_usd": 0.0, "profit_usd": 0.0, "redemptions": 0,
            }
        bp = by_product[key]
        bp["units"] += int(r.get("quantity") or 0)
        bp["revenue_usd"] += rev
        bp["cost_usd"] += cost
        bp["profit_usd"] += (rev - cost)
        bp["redemptions"] += 1
    items = []
    for v in by_product.values():
        v["revenue_usd"] = round(v["revenue_usd"], 2)
        v["cost_usd"] = round(v["cost_usd"], 2)
        v["profit_usd"] = round(v["profit_usd"], 2)
        v["margin_pct"] = round((v["profit_usd"] / v["revenue_usd"] * 100), 2) if v["revenue_usd"] > 0 else 0.0
        items.append(v)
    items.sort(key=lambda x: -x["profit_usd"])
    return {
        "total_revenue_usd": round(total_revenue, 2),
        "total_cost_usd": round(total_cost, 2),
        "total_profit_usd": round(total_revenue - total_cost, 2),
        "items": items,
        "deliveries": len(rows),
    }


def _new_pair_bucket(o: dict, rate_doc: dict) -> dict:
    return {
        "pair": f"{o['from_code']}→{o['to_code']}",
        "from_code": o["from_code"],
        "to_code": o["to_code"],
        "orders": 0,
        "volume_from": 0.0,
        "volume_to": 0.0,
        "profit_to": 0.0,
        "profit_usdt": 0.0,
        "real_rate": rate_doc.get("real_rate"),
        "rate_normal": rate_doc.get("rate_normal"),
        "rate_vip": rate_doc.get("rate_vip"),
        "avg_profit_pct": 0.0,
    }


def _role_bucket_for(order: dict) -> str:
    return "vip" if order.get("user_role") in ("vip", "admin") else "normal"


async def _accumulate_revenue_order(
    o: dict, rate_doc: dict, fx: dict,
    by_pair: dict, by_role: dict, missing: set,
) -> tuple[float, float | None]:
    """Mutate by_pair/by_role with this order. Returns (volume_usdt, profit_usdt|None)."""
    profit = await compute_order_profit(o, rate_doc)
    volume_usdt = convert_to_usdt(o["amount_from"], o["from_code"], fx) or 0.0
    role = _role_bucket_for(o)
    by_role[role]["orders"] += 1
    by_role[role]["volume_usdt"] += volume_usdt

    if profit is None:
        missing.add(f"{o['from_code']}→{o['to_code']}")
        return volume_usdt, None

    profit_usdt = convert_to_usdt(profit["amount"], profit["currency"], fx) or 0.0
    by_role[role]["profit_usdt"] += profit_usdt

    key = f"{o['from_code']}→{o['to_code']}"
    bucket = by_pair.setdefault(key, _new_pair_bucket(o, rate_doc))
    bucket["orders"] += 1
    bucket["volume_from"] += o["amount_from"]
    bucket["volume_to"] += o["amount_to"]
    bucket["profit_to"] += profit["amount"]
    bucket["profit_usdt"] += profit_usdt
    return volume_usdt, profit_usdt


def _finalize_pair_items(by_pair: dict) -> list:
    items = []
    for b in by_pair.values():
        if b["volume_to"] > 0 and b["real_rate"]:
            real_value = b["volume_from"] * float(b["real_rate"])
            b["avg_profit_pct"] = (
                round((real_value - b["volume_to"]) / real_value * 100, 3)
                if real_value > 0 else 0.0
            )
        b["profit_to"] = round(b["profit_to"], 4)
        b["profit_usdt"] = round(b["profit_usdt"], 4)
        items.append(b)
    items.sort(key=lambda x: -x["profit_usdt"])
    return items


@router.get("/admin/revenue")
async def admin_revenue(request: Request, days: Optional[int] = None):
    await require_admin(request)
    q = {"status": {"$in": ["approved", "completed"]}}
    if days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["updated_at"] = {"$gte": cutoff}

    orders = await db.orders.find(q, {"_id": 0}).to_list(5000)
    rates = await db.rates.find({}, {"_id": 0}).to_list(500)
    rate_by_pair = {(r["from_code"], r["to_code"]): r for r in rates}
    fx = await build_rate_lookup()

    by_pair: dict = {}
    by_role = {"normal": {"profit_usdt": 0.0, "orders": 0, "volume_usdt": 0.0},
               "vip": {"profit_usdt": 0.0, "orders": 0, "volume_usdt": 0.0}}
    missing_rate_pairs: set = set()
    total_profit_usdt = 0.0
    total_volume_usdt = 0.0

    for o in orders:
        rate_doc = rate_by_pair.get((o["from_code"], o["to_code"]))
        vol, prof = await _accumulate_revenue_order(
            o, rate_doc, fx, by_pair, by_role, missing_rate_pairs,
        )
        total_volume_usdt += vol
        if prof is not None:
            total_profit_usdt += prof

    pair_items = _finalize_pair_items(by_pair)

    for r in by_role.values():
        r["profit_usdt"] = round(r["profit_usdt"], 4)
        r["volume_usdt"] = round(r["volume_usdt"], 4)

    marketplace = await _compute_marketplace_revenue(days)

    return {
        "total_profit_usdt": round(total_profit_usdt + marketplace["total_profit_usd"], 4),
        "p2p_profit_usdt": round(total_profit_usdt, 4),
        "marketplace_profit_usdt": round(marketplace["total_profit_usd"], 4),
        "total_volume_usdt": round(total_volume_usdt, 4),
        "profit_margin_pct": round((total_profit_usdt / total_volume_usdt * 100), 3) if total_volume_usdt > 0 else 0.0,
        "by_pair": pair_items,
        "by_role": by_role,
        "marketplace": marketplace,
        "missing_real_rate_pairs": sorted(missing_rate_pairs),
        "orders_total": len(orders),
    }


async def build_revenue_timeseries(granularity: str, days: Optional[int] = None,
                                    year: Optional[int] = None, month: Optional[int] = None):
    """Build per-day or per-month buckets for the admin revenue dashboard.

    Filters:
      - `days`: restrict to last N days (preferred for daily charts).
      - `year`/`month`: restrict to a specific calendar month (used for the monthly export).
    """
    order_q: dict = {"status": {"$in": ["approved", "completed"]}}
    redemption_q: dict = {"status": "delivered"}

    if year and month:
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end = (datetime(year + 1, 1, 1, tzinfo=timezone.utc)
               if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc))
        order_q["updated_at"] = {"$gte": start.isoformat(), "$lt": end.isoformat()}
        redemption_q["created_at"] = {"$gte": start.isoformat(), "$lt": end.isoformat()}
    elif days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        order_q["updated_at"] = {"$gte": cutoff}
        redemption_q["created_at"] = {"$gte": cutoff}

    orders = await db.orders.find(order_q, {"_id": 0}).to_list(5000)
    redemptions = await db.redemptions.find(redemption_q, {"_id": 0}).to_list(5000)
    rates = await db.rates.find({}, {"_id": 0}).to_list(500)
    rate_by_pair = {(r["from_code"], r["to_code"]): r for r in rates}
    fx = await build_rate_lookup()

    profit_map: dict = {}
    for o in orders:
        o["_volume_usdt"] = convert_to_usdt(o["amount_from"], o["from_code"], fx) or 0.0
        rate_doc = rate_by_pair.get((o["from_code"], o["to_code"]))
        prof = await compute_order_profit(o, rate_doc)
        if prof is None:
            continue
        prof_usdt = convert_to_usdt(prof["amount"], prof["currency"], fx) or 0.0
        profit_map[o["id"]] = prof_usdt

    return build_buckets(orders, redemptions, profit_map, granularity)


@router.get("/admin/revenue/timeseries")
async def admin_revenue_timeseries(request: Request, granularity: str = "day",
                                     days: Optional[int] = None):
    await require_admin(request)
    if granularity not in ("day", "month"):
        raise HTTPException(status_code=400, detail="granularity inválida (day|month)")
    rows = await build_revenue_timeseries(granularity, days=days)
    return {"granularity": granularity, "rows": rows}


@router.get("/admin/revenue/monthly/export")
async def admin_revenue_monthly_export(request: Request, year: int, month: int,
                                          format: str = "csv"):
    """Export the daily breakdown of a calendar month as CSV or PDF."""
    await require_admin(request)
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="mes inválido")
    if format not in ("csv", "pdf"):
        raise HTTPException(status_code=400, detail="formato inválido (csv|pdf)")

    rows = await build_revenue_timeseries("day", year=year, month=month)
    rows_asc = sorted(rows, key=lambda x: x["bucket"])
    period_label = f"{year}-{month:02d}"

    if format == "csv":
        payload = revenue_monthly_csv(rows_asc, period_label)
        headers = {"Content-Disposition": f'attachment; filename="ganancia-{period_label}.csv"'}
        return Response(content=payload, media_type="text/csv; charset=utf-8", headers=headers)

    totals = {
        "p2p": sum(r["p2p_profit_usdt"] for r in rows_asc),
        "marketplace": sum(r["marketplace_profit_usdt"] for r in rows_asc),
        "total": sum(r["total_profit_usdt"] for r in rows_asc),
        "volume": sum(r["volume_usdt"] for r in rows_asc),
        "orders": sum(r["orders"] for r in rows_asc),
    }
    payload = revenue_monthly_pdf(rows_asc, period_label, totals)
    headers = {"Content-Disposition": f'attachment; filename="ganancia-{period_label}.pdf"'}
    return Response(content=payload, media_type="application/pdf", headers=headers)


@router.post("/admin/revenue/monthly/send-now")
async def admin_revenue_send_now(payload: dict, request: Request):
    """Manually trigger the monthly revenue email."""
    actor = await require_admin(request)
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                 action_label="enviar reporte mensual")
    year = int(payload.get("year") or 0)
    month = int(payload.get("month") or 0)
    if month < 1 or month > 12 or year < 2020:
        raise HTTPException(status_code=400, detail="año/mes inválido")
    rows = await build_revenue_timeseries("day", year=year, month=month)
    rows_asc = sorted(rows, key=lambda x: x["bucket"])
    totals = {
        "p2p": sum(r["p2p_profit_usdt"] for r in rows_asc),
        "marketplace": sum(r["marketplace_profit_usdt"] for r in rows_asc),
        "total": sum(r["total_profit_usdt"] for r in rows_asc),
        "volume": sum(r["volume_usdt"] for r in rows_asc),
        "orders": sum(r["orders"] for r in rows_asc),
    }
    pdf_bytes = revenue_monthly_pdf(rows_asc, f"{year}-{month:02d}", totals)
    admins = await db.users.find({"role": "admin"}, {"_id": 0, "email": 1}).to_list(200)
    sent = 0
    for a in admins:
        if a.get("email") and email_service.notify_monthly_revenue(
            a["email"], f"{year}-{month:02d}", totals, pdf_bytes
        ):
            sent += 1
    return {"ok": True, "sent": sent, "total_admins": len(admins),
            "period": f"{year}-{month:02d}"}


# ============================================================
# Company funds (working capital)
# ============================================================

async def _compute_company_funds(scope: Optional[List[str]] = None) -> List[dict]:
    """Per-currency platform working-capital balance.

    balance[c] = inflows_from_confirmed_orders[c]
                - outflows_to_clients_paid[c]
                - outflows_company_paid[c]
    `scope` (currency codes) optionally restricts the returned list.
    """
    inflow: dict = {}
    async for o in db.orders.find(
        {"status": {"$in": ["approved", "completed"]}},
        {"_id": 0, "from_code": 1, "amount_from": 1},
    ):
        c = o.get("from_code")
        if c:
            inflow[c] = inflow.get(c, 0.0) + float(o.get("amount_from") or 0.0)

    out_clients: dict = {}
    async for w in db.withdrawals.find(
        {"status": "paid"}, {"_id": 0, "currency": 1, "amount_usd": 1}
    ):
        c = w.get("currency") or "USD"
        out_clients[c] = out_clients.get(c, 0.0) + float(w.get("amount_usd") or 0.0)

    out_company: dict = {}
    async for cw in db.company_withdrawals.find(
        {"status": "paid"}, {"_id": 0, "currency": 1, "amount": 1}
    ):
        c = cw.get("currency")
        if c:
            out_company[c] = out_company.get(c, 0.0) + float(cw.get("amount") or 0.0)

    codes = set(inflow) | set(out_clients) | set(out_company)
    rows = []
    for c in sorted(codes):
        if scope and c not in scope:
            continue
        rows.append({
            "currency": c,
            "inflow": round(inflow.get(c, 0.0), 4),
            "outflow_clients": round(out_clients.get(c, 0.0), 4),
            "outflow_company": round(out_company.get(c, 0.0), 4),
            "balance": round(inflow.get(c, 0.0) - out_clients.get(c, 0.0) - out_company.get(c, 0.0), 4),
        })
    return rows


@router.get("/admin/company-funds")
async def admin_company_funds(request: Request):
    actor = await require_staff(request)
    scope = None
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            scope = allowed
    return await _compute_company_funds(scope)


@router.post("/admin/company-withdrawals")
async def create_company_withdrawal(payload: CompanyWithdrawalCreate, request: Request):
    actor = await require_staff(request)
    currency = payload.currency.upper()
    _enforce_employee_currency_scope(actor, currency)
    await _enforce_totp_step_up(actor, payload.totp_code, action_label="retiro del fondo")
    funds = await _compute_company_funds([currency])
    avail = next((f["balance"] for f in funds if f["currency"] == currency), 0.0)
    if payload.amount > avail:
        raise HTTPException(
            status_code=400,
            detail=f"Fondo insuficiente en {currency}: disponible {avail:.2f}",
        )
    cw = CompanyWithdrawal(
        amount=payload.amount,
        currency=currency,
        beneficiary=payload.beneficiary,
        authorized_by_id=actor["user_id"],
        authorized_by_name=actor.get("name", ""),
        authorized_by_email=actor.get("email", ""),
        concept=payload.concept,
        invoice_image=(maybe_upload_proof(payload.invoice_image, "company_invoices")
                        or payload.invoice_image),
        note=payload.note,
    )
    await db.company_withdrawals.insert_one(cw.model_dump())
    await log_action(db, actor, "company_withdrawal.create", "company_withdrawal", cw.id,
                     summary=f"Retiro fondo {currency} {payload.amount} → {payload.beneficiary}",
                     details={"currency": currency, "amount": payload.amount,
                              "beneficiary": payload.beneficiary})
    return cw.model_dump()


@router.get("/admin/company-withdrawals")
async def list_company_withdrawals(request: Request,
                                     status: Optional[str] = None,
                                     currency: Optional[str] = None):
    actor = await require_staff(request)
    q = {}
    if status:
        q["status"] = status
    if currency:
        q["currency"] = currency.upper()
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            if "currency" in q and q["currency"] not in allowed:
                return []
            elif "currency" not in q:
                q["currency"] = {"$in": allowed}
    docs = await db.company_withdrawals.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@router.put("/admin/company-withdrawals/{cwid}/status")
async def update_company_withdrawal(cwid: str, payload: dict, request: Request):
    """Only admin can change status (approve/pay/reject). Staff with scope creates only."""
    actor = await require_admin(request)
    new_status = payload.get("status")
    if new_status not in ("approved", "paid", "rejected"):
        raise HTTPException(status_code=400, detail="status inválido")
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                 action_label="actualizar retiro de fondo")
    cw = await db.company_withdrawals.find_one({"id": cwid}, {"_id": 0})
    if not cw:
        raise HTTPException(status_code=404, detail="No encontrado")
    if cw["status"] == "paid" and new_status != "paid":
        raise HTTPException(status_code=403, detail="Ya fue pagado, no se puede revertir")
    update_doc = {"status": new_status}
    note = payload.get("note")
    if note is not None:
        update_doc["admin_note"] = note
    await db.company_withdrawals.update_one({"id": cwid}, {"$set": update_doc})
    await log_action(db, actor, "company_withdrawal.status", "company_withdrawal", cwid,
                     summary=f"Retiro fondo {cw['currency']} {cw['amount']} → {new_status}",
                     details={"from": cw["status"], "to": new_status})
    return await db.company_withdrawals.find_one({"id": cwid}, {"_id": 0})


# ============================================================
# Staff queue
# ============================================================

@router.get("/admin/queue")
async def staff_queue(request: Request):
    """Pending items in the actor's scope: orders + withdrawals."""
    actor = await require_staff(request)
    order_q = {"status": {"$in": ["pending", "requires_double_approval"]}}
    wd_q = {"status": "pending"}
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            order_q["$or"] = [{"from_code": {"$in": allowed}}, {"to_code": {"$in": allowed}}]
            wd_q["currency"] = {"$in": allowed}
    orders = await db.orders.find(order_q, {"_id": 0}).sort("created_at", -1).to_list(500)
    withdrawals = await db.withdrawals.find(wd_q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"orders": orders, "withdrawals": withdrawals,
            "counts": {"orders": len(orders), "withdrawals": len(withdrawals)}}


# ============================================================
# Users management
# ============================================================

@router.get("/admin/users")
async def list_users(request: Request, q: Optional[str] = None,
                     role: Optional[str] = None,
                     limit: int = 1000, offset: int = 0):
    await require_staff(request)
    mongo_q = {}
    if q:
        rx = {"$regex": q, "$options": "i"}
        mongo_q["$or"] = [{"name": rx}, {"email": rx}]
    if role and role in ("normal", "vip", "employee", "admin"):
        mongo_q["role"] = role
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    total = await db.users.count_documents(mongo_q)
    docs = await db.users.find(mongo_q, {"_id": 0}).sort("created_at", -1).skip(offset).to_list(limit)
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
async def update_user(user_id: str, payload: UserUpdate, request: Request):
    requester = await require_staff(request)
    await _enforce_totp_step_up(requester, payload.totp_code, action_label="actualizar usuario")
    update = {k: v for k, v in payload.model_dump(exclude={"totp_code"}).items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Nada para actualizar")
    if requester.get("role") == "employee" and "role" in update and update["role"] in ("admin", "employee"):
        raise HTTPException(status_code=403, detail="Solo un admin puede asignar este rol")
    old_user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    await db.users.update_one({"user_id": user_id}, {"$set": update})
    new_user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    await log_action(db, requester, "user.update", "user", user_id,
                     summary=f"Usuario {new_user.get('email', '')} actualizado",
                     details={"changes": update,
                              "prev_role": old_user.get("role") if old_user else None})
    return new_user


@router.post("/admin/users/{user_id}/verify-email")
async def admin_verify_user_email(user_id: str, request: Request):
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
# Seed (dev / fresh install bootstrap)
# ============================================================

@router.post("/admin/seed")
async def seed_data(request: Request):
    await require_staff(request)
    # Import catalog models locally to avoid loading market router at module import time.
    from routes.market import Currency, ExchangeRate, Product

    if await db.currencies.count_documents({}) == 0:
        defaults = [
            {"code": "USDT", "name": "Tether", "type": "crypto", "symbol": "₮", "country": "", "is_active": True, "payment_account": "Wallet TRC20: TXxxxxxxxxxxxx"},
            {"code": "BTC", "name": "Bitcoin", "type": "crypto", "symbol": "₿", "country": "", "is_active": True, "payment_account": "Wallet: bc1qxxxxxxxx"},
            {"code": "USD", "name": "US Dollar (Zelle)", "type": "fiat", "symbol": "$", "country": "USA", "is_active": True, "payment_account": "Zelle: pagos@resilience.com"},
            {"code": "CUP", "name": "Peso Cubano", "type": "fiat", "symbol": "₱", "country": "Cuba", "is_active": True, "payment_account": ""},
            {"code": "BRL", "name": "Real Brasileño", "type": "fiat", "symbol": "R$", "country": "Brasil", "is_active": True, "payment_account": ""},
            {"code": "MXN", "name": "Peso Mexicano", "type": "fiat", "symbol": "$", "country": "México", "is_active": True, "payment_account": ""},
        ]
        for d in defaults:
            await db.currencies.insert_one(Currency(**d).model_dump())
    if await db.rates.count_documents({}) == 0:
        rates_default = [
            {"from_code": "USD", "to_code": "CUP", "rate_normal": 380, "rate_vip": 395},
            {"from_code": "USD", "to_code": "BRL", "rate_normal": 4.9, "rate_vip": 5.05},
            {"from_code": "USD", "to_code": "MXN", "rate_normal": 17.2, "rate_vip": 17.6},
            {"from_code": "USDT", "to_code": "CUP", "rate_normal": 378, "rate_vip": 393},
            {"from_code": "USDT", "to_code": "USD", "rate_normal": 0.98, "rate_vip": 0.99},
        ]
        for d in rates_default:
            await db.rates.insert_one(ExchangeRate(**d).model_dump())
    if await db.products.count_documents({}) == 0:
        prods = [
            {"name": "Contenedor de Arroz (40 sacos)", "description": "Saco de 25kg, arroz blanco grado A.", "image_url": "https://images.unsplash.com/photo-1586201375761-83865001e31c?w=600", "price_usd": 1800, "stock": 5, "category": "alimentos"},
            {"name": "Contenedor de Harina (30 sacos)", "description": "Harina de trigo refinada, 25kg.", "image_url": "https://images.unsplash.com/photo-1574323347407-f5e1ad6d020b?w=600", "price_usd": 1200, "stock": 8, "category": "alimentos"},
            {"name": "Pallet de Refrescos (200 cajas)", "description": "Refrescos surtidos, lata 355ml.", "image_url": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=600", "price_usd": 900, "stock": 15, "category": "bebidas"},
            {"name": "Aceite Vegetal (Pallet 120L)", "description": "Aceite refinado en bidones.", "image_url": "https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?w=600", "price_usd": 550, "stock": 20, "category": "alimentos"},
        ]
        for d in prods:
            await db.products.insert_one(Product(**d).model_dump())
    return {"ok": True, "message": "Seed completado"}
