"""Payment accounts router — iter143.

Client-facing:
- GET  /payment-accounts/resolve?currency=USD&amount=250
    → the account the client must send to (highest matching min tier).

Staff (RBAC permission `payment_accounts`):
- GET    /admin/payment-accounts
- POST   /admin/payment-accounts          (+ TOTP step-up)
- PUT    /admin/payment-accounts/{id}     (+ TOTP step-up)
- DELETE /admin/payment-accounts/{id}
"""
import io
import csv
import uuid
import logging
from datetime import timedelta
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from io import BytesIO
from pydantic import BaseModel, ConfigDict, Field, field_validator

from db_client import db
from auth_utils import (
    require_user, require_permission,
    _enforce_totp_step_up,
    now_utc, iso,
)
from audit_log import log_action
from services.payment_accounts import resolve_for_amount, get_active_accounts, pick_account


logger = logging.getLogger(__name__)
router = APIRouter(tags=["PaymentAccounts"])


def _needs_notice(old_id: str, new_id: str, changed_ids: set) -> bool:
    if (old_id or new_id) and old_id != new_id:
        return True
    return bool(new_id and new_id in changed_ids)


async def _scan_and_notify_pending(currency_code: str, changed_details_ids: set) -> None:
    """iter144 — after any account mutation, re-resolve every pending order and
    pending VIP batch item of the currency; warn affected clients (in-app +
    push) that the account they must send to changed or is gone. Best-effort."""
    accounts = await get_active_accounts(currency_code)
    has_accounts = bool(accounts)
    affected: dict = {}  # user_id -> {"new_ids": set, "accounts": dict}

    def mark(uid: str, old_id: Any, new_acc: Any) -> None:
        new_id = (new_acc or {}).get("id") or ""
        if not uid or not _needs_notice(old_id or "", new_id, changed_details_ids):
            return
        slot = affected.setdefault(uid, {"new_ids": set(), "accounts": {}})
        slot["new_ids"].add(new_id)
        if new_acc:
            slot["accounts"][new_id] = new_acc

    orders = await db.orders.find(
        {"from_code": currency_code,
         "status": {"$in": ["pending", "requires_double_approval"]}},
        {"_id": 0, "user_id": 1, "amount_from": 1, "payment_account_id": 1},
    ).to_list(2000)
    for o in orders:
        mark(o.get("user_id"), o.get("payment_account_id"),
             pick_account(accounts, float(o.get("amount_from") or 0.0)))

    items = await db.vip_batch_items.find(
        {"from_code": currency_code, "status": "pending"},
        {"_id": 0, "vip_user_id": 1, "amount": 1, "payment_account_id": 1},
    ).to_list(5000)
    for it in items:
        mark(it.get("vip_user_id"), it.get("payment_account_id"),
             pick_account(accounts, float(it.get("amount") or 0.0)))

    if not affected:
        return
    from routes.notifications import _insert_notification
    from services.notification_i18n import t as _t, resolve_lang
    from push_service import send_push_to_user

    for uid, slot in affected.items():
        lang = await resolve_lang(db, uid)
        new_ids = slot["new_ids"]
        # Worst state wins: some pending row has NO account for its amount
        # while the currency still has tiered accounts → "unavailable".
        if "" in new_ids and has_accounts:
            key = "payment_account_unavailable"
            message = _t(key, lang, "message", currency=currency_code)
        else:
            key = "payment_account_changed"
            details_block = ""
            real_ids = {i for i in new_ids if i}
            if len(real_ids) == 1 and "" not in new_ids:
                acc = slot["accounts"][next(iter(real_ids))]
                details_block = _t(key, lang, "details_block",
                                   label=acc.get("label", ""),
                                   details=(acc.get("account_details") or "")[:400])
            message = _t(key, lang, "message", currency=currency_code,
                         details_block=details_block)
        title = _t(key, lang, "title")
        await _insert_notification(
            recipient_user_id=uid, type=key, title=title, message=message,
            data={"currency_code": currency_code},
        )
        await send_push_to_user(db, uid, {
            "title": title,
            "body": _t(key, lang, "push_body", currency=currency_code),
            "icon": "/icons/icon-192.png",
            "badge": "/icons/icon-192.png",
            "tag": f"payacc-{currency_code}",
            "url": "/dashboard/exchange",
        })
    logger.info(f"[payacc-notify] {currency_code}: notified {len(affected)} client(s)")


class PaymentAccountCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    currency_code: str = Field(..., min_length=1, max_length=16)
    label: str = Field(..., min_length=1, max_length=80)
    account_details: str = Field(..., min_length=1, max_length=1500)
    # iter151 — Optional network / method the client must send through
    # (e.g. "BEP20", "TRC20", "ERC20", "Polygon", "SEPA", "Zelle"). Shown
    # to the client as a highlighted warning above the wallet address so
    # they don't send USDT via the wrong chain and lose the funds.
    network: Optional[str] = Field(None, max_length=30)
    min_amount: float = Field(..., ge=0)
    max_amount: Optional[float] = Field(None, gt=0)
    is_active: bool = True
    totp_code: Optional[str] = Field(None, max_length=11)

    @field_validator("currency_code", mode="before")
    @classmethod
    def _norm_code(cls, v: Any) -> Any:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("network", mode="before")
    @classmethod
    def _norm_network(cls, v: Any) -> Any:
        if v is None:
            return None
        if not isinstance(v, str):
            return v
        v = v.strip()
        return v or None


def _assert_range(payload: PaymentAccountCreate) -> None:
    if payload.max_amount is not None and payload.max_amount <= payload.min_amount:
        raise HTTPException(
            status_code=400,
            detail="El monto máximo debe ser mayor que el mínimo.",
        )


@router.get("/payment-accounts/resolve")
async def resolve_payment_account(
    request: Request, currency: str, amount: float = 0.0,
) -> Any:
    await require_user(request)
    res = await resolve_for_amount(currency, amount)
    acc = res["account"]
    return {
        "currency_code": res["currency_code"],
        "has_tiers": res["has_tiers"],
        "min_required": res["min_required"],
        "below_min": res["below_min"],
        "account": ({
            "id": acc["id"],
            "label": acc.get("label", ""),
            "account_details": acc.get("account_details", ""),
            "network": acc.get("network") or "",
            "min_amount": acc.get("min_amount"),
            "max_amount": acc.get("max_amount"),
        } if acc else None),
    }


@router.get("/admin/payment-accounts/filter-options")
async def payment_account_filter_options(request: Request) -> Any:
    """iter145 — lightweight options for the orders reconciliation filter.
    Gated by `orders` (not `payment_accounts`): order staff need to filter
    by account without being allowed to edit accounts."""
    await require_permission(request, "orders")
    rows = await db.payment_accounts.find(
        {}, {"_id": 0, "id": 1, "label": 1, "currency_code": 1, "is_active": 1,
             "min_amount": 1},
    ).to_list(500)
    rows.sort(key=lambda a: (
        (a.get("currency_code") or ""), float(a.get("min_amount") or 0.0),
    ))
    return rows


@router.get("/admin/payment-accounts/daily-totals")
async def payment_account_daily_totals(request: Request, days: int = 14) -> Any:
    """iter145 — daily inflow per collection account for bank reconciliation.
    Day = UTC ISO date (created_at[:10], platform reporting convention).
    `confirmed` = approved/completed orders + approved batch items;
    `pending` = still-in-review rows (money usually already sent).
    Rejected rows are excluded."""
    await require_permission(request, "payment_accounts")
    return await _daily_totals(days)


