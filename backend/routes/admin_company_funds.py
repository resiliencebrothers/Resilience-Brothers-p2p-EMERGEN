"""Admin router — company funds (working capital + company withdrawals).

Extracted from routes/admin.py during the iter39 split. Tracks per-currency
working capital (inflows from confirmed orders − client payouts − company
payouts) and manages staff-initiated company withdrawals.
"""
import logging
import uuid
from typing import Callable, List, Literal, Optional, Any, Dict

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
from services.currency_utils import norm_code as _norm_code  # noqa: F401 — re-exported for sibling route modules
from services.company_funds_common import (
    assert_can_manage_company_funds, actor_currency_scope,
)


router = APIRouter(tags=["Admin"])
logger = logging.getLogger(__name__)


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
    # iter194 — optional internal account (payment account or custom fund
    # account) this movement physically entered/left. Feeds the per-account
    # breakdown of the fund card.
    account_id: str = ""
    account_label: str = ""
    # iter213 — desglose de billetes para efectivo (formato Excel del
    # operador): {"1000": 3, "500": 2, ...}. Solo method="cash".
    denominations: Optional[Dict[str, int]] = None
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
    account_id: Optional[str] = Field(None, max_length=100)
    denominations: Optional[Dict[str, int]] = None
    totp_code: Optional[str] = Field(None, max_length=11)


# iter213 — denominaciones válidas por moneda (billetes en circulación).
# Regla de negocio (Jun 2026): el CUP efectivo usa solo la nomenclatura «CUP».
CASH_DENOMINATIONS: Dict[str, List[int]] = {
    "CUP": [5000, 2000, 1000, 500, 200, 100, 50, 20, 10, 5, 3, 1],
    "USD": [100, 50, 20, 10, 5, 2, 1],
}


def _parse_denomination_entry(currency: str, valid: Optional[List[int]],
                              k: object, v: object) -> tuple[int, int]:
    """Valida una entrada del desglose → (denominación, cantidad)."""
    try:
        denom = int(float(str(k)))
        qty = int(float(str(v)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail=f"Denominación o cantidad inválida: {k}={v}")
    if qty < 0:
        raise HTTPException(status_code=400,
                            detail="Las cantidades de billetes no pueden ser negativas.")
    if valid and denom not in valid:
        raise HTTPException(
            status_code=400,
            detail=(f"Billete de {denom} no existe en {currency}. "
                    f"Válidos: {', '.join(str(d) for d in valid)}"))
    if not valid and denom <= 0:
        raise HTTPException(status_code=400,
                            detail=f"Denominación inválida: {denom}")
    return denom, qty


def _validate_denominations(currency: str, raw: Dict[str, int],
                            amount: float) -> Dict[str, int]:
    """Valida el desglose de billetes y que su total coincida con el monto."""
    valid = CASH_DENOMINATIONS.get(currency)
    clean: Dict[str, int] = {}
    total = 0.0
    for k, v in (raw or {}).items():
        denom, qty = _parse_denomination_entry(currency, valid, k, v)
        if qty == 0:
            continue
        clean[str(denom)] = clean.get(str(denom), 0) + qty
        total += denom * qty
    if not clean:
        raise HTTPException(status_code=400,
                            detail="Indica al menos un billete en el desglose.")
    if abs(total - amount) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=(f"El desglose de billetes suma {total:,.2f} {currency} "
                    f"pero el monto es {amount:,.2f} {currency}. Deben coincidir."))
    return clean


async def _validate_adjustment_currency(actor: dict, raw: str) -> str:
    """Scope del empleado + existencia en el catálogo. Devuelve el código."""
    currency = raw.upper().strip()
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed and currency not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"No estás autorizado a mover fondos en {currency}",
            )
    # Lenient lookup so legacy rows with trailing whitespace still resolve.
    from routes.market import _find_currency_lenient
    if not await _find_currency_lenient(currency):
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
    return currency


async def _resolve_adjustment_account(payload: "CompanyFundAdjustmentCreate",
                                      currency: str) -> tuple:
    """iter194/195 — atribución de cuenta: explícita, o la caja si es cash."""
    account_id = (payload.account_id or "").strip()
    if account_id:
        from services.fund_accounts import resolve_fund_account
        acc = await resolve_fund_account(account_id)
        if not acc:
            raise HTTPException(status_code=400, detail="Cuenta no encontrada")
        if acc["currency"] and acc["currency"] != currency:
            raise HTTPException(
                status_code=400,
                detail=f"La cuenta «{acc['label']}» es de {acc['currency']}, no de {currency}",
            )
        return account_id, acc["label"]
    if payload.method == "cash":
        from services.fund_accounts import get_or_create_cash_box
        box = await get_or_create_cash_box(currency)
        return box["id"], box["label"]
    return "", ""


async def _assert_can_manage_company_funds(actor: dict) -> None:
    """Compat: delega en services.company_funds_common (code review)."""
    await assert_can_manage_company_funds(actor)


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


def _profit_30d_window() -> tuple[Dict[str, int], str]:
    """Return `(day_index, window_start_iso)` for the last-30-day bucket
    used by the sparklines. `day_index[iso_date] = position 0..29`."""
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).date()
    days = [today - timedelta(days=29 - i) for i in range(30)]  # oldest → newest
    return {d.isoformat(): i for i, d in enumerate(days)}, days[0].isoformat()


def _bucket_day(
    ts: Any, code: str, amount: float,
    series: Dict[str, list], day_index: Dict[str, int], window_start: str,
) -> None:
    """Add `amount` to `series[code][day_of(ts)]` if `ts` falls in the
    last-30-day window. No-op otherwise."""
    day = ts[:10] if isinstance(ts, str) else ""
    if not day or day < window_start or day not in day_index:
        return
    arr = series.setdefault(code, [0.0] * 30)
    arr[day_index[day]] += amount


async def _accumulate_order_profits(
    orders: List[dict], rate_by_pair: Dict[tuple, dict],
    totals: Dict[str, float], series: Dict[str, list],
    day_index: Dict[str, int], window_start: str,
) -> None:
    """Fold P2P order profits into `totals` (per to_code) + `series`."""
    from services.order_profit import compute_order_profit
    for o in orders:
        fc, tc = o.get("from_code"), o.get("to_code")
        if not fc or not tc:
            continue
        p = await compute_order_profit(o, rate_by_pair.get((fc, tc)))
        if not p:
            continue
        code = _norm_code(p.get("currency")) or _norm_code(tc)
        if not code:
            continue
        amount = float(p.get("amount", 0) or 0)
        totals[code] = totals.get(code, 0.0) + amount
        _bucket_day(o.get("updated_at") or o.get("created_at") or "",
                    code, amount, series, day_index, window_start)


def _accumulate_batch_profits(
    items: List[dict], rate_by_pair: Dict[tuple, dict],
    totals: Dict[str, float], series: Dict[str, list],
    day_index: Dict[str, int], window_start: str,
) -> None:
    """Fold VIP batch item margins into `totals` (per from_code) + `series`."""
    for it in items:
        computed = _batch_item_margin_from(it, rate_by_pair)
        if computed is None:
            continue
        _, _, _, margin_from = computed
        code = _norm_code(it.get("from_code"))
        if not code:
            continue
        totals[code] = totals.get(code, 0.0) + margin_from
        _bucket_day(it.get("reviewed_at") or it.get("created_at") or "",
                    code, margin_from, series, day_index, window_start)


