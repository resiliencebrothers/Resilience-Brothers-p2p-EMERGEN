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
    require_admin, require_permission,
    now_utc, iso,
    _enforce_employee_currency_scope, _enforce_totp_step_up,
)
from audit_log import log_action
from services.proof_upload import maybe_upload_proof


router = APIRouter(tags=["Admin"])


def _norm_code(c: Any) -> Optional[str]:
    """iter55.7 — Normalise a currency code by stripping whitespace and
    upper-casing. Returns None for empty/non-string inputs so callers can
    skip corrupted rows without polluting aggregations."""
    return c.strip().upper() if isinstance(c, str) and c.strip() else None


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
    """iter54 — Admin always allowed; employees need can_manage_company_funds=True
    OR (iter55.16) the `company_funds` permission code in allowed_permissions."""
    if actor.get("role") == "admin":
        return
    if actor.get("role") == "employee":
        perms = actor.get("allowed_permissions") or []
        if not perms or "company_funds" in perms:
            return
        if actor.get("can_manage_company_funds"):
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


async def _aggregate_by_currency(
    collection: Any,
    query: Dict[str, Any],
    currency_field: str,
    amount_field: str,
    default_currency: Optional[str] = None,
) -> Dict[str, float]:
    """Iterate `collection.find(query)` and sum `amount_field` grouped by
    normalised `currency_field`. Whitespace-only / missing currency codes
    fall back to `default_currency` (or are skipped when None).
    """
    projection = {"_id": 0, currency_field: 1, amount_field: 1}
    totals: Dict[str, float] = {}
    async for doc in collection.find(query, projection):
        code = _norm_code(doc.get(currency_field)) or default_currency
        if not code:
            continue
        totals[code] = totals.get(code, 0.0) + float(doc.get(amount_field) or 0.0)
    return totals


async def _aggregate_withdrawals_by_role(
    default_currency: str = "USD",
) -> tuple[Dict[str, float], Dict[str, float]]:
    """iter69 — Split paid withdrawals into two buckets by requesting user's
    role: `vip` (real VIP users) and `normal` (regular clients — who can also
    withdraw once they've accumulated a balance via order payouts).

    Returns (vip_totals, normal_totals) grouped by normalised currency code.
    Withdrawals from unknown / missing users fall into the `normal` bucket
    (safest for accounting — treat as regular client until proven VIP).
    """
    vip_totals: Dict[str, float] = {}
    normal_totals: Dict[str, float] = {}
    # Single $lookup pipeline is more efficient than N find_one calls.
    pipeline = [
        {"$match": {"status": "paid"}},
        {"$lookup": {
            "from": "users",
            "localField": "user_id",
            "foreignField": "user_id",
            "as": "_user",
        }},
        {"$project": {
            "_id": 0,
            "currency": 1,
            "amount_usd": 1,
            "role": {"$arrayElemAt": ["$_user.role", 0]},
        }},
    ]
    async for row in db.withdrawals.aggregate(pipeline):
        code = _norm_code(row.get("currency")) or default_currency
        amt = float(row.get("amount_usd") or 0.0)
        if not code or amt <= 0:
            continue
        bucket = vip_totals if row.get("role") == "vip" else normal_totals
        bucket[code] = bucket.get(code, 0.0) + amt
    return vip_totals, normal_totals


async def _aggregate_manual_adjustments() -> tuple[Dict[str, float], Dict[str, float]]:
    """Return (manual_inflows, manual_outflows) grouped by normalised currency."""
    manual_in: Dict[str, float] = {}
    manual_out: Dict[str, float] = {}
    async for a in db.company_fund_adjustments.find(
        {}, {"_id": 0, "currency": 1, "amount": 1, "adjustment_type": 1}
    ):
        code = _norm_code(a.get("currency"))
        amt = float(a.get("amount") or 0.0)
        if not code or amt <= 0:
            continue
        bucket = manual_in if a.get("adjustment_type") == "inflow" else manual_out
        bucket[code] = bucket.get(code, 0.0) + amt
    return manual_in, manual_out


