"""iter263/265 — Espejo automático: operaciones de efectivo → Caja de Efectivo.

servicio replica cada operación contable que mueve efectivo físico CUP/USD
en la caja de empresa «Fondo Resilience» (identidad de sistema
`company_cash`, H03):
  - ajustes manuales de capital en efectivo (iter263),
  - retiros de empresa PAGADOS desde la cuenta de caja (H01),
  - transferencias internas que entran/salen de la cuenta de caja (H01).
Todo con id determinista por documento origen ($setOnInsert nunca duplica) y
backfill del histórico. Los espejos sin desglose quedan `denoms_pending` para
que el conteo pendiente sea visible, no efectivo inexistente.
"""
import logging
import uuid
from typing import Any, Dict, Optional

from db_client import db
from auth_utils import iso, now_utc
from services.currency_utils import norm_code

logger = logging.getLogger(__name__)

COMPANY_BOX_NAME = "Fondo Resilience"
SYSTEM_PURPOSE = "company_cash"

# moneda del ajuste → fondo de la caja (billetes físicos)
# Regla de negocio (Jun 2026): el efectivo cubano usa UNA sola nomenclatura,
# «CUP» — no existe un código CUPE separado.
_FUND_BY_CURRENCY = {"CUP": "CUP", "USD": "USD"}

_BOX_INDEX_READY = False


def fund_for_currency(currency: object) -> Optional[str]:
    """Fondo de caja (CUP/USD) para la moneda del ajuste, o None si no aplica."""
    return _FUND_BY_CURRENCY.get(norm_code(currency) or "")


async def _ensure_box_identity_index() -> None:
    """H03 — unicidad en DB de la caja automática (una sola identidad)."""
    global _BOX_INDEX_READY
    if _BOX_INDEX_READY:
        return
    try:
        await db.cash_boxes.create_index(
            "system_purpose", unique=True,
            partialFilterExpression={"system_purpose": {"$exists": True}})
        _BOX_INDEX_READY = True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"índice de identidad de caja no disponible: {e}")


async def get_or_create_company_cash_box() -> Dict[str, Any]:
    """Caja de empresa del sistema. H03: la identidad es `system_purpose`
    (inmutable), no el nombre visible — renombrarla no divide el historial."""
    await _ensure_box_identity_index()
    key = {"scope": "empresa", "system_purpose": SYSTEM_PURPOSE}
    box = await db.cash_boxes.find_one(key, {"_id": 0})
    if box:
        if not box.get("is_active", True):
            await db.cash_boxes.update_one({"id": box["id"]},
                                           {"$set": {"is_active": True}})
        return box
    # migración: caja legada creada por nombre → estampar el propósito
    legacy = await db.cash_boxes.find_one(
        {"scope": "empresa", "name": COMPANY_BOX_NAME}, {"_id": 0})
    if legacy:
        try:
            await db.cash_boxes.update_one(
                {"id": legacy["id"], "system_purpose": {"$exists": False}},
                {"$set": {"system_purpose": SYSTEM_PURPOSE, "is_active": True}})
        except Exception:  # noqa: BLE001 — carrera con otro estampador
            pass
        return (await db.cash_boxes.find_one(key, {"_id": 0})) or legacy
    doc: Dict[str, Any] = {
        "id": f"cbox_{uuid.uuid4().hex[:12]}",
        "name": COMPANY_BOX_NAME,
        "scope": "empresa",
        "system_purpose": SYSTEM_PURPOSE,
        "owner_id": "",
        "created_by_id": "system",
        "created_by_name": "Sistema (efectivo de empresa)",
        "created_at": iso(now_utc()),
        "is_active": True,
        "initial": {},
    }
    try:
        await db.cash_boxes.update_one(key, {"$setOnInsert": doc}, upsert=True)
    except Exception:  # noqa: BLE001 — duplicado por carrera: ya existe
        pass
    return (await db.cash_boxes.find_one(key, {"_id": 0})) or doc


async def _upsert_mirror_movement(mov_id: str, doc: Dict[str, Any],
                                  source_coll: Any, source_id: str) -> str:
    """Inserta el movimiento espejo (idempotente) y marca el doc origen."""
    await db.cash_box_movements.update_one(
        {"id": mov_id}, {"$setOnInsert": doc}, upsert=True)
    await source_coll.update_one(
        {"id": source_id}, {"$set": {"cash_box_movement_id": mov_id}})
    return mov_id


async def mirror_adjustment_to_cash_box(adj: Dict[str, Any]) -> Optional[str]:
    """Ajuste manual de capital en efectivo → movimiento de la caja física."""
    if (adj.get("method") or "") != "cash":
        return None
    fund = fund_for_currency(adj.get("currency"))
    aid = str(adj.get("id") or "")
    if not fund or not aid:
        return None
    box = await get_or_create_company_cash_box()
    kind = "entrada" if adj.get("adjustment_type") == "inflow" else "salida"
    mov_id = f"cmov_adj_{aid.replace('-', '')[:20]}"
    denoms = adj.get("denominations") or None
    doc: Dict[str, Any] = {
        "id": mov_id,
        "box_id": box["id"],
        "fund": fund,
        "type": kind,
        "amount": round(float(adj.get("amount") or 0), 2),
        "concept": (f"Ajuste de capital ({kind}): "
                    f"{adj.get('source_name') or ''}").strip()[:200],
        "responsible": str(adj.get("source_name") or "")[:80],
        "denominations": denoms,
        "denoms_pending": denoms is None,
        "created_at": adj.get("created_at") or iso(now_utc()),
        "created_by_id": adj.get("actor_id") or "system",
        "created_by_name": adj.get("actor_name") or adj.get("actor_email") or "Sistema",
        "source_adjustment_id": aid,
    }
    return await _upsert_mirror_movement(
        mov_id, doc, db.company_fund_adjustments, aid)


