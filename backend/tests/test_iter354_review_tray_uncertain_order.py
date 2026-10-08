"""iter354 — Bandeja de Revisión: agrupar y RESOLVER movimientos con orden/
valoración incierta (`effect_seq_uncertain`) re-sellando su secuencia efectiva.

Escenario base para generar un movimiento incierto (como en iter353):
  apertura 8 @ 200 · venta 4 · entrada 2 @ 500 (interrumpida antes de sellar la
  secuencia; evidencia irrecuperable) · venta posterior 1. La entrada queda
  `effect_seq_uncertain=True`. Ordenada al final, el valor histórico es 1.600 CUP
  (sobrevaloración). Al RESOLVER colocándola tras la venta de 4, el orden efectivo
  correcto da 5 × 300 = 1.500 CUP y la cobertura vuelve a 'completa'.
"""
import uuid

import pytest

import services.inventory as inv
from db_client import db
from auth_utils import now_utc, iso
from services.inventory import (record_movement, today_havana,
                                apply_stock_idempotent, _complete_pending_stock)
from services.inventory_ipv import register_audited_opening
from services.inventory_history import (build_cutoff_report,
                                         list_uncertain_movements,
                                         uncertain_movement_timeline,
                                         resolve_uncertain_order)

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk_product(stock, cost):
    pid = f"TEST_IPV354_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": f"Prod {pid}", "category": "test", "price_usd": 800.0,
        "cost_usd": float(cost), "stock": float(stock), "unit": "unidad",
        "is_active": True, "owner_id": ""})
    return pid


async def _cleanup(*pids):
    for pid in pids:
        await db.products.delete_many({"id": pid})
        await db.inventory_movements.delete_many({"product_id": pid})
        await db.inventory_counts.delete_many({"product_id": pid})
        await db.stock_ops.delete_many({"product_id": pid})


async def _p(pid):
    return await db.products.find_one({"id": pid}, {"_id": 0})


async def _row(pid):
    rep = await build_cutoff_report(today_havana())
    row = next((r for r in rep["products"] if r["product_id"] == pid), None)
    return row, rep["totals"]


async def _make_uncertain_entrada(pid):
    """Deja una ENTRADA 2@500 marcada como incierta (evidencia de orden perdida).
    Devuelve el id del movimiento de la entrada incierta."""
    await register_audited_opening(pid, 200.0, "Apertura", ACTOR)
    await record_movement(product=await _p(pid), mtype="venta", quantity=4,
                          note="venta inicial", source="manual", actor=ACTOR)
    mid = str(uuid.uuid4())
    await db.inventory_movements.insert_one({
        "id": mid, "product_id": pid, "product_name": f"Prod {pid}",
        "type": "entrada", "quantity": 2.0, "unit": "unidad", "unit_price": 0.0,
        "unit_cost": 500.0, "total": 1000.0, "cost_of_sale": 0.0, "profit": 0.0,
        "note": "compra interrumpida", "source": "manual", "ref_id": "",
        "actor_id": ACTOR["user_id"], "actor_email": ACTOR["email"],
        "created_at": iso(now_utc()), "needs_stock": True, "stock_applied": False})
    entrada = await db.inventory_movements.find_one({"id": mid}, {"_id": 0})
    op = f"invmov:{mid}"
    # Aplica stock/WAC pero la caída ocurre en el sellado; luego se borra la
    # evidencia del orden (stock_ops + log) → irrecuperable.
    real_mark = inv._stock_ops_mark_applied

    async def _boom(o, effect_seq=None):
        if o == op:
            raise RuntimeError("caída antes de sellar")
        return await real_mark(o, effect_seq=effect_seq)

    inv._stock_ops_mark_applied = _boom
    try:
        with pytest.raises(RuntimeError):
            await apply_stock_idempotent(pid, 2.0, op, require_available=False,
                                         cost_fold=(2.0, 500.0))
    finally:
        inv._stock_ops_mark_applied = real_mark
    await db.stock_ops.update_one(
        {"op_id": op}, {"$set": {"state": "pending"},
                        "$unset": {"effect_seq": "", "applied_at": ""}})
    await db.products.update_one({"id": pid}, {"$set": {"effect_seq_log": []}})
    await record_movement(product=await _p(pid), mtype="venta", quantity=1,
                          note="venta posterior", source="manual", actor=ACTOR)
    healed = await _complete_pending_stock(entrada)
    assert healed.get("effect_seq_uncertain") is True
    return mid