async def _aggregate_profit_by_currency() -> tuple[Dict[str, float], Dict[str, list]]:
    """iter122 — Per-currency total profit + last-30-day daily buckets.

    Uses the shared `compute_order_profit` (same math as the Revenue module)
    so numbers align across the app.

    Returns:
      * `totals`  — {currency: summed profit across ALL approved/completed orders}
      * `series`  — {currency: [30 floats]} ordered oldest → newest, one bucket
                    per day (UTC). Orders older than 30 days contribute only
                    to `totals`, not the sparkline.

    Orders whose pair has no configured `real_rate` are silently skipped
    (they contribute 0 profit, same as Revenue).

    Approved VIP batch items (pair batches) also contribute: the company
    receives `from_code` from the VIP and sells it at the pair's real rate.
    Their profit is expressed IN `from_code` (margin_to ÷ real_rate) and
    attributed to that currency's card — e.g. BRL batches show up on the
    BRL card even when there are no P2P orders in BRL.
    """
    orders = await db.orders.find(
        {"status": {"$in": ["approved", "completed"]}},
        {"_id": 0, "from_code": 1, "to_code": 1, "amount_from": 1,
         "amount_to": 1, "updated_at": 1, "created_at": 1},
    ).to_list(50000)
    items = await db.vip_batch_items.find(
        {"status": "approved", "to_code": {"$exists": True, "$ne": None}},
        {"_id": 0, "from_code": 1, "to_code": 1, "amount": 1, "amount_to": 1,
         "rate_applied": 1, "reviewed_at": 1, "created_at": 1},
    ).to_list(50000)
    if not orders and not items:
        return {}, {}
    rate_by_pair = await _profit_detail_rate_lookup(orders, items)
    day_index, window_start = _profit_30d_window()

    totals: Dict[str, float] = {}
    series: Dict[str, list] = {}
    await _accumulate_order_profits(orders, rate_by_pair, totals, series,
                                     day_index, window_start)
    _accumulate_batch_profits(items, rate_by_pair, totals, series,
                               day_index, window_start)
    series = {c: [round(v, 4) for v in arr] for c, arr in series.items()}
    return totals, series


async def _aggregate_client_balances() -> Dict[str, float]:
    """iter117 — outstanding client balances per currency: money the company
    still OWES clients (VIP + normal) held in custody (`users.vip_balances`
    plus the legacy `vip_balance_usd` field, merged into USD). Operator
    report: a VIP holding 5,167 USDT was not discounted from the fund."""
    totals: Dict[str, float] = {}
    async for u in db.users.find(
        {"role": {"$nin": ["admin", "employee"]},
         "$or": [{"vip_balances": {"$exists": True}}, {"vip_balance_usd": {"$gt": 0}}]},
        {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1},
    ):
        for code, amt in (u.get("vip_balances") or {}).items():
            c = _norm_code(code)
            a = float(amt or 0.0)
            if not c or not a:
                continue
            totals[c] = totals.get(c, 0.0) + a
        legacy = float(u.get("vip_balance_usd") or 0.0)
        if legacy:
            totals["USD"] = totals.get("USD", 0.0) + legacy
    return totals


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
    src = await _gather_fund_sources()
    profit_by_ccy, profit_series = await _aggregate_profit_by_currency()
    codes = set().union(*(set(v) for v in src.values()))
    rows = []
    for c in sorted(codes):
        if scope and c not in scope:
            continue
        rows.append(_build_fund_row(c, src, profit_by_ccy, profit_series))
    return rows


async def _gather_fund_sources() -> Dict[str, Dict[str, float]]:
    """Fetch every per-currency aggregate that feeds the balance formula."""
    out_clients_vip, out_clients_normal = await _aggregate_withdrawals_by_role()
    manual_in, manual_out = await _aggregate_manual_adjustments()
    return {
        "inflow": await _aggregate_by_currency(
            db.orders, {"status": {"$in": ["approved", "completed"]}},
            "from_code", "amount_from"),
        "out_orders": await _aggregate_by_currency(
            db.orders,
            {"status": "completed", "delivery_method": {"$ne": "accumulate"}},
            "to_code", "amount_to"),
        "out_clients_vip": out_clients_vip,
        "out_clients_normal": out_clients_normal,
        "out_company": await _aggregate_by_currency(
            db.company_withdrawals, {"status": "paid"}, "currency", "amount"),
        "manual_in": manual_in,
        "manual_out": manual_out,
        "client_bal": await _aggregate_client_balances(),
        # iter113 — VIP batch inflows: on each approved pair item the company
        # RECEIVES `amount` in `from_code` (the VIP sends it externally before
        # staff confirms). Client deposits are also real money entering
        # company custody in the deposited currency.
        "in_vip_batches": await _aggregate_by_currency(
            db.vip_batch_items,
            {"status": "approved", "to_code": {"$nin": [None, ""]}},
            "from_code", "amount"),
        "in_deposits": await _aggregate_by_currency(
            db.deposits, {"status": "confirmed"}, "currency", "amount"),
    }


def _build_fund_row(c: str, src: Dict[str, Dict[str, float]],
                    profit_by_ccy: Dict[str, float],
                    profit_series: Dict[str, list]) -> dict:
    """Assemble the per-currency balance row from the gathered aggregates."""
    i = src["inflow"].get(c, 0.0)
    ivb = src["in_vip_batches"].get(c, 0.0)
    idep = src["in_deposits"].get(c, 0.0)
    oo = src["out_orders"].get(c, 0.0)
    ocv = src["out_clients_vip"].get(c, 0.0)
    ocn = src["out_clients_normal"].get(c, 0.0)
    oc = ocv + ocn  # legacy field: total client withdrawals
    ok = src["out_company"].get(c, 0.0)
    mi = src["manual_in"].get(c, 0.0)
    mo = src["manual_out"].get(c, 0.0)
    cb = src["client_bal"].get(c, 0.0)
    pr = profit_by_ccy.get(c, 0.0)
    # iter122 — Profitability % of the operated volume in this currency:
    # delivered order volume + VIP batch inflows (currencies like BRL
    # only enter via batches, so batches must count as volume too).
    vol = oo + ivb
    pr_pct = (pr / vol * 100.0) if vol > 0 else 0.0
    return {
        "currency": c,
        "inflow": round(i, 4),
        "inflow_vip_batches": round(ivb, 4),
        "inflow_deposits": round(idep, 4),
        "outflow_orders": round(oo, 4),
        "outflow_clients": round(oc, 4),
        "outflow_clients_vip": round(ocv, 4),
        "outflow_clients_normal": round(ocn, 4),
        "outflow_company": round(ok, 4),
        "manual_inflow": round(mi, 4),
        "manual_outflow": round(mo, 4),
        # iter117 — liability: client balances the company still owes.
        "client_balances": round(cb, 4),
        # iter122 — realised profit accumulated for this currency across
        # every approved/completed order whose `to_code` matches.
        "profit_total": round(pr, 4),
        "profit_pct": round(pr_pct, 3),
        # iter122 — 30-day daily profit series (oldest → newest) for the
        # per-card sparkline.
        "profit_30d": profit_series.get(c, [0.0] * 30),
        "balance": round(i + ivb + idep + mi - oo - oc - ok - mo, 4),
        "balance_available": round(i + ivb + idep + mi - oo - oc - ok - mo - cb, 4),
    }


