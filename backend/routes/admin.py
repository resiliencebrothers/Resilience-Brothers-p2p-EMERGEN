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
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional, Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
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
from services.order_events import publish_order_status_sse

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
    auto_send_monthly_audit: Optional[bool] = Field(
        default=None,
        description="Si es False, desactiva el envío automático mensual del informe de auditoría (día 1 09:15 UTC). Cualquier otro valor = activo.",
    )
    auto_send_monthly_vip_ledger: Optional[bool] = Field(
        default=None,
        description="Si es False, desactiva el envío automático mensual del estado de cuenta VIP a todos los VIPs (día 1 09:30 UTC). Cualquier otro valor = activo.",
    )
    office_address: Optional[str] = Field(
        default=None, max_length=300,
        description="iter113 — Dirección de las oficinas de la empresa mostrada a clientes que depositan efectivo ≤ umbral de mensajería.",
    )
    cash_provinces: Optional[List[str]] = Field(
        default=None,
        description="iter192 — Provincias con disponibilidad de entrega de efectivo. None = todas disponibles.",
    )
    referral_bonus_pct: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="iter112 — % de la ganancia de la primera orden del referido que se acredita al referidor (USDT). Default 10.",
    )
    courier_rate_usdt_per_km: Optional[float] = Field(
        default=None, ge=0, le=1000,
        description="iter198 — Tarifa de mensajería (USDT por km) para retiros en efectivo. 0 = sin cobro.",
    )
    courier_free_min_usdt: Optional[float] = Field(
        default=None, ge=0,
        description="iter198 — Umbral en USDT equivalente a partir del cual la mensajería es gratis. Default 1000.",
    )
    courier_min_fee_usdt: Optional[float] = Field(
        default=None, ge=0, le=1000,
        description="iter198 — Tarifa mínima de mensajería (USDT). Default 2.00 (cubre los primeros 4 km).",
    )
    courier_share_pct: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="iter199 — % de la tarifa de mensajería que gana el mensajero. Default 80.",
    )
    office_latitude: Optional[float] = Field(
        default=None, ge=-90, le=90,
        description="iter198 — Latitud de la oficina Resilience Brothers (origen fijo de las entregas).",
    )
    office_longitude: Optional[float] = Field(
        default=None, ge=-180, le=180,
        description="iter198 — Longitud de la oficina Resilience Brothers.",
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

def _merge_or_clause(q: Dict[str, Any], clause: Dict[str, Any]) -> None:
    """AND a `$or` clause into the query without clobbering an existing one."""
    if "$and" in q:
        q["$and"].append(clause)
    elif "$or" in q:
        q["$and"] = [{"$or": q.pop("$or")}, clause]
    else:
        q["$or"] = clause["$or"]


def _orders_admin_query(actor: Dict[str, Any], status: Optional[str],
                        user_q: Optional[str], currency: Optional[str],
                        payment_account: Optional[str]) -> Dict[str, Any]:
    """Build the Mongo filter for the admin orders listing (incl. the
    employee `allowed_currencies` scope)."""
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if payment_account:
        q["payment_account_id"] = payment_account
    if currency:
        cur = currency.upper()
        q["$or"] = [{"from_code": cur}, {"to_code": cur}]
    if user_q:
        rx = {"$regex": re.escape(user_q), "$options": "i"}
        _merge_or_clause(q, {"$or": [{"user_name": rx}, {"user_email": rx}]})
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            _merge_or_clause(q, {"$or": [{"from_code": {"$in": allowed}},
                                         {"to_code": {"$in": allowed}}]})
    return q


@router.get("/admin/pending-counts")
async def admin_pending_counts(request: Request) -> Any:
    """iter191 — red sidebar badges: pending matters per admin section so
    staff notice queued work (e.g. withdrawal requests) without opening it."""
    await require_staff(request)
    wd = await db.withdrawals.count_documents({"status": "pending"})
    dep = await db.deposits.count_documents({"status": "pending"})
    cap = await db.capital_requests.count_documents({"status": "pending"})
    vip_items = await db.vip_batch_items.count_documents({"status": "pending"})
    orders = await db.orders.count_documents(
        {"status": {"$in": ["pending", "requires_double_approval"]}})
    recon = await db.bank_transactions.count_documents({"status": "manual_review"})
    return {
        "withdrawals": wd,
        "deposits": dep,
        "capital_requests": cap,
        "withdrawals_hub": wd + dep + cap,
        "vip_batches": vip_items,
        "orders": orders,
        "reconciliation": recon,
    }


@router.get("/admin/orders")
async def all_orders(request: Request, status: Optional[str] = None,
                     user_q: Optional[str] = None, currency: Optional[str] = None,
                     payment_account: Optional[str] = None,
                     limit: int = 1000, offset: int = 0) -> Any:
    actor = await require_permission(request, "orders")
    q = _orders_admin_query(actor, status, user_q, currency, payment_account)
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


def _detect_crypto_network_from_delivery(delivery_details: str) -> str:
    """Sniff TRC20/BEP20 from `delivery_details` (same heuristic used across
    the codebase). Returns '' when the network cannot be inferred."""
    delivery = (delivery_details or "").upper()
    if "TRC20" in delivery:
        return "TRC20"
    if "BEP20" in delivery:
        return "BEP20"
    return ""


def _validate_crypto_tx_hash(tx_hash: str, network: str) -> None:
    """iter55.19h — guard against copy-paste errors between explorers."""
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


def _collect_order_payout_evidence(payload: dict, update_doc: dict,
                                    order: Optional[dict] = None) -> None:
    """Persist optional payout proof image + tx hash on the update document.
    Used by staff/admin when marking an order as completed."""
    proof = payload.get("payout_proof_image")
    if proof:
        update_doc["payout_proof_image"] = maybe_upload_proof(proof, "order_payouts") or proof
    tx_hash = payload.get("payout_tx_hash")
    if not tx_hash:
        return
    tx_hash = tx_hash.strip()
    method = (order or {}).get("delivery_method") or ""
    if method == "crypto":
        network = _detect_crypto_network_from_delivery(
            (order or {}).get("delivery_details") or ""
        )
        if network:
            _validate_crypto_tx_hash(tx_hash, network)
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

    await publish_order_status_sse(order_id, updated, new_status, prev_status)

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


async def _assert_redemption_courier_ready(r: dict) -> None:
    """iter205 — mismo candado que retiros cash: un canje del mercado no se
    marca 'entregado' sin tarifa resuelta y sin que el mensajero haya
    realizado la entrega (delivered/confirmed)."""
    from services.courier_fee import quote_courier_fee
    cq = await quote_courier_fee("USD", float(r.get("total_usd") or 0.0))
    if not cq["enabled"]:
        return
    fee_charged = float(r.get("courier_fee_usdt") or 0) > 0
    if not cq["free"] and r.get("courier_fee_status") != "free" and not fee_charged:
        raise HTTPException(
            status_code=409,
            detail=("Mensajería sin cobrar: cobra el costo de la entrega de "
                    "este canje antes de marcarlo como entregado."))
    job = await db.deliveries.find_one(
        {"kind": "redemption", "ref_id": r["id"],
         "status": {"$ne": "cancelled"}}, {"_id": 0})
    if not job:
        raise HTTPException(
            status_code=409,
            detail=("No existe trabajo de mensajería para este canje. Créalo "
                    "en la sección Mensajería y espera a que el mensajero "
                    "confirme la entrega."))
    if job.get("status") not in ("delivered", "confirmed"):
        if not job.get("courier_id"):
            raise HTTPException(
                status_code=409,
                detail="Ningún mensajero ha tomado esta entrega todavía.")
        raise HTTPException(
            status_code=409,
            detail=(f"El mensajero {job.get('courier_name') or ''} aún no "
                    "marcó esta entrega como realizada."))


@router.put("/admin/redemptions/{rid}/status")
async def update_redemption(rid: str, payload: dict, request: Request) -> Any:
    actor = await require_permission(request, "orders")
    new_status = payload.get("status")
    note = payload.get("admin_note", "")
    if new_status not in ("approved", "delivered", "rejected", "pending"):
        raise HTTPException(status_code=400, detail="status inválido")
    r = await db.redemptions.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="No encontrado")
    if new_status == "delivered" and r["status"] != "delivered":
        await _assert_redemption_courier_ready(r)
    if new_status == "rejected" and r["status"] != "rejected":
        # iter198 — any charged courier fee is refunded with the product total.
        refund = r["total_usd"] + float(r.get("courier_fee_usd") or 0.0)
        await db.users.update_one(
            {"user_id": r["user_id"]}, {"$inc": {"vip_balance_usd": refund}}
        )
        await db.products.update_one(
            {"id": r["product_id"]}, {"$inc": {"stock": r["quantity"]}}
        )
        # iter205 — el canje rechazado cancela su trabajo de mensajería.
        try:
            from services.deliveries import cancel_active_delivery
            await cancel_active_delivery("redemption", rid,
                                         actor_id=actor.get("user_id"),
                                         note="canje rechazado")
        except Exception as e:
            logger.error(f"delivery cancel failed: {e}")
    await db.redemptions.update_one(
        {"id": rid}, {"$set": {"status": new_status, "admin_note": note}}
    )
    updated = await db.redemptions.find_one({"id": rid}, {"_id": 0})

    # iter55.23 — audit trail so "quién rechazó este canje?" can be answered.
    if new_status != r["status"]:
        await log_action(
            db, actor, f"redemption.{new_status}", "redemption", rid,
            summary=f"Canje {r.get('total_usd','?')} USD → {new_status}",
            details={
                "prev": r["status"],
                "new": new_status,
                "user_id": r.get("user_id"),
                "product_id": r.get("product_id"),
                "quantity": r.get("quantity"),
                "total_usd": r.get("total_usd"),
                "admin_note": note,
            },
        )
    return updated


