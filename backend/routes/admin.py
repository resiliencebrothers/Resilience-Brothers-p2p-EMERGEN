"""Admin router — core operations.

After the iter39 split this file owns only the cross-cutting admin endpoints:
- Defensive mode (public read + admin toggle)
- Orders / redemptions admin (list + status transitions)
- Platform stats + health summary
- Admin settings (vip threshold, defensive margin, ops notifications email)
- Transactions registry + CSV/PDF exports
- Staff queue
- Seed bootstrap

Domain-specific sub-routers live in:
- routes/admin_withdrawals.py
- routes/admin_users.py
- routes/admin_audit.py
- routes/admin_company_funds.py
- routes/admin_revenue.py     (also exposes `build_revenue_timeseries`)
"""
import csv
import io
import logging
import os
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional, Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import (
    require_admin, require_staff, require_permission,
    now_utc, iso,
    _enforce_totp_step_up,
)
from audit_log import log_action
from transactions_pdf import generate_transactions_pdf

from services.balances import (
    build_rate_lookup, convert_to_usdt,
    get_defensive_mode, DEFENSIVE_MODE_KEY,
)
from services.orders_helpers import (
    VALID_ORDER_STATUSES,
    authorize_status_transition, run_post_status_side_effects,
)
from services.proof_upload import maybe_upload_proof
from services.transactions import (
    build_transactions, compute_transaction_totals,
)
from services.health import build_health_summary

# Re-export so legacy importers (server.py startup wrapper) keep working.
from routes.admin_revenue import build_revenue_timeseries  # noqa: F401
from routes.admin_company_funds import _compute_company_funds


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Admin"])


# ============================================================
# Pydantic models
# ============================================================

class AdminSettings(BaseModel):
    vip_threshold_usdt: float = Field(default=5000.0, ge=0)
    defensive_margin_pct: Optional[float] = Field(default=None)
    ops_notifications_email: Optional[str] = Field(
        default=None, max_length=254,
        description="Bandeja única que recibe los emails operativos (nuevos órdenes, retiros, alertas). Si está vacío, cada admin recibe en su correo personal.",
    )
    totp_code: Optional[str] = Field(default=None, max_length=11,
                                       description="Código 2FA requerido")


class DefensiveModePayload(BaseModel):
    enabled: bool
    reason: Optional[str] = Field(None, max_length=500)
    totp_code: Optional[str] = Field(None, max_length=11)


# ============================================================
# System / Defensive mode
# ============================================================

@router.get("/system/defensive-mode")
async def public_defensive_mode() -> Any:
    """Public endpoint so the SPA can show the warning banner to everyone."""
    state = await get_defensive_mode()
    return {"enabled": bool(state.get("enabled")), "enabled_at": state.get("enabled_at")}


@router.post("/admin/defensive-mode/toggle")
async def admin_toggle_defensive_mode(payload: DefensiveModePayload, request: Request) -> Any:
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
                     limit: int = 1000, offset: int = 0) -> Any:
    actor = await require_permission(request, "orders")
    q: Dict[str, Any] = {}
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


def _collect_order_payout_evidence(payload: dict, update_doc: dict,
                                    order: dict = None) -> None:
    """Persist optional payout proof image + tx hash on the update document.
    Used by staff/admin when marking an order as completed.

    iter55.19h: for crypto orders we sniff the network from `delivery_details`
    (same heuristic used elsewhere) and validate the tx_hash format against
    that family — prevents copy-paste errors between explorers.
    """
    proof = payload.get("payout_proof_image")
    if proof:
        update_doc["payout_proof_image"] = maybe_upload_proof(proof, "order_payouts") or proof
    tx_hash = payload.get("payout_tx_hash")
    if tx_hash:
        tx_hash = tx_hash.strip()
        method = (order or {}).get("delivery_method") or ""
        if method == "crypto":
            delivery = ((order or {}).get("delivery_details") or "").upper()
            network = ""
            if "TRC20" in delivery:
                network = "TRC20"
            elif "BEP20" in delivery:
                network = "BEP20"
            if network:
                from services.crypto_networks import (
                    is_tx_hash_valid_for_network, tx_hash_mismatch_reason,
                )
                if not is_tx_hash_valid_for_network(tx_hash, network):
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "code": "TX_HASH_NETWORK_MISMATCH",
                            "message": tx_hash_mismatch_reason(tx_hash, network),
                            "network": network,
                        },
                    )
        update_doc["payout_tx_hash"] = tx_hash


