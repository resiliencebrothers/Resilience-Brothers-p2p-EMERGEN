"""iter350e — Limpieza de Huérfanos: barrido programado que elimina movimientos
de ajuste de conteo NO aplicados cuyo conteo de respaldo ya no está vigente
(superado por un recuento o borrado), complementando la invalidación en línea.

Casos: huérfano por versión superada, huérfano por conteo borrado, respeto del
pendiente VIVO (mismo id y versión, pending_apply/claiming), respeto del
movimiento reciente (ventana de gracia) y del ajuste ya aplicado.
"""
import uuid
from datetime import timedelta

import pytest

from db_client import db
from auth_utils import now_utc, iso
from services.inventory_ipv import cleanup_orphan_count_adjustments

pytestmark = pytest.mark.asyncio

OLD = iso(now_utc() - timedelta(hours=2))      # fuera de la ventana de gracia
RECENT = iso(now_utc())                         # dentro de la ventana de gracia


async def _mk_mov(pid, cid, ver, *, applied=False, created_at=OLD):
    mid = str(uuid.uuid4())
    await db.inventory_movements.insert_one({
        "id": mid, "product_id": pid, "product_name": pid, "type": "ajuste_neg",
        "quantity": 2.0, "unit": "unidad", "unit_price": 0.0, "unit_cost": 200.0,
        "total": 400.0, "cost_of_sale": 0.0, "profit": 0.0, "note": "",
        "source": "conteo", "ref_id": cid, "actor_id": "", "actor_email": "",
        "created_at": created_at, "dedupe_key": f"count-adjust:{cid}:v{ver}",
        "needs_stock": True, "stock_applied": applied})
    return mid


async def _mk_count(pid, cid, ver, auth_state, authorized=False):
    await db.inventory_counts.insert_one({
        "id": cid, "product_id": pid, "product_name": pid,
        "count_date": "2026-05-01", "counted_qty": 8.0, "theoretical_stock": 10.0,
        "difference": -2.0, "unit": "unidad", "version": ver,
        "auth_state": auth_state, "authorized": authorized})


async def _exists(mid):
    return await db.inventory_movements.find_one({"id": mid}) is not None


async def _cleanup(pid):
    await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_counts.delete_many({"product_id": pid})


async def test_removes_orphan_from_superseded_version():
    pid = f"TEST_ORPH_{uuid.uuid4().hex[:8]}"
    cid = str(uuid.uuid4())
    try:
        # Conteo superado: ahora va por la versión 2 (idle); el huérfano es v1.
        await _mk_count(pid, cid, ver=2, auth_state="idle")
        mid = await _mk_mov(pid, cid, ver=1)
        n = await cleanup_orphan_count_adjustments()
        assert n >= 1
        assert not await _exists(mid)
    finally:
        await _cleanup(pid)


async def test_removes_orphan_when_count_deleted():
    pid = f"TEST_ORPH_{uuid.uuid4().hex[:8]}"
    cid = str(uuid.uuid4())
    try:
        # No existe conteo de respaldo (fue borrado) → huérfano.
        mid = await _mk_mov(pid, cid, ver=1)
        n = await cleanup_orphan_count_adjustments()
        assert n >= 1
        assert not await _exists(mid)
    finally:
        await _cleanup(pid)


async def test_keeps_live_pending():
    pid = f"TEST_ORPH_{uuid.uuid4().hex[:8]}"
    cid = str(uuid.uuid4())
    try:
        # Pendiente VIVO: mismo id y versión, aún pending_apply sin autorizar.
        await _mk_count(pid, cid, ver=1, auth_state="pending_apply")
        mid = await _mk_mov(pid, cid, ver=1)
        await cleanup_orphan_count_adjustments()
        assert await _exists(mid), "no debe borrar un pendiente vivo"
    finally:
        await _cleanup(pid)


async def test_keeps_recent_movement():
    pid = f"TEST_ORPH_{uuid.uuid4().hex[:8]}"
    cid = str(uuid.uuid4())
    try:
        # Huérfano por versión, pero RECIENTE → dentro de la ventana de gracia.
        await _mk_count(pid, cid, ver=2, auth_state="idle")
        mid = await _mk_mov(pid, cid, ver=1, created_at=RECENT)
        await cleanup_orphan_count_adjustments()  # stale_minutes=30 por defecto
        assert await _exists(mid), "no debe tocar movimientos recientes"
    finally:
        await _cleanup(pid)


async def test_never_touches_applied_movement():
    pid = f"TEST_ORPH_{uuid.uuid4().hex[:8]}"
    cid = str(uuid.uuid4())
    try:
        # Un ajuste ya APLICADO nunca es candidato, aunque el conteo cambiara.
        await _mk_count(pid, cid, ver=2, auth_state="idle")
        mid = await _mk_mov(pid, cid, ver=1, applied=True)
        await cleanup_orphan_count_adjustments()
        assert await _exists(mid), "jamás borrar un ajuste aplicado"
    finally:
        await _cleanup(pid)
