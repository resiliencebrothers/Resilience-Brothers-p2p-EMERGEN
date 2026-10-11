"""SUN-08-R2-REC-INT — una compensación PARCIAL no debe desaparecer al marcarse
`voided`.

`reverse_pos_sale` marca `voided=True`/`cobro_aborted=True` (decisión TERMINAL de
aborto) ANTES de devolver el stock y documentar la reposición. Si se interrumpe
en esa frontera, la venta queda `voided` pero con stock aún debido. El filtro por
«venta activa» (`voided != True`) PERDÍA esa obligación: todos los recuperadores
la saltaban y la salud reportaba healthy=True con una unidad descontada para
siempre.

Fix: separar la DECISIÓN de aborto (`voided`/`cobro_aborted`) de la EVIDENCIA de
compensación terminada (`reversal_done`). La obligación sigue seleccionable hasta
que stock + su doc + fondo estén garantizados y se selle `reversal_done=True`
(reanudación idempotente, sin duplicar stock ni dinero). La supervisión cuenta esa
misma obligación incompleta.

Aceptación:
• interrupción tras persistir `voided` y antes de devolver stock — desde el
  RECONCILIADOR y desde la PETICIÓN.
• interrupción tras devolver stock y antes de documentar la reposición — sin
  duplicar stock al retomar.
• la salud muestra el pendiente antes; tras reparar: stock 10, fondo 0, 0 obligac.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from db_client import db
import services.inventory as si
import routes.inventory as rinv
from services.inventory import (reconcile_reversed_cobro_effects,
                                reconciliation_health, record_movement,
                                heal_pending_cobros)
from routes.pos import pos_cobro, CobroIn, CobroLine
from tests.conftest import ADMIN_TOKEN

STOCK = 10.0


async def _mk(stock=STOCK, price=100.0):
    pid = f"TEST_RECINT_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": price,
        "cost_usd": 60.0, "stock": stock, "unit": "unidad", "is_active": True})
    return pid


async def _stock(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
    return round(float((p or {}).get("stock") or 0), 3)


async def _fund_net(pid):
    movs = await db.inventory_movements.find(
        {"product_id": pid}, {"_id": 0, "id": 1}).to_list(5000)
    ids = [m["id"] for m in movs]
    rows = await db.company_fund_adjustments.find(
        {"ref_id": {"$in": ids}}, {"_id": 0, "adjustment_type": 1, "amount": 1}
    ).to_list(5000)
    net = 0.0
    for r in rows:
        a = float(r["amount"])
        net += a if r["adjustment_type"] == "inflow" else -a
    return round(net, 2)


async def _venta(pid):
    return await db.inventory_movements.find_one(
        {"product_id": pid, "type": "venta"}, {"_id": 0})


async def _reversed_pending_for(cid):
    """¿La salud cuenta ESTE cobro como obligación de reverso incompleto?"""
    pipe = [
        {"$match": {"id": cid, "state": "reversed"}},
        {"$lookup": {
            "from": "inventory_movements", "let": {"cid": "$id"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$cobro_id", "$$cid"]},
                    {"$eq": ["$type", "venta"]},
                    {"$eq": ["$source", "manual"]},
                    {"$ne": ["$reversal_done", True]}]}}},
                {"$limit": 1}, {"$project": {"_id": 1}}],
            "as": "_p"}},
        {"$match": {"_p": {"$ne": []}}}, {"$count": "n"}]
    r = await db.pos_cobros.aggregate(pipe).to_list(1)
    return r[0]["n"] if r else 0


async def _cleanup(pid, cid=None):
    movs = await db.inventory_movements.find(
        {"product_id": pid}, {"_id": 0, "id": 1, "cobro_id": 1}).to_list(5000)
    ids = [m["id"] for m in movs]
    cobro_ids = [m.get("cobro_id") for m in movs if m.get("cobro_id")]
    await db.company_fund_adjustments.delete_many({"ref_id": {"$in": ids}})
    await db.inventory_movements.delete_many({"product_id": pid})
    for mid in ids:
        await db.stock_ops.delete_many({"op_id": {"$in": [
            f"invmov:{mid}", f"invmov:{mid}:burn", f"invmov:{mid}:undo"]}})
    await db.products.delete_many({"id": pid})
    await db.inventory_lots.delete_many({"product_id": pid})
    await db.pos_cobros.delete_many({"id": {"$in": cobro_ids + ([cid] if cid else [])}})


def _admin_request():
    scope = {
        "type": "http", "method": "POST", "path": "/api/admin/pos/cobro",
        "raw_path": b"/api/admin/pos/cobro", "query_string": b"",
        "headers": [(b"authorization", f"Bearer {ADMIN_TOKEN}".encode())],
        "scheme": "http", "server": ("testserver", 80),
        "client": ("testclient", 12345)}
    return Request(scope)


def _payload(pid, qty=1, paid=100, idem=""):
    return CobroIn(items=[CobroLine(product_id=pid, quantity=qty)],
                   paid=paid, idempotency_key=idem)


async def _age_and_heal(cobro_id):
    old = (datetime.now(timezone.utc) - timedelta(seconds=121)).isoformat()
    await db.pos_cobros.update_one({"id": cobro_id}, {"$set": {"updated_at": old}})
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    await heal_pending_cobros(cutoff)


async def _seed_reversed_sale(pid, cid):
    """Venta real (stock aplicado, ingreso +100) colgando de un cobro reversed."""
    now = datetime.now(timezone.utc).isoformat()
    await db.pos_cobros.insert_one({
        "id": cid, "state": "reversed", "owner": "healer:x", "mov_ids": [],
        "updated_at": now, "created_at": now})
    prod = await db.products.find_one({"id": pid}, {"_id": 0})
    await record_movement(product=prod, mtype="venta", quantity=1,
                          source="manual", cobro_id=cid)


# ═══ 1) Interrupción tras `voided` y antes de devolver stock — RECONCILIADOR ══
@pytest.mark.asyncio
async def test_partial_reversal_via_reconciler_is_resumed(monkeypatch):
    pid = await _mk()
    cid = str(uuid.uuid4())
    await _seed_reversed_sale(pid, cid)
    assert await _stock(pid) == STOCK - 1
    assert await _fund_net(pid) == 100.0

    calls = {"n": 0}
    real_burn = si.burn_or_undo_stock

    async def _burn_fail_once(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transitorio en la frontera de persistencia")
        return await real_burn(*a, **k)

    monkeypatch.setattr(si, "burn_or_undo_stock", _burn_fail_once)
    try:
        with pytest.raises(RuntimeError):
            await reconcile_reversed_cobro_effects()
        # Parcial: `voided` persistió pero el stock NO se devolvió.
        v = await _venta(pid)
        assert v["voided"] is True and v["cobro_aborted"] is True
        assert v.get("reversal_done") is not True
        assert await _stock(pid) == STOCK - 1
        # La salud DEBE mostrar el pendiente (no desaparece por estar voided).
        assert await _reversed_pending_for(cid) >= 1
        h = await reconciliation_health()
        assert h["healthy"] is False
        assert h["queues"]["reversed_cobro_effects"]["pending"] >= 1

        monkeypatch.undo()
        # Reanudación idempotente: completa stock + doc + fondo y sella done.
        await reconcile_reversed_cobro_effects()
        assert await _stock(pid) == STOCK
        assert await _fund_net(pid) == 0.0
        v2 = await _venta(pid)
        assert v2["reversal_done"] is True
        assert await _reversed_pending_for(cid) == 0
    finally:
        monkeypatch.undo()
        await _cleanup(pid, cid)


# ═══ 2) Interrupción tras `voided` y antes de devolver stock — PETICIÓN ═══════
@pytest.mark.asyncio
async def test_partial_reversal_via_request_is_resumed(monkeypatch):
    pid = await _mk()
    idem = str(uuid.uuid4())
    real_impl = rinv._create_movement_impl
    real_burn = si.burn_or_undo_stock
    calls = {"n": 0}

    async def _heal_then_publish(payload, request, actor, *, cobro_id=""):
        await _age_and_heal(cobro_id)   # recuperador cierra el cobro: reversed
        return await real_impl(payload, request, actor, cobro_id=cobro_id)

    async def _burn_fail_once(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transitorio durante la compensación del escritor")
        return await real_burn(*a, **k)

    monkeypatch.setattr(rinv, "_create_movement_impl", _heal_then_publish)
    monkeypatch.setattr(si, "burn_or_undo_stock", _burn_fail_once)
    try:
        with pytest.raises(HTTPException) as ei:
            await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        assert ei.value.status_code == 409

        monkeypatch.undo()
        # Compensación interrumpida tras `voided`: stock aún debido.
        v = await _venta(pid)
        assert v["voided"] is True and v["cobro_aborted"] is True
        assert v.get("reversal_done") is not True
        assert await _stock(pid) == STOCK - 1
        cid = v["cobro_id"]
        assert await _reversed_pending_for(cid) >= 1
        assert (await reconciliation_health())["healthy"] is False

        # El reconciliador de fondo la retoma y la completa.
        await reconcile_reversed_cobro_effects()
        assert await _stock(pid) == STOCK
        assert await _fund_net(pid) == 0.0
        v2 = await _venta(pid)
        assert v2["reversal_done"] is True
        assert await _reversed_pending_for(cid) == 0
    finally:
        monkeypatch.undo()
        await _cleanup(pid)


# ═══ 3) Interrupción tras devolver stock y antes de documentar — sin duplicar ═
@pytest.mark.asyncio
async def test_interrupt_after_stock_before_doc_no_double_stock(monkeypatch):
    pid = await _mk()
    cid = str(uuid.uuid4())
    await _seed_reversed_sale(pid, cid)
    assert await _stock(pid) == STOCK - 1

    real_rm = si.record_movement
    state = {"raised": False}

    async def _rm_fail_restock_once(*a, **k):
        if (not state["raised"]
                and str(k.get("dedupe_key", "")).startswith("cobro-rev-stock:")):
            state["raised"] = True
            raise RuntimeError("transitorio antes de documentar la reposición")
        return await real_rm(*a, **k)

    monkeypatch.setattr(si, "record_movement", _rm_fail_restock_once)
    try:
        with pytest.raises(RuntimeError):
            await reconcile_reversed_cobro_effects()
        # El stock YA se devolvió (burn 'undone'), pero falta el doc de reposición.
        assert await _stock(pid) == STOCK
        assert await db.inventory_movements.find_one(
            {"cobro_id": cid, "type": "ajuste_pos"}, {"_id": 1}) is None
        v = await _venta(pid)
        assert v.get("reversal_done") is not True
        assert await _reversed_pending_for(cid) >= 1
        assert (await reconciliation_health())["healthy"] is False

        monkeypatch.undo()
        # Reanudar NO debe volver a devolver stock (burn ya está 'undone').
        await reconcile_reversed_cobro_effects()
        assert await _stock(pid) == STOCK   # sigue 10, NO 11
        assert await db.inventory_movements.find_one(
            {"cobro_id": cid, "type": "ajuste_pos"}, {"_id": 1}) is not None
        v2 = await _venta(pid)
        assert v2["reversal_done"] is True
        assert await _fund_net(pid) == 0.0
        assert await _reversed_pending_for(cid) == 0
    finally:
        monkeypatch.undo()
        await _cleanup(pid, cid)
