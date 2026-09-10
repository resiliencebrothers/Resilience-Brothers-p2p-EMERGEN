"""iter269(V01) — Presupuesto atómico de retiros de empresa por moneda.

Leer un agregado y luego escribir documentos distintos no impide que dos
retiros DIFERENTES consuman el mismo disponible (V01). Este servicio
serializa el gasto contra UN documento de presupuesto por moneda:
  - creación: la reserva se comprueba y consume en un único update con guard
    (`reserved <= disponible - importe`), bajo el cerrojo de gasto,
  - pago: el mismo cerrojo exclusivo por moneda (`pay_lock` con caducidad)
    obliga a evaluar el disponible DENTRO de la sección crítica, nunca sobre
    una foto vieja,
  - rechazo/pago: la reserva se libera exactamente una vez (el claim atómico
    de estado del retiro garantiza un solo liberador),
  - recuperación: `resync_budgets` recalcula la reserva desde los retiros
    reales cuando no hay actividad reciente; una reserva huérfana (residuo de
    docs mutados externamente) también se corrige con CAS en el claim.
"""
import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Optional

from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import iso, now_utc

logger = logging.getLogger(__name__)

_EPS = 1e-6
_LOCK_STALE_MINUTES = 2
_LOCK_WAIT_SECONDS = 8.0
_RESYNC_QUIET_MINUTES = 15
_CLAIM_HEAL_QUIET_SECONDS = 5

_INDEX_READY = False


async def _ensure_index() -> None:
    global _INDEX_READY
    if _INDEX_READY:
        return
    try:
        await db.company_fund_budgets.create_index("currency", unique=True)
        _INDEX_READY = True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"índice de presupuesto no disponible: {e}")


async def _pending_sum(currency: str) -> float:
    total = 0.0
    async for r in db.company_withdrawals.find(
            {"currency": currency, "status": {"$in": ["pending", "approved"]}},
            {"_id": 0, "amount": 1}):
        total += float(r.get("amount") or 0.0)
    return round(total, 6)


async def _ensure_budget(currency: str) -> None:
    await _ensure_index()
    if await db.company_fund_budgets.find_one({"currency": currency},
                                              {"_id": 1}):
        return
    reserved = await _pending_sum(currency)
    try:
        await db.company_fund_budgets.update_one(
            {"currency": currency},
            {"$setOnInsert": {"currency": currency, "reserved": reserved,
                              "pay_lock": "", "pay_locked_at": "",
                              "updated_at": iso(now_utc())}},
            upsert=True)
    except DuplicateKeyError:
        pass  # otro creador ganó la carrera: el doc ya existe


async def current_reserved(currency: str) -> float:
    doc = await db.company_fund_budgets.find_one(
        {"currency": currency}, {"_id": 0, "reserved": 1})
    return float((doc or {}).get("reserved") or 0.0)


async def _heal_over_reservation(currency: str) -> bool:
    """Corrige una reserva huérfana (mayor que los retiros reales) con CAS,
    solo si el presupuesto lleva unos segundos sin actividad — nunca pisa
    una operación en vuelo (todo claim actualiza `updated_at`)."""
    doc = await db.company_fund_budgets.find_one(
        {"currency": currency}, {"_id": 0})
    if not doc:
        return False
    quiet = iso(now_utc() - timedelta(seconds=_CLAIM_HEAL_QUIET_SECONDS))
    if (doc.get("updated_at") or "") > quiet:
        return False
    real = await _pending_sum(currency)
    if float(doc.get("reserved") or 0.0) <= real + _EPS:
        return False
    res = await db.company_fund_budgets.update_one(
        {"currency": currency, "reserved": doc.get("reserved"),
         "updated_at": doc.get("updated_at")},
        {"$set": {"reserved": real, "updated_at": iso(now_utc())}})
    if res.modified_count:
        logger.warning("[fund-budget] reserva huérfana de %s corregida a %.6f",
                       currency, real)
    return bool(res.modified_count)


