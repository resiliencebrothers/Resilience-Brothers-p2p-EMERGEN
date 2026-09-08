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
    require_staff, require_permission, require_admin,
    now_utc, iso,
    _enforce_employee_currency_scope, _enforce_totp_step_up,
)
from audit_log import log_action
from services.currency_utils import norm_code as _norm_code
from services.company_funds_common import assert_can_manage_company_funds
from services.fund_accounts import (  # noqa: F401 — re-export compat
    CASH_BOX_NAME,
    HAS_ACC as _HAS_ACC,
    account_assigned_balances as _account_assigned_balances,
    auto_paid_from_account,
    get_or_create_cash_box,
    resolve_fund_account,
)

router = APIRouter(tags=["Admin"])


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
            "min_balance_alert": pa.get("min_balance_alert"),
            "low_balance_alerted_at": pa.get("low_balance_alerted_at", ""),
        })
    async for fa in db.fund_accounts.find({"currency": code}, {"_id": 0}):
        seen.add(fa["id"])
        row = {
            "id": fa["id"], "label": fa.get("name") or fa["id"],
            "source": "custom", "method": fa.get("method") or "other",
            "is_active": bool(fa.get("is_active", True)),
            "balance": round(assigned.get(fa["id"], 0.0), 4),
            "min_balance_alert": fa.get("min_balance_alert"),
            "low_balance_alerted_at": fa.get("low_balance_alerted_at", ""),
        }
        # iter235 — último desglose de billetes de las cuentas de efectivo.
        if row["method"] == "cash":
            row["denoms_snapshot"] = await db.fund_account_denoms.find_one(
                {"account_id": fa["id"]}, {"_id": 0},
                sort=[("created_at", -1)])
        accounts.append(row)
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


class MinBalancePayload(BaseModel):
    min_balance: Optional[float] = Field(None, ge=0, le=1_000_000_000)


class DenomsSnapshotPayload(BaseModel):
    denominations: Dict[str, int]
    note: str = Field(default="", max_length=200)


@router.get("/admin/company-funds/accounts/{account_id}/denominations")
async def list_account_denoms(account_id: str, request: Request) -> Any:
    """iter235 — historial de desgloses de billetes de una cuenta de efectivo."""
    actor = await require_permission(request, "company_funds")
    acc = await resolve_fund_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    _enforce_employee_currency_scope(actor, acc["currency"])
    return await db.fund_account_denoms.find(
        {"account_id": account_id}, {"_id": 0}) \
        .sort("created_at", -1).to_list(20)


@router.post("/admin/company-funds/accounts/{account_id}/denominations")
async def save_account_denoms(account_id: str, payload: DenomsSnapshotPayload,
                              request: Request) -> Any:
    """iter235 — registra en qué billetes está repartido el efectivo de la
    cuenta (ej. Fondo Resilience): guarda el conteo por denominación y la
    diferencia contra el balance del sistema (cuadrada/sobrante/faltante)."""
    from routes.admin_company_funds import CASH_DENOMINATIONS

    actor = await require_permission(request, "company_funds")
    acc = await resolve_fund_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    code = acc["currency"]
    _enforce_employee_currency_scope(actor, code)
    if acc.get("method") != "cash":
        raise HTTPException(
            status_code=400,
            detail="El desglose de billetes solo aplica a cuentas de efectivo")
    valid = CASH_DENOMINATIONS.get(code)
    if not valid:
        raise HTTPException(
            status_code=400,
            detail=f"No hay denominaciones definidas para {code}")
    clean: Dict[str, int] = {}
    total = 0.0
    for k, v in payload.denominations.items():
        try:
            denom, qty = int(float(k)), int(v)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Desglose inválido")
        if denom not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"Denominación {denom} no válida para {code}")
        if qty < 0:
            raise HTTPException(status_code=400,
                                detail="Las cantidades no pueden ser negativas")
        if qty:
            clean[str(denom)] = qty
            total += denom * qty
    total = round(total, 2)
    assigned = await _account_assigned_balances(code)
    system = round(float(assigned.get(account_id, 0.0)), 2)
    diff = round(total - system, 2)
    doc = {
        "id": f"fdnm_{uuid.uuid4().hex[:12]}",
        "account_id": account_id,
        "account_label": acc["label"],
        "currency": code,
        "denominations": clean,
        "total": total,
        "system_balance": system,
        "difference": diff,
        "status": "cuadrada" if diff == 0 else ("sobrante" if diff > 0 else "faltante"),
        "note": payload.note.strip(),
        "created_at": iso(now_utc()),
        "created_by_id": actor["user_id"],
        "created_by_name": actor.get("name") or actor.get("email") or "",
    }
    await db.fund_account_denoms.insert_one({**doc})
    await log_action(
        db, actor, "company_funds.denoms_snapshot", "fund_account", account_id,
        summary=(f"Desglose de billetes {acc['label']} ({code}): "
                 f"{total:g} contado vs {system:g} sistema → {doc['status']}"),
        details={"denominations": clean, "difference": diff})
    if diff != 0:
        await _notify_denoms_mismatch(doc, actor)
    return doc


