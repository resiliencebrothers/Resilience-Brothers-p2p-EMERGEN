"""iter194 — Company fund accounts (per-account treasury breakdown).

Hybrid model requested by the operator:
  * AUTOMATIC attribution — new orders / VIP batch items already snapshot the
    `payment_account_id` the client paid into, so their inflows are credited
    to that account.
  * MANUAL tools — custom fund accounts (cash boxes, personal Zelles, wallets),
    account-tagged manual adjustments, "paid from account" attribution on
    client/company withdrawals, and transfers between accounts (including the
    virtual "Sin asignar" bucket = card total − sum of assigned balances).

Collections:
  * `fund_accounts`           — operator-created accounts {id, name, currency, method…}
  * `fund_account_transfers`  — signed movements between accounts (None = unassigned)
"""
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import (
    require_staff, require_permission,
    now_utc, iso,
    _enforce_employee_currency_scope, _enforce_totp_step_up,
)
from audit_log import log_action
from services.currency_utils import norm_code as _norm_code
from services.company_funds_common import assert_can_manage_company_funds

router = APIRouter(tags=["Admin"])

_HAS_ACC = {"$nin": [None, ""]}

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


class FundAccountCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    currency: str = Field(..., min_length=1, max_length=10)
    method: Literal["bank", "cash", "crypto", "other"] = "bank"
    note: str = Field(default="", max_length=300)


class FundAccountUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    note: Optional[str] = Field(None, max_length=300)
    is_active: Optional[bool] = None


class FundTransferCreate(BaseModel):
    currency: str = Field(..., min_length=1, max_length=10)
    from_account_id: Optional[str] = None  # None → "Sin asignar"
    to_account_id: Optional[str] = None    # None → "Sin asignar"
    amount: float = Field(..., gt=0, le=1_000_000_000)
    note: str = Field(default="", max_length=300)
    totp_code: Optional[str] = Field(None, max_length=11)


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


async def _account_assigned_balances(code: str) -> Dict[str, float]:
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
         "payment_account_id": _HAS_ACC},
        {"_id": 0, "payment_account_id": 1, "amount_from": 1},
    ):
        _add(o["payment_account_id"], float(o.get("amount_from") or 0.0))

    async for it in db.vip_batch_items.find(
        {"status": "approved", "from_code": code,
         "to_code": {"$nin": [None, ""]}, "payment_account_id": _HAS_ACC},
        {"_id": 0, "payment_account_id": 1, "amount": 1},
    ):
        _add(it["payment_account_id"], float(it.get("amount") or 0.0))

    async for a in db.company_fund_adjustments.find(
        {"currency": code, "account_id": _HAS_ACC},
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
        {"status": "paid", "currency": code, "paid_from_account_id": _HAS_ACC},
        {"_id": 0, "paid_from_account_id": 1, "amount_usd": 1},
    ):
        _add(w["paid_from_account_id"], -float(w.get("amount_usd") or 0.0))

    async for cw in db.company_withdrawals.find(
        {"status": "paid", "currency": code, "paid_from_account_id": _HAS_ACC},
        {"_id": 0, "paid_from_account_id": 1, "amount": 1},
    ):
        _add(cw["paid_from_account_id"], -float(cw.get("amount") or 0.0))

    return totals


@router.get("/admin/fund-accounts/options")
async def fund_account_options(request: Request, currency: str) -> Any:
    """Lightweight {id, label} list for the account selectors (adjustments,
    withdrawal payout attribution). Gated by staff role only — labels are
    already visible to order/withdrawal staff elsewhere."""
    await require_staff(request)
    code = _norm_code(currency)
    if not code:
        raise HTTPException(status_code=400, detail="moneda inválida")
    rows: List[dict] = []
    async for pa in db.payment_accounts.find(
        {"currency_code": code, "is_active": True},
        {"_id": 0, "id": 1, "label": 1},
    ):
        rows.append({"id": pa["id"], "label": pa.get("label") or pa["id"]})
    async for fa in db.fund_accounts.find(
        {"currency": code, "is_active": True},
        {"_id": 0, "id": 1, "name": 1},
    ):
        rows.append({"id": fa["id"], "label": fa.get("name") or fa["id"]})
    return rows