async def _daily_totals(days: int, account_id: Optional[str] = None) -> dict:
    days = max(1, min(days, 90))
    start = (now_utc() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    acc_match = {"$nin": [None, ""]} if not account_id else account_id
    accounts = {
        a["id"]: a
        for a in await db.payment_accounts.find({}, {"_id": 0}).to_list(500)
    }
    rows: dict = {}

    def slot(day: str, acc_id: str, fallback_label: str, fallback_cur: str) -> dict:
        key = (day, acc_id)
        if key not in rows:
            acc = accounts.get(acc_id) or {}
            rows[key] = {
                "date": day, "account_id": acc_id,
                "label": acc.get("label") or fallback_label or "?",
                "currency_code": acc.get("currency_code") or fallback_cur or "",
                "confirmed": 0.0, "pending": 0.0,
                "count_confirmed": 0, "count_pending": 0,
            }
        return rows[key]

    orders = await db.orders.find(
        {"payment_account_id": acc_match,
         "status": {"$ne": "rejected"}, "created_at": {"$gte": start}},
        {"_id": 0, "payment_account_id": 1, "payment_account_label": 1,
         "from_code": 1, "amount_from": 1, "status": 1, "created_at": 1},
    ).to_list(20000)
    for o in orders:
        day = (o.get("created_at") or "")[:10]
        if not day:
            continue
        s = slot(day, o["payment_account_id"],
                 o.get("payment_account_label"), o.get("from_code"))
        amt = float(o.get("amount_from") or 0.0)
        if o.get("status") in ("approved", "completed"):
            s["confirmed"] += amt
            s["count_confirmed"] += 1
        else:
            s["pending"] += amt
            s["count_pending"] += 1

    items = await db.vip_batch_items.find(
        {"payment_account_id": acc_match,
         "status": {"$ne": "rejected"}, "created_at": {"$gte": start}},
        {"_id": 0, "payment_account_id": 1, "payment_account_label": 1,
         "from_code": 1, "amount": 1, "status": 1, "created_at": 1},
    ).to_list(50000)
    for it in items:
        day = (it.get("created_at") or "")[:10]
        if not day:
            continue
        s = slot(day, it["payment_account_id"],
                 it.get("payment_account_label"), it.get("from_code"))
        amt = float(it.get("amount") or 0.0)
        if it.get("status") == "approved":
            s["confirmed"] += amt
            s["count_confirmed"] += 1
        else:
            s["pending"] += amt
            s["count_pending"] += 1

    out = sorted(rows.values(),
                 key=lambda r: (r["date"], r["currency_code"], r["label"]))
    out.reverse()
    for r in out:
        r["confirmed"] = round(r["confirmed"], 2)
        r["pending"] = round(r["pending"], 2)
        r["total"] = round(r["confirmed"] + r["pending"], 2)
    return {"start": start, "days": days, "rows": out}


async def _export_account_label(account_id: Optional[str]) -> str:
    if not account_id:
        return ""
    acc = await db.payment_accounts.find_one({"id": account_id}, {"_id": 0})
    return (acc or {}).get("label") or account_id


@router.get("/admin/payment-accounts/daily-totals/export.csv")
async def export_daily_totals_csv(request: Request, days: int = 14,
                                  account: Optional[str] = None) -> Any:
    await require_permission(request, "payment_accounts")
    data = await _daily_totals(days, account)
    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    writer.writerow(["fecha", "cuenta", "moneda", "confirmado", "pendiente",
                     "total", "ops_confirmadas", "ops_pendientes"])
    for r in data["rows"]:
        writer.writerow([
            r["date"], r["label"], r["currency_code"],
            f"{r['confirmed']:.2f}", f"{r['pending']:.2f}", f"{r['total']:.2f}",
            r["count_confirmed"], r["count_pending"],
        ])
    buf = BytesIO(text_buf.getvalue().encode("utf-8-sig"))
    ts = now_utc().strftime("%Y%m%d_%H%M")
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="conciliacion_cuentas_{ts}.csv"'},
    )


@router.get("/admin/payment-accounts/daily-totals/export.pdf")
async def export_daily_totals_pdf(request: Request, days: int = 14,
                                  account: Optional[str] = None) -> Any:
    actor = await require_permission(request, "payment_accounts")
    data = await _daily_totals(days, account)
    from reconciliation_pdf import generate_reconciliation_pdf
    pdf_bytes = generate_reconciliation_pdf(
        data["rows"], data["start"],
        await _export_account_label(account), actor,
    )
    ts = now_utc().strftime("%Y%m%d_%H%M")
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="conciliacion_cuentas_{ts}.pdf"'},
    )