def _actor_currency_scope(actor: Dict[str, Any]) -> Optional[List[str]]:
    """Compat: delega en services.company_funds_common (code review)."""
    return actor_currency_scope(actor)


@router.get("/admin/company-funds")
async def admin_company_funds(request: Request) -> Any:
    actor = await require_permission(request, "company_funds")
    return await _compute_company_funds(_actor_currency_scope(actor))


def _usdt_totals_and_breakdown(
    rows: List[dict], fx: dict,
) -> tuple[Dict[str, float], List[str], List[dict]]:
    """Convierte cada fila por moneda a USDT y acumula los totales globales.
    Devuelve (totales, monedas sin tasa, desglose por moneda)."""
    totals = {k: 0.0 for k in
              ("balance", "available", "liabilities", "inflow", "outflow", "profit")}
    missing: List[str] = []
    breakdown: List[dict] = []
    for r in rows:
        conv = _row_usdt_summary(r, fx)
        if conv is None:
            # No rate path — count the currency as "missing" so the operator
            # knows the total is under-reported until they configure a rate.
            missing.append(r["currency"])
            continue
        for k in totals:
            totals[k] += conv[f"{k}_usdt"]
        breakdown.append({
            "currency": r["currency"],
            "balance": round(conv["balance"], 4),
            "balance_available": round(conv["available"], 4),
            "balance_usdt": round(conv["balance_usdt"], 2),
            "balance_available_usdt": round(conv["available_usdt"], 2),
        })
    return totals, missing, breakdown


def _client_owed_amount(u: dict, c: str) -> float:
    """Cuánto se le debe al usuario en `c` (vip_balances + legado USD)."""
    amt = 0.0
    for code, val in (u.get("vip_balances") or {}).items():
        if _norm_code(code) == c:
            amt += float(val or 0.0)
    if c == "USD":
        amt += float(u.get("vip_balance_usd") or 0.0)
    return amt


async def _collect_client_balances(c: str) -> tuple:
    """(clientes con saldo en `c` ordenados desc, total del pasivo)."""
    clients: List[dict] = []
    total = 0.0
    async for u in db.users.find(
            {"role": {"$nin": ["admin", "employee"]},
             "$or": [{"vip_balances": {"$exists": True}},
                     {"vip_balance_usd": {"$gt": 0}}]},
            {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1,
             "vip_balances": 1, "vip_balance_usd": 1}):
        amt = _client_owed_amount(u, c)
        if abs(amt) < 1e-9:
            continue
        total += amt
        clients.append({"user_id": u.get("user_id") or "",
                        "name": u.get("name") or "",
                        "email": u.get("email") or "",
                        "role": u.get("role") or "",
                        "amount": round(amt, 4)})
    clients.sort(key=lambda r: -r["amount"])
    return clients, total


@router.get("/admin/company-funds/client-balances/{currency}")
async def company_funds_client_balances_breakdown(
        currency: str, request: Request) -> Any:
    """iter268 — desglose por CLIENTE del pasivo «saldos clientes (por pagar)»
    de una moneda: a quién se le debe y cuánto (custodia en vip_balances +
    el legado vip_balance_usd fusionado en USD)."""
    actor = await require_permission(request, "company_funds")
    c = _norm_code(currency)
    if not c:
        raise HTTPException(status_code=400, detail="Moneda inválida")
    scope = _actor_currency_scope(actor)
    if scope is not None and c not in scope:
        raise HTTPException(status_code=403, detail="Moneda fuera de tu alcance")
    clients, total = await _collect_client_balances(c)
    return {"currency": c, "total": round(total, 4), "clients": clients}


@router.get("/admin/company-funds/total-usdt")
async def admin_company_funds_total_usdt(request: Request) -> Any:
    """iter152 — Global treasury summary in USDT.

    Sums every per-currency row from `_compute_company_funds()` after
    converting each side of the balance sheet to USDT via the same rate
    lookup used by the VIP threshold + user portfolio views.

    Response:
      total_balance_usdt        — inflows − outflows in every currency (raw)
      total_available_usdt      — same MINUS client custody (what we owe VIPs
                                   / normals). This is the number the admin
                                   wants for "cuánto tenemos realmente libre".
      total_liabilities_usdt    — sum of `client_balances` (custody)
      total_inflow_usdt         — every inflow source (orders + batches + deposits + manual)
      total_outflow_usdt        — every outflow (orders + client wds + company wds + manual)
      total_profit_usdt         — realised profit across every currency
      missing_rate_currencies   — currencies excluded from the totals because
                                   we don't have a rate path to USDT yet, so
                                   the operator can spot gaps in configuration.
      rows                      — per-currency breakdown after conversion
    """
    actor = await require_permission(request, "company_funds")
    from services.balances import build_rate_lookup
    rows = await _compute_company_funds(_actor_currency_scope(actor))
    fx = await build_rate_lookup()
    totals, missing, breakdown = _usdt_totals_and_breakdown(rows, fx)
    return {
        "base": "USDT",
        "total_balance_usdt": round(totals["balance"], 2),
        "total_available_usdt": round(totals["available"], 2),
        "total_liabilities_usdt": round(totals["liabilities"], 2),
        "total_inflow_usdt": round(totals["inflow"], 2),
        "total_outflow_usdt": round(totals["outflow"], 2),
        "total_profit_usdt": round(totals["profit"], 2),
        "missing_rate_currencies": missing,
        "rows": sorted(breakdown, key=lambda r: -r["balance_usdt"]),
    }


def _row_usdt_summary(r: dict, fx: dict) -> Optional[Dict[str, float]]:
    """Convert one company-funds row to USDT. None → no rate path."""
    from services.balances import convert_to_usdt
    code = r["currency"]

    def _f(*keys: str) -> float:
        return sum(float(r.get(k) or 0.0) for k in keys)

    def _conv(amount: float) -> float:
        return convert_to_usdt(amount, code, fx) or 0.0

    bal = _f("balance")
    bal_u = convert_to_usdt(bal, code, fx)
    if bal_u is None:
        return None
    avail = _f("balance_available")
    return {
        "balance": bal,
        "available": avail,
        "balance_usdt": bal_u,
        "available_usdt": _conv(avail),
        "liabilities_usdt": _conv(_f("client_balances")),
        "profit_usdt": _conv(_f("profit_total")),
        "inflow_usdt": _conv(_f("inflow", "inflow_vip_batches",
                                "inflow_deposits", "manual_inflow")),
        "outflow_usdt": _conv(_f("outflow_orders", "outflow_clients",
                                 "outflow_company", "manual_outflow")),
    }


