"""Money — rate lookup, USDT conversion, user balance helpers, defensive mode
and account-status guards. Extracted from server.py during iter33 refactor.

Pure business helpers, no HTTP layer; the only side effect is MongoDB I/O via
the shared `db_client`.
"""
from typing import Optional
from datetime import datetime, timezone

from fastapi import HTTPException

from db_client import db


# ============================================================
# Rate lookup + USDT conversion
# ============================================================

async def build_rate_lookup() -> dict:
    """Return rate lookup dict { (from,to): rate_normal } for conversion."""
    docs = await db.rates.find({}, {"_id": 0}).to_list(1000)
    return {(d["from_code"], d["to_code"]): float(d["rate_normal"]) for d in docs}


def _convert_direct(amount: float, code: str, rates: dict) -> Optional[float]:
    """Try inverse `USDT→code` first (canonical *valuation* rate used by the
    operator), falling back to direct `code→USDT` if no inverse is available.

    Rationale: when displaying a user balance in USDT-equivalent terms (or when
    checking the VIP threshold), we want the "buy-back" valuation rate the
    operator quotes — i.e. *how much USDT would I need to buy this balance*.
    The direct `code→USDT` rate is an order-execution price (the spread the
    operator applies when *receiving* USDT for code), which would understate
    holdings. Order-creation code paths use the dedicated rate-lookup logic in
    `resolve_order_rate` and are unaffected by this preference.
    """
    inverse = rates.get(("USDT", code))
    if inverse and inverse > 0:
        return amount / inverse
    if (code, "USDT") in rates:
        return amount * rates[(code, "USDT")]
    return None


def _convert_via_usd(amount: float, code: str, rates: dict) -> Optional[float]:
    """Convert code → USD → USDT. Returns None if no path."""
    usd_val = None
    if (code, "USD") in rates:
        usd_val = amount * rates[(code, "USD")]
    else:
        inv = rates.get(("USD", code))
        if inv and inv > 0:
            usd_val = amount / inv
    if usd_val is None:
        return None
    direct = _convert_direct(usd_val, "USD", rates)
    if direct is not None:
        return direct
    return usd_val  # assume 1 USD ≈ 1 USDT if no rate found


def convert_to_usdt(amount: float, code: str, rates: dict) -> Optional[float]:
    """Convert amount in `code` to USDT using available rates. Returns None if no path."""
    if amount == 0:
        return 0.0
    if code == "USDT":
        return amount
    direct = _convert_direct(amount, code, rates)
    if direct is not None:
        return direct
    return _convert_via_usd(amount, code, rates)


async def compute_total_usdt(user_doc: dict) -> float:
    rates = await build_rate_lookup()
    balances = dict(user_doc.get("vip_balances") or {})
    legacy = float(user_doc.get("vip_balance_usd") or 0.0)
    if legacy > 0:
        balances["USD"] = balances.get("USD", 0.0) + legacy
    return sum((convert_to_usdt(amt, code, rates) or 0) for code, amt in balances.items())


# ============================================================
# Per-currency user balance manipulation
# ============================================================

def get_user_balance(user: dict, code: str) -> float:
    """Get user's balance in a specific currency. Merges legacy vip_balance_usd into USD."""
    bal = float((user.get("vip_balances") or {}).get(code, 0.0))
    if code == "USD":
        bal += float(user.get("vip_balance_usd") or 0.0)
    return bal


async def decrement_balance(user_id: str, code: str, amount: float) -> None:
    """Decrement a currency balance. For USD, prefer vip_balance_usd legacy field first."""
    if code == "USD":
        user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
        legacy = float(user.get("vip_balance_usd") or 0.0)
        if legacy >= amount:
            await db.users.update_one(
                {"user_id": user_id}, {"$inc": {"vip_balance_usd": -amount}}
            )
            return
        remainder = amount - legacy
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"vip_balance_usd": 0.0},
             "$inc": {f"vip_balances.{code}": -remainder}},
        )
    else:
        await db.users.update_one(
            {"user_id": user_id}, {"$inc": {f"vip_balances.{code}": -amount}}
        )


async def accumulate_vip_balance(order: dict) -> bool:
    """Credit a VIP per-currency balance for an `accumulate` order.

    Idempotent: marks the order with `accumulated_at` on first credit and
    refuses to credit a second time. Returns True if a credit was applied,
    False if the order was already credited.

    iter51 — required so any first transition into a "money-settled" status
    (`approved` OR `completed`, including a direct pending→completed jump
    from the admin's "Completar" button) credits exactly once.
    """
    res = await db.orders.update_one(
        {"id": order["id"], "accumulated_at": {"$exists": False}},
        {"$set": {"accumulated_at": datetime.now(timezone.utc).isoformat()}},
    )
    if res.modified_count == 0:
        # Either the order already had `accumulated_at`, or the order id
        # doesn't exist — in both cases we MUST NOT double-credit.
        return False
    # iter55.32 — capital-request auto-discount: if this user has any active
    # (disbursed) capital debt in the SAME currency this order accumulates
    # into, deduct a % from the credited amount and use it to pay down the
    # oldest debt first (FIFO). We do this BEFORE crediting the balance so
    # the operator never sees a "money-in / money-out" ping-pong.
    net_amount = await _apply_capital_request_repayment(
        order["user_id"], order["to_code"], float(order["amount_to"]), order["id"],
    )
    if net_amount <= 0:
        # 100% of the credit went to repay debt — nothing to add to balance.
        return True
    await db.users.update_one(
        {"user_id": order["user_id"]},
        {"$inc": {f"vip_balances.{order['to_code']}": net_amount}},
    )
    return True


