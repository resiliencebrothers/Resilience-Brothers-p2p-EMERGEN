"""Tiered payment (collection) accounts — iter143.

Collection `payment_accounts`: the destination accounts a client must send
their payment TO, selected automatically by the amount they will send:
    {id, currency_code, label, account_details, min_amount, max_amount?,
     is_active, created_at, updated_at}

Resolution rule (operator decision, Jun 2026): the ACTIVE account with the
HIGHEST `min_amount` <= amount (and amount <= max_amount when set) wins.
When the currency has no active tiered accounts, callers fall back to the
legacy free-text `currency.payment_account` field.
"""
from typing import Optional

from fastapi import HTTPException

from db_client import db


def pick_account(accounts: list[dict], amount: float) -> Optional[dict]:
    candidates = []
    for a in accounts:
        if not a.get("is_active", True):
            continue
        try:
            mn = float(a.get("min_amount") or 0.0)
        except (TypeError, ValueError):
            continue
        if amount < mn:
            continue
        mx = a.get("max_amount")
        if mx is not None and float(mx) > 0 and amount > float(mx):
            continue
        candidates.append((mn, a))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p[0], reverse=True)
    return candidates[0][1]


def min_required(accounts: list[dict]) -> Optional[float]:
    mins = [
        float(a.get("min_amount") or 0.0)
        for a in accounts if a.get("is_active", True)
    ]
    return min(mins) if mins else None


async def get_active_accounts(currency_code: str) -> list[dict]:
    code = (currency_code or "").strip().upper()
    if not code:
        return []
    return await db.payment_accounts.find(
        {"currency_code": code, "is_active": True}, {"_id": 0},
    ).to_list(100)


async def resolve_for_amount(currency_code: str, amount: Optional[float]) -> dict:
    accounts = await get_active_accounts(currency_code)
    required = min_required(accounts)
    amt = float(amount or 0.0)
    account = pick_account(accounts, amt) if amt > 0 else None
    return {
        "currency_code": (currency_code or "").strip().upper(),
        "has_tiers": len(accounts) > 0,
        "account": account,
        "min_required": required,
        "below_min": bool(accounts) and amt > 0 and required is not None and amt < required,
    }


async def assert_amount_meets_minimum(currency_code: str, amount: float) -> Optional[dict]:
    """Raise 400 when the currency has tiered accounts and no account matches
    the amount. Returns the resolved account (None when the currency has no
    tiered accounts — legacy behaviour applies)."""
    res = await resolve_for_amount(currency_code, amount)
    if not res["has_tiers"]:
        return None
    if res["account"] is None:
        req = res["min_required"]
        if res["below_min"] and req is not None:
            detail = (f"El monto mínimo para enviar {res['currency_code']} es "
                      f"{req:g}. Ajusta el monto para continuar.")
        else:
            detail = (f"No hay una cuenta de cobro disponible para ese monto en "
                      f"{res['currency_code']}. Contacta al equipo.")
        raise HTTPException(status_code=400, detail=detail)
    return res["account"]
