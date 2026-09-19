"""iter277 — Estado canónico de billetes por cuenta de efectivo.

Billetes actuales = último desglose CONTADO de la cuenta (base) ± los
movimientos con desglose posteriores al conteo:
  * ajustes manuales en efectivo (entradas suman, salidas restan),
  * transferencias entre cuentas con desglose (origen resta, destino suma),
  * retiros de empresa pagados en efectivo con desglose (restan).
La caja canónica absorbe además los ajustes históricos sin cuenta atribuida.
Un movimiento de efectivo SIN desglose no altera los billetes: la diferencia
contra el balance del sistema queda visible hasta el próximo conteo.
"""
from typing import Any, Dict, Optional

from fastapi import HTTPException

from db_client import db

_HAS_DENOMS: Dict[str, Any] = {"$nin": [None, {}]}


def _apply(counts: Dict[int, int], denoms: Optional[dict], sign: int) -> None:
    for k, v in (denoms or {}).items():
        try:
            d, q = int(float(k)), int(v)
        except (TypeError, ValueError):
            continue
        counts[d] = counts.get(d, 0) + sign * q


async def current_account_denoms(acc: dict) -> Dict[str, Any]:
    """Estado actual {denominations, total, counted_at} de una cuenta cash."""
    acc_id = acc["id"]
    snap = await db.fund_account_denoms.find_one(
        {"account_id": acc_id}, {"_id": 0}, sort=[("created_at", -1)])
    counts: Dict[int, int] = {}
    since = ""
    if snap:
        _apply(counts, snap.get("denominations"), 1)
        since = str(snap.get("created_at") or "")

    is_canonical = bool(acc.get("system_purpose"))
    acc_match: Any = acc_id if not is_canonical else {"$in": [acc_id, "", None]}
    q: Dict[str, Any] = {"method": "cash", "account_id": acc_match,
                         "denominations": _HAS_DENOMS}
    if is_canonical:
        q["currency"] = acc.get("currency")
    if since:
        q["created_at"] = {"$gt": since}
    async for a in db.company_fund_adjustments.find(
            q, {"_id": 0, "adjustment_type": 1, "denominations": 1}):
        _apply(counts, a.get("denominations"),
               1 if a.get("adjustment_type") == "inflow" else -1)

    q2: Dict[str, Any] = {"status": {"$nin": ["pending", "aborted"]},
                          "denominations": _HAS_DENOMS,
                          "$or": [{"from_account_id": acc_id},
                                  {"to_account_id": acc_id}]}
    if since:
        # S05 — el corte es el momento EFECTIVO del traslado (confirmed_at):
        # una transferencia iniciada antes de un conteo pero confirmada
        # después SÍ mueve billetes posteriores al conteo. Las históricas sin
        # ese dato conservan el corte por created_at.
        q2["$and"] = [{"$or": [
            {"confirmed_at": {"$gt": since}},
            {"confirmed_at": {"$exists": False},
             "created_at": {"$gt": since}},
        ]}]
    async for tr in db.fund_account_transfers.find(
            q2, {"_id": 0, "from_account_id": 1, "to_account_id": 1,
                 "denominations": 1}):
        if tr.get("from_account_id") == acc_id:
            _apply(counts, tr.get("denominations"), -1)
        if tr.get("to_account_id") == acc_id:
            _apply(counts, tr.get("denominations"), 1)

    q3: Dict[str, Any] = {"status": "paid", "paid_from_account_id": acc_id,
                          "denominations": _HAS_DENOMS}
    if since:
        q3["paid_at"] = {"$gt": since}
    async for w in db.company_withdrawals.find(
            q3, {"_id": 0, "denominations": 1}):
        _apply(counts, w.get("denominations"), -1)

    # S03 — los retiros de CLIENTES pagados desde la cuenta también sacan
    # billetes: su desglose llega al pagarse o al completarse desde la Caja
    # de Efectivo (que lo propaga al documento del retiro).
    q4: Dict[str, Any] = {"status": "paid", "paid_from_account_id": acc_id,
                          "denominations": _HAS_DENOMS}
    if since:
        q4["paid_at"] = {"$gt": since}
    async for w in db.withdrawals.find(q4, {"_id": 0, "denominations": 1}):
        _apply(counts, w.get("denominations"), -1)

    denominations = {str(d): n for d, n in
                     sorted(counts.items(), reverse=True) if n != 0}
    total = round(sum(d * n for d, n in counts.items()), 2)
    return {"denominations": denominations, "total": total,
            "counted_at": since}


async def assert_bills_available(account_id: str, requested: Dict[str, int],
                                 label: str, op_label: str) -> None:
    """S04 — una salida detallada debe estar cubierta por los billetes
    CONOCIDOS de la cuenta: nunca se presenta una composición negativa como
    válida. Con inventario totalmente vacío (histórico sin detallar) no hay
    composición que exigir: queda como conciliación pendiente visible."""
    acc = await db.fund_accounts.find_one({"id": account_id}, {"_id": 0})
    if not acc:
        return
    cur = await current_account_denoms(acc)
    inv = {int(float(k)): int(v) for k, v in cur["denominations"].items()}
    if not inv:
        return
    missing = []
    for k, q in (requested or {}).items():
        try:
            d, need = int(float(k)), int(q)
        except (TypeError, ValueError):
            continue
        have = inv.get(d, 0)
        if need > have:
            missing.append(f"{need}×{d} (hay {max(have, 0)})")
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(f"La cuenta «{label}» no tiene esos billetes para "
                    f"{op_label}: {', '.join(missing)}. Registra primero el "
                    "cambio físico de billetes o un nuevo conteo."))


async def cash_denoms_by_currency() -> Dict[str, Dict[int, int]]:
    """Suma del estado actual de TODAS las cuentas de efectivo por moneda
    (los alias fusionados no cuentan: su historial vive en la canónica)."""
    out: Dict[str, Dict[int, int]] = {}
    async for fa in db.fund_accounts.find(
            {"method": "cash", "merged_into": {"$exists": False}},
            {"_id": 0}):
        code = fa.get("currency") or ""
        if not code:
            continue
        cur = await current_account_denoms(fa)
        bucket = out.setdefault(code, {})
        for k, v in cur["denominations"].items():
            bucket[int(k)] = bucket.get(int(k), 0) + int(v)
    return out