async def _apply_capital_request_repayment(user_id: str, currency: str,
                                             amount: float, order_id: str) -> float:
    """iter55.32 — pay down active capital debts before crediting an
    accumulated order. Returns the NET amount that should be credited to
    the VIP's balance (original minus deductions).

    Rules:
      - Only requests with `status='disbursed'` and matching `currency_code`
        are considered.
      - FIFO: oldest disbursed-first.
      - Each order is discounted ONCE by the OLDEST active debt's
        `discount_pct`. That total budget is then FIFO-distributed across
        all active debts (older first) up to each debt's remaining amount.
        Rationale: multiple debts should not compound the discount — the
        VIP should never pay >`discount_pct` of any single order back.
      - When `debt_remaining` hits 0 → status flips to `paid_off`.
      - Repayment events are logged inside the request doc for audit.
      - If no active debt or amount <= 0, no-op returning the input amount.
    """
    if amount <= 0:
        return amount
    active = await db.capital_requests.find(
        {"user_id": user_id, "status": "disbursed", "currency_code": currency},
        {"_id": 0},
    ).sort("disbursed_at", 1).to_list(50)
    if not active:
        return amount

    # Total per-order discount budget is set by the OLDEST active debt.
    oldest_pct = float(active[0].get("discount_pct") or 0.0)
    if oldest_pct <= 0:
        return amount
    budget = round(amount * oldest_pct / 100.0, 4)
    if budget <= 0:
        return amount

    now_iso_ = datetime.now(timezone.utc).isoformat()
    for cr in active:
        if budget <= 0:
            break
        debt = float(cr.get("debt_remaining") or 0.0)
        if debt <= 0:
            continue
        contribution = round(min(budget, debt), 4)
        if contribution <= 0:
            continue
        new_debt = round(debt - contribution, 4)
        set_ops: dict = {"updated_at": now_iso_}
        inc_ops: dict = {}
        if new_debt <= 0.0001:
            # Force debt to zero + flip to paid_off. Cannot combine $inc and
            # $set on the same field, so we use pure $set here.
            set_ops.update({
                "status": "paid_off",
                "paid_off_at": now_iso_,
                "debt_remaining": 0.0,
            })
        else:
            inc_ops["debt_remaining"] = -contribution
        update: dict = {
            "$set": set_ops,
            "$push": {"repayment_events": {
                "order_id": order_id, "amount": contribution, "at": now_iso_,
            }},
        }
        if inc_ops:
            update["$inc"] = inc_ops
        await db.capital_requests.update_one({"id": cr["id"]}, update)
        budget = round(budget - contribution, 6)

    return round(amount - round(amount * oldest_pct / 100.0, 4) + budget, 6)


# ============================================================
# Account status + defensive mode
# ============================================================

DEFENSIVE_MODE_KEY = "defensive_mode"


async def get_defensive_mode() -> dict:
    doc = await db.system_config.find_one({"key": DEFENSIVE_MODE_KEY}, {"_id": 0})
    return doc or {
        "key": DEFENSIVE_MODE_KEY, "enabled": False, "reason": "",
        "enabled_at": None, "enabled_by_email": "",
    }


async def assert_not_defensive(action_label: str) -> None:
    state = await get_defensive_mode()
    if state.get("enabled"):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DEFENSIVE_MODE",
                "message": (f"La plataforma está en modo defensivo y temporalmente "
                            f"no acepta {action_label}. Intenta de nuevo en unos minutos."),
                "reason": state.get("reason", ""),
            },
        )


async def assert_account_active(user: dict) -> None:
    """Gate client operations (orders, withdrawals, redemptions) on account_status.
    Staff/admin always pass through."""
    if user.get("role") in ("admin", "employee"):
        return
    status = user.get("account_status", "active")
    if status == "active":
        return
    if status == "under_review":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ACCOUNT_UNDER_REVIEW",
                "message": ("Tu cuenta está bajo revisión. Un miembro del staff debe "
                            "verificar tu teléfono antes de poder operar. Contacta a "
                            "soporte para acelerar la verificación."),
            },
        )
    # blocked
    raise HTTPException(
        status_code=403,
        detail={
            "code": "ACCOUNT_BLOCKED",
            "message": "Tu cuenta está bloqueada. Si crees que es un error, contacta a soporte.",
        },
    )
