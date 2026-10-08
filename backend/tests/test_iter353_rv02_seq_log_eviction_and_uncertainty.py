"""iter353 — RV-02 (MEDIA, residual): compactación por EVIDENCIA + incertidumbre
expuesta en el reporte.

Dos problemas residuales que esta iteración corrige:

(1) EVICCIÓN PREMATURA del effect_seq_log. `_seq_log_expr` capaba el log con
    `$slice: -1000`. Si una entrada se interrumpía ANTES de sellar su secuencia
    en stock_ops y después llegaban ≥1.000 operaciones, el par op→seq de la
    entrada pendiente salía del log aunque NO tuviera copia duradera → al
    recuperar quedaba effect_seq=None y el WAC histórico resultaba incorrecto
    (350 en vez de 300; 1.400 en vez de 1.200 CUP).
    Fix: la poda del log se basa en EVIDENCIA duradera — el par op→seq se retira
    SOLO cuando ya quedó sellado en stock_ops (`_prune_seq_log`). Así el log solo
    retiene secuencias aún sin sellar y el $slice jamás expulsa evidencia
    pendiente, por muchas operaciones posteriores que lleguen.

(2) EL REPORTE NO EXPONÍA LA INCERTIDUMBRE. Cuando un orden antiguo era
    irreconstruible, el movimiento quedaba `effect_seq_uncertain=True` y se
    ordenaba al final, pero la fila del reporte seguía diciendo
    coverage='completa'. Fix: la incertidumbre se traslada al reporte —
    coverage='parcial', campo `uncertain_valuation=True` y
    `totals.uncertain_count`.
"""
import uuid
from datetime import timedelta

import pytest

import services.inventory as inv
from db_client import db
from auth_utils import now_utc, iso
from services.inventory import (record_movement, today_havana,
                                apply_stock_idempotent, _complete_pending_stock,
                                _seq_from_log, EFFECT_SEQ_LOG_CAP)
from services.inventory_ipv import register_audited_opening
from services.inventory_history import build_cutoff_report

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk_product(stock, cost, unit="libra"):
    pid = f"TEST_IPV353_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 800.0,
        "cost_usd": float(cost), "stock": float(stock), "unit": unit,
        "is_active": True, "owner_id": ""})
    return pid


async def _cleanup(pid):
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


async def _insert_pending_entrada(pid, qty, cost, unit="libra"):
    mid = str(uuid.uuid4())
    await db.inventory_movements.insert_one({
        "id": mid, "product_id": pid, "product_name": pid, "type": "entrada",
        "quantity": float(qty), "unit": unit, "unit_price": 0.0,
        "unit_cost": float(cost), "total": round(cost * qty, 2),
        "cost_of_sale": 0.0, "profit": 0.0, "note": "entrada interrumpida",
        "source": "manual", "ref_id": "", "actor_id": ACTOR["user_id"],
        "actor_email": ACTOR["email"], "created_at": iso(now_utc()),
        "needs_stock": True, "stock_applied": False})
    return await db.inventory_movements.find_one({"id": mid}, {"_id": 0})


async def _crash_apply_entrada(pid, op, qty, cost):
    """Aplica el stock/WAC de la entrada pero FALLA justo en el sellado de
    stock_ops: la escritura atómica del producto ocurre (y deja el par op→seq
    en el log), pero stock_ops queda 'pending' y el log NO se poda."""
    real_mark = inv._stock_ops_mark_applied

    async def _boom(o, effect_seq=None):
        if o == op:
            raise RuntimeError("caída simulada antes de sellar stock_ops")
        return await real_mark(o, effect_seq=effect_seq)

    inv._stock_ops_mark_applied = _boom
    try:
        with pytest.raises(RuntimeError):
            await apply_stock_idempotent(pid, float(qty), op,
                                         require_available=False,
                                         cost_fold=(float(qty), float(cost)))
    finally:
        inv._stock_ops_mark_applied = real_mark


