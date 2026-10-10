"""SUN-08-R2 — El recuperador NO debe competir con un cobro todavía activo.

Bug: `heal_pending_cobros` seleccionaba cobros committing/reversing antiguos y
los revertía SIN reclamar primero la operación con una transición condicional;
el escritor seguía escribiendo por `id` (incluida la confirmación final) sin
verificar que conservara la propiedad. La antigüedad de 120s no prueba que el
escritor haya muerto → un escritor pausado y luego reanudado dejaba la operación
'committed' con un resultado de éxito que apuntaba a una venta ANULADA.

Fix: token de PROPIEDAD/generación (`owner`) + transiciones CONDICIONALES. El
escritor verifica la propiedad antes de publicar cada efecto y en la
confirmación final (CAS `committing→committed` con su owner). El recuperador
ROBA la propiedad con un reclamo atómico condicionado a estado+antigüedad. Solo
sobrevive UN resultado: committed con efectos válidos, o abortado con neto cero;
ningún éxito almacenado apunta a una venta anulada.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from db_client import db
import routes.inventory as rinv
from services.inventory import reverse_cobro, heal_pending_cobros  # noqa: F401
from routes.pos import pos_cobro, CobroIn, CobroLine
from tests.conftest import ADMIN_TOKEN


async def _mk(stock=10.0, price=100.0, cost=60.0, unit="unidad"):
    pid = f"TEST_R2_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": price,
        "cost_usd": cost, "stock": stock, "unit": unit, "is_active": True})
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


async def _cobro_doc_for(pid):
    v = await db.inventory_movements.find_one(
        {"product_id": pid, "type": "venta"}, {"_id": 0, "cobro_id": 1})
    if not v or not v.get("cobro_id"):
        return None
    return await db.pos_cobros.find_one({"id": v["cobro_id"]}, {"_id": 0})


async def _cleanup(*pids):
    for pid in pids:
        movs = await db.inventory_movements.find(
            {"product_id": pid}, {"_id": 0, "id": 1, "cobro_id": 1}).to_list(5000)
        mov_ids = [m["id"] for m in movs]
        cobro_ids = [m.get("cobro_id") for m in movs if m.get("cobro_id")]
        await db.company_fund_adjustments.delete_many({"ref_id": {"$in": mov_ids}})
        await db.inventory_movements.delete_many({"product_id": pid})
        for mid in mov_ids:
            await db.stock_ops.delete_many(
                {"op_id": {"$in": [f"invmov:{mid}", f"invmov:{mid}:burn",
                                   f"invmov:{mid}:undo"]}})
        await db.products.delete_many({"id": pid})
        await db.inventory_lots.delete_many({"product_id": pid})
        if cobro_ids:
            await db.pos_cobros.delete_many({"id": {"$in": cobro_ids}})


def _admin_request():
    scope = {
        "type": "http", "method": "POST", "path": "/api/admin/pos/cobro",
        "raw_path": b"/api/admin/pos/cobro", "query_string": b"",
        "headers": [(b"authorization", f"Bearer {ADMIN_TOKEN}".encode())],
        "scheme": "http", "server": ("testserver", 80),
        "client": ("testclient", 12345),
    }
    return Request(scope)


def _payload(pid, qty=1, paid=100, idem=""):
    return CobroIn(items=[CobroLine(product_id=pid, quantity=qty)],
                   paid=paid, idempotency_key=idem)


async def _age_and_heal(cobro_id):
    """Simula un escritor pausado 121s + un recuperador con el corte real 120s."""
    old = (datetime.now(timezone.utc) - timedelta(seconds=121)).isoformat()
    await db.pos_cobros.update_one({"id": cobro_id}, {"$set": {"updated_at": old}})
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    await heal_pending_cobros(cutoff)


# ═══════ Orden H→W: el recuperador revierte y el escritor reanuda la confirmación
@pytest.mark.asyncio
async def test_healer_then_writer_commit_aborts_with_net_zero(monkeypatch):
    S = 10.0
    pid = await _mk(stock=S, price=100.0)
    idem = str(uuid.uuid4())
    real_impl = rinv._create_movement_impl

    async def _impl_then_heal(payload, request, actor, *, cobro_id=""):
        mov = await real_impl(payload, request, actor, cobro_id=cobro_id)
        # El escritor "se pausa" tras publicar la venta; el recuperador (lectura
        # antigua) reclama y revierte ANTES de la confirmación final.
        await _age_and_heal(cobro_id)
        return mov

    monkeypatch.setattr(rinv, "_create_movement_impl", _impl_then_heal)
    try:
        with pytest.raises(HTTPException) as ei:
            await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        assert ei.value.status_code == 409
        assert ei.value.detail["code"] == "COBRO_RECOVERED"

        # SOLO sobrevive el resultado abortado con neto cero.
        assert await _stock(pid) == S
        assert await _fund_net(pid) == 0.0
        v = await db.inventory_movements.find_one(
            {"product_id": pid, "type": "venta"}, {"_id": 0})
        assert v["voided"] is True and v["cobro_aborted"] is True
        cobro = await db.pos_cobros.find_one({"id": v["cobro_id"]}, {"_id": 0})
        assert cobro["state"] == "reversed"
        # NINGÚN éxito almacenado que apunte a una venta anulada.
        assert not cobro.get("result")

        # Reintentar con la misma clave NO devuelve un éxito: reporta revertido.
        monkeypatch.undo()
        with pytest.raises(HTTPException) as ei2:
            await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        assert ei2.value.status_code == 409
        assert ei2.value.detail["code"] == "COBRO_REVERSED"
        assert await _stock(pid) == S and await _fund_net(pid) == 0.0
    finally:
        await _cleanup(pid)


# ═══════ Orden W→H: el escritor confirma y un recuperador tardío NO lo toca ═
@pytest.mark.asyncio
async def test_writer_commit_then_late_healer_is_noop():
    S = 10.0
    pid = await _mk(stock=S, price=100.0)
    idem = str(uuid.uuid4())
    try:
        r = await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        assert r["total"] == 100.0
        cobro = await db.pos_cobros.find_one(
            {"idempotency_key": idem}, {"_id": 0})
        # Recuperador tardío con lectura antigua: NO revierte un cobro confirmado.
        await _age_and_heal(cobro["id"])
        cobro2 = await db.pos_cobros.find_one({"id": cobro["id"]}, {"_id": 0})
        assert cobro2["state"] == "committed"
        assert cobro2.get("result")
        v = await db.inventory_movements.find_one(
            {"product_id": pid, "type": "venta"}, {"_id": 0})
        assert v.get("voided") is not True
        assert await _stock(pid) == S - 1
        assert await _fund_net(pid) == 100.0
    finally:
        await _cleanup(pid)


# ═══════ Cobro pausado ENTRE líneas: no publica la línea posterior ══════════
@pytest.mark.asyncio
async def test_paused_between_lines_does_not_publish_later_line(monkeypatch):
    S = 10.0
    a = await _mk(stock=S, price=100.0)
    b = await _mk(stock=S, price=200.0)
    real_impl = rinv._create_movement_impl

    async def _impl_heal_after_a(payload, request, actor, *, cobro_id=""):
        mov = await real_impl(payload, request, actor, cobro_id=cobro_id)
        if payload.product_id == a:   # tras publicar la 1ª línea, interrumpe
            await _age_and_heal(cobro_id)
        return mov

    monkeypatch.setattr(rinv, "_create_movement_impl", _impl_heal_after_a)
    try:
        with pytest.raises(HTTPException) as ei:
            await pos_cobro(
                CobroIn(items=[CobroLine(product_id=a, quantity=1),
                               CobroLine(product_id=b, quantity=1)], paid=300),
                _admin_request())
        assert ei.value.status_code == 409

        # Línea A revertida (neto cero); línea B NUNCA publicada.
        assert await _stock(a) == S
        assert await _fund_net(a) == 0.0
        va = await db.inventory_movements.find_one(
            {"product_id": a, "type": "venta"}, {"_id": 0})
        assert va["voided"] is True
        vb = await db.inventory_movements.find_one(
            {"product_id": b, "type": "venta"}, {"_id": 0})
        assert vb is None
        assert await _stock(b) == S
        cobro = await db.pos_cobros.find_one({"id": va["cobro_id"]}, {"_id": 0})
        assert cobro["state"] == "reversed"
        assert not cobro.get("result")
    finally:
        await _cleanup(a, b)


# ═══════ Un escritor que renovó su lease NO es robado por el recuperador ════
@pytest.mark.asyncio
async def test_fresh_lease_not_stolen_by_stale_healer():
    S = 10.0
    pid = await _mk(stock=S, price=100.0)
    owner = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    prod = await db.products.find_one({"id": pid}, {"_id": 0})
    try:
        from services.inventory import record_movement
        await record_movement(product=prod, mtype="venta", quantity=1,
                              source="manual", cobro_id=cid)
        # Cobro en curso con lease FRESCO (el escritor acaba de renovar).
        await db.pos_cobros.insert_one({
            "id": cid, "state": "committing", "owner": owner, "mov_ids": [],
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat()})
        # Recuperador con corte 120s: NO debe robar un escritor en vuelo.
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        await heal_pending_cobros(cutoff)
        cobro = await db.pos_cobros.find_one({"id": cid}, {"_id": 0})
        assert cobro["state"] == "committing" and cobro["owner"] == owner
        v = await db.inventory_movements.find_one(
            {"product_id": pid, "type": "venta"}, {"_id": 0})
        assert v.get("voided") is not True
        assert await _stock(pid) == S - 1
    finally:
        await _cleanup(pid)
