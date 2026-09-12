"""iter263/265/269 — Espejo automático: operaciones de efectivo → Caja de Efectivo.

El fondo de empresa contable y la Caja de Efectivo física deben contar la
misma historia. Este servicio replica cada operación contable que mueve
efectivo físico CUP/USD en la caja de empresa «Fondo Resilience» (identidad
de sistema `company_cash`, H03):
  - ajustes manuales de capital en efectivo (iter263),
  - retiros de EMPRESA pagados desde la cuenta de caja (H01),
  - retiros de CLIENTES pagados desde la cuenta de caja (V02),
  - transferencias internas que entran/salen de la cuenta de caja (H01).
Todo con id determinista por documento origen ($setOnInsert nunca duplica) y
backfill del histórico. La cuenta contable de caja también se identifica por
`system_purpose`, no por su nombre editable (V03). Un fallo al crear la caja
se PROPAGA: nunca se marca un origen como replicado sin caja persistida (V05).
"""
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import iso, now_utc
from services.currency_utils import norm_code

logger = logging.getLogger(__name__)

COMPANY_BOX_NAME = "Fondo Resilience"
SYSTEM_PURPOSE = "company_cash"
NOT_APPLICABLE = "na"  # marcador definitivo: la operación no toca la caja

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
    (inmutable), no el nombre visible. V05: solo se devuelve una caja cuya
    persistencia esté comprobada; cualquier otro fallo se propaga para que la
    operación quede pendiente y el backfill la reintente."""
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
        except DuplicateKeyError:
            pass  # otro estampador ganó: se relee por identidad abajo
        stamped = await db.cash_boxes.find_one(key, {"_id": 0})
        if stamped:
            return stamped
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
    except DuplicateKeyError:
        pass  # colisión de unicidad recuperable: otro creador ganó
    # V05 — exigir el registro persistido; si no existe, PROPAGAR el fallo
    box = await db.cash_boxes.find_one(key, {"_id": 0})
    if not box:
        raise RuntimeError(
            "La caja de empresa no pudo persistirse; la operación queda "
            "pendiente y se reintentará")
    return box


async def _bump_fund_rev(box_id: str, fund: str) -> None:
    """V04 — revisión del fondo: cualquier mutación de movimientos invalida
    el arqueo de cierre vigente."""
    await db.cash_boxes.update_one(
        {"id": box_id}, {"$inc": {f"fund_revs.{fund}": 1}})


async def _upsert_mirror_movement(mov_id: str, doc: Dict[str, Any],
                                  source_coll: Any, source_id: str) -> str:
    """Inserta el movimiento espejo (idempotente) y marca el doc origen.
    N05 — la invalidación del arqueo (revisión del fondo) se persiste en el
    propio movimiento (`rev_bumped`): si el incremento falla, el reintento lo
    completa ANTES de declarar el origen sincronizado — nunca queda un cierre
    vigente sustentado en un saldo que ya cambió."""
    await db.cash_box_movements.update_one(
        {"id": mov_id}, {"$setOnInsert": {**doc, "rev_bumped": False}},
        upsert=True)
    mov = await db.cash_box_movements.find_one(
        {"id": mov_id}, {"_id": 0, "box_id": 1, "fund": 1, "rev_bumped": 1})
    if mov and not mov.get("rev_bumped"):
        await _bump_fund_rev(str(mov.get("box_id") or ""),
                             str(mov.get("fund") or ""))
        await db.cash_box_movements.update_one(
            {"id": mov_id}, {"$set": {"rev_bumped": True}})
    await source_coll.update_one(
        {"id": source_id}, {"$set": {"cash_box_movement_id": mov_id}})
    return mov_id


# --------------------------------------------------------------------------
# Identidad de la CUENTA contable de caja (V03): por propósito, no por nombre
# --------------------------------------------------------------------------

async def _is_company_cash_account(acc: Dict[str, Any]) -> bool:
    """¿La cuenta es la cuenta de caja del sistema? Estampa el propósito en
    cuentas legadas identificadas por la convención de nombre."""
    if acc.get("system_purpose") == SYSTEM_PURPOSE:
        return True
    if acc.get("method") == "cash" and acc.get("name") == COMPANY_BOX_NAME:
        await db.fund_accounts.update_one(
            {"id": acc.get("id"), "system_purpose": {"$exists": False}},
            {"$set": {"system_purpose": SYSTEM_PURPOSE}})
        return True
    return False


async def _company_cash_account(currency: object) -> Optional[Dict[str, Any]]:
    """Cuenta contable de caja de esa moneda, por IDENTIDAD persistente.
    Nota (decisión de negocio abierta): otras cuentas de efectivo NO mapean a
    la caja automática — cada una podría ser una caja física distinta."""
    code = norm_code(currency)
    if not code:
        return None
    acc = await db.fund_accounts.find_one(
        {"system_purpose": SYSTEM_PURPOSE, "currency": code}, {"_id": 0})
    if acc:
        return acc
    legacy = await db.fund_accounts.find_one(
        {"name": COMPANY_BOX_NAME, "method": "cash", "currency": code},
        {"_id": 0})
    if legacy and await _is_company_cash_account(legacy):
        return legacy
    return None


async def _paid_from_is_cash_box(src: Dict[str, Any]) -> bool:
    """¿El documento se pagó desde la cuenta de caja? Resuelve por ID (estable
    ante renombres) y comprueba la identidad."""
    acc_id = str(src.get("paid_from_account_id") or "")
    if not acc_id:
        return False
    acc = await db.fund_accounts.find_one({"id": acc_id}, {"_id": 0})
    return bool(acc) and await _is_company_cash_account(acc)


# --------------------------------------------------------------------------
# Espejos por tipo de operación
# --------------------------------------------------------------------------

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


async def mirror_company_withdrawal_to_cash_box(
        cw: Dict[str, Any]) -> Optional[str]:
    """H01 — retiro de empresa PAGADO desde la cuenta de caja → salida física."""
    if (cw.get("status") or "") != "paid":
        return None
    fund = fund_for_currency(cw.get("currency"))
    cwid = str(cw.get("id") or "")
    if not fund or not cwid or not await _paid_from_is_cash_box(cw):
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


async def mirror_client_withdrawal_to_cash_box(
        w: Dict[str, Any]) -> Optional[str]:
    """V02 — retiro de CLIENTE pagado desde la cuenta de caja → salida física
    (misma magnitud que descuenta la contabilidad: `amount_usd` en la moneda
    del retiro). El momento efectivo es `paid_at`."""
    if (w.get("status") or "") != "paid":
        return None
    fund = fund_for_currency(w.get("currency"))
    wid = str(w.get("id") or "")
    if not fund or not wid or not await _paid_from_is_cash_box(w):
        return None
    box = await get_or_create_company_cash_box()
    mov_id = f"cmov_wd_{wid.replace('-', '')[:20]}"
    who = w.get("user_name") or w.get("user_email") or w.get("user_id") or ""
    doc: Dict[str, Any] = {
        "id": mov_id,
        "box_id": box["id"],
        "fund": fund,
        "type": "salida",
        "amount": round(float(w.get("amount_usd") or 0), 2),
        "concept": f"Retiro de cliente pagado: {who}".strip()[:200],
        "responsible": str(who)[:80],
        "denominations": None,
        "denoms_pending": True,
        "created_at": w.get("paid_at") or w.get("created_at") or iso(now_utc()),
        "created_by_id": "system",
        "created_by_name": "Sistema (pago a cliente)",
        "source_client_withdrawal_id": wid,
    }
    return await _upsert_mirror_movement(mov_id, doc, db.withdrawals, wid)


async def mirror_fund_transfer_to_cash_box(tr: Dict[str, Any]) -> Optional[str]:
    """H01 — transferencia interna que entra/sale de la cuenta de caja →
    entrada/salida física. No altera el capital total (solo ubicación)."""
    fund = fund_for_currency(tr.get("currency"))
    trid = str(tr.get("id") or "")
    if not fund or not trid:
        return None
    kind = ""
    sides = []
    for field, side_kind in (("from_account_id", "salida"),
                             ("to_account_id", "entrada")):
        acc_id = tr.get(field)
        if not acc_id:
            continue
        acc = await db.fund_accounts.find_one({"id": acc_id}, {"_id": 0})
        if acc and await _is_company_cash_account(acc):
            sides.append(side_kind)
    # N06 — si AMBOS extremos son la misma caja física, es un traslado
    # interno: no hay salida ni entrada neta de billetes, no se refleja.
    if len(sides) == 1:
        kind = sides[0]
    if not kind:
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


# --------------------------------------------------------------------------
# Backfill y reparaciones
# --------------------------------------------------------------------------

_MirrorFn = Callable[[Dict[str, Any]], Awaitable[Optional[str]]]

_SOURCES: tuple = (
    (lambda: db.company_fund_adjustments, {"method": "cash"},
     mirror_adjustment_to_cash_box),
    (lambda: db.company_withdrawals, {"status": "paid"},
     mirror_company_withdrawal_to_cash_box),
    (lambda: db.withdrawals, {"status": "paid"},
     mirror_client_withdrawal_to_cash_box),
    (lambda: db.fund_account_transfers, {}, mirror_fund_transfer_to_cash_box),
)


async def _backfill(coll: Any, query: Dict[str, Any], mirror: _MirrorFn) -> int:
    n = 0
    q = {**query, "cash_box_movement_id": {"$exists": False}}
    async for src in coll.find(q, {"_id": 0}):
        if await mirror(src):
            n += 1
        else:
            # no aplica a la caja física — marcador DEFINITIVO (V03: la
            # identidad por id/propósito hace la decisión estable)
            await coll.update_one({"id": str(src.get("id") or "")},
                                  {"$set": {"cash_box_movement_id": NOT_APPLICABLE}})
    return n


async def _repair_legacy_markers() -> int:
    """V03 — reintenta los docs marcados con cadena vacía por versiones
    anteriores (identidad no resuelta ≠ definitivamente ajena a caja)."""
    n = 0
    for coll_fn, extra_q, mirror in _SOURCES:
        coll = coll_fn()
        async for src in coll.find({**extra_q, "cash_box_movement_id": ""},
                                   {"_id": 0}):
            if await mirror(src):
                n += 1
            else:
                await coll.update_one(
                    {"id": str(src.get("id") or "")},
                    {"$set": {"cash_box_movement_id": NOT_APPLICABLE}})
    return n


async def _repair_orphan_movements() -> int:
    """V05 — re-vincula movimientos espejo cuyo box_id no existe (huérfanos de
    la ventana del bug anterior), sin inventar saldos ni duplicar."""
    linked_q = {"$or": [
        {"source_adjustment_id": {"$exists": True}},
        {"source_withdrawal_id": {"$exists": True}},
        {"source_client_withdrawal_id": {"$exists": True}},
        {"source_transfer_id": {"$exists": True}},
    ]}
    box_ids = await db.cash_box_movements.distinct("box_id", linked_q)
    if not box_ids:
        return 0
    existing = set(await db.cash_boxes.distinct("id", {"id": {"$in": box_ids}}))
    orphan = [b for b in box_ids if b not in existing]
    if not orphan:
        return 0
    box = await get_or_create_company_cash_box()
    res = await db.cash_box_movements.update_many(
        {**linked_q, "box_id": {"$in": orphan}},
        {"$set": {"box_id": box["id"]}})
    for fund in ("CUP", "USD"):
        await _bump_fund_rev(box["id"], fund)
    if res.modified_count:
        logger.warning("[cash-box-sync] %s movimiento(s) huérfanos re-vinculados",
                       res.modified_count)
    return int(res.modified_count)


async def _stamp_cash_accounts() -> None:
    """V03 — migración: estampa la identidad en las cuentas de caja legadas
    (por convención de nombre) antes de que alguien las renombre."""
    async for acc in db.fund_accounts.find(
            {"name": COMPANY_BOX_NAME, "method": "cash",
             "system_purpose": {"$exists": False}}, {"_id": 0}):
        await _is_company_cash_account(acc)


async def backfill_cash_adjustments() -> int:
    """Replica los ajustes en efectivo históricos que aún no están en la caja."""
    return await _backfill(db.company_fund_adjustments, {"method": "cash"},
                           mirror_adjustment_to_cash_box)


async def backfill_cash_operations() -> int:
    """Backfill completo: ajustes + retiros de empresa pagados + retiros de
    clientes pagados + transferencias internas, más reparaciones (identidad
    de cuentas, marcadores legados, huérfanos y duplicados N06). Idempotente."""
    from services.fund_accounts import consolidate_duplicate_cash_accounts
    await consolidate_duplicate_cash_accounts()
    await _stamp_cash_accounts()
    await _repair_orphan_movements()
    n = await _repair_legacy_markers()
    for coll_fn, extra_q, mirror in _SOURCES:
        n += await _backfill(coll_fn(), extra_q, mirror)
    return n