@router.get("/admin/company-funds/client-debts")
async def company_funds_client_debts(request: Request) -> Any:
    """iter162 — Bidirectional client-debt report.

    we_owe : clients holding custody balances (users.vip_balances per
             currency + legacy vip_balance_usd merged into USD).
    owe_us : VIP-ledger debt (vip_ledger.negative_usdt — debit batches the
             VIP settles later, tracked in USDT).
    Every row carries per-currency amounts + USDT equivalent; the summary
    exposes both totals and the net position in USDT.
    """
    await require_permission(request, "company_funds")
    from services.balances import build_rate_lookup
    fx = await build_rate_lookup()
    missing: set = set()

    we_owe, total_we_owe = await _collect_we_owe(fx, missing)
    owe_us, total_owe_us = await _collect_owe_us()
    return {
        "base": "USDT",
        "we_owe": we_owe,
        "owe_us": owe_us,
        "total_we_owe_usdt": round(total_we_owe, 2),
        "total_owe_us_usdt": round(total_owe_us, 2),
        "net_usdt": round(total_owe_us - total_we_owe, 2),
        "missing_rate_currencies": sorted(missing),
    }


def _balance_rows_usdt(balances: Dict[str, float], fx: dict,
                       missing: set) -> tuple[list, float]:
    """Per-currency rows + USDT total; unknown-rate codes go to `missing`."""
    from services.balances import convert_to_usdt
    rows, total_u = [], 0.0
    for c, a in balances.items():
        usdt = convert_to_usdt(a, c, fx)
        if usdt is None:
            missing.add(c)
        else:
            total_u += usdt
        rows.append({"currency": c, "amount": round(a, 4),
                     "usdt": round(usdt, 2) if usdt is not None else None})
    rows.sort(key=lambda r: -float(r.get("usdt") or 0.0))  # type: ignore[arg-type]
    return rows, total_u


def _user_custody_balances(u: dict) -> Dict[str, float]:
    """Positive per-currency custody (vip_balances + legacy USD field)."""
    balances: Dict[str, float] = {}
    for code, amt in (u.get("vip_balances") or {}).items():
        c = _norm_code(code)
        a = float(amt or 0.0)
        if c and a:
            balances[c] = balances.get(c, 0.0) + a
    legacy = float(u.get("vip_balance_usd") or 0.0)
    if legacy:
        balances["USD"] = balances.get("USD", 0.0) + legacy
    return {c: a for c, a in balances.items() if a > 0}


async def _collect_we_owe(fx: dict, missing: set) -> tuple[list, float]:
    """Clients holding custody balances (money the company owes them)."""
    we_owe: list = []
    total = 0.0
    async for u in db.users.find(
        {"role": {"$nin": ["admin", "employee"]},
         "$or": [{"vip_balances": {"$exists": True}}, {"vip_balance_usd": {"$gt": 0}}]},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1,
         "vip_balances": 1, "vip_balance_usd": 1},
    ):
        positive = _user_custody_balances(u)
        if not positive:
            continue
        rows, total_u = _balance_rows_usdt(positive, fx, missing)
        total += total_u
        we_owe.append({
            "user_id": u["user_id"], "name": u.get("name") or "",
            "email": u.get("email") or "", "role": u.get("role") or "normal",
            "balances": rows, "total_usdt": round(total_u, 2),
        })
    we_owe.sort(key=lambda r: -r["total_usdt"])
    return we_owe, total


async def _collect_owe_us() -> tuple[list, float]:
    """VIP-ledger debt in USDT (money the clients owe the company)."""
    owe_us: list = []
    total = 0.0
    ledgers = await db.vip_ledger.find(
        {"negative_usdt": {"$gt": 0}}, {"_id": 0},
    ).to_list(5000)
    ids = [led["vip_user_id"] for led in ledgers]
    users_by_id = {
        u["user_id"]: u
        async for u in db.users.find(
            {"user_id": {"$in": ids}},
            {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1},
        )
    }
    for led in ledgers:
        amt = round(float(led.get("negative_usdt") or 0.0), 2)
        info = users_by_id.get(led["vip_user_id"]) or {}
        total += amt
        owe_us.append({
            "user_id": led["vip_user_id"], "name": info.get("name") or "",
            "email": info.get("email") or "", "role": info.get("role") or "vip",
            "balances": [{"currency": "USDT", "amount": amt, "usdt": amt}],
            "total_usdt": amt, "updated_at": led.get("updated_at"),
        })
    owe_us.sort(key=lambda r: -r["total_usdt"])
    return owe_us, total


def _day_window(date: Optional[str]) -> tuple:
    """(day, next_day) en formato YYYY-MM-DD; `date` opcional (default hoy UTC)."""
    from datetime import datetime, timedelta
    if date:
        try:
            d0 = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="fecha inválida (YYYY-MM-DD)")
        return date, (d0 + timedelta(days=1)).strftime("%Y-%m-%d")
    now = now_utc()
    return now.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d")


@router.get("/admin/company-funds/batches-today")
async def company_funds_batches_today(request: Request, date: Optional[str] = None) -> Any:
    """Daily VIP batch summary for the company-funds stats: how many batches
    closed on the given day (manual + auto) and the volume approved that day
    in USDT. `date` (YYYY-MM-DD) is optional — defaults to today (UTC)."""
    await require_permission(request, "company_funds")
    from services.balances import build_rate_lookup, convert_to_usdt
    day, next_day = _day_window(date)
    win = {"$gte": day, "$lt": next_day}

    closed = await db.vip_batches.find(
        {"status": "closed", "closed_at": win},
        {"_id": 0, "auto_closed": 1},
    ).to_list(5000)

    approved_today = await db.vip_batch_items.find(
        {"status": "approved", "reviewed_at": win},
        {"_id": 0, "amount": 1, "from_code": 1, "currency": 1},
    ).to_list(50000)
    fx = await build_rate_lookup()
    volume = 0.0
    for it in approved_today:
        code = _norm_code(it.get("from_code") or it.get("currency")) or "USDT"
        volume += convert_to_usdt(float(it.get("amount") or 0.0), code, fx) or 0.0

    return {
        "date": day,
        "closed_count": len(closed),
        "auto_count": sum(1 for b in closed if b.get("auto_closed")),
        "orders_approved": len(approved_today),
        "volume_usdt": round(volume, 2),
    }


async def _vip_display_names(batches: List[dict], orders: List[dict]) -> Dict[str, str]:
    """{vip_user_id: nombre o email} para todas las filas del día."""
    vip_ids = [v for v in {b.get("vip_user_id") for b in batches}
               | {o.get("vip_user_id") for o in orders} if v]
    names: Dict[str, str] = {}
    if vip_ids:
        async for u in db.users.find({"user_id": {"$in": vip_ids}},
                                     {"_id": 0, "user_id": 1, "name": 1, "email": 1}):
            names[u["user_id"]] = u.get("name") or u.get("email") or "—"
    return names


def _doc_pair(doc: dict) -> str:
    if doc.get("to_code"):
        return f"{doc.get('from_code')}→{doc.get('to_code')}"
    return doc.get("currency") or "—"


def _batch_summary_rows(batches: List[dict], names: Dict[str, str]) -> List[dict]:
    return [{
        "id": b["id"],
        "pair": _doc_pair(b),
        "vip_name": names.get(str(b.get("vip_user_id") or ""), "—"),
        "auto_closed": bool(b.get("auto_closed")),
        "closed_at": b.get("closed_at"),
        "items_approved": b.get("items_approved") or 0,
        "items_pending": b.get("items_pending") or 0,
        "items_rejected": b.get("items_rejected") or 0,
        "amount_approved": b.get("amount_approved") or 0.0,
        "from_code": b.get("from_code") or b.get("currency"),
    } for b in batches]