def _validate_order_payout_evidence(order: dict, update_doc: dict, new_status: str) -> None:
    """When marking an order as completed, ensure the required payout artefact
    is present for transfer-method deliveries. Mirrors withdrawal validation
    (iter38). cash deliveries are exempt because there's no captured artefact."""
    if new_status != "completed" or order["status"] == "completed":
        return
    method = order.get("delivery_method")
    existing_proof = order.get("payout_proof_image") or update_doc.get("payout_proof_image")
    if method == "transfer" and not existing_proof:
        raise HTTPException(
            status_code=400,
            detail="Adjunta la captura del pago realizado al cliente antes de marcar como completada",
        )
    if method == "crypto":
        existing_hash = order.get("payout_tx_hash") or update_doc.get("payout_tx_hash")
        if not existing_hash and not existing_proof:
            raise HTTPException(
                status_code=400,
                detail="Adjunta hash de transacción y/o captura del envío al cliente antes de marcar como completada",
            )


@router.put("/admin/orders/{order_id}/status")
async def update_order_status(order_id: str, payload: dict, request: Request) -> Any:
    actor = await require_permission(request, "orders")
    new_status = payload.get("status")
    note = payload.get("admin_note", "")
    if new_status not in VALID_ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="status inválido")
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    await authorize_status_transition(actor, order, new_status, payload.get("totp_code"))

    prev_status = order["status"]
    update_doc = {"status": new_status, "admin_note": note,
                  "updated_at": iso(now_utc())}
    _collect_order_payout_evidence(payload, update_doc, order)
    _validate_order_payout_evidence(order, update_doc, new_status)

    await db.orders.update_one({"id": order_id}, {"$set": update_doc})
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
async def all_redemptions(request: Request) -> Any:
    await require_permission(request, "orders")
    docs = await db.redemptions.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@router.put("/admin/redemptions/{rid}/status")
async def update_redemption(rid: str, payload: dict, request: Request) -> Any:
    await require_permission(request, "orders")
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
    totals: Dict[str, float] = {}
    for u in users:
        for code, amt in (u.get("vip_balances") or {}).items():
            totals[code] = totals.get(code, 0.0) + float(amt or 0.0)
        legacy = float(u.get("vip_balance_usd") or 0.0)
        if legacy > 0:
            totals["USD"] = totals.get("USD", 0.0) + legacy
    items: List[Dict[str, Any]] = []
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
async def admin_platform_stats(request: Request) -> Any:
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
async def admin_health_summary(request: Request) -> Any:
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
async def get_admin_settings(request: Request) -> Any:
    await require_staff(request)
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0})
    if not doc:
        return {
            "vip_threshold_usdt": float(os.environ.get("VIP_ALERT_THRESHOLD_USDT", 5000)),
            "defensive_margin_pct": None,
            "ops_notifications_email": None,
        }
    return {
        "vip_threshold_usdt": float(doc.get("vip_threshold_usdt", 5000)),
        "defensive_margin_pct": doc.get("defensive_margin_pct"),
        "ops_notifications_email": doc.get("ops_notifications_email"),
    }


@router.put("/admin/settings")
async def update_admin_settings(payload: AdminSettings, request: Request) -> Any:
    actor = await require_admin(request)
    await _enforce_totp_step_up(actor, payload.totp_code, action_label="actualizar configuración")
    data = payload.model_dump(exclude={"totp_code"})
    # Normalise empty string → None and validate light email shape
    ops_email = (data.get("ops_notifications_email") or "").strip() or None
    if ops_email and ("@" not in ops_email or " " in ops_email):
        raise HTTPException(status_code=400, detail="ops_notifications_email no tiene un formato válido")
    data["ops_notifications_email"] = ops_email
    data["id"] = "global"
    await db.settings.update_one({"id": "global"}, {"$set": data}, upsert=True)
    await log_action(db, actor, "settings.update", "settings", "global",
                     summary="Settings actualizados", details=data)
    return {"ok": True, **data}


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
                            limit: int = 100, offset: int = 0) -> Any:
    await require_permission(request, "transactions")
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
                                  max_amount: Optional[float] = None) -> Any:
    await require_permission(request, "transactions")
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
                                  max_amount: Optional[float] = None) -> Any:
    await require_permission(request, "transactions")
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
# Staff queue
# ============================================================

@router.get("/admin/queue")
async def staff_queue(request: Request) -> Any:
    """Pending items in the actor's scope: orders + withdrawals."""
    actor = await require_permission(request, "quick_view")
    order_q: Dict[str, Any] = {"status": {"$in": ["pending", "requires_double_approval"]}}
    wd_q: Dict[str, Any] = {"status": "pending"}
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
# Quick summary — mobile dashboard (iter45)
# ============================================================