async def _apply_courier_fee_balance_delta(r: dict, delta: float) -> None:
    """Charge (delta>0) or refund (delta<0) the fee difference in USD."""
    if delta > 0:
        owner = await db.users.find_one({"user_id": r["user_id"]}, {"_id": 0})
        from services.balances import get_user_balance, decrement_balance
        bal = get_user_balance(owner or {}, "USD")
        if bal < delta:
            raise HTTPException(
                status_code=400,
                detail=(f"Saldo insuficiente del cliente ({round(bal, 2)} USD) "
                        f"para cubrir la mensajería ({delta} USD)."))
        await decrement_balance(r["user_id"], "USD", delta)
    elif delta < 0:
        await db.users.update_one({"user_id": r["user_id"]},
                                  {"$inc": {"vip_balances.USD": -delta}})


async def _notify_redemption_courier_fee(r: dict, rid: str, km: float,
                                         fee_usdt: float, fee_usd: float,
                                         delta: float) -> None:
    try:
        from routes.notifications import _insert_notification
        if fee_usdt > 0:
            title = "Costo de mensajería aplicado"
            msg = (f"Se descontó {fee_usd} USD (≈ {fee_usdt} USDT · {km} km) de tu "
                   f"saldo por la entrega de tu canje «{r.get('product_name', '')}».")
        else:
            title = "Cobro de mensajería anulado"
            msg = (f"Se devolvió {abs(delta)} USD a tu saldo: el cobro de mensajería "
                   f"de tu canje «{r.get('product_name', '')}» fue anulado.")
        await _insert_notification(recipient_user_id=r["user_id"], type="courier_fee",
                                   title=title, message=msg,
                                   data={"redemption_id": rid, "km": km,
                                         "fee_usdt": fee_usdt})
    except Exception as e:
        logger.error(f"redemption courier fee notification failed: {e}")


