"""Admin router — company funds (working capital + company withdrawals).

Extracted from routes/admin.py during the iter39 split. Tracks per-currency
working capital (inflows from confirmed orders − client payouts − company
payouts) and manages staff-initiated company withdrawals.
"""
import uuid
from typing import List, Literal, Optional, Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import (
    require_admin, require_staff,
    now_utc, iso,
    _enforce_employee_currency_scope, _enforce_totp_step_up,
)
from audit_log import log_action
from services.proof_upload import maybe_upload_proof


router = APIRouter(tags=["Admin"])


class CompanyFundAdjustment(BaseModel):
    """iter54 — Manual capital-of-trabajo movements recorded by admin/staff.

    - Type `inflow` (add capital to the company) — e.g., owner deposits 10M CUPT
    - Type `outflow` (withdraw own capital) — e.g., pay company expenses in cash

    Method distinguishes where the funds physically moved:
      - `transfer` → bank account (capture bank + account details)
      - `cash`     → physical cash (capture depositor/receiver name)
      - `crypto`   → wallet (capture blockchain address / tx hash)

    Recorded in `company_fund_adjustments` collection. Reflected as positive
    (inflow) or negative (outflow) in the per-currency balance calculation.
    """
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    adjustment_type: Literal["inflow", "outflow"]
    currency: str
    amount: float = Field(..., gt=0)
    method: Literal["transfer", "cash", "crypto"]
    source_name: str = Field(..., min_length=2, description="Persona, banco o wallet")
    source_account: str = Field(default="", description="Cuenta bancaria, dirección wallet, o vacío para cash")
    note: str = ""
    actor_id: str
    actor_email: str
    actor_name: str
    created_at: str = Field(default_factory=lambda: iso(now_utc()))


class CompanyFundAdjustmentCreate(BaseModel):
    adjustment_type: Literal["inflow", "outflow"]
    currency: str = Field(..., min_length=1, max_length=10)
    amount: float = Field(..., gt=0, le=1_000_000_000)
    method: Literal["transfer", "cash", "crypto"]
    source_name: str = Field(..., min_length=2, max_length=200)
    source_account: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=500)
    totp_code: Optional[str] = Field(None, max_length=11)


async def _assert_can_manage_company_funds(actor: dict) -> None:
    """iter54 — Admin always allowed; employees need can_manage_company_funds=True."""
    if actor.get("role") == "admin":
        return
    if actor.get("role") == "employee" and actor.get("can_manage_company_funds"):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "No tienes permiso para gestionar los fondos de la empresa. "
            "Pídeselo a un administrador."
        ),
    )


class CompanyWithdrawal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    amount: float
    currency: str
    beneficiary: str
    authorized_by_id: str
    authorized_by_name: str
    authorized_by_email: str
    concept: str = ""
    invoice_image: str = ""
    note: str = ""
    status: Literal["pending", "approved", "paid", "rejected"] = "pending"
    created_at: str = Field(default_factory=lambda: iso(now_utc()))


