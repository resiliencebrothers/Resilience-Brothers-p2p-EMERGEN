"""Primitivas del protocolo de markers `credit_pending` (patrón outbox).

Extraído de credit_recovery.py para romper el ciclo de imports
balances ⇄ credit_recovery: este módulo NO importa balances a nivel de
módulo (solo lazy dentro de apply_and_clear), así el grafo de imports
queda acíclico: balances → credit_markers y credit_recovery → credit_markers.
"""
import uuid
from datetime import datetime, timezone

from db_client import db


def pending_marker(user_id: str, code: str, amount: float, reason: str,
                   legacy_usd: bool = False, prepared: bool = True) -> dict:
    """Intención de abono que viaja dentro del claim atómico del doc origen.
    `prepared=False` (iter254/R04): el importe aún no es definitivo — el healer
    NO debe acreditarlo tal cual; debe completar el cálculo primero."""
    return {
        "op_id": f"{reason}:{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "code": code,
        "amount": round(float(amount), 8),
        "legacy_usd": bool(legacy_usd),
        "prepared": bool(prepared),
        "at": datetime.now(timezone.utc).isoformat(),
    }


async def apply_and_clear(coll_name: str, doc_id: str, marker: dict,
                          key_field: str = "id") -> bool:
    """Abona (idempotente por op_id) y limpia el marker del doc origen."""
    from services.balances import credit_balance_idempotent
    ok = await credit_balance_idempotent(
        marker["user_id"], marker["code"], float(marker["amount"]),
        marker["op_id"], legacy_usd=bool(marker.get("legacy_usd")))
    await db[coll_name].update_one(
        {key_field: doc_id, "credit_pending.op_id": marker["op_id"]},
        {"$unset": {"credit_pending": ""}},
    )
    return ok
