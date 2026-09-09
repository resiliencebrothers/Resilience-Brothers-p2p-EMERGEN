"""Helpers de permisos compartidos entre los módulos de fondos de la empresa
(`routes/admin_company_funds.py` y `routes/company_fund_accounts.py`).

Extraído a services/ para eliminar los imports cruzados entre ambos routers
(hallazgo del code review — acoplamiento circular vía lazy imports).
"""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from db_client import db
from auth_utils import now_utc, iso


async def record_auto_fund_adjustment(*, adjustment_type: str, currency: str,
                                      amount: float, source_name: str,
                                      note: str = "", ref_id: str = "",
                                      dedupe_key: str = "") -> dict:
    """iter219 — movimiento AUTOMÁTICO de capital (ventas del marketplace,
    comisiones de vendedores VIP). Usa el mismo esquema que los ajustes
    manuales para que `_aggregate_manual_adjustments` lo refleje directo en
    el fondo de la empresa.
    iter257(D08) — `dedupe_key` (índice único sparse) hace el asiento
    IDEMPOTENTE: reintentos y healers pueden re-ejecutar sin duplicar."""
    global _ADJ_DEDUPE_INDEX_READY
    doc = {
        "id": str(uuid.uuid4()),
        "adjustment_type": adjustment_type,
        "currency": currency,
        "amount": round(float(amount), 2),
        "method": "transfer",
        "source_name": source_name,
        "source_account": "",
        "note": note,
        "account_id": "",
        "account_label": "",
        "denominations": None,
        "actor_id": "system",
        "actor_email": "sistema",
        "actor_name": "Sistema (automático)",
        "source": "marketplace_auto",
        "ref_id": ref_id,
        "created_at": iso(now_utc()),
    }
    if dedupe_key:
        if not _ADJ_DEDUPE_INDEX_READY:
            await db.company_fund_adjustments.create_index(
                "dedupe_key", unique=True, sparse=True)
            _ADJ_DEDUPE_INDEX_READY = True
        doc["dedupe_key"] = dedupe_key
        try:
            await db.company_fund_adjustments.insert_one({**doc})
        except Exception:
            existing = await db.company_fund_adjustments.find_one(
                {"dedupe_key": dedupe_key}, {"_id": 0})
            if existing:
                return existing
            raise
        return doc
    await db.company_fund_adjustments.insert_one({**doc})
    return doc


_ADJ_DEDUPE_INDEX_READY = False


async def assert_can_manage_company_funds(actor: dict) -> None:
    """iter54 — Admin siempre; empleados necesitan can_manage_company_funds=True
    O (iter55.16) el permiso `company_funds` en allowed_permissions."""
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


def actor_currency_scope(actor: Dict[str, Any]) -> Optional[List[str]]:
    """Restricción `allowed_currencies` del empleado (None = sin restricción)."""
    if actor.get("role") != "employee":
        return None
    return actor.get("allowed_currencies") or None
