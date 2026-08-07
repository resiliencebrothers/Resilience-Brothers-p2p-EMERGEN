"""iter110 · Phase 1 — VIP batch operations + running balance.

Business model (25 Jul 2026):
  A VIP client is essentially a broker aggregating remittances/exchanges
  from his own downstream clients. Instead of one order at a time (each
  with its own proof), the VIP now files **batches** of individual items
  (only "holder name + amount"), which the admin approves one-by-one.
  Every approval nudges the VIP's running USDT balance:

    - direction = "credit" (VIP delivered value to us — e.g. Zelle, USDT):
        positive_usdt += amount_usdt      (we owe the VIP)
    - direction = "debit" (we delivered value on the VIP's behalf — e.g.
                          CUP transferencia to end beneficiaries and the
                          VIP will settle later in USDT):
        negative_usdt += amount_usdt      (the VIP owes us)

  Two separate ledgers, no automatic netting. Settlement happens via
  Phase 3 (later).

Coexistence: the classic per-order flow (with proofs) stays available
for VIPs who prefer it. Phase 1 introduces batches as an *additional*
path — no destructive migrations.

Collections:
  vip_batches
    { id, vip_user_id, vip_email, vip_name, direction,
      currency, note?, status, totals, timestamps }
  vip_batch_items
    { id, batch_id, vip_user_id, holder_name, amount,
      currency, direction, status, admin_note?, balance_delta_usdt,
      timestamps, reviewed_by }
  vip_ledger
    { vip_user_id, positive_usdt, negative_usdt, updated_at }

Endpoints:
  # VIP client
  GET  /api/vip/balance
  POST /api/vip/batches
  GET  /api/vip/batches
  GET  /api/vip/batches/{id}
  POST /api/vip/batches/{id}/items
  POST /api/vip/batches/{id}/close
  # Admin / staff with `orders` permission
  GET  /api/admin/vip-batches
  GET  /api/admin/vip-batches/pending-count
  POST /api/admin/vip-batches/items/{item_id}/approve
  POST /api/admin/vip-batches/items/{item_id}/reject
"""
from __future__ import annotations

import uuid
import logging
from typing import Any, Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import require_user, require_permission, iso, now_utc
from audit_log import log_action
from services.balances import build_rate_lookup, convert_to_usdt
from services.delivery_rules import allowed_delivery_methods
from services.rate_tiers import effective_rates, normalize_tiers
from services.payment_accounts import (
    get_active_accounts, pick_account, min_required as pa_min_required,
)
from services.vip_batch_alerts import dispatch_vip_batch_alerts

logger = logging.getLogger("vip_batches")

router = APIRouter(tags=["VIP Batches"])

MAX_ITEMS_PER_BATCH = 500
MAX_BATCHES_OPEN_PER_VIP = 20
ALLOWED_DIRECTIONS = {"credit", "debit"}


# ============================================================
# Payloads
# ============================================================

class VipBatchCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # iter113 — pair-based batches (owner redesign): the VIP picks an exchange
    # pair (from_code → to_code). Legacy single-currency direction batches are
    # still accepted for backward compat when from/to are omitted.
    direction: Optional[str] = Field(default=None, pattern="^(credit|debit)$")
    currency: Optional[str] = Field(default=None, min_length=1, max_length=16)
    from_code: Optional[str] = Field(default=None, min_length=1, max_length=16)
    to_code: Optional[str] = Field(default=None, min_length=1, max_length=16)
    note: Optional[str] = Field(default=None, max_length=200)


class VipBatchItemIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # holder_name is optional when the destination requires a CUP card — the
    # card becomes the item identifier. Enforced per-batch in the endpoint.
    holder_name: str = Field(default="", max_length=120)
    amount: float = Field(..., gt=0, le=10_000_000)
    card_number: Optional[str] = Field(default=None, max_length=40)


