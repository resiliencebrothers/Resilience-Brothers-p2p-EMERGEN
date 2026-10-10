"""SUN-08 — El reverso del carrito POS debe neutralizar venta + ingreso +
ganancia + stock (no solo reponer stock).

Bug: `POST /admin/pos/cobro` registra cada línea con `create_movement`, que
aplica stock Y contabiliza el ingreso/ganancia. Si una línea posterior fallaba,
el reverso anterior sólo reponía stock (un `ajuste_pos` con total=0): la venta y
su ingreso en `company_fund_adjustments` seguían contando en el cierre diario.

Estos tests corren EN PROCESO sobre productos desechables (idempotentes entre
corridas, sin depender del servidor vivo ni agotar el stock de productos
compartidos). Cubren el criterio de cierre:
  - Forzar un fallo tras la primera línea → verificar JUNTOS stock, movimientos
    efectivos, fondo, ventas del cierre y ganancia.
  - El cobro rechazado NO aporta ingresos ni utilidades.
  - Repetir la recuperación NO duplica el reverso.
  - Consolidar líneas repetidas ANTES de validar stock.
"""
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from db_client import db
from services.inventory import (record_movement, reverse_cobro,
                                build_dashboard, today_havana)
import routes.inventory as inv_mod
from routes.pos import pos_cobro, CobroIn, CobroLine
from tests.conftest import ADMIN_TOKEN

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk(stock=10.0, price=100.0, cost=60.0, unit="unidad"):
    pid = f"TEST_SUN08_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": price,
        "cost_usd": cost, "stock": stock, "unit": unit, "is_active": True})
    return pid