async def _order_detail_rows(orders: List[dict],
                             names: Dict[str, str]) -> tuple:
    """(rows, volumen aprobado del día convertido a USDT)."""
    from services.balances import build_rate_lookup, convert_to_usdt
    fx = await build_rate_lookup()
    rows, volume = [], 0.0
    for o in orders:
        code = _norm_code(o.get("from_code") or o.get("currency")) or "USDT"
        volume += convert_to_usdt(float(o.get("amount") or 0.0), code, fx) or 0.0
        rows.append({
            "id": o["id"],
            "reviewed_at": o.get("reviewed_at"),
            "vip_name": names.get(str(o.get("vip_user_id") or ""), "—"),
            "holder": o.get("card_number") or o.get("holder_name") or "—",
            "pair": _doc_pair(o),
            "amount": o.get("amount"),
            "from_code": o.get("from_code") or o.get("currency"),
            "amount_to": o.get("amount_to"),
            "to_code": o.get("to_code"),
        })
    return rows, volume


@router.get("/admin/company-funds/batches-today/detail")
async def company_funds_batches_today_detail(request: Request, date: Optional[str] = None) -> Any:
    """Drill-down for the 'Lotes del día' card: the exact closed batches and
    approved orders of the given day (default today, UTC)."""
    await require_permission(request, "company_funds")
    day, next_day = _day_window(date)
    win = {"$gte": day, "$lt": next_day}

    batches = await db.vip_batches.find(
        {"status": "closed", "closed_at": win}, {"_id": 0},
    ).sort("closed_at", 1).to_list(5000)
    orders = await db.vip_batch_items.find(
        {"status": "approved", "reviewed_at": win}, {"_id": 0},
    ).sort("reviewed_at", 1).to_list(50000)

    names = await _vip_display_names(batches, orders)
    order_rows, volume = await _order_detail_rows(orders, names)
    return {"date": day, "batches": _batch_summary_rows(batches, names),
            "orders": order_rows, "volume_usdt": round(volume, 2)}


async def _profit_detail_rate_lookup(
    orders_docs: List[dict], batches_docs: List[dict],
) -> Dict[tuple, dict]:
    """Build a `{(from_code, to_code): rate_doc}` map for every pair that
    appears in the caller's orders or batches — avoids N+1 rate look-ups."""
    pairs = {(o.get("from_code"), o.get("to_code")) for o in orders_docs
             if o.get("from_code") and o.get("to_code")}
    pairs |= {(i.get("from_code"), i.get("to_code")) for i in batches_docs
              if i.get("from_code") and i.get("to_code")}
    if not pairs:
        return {}
    rate_docs = await db.rates.find(
        {"$or": [{"from_code": fc, "to_code": tc} for fc, tc in pairs]},
        {"_id": 0, "from_code": 1, "to_code": 1, "real_rate": 1,
         "rate_normal": 1, "rate_vip": 1},
    ).to_list(1000)
    return {(r["from_code"], r["to_code"]): r for r in rate_docs}


def _profit_order_row(o: dict, p: dict, amount: float,
                      rate_by_pair: Dict[tuple, dict]) -> dict:
    fc, tc = o.get("from_code"), o.get("to_code")
    return {
        "id": o["id"],
        "reviewed_at": o.get("updated_at") or o.get("created_at"),
        "pair": f"{fc}→{tc}",
        "from_code": fc, "to_code": tc,
        "user_name": o.get("user_name") or o.get("user_email") or "—",
        "user_role": o.get("user_role") or "normal",
        "amount_from": float(o.get("amount_from") or 0.0),
        "amount_to": float(o.get("amount_to") or 0.0),
        "real_rate": float((rate_by_pair.get((fc, tc)) or {}).get("real_rate") or 0.0),
        "profit": round(amount, 4),
        "profit_pct": p.get("pct") or 0.0,
    }


async def _build_profit_order_rows(
    orders_docs: List[dict], rate_by_pair: Dict[tuple, dict],
) -> tuple[List[dict], float]:
    """Turn approved/completed orders into per-row profit entries. Skips
    orders whose pair has no configured real rate (same as the aggregate)."""
    from services.order_profit import compute_order_profit
    rows: List[dict] = []
    total = 0.0
    for o in orders_docs:
        fc, tc = o.get("from_code"), o.get("to_code")
        if not fc or not tc:
            continue
        p = await compute_order_profit(o, rate_by_pair.get((fc, tc)))
        if not p:
            continue
        amount = float(p.get("amount", 0) or 0)
        total += amount
        rows.append(_profit_order_row(o, p, amount, rate_by_pair))
    return rows, total


def _batch_item_margin_from(
    it: dict, rate_by_pair: Dict[tuple, dict],
) -> Optional[tuple[float, float, float, float]]:
    """Return (amount, applied, real, margin_from) for a VIP batch item, or
    None when the item cannot contribute profit (missing rate / bad data).
    Isolates the guard clauses that previously bloated the endpoint."""
    fc, tc = it.get("from_code"), it.get("to_code")
    if not fc or not tc:
        return None
    real = float((rate_by_pair.get((fc, tc)) or {}).get("real_rate") or 0.0)
    if real <= 0:
        return None
    amount = float(it.get("amount") or 0.0)
    applied = float(it.get("rate_applied") or 0.0)
    if applied <= 0 and amount > 0:
        applied = float(it.get("amount_to") or 0.0) / amount
    if amount <= 0 or applied <= 0:
        return None
    return amount, applied, real, amount * (real - applied) / real


async def _load_vip_names(batches_docs: List[dict]) -> Dict[str, str]:
    """One-shot `{user_id: display_name}` map for the batch rows."""
    vip_ids = [v for v in {b.get("vip_user_id") for b in batches_docs} if v]
    if not vip_ids:
        return {}
    names: Dict[str, str] = {}
    async for u in db.users.find(
        {"user_id": {"$in": vip_ids}},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1},
    ):
        names[u["user_id"]] = u.get("name") or u.get("email") or "—"
    return names


def _build_profit_batch_rows(
    batches_docs: List[dict], rate_by_pair: Dict[tuple, dict],
    names: Dict[str, str],
) -> tuple[List[dict], float]:
    """Turn approved VIP batch items into per-row profit entries."""
    rows: List[dict] = []
    total = 0.0
    for it in batches_docs:
        computed = _batch_item_margin_from(it, rate_by_pair)
        if computed is None:
            continue
        amount, applied, real, margin_from = computed
        total += margin_from
        rows.append({
            "id": it["id"],
            "reviewed_at": it.get("reviewed_at") or it.get("created_at"),
            "pair": f"{it['from_code']}→{it['to_code']}",
            "from_code": it["from_code"], "to_code": it["to_code"],
            "vip_name": names.get(it.get("vip_user_id") or "", "—"),
            "holder": it.get("card_number") or it.get("holder_name") or "—",
            "amount": amount,
            "amount_to": float(it.get("amount_to") or 0.0),
            "rate_applied": applied,
            "real_rate": real,
            "profit": round(margin_from, 4),
        })
    return rows, total


