"""Amount-tiered exchange rates — iter143.

A rate document may carry an optional `tiers` list:
    tiers: [{min_amount, rate_normal, rate_vip, real_rate?}, ...]

A tier applies when the SENT amount (amount_from) >= tier.min_amount; the
tier with the HIGHEST matching min_amount wins. When no tier matches (or
none is configured) the base rate_normal / rate_vip / real_rate on the
document apply. Mirrors the payment-account selection rule in
`services/payment_accounts.py` so account and rate always stay in sync.
"""
from typing import Any, Optional


def normalize_tiers(raw: Any) -> list[dict]:
    """Valid tier dicts sorted by min_amount DESC (highest first)."""
    if not isinstance(raw, list):
        return []
    out = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        try:
            mn = float(t.get("min_amount") or 0)
        except (TypeError, ValueError):
            continue
        if mn < 0:
            continue
        out.append(t)
    out.sort(key=lambda t: float(t["min_amount"]), reverse=True)
    return out


def pick_tier(rate_doc: Optional[dict], amount: Optional[float]) -> Optional[dict]:
    if not rate_doc or amount is None:
        return None
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return None
    for tier in normalize_tiers(rate_doc.get("tiers")):
        if amt >= float(tier["min_amount"]):
            return tier
    return None


def _positive(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def effective_rates(rate_doc: Optional[dict], amount: Optional[float]) -> dict:
    """{rate_normal, rate_vip, real_rate} applying the matching tier (if any).
    Tier fields fall back to the base document values when absent/invalid."""
    base = rate_doc or {}
    tier = pick_tier(base, amount) or {}
    return {
        "rate_normal": _positive(tier.get("rate_normal")) or float(base.get("rate_normal") or 0.0),
        "rate_vip": _positive(tier.get("rate_vip")) or float(base.get("rate_vip") or 0.0),
        "real_rate": _positive(tier.get("real_rate")) or _positive(base.get("real_rate")),
    }