async def _stock(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
    return float((p or {}).get("stock") or 0)


async def _cleanup(*pids):
    for pid in pids:
        movs = await db.inventory_movements.find(
            {"product_id": pid}, {"_id": 0, "id": 1, "cobro_id": 1}).to_list(5000)
        mov_ids = [m["id"] for m in movs]
        cobro_ids = [m.get("cobro_id") for m in movs if m.get("cobro_id")]
        await db.company_fund_adjustments.delete_many({"ref_id": {"$in": mov_ids}})
        await db.inventory_movements.delete_many({"product_id": pid})
        await db.products.delete_many({"id": pid})
        await db.inventory_lots.delete_many({"product_id": pid})
        if cobro_ids:
            await db.pos_cobros.delete_many({"id": {"$in": cobro_ids}})


def _admin_request():
    """Request mínimo autenticado como admin (sesión sembrada por conftest)."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/admin/pos/cobro",
        "raw_path": b"/api/admin/pos/cobro",
        "query_string": b"",
        "headers": [(b"authorization", f"Bearer {ADMIN_TOKEN}".encode())],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 12345),
    }
    return Request(scope)


# ═══════════════ 1) Reverso a nivel de servicio (venta ya cobrada) ═══════════
@pytest.mark.asyncio
async def test_reverse_cobro_neutralizes_sale_income_profit_and_stock():
    pid = await _mk(stock=10.0, price=100.0, cost=60.0)
    today = today_havana()
    cobro_id = str(uuid.uuid4())
    prod = await db.products.find_one({"id": pid}, {"_id": 0})
    try:
        mov = await record_movement(product=prod, mtype="venta", quantity=1,
                                    source="manual", cobro_id=cobro_id,
                                    actor=ACTOR)
        mid = mov["id"]
        # La venta cuenta: stock −1, ingreso al fondo, ganancia en el dashboard.
        assert await _stock(pid) == 9.0
        inflow = await db.company_fund_adjustments.find_one(
            {"ref_id": mid, "adjustment_type": "inflow"}, {"_id": 0})
        assert inflow and inflow["amount"] == 100.0
        d = await build_dashboard(today, today, product_ids=[pid])
        assert d["units_sold"] == 1 and d["sales_revenue"] == 100.0 and d["profit"] == 40.0

        # ── Reverso ──
        n = await reverse_cobro(cobro_id, ACTOR)
        assert n == 1
        # Stock repuesto.
        assert await _stock(pid) == 10.0
        # Venta ANULADA (ya no cuenta como venta efectiva).
        voided = await db.inventory_movements.find_one({"id": mid}, {"_id": 0})
        assert voided.get("voided") is True
        assert voided.get("void_reason") == "cobro_reversal"
        # Ingreso al fondo compensado con un outflow idéntico (neto 0).
        outflow = await db.company_fund_adjustments.find_one(
            {"dedupe_key": f"cobro-rev-fund:{mid}"}, {"_id": 0})
        assert outflow and outflow["adjustment_type"] == "outflow" and outflow["amount"] == 100.0
        # El dashboard ya NO suma ni ingresos ni ganancia.
        d2 = await build_dashboard(today, today, product_ids=[pid])
        assert d2["units_sold"] == 0 and d2["sales_revenue"] == 0.0 and d2["profit"] == 0.0

        # ── Idempotencia: repetir la recuperación NO duplica el reverso ──
        await reverse_cobro(cobro_id, ACTOR)
        await reverse_cobro(cobro_id, ACTOR)
        assert await _stock(pid) == 10.0
        outs = await db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"cobro-rev-fund:{mid}"})
        assert outs == 1
        rev_movs = await db.inventory_movements.count_documents(
            {"ref_id": mid, "type": "ajuste_pos", "source": "cobro_reversal"})
        assert rev_movs == 1
    finally:
        await _cleanup(pid)


# ═══════════════ 2) Fallo tras la primera línea → reverso ENTERO ════════════
@pytest.mark.asyncio
async def test_pos_cobro_failure_after_first_line_reverts_whole_operation(monkeypatch):
    a = await _mk(stock=10.0, price=100.0, cost=60.0)
    b = await _mk(stock=10.0, price=200.0, cost=0.0)
    today = today_havana()
    real_impl = inv_mod._create_movement_impl
    calls = {"n": 0}

    async def _flaky_impl(payload, request, actor, *, cobro_id=""):
        calls["n"] += 1
        if calls["n"] == 1:                       # línea A: se registra OK
            return await real_impl(payload, request, actor, cobro_id=cobro_id)
        raise HTTPException(status_code=400,      # línea B: carrera de stock
                            detail="simulated race on line B")

    monkeypatch.setattr(inv_mod, "_create_movement_impl", _flaky_impl)
    try:
        payload = CobroIn(items=[CobroLine(product_id=a, quantity=1),
                                 CobroLine(product_id=b, quantity=1)], paid=300)
        with pytest.raises(HTTPException):
            await pos_cobro(payload, _admin_request())

        # La venta de A se registró y luego se revirtió ENTERA.
        assert await _stock(a) == 10.0            # stock repuesto
        assert await _stock(b) == 10.0            # B nunca se tocó
        venta_a = await db.inventory_movements.find_one(
            {"product_id": a, "type": "venta"}, {"_id": 0})
        assert venta_a and venta_a.get("voided") is True
        mid = venta_a["id"]
        # Ingreso compensado (neto 0).
        inflow = await db.company_fund_adjustments.find_one(
            {"ref_id": mid, "adjustment_type": "inflow"}, {"_id": 0})
        outflow = await db.company_fund_adjustments.find_one(
            {"dedupe_key": f"cobro-rev-fund:{mid}"}, {"_id": 0})
        assert inflow and outflow and inflow["amount"] == outflow["amount"]
        # Ni ingresos ni ganancia del cobro rechazado en el dashboard.
        d = await build_dashboard(today, today, product_ids=[a])
        assert d["units_sold"] == 0 and d["sales_revenue"] == 0.0 and d["profit"] == 0.0
        # La operación de cobro quedó marcada como revertida.
        cobro = await db.pos_cobros.find_one(
            {"id": venta_a.get("cobro_id")}, {"_id": 0})
        assert cobro and cobro["state"] == "reversed"
    finally:
        await _cleanup(a, b)


# ═══════════════ 3) Consolidación de líneas repetidas (dentro de stock) ══════
@pytest.mark.asyncio
async def test_pos_cobro_consolidates_duplicate_lines():
    pid = await _mk(stock=5.0, price=100.0, cost=60.0)
    try:
        payload = CobroIn(items=[CobroLine(product_id=pid, quantity=2),
                                 CobroLine(product_id=pid, quantity=1)],
                          paid=99_999)
        result = await pos_cobro(payload, _admin_request())
        # Dos líneas del mismo producto → UN solo movimiento de venta.
        assert len(result["movements"]) == 1
        assert result["movements"][0]["quantity"] == 3.0
        assert result["total"] == 300.0
        assert await _stock(pid) == 2.0
        ventas = await db.inventory_movements.count_documents(
            {"product_id": pid, "type": "venta"})
        assert ventas == 1
    finally:
        await _cleanup(pid)


# ═══════════════ 4) Líneas repetidas que exceden stock → rechazo limpio ══════
@pytest.mark.asyncio
async def test_pos_cobro_duplicate_lines_exceeding_stock_rejected_cleanly():
    pid = await _mk(stock=1.0, price=100.0, cost=60.0)
    try:
        # Cada línea 1u pasa individualmente (stock=1), pero consolidadas = 2u.
        payload = CobroIn(items=[CobroLine(product_id=pid, quantity=1),
                                 CobroLine(product_id=pid, quantity=1)],
                          paid=99_999)
        with pytest.raises(HTTPException) as ei:
            await pos_cobro(payload, _admin_request())
        assert ei.value.status_code == 400
        assert "stock" in str(ei.value.detail).lower()
        # Sin cobro parcial: stock intacto, ninguna venta registrada.
        assert await _stock(pid) == 1.0
        ventas = await db.inventory_movements.count_documents(
            {"product_id": pid, "type": "venta"})
        assert ventas == 0
    finally:
        await _cleanup(pid)
