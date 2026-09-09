"""iter263 — Espejo automático: ajustes de capital en EFECTIVO → Caja de Efectivo.

El fondo de empresa contable (company_fund_adjustments) y la Caja de Efectivo
física (cash_boxes / cash_box_movements) eran módulos independientes: el stock
de billetes registrado en los ajustes manuales no aparecía en la caja. Este
servicio replica cada ajuste en efectivo CUP/CUPE/USD (con su desglose de
billetes) como movimiento de la caja de empresa «Fondo Resilience», de forma
idempotente (id determinista por ajuste) y con backfill para el histórico.
"""
import logging
import uuid
from typing import Any, Dict, Optional

from db_client import db
from auth_utils import iso, now_utc
from services.currency_utils import norm_code

logger = logging.getLogger(__name__)

COMPANY_BOX_NAME = "Fondo Resilience"

# moneda del ajuste → fondo de la caja (billetes físicos)
_FUND_BY_CURRENCY = {"CUP": "CUP", "CUPE": "CUP", "USD": "USD"}


def fund_for_currency(currency: object) -> Optional[str]:
    """Fondo de caja (CUP/USD) para la moneda del ajuste, o None si no aplica."""
    return _FUND_BY_CURRENCY.get(norm_code(currency) or "")


async def get_or_create_company_cash_box() -> Dict[str, Any]:
    """Caja de empresa «Fondo Resilience» — creada (o reactivada) al primer uso."""
    key = {"scope": "empresa", "name": COMPANY_BOX_NAME}
    box = await db.cash_boxes.find_one(key, {"_id": 0})
    if box:
        if not box.get("is_active", True):
            await db.cash_boxes.update_one({"id": box["id"]},
                                           {"$set": {"is_active": True}})
        return box
    doc: Dict[str, Any] = {
        "id": f"cbox_{uuid.uuid4().hex[:12]}",
        "name": COMPANY_BOX_NAME,
        "scope": "empresa",
        "owner_id": "",
        "created_by_id": "system",
        "created_by_name": "Sistema (ajustes de capital)",
        "created_at": iso(now_utc()),
        "is_active": True,
        "initial": {},
    }
    # upsert por clave natural — dos creadores concurrentes convergen en una caja
    await db.cash_boxes.update_one(key, {"$setOnInsert": doc}, upsert=True)
    return (await db.cash_boxes.find_one(key, {"_id": 0})) or doc


async def mirror_adjustment_to_cash_box(adj: Dict[str, Any]) -> Optional[str]:
    """Replica un ajuste manual de capital en efectivo como movimiento de la
    caja de empresa, con su desglose de billetes. Idempotente: el id del
    movimiento es determinista por ajuste ($setOnInsert nunca duplica)."""
    if (adj.get("method") or "") != "cash":
        return None
    fund = fund_for_currency(adj.get("currency"))
    aid = str(adj.get("id") or "")
    if not fund or not aid:
        return None
    box = await get_or_create_company_cash_box()
    kind = "entrada" if adj.get("adjustment_type") == "inflow" else "salida"
    mov_id = f"cmov_adj_{aid.replace('-', '')[:20]}"
    doc: Dict[str, Any] = {
        "id": mov_id,
        "box_id": box["id"],
        "fund": fund,
        "type": kind,
        "amount": round(float(adj.get("amount") or 0), 2),
        "concept": (f"Ajuste de capital ({kind}): "
                    f"{adj.get('source_name') or ''}").strip()[:200],
        "responsible": str(adj.get("source_name") or "")[:80],
        "denominations": adj.get("denominations") or None,
        "created_at": adj.get("created_at") or iso(now_utc()),
        "created_by_id": adj.get("actor_id") or "system",
        "created_by_name": adj.get("actor_name") or adj.get("actor_email") or "Sistema",
        "source_adjustment_id": aid,
    }
    await db.cash_box_movements.update_one(
        {"id": mov_id}, {"$setOnInsert": doc}, upsert=True)
    await db.company_fund_adjustments.update_one(
        {"id": aid}, {"$set": {"cash_box_movement_id": mov_id}})
    return mov_id


async def backfill_cash_adjustments() -> int:
    """Replica los ajustes en efectivo históricos que aún no están en la caja
    (stock existente antes de esta función + sanación si el espejo inline
    falló). Idempotente — seguro en cada arranque y cada ciclo del scheduler."""
    n = 0
    cursor = db.company_fund_adjustments.find(
        {"method": "cash", "cash_box_movement_id": {"$exists": False}},
        {"_id": 0})
    async for adj in cursor:
        mov_id = await mirror_adjustment_to_cash_box(adj)
        if mov_id:
            n += 1
        else:
            # moneda sin billetes CUP/USD — marcar para no re-escanear
            await db.company_fund_adjustments.update_one(
                {"id": str(adj.get("id") or "")},
                {"$set": {"cash_box_movement_id": ""}})
    return n
