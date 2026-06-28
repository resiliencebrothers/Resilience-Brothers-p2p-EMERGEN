"""Admin router — company funds (working capital + company withdrawals).

Extracted from routes/admin.py during the iter39 split. Tracks per-currency
working capital (inflows from confirmed orders − client payouts − company
payouts) and manages staff-initiated company withdrawals.
"""
import uuid
from typing import List, Literal, Optional

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
                - outflows_to_clients_paid[c]
                - outflows_company_paid[c]
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

    codes = set(inflow) | set(out_clients) | set(out_company)
    rows = []
    for c in sorted(codes):
        if scope and c not in scope:
            continue
        rows.append({
            "currency": c,
            "inflow": round(inflow.get(c, 0.0), 4),
            "outflow_clients": round(out_clients.get(c, 0.0), 4),
            "outflow_company": round(out_company.get(c, 0.0), 4),
            "balance": round(inflow.get(c, 0.0) - out_clients.get(c, 0.0) - out_company.get(c, 0.0), 4),
        })
    return rows


@router.get("/admin/company-funds")
async def admin_company_funds(request: Request):
    actor = await require_staff(request)
    scope = None
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            scope = allowed
    return await _compute_company_funds(scope)


@router.post("/admin/company-withdrawals")
async def create_company_withdrawal(payload: CompanyWithdrawalCreate, request: Request):
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
                                     currency: Optional[str] = None):
    actor = await require_staff(request)
    q = {}
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
async def update_company_withdrawal(cwid: str, payload: dict, request: Request):
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