async def _load_redemption_for_fee(rid: str) -> dict:
    """Fetch + guards del canje antes de cobrar mensajería."""
    r = await db.redemptions.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="No encontrado")
    if r.get("status") == "rejected":
        raise HTTPException(status_code=409,
                            detail="Canje rechazado — no se puede cobrar mensajería.")
    return r


async def _price_redemption_fee(payload: dict, r: dict) -> tuple:
    """Cálculo de la tarifa: por municipio fijo o por km.
    Returns (km, fee_usdt, fee_usd, muni_name, quote)."""
    from services.courier_fee import (
        parse_km_payload, price_charge_or_raise,
        price_charge_municipality_or_raise,
    )
    total = float(r.get("total_usd") or 0.0)
    muni_key = (payload.get("municipality") or "").strip()
    if muni_key:
        # iter211 — cobro por tarifa fija de municipio (mapa falló).
        q, fee_usdt, fee_usd, muni = await price_charge_municipality_or_raise(
            muni_key, "USD", total, op_label="Este canje")
        return 0.0, fee_usdt, fee_usd, muni["municipality"], q
    km = parse_km_payload(payload)
    q, fee_usdt, fee_usd = await price_charge_or_raise(
        km, "USD", total, op_label="Este canje")
    return km, fee_usdt, fee_usd, None, q


