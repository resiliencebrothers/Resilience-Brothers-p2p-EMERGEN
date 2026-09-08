"""Helpers compartidos de cuentas de fondos (extraídos de
routes/company_fund_accounts.py para romper el ciclo de imports con
routes/admin_company_funds.py y routes/admin_withdrawals.py).
"""
import uuid
from typing import Any, Dict, List, Optional

from db_client import db
from auth_utils import iso, now_utc
from services.currency_utils import norm_code as _norm_code

HAS_ACC = {"$nin": [None, ""]}

# iter195 — company cash box. All physical cash (CUP / USD efectivo) enters
# and leaves this box automatically, per operator instruction.
CASH_BOX_NAME = "Fondo Resilience"


async def get_or_create_cash_box(currency: str) -> dict:
    """Return {id, label} of the company cash box for `currency`, creating
    (or reactivating) it lazily on first use."""
    code = _norm_code(currency)
    fa = await db.fund_accounts.find_one(
        {"currency": code, "name": CASH_BOX_NAME}, {"_id": 0})
    if fa:
        if not fa.get("is_active", True):
            await db.fund_accounts.update_one(
                {"id": fa["id"]}, {"$set": {"is_active": True}})
        return {"id": fa["id"], "label": fa.get("name") or fa["id"]}
    doc = {
        "id": f"facc_{uuid.uuid4().hex[:12]}",
        "name": CASH_BOX_NAME,
        "currency": code,
        "method": "cash",
        "note": "Caja de efectivo de la empresa (auto-creada)",
        "is_active": True,
        "created_at": iso(now_utc()),
        "created_by_id": "system",
        "created_by_name": "Sistema",
    }
    await db.fund_accounts.insert_one({**doc})
    return {"id": doc["id"], "label": doc["name"]}


async def auto_paid_from_account(
    currency: str, method: Optional[str] = None,
) -> Optional[dict]:
    """iter195 — auto-attribution when staff didn't pick an account:
    * method == "cash" → the company cash box (created lazily).
    * exactly ONE active account for the currency → that account.
    * otherwise → None (stays unassigned)."""
    code = _norm_code(currency)
    if not code:
        return None
    if method == "cash":
        return await get_or_create_cash_box(code)
    opts: List[dict] = []
    async for pa in db.payment_accounts.find(
        {"currency_code": code, "is_active": True},
        {"_id": 0, "id": 1, "label": 1},
    ):
        opts.append({"id": pa["id"], "label": pa.get("label") or pa["id"]})
    async for fa in db.fund_accounts.find(
        {"currency": code, "is_active": True},
        {"_id": 0, "id": 1, "name": 1},
    ):
        opts.append({"id": fa["id"], "label": fa.get("name") or fa["id"]})
    return opts[0] if len(opts) == 1 else None


async def resolve_fund_account(account_id: str) -> Optional[dict]:
    """Resolve a payment account (Cuentas de Cobro) or a custom fund account
    into a uniform {id, label, source, method, currency, is_active} dict."""
    if not account_id:
        return None
    pa = await db.payment_accounts.find_one({"id": account_id}, {"_id": 0})
    if pa:
        return {
            "id": pa["id"], "label": pa.get("label") or pa["id"],
            "source": "payment", "method": "bank",
            "currency": _norm_code(pa.get("currency_code")),
            "is_active": bool(pa.get("is_active", True)),
        }
    fa = await db.fund_accounts.find_one({"id": account_id}, {"_id": 0})
    if fa:
        return {
            "id": fa["id"], "label": fa.get("name") or fa["id"],
            "source": "custom", "method": fa.get("method") or "other",
            "currency": _norm_code(fa.get("currency")),
            "is_active": bool(fa.get("is_active", True)),
        }
    return None


async def account_assigned_balances(code: str) -> Dict[str, float]:
    """Per-account signed balance for `code` across every attributed source:
    order inflows, VIP batch inflows, tagged adjustments, transfers, and
    paid withdrawals attributed via `paid_from_account_id`."""
    totals: Dict[str, float] = {}

    def _add(acc_id: Any, amt: float) -> None:
        if not acc_id:
            return
        totals[acc_id] = totals.get(acc_id, 0.0) + amt

    async for o in db.orders.find(
        {"status": {"$in": ["approved", "completed"]}, "from_code": code,
         "payment_account_id": HAS_ACC},
        {"_id": 0, "payment_account_id": 1, "amount_from": 1},
    ):
        _add(o["payment_account_id"], float(o.get("amount_from") or 0.0))

    async for it in db.vip_batch_items.find(
        {"status": "approved", "from_code": code,
         "to_code": {"$nin": [None, ""]}, "payment_account_id": HAS_ACC},
        {"_id": 0, "payment_account_id": 1, "amount": 1},
    ):
        _add(it["payment_account_id"], float(it.get("amount") or 0.0))

    async for a in db.company_fund_adjustments.find(
        {"currency": code, "account_id": HAS_ACC},
        {"_id": 0, "account_id": 1, "amount": 1, "adjustment_type": 1},
    ):
        amt = float(a.get("amount") or 0.0)
        _add(a["account_id"], amt if a.get("adjustment_type") == "inflow" else -amt)

    async for tr in db.fund_account_transfers.find(
        {"currency": code},
        {"_id": 0, "from_account_id": 1, "to_account_id": 1, "amount": 1},
    ):
        amt = float(tr.get("amount") or 0.0)
        _add(tr.get("from_account_id"), -amt)
        _add(tr.get("to_account_id"), amt)

    async for w in db.withdrawals.find(
        {"status": "paid", "currency": code, "paid_from_account_id": HAS_ACC},
        {"_id": 0, "paid_from_account_id": 1, "amount_usd": 1},
    ):
        _add(w["paid_from_account_id"], -float(w.get("amount_usd") or 0.0))

    async for cw in db.company_withdrawals.find(
        {"status": "paid", "currency": code, "paid_from_account_id": HAS_ACC},
        {"_id": 0, "paid_from_account_id": 1, "amount": 1},
    ):
        _add(cw["paid_from_account_id"], -float(cw.get("amount") or 0.0))

    return totals
