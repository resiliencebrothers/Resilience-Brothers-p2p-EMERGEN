"""iter110 · Phases 2 + 3 — Capital deposits & settlements on the VIP ledger.

Extends the ledger built in Phase 1 (see `vip_batches.py`) with two new
operator flows:

  Phase 2 — Capital deposits ("envío de capital"):
    The VIP wires their own funds to the company *before* starting the day
    to pre-fund their `positive_usdt`. Optional proof_url (unlike batch
    items — capital transfers usually come with a receipt attached).
    Admin confirms → `positive_usdt += converted_to_usdt`.

  Phase 3 — Settlements ("cobros y pagos"):
    Two directions clear the ledger:
      - payout    : we pay the VIP against their positive_usdt.
      - collection: the VIP pays us against their negative_usdt.
    Two sources:
      - VIP-initiated (status starts pending, requires admin approve)
      - Admin-registered unilateral (status starts confirmed, ledger applied on POST)

Collections:
  vip_capital_deposits
    { id, vip_user_id, vip_email, vip_name,
      currency, amount, proof_url?, note?,
      status: pending|confirmed|rejected,
      created_at, updated_at, reviewed_at, reviewed_by,
      admin_note?, balance_delta_usdt? }

  vip_settlements
    { id, vip_user_id, vip_email, vip_name,
      direction: payout|collection,
      currency, amount, amount_usdt,
      settlement_method, note?,
      requested_by: vip|admin,
      status: pending|confirmed|rejected,
      created_at, updated_at, reviewed_at, reviewed_by,
      admin_note? }
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone, timedelta
from io import BytesIO
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import require_user, require_permission, iso, now_utc
from audit_log import log_action
from services.balances import build_rate_lookup, convert_to_usdt
from services.vip_ledger_reporting import (
    parse_date_or_400 as _parse_date_or_400,
    default_range as _default_range,
    collect_ledger_movements as _collect_ledger_movements,
    DEFAULT_RANGE_DAYS,  # noqa: F401  (kept for backwards compat)
)
from services.vip_batch_ops import (
    ensure_ledger as _ensure_ledger,
    serialize_doc as _serialize,
)
from vip_ledger_pdf import generate_vip_ledger_pdf
from email_service import notify_vip_ledger_statement, VipLedgerEmailContext

logger = logging.getLogger("vip_ledger_ops")

router = APIRouter(tags=["VIP Ledger Ops"])

ALLOWED_METHODS = {"bank_transfer", "crypto", "cash", "zelle", "other"}


# ============================================================
# Payloads
# ============================================================

class CapitalDepositCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    currency: str = Field(..., min_length=1, max_length=16)
    amount: float = Field(..., gt=0, le=10_000_000)
    # iter112 — deposit method is mandatory; transfers require proof + holder;
    # crypto additionally requires the tx hash.
    deposit_method: str = Field(..., min_length=2, max_length=32)
    account_holder: Optional[str] = Field(default=None, max_length=120)
    tx_hash: Optional[str] = Field(default=None, max_length=200)
    proof_image: Optional[str] = None  # base64 data URL — uploaded to storage
    proof_url: Optional[str] = Field(default=None, max_length=500)
    note: Optional[str] = Field(default=None, max_length=200)


class SettlementCreate(BaseModel):
    """VIP-initiated payout request or admin-registered movement."""
    model_config = ConfigDict(extra="ignore")
    direction: str = Field(..., pattern="^(payout|collection)$")
    currency: str = Field(..., min_length=1, max_length=16)
    amount: float = Field(..., gt=0, le=10_000_000)
    settlement_method: str = Field(..., min_length=2, max_length=32)
    note: Optional[str] = Field(default=None, max_length=300)


class RejectPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    admin_note: str = Field(default="", max_length=300)


class ConfirmPayload(BaseModel):
    """iter112b — `force=True` overrides the duplicate-tx-hash guard."""
    model_config = ConfigDict(extra="ignore")
    force: bool = False


# ============================================================
# Helpers
# ============================================================

def _require_vip(user: dict) -> None:
    if user.get("role") != "vip":
        raise HTTPException(
            status_code=403,
            detail="Solo los clientes VIP pueden usar esta operativa.",
        )


async def _amount_to_usdt(amount: float, currency: str) -> float:
    rates = await build_rate_lookup()
    val = convert_to_usdt(float(amount), currency.upper(), rates)
    if val is None:
        raise HTTPException(
            status_code=422,
            detail=f"No hay tasa configurada para {currency}. Añade una tasa {currency}→USDT.",
        )
    return round(float(val), 4)


async def _notify_staff(kind: str, doc: dict, currency: str, amount: float,
                        perm: str = "orders") -> None:
    try:
        from routes.notifications import _insert_notification
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_ledger_ops] notif import failed: {e}")
        return
    titles = {
        "capital_deposit": ("Nuevo depósito de capital VIP",
                            f"{doc.get('vip_name') or doc.get('vip_email')} envió {amount} {currency}"),
        "settlement_request": ("Nueva solicitud de cobro VIP",
                                f"{doc.get('vip_name') or doc.get('vip_email')} pide {amount} {currency}"),
    }[kind]
    cursor = db.users.find(
        {"$or": [
            {"role": "admin"},
            {"role": "employee", "allowed_permissions": perm},
            {"role": "employee", "allowed_permissions": {"$in": [[], None]}},
        ]},
        {"_id": 0, "user_id": 1},
    )
    async for r in cursor:
        try:
            await _insert_notification(
                recipient_user_id=r["user_id"],
                type=kind, title=titles[0], message=titles[1],
                data={"id": doc["id"], "vip_user_id": doc["vip_user_id"]},
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[vip_ledger_ops] staff notify failed: {e}")


async def _notify_vip(kind: str, doc: dict, approved: bool, admin_note: str = "") -> None:
    try:
        from routes.notifications import _insert_notification
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_ledger_ops] notif import failed: {e}")
        return
    action = "confirmado" if approved else "rechazado"
    labels = {
        "capital_deposit": f"Depósito de capital {action}",
        "settlement": f"Cobro/pago {action}",
    }
    try:
        await _insert_notification(
            recipient_user_id=doc["vip_user_id"],
            type=f"{kind}_decision",
            title=labels[kind],
            message=admin_note or f"Tu operación de {doc.get('amount', 0)} {doc.get('currency', '')} fue {action}.",
            data={"id": doc["id"]},
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_ledger_ops] vip notify failed: {e}")
    # iter197 — email mirror so the decision reaches the VIP even when they
    # aren't logged in. Best-effort: an email outage never breaks the flow.
    try:
        target = await db.users.find_one(
            {"user_id": doc["vip_user_id"]},
            {"_id": 0, "email": 1, "name": 1, "preferred_language": 1},
        )
        if target and target.get("email"):
            from email_service import (notify_capital_deposit_decision,
                                       notify_settlement_decision)
            if kind == "capital_deposit":
                notify_capital_deposit_decision(doc, target, approved, admin_note)
            else:
                notify_settlement_decision(doc, target, approved, admin_note)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[vip_ledger_ops] vip email failed: {e}")


# ============================================================
# Phase 2 — Capital deposits
# ============================================================

_METHOD_LABELS = {
    "bank_transfer": "transferencia bancaria",
    "crypto": "cripto (USDT)",
    "zelle": "Zelle",
    "other": "otro método",
}


@router.post("/vip/capital-deposits")
async def create_capital_deposit(payload: CapitalDepositCreate, request: Request) -> Any:
    # iter166 — capital deposits were unified with regular client deposits
    # (owner decision): VIPs now use POST /api/deposits. Existing records
    # stay readable for history/statements.
    user = await require_user(request)
    _require_vip(user)
    raise HTTPException(
        status_code=410,
        detail=("Los depósitos de capital se unificaron con los depósitos "
                "normales. Usa la sección Depositar de tu panel."),
    )


@router.get("/vip/capital-deposits")
async def list_own_capital_deposits(request: Request, limit: int = 50) -> Any:
    user = await require_user(request)
    _require_vip(user)
    cursor = db.vip_capital_deposits.find(
        {"vip_user_id": user["user_id"]}, {"_id": 0},
    ).sort("created_at", -1).limit(min(max(1, limit), 200))
    return {"items": [_serialize(d) async for d in cursor]}


@router.get("/admin/vip-capital-deposits")
async def admin_list_capital_deposits(request: Request, status: Optional[str] = None,
                                        limit: int = 200) -> Any:
    # iter163 — capital deposits moved to the `withdrawals` gate (unified
    # Deposits & Withdrawals section).
    await require_permission(request, "withdrawals")
    q: dict[str, Any] = {}
    if status in ("pending", "confirmed", "rejected"):
        q["status"] = status
    cursor = db.vip_capital_deposits.find(q, {"_id": 0}).sort("created_at", -1).limit(min(max(1, limit), 500))
    items = [_serialize(d) async for d in cursor]
    # iter112b — flag rows whose tx_hash appears in 2+ non-rejected deposits
    # so staff spots a reused receipt before opening the confirm flow.
    hashes = [i["tx_hash"] for i in items if i.get("tx_hash")]
    dup_set: set = set()
    if hashes:
        rows = await db.vip_capital_deposits.aggregate([
            {"$match": {"tx_hash": {"$in": hashes}, "status": {"$ne": "rejected"}}},
            {"$group": {"_id": "$tx_hash", "n": {"$sum": 1}}},
            {"$match": {"n": {"$gte": 2}}},
        ]).to_list(1000)
        dup_set = {r["_id"] for r in rows}
    for i in items:
        i["duplicate_hash"] = bool(i.get("tx_hash")) and i["tx_hash"] in dup_set
    pending = await db.vip_capital_deposits.count_documents({"status": "pending"})
    return {"items": items, "pending": pending}


async def _find_hash_duplicates(tx_hash: str, exclude_id: str) -> list[dict]:
    """Other non-rejected deposits sharing the same tx hash."""
    return await db.vip_capital_deposits.find(
        {"tx_hash": tx_hash, "id": {"$ne": exclude_id},
         "status": {"$ne": "rejected"}},
        {"_id": 0, "id": 1, "vip_email": 1, "amount": 1, "currency": 1,
         "status": 1, "created_at": 1},
    ).to_list(10)


@router.post("/admin/vip-capital-deposits/{dep_id}/confirm")
async def admin_confirm_capital_deposit(dep_id: str, request: Request,
                                          payload: Optional[ConfirmPayload] = None) -> Any:
    staff = await require_permission(request, "withdrawals")
    doc = await db.vip_capital_deposits.find_one({"id": dep_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Depósito no encontrado.")
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail="Este depósito ya fue procesado.")
    force = bool(payload and payload.force)
    duplicates: list[dict] = []
    if doc.get("tx_hash"):
        duplicates = await _find_hash_duplicates(doc["tx_hash"], dep_id)
        if duplicates and not force:
            raise HTTPException(status_code=409, detail={
                "code": "DUPLICATE_TX_HASH",
                "message": ("Este hash ya fue usado en otro depósito no rechazado. "
                            "Verifica que no sea un comprobante repetido antes de confirmar."),
                "duplicates": duplicates,
            })
    delta = await _amount_to_usdt(doc["amount"], doc["currency"])
    # iter113 — capital deposits credit the VIP's per-currency USDT balance.
    # iter257(D02) — claim ATÓMICO pendiente→confirmado con la intención del
    # abono (marker) en el MISMO update: dos confirmaciones simultáneas no
    # pueden abonar dos veces, y un crash tras el claim lo completa
    # heal_pending_credits (la colección está en PENDING_COLLECTIONS).
    from services.credit_recovery import pending_marker, apply_and_clear
    marker = pending_marker(doc["vip_user_id"], "USDT", delta,
                            "capital-deposit")
    now = iso(now_utc())
    claim = await db.vip_capital_deposits.update_one(
        {"id": dep_id, "status": "pending"},
        {"$set": {
            "status": "confirmed", "updated_at": now,
            "reviewed_at": now, "reviewed_by": staff["user_id"],
            "balance_delta_usdt": delta,
            "credit_pending": marker,
        }},
    )
    if claim.matched_count == 0:
        raise HTTPException(status_code=409, detail="Este depósito ya fue procesado.")
    await apply_and_clear("vip_capital_deposits", dep_id, marker)
    from services.live_events import emit_balance_changed
    await emit_balance_changed(doc["vip_user_id"], "capital_deposit_confirmed",
                               deposit_id=dep_id)
    fresh = await db.vip_capital_deposits.find_one({"id": dep_id}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="vip_capital.confirm",
        entity_type="vip_capital_deposit", entity_id=dep_id,
        details={"vip_user_id": doc["vip_user_id"], "delta_usdt": delta,
                 "forced_duplicate_hash": bool(duplicates and force)},
    )
    await _notify_vip("capital_deposit", fresh, approved=True)
    return _serialize(fresh)


@router.post("/admin/vip-capital-deposits/{dep_id}/reject")
async def admin_reject_capital_deposit(dep_id: str, payload: RejectPayload, request: Request) -> Any:
    staff = await require_permission(request, "withdrawals")
    doc = await db.vip_capital_deposits.find_one({"id": dep_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Depósito no encontrado.")
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail="Este depósito ya fue procesado.")
    now = iso(now_utc())
    # iter260(E03) — claim ATÓMICO pendiente→rechazado: si una confirmación
    # concurrente ganó (y acreditó), este rechazo pierde y devuelve 409 en
    # vez de sobrescribir el estado confirmado.
    claim = await db.vip_capital_deposits.update_one(
        {"id": dep_id, "status": "pending"},
        {"$set": {
            "status": "rejected", "updated_at": now, "reviewed_at": now,
            "reviewed_by": staff["user_id"],
            "admin_note": payload.admin_note.strip() or None,
        }},
    )
    if claim.matched_count == 0:
        raise HTTPException(status_code=409, detail="Este depósito ya fue procesado.")
    fresh = await db.vip_capital_deposits.find_one({"id": dep_id}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="vip_capital.reject",
        entity_type="vip_capital_deposit", entity_id=dep_id,
        details={"vip_user_id": doc["vip_user_id"], "note": payload.admin_note.strip()},
    )
    await _notify_vip("capital_deposit", fresh, approved=False, admin_note=payload.admin_note.strip())
    return _serialize(fresh)


# ============================================================
# Phase 3 — Settlements
# ============================================================

def _validate_settlement_method(method: str) -> str:
    m = method.strip().lower()
    if m not in ALLOWED_METHODS:
        raise HTTPException(
            status_code=422,
            detail=f"Método inválido. Usa: {sorted(ALLOWED_METHODS)}",
        )
    return m


async def _apply_settlement_effect(direction: str, vip_user_id: str,
                                   amount_usdt: float, op_id: str) -> str:
    """iter113/iter257(D03) — efecto del settlement IDEMPOTENTE por op_id.
    payout: débito con guard atómico de saldo (helper duradero) — devuelve
    'applied' | 'duplicate' | 'insufficient' (nunca deja saldo negativo).
    collection: baja de la deuda legacy con registro embebido en el ledger."""
    if direction == "payout":
        from services.balances import debit_balance_idempotent
        st = await debit_balance_idempotent(vip_user_id, "USDT",
                                            float(amount_usdt), op_id)
        if st != "insufficient":
            from services.live_events import emit_balance_changed
            await emit_balance_changed(vip_user_id, "settlement_payout",
                                       amount_usdt=float(amount_usdt))
        return st
    await _ensure_ledger(vip_user_id)
    res = await db.vip_ledger.update_one(
        {"vip_user_id": vip_user_id, "applied_ops": {"$ne": op_id}},
        {"$inc": {"negative_usdt": -float(amount_usdt)},
         "$set": {"updated_at": iso(now_utc())},
         "$push": {"applied_ops": op_id}},
    )
    return "applied" if res.matched_count else "duplicate"


@router.post("/vip/settlements")
async def vip_create_settlement(payload: SettlementCreate, request: Request) -> Any:
    """VIP-initiated request. Always starts pending — admin must approve."""
    user = await require_user(request)
    _require_vip(user)
    method = _validate_settlement_method(payload.settlement_method)
    amount_usdt = await _amount_to_usdt(payload.amount, payload.currency)

    # Only allow VIP to request payout of positive balance (not collection).
    # Collection movements are admin-registered when the VIP actually pays.
    if payload.direction != "payout":
        raise HTTPException(
            status_code=422,
            detail="Los clientes solo pueden solicitar cobros ('payout'). El admin registra los pagos entrantes.",
        )

    now = iso(now_utc())
    doc = {
        "id": f"vset_{uuid.uuid4().hex[:12]}",
        "vip_user_id": user["user_id"],
        "vip_email": user.get("email", ""),
        "vip_name": user.get("name", ""),
        "direction": payload.direction,
        "currency": payload.currency.strip().upper(),
        "amount": round(float(payload.amount), 2),
        "amount_usdt": amount_usdt,
        "settlement_method": method,
        "note": (payload.note or "").strip() or None,
        "requested_by": "vip",
        "status": "pending",
        "admin_note": None,
        "created_at": now,
        "updated_at": now,
        "reviewed_at": None,
        "reviewed_by": None,
    }
    await db.vip_settlements.insert_one(dict(doc))
    await log_action(
        db=db, actor=user, action="vip_settlement.create",
        entity_type="vip_settlement", entity_id=doc["id"],
        details={"amount": doc["amount"], "currency": doc["currency"], "usdt": amount_usdt},
    )
    await _notify_staff("settlement_request", doc, doc["currency"], doc["amount"])
    return _serialize(doc)


@router.get("/vip/settlements")
async def list_own_settlements(request: Request, limit: int = 50) -> Any:
    user = await require_user(request)
    _require_vip(user)
    cursor = db.vip_settlements.find(
        {"vip_user_id": user["user_id"]}, {"_id": 0},
    ).sort("created_at", -1).limit(min(max(1, limit), 200))
    return {"items": [_serialize(d) async for d in cursor]}


@router.get("/admin/vip-settlements")
async def admin_list_settlements(request: Request, status: Optional[str] = None,
                                   limit: int = 200) -> Any:
    await require_permission(request, "orders")
    q: dict[str, Any] = {}
    if status in ("pending", "confirmed", "rejected"):
        q["status"] = status
    cursor = db.vip_settlements.find(q, {"_id": 0}).sort("created_at", -1).limit(min(max(1, limit), 500))
    items = [_serialize(d) async for d in cursor]
    pending = await db.vip_settlements.count_documents({"status": "pending"})
    return {"items": items, "pending": pending}


class AdminSettlementCreate(SettlementCreate):
    """Admin-registered unilateral movement (both directions allowed)."""
    vip_user_id: str = Field(..., min_length=3)


@router.post("/admin/vip-settlements")
async def admin_create_settlement(payload: AdminSettlementCreate, request: Request) -> Any:
    """Register a paid-out or collected settlement unilaterally.
    Ledger applied *immediately* — no separate approve step."""
    staff = await require_permission(request, "orders")
    method = _validate_settlement_method(payload.settlement_method)
    target = await db.users.find_one({"user_id": payload.vip_user_id}, {"_id": 0, "role": 1, "email": 1, "name": 1})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if target.get("role") != "vip":
        raise HTTPException(status_code=422, detail="El usuario objetivo no es VIP.")
    amount_usdt = await _amount_to_usdt(payload.amount, payload.currency)

    # iter257(D03) — primero el DOCUMENTO (con el plan del efecto), después el
    # dinero (idempotente por op_id): un crash entre ambos lo completa el
    # healer; sin saldo suficiente no se registra ningún pago válido.
    now = iso(now_utc())
    sid = f"vset_{uuid.uuid4().hex[:12]}"
    op_id = f"settlement:{sid}"
    doc = {
        "id": sid,
        "vip_user_id": payload.vip_user_id,
        "vip_email": target.get("email", ""),
        "vip_name": target.get("name", ""),
        "direction": payload.direction,
        "currency": payload.currency.strip().upper(),
        "amount": round(float(payload.amount), 2),
        "amount_usdt": amount_usdt,
        "settlement_method": method,
        "note": (payload.note or "").strip() or None,
        "requested_by": "admin",
        "status": "confirmed",
        "admin_note": None,
        "created_at": now,
        "updated_at": now,
        "reviewed_at": now,
        "reviewed_by": staff["user_id"],
        "settle_pending": {"op_id": op_id, "direction": payload.direction,
                           "amount_usdt": amount_usdt, "at": now},
    }
    await db.vip_settlements.insert_one(dict(doc))
    st = await _apply_settlement_effect(payload.direction, payload.vip_user_id,
                                        amount_usdt, op_id)
    if st == "insufficient":
        await db.vip_settlements.delete_one({"id": sid})
        raise HTTPException(
            status_code=409,
            detail=(f"El VIP no tiene {amount_usdt} USDT disponibles; "
                    "no se registró el pago."))
    await db.vip_settlements.update_one(
        {"id": sid, "settle_pending.op_id": op_id},
        {"$unset": {"settle_pending": ""}})
    doc.pop("settle_pending", None)
    await log_action(
        db=db, actor=staff, action="vip_settlement.admin_register",
        entity_type="vip_settlement", entity_id=doc["id"],
        details={"direction": doc["direction"], "vip_user_id": doc["vip_user_id"],
                 "amount_usdt": amount_usdt},
    )
    await _notify_vip("settlement", doc, approved=True)
    return _serialize(doc)


@router.post("/admin/vip-settlements/{sid}/approve")
async def admin_approve_settlement(sid: str, request: Request) -> Any:
    staff = await require_permission(request, "orders")
    doc = await db.vip_settlements.find_one({"id": sid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado.")
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail="Este movimiento ya fue procesado.")
    # iter257(D03) — claim ATÓMICO pendiente→confirmado con el plan del efecto
    # en el MISMO update: dos aprobaciones simultáneas no duplican; sin saldo
    # el movimiento vuelve a pendiente; un crash lo completa el healer.
    op_id = f"settlement:{sid}"
    now = iso(now_utc())
    claim = await db.vip_settlements.update_one(
        {"id": sid, "status": "pending"},
        {"$set": {"status": "confirmed", "updated_at": now,
                  "reviewed_at": now, "reviewed_by": staff["user_id"],
                  "settle_pending": {"op_id": op_id,
                                     "direction": doc["direction"],
                                     "amount_usdt": doc["amount_usdt"],
                                     "at": now}}},
    )
    if claim.matched_count == 0:
        raise HTTPException(status_code=409, detail="Este movimiento ya fue procesado.")
    st = await _apply_settlement_effect(doc["direction"], doc["vip_user_id"],
                                        doc["amount_usdt"], op_id)
    if st == "insufficient":
        await db.vip_settlements.update_one(
            {"id": sid, "settle_pending.op_id": op_id},
            {"$set": {"status": "pending", "updated_at": iso(now_utc())},
             "$unset": {"settle_pending": "", "reviewed_at": "",
                        "reviewed_by": ""}})
        raise HTTPException(
            status_code=409,
            detail=(f"El VIP no tiene {doc['amount_usdt']} USDT disponibles; "
                    "el movimiento sigue pendiente."))
    await db.vip_settlements.update_one(
        {"id": sid, "settle_pending.op_id": op_id},
        {"$unset": {"settle_pending": ""}})
    fresh = await db.vip_settlements.find_one({"id": sid}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="vip_settlement.approve",
        entity_type="vip_settlement", entity_id=sid,
        details={"amount_usdt": doc["amount_usdt"], "direction": doc["direction"]},
    )
    await _notify_vip("settlement", fresh, approved=True)
    return _serialize(fresh)


@router.post("/admin/vip-settlements/{sid}/reject")
async def admin_reject_settlement(sid: str, payload: RejectPayload, request: Request) -> Any:
    staff = await require_permission(request, "orders")
    doc = await db.vip_settlements.find_one({"id": sid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado.")
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail="Este movimiento ya fue procesado.")
    now = iso(now_utc())
    # iter260(E03) — claim atómico: un approve concurrente que ya confirmó
    # (y aplicó el efecto) no puede ser pisado por este rechazo.
    claim = await db.vip_settlements.update_one(
        {"id": sid, "status": "pending"},
        {"$set": {"status": "rejected", "updated_at": now,
                  "reviewed_at": now, "reviewed_by": staff["user_id"],
                  "admin_note": payload.admin_note.strip() or None}},
    )
    if claim.matched_count == 0:
        raise HTTPException(status_code=409, detail="Este movimiento ya fue procesado.")
    fresh = await db.vip_settlements.find_one({"id": sid}, {"_id": 0})
    await log_action(
        db=db, actor=staff, action="vip_settlement.reject",
        entity_type="vip_settlement", entity_id=sid,
        details={"note": payload.admin_note.strip()},
    )
    await _notify_vip("settlement", fresh, approved=False, admin_note=payload.admin_note.strip())
    return _serialize(fresh)


# ============================================================
# iter111 — PDF export of the VIP ledger statement
# ============================================================
# Ledger-movement helpers now live in services/vip_ledger_reporting.py so
# both this router and scheduler.py can consume them without a circular
# dependency. See the `services.vip_ledger_reporting` import above.


async def _fetch_vip_profile(vip_user_id: str) -> dict:
    doc = await db.users.find_one(
        {"user_id": vip_user_id},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="VIP no encontrado.")
    if doc.get("role") != "vip":
        raise HTTPException(status_code=422, detail="El usuario objetivo no es VIP.")
    return doc


async def _build_and_stream_pdf(vip: dict, actor: dict,
                                 from_date: Optional[str], to_date: Optional[str]) -> StreamingResponse:
    from_dt = _parse_date_or_400(from_date, "from_date")
    to_dt = _parse_date_or_400(to_date, "to_date")
    initial_pos, initial_neg, movements = await _collect_ledger_movements(
        vip["user_id"], from_dt, to_dt,
    )
    pdf_bytes = generate_vip_ledger_pdf(
        vip={"user_id": vip["user_id"], "name": vip.get("name", ""),
             "email": vip.get("email", "")},
        since=(from_date or ""),
        until=(to_date or ""),
        initial_positive=initial_pos,
        initial_negative=initial_neg,
        movements=movements,
        actor=actor,
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    slug = (vip.get("email") or vip["user_id"]).split("@")[0].replace(" ", "_")
    filename = f"vip_ledger_{slug}_{ts}.pdf"
    await log_action(
        db=db, actor=actor, action="vip_ledger.export_pdf",
        entity_type="vip_ledger", entity_id=vip["user_id"],
        details={"since": from_date or "", "until": to_date or "",
                 "movements": len(movements)},
    )
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/vip/ledger/export.pdf")
async def export_own_ledger_pdf(request: Request,
                                 from_date: Optional[str] = None,
                                 to_date: Optional[str] = None) -> Any:
    """VIP downloads their own ledger statement PDF.

    Default range: last 90 days when both `from_date` and `to_date` are
    omitted.
    """
    user = await require_user(request)
    _require_vip(user)
    from_date, to_date = _default_range(from_date, to_date)
    vip = {"user_id": user["user_id"], "name": user.get("name", ""),
           "email": user.get("email", "")}
    return await _build_and_stream_pdf(vip, user, from_date, to_date)


@router.get("/admin/vip-ledger/{vip_user_id}/export.pdf")
async def admin_export_ledger_pdf(vip_user_id: str, request: Request,
                                    from_date: Optional[str] = None,
                                    to_date: Optional[str] = None) -> Any:
    """Admin/staff (with `orders` permission) downloads any VIP's ledger PDF.

    Default range: last 90 days when both `from_date` and `to_date` are
    omitted.
    """
    staff = await require_permission(request, "orders")
    vip = await _fetch_vip_profile(vip_user_id)
    from_date, to_date = _default_range(from_date, to_date)
    return await _build_and_stream_pdf(vip, staff, from_date, to_date)

# ============================================================
# iter111.2 — Email PDF export
# ============================================================
import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LedgerEmailPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=600)
    from_date: Optional[str] = None
    to_date: Optional[str] = None


async def _send_ledger_email(vip: dict, actor: dict, payload: LedgerEmailPayload,
                              fallback_to: str) -> dict:
    """Resolve recipient, build the PDF and enqueue Resend send."""
    to = (payload.to or fallback_to or "").strip().lower()
    if not to or not _EMAIL_RE.match(to):
        raise HTTPException(status_code=422, detail="Correo destinatario inválido.")
    from_date, to_date = _default_range(payload.from_date, payload.to_date)
    from_dt = _parse_date_or_400(from_date, "from_date")
    to_dt = _parse_date_or_400(to_date, "to_date")
    initial_pos, initial_neg, movements = await _collect_ledger_movements(
        vip["user_id"], from_dt, to_dt,
    )
    pdf_bytes = generate_vip_ledger_pdf(
        vip={"user_id": vip["user_id"], "name": vip.get("name", ""),
             "email": vip.get("email", "")},
        since=from_date, until=to_date,
        initial_positive=initial_pos, initial_negative=initial_neg,
        movements=movements, actor=actor,
    )
    ok = notify_vip_ledger_statement(VipLedgerEmailContext(
        to=to,
        vip_name=vip.get("name") or vip.get("email", ""),
        since=from_date, until=to_date,
        movements_count=len(movements),
        pdf_bytes=pdf_bytes,
        issuer_name=actor.get("name") or actor.get("email", ""),
        personal_note=payload.note or "",
        lang=(actor.get("preferred_language") or "es"),
    ))
    if not ok:
        # RESEND_API_KEY missing or provider error — surface a soft failure
        raise HTTPException(
            status_code=502,
            detail="No se pudo enviar el correo. Verifica la configuración de Resend o reintenta.",
        )
    await log_action(
        db=db, actor=actor, action="vip_ledger.email_pdf",
        entity_type="vip_ledger", entity_id=vip["user_id"],
        details={"to": to, "since": from_date, "until": to_date,
                 "movements": len(movements)},
    )
    return {"ok": True, "to": to, "movements": len(movements),
            "since": from_date, "until": to_date}


async def _enforce_email_rate_limit(key: str, max_calls: int,
                                     window_seconds: int = 3600) -> None:
    """SEC hardening (auditoría 28/7/2026) — Mongo-backed sliding-window rate
    limit for the ledger-email endpoints. Self-contained so it works despite
    this module's `from __future__ import annotations` (which breaks slowapi's
    body-param introspection). Prevents authenticated mail-relay abuse."""
    now = now_utc()
    cutoff = now - timedelta(seconds=window_seconds)
    await db.ledger_email_events.insert_one({"key": key, "at": now})
    recent = await db.ledger_email_events.count_documents(
        {"key": key, "at": {"$gte": cutoff}},
    )
    if recent > max_calls:
        raise HTTPException(
            status_code=429,
            detail=("Has alcanzado el límite de envíos por correo. "
                    "Intenta de nuevo más tarde."),
        )


@router.post("/vip/ledger/email")
async def email_own_ledger_pdf(payload: LedgerEmailPayload, request: Request) -> Any:
    """VIP sends own ledger PDF to any email address.

    SEC hardening (auditoría 28/7/2026): rate-limited to 10/hour per client to
    prevent using the endpoint as an authenticated mail relay for spam.
    Default recipient: the VIP's own email. Default range: last 90 days.
    """
    user = await require_user(request)
    _require_vip(user)
    await _enforce_email_rate_limit(f"vip:{user['user_id']}", max_calls=10)
    vip = {"user_id": user["user_id"], "name": user.get("name", ""),
           "email": user.get("email", "")}
    return await _send_ledger_email(vip, user, payload,
                                     fallback_to=user.get("email", ""))


@router.post("/admin/vip-ledger/{vip_user_id}/email")
async def admin_email_ledger_pdf(vip_user_id: str, payload: LedgerEmailPayload,
                                    request: Request) -> Any:
    """Admin/staff (with `orders` permission) sends any VIP's ledger PDF.

    SEC hardening (auditoría 28/7/2026): rate-limited to 60/hour to cap relay
    abuse while leaving generous headroom for legitimate operator bulk sends.
    Default recipient: the VIP's own email. Default range: last 90 days.
    """
    staff = await require_permission(request, "orders")
    await _enforce_email_rate_limit(f"staff:{staff['user_id']}", max_calls=60)
    vip = await _fetch_vip_profile(vip_user_id)
    return await _send_ledger_email(vip, staff, payload,
                                     fallback_to=vip.get("email", ""))


# ============================================================
# iter111.3 — Monthly automatic mailing controls
# ============================================================

class MonthlyLedgerPrefPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.get("/vip/ledger/monthly-preference")
async def get_monthly_ledger_preference(request: Request) -> Any:
    """VIP reads its own monthly-mailing opt-in state."""
    user = await require_user(request)
    _require_vip(user)
    # Default = True (opted in) unless the field is explicitly False.
    enabled = user.get("monthly_ledger_email_enabled")
    return {"enabled": (enabled is not False)}


@router.put("/vip/ledger/monthly-preference")
async def set_monthly_ledger_preference(payload: MonthlyLedgerPrefPayload,
                                          request: Request) -> Any:
    """VIP toggles its own monthly-mailing opt-in state."""
    user = await require_user(request)
    _require_vip(user)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"monthly_ledger_email_enabled": bool(payload.enabled)}},
    )
    await log_action(
        db=db, actor=user, action="vip_ledger.monthly_pref",
        entity_type="user", entity_id=user["user_id"],
        details={"enabled": bool(payload.enabled)},
    )
    return {"ok": True, "enabled": bool(payload.enabled)}


@router.post("/admin/vip-ledger/monthly-mailing/run-now")
async def admin_run_monthly_mailing_now(request: Request) -> Any:
    """Manually trigger the same monthly VIP ledger mailing that runs on
    day 1 09:30 UTC. Reserved for admin (permission: `orders`) — useful for
    smoke tests, one-off resends, and disaster recovery."""
    actor = await require_permission(request, "orders")
    from scheduler import run_monthly_vip_ledger_email
    result = await run_monthly_vip_ledger_email(db)
    await log_action(
        db=db, actor=actor, action="vip_ledger.monthly_run_now",
        entity_type="scheduler", entity_id="monthly_vip_ledger_email",
        details=result or {},
    )
    return {"ok": True, **(result or {})}