@router.get("/admin/company-funds/accounts/{currency}")
async def fund_account_breakdown(currency: str, request: Request) -> Any:
    """Per-account breakdown of the currency's fund card. `unassigned` is the
    remainder (card gross balance − sum of assigned balances), so historical
    movements without account attribution never break the totals."""
    actor = await require_permission(request, "company_funds")
    code = _norm_code(currency)
    if not code:
        raise HTTPException(status_code=400, detail="moneda inválida")
    _enforce_employee_currency_scope(actor, code)

    from routes.admin_company_funds import _compute_company_funds
    rows = await _compute_company_funds([code])
    total = next((r["balance"] for r in rows if r["currency"] == code), 0.0)
    assigned = await _account_assigned_balances(code)

    accounts: List[dict] = []
    seen: set = set()
    async for pa in db.payment_accounts.find({"currency_code": code}, {"_id": 0}):
        seen.add(pa["id"])
        accounts.append({
            "id": pa["id"], "label": pa.get("label") or pa["id"],
            "source": "payment", "method": "bank",
            "is_active": bool(pa.get("is_active", True)),
            "balance": round(assigned.get(pa["id"], 0.0), 4),
        })
    async for fa in db.fund_accounts.find({"currency": code}, {"_id": 0}):
        seen.add(fa["id"])
        accounts.append({
            "id": fa["id"], "label": fa.get("name") or fa["id"],
            "source": "custom", "method": fa.get("method") or "other",
            "is_active": bool(fa.get("is_active", True)),
            "balance": round(assigned.get(fa["id"], 0.0), 4),
        })
    for acc_id, bal in assigned.items():
        if acc_id not in seen:
            accounts.append({
                "id": acc_id, "label": acc_id, "source": "unknown",
                "method": "other", "is_active": False,
                "balance": round(bal, 4),
            })
    accounts.sort(key=lambda a: -a["balance"])

    unassigned = total - sum(a["balance"] for a in accounts)
    transfers = await db.fund_account_transfers.find(
        {"currency": code}, {"_id": 0},
    ).sort("created_at", -1).to_list(30)

    return {
        "currency": code,
        "total_balance": round(total, 4),
        "accounts": accounts,
        "unassigned": round(unassigned, 4),
        "transfers": transfers,
    }


@router.post("/admin/company-funds/accounts")
async def create_fund_account(payload: FundAccountCreate, request: Request) -> Any:
    actor = await require_permission(request, "company_funds")
    await assert_can_manage_company_funds(actor)
    code = _norm_code(payload.currency)
    if not code:
        raise HTTPException(status_code=400, detail="moneda inválida")
    _enforce_employee_currency_scope(actor, code)

    from routes.market import _find_currency_lenient
    if not await _find_currency_lenient(code):
        raise HTTPException(
            status_code=400,
            detail=f"Moneda «{code}» no disponible en el catálogo",
        )
    name = payload.name.strip()
    dup = await db.fund_accounts.find_one(
        {"currency": code, "name": name, "is_active": True}, {"_id": 0, "id": 1},
    )
    if dup:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe una cuenta «{name}» en {code}",
        )
    doc = {
        "id": f"facc_{uuid.uuid4().hex[:12]}",
        "name": name,
        "currency": code,
        "method": payload.method,
        "note": payload.note.strip(),
        "is_active": True,
        "created_at": iso(now_utc()),
        "created_by_id": actor["user_id"],
        "created_by_name": actor.get("name", ""),
    }
    await db.fund_accounts.insert_one({**doc})
    await log_action(
        db, actor, "company_funds.account_create", "fund_account", doc["id"],
        summary=f"Cuenta de fondo «{name}» ({code}, {payload.method}) creada",
        details={"currency": code, "method": payload.method},
    )
    return doc