@router.get("/admin/quick-summary")
async def admin_quick_summary(request: Request) -> Any:
    """Compact payload for the mobile-first quick dashboard at /admin/quick.

    Combines what staff needs in 5 seconds: pendientes (orders+withdrawals
    counts and 5 most recent orders), company working-capital (per-currency
    + USDT-equivalent total) and VIP-accumulated balances (what we owe).

    Employee role respects `allowed_currencies` scope on every section.
    """
    actor = await require_permission(request, "quick_view")
    rates = await build_rate_lookup()

    # ---- scope filter (employee can only see currencies in allowed_currencies)
    allowed: Optional[list] = None
    if actor.get("role") == "employee":
        cur = actor.get("allowed_currencies") or []
        if cur:
            allowed = cur

    # ---- 1. Pendientes
    order_q: Dict[str, Any] = {"status": {"$in": ["pending", "requires_double_approval"]}}
    wd_q: Dict[str, Any] = {"status": "pending"}
    if allowed:
        order_q["$or"] = [{"from_code": {"$in": allowed}}, {"to_code": {"$in": allowed}}]
        wd_q["currency"] = {"$in": allowed}

    orders_count = await db.orders.count_documents(order_q)
    withdrawals_count = await db.withdrawals.count_documents(wd_q)
    recent_orders = await db.orders.find(
        order_q,
        {"_id": 0, "id": 1, "from_code": 1, "to_code": 1,
         "amount_from": 1, "amount_to": 1, "created_at": 1, "user_email": 1},
    ).sort("created_at", -1).to_list(5)

    # ---- 2. Company funds (per-currency working capital + USDT total)
    funds_rows = await _compute_company_funds(allowed)
    funds_items: List[Dict[str, Any]] = []
    funds_total_usdt = 0.0
    for row in funds_rows:
        code = row["currency"]
        bal = float(row.get("balance") or 0.0)
        usdt = convert_to_usdt(bal, code, rates)
        if usdt is not None:
            funds_total_usdt += usdt
        funds_items.append({
            "currency": code,
            "balance": bal,
            "usdt_equivalent": round(usdt, 4) if usdt is not None else None,
        })

    # ---- 3. VIP holdings (what we owe to clients)
    vip = await _aggregate_vip_holdings(rates)

    return {
        "pending": {
            "orders_count": orders_count,
            "withdrawals_count": withdrawals_count,
            "recent_orders": recent_orders,
        },
        "company_funds": {
            "items": funds_items,
            "total_usdt": round(funds_total_usdt, 4),
        },
        "vip_holdings": vip,
    }


# ============================================================
# Seed (dev / fresh install bootstrap)
# ============================================================

@router.post("/admin/seed")
async def seed_data(request: Request) -> Any:
    await require_staff(request)
    # Import catalog models locally to avoid loading market router at module import time.
    from routes.market import Currency, ExchangeRate, Product

    if await db.currencies.count_documents({}) == 0:
        defaults: List[Dict[str, Any]] = [
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
        rates_default: List[Dict[str, Any]] = [
            {"from_code": "USD", "to_code": "CUP", "rate_normal": 380, "rate_vip": 395},
            {"from_code": "USD", "to_code": "BRL", "rate_normal": 4.9, "rate_vip": 5.05},
            {"from_code": "USD", "to_code": "MXN", "rate_normal": 17.2, "rate_vip": 17.6},
            {"from_code": "USDT", "to_code": "CUP", "rate_normal": 378, "rate_vip": 393},
            {"from_code": "USDT", "to_code": "USD", "rate_normal": 0.98, "rate_vip": 0.99},
        ]
        for d in rates_default:
            await db.rates.insert_one(ExchangeRate(**d).model_dump())
    if await db.products.count_documents({}) == 0:
        prods: List[Dict[str, Any]] = [
            {"name": "Contenedor de Arroz (40 sacos)", "description": "Saco de 25kg, arroz blanco grado A.", "image_url": "https://images.unsplash.com/photo-1586201375761-83865001e31c?w=600", "price_usd": 1800, "stock": 5, "category": "alimentos"},
            {"name": "Contenedor de Harina (30 sacos)", "description": "Harina de trigo refinada, 25kg.", "image_url": "https://images.unsplash.com/photo-1574323347407-f5e1ad6d020b?w=600", "price_usd": 1200, "stock": 8, "category": "alimentos"},
            {"name": "Pallet de Refrescos (200 cajas)", "description": "Refrescos surtidos, lata 355ml.", "image_url": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=600", "price_usd": 900, "stock": 15, "category": "bebidas"},
            {"name": "Aceite Vegetal (Pallet 120L)", "description": "Aceite refinado en bidones.", "image_url": "https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?w=600", "price_usd": 550, "stock": 20, "category": "alimentos"},
        ]
        for d in prods:
            await db.products.insert_one(Product(**d).model_dump())
    return {"ok": True, "message": "Seed completado"}
