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
from datetime import timedelta
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


async def _upsert_movement_with_rev(mov_id: str, doc: Dict[str, Any]) -> None:
    """Inserta un movimiento (idempotente) e invalida el arqueo vigente.
    N05 — la invalidación de la revisión se persiste en el propio movimiento
    (`rev_bumped`): si el incremento falla, el reintento lo completa — nunca
    queda un cierre vigente sustentado en un saldo que ya cambió."""
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


async def _upsert_mirror_movement(mov_id: str, doc: Dict[str, Any],
                                  source_coll: Any, source_id: str) -> str:
    """Movimiento espejo + marca del doc origen. El origen solo se declara
    sincronizado DESPUÉS de que el movimiento y su invalidación existan."""
    await _upsert_movement_with_rev(mov_id, doc)
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
        # M03 — un alias fusionado sigue representando la caja física (para
        # espejos históricos) pero NUNCA recupera la identidad automática.
        if not acc.get("merged_into"):
            try:
                await db.fund_accounts.update_one(
                    {"id": acc.get("id"),
                     "system_purpose": {"$exists": False},
                     "merged_into": {"$exists": False}},
                    {"$set": {"system_purpose": SYSTEM_PURPOSE}})
            except DuplicateKeyError:
                pass  # otra cuenta ya posee la identidad de esta moneda
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
    """Ajuste manual de capital en efectivo → movimiento de la caja física.
    S01 — la Caja de Efectivo representa la CUENTA CANÓNICA: un ajuste
    atribuido a OTRA cuenta de efectivo no entra aquí (el traslado posterior
    hacia la canónica ya genera su propia entrada física); sin atribución
    (histórico) la canónica lo absorbe, como el inventario por cuenta."""
    if (adj.get("method") or "") != "cash":
        return None
    fund = fund_for_currency(adj.get("currency"))
    aid = str(adj.get("id") or "")
    if not fund or not aid:
        return None
    acc_id = str(adj.get("account_id") or "")
    if acc_id:
        acc = await db.fund_accounts.find_one({"id": acc_id}, {"_id": 0})
        if not acc or not await _is_company_cash_account(acc):
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
    # S03 — el desglose autorizado en el pago viaja al espejo: una sola
    # fuente de verdad, sin quedar «pendiente» en la Caja.
    cw_denoms = cw.get("denominations") or None
    doc: Dict[str, Any] = {
        "id": mov_id,
        "box_id": box["id"],
        "fund": fund,
        "type": "salida",
        "amount": round(float(cw.get("amount") or 0), 2),
        "concept": concept.strip()[:200],
        "responsible": str(cw.get("beneficiary") or "")[:80],
        "denominations": cw_denoms,
        "denoms_pending": cw_denoms is None,
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
    w_denoms = w.get("denominations") or None
    doc: Dict[str, Any] = {
        "id": mov_id,
        "box_id": box["id"],
        "fund": fund,
        "type": "salida",
        "amount": round(float(w.get("amount_usd") or 0), 2),
        "concept": f"Retiro de cliente pagado: {who}".strip()[:200],
        "responsible": str(who)[:80],
        "denominations": w_denoms,
        "denoms_pending": w_denoms is None,
        "created_at": w.get("paid_at") or w.get("created_at") or iso(now_utc()),
        "created_by_id": "system",
        "created_by_name": "Sistema (pago a cliente)",
        "source_client_withdrawal_id": wid,
    }
    return await _upsert_mirror_movement(mov_id, doc, db.withdrawals, wid)


async def mirror_fund_transfer_to_cash_box(tr: Dict[str, Any]) -> Optional[str]:
    """H01 — transferencia interna que entra/sale de la cuenta de caja →
    entrada/salida física. No altera el capital total (solo ubicación).
    M02 — una transferencia provisional o abortada NUNCA se refleja."""
    if str(tr.get("status") or "") in ("pending", "aborted"):
        return None
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
    tr_denoms = tr.get("denominations") or None
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
        "denominations": tr_denoms,
        "denoms_pending": tr_denoms is None,
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
     mirror_adjustment_to_cash_box, ("account_id",)),
    (lambda: db.company_withdrawals, {"status": "paid"},
     mirror_company_withdrawal_to_cash_box, ("paid_from_account_id",)),
    (lambda: db.withdrawals, {"status": "paid"},
     mirror_client_withdrawal_to_cash_box, ("paid_from_account_id",)),
    # M02 — las transferencias provisionales/abortadas no existen para el
    # recuperador: solo las confirmadas (o históricas sin estado) se reflejan.
    (lambda: db.fund_account_transfers,
     {"status": {"$nin": ["pending", "aborted"]}},
     mirror_fund_transfer_to_cash_box,
     ("from_account_id", "to_account_id")),
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
    for coll_fn, extra_q, mirror, _fields in _SOURCES:
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