@router.get("/admin/company-funds/profit-detail/{currency}")
async def company_funds_profit_detail(currency: str, request: Request) -> Any:
    """iter142 — Drill-down for the "Rentabilidad total" chip on each fund
    card. Returns the exact P2P orders (whose `to_code` matches) and VIP
    batch items (whose `from_code` matches) that generated the currency's
    accumulated profit, alongside per-item amounts so the operator can
    audit where each dollar/peso came from.

    Order profit is expressed in `to_code` (same math as
    `_aggregate_profit_by_currency`); batch margin is expressed in
    `from_code`. The response also carries a per-row `profit` value in
    `currency` so the UI can render one consistent column.
    """
    actor = await require_permission(request, "company_funds")
    code = _norm_code(currency)
    if not code:
        raise HTTPException(status_code=400, detail="moneda inválida")
    _enforce_employee_currency_scope(actor, code)

    orders_docs = await db.orders.find(
        {"status": {"$in": ["approved", "completed"]}, "to_code": code},
        {"_id": 0},
    ).sort("updated_at", -1).to_list(20000)
    batches_docs = await db.vip_batch_items.find(
        {"status": "approved", "from_code": code,
         "to_code": {"$exists": True, "$ne": None}},
        {"_id": 0},
    ).sort("reviewed_at", -1).to_list(20000)

    rate_by_pair = await _profit_detail_rate_lookup(orders_docs, batches_docs)
    order_rows, orders_total = await _build_profit_order_rows(orders_docs, rate_by_pair)
    names = await _load_vip_names(batches_docs)
    batch_rows, batches_total = _build_profit_batch_rows(batches_docs, rate_by_pair, names)

    return {
        "currency": code,
        "orders": order_rows,
        "batches": batch_rows,
        "orders_profit_total": round(orders_total, 4),
        "batches_profit_total": round(batches_total, 4),
        "profit_total": round(orders_total + batches_total, 4),
    }


@router.post("/admin/company-withdrawals")
async def create_company_withdrawal(payload: CompanyWithdrawalCreate, request: Request) -> Any:
    actor = await require_permission(request, "company_funds")
    currency = payload.currency.upper()
    _enforce_employee_currency_scope(actor, currency)
    await _enforce_totp_step_up(actor, payload.totp_code, action_label="retiro del fondo")
    # V01 — crear y pagar contienden sobre el MISMO cerrojo por moneda: el
    # disponible se evalúa DENTRO de la sección crítica (nunca sobre una foto
    # vieja) y la reserva se comprueba y consume en un único update atómico
    # contra el presupuesto compartido (services/company_fund_budget).
    from services import company_fund_budget as fund_budget
    lock = await fund_budget.acquire_pay_lock_wait(currency)
    if not lock:
        raise HTTPException(
            status_code=409,
            detail=(f"Otra operación del fondo {currency} está en curso; "
                    "inténtalo de nuevo en unos segundos."))
    try:
        funds = await _compute_company_funds([currency])
        row = next((f for f in funds if f["currency"] == currency), None)
        balance = float(row["balance"]) if row else 0.0
        custodia = float(row["client_balances"]) if row else 0.0
        # iter266 — disponible REAL: el dinero en custodia de clientes no es
        # capital propio y no puede financiar retiros de empresa.
        avail = float(row["balance_available"]) if row else 0.0
        # H02/V01 — los retiros aún no pagados (pending/approved) comprometen
        # el fondo; la reserva se reclama atómicamente (guard + $inc).
        if not await fund_budget.claim_reservation(
                currency, float(payload.amount), avail):
            reserved = await fund_budget.current_reserved(currency)
            disponible = round(avail - reserved, 4)
            raise HTTPException(
                status_code=400,
                detail=(f"Fondo insuficiente en {currency}: disponible real "
                        f"{disponible:.2f} (balance {balance:.2f} − "
                        f"{custodia:.2f} en custodia de clientes − "
                        f"{reserved:.2f} ya reservado en retiros pendientes)"),
            )
    finally:
        await fund_budget.release_pay_lock(currency, lock)
    try:
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
    except Exception:
        # V01 — la reserva reclamada nunca queda huérfana si la inserción falla
        await fund_budget.release_reservation(currency, float(payload.amount))
        raise
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


async def _paid_from_account_fields(payload: dict, cw: dict) -> Dict[str, Any]:
    """iter194/195 — "paid from account": explicit choice wins; otherwise
    auto-attribute when the currency has exactly one active account."""
    from services.fund_accounts import (
        resolve_fund_account, auto_paid_from_account,
    )
    acc_id = (payload.get("paid_from_account_id") or "").strip()
    if acc_id:
        acc = await resolve_fund_account(acc_id)
        if not acc:
            raise HTTPException(status_code=400, detail="Cuenta de origen no encontrada")
        return {"paid_from_account_id": acc_id,
                "paid_from_account_label": acc["label"]}
    acc = await auto_paid_from_account(cw.get("currency") or "")
    if acc:
        return {"paid_from_account_id": acc["id"],
                "paid_from_account_label": acc["label"]}
    return {}


# H02 — transiciones válidas de un retiro de empresa (paid/rejected: finales)
_CW_TRANSITIONS: Dict[str, set] = {
    "pending": {"approved", "paid", "rejected"},
    "approved": {"paid", "rejected"},
    "paid": set(),
    "rejected": set(),
}


async def _claim_cw_transition(cwid: str, prev_status: str,
                               update_doc: Dict[str, Any]) -> None:
    """H02 — claim atómico condicionado al estado leído: un rechazo obsoleto
    no puede sobrescribir un pago que ganó la carrera."""
    res = await db.company_withdrawals.update_one(
        {"id": cwid, "status": prev_status}, {"$set": update_doc})
    if res.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="El retiro cambió de estado; recarga e inténtalo de nuevo.")


async def _pay_company_withdrawal(cwid: str, cw: dict, payload: dict,
                                  update_doc: Dict[str, Any]) -> None:
    """V01 — pago bajo cerrojo exclusivo por moneda: el disponible se evalúa
    DENTRO de la sección crítica; dos pagos distintos nunca validan la misma
    foto del fondo, y la reserva se consume exactamente una vez."""
    from services import company_fund_budget as fund_budget
    lock = await fund_budget.acquire_pay_lock_wait(cw["currency"])
    if not lock:
        raise HTTPException(
            status_code=409,
            detail=(f"Otra operación del fondo {cw['currency']} está en "
                    "curso; inténtalo de nuevo en unos segundos."))
    try:
        # H02/iter266 — el pago revalida el DISPONIBLE REAL en ese momento
        # (sin custodia de clientes); una salida sin fondos debe tratarse
        # explícitamente, no colarse.
        funds = await _compute_company_funds([cw["currency"]])
        avail = next((f["balance_available"] for f in funds
                      if f["currency"] == cw["currency"]), 0.0)
        if float(cw["amount"]) > avail + 1e-9:
            raise HTTPException(
                status_code=409,
                detail=(f"Fondo insuficiente en {cw['currency']} para marcar "
                        f"pagado: disponible real {avail:.2f} (descontada la "
                        "custodia de clientes). Registra primero el capital "
                        "o resuelve el descuadre explícitamente."))
        update_doc.update(await _paid_from_account_fields(payload, cw))
        update_doc["paid_at"] = iso(now_utc())
        await _claim_cw_transition(cwid, cw["status"], update_doc)
        await fund_budget.release_reservation(
            cw["currency"], float(cw["amount"]))
    finally:
        await fund_budget.release_pay_lock(cw["currency"], lock)


