"""SUN-08-R2-REG — ESCRITOR TARDÍO PUBLICA EFECTOS DESPUÉS DE LA REVERSIÓN.

Regresión del fix de la respuesta perdida (iter366): al quitar la reversión
incondicional del `except`, un escritor que publica la venta DESPUÉS de perder
la propiedad dejaba una venta ACTIVA colgando de un cobro ya 'reversed' (stock
descontado, ingreso +100, sin `voided`). Ni `heal_pending_cobros` (solo mira
committing/reversing) ni `reconcile_aborted_cobro_funds` (solo ventas ya
`cobro_aborted`) lo corregían.

La comprobación de propiedad (lease) del escritor y la publicación de la venta
son escrituras SEPARADAS → hay un intervalo en el que el recuperador puede robar
la propiedad y cerrar el cobro revirtiendo lo que existía (nada aún).

Fix en dos niveles:
1) El `except` de `pos_cobro`: si perdimos la propiedad y el cobro NO está
   'committed', compensamos NUESTROS efectos tardíos (reverse_cobro idempotente)
   antes de responder 409 — sin tocar jamás un cobro 'committed'.
2) Invariante DURABLE: `reconcile_reversed_cobro_effects` (scheduler) revierte
   cualquier venta activa que cuelgue de un cobro 'reversed' aunque el escritor
   muera antes de compensar.

Pruebas de aceptación cubiertas:
• pausa tras renovar el lease y antes de insertar (una línea).
• lo mismo en la SEGUNDA línea de un carrito.
• escritor que muere tras publicar el efecto tardío (lo cierra el reconciliador).
• (iter366) confirmación persistida con respuesta perdida sigue conservando sus
   efectos — se re-verifica aquí el invariante committed intacto.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from db_client import db
import routes.inventory as rinv
from services.inventory import (heal_pending_cobros,
                                reconcile_reversed_cobro_effects,
                                record_movement)
from routes.pos import pos_cobro, CobroIn, CobroLine
from tests.conftest import ADMIN_TOKEN


async def _mk(stock=10.0, price=100.0, cost=60.0, unit="unidad"):
    pid = f"TEST_REG_{uuid.uuid4().hex[:8]}"
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


async def _cleanup(*pids, extra_cobros=()):
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
    if extra_cobros:
        await db.pos_cobros.delete_many({"id": {"$in": list(extra_cobros)}})


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
    """Simula un escritor pausado 121s + un recuperador con el corte real 120s.
    El recuperador roba la propiedad y revierte lo que exista AHORA."""
    old = (datetime.now(timezone.utc) - timedelta(seconds=121)).isoformat()
    await db.pos_cobros.update_one({"id": cobro_id}, {"$set": {"updated_at": old}})
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    await heal_pending_cobros(cutoff)


# ═══ 1) Pausa tras renovar el lease y ANTES de insertar: el escritor publica la
#        venta DESPUÉS de que el recuperador cerró el cobro → compensada. ══════
@pytest.mark.asyncio
async def test_late_writer_single_line_is_compensated(monkeypatch):
    S = 10.0
    pid = await _mk(stock=S, price=100.0)
    idem = str(uuid.uuid4())
    real_impl = rinv._create_movement_impl

    async def _heal_then_publish(payload, request, actor, *, cobro_id=""):
        # El escritor se pausa ANTES de insertar la venta; el recuperador
        # reclama y revierte SIN encontrar ventas todavía → state=reversed.
        await _age_and_heal(cobro_id)
        # El escritor reanuda y publica la venta TARDÍA (ya sin propiedad).
        return await real_impl(payload, request, actor, cobro_id=cobro_id)

    monkeypatch.setattr(rinv, "_create_movement_impl", _heal_then_publish)
    try:
        with pytest.raises(HTTPException) as ei:
            await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        assert ei.value.status_code == 409
        assert ei.value.detail["code"] == "COBRO_RECOVERED"

        monkeypatch.undo()

        # La venta tardía quedó COMPENSADA: neto cero, stock íntegro.
        assert await _stock(pid) == S
        assert await _fund_net(pid) == 0.0
        v = await db.inventory_movements.find_one(
            {"product_id": pid, "type": "venta"}, {"_id": 0})
        assert v["voided"] is True and v["cobro_aborted"] is True
        cobro = await db.pos_cobros.find_one({"id": v["cobro_id"]}, {"_id": 0})
        assert cobro["state"] == "reversed"
        assert not cobro.get("result")
    finally:
        monkeypatch.undo()
        await _cleanup(pid)


# ═══ 2) Lo mismo pero en la SEGUNDA línea de un carrito ══════════════════════
@pytest.mark.asyncio
async def test_late_writer_second_line_is_compensated(monkeypatch):
    S = 10.0
    a = await _mk(stock=S, price=100.0)
    b = await _mk(stock=S, price=200.0)
    real_impl = rinv._create_movement_impl

    async def _heal_before_b(payload, request, actor, *, cobro_id=""):
        if payload.product_id == b:
            # Línea A ya publicada; interrumpimos ANTES de insertar la línea B.
            await _age_and_heal(cobro_id)
        return await real_impl(payload, request, actor, cobro_id=cobro_id)

    monkeypatch.setattr(rinv, "_create_movement_impl", _heal_before_b)
    try:
        with pytest.raises(HTTPException) as ei:
            await pos_cobro(
                CobroIn(items=[CobroLine(product_id=a, quantity=1),
                               CobroLine(product_id=b, quantity=1)], paid=300),
                _admin_request())
        assert ei.value.status_code == 409
        assert ei.value.detail["code"] == "COBRO_RECOVERED"

        monkeypatch.undo()

        # Ambas líneas compensadas (A revertida por el recuperador, B tardía por
        # el escritor): stock íntegro y neto cero en las dos.
        assert await _stock(a) == S and await _stock(b) == S
        assert await _fund_net(a) == 0.0 and await _fund_net(b) == 0.0
        va = await db.inventory_movements.find_one(
            {"product_id": a, "type": "venta"}, {"_id": 0})
        vb = await db.inventory_movements.find_one(
            {"product_id": b, "type": "venta"}, {"_id": 0})
        assert va["voided"] is True and va["cobro_aborted"] is True
        assert vb is not None and vb["voided"] is True and vb["cobro_aborted"] is True
        cobro = await db.pos_cobros.find_one({"id": va["cobro_id"]}, {"_id": 0})
        assert cobro["state"] == "reversed" and not cobro.get("result")
    finally:
        monkeypatch.undo()
        await _cleanup(a, b)


# ═══ 3) Escritor que MUERE tras publicar el efecto tardío (antes de compensar):
#        el invariante DURABLE lo cierra. ════════════════════════════════════
@pytest.mark.asyncio
async def test_durable_reconciler_fixes_orphan_late_sale():
    S = 10.0
    pid = await _mk(stock=S, price=100.0)
    cid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        # Cobro ya cerrado por el recuperador (reversed) + venta ACTIVA que un
        # escritor tardío publicó y no alcanzó a compensar (proceso muerto).
        await db.pos_cobros.insert_one({
            "id": cid, "state": "reversed", "owner": "healer:crashed",
            "mov_ids": [], "updated_at": now, "created_at": now})
        prod = await db.products.find_one({"id": pid}, {"_id": 0})
        await record_movement(product=prod, mtype="venta", quantity=1,
                              source="manual", cobro_id=cid)

        # Estado HUÉRFANO antes del reconciliador.
        assert await _stock(pid) == S - 1
        assert await _fund_net(pid) == 100.0
        v = await db.inventory_movements.find_one(
            {"product_id": pid, "type": "venta"}, {"_id": 0})
        assert v.get("voided") is not True

        # Respaldo durable: revierte la venta activa del cobro reversado.
        since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        n = await reconcile_reversed_cobro_effects(since)
        assert n >= 1

        assert await _stock(pid) == S
        assert await _fund_net(pid) == 0.0
        v2 = await db.inventory_movements.find_one(
            {"product_id": pid, "type": "venta"}, {"_id": 0})
        assert v2["voided"] is True and v2["cobro_aborted"] is True

        # Idempotente: repetir no cambia nada.
        await reconcile_reversed_cobro_effects(since)
        assert await _stock(pid) == S and await _fund_net(pid) == 0.0
    finally:
        await _cleanup(pid, extra_cobros=(cid,))


# ═══ 4) Invariante committed intacto: una confirmación buena NO se compensa ═══
@pytest.mark.asyncio
async def test_committed_cobro_effects_survive_reconciler():
    S = 10.0
    pid = await _mk(stock=S, price=100.0)
    idem = str(uuid.uuid4())
    try:
        r = await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        assert r["total"] == 100.0
        # El reconciliador de cobros reversados NO debe tocar un cobro bueno.
        since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        await reconcile_reversed_cobro_effects(since)
        assert await _stock(pid) == S - 1
        assert await _fund_net(pid) == 100.0
        v = await db.inventory_movements.find_one(
            {"product_id": pid, "type": "venta"}, {"_id": 0})
        assert v.get("voided") is not True
    finally:
        await _cleanup(pid)
