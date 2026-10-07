"""iter350 — Recuperador Automático de ajustes de conteo físico (IPV).

Verifica que `recover_pending_count_adjustments()` completa, de forma idempotente,
ajustes que quedaron a medio aplicar tras una interrupción:
- `pending_apply`: el movimiento ya se registró pero el stock no se aplicó.
- `claiming` estancado: el claim quedó colgado (incluso antes de registrar el
  movimiento). No toca claims RECIENTES (autorización de admin en curso).
Nunca duplica el ajuste; conteos sin documento persistido (legacy) se omiten.
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from db_client import db
from auth_utils import now_utc, iso
from services.inventory import today_havana
from services.inventory_ipv import (record_physical_count,
                                     recover_pending_count_adjustments)

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk_product(stock=10.0, cost=200.0):
    pid = f"TEST_IPV350_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 500.0,
        "cost_usd": cost, "stock": stock, "unit": "unidad", "is_active": True})
    return pid


async def _cleanup(pid):
    await db.products.delete_many({"id": pid})
    await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_lots.delete_many({"product_id": pid})
    await db.inventory_counts.delete_many({"product_id": pid})
    await db.stock_ops.delete_many({"product_id": pid})
    await db.inventory_incidents.delete_many({"product_id": pid})


async def _stock(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
    return p["stock"]


async def _count(pid):
    return await db.inventory_counts.find_one({"product_id": pid}, {"_id": 0})


async def _inject_movement(pid, count_id, version, *, applied_stock):
    """Registra el movimiento de ajuste con el stock SIN aplicar (interrupción
    entre el log y la aplicación)."""
    mov_id = str(uuid.uuid4())
    await db.inventory_movements.insert_one({
        "id": mov_id, "product_id": pid, "product_name": pid,
        "type": "ajuste_neg", "quantity": 2.0, "unit": "unidad",
        "unit_price": 500.0, "unit_cost": 200.0, "total": 400.0,
        "cost_of_sale": 0.0, "profit": 0.0,
        "note": "Ajuste interrumpido", "photo_url": "", "source": "conteo",
        "ref_id": count_id, "actor_id": ACTOR["user_id"],
        "actor_email": ACTOR["email"],
        "created_at": iso(now_utc()),
        "dedupe_key": f"count-adjust:{count_id}:v{version}",
        "needs_stock": True, "stock_applied": bool(applied_stock)})
    return mov_id


async def _mk_counted(pid):
    """Crea un conteo 8 sobre stock 10 (diferencia -2 → ajuste_neg de 2).
    Relee de la BD para obtener `version` (se incrementa con $inc, no viaja en
    el doc devuelto por record_physical_count)."""
    c = await record_physical_count(
        {"id": pid, "name": pid, "stock": 10.0, "cost_usd": 200.0,
         "unit": "unidad"}, 8, ACTOR)
    assert c["difference"] == -2.0
    return await db.inventory_counts.find_one({"id": c["id"]}, {"_id": 0})


async def test_recovers_pending_apply():
    """pending_apply: movimiento ya registrado (stock sin aplicar). El
    recuperador completa el efecto: stock 8, un único ajuste, conteo ajustado."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await _mk_counted(pid)
        mov_id = await _inject_movement(pid, c["id"], c["version"],
                                        applied_stock=False)
        await db.inventory_counts.update_one(
            {"id": c["id"]},
            {"$set": {"auth_state": "pending_apply",
                      "adjustment_document": "DOC-350",
                      "adjustment_movement_id": mov_id,
                      "claimed_by": ACTOR["user_id"]}})
        assert await _stock(pid) == 10.0  # precondición: nada aplicado

        healed = await recover_pending_count_adjustments()

        assert healed >= 1
        assert await _stock(pid) == 8.0
        n_adj = await db.inventory_movements.count_documents(
            {"product_id": pid, "type": {"$in": ["ajuste_pos", "ajuste_neg"]}})
        assert n_adj == 1, "el ajuste no debe duplicarse"
        cnt = await _count(pid)
        assert cnt["authorized"] is True and cnt["status"] == "ajustado"
        assert cnt["auth_state"] == "authorized"
        assert cnt["adjustment_movement_id"] == mov_id
        assert cnt.get("recovered_at")
    finally:
        await _cleanup(pid)