async def _company_cash_account(currency: object) -> Optional[Dict[str, Any]]:
    """Cuenta contable «Fondo Resilience» (efectivo) de esa moneda, si existe.
    Nota (decisión de negocio abierta): otras cuentas de efectivo NO mapean a
    la caja automática — cada una podría ser una caja física distinta."""
    code = norm_code(currency)
    if not code:
        return None
    return await db.fund_accounts.find_one(
        {"name": COMPANY_BOX_NAME, "method": "cash", "currency": code},
        {"_id": 0, "id": 1, "currency": 1})


async def mirror_company_withdrawal_to_cash_box(
        cw: Dict[str, Any]) -> Optional[str]:
    """H01 — retiro de empresa PAGADO desde la cuenta de caja → salida física."""
    if (cw.get("status") or "") != "paid":
        return None
    fund = fund_for_currency(cw.get("currency"))
    cwid = str(cw.get("id") or "")
    acc_id = str(cw.get("paid_from_account_id") or "")
    if not fund or not cwid or not acc_id:
        return None
    acc = await _company_cash_account(cw.get("currency"))
    if not acc or acc["id"] != acc_id:
        return None
    box = await get_or_create_company_cash_box()
    mov_id = f"cmov_cw_{cwid.replace('-', '')[:20]}"
    concept = (f"Retiro de empresa pagado: {cw.get('beneficiary') or ''}"
               + (f" — {cw['concept']}" if cw.get("concept") else ""))
    doc: Dict[str, Any] = {
        "id": mov_id,
        "box_id": box["id"],
        "fund": fund,
        "type": "salida",
        "amount": round(float(cw.get("amount") or 0), 2),
        "concept": concept.strip()[:200],
        "responsible": str(cw.get("beneficiary") or "")[:80],
        "denominations": None,
        "denoms_pending": True,
        "created_at": cw.get("paid_at") or cw.get("created_at") or iso(now_utc()),
        "created_by_id": cw.get("authorized_by_id") or "system",
        "created_by_name": cw.get("authorized_by_name") or "Sistema",
        "source_withdrawal_id": cwid,
    }
    return await _upsert_mirror_movement(
        mov_id, doc, db.company_withdrawals, cwid)


async def mirror_fund_transfer_to_cash_box(tr: Dict[str, Any]) -> Optional[str]:
    """H01 — transferencia interna que entra/sale de la cuenta de caja →
    entrada/salida física. No altera el capital total (solo ubicación)."""
    fund = fund_for_currency(tr.get("currency"))
    trid = str(tr.get("id") or "")
    if not fund or not trid:
        return None
    acc = await _company_cash_account(tr.get("currency"))
    if not acc:
        return None
    if tr.get("from_account_id") == acc["id"]:
        kind = "salida"
    elif tr.get("to_account_id") == acc["id"]:
        kind = "entrada"
    else:
        return None
    box = await get_or_create_company_cash_box()
    mov_id = f"cmov_tr_{trid.replace('-', '')[:20]}"
    doc: Dict[str, Any] = {
        "id": mov_id,
        "box_id": box["id"],
        "fund": fund,
        "type": kind,
        "amount": round(float(tr.get("amount") or 0), 2),
        "concept": (f"Transferencia interna: "
                    f"{tr.get('from_label') or 'Sin asignar'} → "
                    f"{tr.get('to_label') or 'Sin asignar'}")[:200],
        "responsible": str(tr.get("actor_name") or "")[:80],
        "denominations": None,
        "denoms_pending": True,
        "created_at": tr.get("created_at") or iso(now_utc()),
        "created_by_id": tr.get("actor_id") or "system",
        "created_by_name": tr.get("actor_name") or "Sistema",
        "source_transfer_id": trid,
    }
    return await _upsert_mirror_movement(
        mov_id, doc, db.fund_account_transfers, trid)


async def _backfill(coll: Any, query: Dict[str, Any], mirror: Any) -> int:
    n = 0
    query = {**query, "cash_box_movement_id": {"$exists": False}}
    async for src in coll.find(query, {"_id": 0}):
        if await mirror(src):
            n += 1
        else:
            # no aplica a la caja física — marcar para no re-escanear
            await coll.update_one({"id": str(src.get("id") or "")},
                                  {"$set": {"cash_box_movement_id": ""}})
    return n


async def backfill_cash_adjustments() -> int:
    """Replica los ajustes en efectivo históricos que aún no están en la caja."""
    return await _backfill(db.company_fund_adjustments, {"method": "cash"},
                           mirror_adjustment_to_cash_box)


async def backfill_cash_operations() -> int:
    """Backfill completo: ajustes + retiros pagados + transferencias internas.
    Idempotente — seguro en cada arranque y cada ciclo del scheduler."""
    n = await backfill_cash_adjustments()
    n += await _backfill(db.company_withdrawals, {"status": "paid"},
                         mirror_company_withdrawal_to_cash_box)
    n += await _backfill(db.fund_account_transfers, {},
                         mirror_fund_transfer_to_cash_box)
    return n
