"""Helpers compartidos de cuentas de fondos (extraídos de
routes/company_fund_accounts.py para romper el ciclo de imports con
routes/admin_company_funds.py y routes/admin_withdrawals.py).
"""
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import iso, now_utc
from services.currency_utils import norm_code as _norm_code

logger = logging.getLogger(__name__)

HAS_ACC = {"$nin": [None, ""]}

# iter195 — company cash box. All physical cash (CUP / USD efectivo) enters
# and leaves this box automatically, per operator instruction.
CASH_BOX_NAME = "Fondo Resilience"

_CASH_ACC_INDEX_READY = False


async def consolidate_duplicate_cash_accounts() -> int:
    """N06 — funde cuentas automáticas duplicadas (mismo propósito y moneda)
    en la más antigua, re-apuntando TODOS sus vínculos históricos: ningún
    movimiento se pierde y un traslado entre duplicados queda neto en cero."""
    merged = 0
    currencies = await db.fund_accounts.distinct(
        "currency", {"system_purpose": "company_cash"})
    for code in currencies:
        rows = await db.fund_accounts.find(
            {"currency": code, "system_purpose": "company_cash"},
            {"_id": 0}).sort("created_at", 1).to_list(50)
        if len(rows) <= 1:
            continue
        canonical, dups = rows[0], rows[1:]
        for dup in dups:
            for coll, field in (
                    (db.company_fund_adjustments, "account_id"),
                    (db.fund_account_transfers, "from_account_id"),
                    (db.fund_account_transfers, "to_account_id"),
                    (db.withdrawals, "paid_from_account_id"),
                    (db.company_withdrawals, "paid_from_account_id"),
                    (db.fund_account_denoms, "account_id")):
                await coll.update_many({field: dup["id"]},
                                       {"$set": {field: canonical["id"]}})
            await db.fund_accounts.update_one(
                {"id": dup["id"]},
                {"$set": {"is_active": False,
                          "merged_into": canonical["id"]},
                 "$unset": {"system_purpose": ""}})
            merged += 1
            logger.warning(
                "[fund-accounts] cuenta de caja duplicada %s (%s) "
                "consolidada en %s", dup["id"], code, canonical["id"])
    return merged


async def _ensure_cash_account_identity() -> None:
    """N06 — unicidad en DB de la cuenta automática (propósito + moneda),
    consolidando antes los duplicados históricos si existieran."""
    global _CASH_ACC_INDEX_READY
    if _CASH_ACC_INDEX_READY:
        return
    try:
        await consolidate_duplicate_cash_accounts()
        await db.fund_accounts.create_index(
            [("system_purpose", 1), ("currency", 1)], unique=True,
            partialFilterExpression={"system_purpose": {"$exists": True}})
        _CASH_ACC_INDEX_READY = True
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"índice de identidad de cuenta de caja no disponible: {e}")


async def get_or_create_cash_box(currency: str) -> dict:
    """Return {id, label} of the company cash box for `currency`, creating
    (or reactivating) it lazily on first use. V03 — la identidad es
    `system_purpose` (persistente), no el nombre editable. N06 — la creación
    es un upsert por identidad bajo índice único: dos primeras solicitudes
    concurrentes devuelven la MISMA cuenta, nunca dos."""
    code = _norm_code(currency)
    await _ensure_cash_account_identity()
    key = {"currency": code, "system_purpose": "company_cash"}
    fa = await db.fund_accounts.find_one(key, {"_id": 0})
    if not fa:
        legacy = await db.fund_accounts.find_one(
            {"currency": code, "name": CASH_BOX_NAME,
             "merged_into": {"$exists": False}}, {"_id": 0})
        if legacy:
            # migración: estampa la identidad en la cuenta legada por nombre
            try:
                await db.fund_accounts.update_one(
                    {"id": legacy["id"], "system_purpose": {"$exists": False}},
                    {"$set": {"system_purpose": "company_cash"}})
            except DuplicateKeyError:
                pass  # otro estampador ganó: se relee por identidad abajo
            fa = await db.fund_accounts.find_one(key, {"_id": 0})
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
        "system_purpose": "company_cash",
        "note": "Caja de efectivo de la empresa (auto-creada)",
        "is_active": True,
        "created_at": iso(now_utc()),
        "created_by_id": "system",
        "created_by_name": "Sistema",
    }
    try:
        await db.fund_accounts.update_one(key, {"$setOnInsert": doc},
                                          upsert=True)
    except DuplicateKeyError:
        pass  # colisión de unicidad recuperable: otro creador ganó
    fa = await db.fund_accounts.find_one(key, {"_id": 0})
    if not fa:
        raise RuntimeError(
            "La cuenta de caja no pudo persistirse; la operación queda "
            "pendiente y se reintentará")
    return {"id": fa["id"], "label": fa.get("name") or fa["id"]}


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
    # M03 — un alias fusionado remite SIEMPRE a su identidad canónica: nunca
    # vuelve a operar ni a recibir atribuciones por su id antiguo.
    hops = 0
    while fa and fa.get("merged_into") and hops < 3:
        nxt = await db.fund_accounts.find_one(
            {"id": fa["merged_into"]}, {"_id": 0})
        if not nxt:
            break
        fa, hops = nxt, hops + 1
    if fa:
        return {
            "id": fa["id"], "label": fa.get("name") or fa["id"],
            "source": "custom", "method": fa.get("method") or "other",
            "currency": _norm_code(fa.get("currency")),
            "is_active": bool(fa.get("is_active", True)),
        }
    return None


async def resolve_payout_account(account_id: str, currency: str) -> dict:
    """N03 — cuenta de ORIGEN de un pago: debe existir, estar ACTIVA y
    coincidir en MONEDA con la operación. Nunca se convierte entre monedas
    ni se atribuye una salida a una cuenta de otra divisa."""
    acc = await resolve_fund_account(account_id)
    if not acc:
        raise HTTPException(status_code=400,
                            detail="Cuenta de origen no encontrada")
    if not acc.get("is_active", True):
        raise HTTPException(
            status_code=400,
            detail=f"La cuenta «{acc['label']}» está desactivada")
    code = _norm_code(currency)
    if acc.get("currency") and code and acc["currency"] != code:
        raise HTTPException(
            status_code=400,
            detail=(f"La cuenta «{acc['label']}» es de {acc['currency']}, "
                    f"no de {code}"))
    return acc


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
        {"currency": code, "status": {"$nin": ["pending", "aborted"]}},
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
