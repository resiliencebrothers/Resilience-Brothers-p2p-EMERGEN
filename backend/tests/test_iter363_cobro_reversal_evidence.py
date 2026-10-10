"""SUN-08-R1 — El reverso de un cobro abortado debe compensar SOLO los efectos
que REALMENTE se aplicaron, no revertir a ciegas.

Bug: `reverse_pos_sale` creaba una salida de dinero y una devolución de stock
sin comprobar qué efectos originales llegaron a ejecutarse.
  • Variante 1 (interrumpido ANTES del descuento): la venta existe con
    stock_applied=False; el reverso devolvía stock (→ 11) y creaba una salida
    (→ fondo −100) de un ingreso que nunca existió. El recuperador general
    luego reaplicaba la unidad y dejaba el fondo en −100.
  • Variante 2 (stock aplicado pero el ingreso falló y fue absorbido): el
    reverso dejaba la salida sin que hubiera entrada → fondo −100.

Fix: evidencia durable + decisión terminal compartida (voided + cobro_aborted).
El stock se resuelve con `burn_or_undo_stock` (undone/burned); el ingreso se
revierte SOLO si su asiento INFLOW propio existe; los recuperadores generales
excluyen los cobros abortados. En TODO cobro abortado: neto del fondo = 0, stock
como si la venta nunca ocurrió, y la reconstrucción por movimientos cuadra.
"""
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from db_client import db
import routes.inventory as rinv
import services.inventory as sinv
from services.inventory import record_movement, reverse_cobro, build_dashboard, today_havana
from services.inventory_history import _documented_totals
from services.credit_recovery import heal_initializing_ops
from routes.pos import pos_cobro, CobroIn, CobroLine
from tests.conftest import ADMIN_TOKEN

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk(stock=10.0, price=100.0, cost=60.0, unit="unidad"):
    pid = f"TEST_R1_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": price,
        "cost_usd": cost, "stock": stock, "unit": unit, "is_active": True})
    return pid


async def _stock(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
    return round(float((p or {}).get("stock") or 0), 3)


async def _fund_net(pid):
    """Neto del fondo atribuible a este producto (inflow − outflow)."""
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


async def _documented(pid):
    """Delta de stock reconstruido SOLO desde movimientos (igual que el IPV)."""
    d = await _documented_totals([pid])
    return round(float(d.get(pid, 0)), 3)


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


# ═══════ Variante 1 — interrumpido ANTES del descuento (nunca aplicado) ═════
@pytest.mark.asyncio
async def test_r1_variant1_not_applied_no_overcredit(monkeypatch):
    S = 10.0
    pid = await _mk(stock=S, price=100.0, cost=60.0)
    today = today_havana()

    async def _boom(*a, **k):
        raise RuntimeError("fallo transitorio antes del descuento de stock")

    monkeypatch.setattr(sinv, "apply_stock_idempotent", _boom)
    try:
        with pytest.raises(Exception):
            await pos_cobro(
                CobroIn(items=[CobroLine(product_id=pid, quantity=1)], paid=100),
                _admin_request())

        # El efecto NUNCA se aplicó: el reverso NO sobre-repone (no 11) ni crea
        # salida fantasma.
        assert await _stock(pid) == S
        assert await _fund_net(pid) == 0.0
        v = await db.inventory_movements.find_one(
            {"product_id": pid, "type": "venta"}, {"_id": 0})
        assert v["voided"] is True and v["cobro_aborted"] is True
        assert v["stock_apply_failed"] is True
        assert v.get("stock_applied") is not True
        # Reconstrucción por movimientos cuadra con el stock real.
        assert S + await _documented(pid) == await _stock(pid)
        # Excluida de ventas/ganancia.
        d = await build_dashboard(today, today, product_ids=[pid])
        assert d["units_sold"] == 0 and d["profit"] == 0.0

        # El recuperador general NO reactiva el efecto abortado.
        monkeypatch.undo()
        await heal_initializing_ops(max_age_seconds=-5)
        assert await _stock(pid) == S
        assert await _fund_net(pid) == 0.0

        # Repetir la recuperación no duplica nada.
        cid = v.get("cobro_id")
        await reverse_cobro(cid)
        await reverse_cobro(cid)
        assert await _stock(pid) == S
        assert await _fund_net(pid) == 0.0
    finally:
        await _cleanup(pid)


# ═══════ Variante 2 — stock aplicado pero el ingreso falló (absorbido) ══════
@pytest.mark.asyncio
async def test_r1_variant2_applied_without_inflow(monkeypatch):
    S = 10.0
    a = await _mk(stock=S, price=100.0, cost=60.0)
    b = await _mk(stock=S, price=200.0, cost=0.0)

    async def _noop_fund(mov):   # el ingreso de A no llega a registrarse
        return

    real_impl = rinv._create_movement_impl

    async def _fail_b(payload, request, actor, *, cobro_id=""):
        if payload.product_id == b:
            raise HTTPException(status_code=400, detail="fallo línea B")
        return await real_impl(payload, request, actor, cobro_id=cobro_id)

    monkeypatch.setattr(sinv, "_record_fund_flow", _noop_fund)
    monkeypatch.setattr(rinv, "_create_movement_impl", _fail_b)
    try:
        with pytest.raises(HTTPException):
            await pos_cobro(
                CobroIn(items=[CobroLine(product_id=a, quantity=1),
                               CobroLine(product_id=b, quantity=1)], paid=300),
                _admin_request())

        # A: stock aplicado y revertido; su ingreso NUNCA existió → sin salida
        # fantasma. Neto del fondo = 0.
        assert await _stock(a) == S
        assert await _stock(b) == S
        assert await _fund_net(a) == 0.0
        va = await db.inventory_movements.find_one(
            {"product_id": a, "type": "venta"}, {"_id": 0})
        assert va["voided"] is True and va["cobro_aborted"] is True
        assert va.get("stock_applied") is True
        assert S + await _documented(a) == await _stock(a)

        # El recuperador general NO reactiva el ingreso ausente de un cobro
        # abortado (antes el asiento 'perdido' se reponía → fondo +100).
        monkeypatch.undo()
        await heal_initializing_ops(max_age_seconds=-5)
        assert await _fund_net(a) == 0.0
        assert await _stock(a) == S
    finally:
        await _cleanup(a, b)


# ═══════ Camino normal — aplicado + ingreso: reverso exacto y coordinado ════
@pytest.mark.asyncio
async def test_r1_normal_applied_reversal_consistent_and_recoverer_safe():
    S = 10.0
    pid = await _mk(stock=S, price=100.0, cost=60.0)
    cid = str(uuid.uuid4())
    prod = await db.products.find_one({"id": pid}, {"_id": 0})
    try:
        await record_movement(product=prod, mtype="venta", quantity=1,
                              source="manual", cobro_id=cid, actor=ACTOR)
        assert await _stock(pid) == S - 1
        assert await _fund_net(pid) == 100.0   # ingreso registrado

        await reverse_cobro(cid)
        assert await _stock(pid) == S          # stock revertido (undone)
        assert await _fund_net(pid) == 0.0     # ingreso + salida = 0
        assert S + await _documented(pid) == await _stock(pid)

        # Recuperador general no duplica efectos.
        await heal_initializing_ops(max_age_seconds=-5)
        assert await _stock(pid) == S
        assert await _fund_net(pid) == 0.0

        # Idempotente.
        await reverse_cobro(cid)
        assert await _stock(pid) == S
        assert await _fund_net(pid) == 0.0
    finally:
        await _cleanup(pid)