@router.post("/admin/redemptions/{rid}/courier-fee")
async def set_redemption_courier_fee(rid: str, payload: dict, request: Request) -> Any:
    """iter198 — charge (or update/annul with km=0) the courier fee of a
    marketplace delivery. Same engine as cash withdrawals: MAX(min, km×rate)
    in USDT, converted to USD and deducted from the client's balance."""
    actor = await require_permission(request, "orders")
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                 action_label="cobro de mensajería del mercado")
    r = await _load_redemption_for_fee(rid)
    km, fee_usdt, fee_usd, muni_name, q = await _price_redemption_fee(payload, r)
    prev_fee = float(r.get("courier_fee_usd") or 0.0)
    delta = round(fee_usd - prev_fee, 2)
    await _apply_courier_fee_balance_delta(r, delta)
    await db.redemptions.update_one({"id": rid}, {"$set": {
        "courier_km": km,
        "courier_fee_usdt": fee_usdt,
        "courier_fee_usd": fee_usd,
        "courier_municipality": muni_name,
        "courier_fee_status": "charged" if fee_usdt > 0 else "manual_review",
        "courier_rate_snapshot": q["rate_usdt_per_km"],
        "courier_min_fee_snapshot": q["min_fee_usdt"],
    }})
    updated = await db.redemptions.find_one({"id": rid}, {"_id": 0})
    # iter199 — keep the courier delivery job in sync with this charge.
    try:
        from services.deliveries import upsert_delivery_for_charge
        await upsert_delivery_for_charge("redemption", updated or r, km=km,
                                         fee_usdt=fee_usdt,
                                         actor_id=actor.get("user_id"))
    except Exception as e:
        logger.error(f"delivery sync failed: {e}")
    await log_action(
        db, actor, "redemption.courier_fee", "redemption", rid,
        summary=f"Mensajería {km} km → {fee_usdt} USDT ({fee_usd} USD) en canje {rid[:8]}",
        details={"km": km, "fee_usdt": fee_usdt, "fee_usd": fee_usd,
                 "prev_fee_usd": prev_fee, "delta": delta,
                 "user_id": r.get("user_id")},
    )
    await _notify_redemption_courier_fee(r, rid, km, fee_usdt, fee_usd, delta)
    return updated


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


def _sum_users_balances(users: list) -> Dict[str, float]:
    """Sum every currency across the user set, folding the legacy USD field."""
    totals: Dict[str, float] = {}
    for u in users:
        for code, amt in (u.get("vip_balances") or {}).items():
            totals[code] = totals.get(code, 0.0) + float(amt or 0.0)
        legacy = float(u.get("vip_balance_usd") or 0.0)
        if legacy > 0:
            totals["USD"] = totals.get("USD", 0.0) + legacy
    return totals


def _totals_to_usdt_breakdown(totals: Dict[str, float], rates: dict) -> tuple:
    """Convert each currency total to USDT and return (items, total_usdt)."""
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
    return items, round(total_usdt, 4)