class VipBatchItemsBulk(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: List[VipBatchItemIn] = Field(..., min_length=1, max_length=100)


class RejectPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    admin_note: str = Field(default="", max_length=300)


# ============================================================
# Helpers
# ============================================================

def _serialize(doc: dict) -> dict:
    d = dict(doc)
    d.pop("_id", None)
    return d


async def _ensure_ledger(vip_user_id: str) -> dict:
    doc = await db.vip_ledger.find_one({"vip_user_id": vip_user_id}, {"_id": 0})
    if doc:
        return doc
    fresh = {
        "vip_user_id": vip_user_id,
        "positive_usdt": 0.0,
        "negative_usdt": 0.0,
        "updated_at": iso(now_utc()),
    }
    await db.vip_ledger.insert_one(dict(fresh))
    return fresh


async def _increment_ledger(vip_user_id: str, direction: str, delta_usdt: float) -> None:
    field = "positive_usdt" if direction == "credit" else "negative_usdt"
    await db.vip_ledger.update_one(
        {"vip_user_id": vip_user_id},
        {"$inc": {field: float(delta_usdt)},
         "$set": {"updated_at": iso(now_utc())}},
        upsert=True,
    )


async def _refresh_batch_totals(batch_id: str) -> None:
    """Recompute the summary counters on the parent batch."""
    pipeline = [
        {"$match": {"batch_id": batch_id}},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
            "amount": {"$sum": "$amount"},
        }},
    ]
    rows = await db.vip_batch_items.aggregate(pipeline).to_list(10)
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    amount_pending = 0.0
    amount_approved = 0.0
    for r in rows:
        counts[r["_id"]] = r["count"]
        if r["_id"] == "pending":
            amount_pending = r["amount"]
        if r["_id"] == "approved":
            amount_approved = r["amount"]
    await db.vip_batches.update_one(
        {"id": batch_id},
        {"$set": {
            "items_pending": counts["pending"],
            "items_approved": counts["approved"],
            "items_rejected": counts["rejected"],
            "amount_pending": round(amount_pending, 2),
            "amount_approved": round(amount_approved, 2),
            "updated_at": iso(now_utc()),
        }},
    )


async def _notify_staff_new_batch(batch: dict) -> None:
    try:
        from routes.notifications import _insert_notification
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_batches] notif import failed: {e}")
        return
    cursor = db.users.find(
        {"$or": [
            {"role": "admin"},
            {"role": "employee", "allowed_permissions": "orders"},
            {"role": "employee", "allowed_permissions": {"$in": [[], None]}},
        ]},
        {"_id": 0, "user_id": 1},
    )
    label = "envió" if batch["direction"] == "credit" else "necesita CUP por"
    if batch.get("to_code"):
        label = f"abrió lote {batch['from_code']}→{batch['to_code']} de"
    async for r in cursor:
        try:
            await _insert_notification(
                recipient_user_id=r["user_id"],
                type="new_vip_batch",
                title="Nuevo lote VIP",
                message=f"{batch.get('vip_name') or batch.get('vip_email')} {label} {batch['currency']}.",
                data={"batch_id": batch["id"], "vip_user_id": batch["vip_user_id"]},
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[vip_batches] notify {r['user_id']} failed: {e}")


async def _notify_vip_item_decision(item: dict, approved: bool, admin_note: str = "") -> None:
    try:
        from routes.notifications import _insert_notification
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_batches] notif import failed: {e}")
        return
    if approved:
        title = "Orden VIP aprobada"
        if item.get("to_code"):
            credited = item.get("amount_to") or 0
            message = (f"{item['holder_name']} · {item['amount']} {item.get('from_code', '')} confirmada — "
                       f"se acreditaron {credited} {item['to_code']} a tu saldo.")
        else:
            message = f"{item['holder_name']} · {item['amount']} {item['currency']} confirmada."
    else:
        title = "Orden VIP rechazada"
        message = admin_note or f"{item['holder_name']} · {item['amount']} {item['currency']} rechazada."
    try:
        await _insert_notification(
            recipient_user_id=item["vip_user_id"],
            type="vip_batch_item_decision",
            title=title,
            message=message,
            data={"item_id": item["id"], "batch_id": item["batch_id"]},
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_batches] vip notify failed: {e}")


def _require_vip(user: dict) -> None:
    if user.get("role") != "vip":
        raise HTTPException(
            status_code=403,
            detail="Solo los clientes VIP pueden usar la operativa por lotes.",
        )