async def claim_reservation(currency: str, amount: float,
                            available: float) -> bool:
    """Reserva atómica en la creación: comprobar y consumir en un solo paso.
    Si el guard falla por una reserva huérfana, se corrige y reintenta una vez."""
    await _ensure_budget(currency)
    for attempt in (0, 1):
        res = await db.company_fund_budgets.update_one(
            {"currency": currency,
             "reserved": {"$lte": round(available - amount + _EPS, 6)}},
            {"$inc": {"reserved": round(amount, 6)},
             "$set": {"updated_at": iso(now_utc())}})
        if res.matched_count == 1:
            return True
        if attempt or not await _heal_over_reservation(currency):
            return False
    return False


async def release_reservation(currency: str, amount: float) -> None:
    """Libera la reserva (pago completado, rechazo o inserción fallida).
    Guard: la reserva nunca queda negativa; ante deriva se recalcula desde
    los retiros reales con CAS (y si no aplica, el resync la corrige)."""
    await _ensure_budget(currency)
    amt = round(float(amount), 6)
    res = await db.company_fund_budgets.update_one(
        {"currency": currency, "reserved": {"$gte": amt - _EPS}},
        {"$inc": {"reserved": -amt},
         "$set": {"updated_at": iso(now_utc())}})
    if res.matched_count == 1:
        return
    doc = await db.company_fund_budgets.find_one(
        {"currency": currency}, {"_id": 0})
    real = await _pending_sum(currency)
    cas = await db.company_fund_budgets.update_one(
        {"currency": currency,
         "reserved": (doc or {}).get("reserved"),
         "updated_at": (doc or {}).get("updated_at")},
        {"$set": {"reserved": real, "updated_at": iso(now_utc())}})
    if not cas.matched_count:
        logger.warning("[fund-budget] liberación de %s aplazada al resync",
                       currency)


async def acquire_pay_lock(currency: str) -> Optional[str]:
    """Cerrojo exclusivo de GASTO por moneda (creación y pago contienden
    sobre el mismo registro), con robo de cerrojos caducados."""
    await _ensure_budget(currency)
    token = uuid.uuid4().hex
    now = iso(now_utc())
    stale = iso(now_utc() - timedelta(minutes=_LOCK_STALE_MINUTES))
    res = await db.company_fund_budgets.update_one(
        {"currency": currency,
         "$or": [{"pay_lock": {"$in": [None, ""]}},
                 {"pay_locked_at": {"$lt": stale}}]},
        {"$set": {"pay_lock": token, "pay_locked_at": now, "updated_at": now}})
    return token if res.matched_count == 1 else None


async def acquire_pay_lock_wait(
        currency: str,
        timeout_s: float = _LOCK_WAIT_SECONDS) -> Optional[str]:
    """Espera breve por el cerrojo de gasto de la moneda (V01)."""
    deadline = now_utc() + timedelta(seconds=timeout_s)
    while True:
        token = await acquire_pay_lock(currency)
        if token or now_utc() >= deadline:
            return token
        await asyncio.sleep(0.08)


async def release_pay_lock(currency: str, token: str) -> None:
    await db.company_fund_budgets.update_one(
        {"currency": currency, "pay_lock": token},
        {"$set": {"pay_lock": "", "pay_locked_at": "",
                  "updated_at": iso(now_utc())}})


async def resync_budgets() -> int:
    """Recuperación ante fallos: si un proceso murió entre el presupuesto y el
    estado del retiro, la reserva puede quedar desviada. Recalcula desde los
    retiros reales, solo sobre presupuestos SIN actividad reciente."""
    fixed = 0
    quiet = iso(now_utc() - timedelta(minutes=_RESYNC_QUIET_MINUTES))
    async for b in db.company_fund_budgets.find({}, {"_id": 0}):
        if (b.get("updated_at") or "") > quiet:
            continue  # actividad reciente: no pisar operaciones en vuelo
        real = await _pending_sum(str(b.get("currency") or ""))
        if abs(float(b.get("reserved") or 0.0) - real) <= _EPS:
            continue
        res = await db.company_fund_budgets.update_one(
            {"currency": b.get("currency"), "updated_at": b.get("updated_at")},
            {"$set": {"reserved": real, "updated_at": iso(now_utc())}})
        if res.modified_count:
            fixed += 1
            logger.warning(
                "[fund-budget] reserva de %s resincronizada a %.6f",
                b.get("currency"), real)
    return fixed