@router.get("/admin/payment-accounts")
async def list_payment_accounts(
    request: Request, currency: Optional[str] = None,
) -> Any:
    await require_permission(request, "payment_accounts")
    q: dict = {}
    if currency:
        q["currency_code"] = currency.strip().upper()
    rows = await db.payment_accounts.find(q, {"_id": 0}).to_list(500)
    rows.sort(key=lambda a: (
        (a.get("currency_code") or ""), float(a.get("min_amount") or 0.0),
    ))
    return rows


@router.post("/admin/payment-accounts")
async def create_payment_account(
    payload: PaymentAccountCreate, request: Request,
) -> Any:
    actor = await require_permission(request, "payment_accounts")
    await _enforce_totp_step_up(actor, payload.totp_code,
                                action_label="crear cuenta de cobro")
    _assert_range(payload)
    doc = {
        "id": f"payacc_{uuid.uuid4().hex[:12]}",
        **payload.model_dump(exclude={"totp_code"}),
        "created_at": iso(now_utc()),
        "updated_at": iso(now_utc()),
    }
    await db.payment_accounts.insert_one(dict(doc))
    await log_action(
        db, actor, "payment_account.create", "payment_account", doc["id"],
        summary=(f"Cuenta de cobro creada: {doc['currency_code']} · "
                 f"{doc['label']} (mín {doc['min_amount']:g})"),
        details={"new": doc},
    )
    try:
        await _scan_and_notify_pending(doc["currency_code"], set())
    except Exception as e:
        logger.error(f"payacc create notify failed: {e}")
    return doc


@router.put("/admin/payment-accounts/{account_id}")
async def update_payment_account(
    account_id: str, payload: PaymentAccountCreate, request: Request,
) -> Any:
    actor = await require_permission(request, "payment_accounts")
    await _enforce_totp_step_up(actor, payload.totp_code,
                                action_label="editar cuenta de cobro")
    _assert_range(payload)
    old = await db.payment_accounts.find_one({"id": account_id}, {"_id": 0})
    if not old:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada.")
    await db.payment_accounts.update_one(
        {"id": account_id},
        {"$set": {**payload.model_dump(exclude={"totp_code"}),
                  "updated_at": iso(now_utc())}},
    )
    fresh = await db.payment_accounts.find_one({"id": account_id}, {"_id": 0})
    await log_action(
        db, actor, "payment_account.update", "payment_account", account_id,
        summary=(f"Cuenta de cobro actualizada: {fresh['currency_code']} · "
                 f"{fresh['label']} (mín {fresh['min_amount']:g})"),
        details={"old": old, "new": fresh},
    )
    try:
        changed_ids = set()
        if (old.get("account_details") or "").strip() != (fresh.get("account_details") or "").strip():
            changed_ids.add(account_id)
        for code in {old.get("currency_code"), fresh.get("currency_code")}:
            if code:
                await _scan_and_notify_pending(code, changed_ids)
    except Exception as e:
        logger.error(f"payacc update notify failed: {e}")
    return fresh


@router.delete("/admin/payment-accounts/{account_id}")
async def delete_payment_account(account_id: str, request: Request) -> Any:
    actor = await require_permission(request, "payment_accounts")
    old = await db.payment_accounts.find_one({"id": account_id}, {"_id": 0})
    if not old:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada.")
    await db.payment_accounts.delete_one({"id": account_id})
    await log_action(
        db, actor, "payment_account.delete", "payment_account", account_id,
        summary=(f"Cuenta de cobro eliminada: {old.get('currency_code')} · "
                 f"{old.get('label')}"),
        details={"old": old},
    )
    try:
        await _scan_and_notify_pending(old.get("currency_code") or "", set())
    except Exception as e:
        logger.error(f"payacc delete notify failed: {e}")
    return {"ok": True}