# --------------------------------------------------------------------------
# (1) EVICCIÓN — con 1.000+ operaciones posteriores y el LÍMITE REAL vigente,
#     la secuencia pendiente SOBREVIVE y el valor histórico es 4 × 300 = 1.200
# --------------------------------------------------------------------------
async def test_pending_sequence_survives_cap_with_1000_later_ops():
    assert EFFECT_SEQ_LOG_CAP == 1000  # límite real, sin reducir
    pid = await _mk_product(stock=8, cost=200, unit="libra")
    try:
        await register_audited_opening(pid, 200.0, "Apertura lb", ACTOR)
        await record_movement(product=await _p(pid), mtype="venta", quantity=4,
                              note="venta inicial", source="manual", actor=ACTOR)
        assert (await _p(pid))["stock"] == 4.0

        entrada = await _insert_pending_entrada(pid, 2, 500, unit="libra")
        op = f"invmov:{entrada['id']}"
        await _crash_apply_entrada(pid, op, 2, 500)  # stock 6, WAC 300, log con op→seq
        prod = await _p(pid)
        assert prod["stock"] == 6.0 and round(prod["cost_usd"], 2) == 300.0
        seq_original = _seq_from_log(prod, op)
        assert seq_original is not None

        await record_movement(product=await _p(pid), mtype="venta", quantity=1,
                              note="venta posterior", source="manual", actor=ACTOR)
        assert (await _p(pid))["stock"] == 5.0

        # 1.000 ventas de 0,001 lb mediante la función original: 1.000 appends
        # (cada uno auto-podado tras sellar) que SUPERAN el límite del log.
        prod_lb = await _p(pid)
        for _ in range(1000):
            await record_movement(product=prod_lb, mtype="venta", quantity=0.001,
                                  note="micro", source="manual", actor=ACTOR)
        assert round((await _p(pid))["stock"], 3) == 4.0

        # La secuencia de la entrada pendiente SIGUE en el log (no fue evictada).
        assert _seq_from_log(await _p(pid), op) == seq_original, \
            "la compactación por evidencia conserva la secuencia aún sin sellar"

        # Reintento: recupera la secuencia original → valoración correcta.
        healed = await _complete_pending_stock(entrada)
        assert healed.get("effect_seq") == seq_original
        assert not healed.get("effect_seq_uncertain")

        row, _ = await _row(pid)
        assert round(row["final_stock"], 3) == 4.0
        assert round(row["wac"], 2) == 300.0, f"WAC 300, got {row['wac']}"
        assert round(row["value"], 2) == 1200.0, f"valor 1200, got {row['value']}"
        assert row["coverage"] == "completa"
        assert row["uncertain_valuation"] is False
    finally:
        await _cleanup(pid)


# --------------------------------------------------------------------------
# (2) INCERTIDUMBRE EXPUESTA — evidencia irrecuperable → el reporte señala
#     coverage='parcial' + uncertain_valuation; coverage='completa' NO es válido
# --------------------------------------------------------------------------
async def test_report_surfaces_uncertain_valuation_when_evidence_lost():
    pid = await _mk_product(stock=8, cost=200, unit="libra")
    try:
        await register_audited_opening(pid, 200.0, "Apertura lb", ACTOR)
        await record_movement(product=await _p(pid), mtype="venta", quantity=4,
                              note="venta inicial", source="manual", actor=ACTOR)

        entrada = await _insert_pending_entrada(pid, 2, 500, unit="libra")
        op = f"invmov:{entrada['id']}"
        await _crash_apply_entrada(pid, op, 2, 500)

        # PÉRDIDA TOTAL de evidencia del orden (p. ej. caída catastrófica o dato
        # heredado): ni stock_ops ni el log embebido conservan la secuencia.
        await db.stock_ops.update_one(
            {"op_id": op}, {"$set": {"state": "pending"},
                            "$unset": {"effect_seq": "", "applied_at": ""}})
        await db.products.update_one({"id": pid}, {"$set": {"effect_seq_log": []}})

        await record_movement(product=await _p(pid), mtype="venta", quantity=1,
                              note="venta posterior", source="manual", actor=ACTOR)

        healed = await _complete_pending_stock(entrada)
        assert healed.get("effect_seq") is None
        assert healed.get("effect_seq_uncertain") is True

        row, totals = await _row(pid)
        assert row["coverage"] == "parcial", \
            "coverage='completa' NO es aceptable con valoración incierta"
        assert row["uncertain_valuation"] is True
        assert totals["uncertain_count"] >= 1
    finally:
        await _cleanup(pid)
