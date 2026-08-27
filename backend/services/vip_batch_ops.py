"""Shared VIP-batch domain operations (ledger, totals, item decisions).

Extracted from routes/vip_batches.py to break the circular dependency
routes/vip_batches ↔ services/reconciliation_matcher: the matcher approves
batch items too, so the decision engine must live below the routes layer.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from db_client import db
from auth_utils import iso, now_utc
from services.balances import build_rate_lookup, convert_to_usdt
from services.rate_tiers import effective_rates
from services.vip_batch_alerts import dispatch_vip_batch_alerts

logger = logging.getLogger("vip_batch_ops")


def serialize_doc(doc: dict) -> dict:
    d = dict(doc)
    d.pop("_id", None)
    return d


async def ensure_ledger(vip_user_id: str) -> dict:
    doc = await db.vip_ledger.find_one({"vip_user_id": vip_user_id}, {"_id": 0})
    if doc:
        return doc
    fresh = {
        "vip_user_id": vip_user_id,
        "positive_usdt": 0.0,
        "negative_usdt": 0.0,
        "updated_at": iso(now_utc()),
    }
    await db.vip_ledger.insert_one(dict(fresh))
    return fresh


async def increment_ledger(vip_user_id: str, direction: str, delta_usdt: float) -> None:
    field = "positive_usdt" if direction == "credit" else "negative_usdt"
    await db.vip_ledger.update_one(
        {"vip_user_id": vip_user_id},
        {"$inc": {field: float(delta_usdt)},
         "$set": {"updated_at": iso(now_utc())}},
        upsert=True,
    )


async def refresh_batch_totals(batch_id: str) -> None:
    """Recompute the summary counters on the parent batch."""
    pipeline = [
        {"$match": {"batch_id": batch_id}},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
            "amount": {"$sum": "$amount"},
        }},
    ]
    rows = await db.vip_batch_items.aggregate(pipeline).to_list(10)
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    amount_pending = 0.0
    amount_approved = 0.0
    for r in rows:
        counts[r["_id"]] = r["count"]
        if r["_id"] == "pending":
            amount_pending = r["amount"]
        if r["_id"] == "approved":
            amount_approved = r["amount"]
    await db.vip_batches.update_one(
        {"id": batch_id},
        {"$set": {
            "items_pending": counts["pending"],
            "items_approved": counts["approved"],
            "items_rejected": counts["rejected"],
            "amount_pending": round(amount_pending, 2),
            "amount_approved": round(amount_approved, 2),
            "updated_at": iso(now_utc()),
        }},
    )


async def notify_vip_item_decision(item: dict, approved: bool, admin_note: str = "") -> None:
    try:
        from routes.notifications import _insert_notification
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_batch_ops] notif import failed: {e}")
        return
    if approved:
        title = "Orden VIP aprobada"
        if item.get("to_code"):
            credited = item.get("amount_to") or 0
            message = (f"{item['holder_name']} · {item['amount']} {item.get('from_code', '')} confirmada — "
                       f"se acreditaron {credited} {item['to_code']} a tu saldo.")
        else:
            message = f"{item['holder_name']} · {item['amount']} {item['currency']} confirmada."
    else:
        title = "Orden VIP rechazada"
        message = admin_note or f"{item['holder_name']} · {item['amount']} {item['currency']} rechazada."
    try:
        await _insert_notification(
            recipient_user_id=item["vip_user_id"],
            type="vip_batch_item_decision",
            title=title,
            message=message,
            data={"item_id": item["id"], "batch_id": item["batch_id"]},
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_batch_ops] vip notify failed: {e}")


async def current_pair_rates(from_code: str, to_code: str,
                             amount: Optional[float] = None) -> tuple:
    """Return (rate_vip, real_rate) for the pair — 0.0 when missing.
    iter143 — when `amount` is given and the rate row has amount `tiers`,
    the matching tier overrides the base rates."""
    doc = await db.rates.find_one(
        {"from_code": from_code, "to_code": to_code}, {"_id": 0},
    )
    if not doc:
        return (0.0, 0.0)
    eff = effective_rates(doc, amount)
    return (eff["rate_vip"], eff["real_rate"] or 0.0)


def staff_pair_allowed(staff: dict, item: dict) -> bool:
    """iter113 — per-pair staff RBAC. Admin always passes; employees with an
    empty/unset `allowed_batch_pairs` keep full access (backward compat);
    scoped employees can only work items whose pair is in their list.
    iter202 — sentinel "none" = explícitamente SIN acceso a ningún lote."""
    if staff.get("role") == "admin":
        return True
    allowed = staff.get("allowed_batch_pairs") or []
    if "none" in allowed:
        return False
    if not allowed:
        return True
    if not item.get("to_code"):
        return False  # legacy non-pair items reserved to unscoped staff/admin
    return f"{item.get('from_code')}->{item.get('to_code')}" in allowed


async def _approve_pair_item(item: dict, rates: dict) -> tuple:
    """iter113 — pair item: credit the VIP's per-currency balance at the
    snapshotted VIP rate and record the platform margin vs the real rate
    as revenue. Returns (balance_delta_usdt, extra_fields)."""
    amount_to = float(item.get("amount_to") or 0.0)
    rate_applied = float(item.get("rate_applied") or 0.0)
    item_amount = float(item.get("amount") or 0.0)
    if amount_to <= 0 or rate_applied <= 0:
        rate_applied, _ = await current_pair_rates(
            item["from_code"], item["to_code"], item_amount)
        if rate_applied <= 0:
            raise HTTPException(
                status_code=422,
                detail=(f"No hay tasa VIP para {item['from_code']}→{item['to_code']}. "
                        "Configúrala antes de aprobar."),
            )
        amount_to = round(float(item["amount"]) * rate_applied, 4)
    _, real_rate = await current_pair_rates(
        item["from_code"], item["to_code"], item_amount)
    margin_usdt = 0.0
    if real_rate > 0:
        margin_to = float(item["amount"]) * real_rate - amount_to
        margin_usdt = round(float(convert_to_usdt(margin_to, item["to_code"], rates) or 0.0), 4)
    await db.users.update_one(
        {"user_id": item["vip_user_id"]},
        {"$inc": {f"vip_balances.{item['to_code']}": amount_to}},
    )
    balance_delta = round(float(convert_to_usdt(amount_to, item["to_code"], rates) or 0.0), 4)
    extra = {
        "amount_to": amount_to,
        "rate_applied": rate_applied,
        "real_rate_applied": real_rate or None,
        "margin_usdt": margin_usdt,
        "credited_currency": item["to_code"],
    }
    return balance_delta, extra


async def _approve_legacy_item(item: dict, rates: dict) -> float:
    """Legacy single-currency item → old USDT ledger behavior."""
    delta = convert_to_usdt(item["amount"], item["currency"], rates)
    if delta is None:
        raise HTTPException(
            status_code=422,
            detail=(f"No hay tasa configurada para {item['currency']}. "
                    f"Añade una tasa {item['currency']}→USDT antes de aprobar."),
        )
    balance_delta = round(float(delta), 4)
    await increment_ledger(item["vip_user_id"], item["direction"], balance_delta)
    return balance_delta


async def _publish_item_decision_events(item: dict, item_id: str,
                                        decision: str) -> None:
    """iter117 — real-time refresh: the VIP dashboard (VipBatchesView) listens
    for `vip_batch_item_decision`; emit it for BOTH approve and reject."""
    try:
        from services.live_bus import publish as live_publish
        await live_publish(
            "vip_batch_item_decision",
            {"item_id": item_id, "batch_id": item["batch_id"], "decision": decision},
            user_id=item["vip_user_id"],
        )
        if decision == "approved" and item.get("to_code"):
            await live_publish(
                "balance_updated",
                {"reason": "vip_batch_item", "item_id": item_id,
                 "currency": item["to_code"]},
                user_id=item["vip_user_id"],
            )
            await live_publish(
                "ledger_changed",
                {"reason": "vip_batch_item", "item_id": item_id,
                 "user_id": item["vip_user_id"]},
                roles=("admin", "employee"),
            )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_batch_ops] SSE publish failed: {e}")


async def apply_item_decision(item_id: str, decision: str, staff: dict,
                              admin_note: str = "") -> dict:
    item = await db.vip_batch_items.find_one({"id": item_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Ítem no encontrado.")
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail="El ítem ya fue procesado.")
    if not staff_pair_allowed(staff, item):
        pair_lbl = (f"{item.get('from_code')}→{item.get('to_code')}"
                    if item.get("to_code") else item.get("currency", ""))
        raise HTTPException(
            status_code=403,
            detail=f"No estás autorizado a trabajar el par de lotes {pair_lbl}. Contacta al admin.",
        )

    now = iso(now_utc())
    balance_delta = None
    extra: dict = {}
    if decision == "approved":
        rates = await build_rate_lookup()
        if item.get("to_code"):
            balance_delta, extra = await _approve_pair_item(item, rates)
        else:
            balance_delta = await _approve_legacy_item(item, rates)

    await db.vip_batch_items.update_one(
        {"id": item_id},
        {"$set": {
            "status": decision,
            "updated_at": now,
            "reviewed_at": now,
            "reviewed_by": staff["user_id"],
            "admin_note": admin_note or None,
            "balance_delta_usdt": balance_delta,
            **extra,
        }},
    )
    await refresh_batch_totals(item["batch_id"])
    fresh = await db.vip_batch_items.find_one({"id": item_id}, {"_id": 0})
    if decision == "approved":
        # iter148 — massive-inflow threshold alerts on approval
        await dispatch_vip_batch_alerts(item["batch_id"], [fresh], "approved")
    await _publish_item_decision_events(item, item_id, decision)
    return fresh