async def _aggregate_vip_holdings(rates: dict) -> dict:
    """Sum vip_balances across all VIP/admin users and convert to USDT."""
    users = await db.users.find(
        {"role": {"$in": ["vip", "admin"]}}, {"_id": 0}
    ).to_list(1000)
    totals = _sum_users_balances(users)
    items, total_usdt = _totals_to_usdt_breakdown(totals, rates)
    return {"items": items, "total_usdt": total_usdt}


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
            "auto_send_monthly_audit": True,
            "auto_send_monthly_vip_ledger": True,
            "referral_bonus_pct": 10.0,
            "courier_rate_usdt_per_km": 0.5,
            "courier_free_min_usdt": 1000.0,
            "courier_min_fee_usdt": 2.0,
            "courier_share_pct": 80.0,
            "office_latitude": None,
            "office_longitude": None,
        }
    # Missing / non-False → treated as enabled (matches scheduler.py opt-out semantics)
    raw_flag = doc.get("auto_send_monthly_audit")
    raw_vip_flag = doc.get("auto_send_monthly_vip_ledger")
    raw_pct = doc.get("referral_bonus_pct")
    return {
        "vip_threshold_usdt": float(doc.get("vip_threshold_usdt", 5000)),
        "defensive_margin_pct": doc.get("defensive_margin_pct"),
        "ops_notifications_email": doc.get("ops_notifications_email"),
        "office_address": doc.get("office_address"),
        "cash_provinces": doc.get("cash_provinces"),
        "auto_send_monthly_audit": raw_flag is not False,
        "auto_send_monthly_vip_ledger": raw_vip_flag is not False,
        "referral_bonus_pct": float(raw_pct) if raw_pct is not None else 10.0,
        "courier_rate_usdt_per_km": float(doc.get("courier_rate_usdt_per_km")
                                          if doc.get("courier_rate_usdt_per_km") is not None else 0.5),
        "courier_free_min_usdt": float(doc.get("courier_free_min_usdt")
                                       if doc.get("courier_free_min_usdt") is not None else 1000.0),
        "courier_min_fee_usdt": float(doc.get("courier_min_fee_usdt")
                                      if doc.get("courier_min_fee_usdt") is not None else 2.0),
        "courier_share_pct": float(doc.get("courier_share_pct")
                                   if doc.get("courier_share_pct") is not None else 80.0),
        "office_latitude": doc.get("office_latitude"),
        "office_longitude": doc.get("office_longitude"),
    }


async def _validate_settings_payload(data: dict) -> dict:
    """Normalización + validaciones ligeras del payload de settings."""
    if "ops_notifications_email" in data:
        ops_email = (data.get("ops_notifications_email") or "").strip() or None
        if ops_email and ("@" not in ops_email or " " in ops_email):
            raise HTTPException(status_code=400, detail="ops_notifications_email no tiene un formato válido")
        data["ops_notifications_email"] = ops_email
    if "cash_provinces" in data and data["cash_provinces"] is not None:
        from routes.orders import CUBA_PROVINCES
        bad = [p for p in data["cash_provinces"] if p not in CUBA_PROVINCES]
        if bad:
            raise HTTPException(status_code=400,
                                detail=f"Provincias no válidas: {', '.join(bad)}")
    return data


@router.put("/admin/settings")
async def update_admin_settings(payload: AdminSettings, request: Request) -> Any:
    actor = await require_admin(request)
    await _enforce_totp_step_up(actor, payload.totp_code, action_label="actualizar configuración")
    data = await _validate_settings_payload(
        payload.model_dump(exclude={"totp_code"}, exclude_unset=True))
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


class TxnFilters:
    """FastAPI dependency that gathers all /admin/transactions* query params.
    Reduces each endpoint from 7 filter args to 1, and centralises validation.
    """

    def __init__(
        self,
        direction: Optional[str] = None,
        currency: Optional[str] = None,
        holder: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        client: Optional[str] = None,
    ):
        _validate_txn_filters(direction, min_amount, max_amount)
        self.direction = direction
        self.currency = currency
        self.holder = holder
        self.since = since
        self.until = until
        self.min_amount = min_amount
        self.max_amount = max_amount
        self.client = client

    async def build_items(self) -> list:
        return await build_transactions(
            self.direction, self.currency, self.holder,
            self.since, self.until, self.min_amount, self.max_amount,
            client=self.client,
        )

    def as_dict(self) -> dict:
        return {
            "direction": self.direction,
            "currency": self.currency,
            "holder": self.holder,
            "since": self.since,
            "until": self.until,
            "min_amount": self.min_amount,
            "max_amount": self.max_amount,
            "client": self.client,
        }