async def _allowed_batch_pairs() -> list:
    """iter113 — exchange pairs available for VIP batches: every configured
    rate whose BOTH currencies are active AND whose destination currency has
    at least one withdrawal/delivery method (CUP transferencia, CUP efectivo,
    USDT, USD, AED, ...). Returns rate_vip per pair."""
    currencies = await db.currencies.find({}, {"_id": 0}).to_list(500)
    cur_by_code: dict = {}
    for c in currencies:
        code = (c.get("code") or "").strip().upper()
        if code and c.get("is_active") is not False:
            cur_by_code[code] = c
    rates = await db.rates.find({}, {"_id": 0}).to_list(1000)
    items, seen = [], set()
    for r in rates:
        fc = (r.get("from_code") or "").strip().upper()
        tc = (r.get("to_code") or "").strip().upper()
        if not fc or not tc or fc == tc or (fc, tc) in seen:
            continue
        if fc not in cur_by_code or tc not in cur_by_code:
            continue
        if not allowed_delivery_methods(cur_by_code[tc]):
            continue
        rate_vip = float(r.get("rate_vip") or 0.0)
        if rate_vip <= 0:
            continue
        seen.add((fc, tc))
        tiers = [
            {"min_amount": float(t["min_amount"]),
             "rate_vip": float(t.get("rate_vip") or 0.0)}
            for t in normalize_tiers(r.get("tiers"))
        ]
        tiers.sort(key=lambda t: t["min_amount"])
        items.append({
            "pair": f"{fc}->{tc}",
            "from_code": fc,
            "to_code": tc,
            "from_name": (cur_by_code[fc].get("name") or fc).strip(),
            "to_name": (cur_by_code[tc].get("name") or tc).strip(),
            "rate_vip": rate_vip,
            "tiers": tiers,
            "requires_card": False,
        })
    items.sort(key=lambda x: (x["from_code"], x["to_code"]))
    return items


async def _current_pair_rates(from_code: str, to_code: str,
                              amount: Optional[float] = None) -> tuple:
    """Return (rate_vip, real_rate) for the pair — 0.0 when missing.
    iter143 — when `amount` is given and the rate row has amount `tiers`,
    the matching tier overrides the base rates."""
    doc = await db.rates.find_one(
        {"from_code": from_code, "to_code": to_code}, {"_id": 0},
    )
    if not doc:
        return (0.0, 0.0)
    eff = effective_rates(doc, amount)
    return (eff["rate_vip"], eff["real_rate"] or 0.0)


def _staff_pair_allowed(staff: dict, item: dict) -> bool:
    """iter113 — per-pair staff RBAC. Admin always passes; employees with an
    empty/unset `allowed_batch_pairs` keep full access (backward compat);
    scoped employees can only work items whose pair is in their list."""
    if staff.get("role") == "admin":
        return True
    allowed = staff.get("allowed_batch_pairs") or []
    if not allowed:
        return True
    if not item.get("to_code"):
        return False  # legacy non-pair items reserved to unscoped staff/admin
    return f"{item.get('from_code')}->{item.get('to_code')}" in allowed


def _requires_cup_card(cur: dict | None) -> bool:  # noqa: ARG001
    """iter161 — ALWAYS False. Business rule changed (owner, Ago 2026): batch
    items credit the client's PLATFORM BALANCE when confirmed; the payout card
    is asked later, in the bank-transfer withdrawal flow. Batch rows now only
    need the sender's name + amount (the collection account is auto-assigned
    by amount). Kept as a function so legacy call sites stay untouched."""
    return False