@router.put("/admin/company-funds/accounts/{account_id}")
async def update_fund_account(
    account_id: str, payload: FundAccountUpdate, request: Request,
) -> Any:
    actor = await require_permission(request, "company_funds")
    await assert_can_manage_company_funds(actor)
    fa = await db.fund_accounts.find_one({"id": account_id}, {"_id": 0})
    if not fa:
        raise HTTPException(
            status_code=404,
            detail="Cuenta no encontrada (las cuentas de cobro se editan en su módulo)",
        )
    _enforce_employee_currency_scope(actor, _norm_code(fa.get("currency")) or "")
    update: Dict[str, Any] = {}
    if payload.name is not None:
        update["name"] = payload.name.strip()
    if payload.note is not None:
        update["note"] = payload.note.strip()
    if payload.is_active is not None:
        update["is_active"] = payload.is_active
    if not update:
        return fa
    await db.fund_accounts.update_one({"id": account_id}, {"$set": update})
    await log_action(
        db, actor, "company_funds.account_update", "fund_account", account_id,
        summary=f"Cuenta de fondo «{fa.get('name')}» actualizada",
        details=update,
    )
    return await db.fund_accounts.find_one({"id": account_id}, {"_id": 0})


@router.post("/admin/company-funds/accounts/transfer")
async def transfer_between_fund_accounts(
    payload: FundTransferCreate, request: Request,
) -> Any:
    """Move balance between two accounts of the same currency. Either side
    may be None (= the "Sin asignar" bucket) so operators can distribute the
    historical unattributed balance into real accounts. TOTP step-up."""
    actor = await require_permission(request, "company_funds")
    await assert_can_manage_company_funds(actor)
    await _enforce_totp_step_up(actor, payload.totp_code,
                                action_label="transferencia entre cuentas")
    code = _norm_code(payload.currency)
    if not code:
        raise HTTPException(status_code=400, detail="moneda inválida")
    _enforce_employee_currency_scope(actor, code)

    frm = (payload.from_account_id or "").strip() or None
    to = (payload.to_account_id or "").strip() or None
    if frm == to:
        raise HTTPException(status_code=400,
                            detail="Origen y destino no pueden ser iguales")

    from_info = to_info = None
    if frm:
        from_info = await resolve_fund_account(frm)
        if not from_info:
            raise HTTPException(status_code=400, detail="Cuenta origen no encontrada")
        if from_info["currency"] and from_info["currency"] != code:
            raise HTTPException(
                status_code=400,
                detail=f"La cuenta origen es de {from_info['currency']}, no de {code}",
            )
    if to:
        to_info = await resolve_fund_account(to)
        if not to_info:
            raise HTTPException(status_code=400, detail="Cuenta destino no encontrada")
        if to_info["currency"] and to_info["currency"] != code:
            raise HTTPException(
                status_code=400,
                detail=f"La cuenta destino es de {to_info['currency']}, no de {code}",
            )

    assigned = await _account_assigned_balances(code)
    if frm:
        avail = assigned.get(frm, 0.0)
    else:
        from routes.admin_company_funds import _compute_company_funds
        rows = await _compute_company_funds([code])
        total = next((r["balance"] for r in rows if r["currency"] == code), 0.0)
        avail = total - sum(assigned.values())
    if payload.amount > avail + 1e-9:
        origin = from_info["label"] if from_info else "Sin asignar"
        raise HTTPException(
            status_code=400,
            detail=f"Saldo insuficiente en «{origin}»: disponible {avail:.2f} {code}",
        )

    doc = {
        "id": str(uuid.uuid4()),
        "currency": code,
        "from_account_id": frm,
        "from_label": from_info["label"] if from_info else "",
        "to_account_id": to,
        "to_label": to_info["label"] if to_info else "",
        "amount": payload.amount,
        "note": payload.note.strip(),
        "actor_id": actor["user_id"],
        "actor_name": actor.get("name", ""),
        "created_at": iso(now_utc()),
    }
    await db.fund_account_transfers.insert_one({**doc})
    await log_action(
        db, actor, "company_funds.account_transfer", "fund_account_transfer", doc["id"],
        summary=(
            f"Transferencia {payload.amount} {code}: "
            f"{doc['from_label'] or 'Sin asignar'} → {doc['to_label'] or 'Sin asignar'}"
        ),
        details={"currency": code, "amount": payload.amount,
                 "from_account_id": frm, "to_account_id": to},
    )
    return doc
