"""Transactions registry — shared helpers between /me/transactions and
/admin/transactions. Extracted from server.py during iter33 refactor.

Builds the unified transaction list (entradas = orders, salidas = withdrawals)
plus the date-range normalization used by the audit log queries.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from db_client import db


# Public alias — every entry in the unified transactions list shares this shape.
TransactionItem = Dict[str, Any]


# ============================================================
# Date helpers (also reused by audit log filtering)
# ============================================================

def normalize_audit_date(value: Optional[str], end_of_day: bool = False) -> Optional[str]:
    """Accept YYYY-MM-DD or full ISO; return ISO UTC string suitable for string compare."""
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        try:
            datetime.fromisoformat(v)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Fecha inválida: {value} (usa YYYY-MM-DD)")
        return f"{v}T23:59:59.999999+00:00" if end_of_day else f"{v}T00:00:00+00:00"
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(status_code=400, detail=f"Fecha inválida: {value}")
    return v


def date_range_query(since: Optional[str], until: Optional[str]) -> dict:
    """Build a created_at range filter using normalize_audit_date."""
    s = normalize_audit_date(since, end_of_day=False)
    u = normalize_audit_date(until, end_of_day=True)
    if not s and not u:
        return {}
    rng = {}
    if s:
        rng["$gte"] = s
    if u:
        rng["$lte"] = u
    return {"created_at": rng}


def build_audit_query(action: Optional[str], actor_id: Optional[str],
                      since: Optional[str], until: Optional[str]) -> Dict[str, Any]:
    q: Dict[str, Any] = {}
    if action:
        q["action"] = action
    if actor_id:
        q["actor_id"] = actor_id
    s = normalize_audit_date(since, end_of_day=False)
    u = normalize_audit_date(until, end_of_day=True)
    if s or u:
        rng: Dict[str, str] = {}
        if s:
            rng["$gte"] = s
        if u:
            rng["$lte"] = u
        q["created_at"] = rng
    return q


async def fetch_audit_entries(action: Optional[str], actor_id: Optional[str],
                              since: Optional[str], until: Optional[str],
                              limit: int) -> List[Dict[str, Any]]:
    q = build_audit_query(action, actor_id, since, until)
    limit = max(1, min(limit, 5000))
    return await db.audit_log.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)


# ============================================================
# Unified transactions registry
# ============================================================

def _order_to_entrada(o: dict) -> TransactionItem:
    return {
        "direction": "in",
        "currency": o["from_code"],
        "amount": float(o.get("amount_from", 0.0)),
        "holder_name": o.get("sender_name", ""),
        "client_name": o.get("user_name", ""),
        "client_email": o.get("user_email", ""),
        "method": o.get("delivery_method", ""),
        "status": o.get("status", ""),
        "ref_id": o.get("id", ""),
        "ref_type": "order",
        "created_at": o.get("created_at", ""),
        "proof_image": o.get("proof_image", ""),
        "delivery_details": o.get("delivery_details", ""),
        "admin_note": o.get("admin_note", ""),
    }


def _withdrawal_to_salida(w: dict) -> TransactionItem:
    return {
        "direction": "out",
        "currency": w.get("currency", "USD"),
        "amount": float(w.get("amount_usd", 0.0)),
        "holder_name": w.get("beneficiary_name", ""),
        "client_name": w.get("user_name", ""),
        "client_email": w.get("user_email", ""),
        "method": w.get("method", ""),
        "status": w.get("status", ""),
        "ref_id": w.get("id", ""),
        "ref_type": "withdrawal",
        "created_at": w.get("created_at", ""),
        "proof_image": "",
        "delivery_details": w.get("details", ""),
        "admin_note": w.get("admin_note", ""),
        # iter55.19c — surface the on-chain network for crypto withdrawals so
        # the transactions registry (and PDF export) always know which chain.
        "crypto_network": w.get("crypto_network", ""),
    }


def _order_payout_to_salida(o: dict) -> TransactionItem:
    return {
        "direction": "out",
        "currency": o["to_code"],
        "amount": float(o.get("amount_to", 0.0)),
        "holder_name": o.get("user_name", ""),  # client receives the payout
        "client_name": o.get("user_name", ""),
        "client_email": o.get("user_email", ""),
        "method": o.get("delivery_method", ""),
        "status": o.get("status", ""),
        "ref_id": o.get("id", ""),
        "ref_type": "order_payout",
        "created_at": o.get("updated_at") or o.get("created_at", ""),
        "proof_image": o.get("payout_proof_image", ""),
        "delivery_details": o.get("delivery_details", ""),
        "admin_note": o.get("admin_note", ""),
    }


def _company_adjustment_to_transaction(a: dict) -> TransactionItem:
    """iter55.15 — Manual capital movements registered from /admin/company-funds
    (aportes propios y salidas manuales de capital). An `inflow` shows up as an
    entrada; an `outflow` as a salida. Holder is the source_name (banco, wallet,
    o persona que aportó el capital)."""
    direction = "in" if a.get("adjustment_type") == "inflow" else "out"
    note = a.get("note", "")
    account = a.get("source_account", "")
    # Combine source_account + note into delivery_details so the operator can
    # see the bank/wallet address alongside the free-form note in the register.
    details = " · ".join(x for x in (account, note) if x)
    return {
        "direction": direction,
        "currency": a.get("currency", ""),
        "amount": float(a.get("amount", 0.0)),
        "holder_name": a.get("source_name", ""),
        "client_name": a.get("actor_name", ""),  # the staff who booked the adjustment
        "client_email": a.get("actor_email", ""),
        "method": a.get("method", ""),
        "status": "approved",  # adjustments are immediate — always effective
        "ref_id": a.get("id", ""),
        "ref_type": "company_adjustment",
        "created_at": a.get("created_at", ""),
        "proof_image": "",
        "delivery_details": details,
        "admin_note": (
            f"Aporte propio ({a.get('method','')})" if direction == "in"
            else f"Salida de capital ({a.get('method','')})"
        ),
    }


def _company_withdrawal_to_salida(cw: dict) -> TransactionItem:
    """iter55.15 — Company-fund withdrawals (retiros del fondo empresa) that
    reached `approved` or `paid` status. These are money that physically left
    the company; the beneficiary is the recipient (proveedor, socio, gasto)."""
    return {
        "direction": "out",
        "currency": cw.get("currency", ""),
        "amount": float(cw.get("amount", 0.0)),
        "holder_name": cw.get("beneficiary", ""),
        "client_name": cw.get("authorized_by_name", ""),
        "client_email": cw.get("authorized_by_email", ""),
        "method": "transfer",  # company_withdrawals do not persist method today
        "status": cw.get("status", ""),
        "ref_id": cw.get("id", ""),
        "ref_type": "company_withdrawal",
        "created_at": cw.get("created_at", ""),
        "proof_image": cw.get("invoice_image", ""),
        "delivery_details": cw.get("concept", ""),
        "admin_note": cw.get("note", ""),
    }


async def _fetch_entradas_orders(date_q: dict, currency: Optional[str], holder: Optional[str],
                                 user_id: Optional[str]) -> List[TransactionItem]:
    q: dict = {
        "status": {"$in": ["approved", "completed"]},
        "sender_name": {"$nin": [None, ""]},
        **date_q,
    }
    if user_id:
        q["user_id"] = user_id
    if currency:
        q["from_code"] = currency
    if holder:
        q["sender_name"] = {"$regex": holder, "$options": "i"}
    rows = await db.orders.find(q, {"_id": 0}).to_list(5000)
    return [_order_to_entrada(o) for o in rows]


async def _fetch_salidas_withdrawals(date_q: dict, currency: Optional[str], holder: Optional[str],
                                     user_id: Optional[str]) -> List[TransactionItem]:
    q: dict = {
        "status": {"$in": ["approved", "paid"]},
        "beneficiary_name": {"$nin": [None, ""]},
        **date_q,
    }
    if user_id:
        q["user_id"] = user_id
    if currency:
        q["currency"] = currency
    if holder:
        q["beneficiary_name"] = {"$regex": holder, "$options": "i"}
    rows = await db.withdrawals.find(q, {"_id": 0}).to_list(5000)
    return [_withdrawal_to_salida(w) for w in rows]


async def _fetch_salidas_order_payouts(date_q: dict, currency: Optional[str], holder: Optional[str],
                                       user_id: Optional[str]) -> List[TransactionItem]:
    """iter55 — P2P order payouts (SALIDAS): when an order is completed and
    delivery_method is not "accumulate", the company physically paid the
    client. Register as an outbound transaction in the destination currency."""
    q: dict = {
        "status": "completed",
        "delivery_method": {"$in": ["transfer", "cash", "crypto"]},
        **date_q,
    }
    if user_id:
        q["user_id"] = user_id
    if currency:
        q["to_code"] = currency
    if holder:
        # holder for outbound P2P is the client themselves (destination account)
        q["$or"] = [
            {"user_name": {"$regex": holder, "$options": "i"}},
            {"delivery_details": {"$regex": holder, "$options": "i"}},
        ]
    rows = await db.orders.find(q, {"_id": 0}).to_list(5000)
    return [_order_payout_to_salida(o) for o in rows]


async def _fetch_company_adjustments(
    date_q: dict, currency: Optional[str], holder: Optional[str],
    direction: Optional[str],
) -> List[TransactionItem]:
    """iter55.15 — Manual capital movements (`company_fund_adjustments`).

    Only returned when `user_id is None` (see build_transactions) because these
    are company-level events, not owned by a specific client. `direction`
    controls whether we return inflows, outflows or both.
    """
    q: dict = {**date_q}
    if currency:
        q["currency"] = currency
    if holder:
        q["source_name"] = {"$regex": holder, "$options": "i"}
    if direction == "in":
        q["adjustment_type"] = "inflow"
    elif direction == "out":
        q["adjustment_type"] = "outflow"
    rows = await db.company_fund_adjustments.find(q, {"_id": 0}).to_list(5000)
    return [_company_adjustment_to_transaction(a) for a in rows]


async def _fetch_company_withdrawals(
    date_q: dict, currency: Optional[str], holder: Optional[str],
) -> List[TransactionItem]:
    """iter55.15 — Approved/paid `company_withdrawals` (retiros del fondo)."""
    q: dict = {
        "status": {"$in": ["approved", "paid"]},
        **date_q,
    }
    if currency:
        q["currency"] = currency
    if holder:
        q["beneficiary"] = {"$regex": holder, "$options": "i"}
    rows = await db.company_withdrawals.find(q, {"_id": 0}).to_list(5000)
    return [_company_withdrawal_to_salida(cw) for cw in rows]


async def build_transactions(direction: Optional[str], currency: Optional[str],
                             holder: Optional[str], since: Optional[str],
                             until: Optional[str],
                             min_amount: Optional[float] = None,
                             max_amount: Optional[float] = None,
                             user_id: Optional[str] = None) -> List[TransactionItem]:
    """Unified transaction list from approved/completed orders + approved/paid withdrawals.

    Each entry: {direction: 'in'|'out', currency, amount, holder_name, client_name,
                 method, status, ref_id, created_at}
    Only records with a non-empty holder/sender field are included.
    If user_id is provided, restricts to transactions owned by that user.
    """
    items: List[TransactionItem] = []
    date_q = date_range_query(since, until)

    if direction in (None, "all", "in"):
        items.extend(await _fetch_entradas_orders(date_q, currency, holder, user_id))

    if direction in (None, "all", "out"):
        items.extend(await _fetch_salidas_withdrawals(date_q, currency, holder, user_id))
        items.extend(await _fetch_salidas_order_payouts(date_q, currency, holder, user_id))

    # iter55.15 — Company-level capital events (aportes propios + retiros del
    # fondo). Only included in the ADMIN transactions register (no user_id
    # filter); the personal /me/transactions endpoint scopes by user_id and
    # therefore never surfaces these company-scope entries.
    if user_id is None:
        adj_dir = direction if direction in ("in", "out") else None
        items.extend(await _fetch_company_adjustments(date_q, currency, holder, adj_dir))
        if direction in (None, "all", "out"):
            items.extend(await _fetch_company_withdrawals(date_q, currency, holder))

    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    if min_amount is not None:
        items = [it for it in items if it["amount"] >= min_amount]
    if max_amount is not None:
        items = [it for it in items if it["amount"] <= max_amount]
    return items


def compute_transaction_totals(items: List[TransactionItem]) -> Dict[str, Any]:
    by_currency: Dict[str, Dict[str, Any]] = {}
    for it in items:
        cur = it["currency"]
        slot = by_currency.setdefault(cur, {"in": 0.0, "out": 0.0, "count": 0})
        slot[it["direction"]] += it["amount"]
        slot["count"] += 1
    for v in by_currency.values():
        v["in"] = round(v["in"], 4)
        v["out"] = round(v["out"], 4)
    return {"by_currency": by_currency, "total_count": len(items)}