def _normalize_cup_card(raw: Optional[str]) -> Optional[str]:
    """16 digits → '9212 9598 7274 4356'; anything else → None."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) != 16:
        return None
    return " ".join(digits[i:i + 4] for i in range(0, 16, 4))


# ============================================================
# VIP endpoints
# ============================================================

@router.get("/vip/balance")
async def get_vip_balance(request: Request) -> Any:
    user = await require_user(request)
    _require_vip(user)
    ledger = await _ensure_ledger(user["user_id"])
    return {
        "positive_usdt": round(ledger.get("positive_usdt", 0.0), 2),
        "negative_usdt": round(ledger.get("negative_usdt", 0.0), 2),
        "net_usdt": round(
            ledger.get("positive_usdt", 0.0) - ledger.get("negative_usdt", 0.0), 2,
        ),
        "updated_at": ledger.get("updated_at"),
    }


@router.get("/vip/batch-currencies")
async def list_vip_batch_currencies(request: Request) -> Any:
    """iter112 — currencies the platform offers for VIP batch/ledger ops.

    Only active currencies with a configured USDT conversion path are
    returned, each with `usdt_per_unit` (value of 1 unit in USDT — same
    lookup the admin approval path uses) so the client can render the
    representative rate. USDT is always listed first.
    """
    user = await require_user(request)
    _require_vip(user)
    currencies = await db.currencies.find({}, {"_id": 0}).to_list(500)
    rates = await build_rate_lookup()
    items = []
    seen: set[str] = set()
    for c in currencies:
        if c.get("is_active") is False:
            continue
        code = (c.get("code") or "").strip().upper()
        if not code or code in seen:
            continue
        per_unit = convert_to_usdt(1.0, code, rates)
        if per_unit is None or per_unit <= 0:
            continue
        seen.add(code)
        items.append({
            "code": code,
            "name": (c.get("name") or code).strip(),
            "type": c.get("type") or "",
            "usdt_per_unit": round(float(per_unit), 6),
        })
    items.sort(key=lambda x: (x["code"] != "USDT", x["code"]))
    return {"items": items}


@router.get("/vip/batch-pairs")
async def list_vip_batch_pairs(request: Request) -> Any:
    """iter113 — pairs the VIP can open batches for (with the VIP rate)."""
    user = await require_user(request)
    _require_vip(user)
    return {"items": await _allowed_batch_pairs()}


@router.get("/admin/vip-batch-pairs")
async def admin_list_batch_pairs(request: Request) -> Any:
    """iter113 — pair catalog for the staff RBAC selector in /admin/users."""
    await require_permission(request, "orders")
    return {"items": await _allowed_batch_pairs()}


@router.post("/vip/batches")
async def create_vip_batch(payload: VipBatchCreate, request: Request) -> Any:
    user = await require_user(request)
    _require_vip(user)

    fc = (payload.from_code or "").strip().upper()
    tc = (payload.to_code or "").strip().upper()
    pair = None
    if fc and tc:
        pairs = await _allowed_batch_pairs()
        pair = next((p for p in pairs if p["from_code"] == fc and p["to_code"] == tc), None)
        if not pair:
            raise HTTPException(
                status_code=422,
                detail=(f"El par {fc}→{tc} no está disponible para lotes. "
                        "Verifica que exista tasa VIP y que la moneda destino sea retirable."),
            )
    else:
        if payload.direction not in ALLOWED_DIRECTIONS or not (payload.currency or "").strip():
            raise HTTPException(status_code=422, detail="Debes elegir el par de cambio del lote.")

    open_count = await db.vip_batches.count_documents(
        {"vip_user_id": user["user_id"], "status": "open"},
    )
    if open_count >= MAX_BATCHES_OPEN_PER_VIP:
        raise HTTPException(
            status_code=409,
            detail=f"Ya tienes {open_count} lotes abiertos (máx {MAX_BATCHES_OPEN_PER_VIP}). Cierra alguno antes de crear otro.",
        )

    doc = {
        "id": f"vbatch_{uuid.uuid4().hex[:12]}",
        "vip_user_id": user["user_id"],
        "vip_email": user.get("email", ""),
        "vip_name": user.get("name", ""),
        "direction": "pair" if pair else payload.direction,
        "currency": fc if pair else payload.currency.strip().upper(),
        "from_code": fc or None,
        "to_code": tc or None,
        "rate_vip": pair["rate_vip"] if pair else None,
        "requires_card": False,
        "note": (payload.note or "").strip() or None,
        "status": "open",
        "items_pending": 0,
        "items_approved": 0,
        "items_rejected": 0,
        "amount_pending": 0.0,
        "amount_approved": 0.0,
        "created_at": iso(now_utc()),
        "updated_at": iso(now_utc()),
        "closed_at": None,
    }
    await db.vip_batches.insert_one(dict(doc))
    await log_action(
        db=db, actor=user, action="vip_batch.create",
        entity_type="vip_batch", entity_id=doc["id"],
        details={"direction": doc["direction"], "currency": doc["currency"],
                 "pair": f"{fc}->{tc}" if pair else None},
    )
    await _notify_staff_new_batch(doc)
    return _serialize(doc)


@router.post("/vip/batches/{batch_id}/items")
async def add_vip_batch_items(batch_id: str, payload: VipBatchItemsBulk, request: Request) -> Any:
    user = await require_user(request)
    _require_vip(user)

    batch = await db.vip_batches.find_one({"id": batch_id, "vip_user_id": user["user_id"]}, {"_id": 0})
    if not batch:
        raise HTTPException(status_code=404, detail="Lote no encontrado.")
    if batch["status"] != "open":
        raise HTTPException(status_code=409, detail="El lote está cerrado, no se pueden agregar más órdenes.")

    total_items = await db.vip_batch_items.count_documents({"batch_id": batch_id})
    if total_items + len(payload.items) > MAX_ITEMS_PER_BATCH:
        raise HTTPException(
            status_code=409,
            detail=f"Un lote no puede exceder {MAX_ITEMS_PER_BATCH} órdenes.",
        )

    # iter113 — pair batches snapshot the CURRENT vip rate on each item so
    # the amount credited is exactly what the client saw when adding the row.
    # iter143 — the rate can vary PER ITEM when the pair has amount tiers,
    # and each item resolves the payment account matching its own amount.
    rate_doc = None
    if batch.get("to_code"):
        rate_doc = await db.rates.find_one(
            {"from_code": batch["from_code"], "to_code": batch["to_code"]}, {"_id": 0},
        )
        if float((rate_doc or {}).get("rate_vip") or 0.0) <= 0:
            raise HTTPException(
                status_code=422,
                detail=(f"No hay tasa VIP configurada para {batch['from_code']}→{batch['to_code']}. "
                        "Contacta al equipo."),
            )
    accounts = await get_active_accounts(batch["from_code"]) if batch.get("from_code") else []
    accounts_min = pa_min_required(accounts)

    requires_card = batch.get("requires_card")
    if requires_card is None and batch.get("to_code"):
        cur = await db.currencies.find_one({"code": batch["to_code"]}, {"_id": 0})
        requires_card = _requires_cup_card(cur)
    # iter161 — cards are no longer collected on batch items (they belong to
    # the withdrawal flow); force off even for batches opened before the rule.
    requires_card = False

    now = iso(now_utc())
    docs = []
    for it in payload.items:
        amount = round(float(it.amount), 2)
        rate_applied = None
        if rate_doc:
            rate_applied = effective_rates(rate_doc, amount)["rate_vip"]
        account = pick_account(accounts, amount) if accounts else None
        if accounts and account is None:
            if accounts_min is not None and amount < accounts_min:
                detail = (f"El monto mínimo para enviar {batch['from_code']} "
                          f"es {accounts_min:g}.")
            else:
                detail = (f"No hay una cuenta de cobro disponible para "
                          f"{amount:g} {batch['from_code']}. Contacta al equipo.")
            raise HTTPException(status_code=422, detail=detail)
        card = _normalize_cup_card(it.card_number)
        if requires_card and not card:
            raise HTTPException(
                status_code=422,
                detail="La tarjeta CUP de destino debe tener exactamente 16 dígitos.",
            )
        holder = " ".join((it.holder_name or "").split())
        if requires_card:
            holder = holder or card
        # iter161 — the FULL NAME (first + last) of the account holder who
        # SENDS the transfer is mandatory so staff can match incoming payments.
        if len([w for w in holder.split(" ") if len(w) >= 2]) < 2:
            raise HTTPException(
                status_code=422,
                detail=("Escribe el nombre y apellidos del titular de la "
                        "cuenta que envía la transferencia."),
            )
        docs.append({
            "id": f"vitem_{uuid.uuid4().hex[:12]}",
            "batch_id": batch_id,
            "vip_user_id": user["user_id"],
            "holder_name": holder,
            "card_number": card if requires_card else None,
            "amount": amount,
            "currency": batch["currency"],
            "direction": batch["direction"],
            "from_code": batch.get("from_code"),
            "to_code": batch.get("to_code"),
            "rate_applied": rate_applied,
            "amount_to": round(amount * rate_applied, 4) if rate_applied else None,
            "payment_account_id": (account or {}).get("id"),
            "payment_account_label": (account or {}).get("label"),
            "payment_account_details": (account or {}).get("account_details"),
            "payment_account_network": (account or {}).get("network"),
            "status": "pending",
            "admin_note": None,
            "balance_delta_usdt": None,
            "margin_usdt": None,
            "created_at": now,
            "updated_at": now,
            "reviewed_at": None,
            "reviewed_by": None,
        })
    await db.vip_batch_items.insert_many([dict(d) for d in docs])
    await _refresh_batch_totals(batch_id)
    # iter148 — massive-inflow threshold alerts (item + cumulative batch total)
    await dispatch_vip_batch_alerts(batch_id, docs, "added")
    return {"added": len(docs), "items": [_serialize(d) for d in docs]}


@router.get("/vip/batches")
async def list_vip_batches(request: Request, status: Optional[str] = None,
                            limit: int = 50) -> Any:
    user = await require_user(request)
    _require_vip(user)
    q: dict[str, Any] = {"vip_user_id": user["user_id"]}
    if status in ("open", "closed"):
        q["status"] = status
    cursor = db.vip_batches.find(q, {"_id": 0}).sort("created_at", -1).limit(min(max(1, limit), 200))
    return {"items": [_serialize(d) async for d in cursor]}


@router.get("/vip/batch-stats")
async def vip_batch_stats(request: Request) -> Any:
    """iter114 — counters for the client dashboard: batch orders must be
    included in the 'Pendientes' / 'Completadas' summary cards."""
    user = await require_user(request)
    _require_vip(user)
    base = {"vip_user_id": user["user_id"]}
    return {
        "items_pending": await db.vip_batch_items.count_documents({**base, "status": "pending"}),
        "items_approved": await db.vip_batch_items.count_documents({**base, "status": "approved"}),
        "items_rejected": await db.vip_batch_items.count_documents({**base, "status": "rejected"}),
    }


@router.get("/vip/batches/{batch_id}")
async def get_vip_batch(batch_id: str, request: Request) -> Any:
    user = await require_user(request)
    _require_vip(user)
    batch = await db.vip_batches.find_one({"id": batch_id, "vip_user_id": user["user_id"]}, {"_id": 0})
    if not batch:
        raise HTTPException(status_code=404, detail="Lote no encontrado.")
    if batch.get("to_code"):
        rate_row = await db.rates.find_one(
            {"from_code": batch["from_code"], "to_code": batch["to_code"]}, {"_id": 0},
        )
        batch["current_rate_vip"] = float((rate_row or {}).get("rate_vip") or 0.0) or None
        # iter143 — expose amount tiers (VIP view only needs min + rate_vip)
        # so the add-item preview can show the per-amount rate.
        tiers = [
            {"min_amount": float(t["min_amount"]),
             "rate_vip": float(t.get("rate_vip") or 0.0)}
            for t in normalize_tiers((rate_row or {}).get("tiers"))
        ]
        tiers.sort(key=lambda t: t["min_amount"])
        batch["rate_tiers"] = tiers
        # iter161 — cards are never collected on batch items anymore.
        batch["requires_card"] = False
    items = await db.vip_batch_items.find(
        {"batch_id": batch_id}, {"_id": 0},
    ).sort("created_at", 1).to_list(MAX_ITEMS_PER_BATCH + 1)
    return {"batch": _serialize(batch), "items": [_serialize(it) for it in items]}


@router.post("/vip/batches/{batch_id}/close")
async def close_vip_batch(batch_id: str, request: Request) -> Any:
    user = await require_user(request)
    _require_vip(user)
    batch = await db.vip_batches.find_one({"id": batch_id, "vip_user_id": user["user_id"]}, {"_id": 0})
    if not batch:
        raise HTTPException(status_code=404, detail="Lote no encontrado.")
    if batch["status"] != "open":
        raise HTTPException(status_code=409, detail="El lote ya está cerrado.")
    await db.vip_batches.update_one(
        {"id": batch_id},
        {"$set": {"status": "closed", "closed_at": iso(now_utc()), "updated_at": iso(now_utc())}},
    )
    return _serialize({**batch, "status": "closed", "closed_at": iso(now_utc())})


# ============================================================
# Admin endpoints
# ============================================================

@router.get("/admin/vip-batches/pending-count")
async def admin_vip_batches_pending_count(request: Request) -> Any:
    """iter112 — pending counters for the 3 admin sub-tabs (items, capital
    deposits, settlements). `pending` kept for backward compat."""
    await require_permission(request, "orders")
    items_pending = await db.vip_batch_items.count_documents({"status": "pending"})
    capital_pending = await db.vip_capital_deposits.count_documents({"status": "pending"})
    settlements_pending = await db.vip_settlements.count_documents({"status": "pending"})
    deposits_pending = await db.deposits.count_documents({"status": "pending"})
    return {
        "pending": items_pending,
        "items_pending": items_pending,
        "capital_pending": capital_pending,
        "settlements_pending": settlements_pending,
        "deposits_pending": deposits_pending,
        "total_pending": items_pending + capital_pending + settlements_pending + deposits_pending,
    }


@router.get("/admin/vip-batches")
async def admin_list_vip_batches(request: Request, status: Optional[str] = None,
                                  direction: Optional[str] = None,
                                  pair: Optional[str] = None,
                                  limit: int = 200) -> Any:
    """Return the flat item queue (what the admin approves one-by-one),
    enriched with parent batch metadata for context. iter113 — employees with
    a non-empty `allowed_batch_pairs` only see items for their pairs.
    Ago 2026 — `pair` param ("EUR->USDT" | "legacy") segments the queue
    server-side; `pair_counts` powers the per-pair filter chips."""
    staff = await require_permission(request, "orders")
    q: dict[str, Any] = {}
    if status in ("pending", "approved", "rejected"):
        q["status"] = status
    else:
        q["status"] = "pending"
    if direction in ALLOWED_DIRECTIONS:
        q["direction"] = direction
    pair_counts = []
    async for g in db.vip_batch_items.aggregate([
        {"$match": dict(q)},
        {"$group": {"_id": {"f": "$from_code", "t": "$to_code"}, "n": {"$sum": 1}}},
    ]):
        f, t_ = g["_id"].get("f"), g["_id"].get("t")
        if not _staff_pair_allowed(staff, {"from_code": f, "to_code": t_}):
            continue
        pair_counts.append({
            "pair": f"{f}->{t_}" if t_ else "legacy",
            "label": f"{f}→{t_}" if t_ else None,
            "count": g["n"],
        })
    pair_counts.sort(key=lambda x: -x["count"])
    if pair and pair != "all":
        if pair == "legacy":
            q["to_code"] = None
        elif "->" in pair:
            f, t_ = pair.split("->", 1)
            q["from_code"], q["to_code"] = f, t_
    items = await db.vip_batch_items.find(q, {"_id": 0}).sort("created_at", 1).limit(min(max(1, limit), 500)).to_list(500)
    items = [it for it in items if _staff_pair_allowed(staff, it)]
    lookup_ids = ({it["vip_user_id"] for it in items}
                  | {it["reviewed_by"] for it in items if it.get("reviewed_by")})
    users_by_id: dict[str, dict] = {}
    if lookup_ids:
        async for u in db.users.find({"user_id": {"$in": list(lookup_ids)}},
                                      {"_id": 0, "user_id": 1, "name": 1, "email": 1}):
            users_by_id[u["user_id"]] = u
    for it in items:
        it["pair"] = (f"{it.get('from_code')}→{it.get('to_code')}"
                      if it.get("to_code") else None)
        vip = users_by_id.get(it["vip_user_id"], {})
        it["vip_name"] = vip.get("name", "")
        it["vip_email"] = vip.get("email", "")
        reviewer = users_by_id.get(it.get("reviewed_by") or "", {})
        it["reviewed_by_name"] = reviewer.get("name") or reviewer.get("email") or None
    return {"items": [_serialize(it) for it in items], "count": len(items),
            "pair_counts": pair_counts}


async def _apply_item_decision(item_id: str, decision: str, staff: dict,
                                admin_note: str = "") -> dict:
    item = await db.vip_batch_items.find_one({"id": item_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Ítem no encontrado.")
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail="El ítem ya fue procesado.")
    if not _staff_pair_allowed(staff, item):
        pair_lbl = (f"{item.get('from_code')}→{item.get('to_code')}"
                    if item.get("to_code") else item.get("currency", ""))
        raise HTTPException(
            status_code=403,
            detail=f"No estás autorizado a trabajar el par de lotes {pair_lbl}. Contacta al admin.",
        )

    now = iso(now_utc())
    balance_delta = None
    extra: dict = {}
    if decision == "approved":
        rates = await build_rate_lookup()
        if item.get("to_code"):
            # iter113 — pair item: credit the VIP's per-currency balance at
            # the snapshotted VIP rate and record the platform margin vs the
            # real rate as revenue.
            amount_to = float(item.get("amount_to") or 0.0)
            rate_applied = float(item.get("rate_applied") or 0.0)
            item_amount = float(item.get("amount") or 0.0)
            if amount_to <= 0 or rate_applied <= 0:
                rate_applied, _ = await _current_pair_rates(
                    item["from_code"], item["to_code"], item_amount)
                if rate_applied <= 0:
                    raise HTTPException(
                        status_code=422,
                        detail=(f"No hay tasa VIP para {item['from_code']}→{item['to_code']}. "
                                "Configúrala antes de aprobar."),
                    )
                amount_to = round(float(item["amount"]) * rate_applied, 4)
            _, real_rate = await _current_pair_rates(
                item["from_code"], item["to_code"], item_amount)
            margin_usdt = 0.0
            if real_rate > 0:
                margin_to = float(item["amount"]) * real_rate - amount_to
                margin_usdt = round(float(convert_to_usdt(margin_to, item["to_code"], rates) or 0.0), 4)
            await db.users.update_one(
                {"user_id": item["vip_user_id"]},
                {"$inc": {f"vip_balances.{item['to_code']}": amount_to}},
            )
            balance_delta = round(float(convert_to_usdt(amount_to, item["to_code"], rates) or 0.0), 4)
            extra = {
                "amount_to": amount_to,
                "rate_applied": rate_applied,
                "real_rate_applied": real_rate or None,
                "margin_usdt": margin_usdt,
                "credited_currency": item["to_code"],
            }
        else:
            # Legacy single-currency item → old USDT ledger behavior.
            delta = convert_to_usdt(item["amount"], item["currency"], rates)
            if delta is None:
                raise HTTPException(
                    status_code=422,
                    detail=(f"No hay tasa configurada para {item['currency']}. "
                            f"Añade una tasa {item['currency']}→USDT antes de aprobar."),
                )
            balance_delta = round(float(delta), 4)
            await _increment_ledger(item["vip_user_id"], item["direction"], balance_delta)

    await db.vip_batch_items.update_one(
        {"id": item_id},
        {"$set": {
            "status": decision,
            "updated_at": now,
            "reviewed_at": now,
            "reviewed_by": staff["user_id"],
            "admin_note": admin_note or None,
            "balance_delta_usdt": balance_delta,
            **extra,
        }},
    )
    await _refresh_batch_totals(item["batch_id"])
    fresh = await db.vip_batch_items.find_one({"id": item_id}, {"_id": 0})
    if decision == "approved":
        # iter148 — massive-inflow threshold alerts on approval
        await dispatch_vip_batch_alerts(item["batch_id"], [fresh], "approved")
    # iter117 — real-time refresh: the VIP dashboard (VipBatchesView) listens
    # for `vip_batch_item_decision`; emit it for BOTH approve and reject.
    try:
        from services.live_bus import publish as live_publish
        await live_publish(
            "vip_batch_item_decision",
            {"item_id": item_id, "batch_id": item["batch_id"], "decision": decision},
            user_id=item["vip_user_id"],
        )
        if decision == "approved" and item.get("to_code"):
            await live_publish(
                "balance_updated",
                {"reason": "vip_batch_item", "item_id": item_id,
                 "currency": item["to_code"]},
                user_id=item["vip_user_id"],
            )
            await live_publish(
                "ledger_changed",
                {"reason": "vip_batch_item", "item_id": item_id,
                 "user_id": item["vip_user_id"]},
                roles=("admin", "employee"),
            )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_batches] SSE publish failed: {e}")
    return fresh


@router.post("/admin/vip-batches/items/{item_id}/approve")
async def admin_approve_vip_item(item_id: str, request: Request) -> Any:
    staff = await require_permission(request, "orders")
    fresh = await _apply_item_decision(item_id, "approved", staff)
    await log_action(
        db=db, actor=staff, action="vip_batch_item.approve",
        entity_type="vip_batch_item", entity_id=item_id,
        details={
            "vip_user_id": fresh["vip_user_id"], "amount": fresh["amount"],
            "currency": fresh["currency"], "direction": fresh["direction"],
            "balance_delta_usdt": fresh["balance_delta_usdt"],
        },
    )
    await _notify_vip_item_decision(fresh, approved=True)
    return _serialize(fresh)


@router.post("/admin/vip-batches/items/{item_id}/reject")
async def admin_reject_vip_item(item_id: str, payload: RejectPayload, request: Request) -> Any:
    staff = await require_permission(request, "orders")
    fresh = await _apply_item_decision(
        item_id, "rejected", staff, admin_note=payload.admin_note.strip(),
    )
    await log_action(
        db=db, actor=staff, action="vip_batch_item.reject",
        entity_type="vip_batch_item", entity_id=item_id,
        details={"vip_user_id": fresh["vip_user_id"], "note": payload.admin_note.strip()},
    )
    await _notify_vip_item_decision(fresh, approved=False, admin_note=payload.admin_note.strip())
    return _serialize(fresh)


@router.get("/admin/vip-balance/{vip_user_id}")
async def admin_get_vip_balance(vip_user_id: str, request: Request) -> Any:
    await require_permission(request, "orders")
    ledger = await _ensure_ledger(vip_user_id)
    return {
        "vip_user_id": vip_user_id,
        "positive_usdt": round(ledger.get("positive_usdt", 0.0), 2),
        "negative_usdt": round(ledger.get("negative_usdt", 0.0), 2),
        "net_usdt": round(
            ledger.get("positive_usdt", 0.0) - ledger.get("negative_usdt", 0.0), 2,
        ),
        "updated_at": ledger.get("updated_at"),
    }
