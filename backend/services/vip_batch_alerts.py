"""iter148 — Threshold alerts for VIP batch inflows (USDT-equivalent).

Operator decision (Jun 2026): alerts fire at BOTH stages ("added" when the
VIP adds items, "approved" when staff confirms them) and evaluate BOTH
criteria: any individual item >= `vip_threshold_usdt` AND the cumulative
batch total crossing it. Cumulative alerts re-fire only when the total
doubles since the last alert (markers `last_alert_total_usdt` /
`last_alert_approved_usdt` on the batch document) to avoid spamming admins
on every added row of an already-big batch.
"""
import logging
from typing import Optional

from db_client import db
from admin_alerts import notify_all_admins, get_vip_threshold
from services.balances import build_rate_lookup, convert_to_usdt

logger = logging.getLogger("vip_batch_alerts")

TOTAL_MARKER = {"added": "last_alert_total_usdt", "approved": "last_alert_approved_usdt"}


def _usdt_equiv(amount, code: str, rates: dict) -> Optional[float]:
    try:
        val = convert_to_usdt(float(amount or 0.0), (code or "").upper(), rates)
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def evaluate_threshold_events(batch: dict, new_items: list, threshold: float,
                              rates: dict, stage: str) -> list:
    """Pure decision logic — returns the list of alert events to fire.
    `batch` counters (amount_pending/amount_approved) must be fresh."""
    events: list = []
    if (batch.get("direction") or "") == "debit":
        return events
    code = (batch.get("from_code") or batch.get("currency") or "").upper()
    if not code:
        return events

    big = []
    for it in new_items:
        usdt = _usdt_equiv(it.get("amount"), code, rates)
        if usdt is not None and usdt >= threshold:
            big.append((it, usdt))
    if big:
        top_item, top_usdt = max(big, key=lambda p: p[1])
        events.append({
            "kind": "big_item",
            "stage": stage,
            "count": len(big),
            "max_amount": float(top_item.get("amount") or 0.0),
            "max_usdt": top_usdt,
            "labels": sorted({(it.get("payment_account_label") or "").strip()
                              for it, _ in big if it.get("payment_account_label")}),
        })

    total = float(batch.get("amount_approved") or 0.0)
    if stage == "added":
        total += float(batch.get("amount_pending") or 0.0)
    total_usdt = _usdt_equiv(total, code, rates)
    last = float(batch.get(TOTAL_MARKER[stage]) or 0.0)
    refire_floor = max(threshold, last * 2) if last > 0 else threshold
    if total_usdt is not None and total_usdt >= refire_floor:
        events.append({
            "kind": "batch_total",
            "stage": stage,
            "total": total,
            "total_usdt": total_usdt,
        })
    return events


def _pair_label(batch: dict) -> str:
    if batch.get("to_code"):
        return f"{batch.get('from_code')}→{batch.get('to_code')}"
    return batch.get("currency") or ""


def _fmt_labels(labels) -> str:
    return ", ".join(labels) if labels else "sin cuenta asignada"


def _event_texts(ev: dict, batch: dict, threshold: float, code: str) -> tuple:
    vip = batch.get("vip_name") or batch.get("vip_email") or batch.get("vip_user_id", "")
    pair = _pair_label(batch)
    labels = _fmt_labels(ev.get("labels"))
    if ev["kind"] == "big_item":
        if ev["stage"] == "added":
            title = "⚠️ Entrada masiva en lote VIP"
            body = (f"{vip} agregó {ev['count']} orden(es) que superan ${threshold:,.0f} USDT "
                    f"en el lote {pair}. Mayor: {ev['max_amount']:,.2f} {code} "
                    f"(≈${ev['max_usdt']:,.2f} USDT). Destino: {labels}.")
        else:
            title = "⚠️ Orden VIP masiva aprobada"
            body = (f"Se aprobó una orden de {ev['max_amount']:,.2f} {code} "
                    f"(≈${ev['max_usdt']:,.2f} USDT) en el lote {pair} de {vip}. "
                    f"Destino: {labels}.")
        return title, body
    if ev["stage"] == "added":
        title = "⚠️ Lote VIP supera umbral acumulado"
        verb = "acumula"
    else:
        title = "⚠️ Lote VIP: total aprobado supera umbral"
        verb = "acumula aprobado"
    body = (f"El lote {pair} de {vip} {verb} {ev['total']:,.2f} {code} "
            f"(≈${ev['total_usdt']:,.2f} USDT), sobre el umbral de ${threshold:,.0f}. "
            f"Cuentas destino: {labels}.")
    return title, body


async def _batch_account_labels(batch_id: str) -> list:
    labels = await db.vip_batch_items.distinct(
        "payment_account_label", {"batch_id": batch_id})
    return sorted(lbl for lbl in labels if lbl)


async def _notify_staff_inapp(title: str, message: str, data: dict) -> None:
    try:
        from routes.notifications import _insert_notification
        cursor = db.users.find(
            {"$or": [
                {"role": "admin"},
                {"role": "employee", "allowed_permissions": "orders"},
                {"role": "employee", "allowed_permissions": {"$in": [[], None]}},
            ]},
            {"_id": 0, "user_id": 1},
        )
        async for r in cursor:
            await _insert_notification(
                recipient_user_id=r["user_id"],
                type="vip_batch_threshold",
                title=title,
                message=message,
                data=data,
            )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_batch_alerts] in-app fanout failed: {e}")


async def dispatch_vip_batch_alerts(batch_id: str, new_items: list, stage: str) -> None:
    """Best-effort fanout (push + email + in-app) — never raises into the request path."""
    try:
        batch = await db.vip_batches.find_one({"id": batch_id}, {"_id": 0})
        if not batch:
            return
        threshold = await get_vip_threshold(db)
        rates = await build_rate_lookup()
        events = evaluate_threshold_events(batch, new_items, threshold, rates, stage)
        if not events:
            return
        code = (batch.get("from_code") or batch.get("currency") or "").upper()
        batch_labels = await _batch_account_labels(batch_id)
        for ev in events:
            if not ev.get("labels"):
                ev["labels"] = batch_labels
            if ev["kind"] == "batch_total":
                # mark BEFORE fanout so a delivery failure can't re-fire forever
                await db.vip_batches.update_one(
                    {"id": batch_id},
                    {"$set": {TOTAL_MARKER[stage]: ev["total_usdt"]}},
                )
            title, body = _event_texts(ev, batch, threshold, code)
            await notify_all_admins(db, title=title, body=body, url_path="/admin/vip-batches")
            await _notify_staff_inapp(title, body, {
                "batch_id": batch_id, "stage": stage, "kind": ev["kind"],
                "vip_user_id": batch.get("vip_user_id"),
            })
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_batch_alerts] dispatch failed for batch {batch_id}: {e}")
