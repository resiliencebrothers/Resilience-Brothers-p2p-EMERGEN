"""iter350b — RV-03 / H04 (ALTA): un corte incompleto NO puede volverse completo
por el paso del tiempo.

Bug del auditor: `base_gap` solo se calculaba cuando el corte era VIGENTE (hoy);
para cortes pasados se forzaba a 0 y la ausencia de saldo negativo se reinterpretaba
como cobertura completa. Así, un corte que hoy es 'parcial' aparecía 'completa' al
día siguiente, y la evidencia de la base sin documentar desaparecía.

Fix: la base sin documentar es un INVARIANTE del producto en el tiempo
    base_gap = existencia_real − existencia_documentada_total (+ aperturas posteriores)
No depende de que el corte sea vigente; documentar una apertura auditada deja
explícito DESDE CUÁNDO el histórico es fiable (campo `reliable_from`).

Casos: paso de jornada (parcial sigue parcial), apertura auditada posterior
(real), apertura a media historia (períodos anteriores siguen parciales) y
producto totalmente documentado (completa en todo corte).
"""
import uuid

import pytest

from db_client import db
from auth_utils import now_utc, iso
from services.inventory import today_havana
from services.inventory_history import build_cutoff_report
from services.inventory_ipv import register_audited_opening

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk(stock, cost=20.0):
    pid = f"TEST_IPV350B_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 40.0,
        "cost_usd": cost, "stock": float(stock), "unit": "unidad",
        "is_active": True, "owner_id": ""})
    return pid


async def _mov(pid, mtype, qty, unit_cost=20.0, created_at=None, source="manual"):
    await db.inventory_movements.insert_one({
        "id": str(uuid.uuid4()), "product_id": pid, "product_name": pid,
        "type": mtype, "quantity": float(qty), "unit": "unidad",
        "unit_price": 0.0, "unit_cost": float(unit_cost),
        "total": float(qty) * float(unit_cost), "cost_of_sale": 0.0,
        "profit": 0.0, "note": "", "source": source, "ref_id": "",
        "actor_id": "", "actor_email": "",
        "created_at": created_at or iso(now_utc())})


async def _cleanup(pid):
    await db.products.delete_many({"id": pid})
    await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_lots.delete_many({"product_id": pid})
    await db.inventory_counts.delete_many({"product_id": pid})
    await db.stock_ops.delete_many({"product_id": pid})


async def _row(pid, cutoff=None):
    rep = await build_cutoff_report(cutoff or today_havana())
    return next((r for r in rep["products"] if r["product_id"] == pid), None)


async def test_day_passage_keeps_partial():
    """Paso de jornada: el mismo producto con base sin documentar sigue PARCIAL
    tanto consultando el corte pasado como el corte vigente (hoy). La marca no
    desaparece por cambiar la fecha actual."""
    pid = await _mk(stock=12)
    try:
        # Solo 2 documentadas (en el pasado); faltan 10 de base sin origen.
        await _mov(pid, "entrada", 2, created_at="2026-01-05T10:00:00+00:00")

        past = await _row(pid, cutoff="2026-01-05")   # corte pasado
        today = await _row(pid, cutoff=today_havana())  # corte vigente

        for row, label in ((past, "pasado"), (today, "vigente")):
            assert row is not None, label
            assert row["coverage"] == "parcial", label
            assert row["undocumented_base"] is True, label
            assert row["base_gap"] == 10.0, label
            assert row["reliable_from"] is None, label
        # El pasado no se rellena con la existencia de hoy.
        assert past["final_stock"] == 2.0
    finally:
        await _cleanup(pid)


async def test_audited_opening_makes_reliable_from_its_date():
    """Apertura auditada REAL (register_audited_opening, fechada hoy): el corte
    de hoy pasa a COMPLETA y `reliable_from` queda fijado a su fecha; un corte
    ANTERIOR a la apertura sigue PARCIAL."""
    pid = await _mk(stock=12)
    try:
        await _mov(pid, "entrada", 2, created_at="2026-02-05T10:00:00+00:00")
        # Antes de documentar: parcial en el pasado y hoy.
        before = await _row(pid, cutoff=today_havana())
        assert before["coverage"] == "parcial" and before["base_gap"] == 10.0

        res = await register_audited_opening(pid, None, "", ACTOR)
        assert res["opening_qty"] == 10.0

        today_row = await _row(pid, cutoff=today_havana())
        assert today_row["coverage"] == "completa"
        assert today_row["undocumented_base"] is False
        assert today_row["base_gap"] == 0.0
        assert today_row["reliable_from"] == today_havana()

        # Un corte ANTERIOR a la apertura (que es de hoy) sigue parcial.
        past_row = await _row(pid, cutoff="2026-02-05")
        assert past_row["coverage"] == "parcial"
        assert past_row["base_gap"] == 10.0
        assert past_row["reliable_from"] is None
    finally:
        await _cleanup(pid)


async def test_mid_history_opening_prior_periods_stay_partial():
    """Apertura auditada fechada a MEDIA historia: el corte en/después de la
    apertura es COMPLETA (reliable_from = su fecha); los cortes ANTERIORES siguen
    PARCIALES porque en esa fecha la base aún no estaba documentada."""
    pid = await _mk(stock=12)
    try:
        await _mov(pid, "entrada", 2, created_at="2026-03-01T10:00:00+00:00")
        # Apertura auditada que documenta la base, fechada el 2026-03-10.
        await _mov(pid, "entrada", 10, unit_cost=20.0,
                   created_at="2026-03-10T09:00:00+00:00",
                   source="apertura_auditada")

        prior = await _row(pid, cutoff="2026-03-05")  # antes de la apertura
        assert prior["coverage"] == "parcial"
        assert prior["base_gap"] == 10.0
        assert prior["final_stock"] == 2.0
        assert prior["reliable_from"] is None

        on_day = await _row(pid, cutoff="2026-03-10")  # día de la apertura
        assert on_day["coverage"] == "completa"
        assert on_day["undocumented_base"] is False
        assert on_day["base_gap"] == 0.0
        assert on_day["final_stock"] == 12.0
        assert on_day["reliable_from"] == "2026-03-10"

        after = await _row(pid, cutoff="2026-03-20")  # después
        assert after["coverage"] == "completa"
        assert after["base_gap"] == 0.0
    finally:
        await _cleanup(pid)


async def test_fully_documented_is_complete_at_any_cutoff():
    """Producto creado correctamente (alta documentada): COMPLETA en cualquier
    corte pasado o vigente; `reliable_from` = su primer movimiento."""
    pid = await _mk(stock=10)
    try:
        await _mov(pid, "entrada", 10, created_at="2026-04-02T08:00:00+00:00")
        for cut in ("2026-04-02", "2026-04-15", today_havana()):
            row = await _row(pid, cutoff=cut)
            assert row is not None, cut
            assert row["coverage"] == "completa", cut
            assert row["undocumented_base"] is False, cut
            assert row["base_gap"] == 0.0, cut
            assert row["reliable_from"] == "2026-04-02", cut
    finally:
        await _cleanup(pid)