class CompanyWithdrawalCreate(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str
    beneficiary: str = Field(..., min_length=2)
    concept: str = ""
    invoice_image: str = ""
    note: str = ""
    totp_code: Optional[str] = Field(None, max_length=11)


async def _compute_company_funds(scope: Optional[List[str]] = None) -> List[dict]:
    """Per-currency platform working-capital balance.

    balance[c] = inflows_from_confirmed_orders[c]
                - outflow_orders[c]  (iter55 — order payouts to clients)
                - outflows_to_clients_paid[c]  (VIP balance withdrawals)
                - outflows_company_paid[c]
                + manual_inflow[c] - manual_outflow[c]
    `scope` (currency codes) optionally restricts the returned list.
    """
    inflow: dict = {}
    async for o in db.orders.find(
        {"status": {"$in": ["approved", "completed"]}},
        {"_id": 0, "from_code": 1, "amount_from": 1},
    ):
        c = o.get("from_code")
        if c:
            inflow[c] = inflow.get(c, 0.0) + float(o.get("amount_from") or 0.0)

    # iter55 — order payouts (money physically leaving the treasury when the
    # admin completes an order with a physical delivery method).
    # `accumulate` is not an outflow: the money stays in the treasury and is
    # tracked as VIP liability, which is settled via db.withdrawals below.
    out_orders: dict = {}
    async for o in db.orders.find(
        {"status": "completed", "delivery_method": {"$ne": "accumulate"}},
        {"_id": 0, "to_code": 1, "amount_to": 1},
    ):
        c = o.get("to_code")
        if c:
            out_orders[c] = out_orders.get(c, 0.0) + float(o.get("amount_to") or 0.0)

    out_clients: dict = {}
    async for w in db.withdrawals.find(
        {"status": "paid"}, {"_id": 0, "currency": 1, "amount_usd": 1}
    ):
        c = w.get("currency") or "USD"
        out_clients[c] = out_clients.get(c, 0.0) + float(w.get("amount_usd") or 0.0)

    out_company: dict = {}
    async for cw in db.company_withdrawals.find(
        {"status": "paid"}, {"_id": 0, "currency": 1, "amount": 1}
    ):
        c = cw.get("currency")
        if c:
            out_company[c] = out_company.get(c, 0.0) + float(cw.get("amount") or 0.0)

    # iter54 — manual capital-of-trabajo adjustments (inflows/outflows).
    manual_in: dict = {}
    manual_out: dict = {}
    async for a in db.company_fund_adjustments.find(
        {}, {"_id": 0, "currency": 1, "amount": 1, "adjustment_type": 1}
    ):
        c = a.get("currency")
        amt = float(a.get("amount") or 0.0)
        if not c or amt <= 0:
            continue
        if a.get("adjustment_type") == "inflow":
            manual_in[c] = manual_in.get(c, 0.0) + amt
        elif a.get("adjustment_type") == "outflow":
            manual_out[c] = manual_out.get(c, 0.0) + amt

    codes = (set(inflow) | set(out_orders) | set(out_clients) | set(out_company)
             | set(manual_in) | set(manual_out))
    rows = []
    for c in sorted(codes):
        if scope and c not in scope:
            continue
        i = inflow.get(c, 0.0)
        oo = out_orders.get(c, 0.0)
        oc = out_clients.get(c, 0.0)
        ok = out_company.get(c, 0.0)
        mi = manual_in.get(c, 0.0)
        mo = manual_out.get(c, 0.0)
        rows.append({
            "currency": c,
            "inflow": round(i, 4),
            "outflow_orders": round(oo, 4),
            "outflow_clients": round(oc, 4),
            "outflow_company": round(ok, 4),
            "manual_inflow": round(mi, 4),
            "manual_outflow": round(mo, 4),
            "balance": round(i + mi - oo - oc - ok - mo, 4),
        })
    return rows


@router.get("/admin/company-funds")
async def admin_company_funds(request: Request) -> Any:
    actor = await require_staff(request)
    scope = None
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            scope = allowed
    return await _compute_company_funds(scope)


@router.post("/admin/company-withdrawals")
async def create_company_withdrawal(payload: CompanyWithdrawalCreate, request: Request) -> Any:
    actor = await require_staff(request)
    currency = payload.currency.upper()
    _enforce_employee_currency_scope(actor, currency)
    await _enforce_totp_step_up(actor, payload.totp_code, action_label="retiro del fondo")
    funds = await _compute_company_funds([currency])
    avail = next((f["balance"] for f in funds if f["currency"] == currency), 0.0)
    if payload.amount > avail:
        raise HTTPException(
            status_code=400,
            detail=f"Fondo insuficiente en {currency}: disponible {avail:.2f}",
        )
    cw = CompanyWithdrawal(
        amount=payload.amount,
        currency=currency,
        beneficiary=payload.beneficiary,
        authorized_by_id=actor["user_id"],
        authorized_by_name=actor.get("name", ""),
        authorized_by_email=actor.get("email", ""),
        concept=payload.concept,
        invoice_image=(maybe_upload_proof(payload.invoice_image, "company_invoices")
                        or payload.invoice_image),
        note=payload.note,
    )
    await db.company_withdrawals.insert_one(cw.model_dump())
    await log_action(db, actor, "company_withdrawal.create", "company_withdrawal", cw.id,
                     summary=f"Retiro fondo {currency} {payload.amount} → {payload.beneficiary}",
                     details={"currency": currency, "amount": payload.amount,
                              "beneficiary": payload.beneficiary})
    return cw.model_dump()


@router.get("/admin/company-withdrawals")
async def list_company_withdrawals(request: Request,
                                     status: Optional[str] = None,
                                     currency: Optional[str] = None) -> Any:
    actor = await require_staff(request)
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if currency:
        q["currency"] = currency.upper()
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            if "currency" in q and q["currency"] not in allowed:
                return []
            elif "currency" not in q:
                q["currency"] = {"$in": allowed}
    docs = await db.company_withdrawals.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@router.put("/admin/company-withdrawals/{cwid}/status")
async def update_company_withdrawal(cwid: str, payload: dict, request: Request) -> Any:
    """Only admin can change status (approve/pay/reject). Staff with scope creates only."""
    actor = await require_admin(request)
    new_status = payload.get("status")
    if new_status not in ("approved", "paid", "rejected"):
        raise HTTPException(status_code=400, detail="status inválido")
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                 action_label="actualizar retiro de fondo")
    cw = await db.company_withdrawals.find_one({"id": cwid}, {"_id": 0})
    if not cw:
        raise HTTPException(status_code=404, detail="No encontrado")
    if cw["status"] == "paid" and new_status != "paid":
        raise HTTPException(status_code=403, detail="Ya fue pagado, no se puede revertir")
    update_doc = {"status": new_status}
    note = payload.get("note")
    if note is not None:
        update_doc["admin_note"] = note
    await db.company_withdrawals.update_one({"id": cwid}, {"$set": update_doc})
    await log_action(db, actor, "company_withdrawal.status", "company_withdrawal", cwid,
                     summary=f"Retiro fondo {cw['currency']} {cw['amount']} → {new_status}",
                     details={"from": cw["status"], "to": new_status})
    return await db.company_withdrawals.find_one({"id": cwid}, {"_id": 0})