async def _mirror_paid_company_withdrawal(fresh: dict, cwid: str) -> None:
    """H01 — pagado desde la cuenta de caja → salida física en la Caja."""
    from services.cash_box_sync import mirror_company_withdrawal_to_cash_box
    try:
        mov_id = await mirror_company_withdrawal_to_cash_box(fresh)
        if mov_id:
            fresh["cash_box_movement_id"] = mov_id
    except Exception as exc:  # el job periódico lo sana
        logger.error("No se pudo replicar el retiro %s en la caja: %s",
                     cwid, exc)


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
    if new_status == cw["status"]:
        return cw
    if new_status not in _CW_TRANSITIONS.get(cw["status"], set()):
        raise HTTPException(
            status_code=409,
            detail=f"Transición inválida: el retiro está «{cw['status']}»")
    update_doc = {"status": new_status}
    note = payload.get("note")
    if note is not None:
        update_doc["admin_note"] = note
    if new_status == "paid":
        await _pay_company_withdrawal(cwid, cw, payload, update_doc)
    else:
        await _claim_cw_transition(cwid, cw["status"], update_doc)
        if new_status == "rejected":
            # V01 — la reserva se libera exactamente una vez al rechazar.
            from services import company_fund_budget as fund_budget
            await fund_budget.release_reservation(
                cw["currency"], float(cw["amount"]))
    await log_action(db, actor, "company_withdrawal.status", "company_withdrawal", cwid,
                     summary=f"Retiro fondo {cw['currency']} {cw['amount']} → {new_status}",
                     details={"from": cw["status"], "to": new_status})
    fresh = await db.company_withdrawals.find_one({"id": cwid}, {"_id": 0})
    if new_status == "paid" and fresh:
        await _mirror_paid_company_withdrawal(fresh, cwid)
    return fresh


# ============================================================
# iter54 — Capital-of-trabajo adjustments (manual inflows/outflows)
# ============================================================

def _resolve_cash_denominations(
    payload: "CompanyFundAdjustmentCreate", currency: str,
) -> Optional[dict]:
    """iter213 — desglose de billetes: obligatorio para efectivo CUP/USD
    (formato del Excel de control físico), validado contra el monto."""
    if payload.method != "cash":
        return None
    if payload.denominations:
        return _validate_denominations(
            currency, payload.denominations, payload.amount)
    if currency in CASH_DENOMINATIONS:
        raise HTTPException(
            status_code=400,
            detail=(f"Para efectivo en {currency} debes indicar el "
                    "desglose de billetes por denominación."))
    return None


async def _log_adjustment_action(actor: dict,
                                 payload: "CompanyFundAdjustmentCreate",
                                 doc: dict, currency: str,
                                 denominations: Optional[dict]) -> None:
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
            "denominations": denominations,
        },
    )


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

    currency = await _validate_adjustment_currency(actor, payload.currency)
    account_id, account_label = await _resolve_adjustment_account(payload, currency)
    denominations = _resolve_cash_denominations(payload, currency)

    adjustment = CompanyFundAdjustment(
        adjustment_type=payload.adjustment_type,
        currency=currency,
        amount=payload.amount,
        method=payload.method,
        source_name=payload.source_name.strip(),
        source_account=payload.source_account.strip(),
        note=payload.note.strip(),
        account_id=account_id,
        account_label=account_label,
        denominations=denominations,
        actor_id=actor["user_id"],
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
    )
    doc = adjustment.model_dump()
    # insert_one mutates the input dict by adding `_id: ObjectId` — pass a copy
    # so the returned `doc` remains JSON-serialisable.
    await db.company_fund_adjustments.insert_one({**doc})
    await _log_adjustment_action(actor, payload, doc, currency, denominations)
    # iter263 — espejo físico: el efectivo (CUP/USD) se replica con su
    # desglose de billetes en la Caja de Efectivo «Fondo Resilience».
    from services.cash_box_sync import mirror_adjustment_to_cash_box
    try:
        mov_id = await mirror_adjustment_to_cash_box(doc)
        if mov_id:
            doc["cash_box_movement_id"] = mov_id
    except Exception as exc:  # nunca romper el ajuste — el job periódico lo sana
        logger.error("No se pudo replicar el ajuste %s en la caja: %s",
                     doc["id"], exc)
    return doc


@router.get("/admin/company-funds/cash-denominations")
async def cash_denominations_summary(request: Request) -> Any:
    """iter213 — Control físico de caja por denominación (formato Excel):
    cantidad actual de billetes = Σ entradas − Σ salidas de los ajustes
    manuales en efectivo con desglose registrado."""
    actor = await require_permission(request, "company_funds")
    scope = _actor_currency_scope(actor)
    counts: Dict[str, Dict[int, int]] = {}
    async for a in db.company_fund_adjustments.find(
        {"method": "cash", "denominations": {"$nin": [None, {}]}},
        {"_id": 0, "currency": 1, "adjustment_type": 1, "denominations": 1},
    ):
        code = _norm_code(a.get("currency"))
        if not code or (scope and code not in scope):
            continue
        sign = 1 if a.get("adjustment_type") == "inflow" else -1
        bucket = counts.setdefault(code, {})
        for k, v in (a.get("denominations") or {}).items():
            try:
                denom, qty = int(float(k)), int(v)
            except (TypeError, ValueError):
                continue
            bucket[denom] = bucket.get(denom, 0) + sign * qty
    rows = []
    for code in sorted(counts):
        denom_order = CASH_DENOMINATIONS.get(
            code, sorted(counts[code], reverse=True))
        items = [{"denomination": d,
                  "count": counts[code].get(d, 0),
                  "value": round(d * counts[code].get(d, 0), 2)}
                 for d in denom_order]
        rows.append({
            "currency": code,
            "denominations": items,
            "total_value": round(sum(x["value"] for x in items), 2),
            "total_bills": sum(x["count"] for x in items),
        })
    return rows


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

def _parse_iso_bound(s: str, is_end: bool) -> str:
    """ISO date/datetime → bound ISO. Fechas sin hora se expanden al día
    completo (00:00:00 / 23:59:59). Inválido → 400."""
    from datetime import datetime as _dt
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


def _date_range_query(since: Optional[str], until: Optional[str]) -> Dict[str, Any]:
    """Build a Mongo `$gte/$lte` `created_at` filter from ISO date/datetime
    strings (día completo para fechas sin hora)."""
    since_iso = _parse_iso_bound(since or "", is_end=False)
    until_iso = _parse_iso_bound(until or "", is_end=True)
    bounds = {k: v for k, v in (("$gte", since_iso), ("$lte", until_iso)) if v}
    return {"created_at": bounds} if bounds else {}