async def test_recovers_stale_claiming_without_movement():
    """claiming estancado sin movimiento (crash antes de registrarlo): el
    recuperador crea el movimiento con el mismo dedupe_key y aplica el stock."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await _mk_counted(pid)
        old = iso(now_utc() - timedelta(seconds=180))
        await db.inventory_counts.update_one(
            {"id": c["id"]},
            {"$set": {"auth_state": "claiming", "claimed_at": old,
                      "claimed_by": ACTOR["user_id"],
                      "adjustment_document": "DOC-350B"}})

        healed = await recover_pending_count_adjustments()

        assert healed >= 1
        assert await _stock(pid) == 8.0
        cnt = await _count(pid)
        assert cnt["authorized"] is True and cnt["status"] == "ajustado"
        n_adj = await db.inventory_movements.count_documents(
            {"product_id": pid, "type": {"$in": ["ajuste_pos", "ajuste_neg"]}})
        assert n_adj == 1
    finally:
        await _cleanup(pid)


async def test_skips_fresh_claiming():
    """Un claim RECIENTE (admin autorizando ahora) NO debe tocarse."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await _mk_counted(pid)
        await db.inventory_counts.update_one(
            {"id": c["id"]},
            {"$set": {"auth_state": "claiming", "claimed_at": iso(now_utc()),
                      "claimed_by": ACTOR["user_id"],
                      "adjustment_document": "DOC-350C"}})

        healed = await recover_pending_count_adjustments()

        assert healed == 0
        assert await _stock(pid) == 10.0  # intacto
        cnt = await _count(pid)
        assert cnt.get("authorized") is not True
        assert cnt["auth_state"] == "claiming"
    finally:
        await _cleanup(pid)


async def test_skips_legacy_claiming_without_document():
    """Claim estancado SIN documento persistido (anterior a iter349) no se puede
    completar automáticamente: se deja para reintento manual."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await _mk_counted(pid)
        old = iso(now_utc() - timedelta(seconds=180))
        await db.inventory_counts.update_one(
            {"id": c["id"]},
            {"$set": {"auth_state": "claiming", "claimed_at": old,
                      "claimed_by": ACTOR["user_id"]}})

        healed = await recover_pending_count_adjustments()

        assert healed == 0
        assert await _stock(pid) == 10.0
        cnt = await _count(pid)
        assert cnt.get("authorized") is not True
    finally:
        await _cleanup(pid)


async def test_idempotent_second_run_noop():
    """Tras sanar un conteo, una segunda corrida no vuelve a tocarlo ni duplica."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await _mk_counted(pid)
        mov_id = await _inject_movement(pid, c["id"], c["version"],
                                        applied_stock=False)
        await db.inventory_counts.update_one(
            {"id": c["id"]},
            {"$set": {"auth_state": "pending_apply",
                      "adjustment_document": "DOC-350D",
                      "adjustment_movement_id": mov_id,
                      "claimed_by": ACTOR["user_id"]}})

        first = await recover_pending_count_adjustments()
        second = await recover_pending_count_adjustments()

        assert first >= 1
        assert second == 0
        assert await _stock(pid) == 8.0
        n_adj = await db.inventory_movements.count_documents(
            {"product_id": pid, "type": {"$in": ["ajuste_pos", "ajuste_neg"]}})
        assert n_adj == 1
    finally:
        await _cleanup(pid)


async def test_stays_pending_when_stock_insufficient():
    """Si el stock es insuficiente al recuperar un ajuste YA registrado
    (pending_apply), el conteo sigue pendiente (no se marca ajustado) para el
    siguiente ciclo."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await _mk_counted(pid)  # diff -2 → ajuste_neg de 2
        mov_id = await _inject_movement(pid, c["id"], c["version"],
                                        applied_stock=False)
        await db.inventory_counts.update_one(
            {"id": c["id"]},
            {"$set": {"auth_state": "pending_apply",
                      "adjustment_document": "DOC-350E",
                      "adjustment_movement_id": mov_id,
                      "claimed_by": ACTOR["user_id"]}})
        # Stock baja a 1 (insuficiente para restar 2) antes del recuperador.
        await db.products.update_one({"id": pid}, {"$set": {"stock": 1.0}})

        healed = await recover_pending_count_adjustments()

        assert healed == 0
        cnt = await _count(pid)
        assert cnt.get("authorized") is not True
        assert cnt["auth_state"] == "pending_apply"
        assert await _stock(pid) == 1.0  # nada aplicado
    finally:
        await _cleanup(pid)
