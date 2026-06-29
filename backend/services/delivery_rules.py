"""Delivery method ↔ currency compatibility — single source of truth.

Used by:
- `routes/orders.py::_assert_delivery_method_matches_currency` (backend guardrail)
- `pages/dashboard/ExchangeView.jsx` (frontend filtered dropdown) — mirrored in JS

The rule layer is:
  1. If the currency declares `delivery_methods=[…]` explicitly → use that list.
  2. Else if `type == "crypto"` → ["crypto"] (wallet only; "accumulate" added separately for VIP).
  3. Else (fiat) → heuristic by name:
       - name/code contains "transferencia" / "transfer" / "banco" → ["transfer"]
       - name/code contains "efectivo" / "cash" → ["cash"]
       - otherwise both → ["transfer", "cash"]

The heuristic lets clients create custom sub-typed currencies (e.g.
"CUPT — Peso Cubano Transferencia", "CUPE — Peso Cubano Efectivo") without
having to wire the admin UI to flip a flag per currency.
"""
from __future__ import annotations
from typing import List


_TRANSFER_HINTS = ("transferencia", "transfer", "banco", "bank", "wire", "zelle", "pix")
_CASH_HINTS = ("efectivo", "cash", "domicilio", "billete")


def allowed_delivery_methods(currency: dict | None) -> List[str]:
    """Return the list of `delivery_method` strings valid for this destination
    currency. Does NOT include `accumulate` (that is always permitted and
    handled by the caller depending on user role)."""
    if not currency:
        return []
    declared = currency.get("delivery_methods") or []
    if isinstance(declared, list) and declared:
        return [m for m in declared if m in ("transfer", "cash", "crypto")]

    ctype = currency.get("type")
    if ctype == "crypto":
        return ["crypto"]

    # fiat — apply heuristic by name/code
    haystack = f"{currency.get('name', '')} {currency.get('code', '')}".lower()
    if any(h in haystack for h in _TRANSFER_HINTS):
        return ["transfer"]
    if any(h in haystack for h in _CASH_HINTS):
        return ["cash"]
    return ["transfer", "cash"]


def is_delivery_method_allowed(currency: dict | None, delivery_method: str) -> bool:
    """`accumulate` is always allowed (no physical delivery). Other methods
    must appear in the computed allow-list for this currency."""
    if delivery_method == "accumulate":
        return True
    return delivery_method in allowed_delivery_methods(currency)
