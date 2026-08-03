"""iter111 shared helpers — VIP ledger statement building blocks.

Extracted from `routes/vip_ledger_ops.py` and reused by both the route
handlers and the APScheduler monthly job, so both can compute ledger
movements without importing each other (breaks the circular dependency
introduced when the scheduler needed to read ledger movements).

Public surface:
  * DEFAULT_RANGE_DAYS  — default 90-day window when caller passes no dates.
  * _DATE_FMT           — ISO-YYYY-MM-DD used everywhere.
  * parse_date_or_400   — validate a user-supplied date string.
  * default_range       — apply the 90-day default when both dates missing.
  * collect_ledger_movements — DB fetch + running-balance projection.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from db_client import db

DEFAULT_RANGE_DAYS = 90
_DATE_FMT = "%Y-%m-%d"


def parse_date_or_400(v: Optional[str], name: str) -> Optional[datetime]:
    """Parse an optional YYYY-MM-DD string, raising 400 if malformed."""
    if not v:
        return None
    try:
        return datetime.strptime(v.strip(), _DATE_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Fecha inválida en '{name}'. Usa YYYY-MM-DD.",
        )


def default_range(from_date: Optional[str],
                  to_date: Optional[str]) -> tuple[str, str]:
    """When both are missing, return the last 90 days by default (agreed
    with the operator). If only one side is provided, respect the user
    input and leave the other open."""
    if not from_date and not to_date:
        today = datetime.now(timezone.utc).date()
        since = today - timedelta(days=DEFAULT_RANGE_DAYS)
        return since.strftime(_DATE_FMT), today.strftime(_DATE_FMT)
    return (from_date or "", to_date or "")


def _deposit_event(d: dict) -> dict:
    ts = d.get("reviewed_at") or d.get("updated_at") or d.get("created_at")
    delta = float(d.get("balance_delta_usdt") or 0.0)
    return {
        "created_at": ts,
        "kind": "deposit",
        "reference": (d.get("note") or "").strip() or d["id"],
        "amount": float(d["amount"]),
        "currency": d["currency"],
        "amount_usdt": delta,
        "_pos_delta": delta,
        "_neg_delta": 0.0,
    }


def _settlement_event(s: dict) -> dict:
    ts = s.get("reviewed_at") or s.get("updated_at") or s.get("created_at")
    delta = float(s.get("amount_usdt") or 0.0)
    is_payout = s["direction"] == "payout"
    return {
        "created_at": ts,
        "kind": s["direction"],
        "reference": (s.get("note") or "").strip() or s["id"],
        "amount": float(s["amount"]),
        "currency": s["currency"],
        "amount_usdt": delta,
        "_pos_delta": (-delta if is_payout else 0.0),
        "_neg_delta": (0.0 if is_payout else -delta),
    }


def _batch_item_event(it: dict) -> dict:
    ts = it.get("reviewed_at") or it.get("updated_at") or it.get("created_at")
    direction = it.get("direction")
    delta = float(it.get("balance_delta_usdt") or 0.0)
    return {
        "created_at": ts,
        "kind": "batch_credit" if direction == "credit" else "batch_debit",
        "reference": (it.get("holder_name") or "").strip() or it["id"],
        "amount": float(it["amount"]),
        "currency": it["currency"],
        "amount_usdt": delta,
        "_pos_delta": (delta if direction == "credit" else 0.0),
        "_neg_delta": (delta if direction == "debit" else 0.0),
    }


async def _fetch_events(vip_user_id: str) -> list[dict]:
    """Pull confirmed/approved rows from the 3 ledger-moving sources and
    normalise into a common event shape."""
    deposits = await db.vip_capital_deposits.find(
        {"vip_user_id": vip_user_id, "status": "confirmed"}, {"_id": 0},
    ).to_list(5000)
    settlements = await db.vip_settlements.find(
        {"vip_user_id": vip_user_id, "status": "confirmed"}, {"_id": 0},
    ).to_list(5000)
    items = await db.vip_batch_items.find(
        {"vip_user_id": vip_user_id, "status": "approved"}, {"_id": 0},
    ).to_list(20000)
    events = [_deposit_event(d) for d in deposits]
    events += [_settlement_event(s) for s in settlements]
    events += [_batch_item_event(it) for it in items]
    events.sort(key=lambda e: (e.get("created_at") or ""))
    return events


async def collect_ledger_movements(
    vip_user_id: str,
    from_dt: Optional[datetime],
    to_dt: Optional[datetime],
) -> tuple[float, float, list[dict]]:
    """Aggregate every ledger-moving row for a VIP.

    Returns (initial_positive, initial_negative, movements_in_range) where
    each movement dict already carries the running balance after itself.
    Only rows with terminal ledger-affecting status are considered.
    """
    events = await _fetch_events(vip_user_id)

    since_iso = from_dt.isoformat() if from_dt else None
    until_iso = (to_dt + timedelta(days=1)).isoformat() if to_dt else None

    initial_pos = 0.0
    initial_neg = 0.0
    running_pos = 0.0
    running_neg = 0.0
    movements: list[dict] = []
    for ev in events:
        ts = ev.get("created_at") or ""
        running_pos += ev["_pos_delta"]
        running_neg += ev["_neg_delta"]
        before_range = since_iso is not None and ts < since_iso
        after_range = until_iso is not None and ts >= until_iso
        if before_range:
            initial_pos = running_pos
            initial_neg = running_neg
            continue
        if after_range:
            continue
        movements.append({
            "created_at": ts,
            "kind": ev["kind"],
            "reference": ev["reference"],
            "amount": ev["amount"],
            "currency": ev["currency"],
            "amount_usdt": abs(ev["amount_usdt"]),
            "running_positive": round(running_pos, 2),
            "running_negative": round(running_neg, 2),
        })
    return round(initial_pos, 2), round(initial_neg, 2), movements
