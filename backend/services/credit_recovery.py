"""iter249 — Acreditaciones EXACTAMENTE-UNA-VEZ con recuperación ante fallos.

Problema reportado: algunas acreditaciones marcaban el documento como
"procesado" ANTES de sumar el dinero; si la base de datos fallaba entre ambos
pasos, el saldo quedaba sin acreditar y el reintento se bloqueaba (el flag ya
estaba consumido). MongoDB corre standalone (sin transacciones multi-doc), así
que se usa el patrón outbox de documento único:

  1. El doc origen reclama la operación (flag) Y registra la intención
     (`credit_pending` = {op_id, user_id, code, amount}) en el MISMO update
     atómico.
  2. El abono usa `credit_balance_idempotent` (el $inc y el registro del op_id
     ocurren en UNA operación sobre el doc del usuario → un reintento nunca
     duplica).
  3. Se limpia el marker.

Si el proceso muere entre pasos, `heal_pending_credits()` (scheduler cada 2
min + arranque) completa la acreditación pendiente: nunca se pierde dinero,
nunca se duplica, y el reintento no queda bloqueado.
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta

from db_client import db
from services.balances import credit_balance_idempotent

logger = logging.getLogger(__name__)

# Colecciones cuyo flujo escribe markers `credit_pending`.
PENDING_COLLECTIONS = ("orders", "deposits", "redemptions", "withdrawals",
                       "deliveries", "capital_requests", "users")


def pending_marker(user_id: str, code: str, amount: float, reason: str,
                   legacy_usd: bool = False) -> dict:
    """Intención de abono que viaja dentro del claim atómico del doc origen."""
    return {
        "op_id": f"{reason}:{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "code": code,
        "amount": round(float(amount), 8),
        "legacy_usd": bool(legacy_usd),
        "at": datetime.now(timezone.utc).isoformat(),
    }


async def apply_and_clear(coll_name: str, doc_id: str, marker: dict,
                          key_field: str = "id") -> bool:
    """Abona (idempotente por op_id) y limpia el marker del doc origen."""
    ok = await credit_balance_idempotent(
        marker["user_id"], marker["code"], float(marker["amount"]),
        marker["op_id"], legacy_usd=bool(marker.get("legacy_usd")))
    await db[coll_name].update_one(
        {key_field: doc_id, "credit_pending.op_id": marker["op_id"]},
        {"$unset": {"credit_pending": ""}},
    )
    return ok


async def heal_pending_credits(max_age_seconds: int = 90) -> int:
    """Completa acreditaciones que quedaron a medias (crash entre el claim y
    el abono). Solo toca markers con antigüedad > max_age_seconds para no
    pisar peticiones en vuelo. Idempotente: el op_id evita duplicados."""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=max_age_seconds)).isoformat()
    healed = 0
    for name in PENDING_COLLECTIONS:
        key = "user_id" if name == "users" else "id"
        rows = await db[name].find(
            {"credit_pending.at": {"$lt": cutoff}},
            {"_id": 0, key: 1, "credit_pending": 1},
        ).to_list(200)
        for row in rows:
            cp = row.get("credit_pending") or {}
            if not cp.get("op_id") or not cp.get("user_id"):
                await db[name].update_one({key: row[key]},
                                          {"$unset": {"credit_pending": ""}})
                continue
            applied = await apply_and_clear(name, row[key], cp, key_field=key)
            healed += 1
            logger.warning(
                "credit_pending sanado: %s/%s op=%s +%s %s → %s (aplicado=%s)",
                name, row[key], cp["op_id"], cp["amount"], cp["code"],
                cp["user_id"], applied)
    return healed