# ============================================================
# iter54 — Capital-of-trabajo adjustments (manual inflows/outflows)
# ============================================================

@router.post("/admin/company-funds/adjustments")
async def create_company_fund_adjustment(
    payload: CompanyFundAdjustmentCreate, request: Request,
) -> Any:
    """Record a manual capital movement (inflow or outflow) into the company
    working-capital ledger. Reflected immediately in `/admin/company-funds`.

    Auth: admin OR employee with `can_manage_company_funds=True`.
    TOTP step-up required (money-moving action).
    """
    actor = await require_staff(request)
    await _assert_can_manage_company_funds(actor)
    await _enforce_totp_step_up(actor, payload.totp_code)

    currency = payload.currency.upper().strip()
    # Employees scope: can only touch their allowed_currencies
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed and currency not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"No estás autorizado a mover fondos en {currency}",
            )

    # Validate the currency exists in the catalog — use lenient lookup so
    # legacy rows with trailing whitespace (e.g. "CUP ") still resolve.
    from routes.market import _find_currency_lenient
    cur_doc = await _find_currency_lenient(currency)
    if not cur_doc:
        # Provide the operator the actual list of active currencies so the UI
        # dropdown mismatch is obvious.
        active = [c["code"].strip().upper() async for c in db.currencies.find(
            {"is_active": True}, {"_id": 0, "code": 1}
        )]
        raise HTTPException(
            status_code=400,
            detail=(
                f"Moneda «{currency}» no disponible en el catálogo. "
                f"Válidas: {', '.join(sorted(set(active)))}"
            ),
        )

    adjustment = CompanyFundAdjustment(
        adjustment_type=payload.adjustment_type,
        currency=currency,
        amount=payload.amount,
        method=payload.method,
        source_name=payload.source_name.strip(),
        source_account=payload.source_account.strip(),
        note=payload.note.strip(),
        actor_id=actor["user_id"],
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
    )
    doc = adjustment.model_dump()
    # insert_one mutates the input dict by adding `_id: ObjectId` — pass a copy
    # so the returned `doc` remains JSON-serialisable.
    await db.company_fund_adjustments.insert_one({**doc})

    sign = "+" if payload.adjustment_type == "inflow" else "-"
    await log_action(
        db, actor, "company_funds.adjust", "company_fund_adjustment", doc["id"],
        summary=(
            f"{sign}{payload.amount} {currency} "
            f"({payload.method}, {payload.adjustment_type}) desde {payload.source_name}"
        ),
        details={
            "adjustment_type": payload.adjustment_type,
            "currency": currency, "amount": payload.amount,
            "method": payload.method,
            "source_name": payload.source_name,
            "source_account": payload.source_account,
        },
    )
    return doc


@router.get("/admin/company-funds/adjustments")
async def list_company_fund_adjustments(
    request: Request, currency: Optional[str] = None, limit: int = 100,
) -> Any:
    """Return the history of manual capital movements. Employees scoped to
    their `allowed_currencies` (if any). Newest first."""
    actor = await require_staff(request)
    q: Dict[str, Any] = {}
    if currency:
        q["currency"] = currency.upper()
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            if "currency" in q and q["currency"] not in allowed:
                return []
            elif "currency" not in q:
                q["currency"] = {"$in": allowed}
    limit = max(1, min(limit, 500))
    return await db.company_fund_adjustments.find(q, {"_id": 0}).sort(
        "created_at", -1
    ).to_list(limit)
