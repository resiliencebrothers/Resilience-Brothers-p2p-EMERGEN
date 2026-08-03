"""Shared order-profit math.

Extracted from services/orders_helpers.py to break the circular dependency
orders_helpers ⇄ referrals (both need this pure function). No DB access.
"""
from typing import Optional


async def compute_order_profit(order: dict, rate_doc: Optional[dict]) -> Optional[dict]:
    """Compute profit for a single approved/completed order in to_code currency.
    Profit logic: we receive amount_from in F, deliver amount_to in T.
    Real value of incoming = amount_from * real_rate (in T units).
    Profit (in T) = (amount_from * real_rate) - amount_to.
    """
    if not rate_doc or rate_doc.get("real_rate") is None:
        return None
    real_rate = float(rate_doc["real_rate"])
    if real_rate <= 0:
        return None
    real_value = order["amount_from"] * real_rate
    profit_to = real_value - order["amount_to"]
    profit_pct = (profit_to / real_value * 100) if real_value > 0 else 0.0
    return {
        "amount": profit_to,
        "currency": order["to_code"],
        "pct": round(profit_pct, 3),
    }