async def _compute_company_funds(scope: Optional[List[str]] = None) -> List[dict]:
    """Per-currency platform working-capital balance.

    balance[c] = inflows_from_confirmed_orders[c]
                - outflow_orders[c]  (iter55 — order payouts to clients)
                - outflow_clients_vip[c] + outflow_clients_normal[c]  (paid client withdrawals)
                - outflow_company_paid[c]
                + manual_inflow[c] - manual_outflow[c]
    `scope` (currency codes) optionally restricts the returned list.

    iter55.7 — Every source code is `.strip().upper()`-normalised before
    aggregation so legacy rows with stray whitespace / mixed casing collapse
    into a single row instead of being split (operator report).

    iter69 — Client withdrawals now split by user role. Legacy consumers can
    still read the combined `outflow_clients` field (sum of vip + normal).
    """
    inflow = await _aggregate_by_currency(
        db.orders,
        {"status": {"$in": ["approved", "completed"]}},
        "from_code", "amount_from",
    )
    out_orders = await _aggregate_by_currency(
        db.orders,
        {"status": "completed", "delivery_method": {"$ne": "accumulate"}},
        "to_code", "amount_to",
    )
    out_clients_vip, out_clients_normal = await _aggregate_withdrawals_by_role()
    out_company = await _aggregate_by_currency(
        db.company_withdrawals,
        {"status": "paid"},
        "currency", "amount",
    )
    manual_in, manual_out = await _aggregate_manual_adjustments()

    codes = (set(inflow) | set(out_orders) | set(out_clients_vip) | set(out_clients_normal)
             | set(out_company) | set(manual_in) | set(manual_out))
    rows = []
    for c in sorted(codes):
        if scope and c not in scope:
            continue
        i = inflow.get(c, 0.0)
        oo = out_orders.get(c, 0.0)
        ocv = out_clients_vip.get(c, 0.0)
        ocn = out_clients_normal.get(c, 0.0)
        oc = ocv + ocn  # legacy field: total client withdrawals
        ok = out_company.get(c, 0.0)
        mi = manual_in.get(c, 0.0)
        mo = manual_out.get(c, 0.0)
        rows.append({
            "currency": c,
            "inflow": round(i, 4),
            "outflow_orders": round(oo, 4),
            "outflow_clients": round(oc, 4),
            "outflow_clients_vip": round(ocv, 4),
            "outflow_clients_normal": round(ocn, 4),
            "outflow_company": round(ok, 4),
            "manual_inflow": round(mi, 4),
            "manual_outflow": round(mo, 4),
            "balance": round(i + mi - oo - oc - ok - mo, 4),
        })
    return rows


@router.get("/admin/company-funds")
async def admin_company_funds(request: Request) -> Any:
    actor = await require_permission(request, "company_funds")
    scope = None
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            scope = allowed
    return await _compute_company_funds(scope)


@router.post("/admin/company-withdrawals")
async def create_company_withdrawal(payload: CompanyWithdrawalCreate, request: Request) -> Any:
    actor = await require_permission(request, "company_funds")
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
    actor = await require_permission(request, "company_funds")
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
    actor = await require_permission(request, "company_funds")
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
    actor = await require_permission(request, "company_funds")
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


# ============================================================
# iter88 — Company funds export
# ============================================================

def _date_range_query(since: Optional[str], until: Optional[str]) -> Dict[str, Any]:
    """Build a Mongo `$gte/$lte` `created_at` filter from ISO date/datetime
    strings. Dates without a time are expanded to include the whole day
    (00:00:00 → 23:59:59). Invalid input → 400."""
    from datetime import datetime as _dt
    q: Dict[str, Any] = {}
    def _parse(s: str, is_end: bool) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        try:
            if "T" in s:
                _dt.fromisoformat(s.replace("Z", "+00:00"))
                return s
            # Bare date → widen to full-day boundary.
            _dt.fromisoformat(s)
            return f"{s}T23:59:59.999999+00:00" if is_end else f"{s}T00:00:00.000000+00:00"
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Formato de fecha inválido: {s}")
    since_iso = _parse(since or "", is_end=False)
    until_iso = _parse(until or "", is_end=True)
    if since_iso and until_iso:
        q["created_at"] = {"$gte": since_iso, "$lte": until_iso}
    elif since_iso:
        q["created_at"] = {"$gte": since_iso}
    elif until_iso:
        q["created_at"] = {"$lte": until_iso}
    return q