async def _notify_denoms_mismatch(snap: dict, actor: dict) -> None:
    """iter236 — Alerta Descuadre Caja: push + email + campana a los admins
    cuando un desglose guardado no cuadra contra el balance del sistema."""
    import logging
    logger = logging.getLogger(__name__)
    code = snap["currency"]
    signo = "sobran" if snap["difference"] > 0 else "faltan"
    title = f"Descuadre de caja: {snap['account_label']}"
    body = (f"El conteo de billetes de «{snap['account_label']}» ({code}) "
            f"registrado por {snap['created_by_name']} no cuadra: contado "
            f"{snap['total']:,.2f} vs sistema {snap['system_balance']:,.2f} — "
            f"{signo} {abs(snap['difference']):,.2f} {code}."
            + (f" Nota: {snap['note']}" if snap.get("note") else ""))
    try:
        from admin_alerts import notify_all_admins
        await notify_all_admins(db, title=title, body=body,
                                url_path="/admin/company-funds")
    except Exception as e:  # noqa: BLE001
        logger.error(f"denoms mismatch push/email failed: {e}")
    try:
        from routes.notifications import _insert_notification
        admins = await db.users.find({"role": "admin"},
                                     {"_id": 0, "user_id": 1}).to_list(50)
        for a in admins:
            await _insert_notification(
                recipient_user_id=a["user_id"], type="cash_count_mismatch",
                title=title, message=body,
                data={"account_id": snap["account_id"], "currency": code,
                      "difference": snap["difference"],
                      "snapshot_id": snap["id"]})
    except Exception as e:  # noqa: BLE001
        logger.error(f"denoms mismatch in-app notify failed: {e}")


@router.put("/admin/company-funds/accounts/{account_id}/min-balance")
async def set_account_min_balance(account_id: str, payload: MinBalancePayload,
                                  request: Request) -> Any:
    """iter224 — umbral de alerta de saldo bajo por cuenta (solo admin).
    min_balance vacío o 0 desactiva la alerta."""
    actor = await require_admin(request)
    target = None
    for coll in ("payment_accounts", "fund_accounts"):
        doc = await db[coll].find_one({"id": account_id}, {"_id": 0})
        if doc:
            target = coll
            break
    if not target:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    if payload.min_balance and payload.min_balance > 0:
        await db[target].update_one(
            {"id": account_id},
            {"$set": {"min_balance_alert": round(float(payload.min_balance), 2)},
             "$unset": {"low_balance_alerted_at": ""}})
    else:
        await db[target].update_one(
            {"id": account_id},
            {"$unset": {"min_balance_alert": "", "low_balance_alerted_at": ""}})
    await log_action(
        db, actor, "fund_account.min_balance", "fund_account", account_id,
        summary=f"Mínimo de alerta: {payload.min_balance if payload.min_balance else 'desactivado'}")
    from services.fund_alerts import check_low_fund_balances
    await check_low_fund_balances()
    updated = await db[target].find_one({"id": account_id}, {"_id": 0})
    return {"id": account_id,
            "min_balance_alert": updated.get("min_balance_alert"),
            "low_balance_alerted_at": updated.get("low_balance_alerted_at", "")}


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
