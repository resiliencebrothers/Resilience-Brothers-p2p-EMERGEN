"""iter351 — RV-02 / H03 (ALTA, residual): ORDEN EFECTIVO TRAS INTERRUPCIONES.

Los dos fallos residuales que esta iteración corrige:

Fallo A — caída ANTES de sellar la secuencia en stock_ops:
  La escritura atómica del producto ya aplicó stock/WAC y asignó la secuencia,
  pero el proceso muere antes de copiar op→seq a stock_ops. Al reintentar el
  mismo movimiento, el op se detecta aplicado y antes quedaba con effect_seq=None
  → el histórico lo colocaba ANTES de todo (infravaloración de 200 CUP).
  Fix: la relación op→seq se persiste en el MISMO commit atómico (effect_seq_log
  embebido en el producto) y el reintento la recupera de ahí.

Fallo B — caída DESPUÉS de sellar effect_seq en stock_ops, antes de sellar el
  movimiento. El recuperador general `heal_initializing_ops` marcaba
  stock_applied=True pero NO copiaba effect_seq al movimiento → misma
  infravaloración. Fix: el recuperador general también sella la secuencia
  (vía _effect_seq_for_op).

Controles que DEBEN seguir verdes (del auditor):
  - Entrada PAUSADA antes de aplicar + venta de 4 antes → 6 / 300 / 1.800.
  - Entrada ya aplicada + respuesta retrasada + venta de 4 → 6 / 260 / 1.560.

Escenario base de los fallos A y B:
  apertura 8 @ 200 · venta 4 (→ 4 @ 200) · entrada 2 @ 500 (→ 6 @ 300) ·
  venta posterior 1 (→ 5 @ 300). Valor histórico correcto = 5 × 300 = 1.500 CUP.
  Antes del fix: 5 × 260 = 1.300 CUP (desviación de 200 CUP).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import services.inventory as inv
from db_client import db
from auth_utils import now_utc, iso
from services.inventory import (record_movement, today_havana,
                                apply_stock_idempotent, _complete_pending_stock,
                                _effect_seq_for_op, _seq_from_log)
from services.inventory_ipv import register_audited_opening
from services.inventory_history import build_cutoff_report, _effect_order_key
from services.credit_recovery import heal_initializing_ops

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk_product(stock, cost):
    pid = f"TEST_IPV351_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 800.0,
        "cost_usd": float(cost), "stock": float(stock), "unit": "unidad",
        "is_active": True, "owner_id": ""})
    return pid


async def _cleanup(pid):
    await db.products.delete_many({"id": pid})
    await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_lots.delete_many({"product_id": pid})
    await db.inventory_counts.delete_many({"product_id": pid})
    await db.stock_ops.delete_many({"product_id": pid})


async def _p(pid):
    return await db.products.find_one({"id": pid}, {"_id": 0})


async def _row(pid):
    rep = await build_cutoff_report(today_havana())
    return next((r for r in rep["products"] if r["product_id"] == pid), None)


async def _open_and_sell4(pid):
    """apertura 8 @ 200 (apply_stock=False) + venta 4 → stock 4, WAC 200."""
    await register_audited_opening(pid, 200.0, "Apertura 351", ACTOR)
    await record_movement(product=await _p(pid), mtype="venta", quantity=4,
                          note="venta inicial", source="manual", actor=ACTOR)
    prod = await _p(pid)
    assert prod["stock"] == 4.0 and round(prod["cost_usd"], 2) == 200.0


async def _insert_pending_entrada(pid, qty, cost, created_at=None):
    """Inserta una ENTRADA registrada pero con el stock PENDIENTE (como la ruta
    record-first antes de aplicar el efecto)."""
    mid = str(uuid.uuid4())
    doc = {
        "id": mid, "product_id": pid, "product_name": pid, "type": "entrada",
        "quantity": float(qty), "unit": "unidad", "unit_price": 0.0,
        "unit_cost": float(cost), "total": round(cost * qty, 2),
        "cost_of_sale": 0.0, "profit": 0.0, "note": "entrada interrumpida",
        "source": "manual", "ref_id": "", "actor_id": ACTOR["user_id"],
        "actor_email": ACTOR["email"], "created_at": created_at or iso(now_utc()),
        "needs_stock": True, "stock_applied": False}
    await db.inventory_movements.insert_one(doc)
    return doc


# --------------------------------------------------------------------------
# FALLO A — caída antes de sellar stock_ops; reintento del mismo movimiento
# --------------------------------------------------------------------------
async def test_failure_a_retry_recovers_sequence_from_product_log():
    pid = await _mk_product(stock=8, cost=200)
    try:
        await _open_and_sell4(pid)
        entrada = await _insert_pending_entrada(pid, 2, 500)
        op = f"invmov:{entrada['id']}"

        # CAÍDA REAL en el punto de sellado: _stock_ops_mark_applied lanza, de
        # modo que la escritura atómica del producto YA ocurrió (stock 6, WAC
        # 300, par op→seq en el log embebido) pero stock_ops queda 'pending' y
        # el log NO se poda (la poda va después del sellado).
        real_mark = inv._stock_ops_mark_applied

        async def _boom(o, effect_seq=None):
            if o == op:
                raise RuntimeError("caída simulada antes de sellar stock_ops")
            return await real_mark(o, effect_seq=effect_seq)

        inv._stock_ops_mark_applied = _boom
        try:
            with pytest.raises(RuntimeError):
                await apply_stock_idempotent(pid, 2.0, op, require_available=False,
                                             cost_fold=(2.0, 500.0))
        finally:
            inv._stock_ops_mark_applied = real_mark

        prod = await _p(pid)
        assert prod["stock"] == 6.0 and round(prod["cost_usd"], 2) == 300.0
        seq_original = _seq_from_log(prod, op)
        assert seq_original is not None, "op→seq sobrevive en el log (sin podar)"
        rec = await db.stock_ops.find_one(
            {"op_id": op}, {"_id": 0, "effect_seq": 1, "state": 1})
        assert rec["state"] == "pending" and rec.get("effect_seq") is None

        # Operación POSTERIOR intercalada: venta de 1 (avanza el contador).
        await record_movement(product=await _p(pid), mtype="venta", quantity=1,
                              note="venta posterior", source="manual", actor=ACTOR)
        assert (await _p(pid))["stock"] == 5.0

        # REINTENTO del mismo movimiento (misma identidad / op_id).
        healed = await _complete_pending_stock(entrada)
        assert healed["stock_applied"] is True
        assert healed.get("effect_seq") == seq_original, \
            "la secuencia ORIGINAL se recupera del log embebido (no None)"
        assert not healed.get("effect_seq_uncertain")

        rec = await db.stock_ops.find_one(
            {"op_id": op}, {"_id": 0, "effect_seq": 1, "state": 1})
        assert rec["effect_seq"] == seq_original and rec["state"] == "applied"

        # Histórico: stock 5, WAC 300, valor 1.500 (NO 260 / 1.300).
        row = await _row(pid)
        assert row is not None
        assert row["final_stock"] == 5.0
        assert round(row["wac"], 2) == 300.0, f"WAC 300, got {row['wac']}"
        assert round(row["value"], 2) == 1500.0, f"valor 1500, got {row['value']}"
        assert row["coverage"] == "completa"
    finally:
        await _cleanup(pid)


# --------------------------------------------------------------------------
# FALLO B — caída después de sellar stock_ops; recuperador GENERAL
# --------------------------------------------------------------------------
async def test_failure_b_general_recoverer_seals_sequence():
    pid = await _mk_product(stock=8, cost=200)
    try:
        await _open_and_sell4(pid)
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
        entrada = await _insert_pending_entrada(pid, 2, 500, created_at=old_ts)
        op = f"invmov:{entrada['id']}"

        # Aplica stock/WAC Y sella stock_ops.effect_seq=N; pero el movimiento
        # queda SIN sellar (stock_applied=False) — la caída fue entre ambos.
        st = await apply_stock_idempotent(pid, 2.0, op, require_available=False,
                                          cost_fold=(2.0, 500.0))
        assert st == "applied"
        rec = await db.stock_ops.find_one({"op_id": op}, {"_id": 0, "effect_seq": 1})
        seq_sealed = rec["effect_seq"]
        assert seq_sealed is not None
        m = await db.inventory_movements.find_one({"id": entrada["id"]}, {"_id": 0})
        assert m.get("stock_applied") is not True  # el movimiento no se selló

        # Operación POSTERIOR intercalada.
        await record_movement(product=await _p(pid), mtype="venta", quantity=1,
                              note="venta posterior", source="manual", actor=ACTOR)
        assert (await _p(pid))["stock"] == 5.0

        # RECUPERADOR GENERAL (no el reintento del mismo movimiento).
        healed = await heal_initializing_ops(max_age_seconds=0)
        assert healed >= 1

        m = await db.inventory_movements.find_one({"id": entrada["id"]}, {"_id": 0})
        assert m["stock_applied"] is True
        assert m.get("effect_seq") == seq_sealed, \
            "el recuperador general copió la secuencia sellada en stock_ops"
        assert not m.get("effect_seq_uncertain")

        row = await _row(pid)
        assert row["final_stock"] == 5.0
        assert round(row["wac"], 2) == 300.0
        assert round(row["value"], 2) == 1500.0, f"valor 1500, got {row['value']}"
        assert row["coverage"] == "completa"
    finally:
        await _cleanup(pid)


# --------------------------------------------------------------------------
# op→seq se persiste en el commit atómico y se PODA tras el sellado duradero
# --------------------------------------------------------------------------
async def test_op_seq_pruned_after_durable_seal():
    pid = await _mk_product(stock=10, cost=200)
    try:
        op = f"test-op:{uuid.uuid4().hex[:8]}"
        # Caso NORMAL (sin caída): tras sellar en stock_ops, el par op→seq se
        # retira del log embebido (stock_ops es ya la fuente duradera).
        real_mark = inv._stock_ops_mark_applied

        async def _boom(o, effect_seq=None):
            if o == op:
                raise RuntimeError("caída antes de sellar")
            return await real_mark(o, effect_seq=effect_seq)

        # Primero demostramos que ANTES de sellar el par vive en el log.
        inv._stock_ops_mark_applied = _boom
        try:
            with pytest.raises(RuntimeError):
                await apply_stock_idempotent(pid, 3.0, op, require_available=False,
                                             cost_fold=(3.0, 400.0))
        finally:
            inv._stock_ops_mark_applied = real_mark
        prod = await _p(pid)
        assert _seq_from_log(prod, op) == prod["effect_seq"], "vive en el log sin sellar"
        assert await _effect_seq_for_op(pid, op) == prod["effect_seq"]

        # Al reintentar (sella de forma duradera), el par se PODA del log.
        st = await apply_stock_idempotent(pid, 3.0, op, require_available=False,
                                          cost_fold=(3.0, 400.0))
        assert st == "duplicate"
        prod = await _p(pid)
        assert _seq_from_log(prod, op) is None, "podado tras el sellado duradero"
        # Sigue siendo recuperable desde stock_ops (fuente duradera).
        assert await _effect_seq_for_op(pid, op) == prod["effect_seq"]
    finally:
        await _cleanup(pid)


# --------------------------------------------------------------------------
# Incertidumbre: sin evidencia reconstruible, NO se antepone a lo secuenciado
# --------------------------------------------------------------------------
async def test_unrecoverable_sequence_is_flagged_and_ordered_last():
    pid = await _mk_product(stock=8, cost=200)
    try:
        await _open_and_sell4(pid)
        entrada = await _insert_pending_entrada(pid, 2, 500)
        op = f"invmov:{entrada['id']}"
        await apply_stock_idempotent(pid, 2.0, op, require_available=False,
                                     cost_fold=(2.0, 500.0))
        # Pérdida TOTAL de evidencia del orden: ni stock_ops ni el log del
        # producto conservan la secuencia de este op.
        await db.stock_ops.update_one(
            {"op_id": op}, {"$set": {"state": "pending"},
                            "$unset": {"effect_seq": "", "applied_at": ""}})
        await db.products.update_one({"id": pid}, {"$set": {"effect_seq_log": []}})

        healed = await _complete_pending_stock(entrada)
        assert healed.get("effect_seq") is None
        assert healed.get("effect_seq_uncertain") is True, \
            "sin evidencia → se SEÑALA la incertidumbre"

        # El movimiento incierto NO debe anteponerse a los secuenciados.
        seq_key = _effect_order_key({"effect_seq": 5})
        legacy_key = _effect_order_key({"created_at": "2020-01-01"})
        uncertain_key = _effect_order_key(
            {"effect_seq_uncertain": True, "applied_at": "2026-01-01"})
        assert legacy_key[0] == 0   # heredado real → primero
        assert seq_key[0] == 1      # secuenciado → en medio
        assert uncertain_key[0] == 2  # incierto → al final, NO antes
    finally:
        await _cleanup(pid)


# --------------------------------------------------------------------------
# CONTROL 1 (debe seguir verde) — entrada PAUSADA antes de aplicar + venta antes
# --------------------------------------------------------------------------
async def test_control_entry_paused_before_apply_sale_first():
    pid = await _mk_product(stock=8, cost=200)
    try:
        await register_audited_opening(pid, 200.0, "Apertura", ACTOR)
        # Entrada 2 @ 500 PAUSADA (registrada, sin aplicar stock ni secuencia).
        entrada = await _insert_pending_entrada(pid, 2, 500)
        # Venta de 4 ocurre ANTES de que la entrada aplique.
        await record_movement(product=await _p(pid), mtype="venta", quantity=4,
                              note="venta antes", source="manual", actor=ACTOR)
        assert (await _p(pid))["stock"] == 4.0
        # Ahora SÍ aplica la entrada (recibe secuencia DESPUÉS de la venta).
        healed = await _complete_pending_stock(entrada)
        assert healed["stock_applied"] is True
        prod = await _p(pid)
        assert prod["stock"] == 6.0 and round(prod["cost_usd"], 2) == 300.0

        row = await _row(pid)
        assert row["final_stock"] == 6.0
        assert round(row["wac"], 2) == 300.0
        assert round(row["value"], 2) == 1800.0, f"valor 1800, got {row['value']}"
    finally:
        await _cleanup(pid)


# --------------------------------------------------------------------------
# CONTROL 2 (debe seguir verde) — entrada aplicada + respuesta retrasada
# --------------------------------------------------------------------------
async def test_control_entry_applied_then_delayed_response():
    pid = await _mk_product(stock=8, cost=200)
    try:
        await register_audited_opening(pid, 200.0, "Apertura", ACTOR)
        entrada = await record_movement(
            product=await _p(pid), mtype="entrada", quantity=2, unit_cost=500.0,
            note="compra", source="manual", actor=ACTOR)
        prod = await _p(pid)
        assert prod["stock"] == 10.0 and round(prod["cost_usd"], 2) == 260.0
        venta = await record_movement(
            product=await _p(pid), mtype="venta", quantity=4, note="venta",
            source="manual", actor=ACTOR)
        assert entrada["effect_seq"] < venta["effect_seq"]
        # Sellado TARDÍO de applied_at de la entrada (después de la venta).
        late = (datetime.fromisoformat(venta["applied_at"])
                + timedelta(minutes=5)).isoformat()
        await db.inventory_movements.update_one(
            {"id": entrada["id"]}, {"$set": {"applied_at": late}})

        row = await _row(pid)
        assert row["final_stock"] == 6.0
        assert round(row["wac"], 2) == 260.0
        assert round(row["value"], 2) == 1560.0, f"valor 1560, got {row['value']}"
        assert row["coverage"] == "completa"
    finally:
        await _cleanup(pid)