@router.get("/admin/transactions")
async def list_transactions(
    request: Request,
    filters: TxnFilters = Depends(),
    limit: int = 100,
    offset: int = 0,
) -> Any:
    await require_permission(request, "transactions")
    items = await filters.build_items()
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
async def export_transactions_csv(
    request: Request,
    filters: TxnFilters = Depends(),
) -> Any:
    await require_permission(request, "transactions")
    items = await filters.build_items()
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
async def export_transactions_pdf(
    request: Request,
    filters: TxnFilters = Depends(),
) -> Any:
    await require_permission(request, "transactions")
    items = await filters.build_items()
    totals = compute_transaction_totals(items)
    pdf_bytes = generate_transactions_pdf(items, filters.as_dict(), totals)
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
    """Pending items in the actor's scope: orders + withdrawals + VIP batches."""
    actor = await require_permission(request, "quick_view")
    order_q: Dict[str, Any] = {"status": {"$in": ["pending", "requires_double_approval"]}}
    wd_q: Dict[str, Any] = {"status": "pending"}
    # VIP batches show up when they still have items awaiting approval,
    # regardless of the parent batch's `open`/`closed` state (a closed
    # batch can still have pending items awaiting admin decision).
    vip_batch_q: Dict[str, Any] = {"items_pending": {"$gt": 0}}
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            order_q["$or"] = [{"from_code": {"$in": allowed}}, {"to_code": {"$in": allowed}}]
            wd_q["currency"] = {"$in": allowed}
            vip_batch_q["currency"] = {"$in": allowed}
    orders = await db.orders.find(order_q, {"_id": 0}).sort("created_at", -1).to_list(500)
    withdrawals = await db.withdrawals.find(wd_q, {"_id": 0}).sort("created_at", -1).to_list(500)
    vip_batches = await db.vip_batches.find(vip_batch_q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {
        "orders": orders,
        "withdrawals": withdrawals,
        "vip_batches": vip_batches,
        "counts": {
            "orders": len(orders),
            "withdrawals": len(withdrawals),
            "vip_batches": len(vip_batches),
        },
    }


# ============================================================
# Quick summary — mobile dashboard (iter45)
# ============================================================

async def _quick_pending_section(allowed: Optional[list]) -> Dict[str, Any]:
    """Pending orders + withdrawals counts and 5 most recent orders."""
    order_q: Dict[str, Any] = {"status": {"$in": ["pending", "requires_double_approval"]}}
    wd_q: Dict[str, Any] = {"status": "pending"}
    if allowed:
        order_q["$or"] = [{"from_code": {"$in": allowed}}, {"to_code": {"$in": allowed}}]
        wd_q["currency"] = {"$in": allowed}
    recent_orders = await db.orders.find(
        order_q,
        {"_id": 0, "id": 1, "from_code": 1, "to_code": 1,
         "amount_from": 1, "amount_to": 1, "created_at": 1, "user_email": 1},
    ).sort("created_at", -1).to_list(5)
    return {
        "orders_count": await db.orders.count_documents(order_q),
        "withdrawals_count": await db.withdrawals.count_documents(wd_q),
        "recent_orders": recent_orders,
    }


async def _quick_funds_section(allowed: Optional[list], rates: dict) -> Dict[str, Any]:
    """Per-currency working capital + USDT-equivalent total."""
    funds_items: List[Dict[str, Any]] = []
    funds_total_usdt = 0.0
    for row in await _compute_company_funds(allowed):
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
    return {"items": funds_items, "total_usdt": round(funds_total_usdt, 4)}


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
        allowed = actor.get("allowed_currencies") or None

    return {
        "pending": await _quick_pending_section(allowed),
        "company_funds": await _quick_funds_section(allowed, rates),
        "vip_holdings": await _aggregate_vip_holdings(rates),
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
            {"code": "USD", "name": "US Dollar (Zelle)", "type": "fiat", "symbol": "$", "country": "USA", "is_active": True, "payment_account": "Zelle: pagos@resilience.com", "is_convertible_to": False},
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