def _csv_currency_filter(actor: dict, currency: Optional[str]) -> "Callable[[Any], bool]":
    """Predicate combining the explicit ?currency filter with the employee
    `allowed_currencies` scope."""
    scope_codes: Optional[List[str]] = None
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            scope_codes = [c.upper() for c in allowed]

    def _ok(code: Any) -> bool:
        c = _norm_code(code)
        if not c:
            return False
        if currency and c != currency.upper():
            return False
        if scope_codes is not None and c not in scope_codes:
            return False
        return True

    return _ok


def _fmt_denominations(denoms: Optional[Dict[str, int]]) -> str:
    """{'1000': 3, '500': 2} → '3×1000 · 2×500' (mayor a menor)."""
    if not denoms:
        return ""
    try:
        pairs = sorted(((int(float(k)), int(v)) for k, v in denoms.items()),
                       key=lambda x: -x[0])
    except (TypeError, ValueError):
        return ""
    return " · ".join(f"{q}×{d}" for d, q in pairs if q)


def _adjustment_csv_row(a: dict) -> List[str]:
    """Manual adjustment → CSV row (inflow = +, outflow = -)."""
    amt = float(a.get("amount") or 0.0)
    direction = a.get("adjustment_type") or ""
    signed = amt if direction == "inflow" else -amt
    return [
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
        _fmt_denominations(a.get("denominations")),
    ]


def _company_withdrawal_csv_row(w: dict) -> List[str]:
    """Company withdrawal → CSV row. Paid outflows are negative; non-paid
    rows carry the raw absolute amount because they haven't moved money yet."""
    amt = float(w.get("amount") or 0.0)
    status = w.get("status") or "pending"
    signed = -amt if status == "paid" else amt
    return [
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
        "",  # denominations N/A
    ]


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
    _currency_ok = _csv_currency_filter(actor, currency)

    rows: List[List[str]] = []
    async for a in db.company_fund_adjustments.find(date_q, {"_id": 0}):
        if _currency_ok(a.get("currency")):
            rows.append(_adjustment_csv_row(a))
    async for w in db.company_withdrawals.find(date_q, {"_id": 0}):
        if _currency_ok(w.get("currency")):
            rows.append(_company_withdrawal_csv_row(w))

    # Sort by date ascending so the CSV reads as a chronological ledger.
    rows.sort(key=lambda r: r[0])

    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    writer.writerow([
        "created_at", "movement_kind", "direction", "currency",
        "amount", "party", "method", "concept_or_note", "status",
        "authorized_by", "id", "denominations",
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
    adj_in, adj_out = await _ranged_adjustment_totals(since_iso, until_iso)
    return _merge_fund_rows(inflow, out_orders, out_clients,
                            out_company, adj_in, adj_out)


async def _ranged_adjustment_totals(
    since_iso: str, until_iso: str,
) -> tuple[Dict[str, float], Dict[str, float]]:
    """Per-currency (inflow, outflow) totals of manual adjustments in range."""
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
        bucket = adj_in if a.get("adjustment_type") == "inflow" else adj_out
        bucket[code] = bucket.get(code, 0.0) + amt
    return adj_in, adj_out


def _merge_fund_rows(
    inflow: Dict[str, float], out_orders: Dict[str, float],
    out_clients: Dict[str, float], out_company: Dict[str, float],
    adj_in: Dict[str, float], adj_out: Dict[str, float],
) -> List[dict]:
    """Combine the per-source aggregates into sorted per-currency rows."""
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


def _range_bounds(date_query: Dict[str, Any]) -> tuple[str, str]:
    """Extract (since_iso, until_iso) from a `_date_range_query` result."""
    if "created_at" not in date_query:
        return "", ""
    return (
        date_query["created_at"].get("$gte", "") or "",
        date_query["created_at"].get("$lte", "") or "",
    )


def _updated_at_range_query(since_iso: str, until_iso: str) -> Dict[str, Any]:
    """Confirmed/completed orders filter constrained by `updated_at` range."""
    q: Dict[str, Any] = {"status": {"$in": ["approved", "completed"]}}
    ts_q: Dict[str, Any] = {}
    if since_iso:
        ts_q["$gte"] = since_iso
    if until_iso:
        ts_q["$lte"] = until_iso
    if ts_q:
        q["updated_at"] = ts_q
    return q


async def _closing_revenue_rows(
    orders: List[dict], rate_by_pair: Dict[Any, dict], fx: Any,
) -> tuple[List[dict], float, int]:
    """Per-currency fees from in-range orders + USD total + order count."""
    from services.orders_helpers import compute_order_profit
    from services.balances import convert_to_usdt

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

    rows: List[dict] = []
    total_usd = 0.0
    for code in sorted(revenue_by_currency):
        fees_native = revenue_by_currency[code]
        fees_usd = convert_to_usdt(fees_native, code, fx) or 0.0
        rows.append({
            "currency": code,
            "fees": round(fees_native, 4),
            "fees_usd": round(fees_usd, 2),
        })
        total_usd += fees_usd
    return rows, total_usd, total_orders


def _closing_kpis(orders: List[dict], funds_rows: List[dict], fx: Any,
                  total_orders: int, total_revenue_usd: float) -> Dict[str, Any]:
    """Executive KPIs — gross volume USD + treasury USD in-range."""
    from services.balances import convert_to_usdt
    total_volume_usd = sum(
        convert_to_usdt(o.get("amount_from", 0), o.get("from_code") or "", fx) or 0.0
        for o in orders
    )
    treasury_usd = sum(
        convert_to_usdt(r["balance"], r["currency"], fx) or 0.0
        for r in funds_rows
    )
    return {
        "total_orders": total_orders,
        "gross_volume_usd": round(total_volume_usd, 2),
        "revenue_usd": round(total_revenue_usd, 2),
        "treasury_usd": round(treasury_usd, 2),
    }


def _closing_filename(since: Optional[str], until: Optional[str]) -> str:
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    if since and until:
        slug = f"_{since}_{until}"
    elif since:
        slug = f"_desde_{since}"
    elif until:
        slug = f"_hasta_{until}"
    else:
        slug = ""
    return f"cierre_empresa{slug}_{ts}.pdf"


async def _closing_report_data(
    since: Optional[str], until: Optional[str],
) -> tuple[List[dict], List[dict], dict, int]:
    """Agrega tesorería + ingresos + KPIs del rango para el PDF de cierre."""
    from services.balances import build_rate_lookup
    since_iso, until_iso = _range_bounds(_date_range_query(since, until))
    funds_rows = await _compute_company_funds_range(since_iso, until_iso)
    orders = await db.orders.find(
        _updated_at_range_query(since_iso, until_iso), {"_id": 0},
    ).to_list(20000)
    rates = await db.rates.find({}, {"_id": 0}).to_list(500)
    rate_by_pair = {(r["from_code"], r["to_code"]): r for r in rates}
    fx = await build_rate_lookup()
    revenue_rows, total_revenue_usd, total_orders = await _closing_revenue_rows(
        orders, rate_by_pair, fx,
    )
    kpis = _closing_kpis(orders, funds_rows, fx, total_orders, total_revenue_usd)
    return funds_rows, revenue_rows, kpis, total_orders


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

    from company_closing_pdf import generate_company_closing_pdf

    actor = await require_permission(request, "company_funds")
    funds_rows, revenue_rows, kpis, total_orders = await _closing_report_data(
        since, until,
    )
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
    filename = _closing_filename(since, until)
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