# --------------------------------------------------------------------------
async def test_list_groups_uncertain_by_product():
    p1 = await _mk_product(8, 200)
    p2 = await _mk_product(8, 200)
    try:
        m1 = await _make_uncertain_entrada(p1)
        m2 = await _make_uncertain_entrada(p2)
        data = await list_uncertain_movements()
        mine = {g["product_id"]: g for g in data["products"]
                if g["product_id"] in (p1, p2)}
        assert set(mine) == {p1, p2}
        assert mine[p1]["movements"][0]["id"] == m1
        assert mine[p2]["movements"][0]["id"] == m2
        assert all(mv["effect_seq_uncertain"] for g in mine.values()
                   for mv in g["movements"])
    finally:
        await _cleanup(p1, p2)


async def test_timeline_marks_target_and_anchors():
    pid = await _mk_product(8, 200)
    try:
        mid = await _make_uncertain_entrada(pid)
        tl = await uncertain_movement_timeline(mid)
        rows = tl["timeline"]
        target = [r for r in rows if r["is_target"]]
        assert len(target) == 1 and target[0]["id"] == mid
        # El objetivo NO es ancla; las filas secuenciadas (apertura/ventas) sí.
        assert target[0]["anchor_eligible"] is False
        anchors = [r for r in rows if r["anchor_eligible"]]
        assert len(anchors) >= 2
        # El incierto va al FINAL del orden efectivo actual.
        assert rows[-1]["id"] == mid
    finally:
        await _cleanup(pid)


async def test_resolve_after_reference_fixes_valuation():
    pid = await _mk_product(8, 200)
    try:
        mid = await _make_uncertain_entrada(pid)
        # Antes: ordenada al final → sobrevaloración (1.600) y cobertura parcial.
        row, _ = await _row(pid)
        assert row["coverage"] == "parcial" and row["uncertain_valuation"] is True
        assert round(row["value"], 2) == 1600.0

        # Ancla = la venta de 4 (secuencia 2). La entrada debe quedar entre la
        # venta de 4 (2) y la venta posterior de 1 (4) → secuencia 3.
        tl = await uncertain_movement_timeline(mid)
        venta4 = next(r for r in tl["timeline"]
                      if r["type"] == "venta" and r["quantity"] == 4.0)
        res = await resolve_uncertain_order(mid, venta4["id"], ACTOR)
        assert res["effect_seq"] == 3.0
        assert res["resolved_by"] == ACTOR["email"]

        mov = await db.inventory_movements.find_one({"id": mid}, {"_id": 0})
        assert mov["effect_seq"] == 3.0
        assert mov.get("effect_seq_uncertain") is False
        assert mov.get("effect_seq_resolved_at")

        # Después: orden correcto → 5 × 300 = 1.500, cobertura completa.
        row, totals = await _row(pid)
        assert round(row["final_stock"], 3) == 5.0
        assert round(row["wac"], 2) == 300.0
        assert round(row["value"], 2) == 1500.0
        assert row["coverage"] == "completa"
        assert row["uncertain_valuation"] is False
        # Ya no aparece en la bandeja.
        data = await list_uncertain_movements()
        assert pid not in {g["product_id"] for g in data["products"]}
    finally:
        await _cleanup(pid)


async def test_resolve_at_beginning_assigns_lower_sequence():
    pid = await _mk_product(8, 200)
    try:
        mid = await _make_uncertain_entrada(pid)
        res = await resolve_uncertain_order(mid, None, ACTOR)  # al inicio
        # menor secuencia existente = 1 (apertura) → 1 - 0.5 = 0.5
        assert res["effect_seq"] == 0.5
        mov = await db.inventory_movements.find_one({"id": mid}, {"_id": 0})
        assert mov.get("effect_seq_uncertain") is False
    finally:
        await _cleanup(pid)


async def test_resolve_validations():
    pid = await _mk_product(8, 200)
    try:
        mid = await _make_uncertain_entrada(pid)
        # No existe
        with pytest.raises(ValueError):
            await resolve_uncertain_order("no-existe", None, ACTOR)
        # Referencia inválida (no secuenciada / otro producto)
        with pytest.raises(ValueError):
            await resolve_uncertain_order(mid, "ref-invalida", ACTOR)
        # Resolver OK y luego reintentar → ya no está incierto
        await resolve_uncertain_order(mid, None, ACTOR)
        with pytest.raises(ValueError):
            await resolve_uncertain_order(mid, None, ACTOR)
    finally:
        await _cleanup(pid)