@router.get("/admin/company-funds/export.csv")
async def export_company_funds_csv(
    request: Request,
    since: Optional[str] = None,
    until: Optional[str] = None,
    currency: Optional[str] = None,
) -> Any:
    """iter88 — Export a unified CSV of every company-fund movement in the
    requested date range. Includes both manual adjustments (inflows and
    outflows) and company withdrawals (all statuses so admins can audit
    pending/approved/paid/rejected). Employee scope is respected."""
    import csv
    import io
    from io import BytesIO
    from datetime import datetime, timezone
    from fastapi.responses import StreamingResponse

    actor = await require_permission(request, "company_funds")
    date_q = _date_range_query(since, until)

    # Employee currency scope — if `allowed_currencies` is set, only rows in
    # those currencies come through.
    scope_codes: Optional[List[str]] = None
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            scope_codes = [c.upper() for c in allowed]

    def _currency_ok(code: Any) -> bool:
        c = _norm_code(code)
        if not c:
            return False
        if currency and c != currency.upper():
            return False
        if scope_codes is not None and c not in scope_codes:
            return False
        return True

    rows: List[List[str]] = []

    # 1) Manual adjustments (inflow = +, outflow = -).
    async for a in db.company_fund_adjustments.find(date_q, {"_id": 0}):
        if not _currency_ok(a.get("currency")):
            continue
        amt = float(a.get("amount") or 0.0)
        direction = a.get("adjustment_type") or ""
        signed = amt if direction == "inflow" else -amt
        rows.append([
            a.get("created_at", ""),
            "adjustment",
            direction,
            _norm_code(a.get("currency")) or "",
            f"{signed:.4f}",
            a.get("source_name", ""),
            a.get("method", ""),
            (a.get("note") or ""),
            "completed",
            a.get("actor_name", ""),
            a.get("id", ""),
        ])

    # 2) Company withdrawals (status paid → applied, others → informational).
    async for w in db.company_withdrawals.find(date_q, {"_id": 0}):
        if not _currency_ok(w.get("currency")):
            continue
        amt = float(w.get("amount") or 0.0)
        status = w.get("status") or "pending"
        # Signed amount for accounting: paid outflows are negative; the
        # non-paid rows carry the raw absolute amount because they haven't
        # moved money yet.
        signed = -amt if status == "paid" else amt
        rows.append([
            w.get("created_at", ""),
            "company_withdrawal",
            "outflow",
            _norm_code(w.get("currency")) or "",
            f"{signed:.4f}",
            w.get("beneficiary", ""),
            "",  # method N/A for company_withdrawal
            (w.get("concept") or w.get("note") or ""),
            status,
            w.get("authorized_by_name", ""),
            w.get("id", ""),
        ])

    # Sort by date ascending so the CSV reads as a chronological ledger.
    rows.sort(key=lambda r: r[0])

    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    writer.writerow([
        "created_at", "movement_kind", "direction", "currency",
        "amount", "party", "method", "concept_or_note", "status",
        "authorized_by", "id",
    ])
    for row in rows:
        writer.writerow(row)

    buf = BytesIO()
    buf.write(text_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"company_funds_{ts}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── iter91 · Company accounting closing PDF ────────────────────────────
async def _aggregate_by_currency_ranged(
    collection: Any,
    query: Dict[str, Any],
    currency_field: str,
    amount_field: str,
    since_iso: str = "",
    until_iso: str = "",
    ts_field: str = "updated_at",
) -> Dict[str, float]:
    """Same shape as `_aggregate_by_currency` but constrains the docs by
    a timestamp range on `ts_field`. Empty bounds mean unbounded on that
    side, so passing since='' until='' matches the all-time aggregate."""
    scoped_query = {**query}
    ts_q: Dict[str, Any] = {}
    if since_iso:
        ts_q["$gte"] = since_iso
    if until_iso:
        ts_q["$lte"] = until_iso
    if ts_q:
        scoped_query[ts_field] = ts_q
    return await _aggregate_by_currency(
        collection, scoped_query, currency_field, amount_field,
    )


async def _compute_company_funds_range(
    since_iso: str, until_iso: str,
) -> List[dict]:
    """Range-aware version of `_compute_company_funds` used by the
    company closing PDF. Each source aggregate is filtered by its own
    natural timestamp so movements outside the range don't leak in.

    * Order inflows / order-payout outflows → `orders.updated_at`
    * Client withdrawals (VIP + Normal)      → `withdrawals.updated_at`
    * Company withdrawals                    → `company_withdrawals.updated_at`
    * Manual adjustments                     → `company_fund_adjustments.created_at`
    """
    inflow = await _aggregate_by_currency_ranged(
        db.orders,
        {"status": {"$in": ["approved", "completed"]}},
        "from_code", "amount_from", since_iso, until_iso, "updated_at",
    )
    out_orders = await _aggregate_by_currency_ranged(
        db.orders,
        {"status": "completed", "delivery_method": {"$ne": "accumulate"}},
        "to_code", "amount_to", since_iso, until_iso, "updated_at",
    )
    out_clients = await _aggregate_by_currency_ranged(
        db.withdrawals,
        {"status": "paid"},
        "currency", "amount_usd", since_iso, until_iso, "updated_at",
    )
    out_company = await _aggregate_by_currency_ranged(
        db.company_withdrawals,
        {"status": "paid"},
        "currency", "amount", since_iso, until_iso, "updated_at",
    )
    # Manual adjustments have no `updated_at`, so scope via `created_at`.
    adj_in: Dict[str, float] = {}
    adj_out: Dict[str, float] = {}
    adj_query: Dict[str, Any] = {}
    ts_q: Dict[str, Any] = {}
    if since_iso:
        ts_q["$gte"] = since_iso
    if until_iso:
        ts_q["$lte"] = until_iso
    if ts_q:
        adj_query["created_at"] = ts_q
    async for a in db.company_fund_adjustments.find(
        adj_query, {"_id": 0, "currency": 1, "amount": 1, "adjustment_type": 1}
    ):
        code = _norm_code(a.get("currency"))
        amt = float(a.get("amount") or 0.0)
        if not code or amt <= 0:
            continue
        (adj_in if a.get("adjustment_type") == "inflow" else adj_out)[code] = (
            (adj_in if a.get("adjustment_type") == "inflow" else adj_out).get(code, 0.0) + amt
        )

    codes = (set(inflow) | set(out_orders) | set(out_clients)
             | set(out_company) | set(adj_in) | set(adj_out))
    rows: List[dict] = []
    for c in sorted(codes):
        i = inflow.get(c, 0.0)
        oo = out_orders.get(c, 0.0)
        oc = out_clients.get(c, 0.0)
        ok = out_company.get(c, 0.0)
        mi = adj_in.get(c, 0.0)
        mo = adj_out.get(c, 0.0)
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


@router.get("/admin/company-funds/closing.pdf")
async def export_company_closing_pdf(
    request: Request,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Any:
    """iter91 — Investor-grade accounting closing PDF for the company.

    Aggregates every treasury movement in the requested range across
    orders, client withdrawals, company withdrawals and manual
    adjustments, adds a per-currency fees / revenue section, and signs
    the last page with the shared signature+stamp block.

    Requires the `company_funds` permission (same guard used by the
    existing CSV export) so employees with a currency scope can only
    download a scoped snapshot.
    """
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from datetime import datetime, timezone

    from company_closing_pdf import generate_company_closing_pdf
    from services.orders_helpers import compute_order_profit

    actor = await require_permission(request, "company_funds")

    # Parse bounds using the same date-range helper the CSV export uses.
    date_query = _date_range_query(since, until)
    since_iso = ""
    until_iso = ""
    if "created_at" in date_query:
        since_iso = date_query["created_at"].get("$gte", "") or ""
        until_iso = date_query["created_at"].get("$lte", "") or ""

    # Treasury movements per currency in-range.
    funds_rows = await _compute_company_funds_range(since_iso, until_iso)

    # Per-currency fees (profits) from confirmed/completed orders in-range.
    order_q: Dict[str, Any] = {"status": {"$in": ["approved", "completed"]}}
    if since_iso and until_iso:
        order_q["updated_at"] = {"$gte": since_iso, "$lte": until_iso}
    elif since_iso:
        order_q["updated_at"] = {"$gte": since_iso}
    elif until_iso:
        order_q["updated_at"] = {"$lte": until_iso}
    orders = await db.orders.find(order_q, {"_id": 0}).to_list(20000)
    rates = await db.rates.find({}, {"_id": 0}).to_list(500)
    rate_by_pair = {(r["from_code"], r["to_code"]): r for r in rates}

    revenue_by_currency: Dict[str, float] = {}
    total_orders = 0
    for o in orders:
        fc, tc = o.get("from_code"), o.get("to_code")
        if not fc or not tc:
            continue
        total_orders += 1
        p = await compute_order_profit(o, rate_by_pair.get((fc, tc)))
        if p:
            code = _norm_code(p.get("currency")) or tc
            revenue_by_currency[code] = revenue_by_currency.get(code, 0.0) + float(p.get("amount", 0) or 0)

    # Convert fees to USD equivalent for the executive summary.
    from services.balances import build_rate_lookup, convert_to_usdt
    fx = await build_rate_lookup()
    revenue_rows: List[dict] = []
    total_revenue_usd = 0.0
    for code in sorted(revenue_by_currency):
        fees_native = revenue_by_currency[code]
        fees_usd = convert_to_usdt(fees_native, code, fx) or 0.0
        revenue_rows.append({
            "currency": code,
            "fees": round(fees_native, 4),
            "fees_usd": round(fees_usd, 2),
        })
        total_revenue_usd += fees_usd

    # KPIs — total volume USD + treasury USD (sum of balance in-range).
    total_volume_usd = 0.0
    for o in orders:
        v = convert_to_usdt(o.get("amount_from", 0), o.get("from_code"), fx) or 0.0
        total_volume_usd += v
    treasury_usd = 0.0
    for r in funds_rows:
        b_usd = convert_to_usdt(r["balance"], r["currency"], fx) or 0.0
        treasury_usd += b_usd

    kpis = {
        "total_orders": total_orders,
        "gross_volume_usd": round(total_volume_usd, 2),
        "revenue_usd": round(total_revenue_usd, 2),
        "treasury_usd": round(treasury_usd, 2),
    }

    pdf_bytes = generate_company_closing_pdf(
        since=since or "", until=until or "",
        funds_rows=funds_rows, revenue_rows=revenue_rows,
        kpis=kpis, actor=actor,
    )
    await log_action(
        db, actor, "company_funds.closing_pdf_exported", "company_funds", "closing",
        summary=f"Exported company closing PDF ({since or '—'} → {until or '—'})",
        details={
            "since": since or "", "until": until or "",
            "currencies": [r["currency"] for r in funds_rows],
            "total_orders": total_orders,
            "revenue_usd": kpis["revenue_usd"],
        },
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    range_slug = ""
    if since and until:
        range_slug = f"_{since}_{until}"
    elif since:
        range_slug = f"_desde_{since}"
    elif until:
        range_slug = f"_hasta_{until}"
    filename = f"cierre_empresa{range_slug}_{ts}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