async def _reevaluate_na_markers() -> int:
    """R01 (continuación de Q02) — un «na» histórico pudo sobrevivir a una
    consolidación ANTERIOR que re-apuntó el vínculo a la cuenta canónica sin
    retirar el marcador: la contabilidad incluye la operación pero la caja
    no, y ni el recuperador normal (sin marcador) ni el reparador de legados
    (cadena vacía) vuelven a verla. Se reevalúan SOLO los «na» cuyos
    vínculos apuntan HOY a una cuenta de caja canónica, sin depender de que
    aún contengan el id del alias. El espejo es idempotente (ids
    deterministas, $setOnInsert) e invalida el arqueo vigente; un «na»
    legítimo (moneda sin fondo físico, traslado interno) se conserva y las
    abortadas quedan excluidas por estado: jamás se reactivan."""
    cash_ids = await db.fund_accounts.distinct(
        "id", {"system_purpose": SYSTEM_PURPOSE})
    if not cash_ids:
        return 0
    n = 0
    for coll_fn, extra_q, mirror, acc_fields in _SOURCES:
        coll = coll_fn()
        q = {**extra_q, "cash_box_movement_id": NOT_APPLICABLE,
             "$or": [{f: {"$in": cash_ids}} for f in acc_fields]}
        async for src in coll.find(q, {"_id": 0}):
            if await mirror(src):
                n += 1
                logger.warning(
                    "[cash-box-sync] marcador «na» residual reevaluado: la "
                    "operación %s sí corresponde a la caja física",
                    src.get("id"))
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
    (por convención de nombre) antes de que alguien las renombre. M03 — una
    cuenta ya fusionada (`merged_into`) queda excluida para siempre: nunca
    recupera la identidad automática ni colisiona con el índice único."""
    async for acc in db.fund_accounts.find(
            {"name": COMPANY_BOX_NAME, "method": "cash",
             "system_purpose": {"$exists": False},
             "merged_into": {"$exists": False}}, {"_id": 0}):
        await _is_company_cash_account(acc)


async def _abort_stale_pending_transfers() -> int:
    """M02 — una transferencia provisional huérfana (su proceso murió antes de
    confirmar o abortar) se aborta de forma trazable: jamás se confirma sola
    ni vuelve a contar para saldos o espejos."""
    cutoff = iso(now_utc() - timedelta(minutes=10))
    res = await db.fund_account_transfers.update_many(
        {"status": "pending", "created_at": {"$lt": cutoff}},
        {"$set": {"status": "aborted",
                  "aborted_reason": "huérfana: proceso interrumpido"}})
    if res.modified_count:
        logger.warning("[cash-box-sync] %s transferencia(s) provisionales "
                       "huérfanas abortadas", res.modified_count)
    return int(res.modified_count)


async def _annul_transfer_mirror(tr: Dict[str, Any], reason: str) -> bool:
    """Anula el espejo físico de una transferencia con una COMPENSACIÓN
    trazable (nunca un aporte de capital) e invalida el arqueo vigente.
    Idempotente por id determinista."""
    trid = str(tr.get("id") or "")
    mov_id = str(tr.get("cash_box_movement_id") or "")
    mov = await db.cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
    if not mov:
        await db.fund_account_transfers.update_one(
            {"id": trid},
            {"$set": {"mirror_annulled_by": NOT_APPLICABLE}})
        return False
    annul_id = f"cmov_annul_{mov_id.replace('-', '')[:24]}"
    doc = {
        "id": annul_id,
        "box_id": mov.get("box_id"),
        "fund": mov.get("fund"),
        "type": "entrada" if mov.get("type") == "salida" else "salida",
        "amount": round(float(mov.get("amount") or 0), 2),
        "concept": f"Anulación de espejo: {reason}"[:200],
        "responsible": "Sistema",
        "denominations": None,
        "denoms_pending": True,
        "created_at": iso(now_utc()),
        "created_by_id": "system",
        "created_by_name": "Sistema",
        "annuls_movement_id": mov_id,
        "source_transfer_id": trid,
    }
    await _upsert_movement_with_rev(annul_id, doc)
    await db.cash_box_movements.update_one(
        {"id": mov_id}, {"$set": {"annulled_by": annul_id}})
    await db.fund_account_transfers.update_one(
        {"id": trid}, {"$set": {"mirror_annulled_by": annul_id}})
    logger.warning("[cash-box-sync] espejo %s anulado por %s (%s)",
                   mov_id, annul_id, reason[:80])
    return True


async def _relink_aborted_transfer_movements() -> int:
    """Q01 — recupera el vínculo inverso movimiento→transferencia cuando la
    escritura de la referencia falló entre ambos pasos: sin él, el reparador
    no podía ver la salida histórica de una transferencia abortada. Nunca se
    vincula un movimiento de COMPENSACIÓN (annuls_movement_id)."""
    n = 0
    missing = {"$in": [None, "", NOT_APPLICABLE]}
    q = {"status": "aborted", "cash_box_movement_id": missing,
         "mirror_annulled_by": {"$exists": False}}
    async for tr in db.fund_account_transfers.find(q, {"_id": 0, "id": 1}):
        mov = await db.cash_box_movements.find_one(
            {"source_transfer_id": tr["id"],
             "annuls_movement_id": {"$exists": False}},
            {"_id": 0, "id": 1})
        if not mov:
            continue
        res = await db.fund_account_transfers.update_one(
            {"id": tr["id"], "cash_box_movement_id": missing},
            {"$set": {"cash_box_movement_id": mov["id"]}})
        if res.modified_count:
            n += 1
            logger.warning("[cash-box-sync] vínculo recuperado: transferencia"
                           " abortada %s ← movimiento %s", tr["id"], mov["id"])
    return n


async def _repair_aborted_transfer_mirrors() -> int:
    """P02 — un movimiento físico unido a una transferencia ABORTADA es una
    salida sin operación válida: se anula con compensación trazable."""
    n = 0
    q = {"status": "aborted",
         "cash_box_movement_id": {"$nin": [None, "", NOT_APPLICABLE]},
         "mirror_annulled_by": {"$exists": False}}
    async for tr in db.fund_account_transfers.find(q, {"_id": 0}):
        if await _annul_transfer_mirror(
                tr, (f"la transferencia {tr.get('id')} fue abortada y su "
                     "movimiento físico no corresponde a una operación "
                     "válida")):
            n += 1
    return n


async def _repair_internal_transfer_mirrors() -> int:
    """M04 — un traslado que quedó INTERNO tras consolidar cuentas (mismo
    origen y destino) nunca movía billetes: si una versión anterior registró
    una salida física, se ANULA con una compensación trazable en la caja
    (nunca con un aporte de capital) y se invalida el arqueo vigente.
    Idempotente: repetir no añade más correcciones."""
    n = 0
    q = {"cash_box_movement_id": {"$nin": [None, "", NOT_APPLICABLE]},
         "mirror_annulled_by": {"$exists": False},
         "from_account_id": {"$nin": [None, ""]},
         "$expr": {"$eq": ["$from_account_id", "$to_account_id"]}}
    async for tr in db.fund_account_transfers.find(q, {"_id": 0}):
        if await _annul_transfer_mirror(
                tr, (f"el traslado {tr.get('id')} quedó interno tras "
                     "consolidar cuentas y no movía billetes")):
            n += 1
    return n


async def _relink_adjustment_movements() -> int:
    """T01 (continuación de S01) — recupera el vínculo inverso
    ajuste→movimiento cuando la versión anterior escribió el espejo físico
    pero falló antes de guardar `cash_box_movement_id` (o un backfill
    posterior marcó el ajuste «na»): sin el vínculo, el reparador de ajustes
    ajenos no veía el espejo y el efectivo duplicado seguía sumando en caja.
    Nunca se vincula una COMPENSACIÓN (annuls_movement_id)."""
    n = 0
    missing = {"$in": [None, "", NOT_APPLICABLE]}
    q = {"method": "cash", "cash_box_movement_id": missing,
         "mirror_annulled_by": {"$exists": False}}
    async for adj in db.company_fund_adjustments.find(q, {"_id": 0, "id": 1}):
        aid = str(adj.get("id") or "")
        if not aid:
            continue
        mov = await db.cash_box_movements.find_one(
            {"source_adjustment_id": aid,
             "annuls_movement_id": {"$exists": False}},
            {"_id": 0, "id": 1, "box_id": 1, "fund": 1, "rev_bumped": 1})
        if not mov:
            continue
        if not mov.get("rev_bumped"):
            # N05 — completar la invalidación pendiente ANTES de declarar el
            # origen sincronizado: el espejo pudo quedar a medias.
            await _bump_fund_rev(str(mov.get("box_id") or ""),
                                 str(mov.get("fund") or ""))
            await db.cash_box_movements.update_one(
                {"id": mov["id"]}, {"$set": {"rev_bumped": True}})
        res = await db.company_fund_adjustments.update_one(
            {"id": aid, "cash_box_movement_id": missing},
            {"$set": {"cash_box_movement_id": mov["id"]}})
        if res.modified_count:
            n += 1
            logger.warning("[cash-box-sync] vínculo recuperado: ajuste %s ← "
                           "movimiento %s (T01)", aid, mov["id"])
    return n


async def _repair_foreign_account_adjustment_mirrors() -> int:
    """S01 — un ajuste cash atribuido a OTRA cuenta de efectivo (no la caja
    canónica) nunca debió espejarse en la Caja de Efectivo: el traslado
    posterior hacia la canónica genera su propia entrada y el mismo efectivo
    se contaba dos veces. El espejo histórico se anula con una COMPENSACIÓN
    trazable (arqueo invalidado); el ajuste conserva el vínculo original y
    queda excluido de nuevas reevaluaciones por `mirror_annulled_by`."""
    n = 0
    q = {"method": "cash",
         "cash_box_movement_id": {"$nin": [None, "", NOT_APPLICABLE]},
         "mirror_annulled_by": {"$exists": False},
         "account_id": {"$nin": [None, ""]}}
    async for adj in db.company_fund_adjustments.find(q, {"_id": 0}):
        acc = await db.fund_accounts.find_one(
            {"id": adj["account_id"]}, {"_id": 0})
        if acc and await _is_company_cash_account(acc):
            continue
        aid = str(adj.get("id") or "")
        mov_id = str(adj.get("cash_box_movement_id") or "")
        mov = await db.cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
        if not mov:
            await db.company_fund_adjustments.update_one(
                {"id": aid}, {"$set": {"mirror_annulled_by": NOT_APPLICABLE}})
            continue
        annul_id = f"cmov_annul_{mov_id.replace('-', '')[:24]}"
        doc = {
            "id": annul_id,
            "box_id": mov.get("box_id"),
            "fund": mov.get("fund"),
            "type": "entrada" if mov.get("type") == "salida" else "salida",
            "amount": round(float(mov.get("amount") or 0), 2),
            "concept": (f"Anulación de espejo: el ajuste {aid} pertenece a "
                        "otra cuenta de efectivo, no a la caja")[:200],
            "responsible": "Sistema",
            "denominations": None,
            "denoms_pending": True,
            "created_at": iso(now_utc()),
            "created_by_id": "system",
            "created_by_name": "Sistema",
            "annuls_movement_id": mov_id,
            "source_adjustment_id": aid,
        }
        await _upsert_movement_with_rev(annul_id, doc)
        await db.cash_box_movements.update_one(
            {"id": mov_id}, {"$set": {"annulled_by": annul_id}})
        await db.company_fund_adjustments.update_one(
            {"id": aid}, {"$set": {"mirror_annulled_by": annul_id}})
        logger.warning("[cash-box-sync] espejo %s de ajuste en cuenta ajena "
                       "anulado por %s", mov_id, annul_id)
        n += 1
    return n


async def backfill_cash_adjustments() -> int:
    """Replica los ajustes en efectivo históricos que aún no están en la caja."""
    return await _backfill(db.company_fund_adjustments, {"method": "cash"},
                           mirror_adjustment_to_cash_box)


_DENOM_LINKS: tuple = (
    ("source_adjustment_id", lambda: db.company_fund_adjustments, "amount"),
    ("source_withdrawal_id", lambda: db.company_withdrawals, "amount"),
    ("source_client_withdrawal_id", lambda: db.withdrawals, "amount_usd"),
    ("source_transfer_id", lambda: db.fund_account_transfers, "amount"),
)


async def _converge_operation_denoms() -> int:
    """T02/T03 (continuación de S03) — el desglose de una operación vive en
    dos documentos (origen contable y movimiento físico) y versiones
    anteriores o una escritura interrumpida podían dejar solo uno:
      * movimiento completado sin propagarlo al origen (T02) → se copia al
        origen tras validar importe y moneda (el corte por fecha del pago
        frente al último conteo lo aplica el propio inventario);
      * origen adjudicado sin espejo (escritura interrumpida, T03) → el
        espejo converge al valor autorizado;
      * composiciones CONTRADICTORIAS → se marcan de forma trazable
        (`denoms_conflict`), jamás se sobrescribe un desglose autorizado.
    Se excluyen compensaciones y espejos anulados. Idempotente."""
    n = 0
    for field, coll_fn, amount_field in _DENOM_LINKS:
        coll = coll_fn()
        q = {field: {"$nin": [None, ""]},
             "annuls_movement_id": {"$exists": False},
             "annulled_by": {"$exists": False},
             "$or": [{"denominations": {"$nin": [None, {}]}},
                     {"denoms_pending": True}]}
        async for mov in db.cash_box_movements.find(q, {"_id": 0}):
            src_id = str(mov.get(field) or "")
            src = await coll.find_one({"id": src_id}, {"_id": 0})
            if not src:
                continue
            mov_denoms = mov.get("denominations") or None
            src_denoms = src.get("denominations") or None
            if mov_denoms == src_denoms:
                continue
            if mov_denoms and src_denoms:
                if not mov.get("denoms_conflict"):
                    await db.cash_box_movements.update_one(
                        {"id": mov["id"]},
                        {"$set": {"denoms_conflict": True}})
                    logger.warning(
                        "[cash-box-sync] desgloses contradictorios entre el "
                        "movimiento %s y su origen %s: requieren resolución "
                        "manual", mov["id"], src_id)
                continue
            if src_denoms:
                res = await db.cash_box_movements.update_one(
                    {"id": mov["id"], "denominations": {"$in": [None, {}]}},
                    {"$set": {"denominations": src_denoms,
                              "denoms_pending": False}})
                if res.modified_count:
                    await _bump_fund_rev(str(mov.get("box_id") or ""),
                                         str(mov.get("fund") or ""))
                    n += 1
                continue
            if (round(float(src.get(amount_field) or 0), 2)
                    != round(float(mov.get("amount") or 0), 2)
                    or fund_for_currency(src.get("currency"))
                    != mov.get("fund")):
                logger.warning(
                    "[cash-box-sync] desglose del movimiento %s no se "
                    "propaga: importe/moneda no coinciden con %s",
                    mov["id"], src_id)
                continue
            res = await coll.update_one(
                {"id": src_id, "denominations": {"$in": [None, {}]}},
                {"$set": {"denominations": mov_denoms}})
            if res.modified_count:
                n += 1
                logger.warning("[cash-box-sync] desglose completado en Caja "
                               "propagado al origen %s (T02)", src_id)
    return n


async def backfill_cash_operations() -> int:
    """Backfill completo: ajustes + retiros de empresa pagados + retiros de
    clientes pagados + transferencias internas, más reparaciones (identidad
    de cuentas, alias fusionados P03, marcadores legados, huérfanos,
    duplicados N06, provisionales M02/P01, espejos M04/P02, vínculos
    perdidos Q01/Q02/T01, «na» residuales de consolidaciones anteriores R01
    y convergencia de desgloses T02/T03). Idempotente."""
    from services.fund_accounts import (
        consolidate_duplicate_cash_accounts, repoint_merged_alias_links,
    )
    await consolidate_duplicate_cash_accounts()
    await repoint_merged_alias_links()
    await _stamp_cash_accounts()
    await _abort_stale_pending_transfers()
    await _relink_aborted_transfer_movements()
    await _relink_adjustment_movements()
    await _repair_aborted_transfer_mirrors()
    await _repair_internal_transfer_mirrors()
    await _repair_foreign_account_adjustment_mirrors()
    await _repair_orphan_movements()
    n = await _repair_legacy_markers()
    n += await _reevaluate_na_markers()
    for coll_fn, extra_q, mirror, _fields in _SOURCES:
        n += await _backfill(coll_fn(), extra_q, mirror)
    n += await _converge_operation_denoms()
    return n
