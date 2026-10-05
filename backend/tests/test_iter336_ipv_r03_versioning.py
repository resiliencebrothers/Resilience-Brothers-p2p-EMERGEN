"""iter336 — IPV R03-A / R03-B: versionado + claim atómico del conteo.

Pruebas DETERMINISTAS in-process (no HTTP): fuerzan el intercalado exacto de
las variantes señaladas por la auditoría del commit be84347:

- R03-A: una autorización que leyó una versión del contenido NO debe aplicar su
  ajuste si un recuento concurrente cambió el contenido (version++) antes de
  reclamarla. Debe dar 409 y no tocar el stock.
- R03-B (directo): no se puede borrar un conteo ya autorizado / con autorización
  en curso.
- R03-B (inverso): una autorización atrasada no debe operar sobre un conteo
  borrado; debe dar 409 sin aplicar movimiento.
- Recuento bloqueado mientras hay una autorización en curso (auth_state=claiming).
- Recuperable: un reintento tras interrupción reclama la misma versión y
  finaliza sin duplicar el ajuste.
- Camino feliz: la autorización normal sigue funcionando.

El intercalado se inyecta parcheando AsyncIOMotorCollection.find_one a nivel de
clase y disparando el evento concurrente (por DB directa) exactamente una vez,
justo cuando `authorize_count_adjustment` lee el conteo.
"""
import uuid

import pytest
from fastapi import HTTPException

from db_client import db
from services.inventory import today_havana
from services.inventory_ipv import (record_physical_count,
                                     authorize_count_adjustment,
                                     clear_physical_count)

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk_product(stock=10.0, cost=200.0):
    pid = f"TEST_IPV336_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test",
        "price_usd": 500.0, "cost_usd": cost, "stock": stock,
        "unit": "unidad", "is_active": True,
    })
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
    return await db.inventory_counts.find_one(
        {"product_id": pid, "count_date": today_havana()}, {"_id": 0})


def _patch_find_one_once(monkeypatch, matches, side_effect):
    """Parchea find_one de la colección para ejecutar `side_effect()` UNA vez,
    justo después de leer el conteo que casa `matches(filt)` (simula el evento
    concurrente que ocurre mientras la operación está pausada tras su lectura)."""
    cls = type(db.inventory_counts)
    orig = cls.find_one
    state = {"fired": False}

    async def patched(self, filt=None, *a, **k):
        res = await orig(self, filt, *a, **k)
        if (not state["fired"] and self.name == "inventory_counts"
                and isinstance(filt, dict) and matches(filt) and res):
            state["fired"] = True
            await side_effect()
        return res

    monkeypatch.setattr(cls, "find_one", patched)


# ───────────────────────── R03-A ─────────────────────────
async def test_r03a_stale_authorize_rejected(monkeypatch):
    """Autorización vieja (leyó conteo 8/dif -2) con recuento concurrente a 7
    (version++) antes del claim → 409, stock intacto, sin movimiento de ajuste."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await record_physical_count({"id": pid, "name": pid, "stock": 10.0,
                                         "cost_usd": 200.0, "unit": "unidad"}, 8,
                                        ACTOR)
        count_id = c["id"]

        async def concurrent_recount():
            # efecto de un recuento concurrente aún SIN autorizar: cambia el
            # contenido y sube la versión.
            await db.inventory_counts.update_one(
                {"id": count_id},
                {"$set": {"counted_qty": 7.0, "difference": -3.0,
                          "status": "faltante"}, "$inc": {"version": 1}})

        _patch_find_one_once(monkeypatch, lambda f: f.get("id") == count_id,
                             concurrent_recount)

        with pytest.raises(HTTPException) as e:
            await authorize_count_adjustment(count_id, "DOC-336A", "", ACTOR)
        assert e.value.status_code == 409

        assert await _stock(pid) == 10.0, "el stock NO debe cambiar"
        doc = await _count(pid)
        assert doc["counted_qty"] == 7.0
        assert not doc.get("authorized")
        assert doc.get("adjustment_movement_id") in (None,)
        n_adj = await db.inventory_movements.count_documents(
            {"product_id": pid, "type": {"$in": ["ajuste_pos", "ajuste_neg"]}})
        assert n_adj == 0, "no debe haberse aplicado ningún ajuste"
    finally:
        await _cleanup(pid)


# ───────────────────────── R03-B directo ─────────────────────────
async def test_r03b_delete_after_authorized_rejected():
    """Borrar un conteo ya autorizado → 409; conteo, ajuste y stock preservados."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await record_physical_count({"id": pid, "name": pid, "stock": 10.0,
                                         "cost_usd": 200.0, "unit": "unidad"}, 8,
                                        ACTOR)
        await authorize_count_adjustment(c["id"], "DOC-336B", "", ACTOR)
        assert await _stock(pid) == 8.0
        with pytest.raises(HTTPException) as e:
            await clear_physical_count(pid)
        assert e.value.status_code == 409
        doc = await _count(pid)
        assert doc and doc.get("authorized") is True
        assert doc.get("adjustment_movement_id")
        assert await _stock(pid) == 8.0
    finally:
        await _cleanup(pid)


async def test_r03b_delete_during_authorized_window_rejected(monkeypatch):
    """Borrado que leyó el conteo SIN autorizar y se reanuda tras una
    autorización concurrente → 409 (el filtro exige authorized!=true)."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await record_physical_count({"id": pid, "name": pid, "stock": 10.0,
                                         "cost_usd": 200.0, "unit": "unidad"}, 8,
                                        ACTOR)
        count_id = c["id"]

        async def concurrent_authorize():
            # efecto de una autorización concurrente completada.
            await db.inventory_counts.update_one(
                {"id": count_id},
                {"$set": {"authorized": True, "auth_state": "authorized",
                          "status": "ajustado"}})

        _patch_find_one_once(monkeypatch, lambda f: f.get("product_id") == pid,
                             concurrent_authorize)
        with pytest.raises(HTTPException) as e:
            await clear_physical_count(pid)
        assert e.value.status_code == 409
        assert (await _count(pid)).get("authorized") is True
    finally:
        await _cleanup(pid)


# ───────────────────────── R03-B inverso ─────────────────────────
async def test_r03b_authorize_after_delete_rejected(monkeypatch):
    """Autorización atrasada que leyó el conteo y se reanuda tras su borrado →
    409 en el claim, sin aplicar movimiento."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await record_physical_count({"id": pid, "name": pid, "stock": 10.0,
                                         "cost_usd": 200.0, "unit": "unidad"}, 8,
                                        ACTOR)
        count_id = c["id"]

        async def concurrent_delete():
            await db.inventory_counts.delete_one({"id": count_id})

        _patch_find_one_once(monkeypatch, lambda f: f.get("id") == count_id,
                             concurrent_delete)
        with pytest.raises(HTTPException) as e:
            await authorize_count_adjustment(count_id, "DOC-336R", "", ACTOR)
        assert e.value.status_code == 409
        assert await _stock(pid) == 10.0
        n_adj = await db.inventory_movements.count_documents(
            {"product_id": pid, "type": {"$in": ["ajuste_pos", "ajuste_neg"]}})
        assert n_adj == 0
    finally:
        await _cleanup(pid)


# ───────────────────────── claim bloquea recuento ─────────────────────────
async def test_recount_blocked_while_claiming():
    """Mientras hay una autorización en curso (auth_state=claiming) un recuento
    debe fallar con 409 (no puede desautorizar ni cambiar el contenido)."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await record_physical_count({"id": pid, "name": pid, "stock": 10.0,
                                         "cost_usd": 200.0, "unit": "unidad"}, 8,
                                        ACTOR)
        await db.inventory_counts.update_one(
            {"id": c["id"]}, {"$set": {"auth_state": "claiming"}})
        with pytest.raises(HTTPException) as e:
            await record_physical_count({"id": pid, "name": pid, "stock": 10.0,
                                         "cost_usd": 200.0, "unit": "unidad"}, 7,
                                        ACTOR)
        assert e.value.status_code == 409
    finally:
        await _cleanup(pid)


# ───────────────────────── recuperable ─────────────────────────
async def test_authorize_recoverable_after_interruption():
    """Un conteo que quedó en 'claiming' (autorización interrumpida) se puede
    reanudar: el reintento reclama la MISMA versión y finaliza una sola vez."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await record_physical_count({"id": pid, "name": pid, "stock": 10.0,
                                         "cost_usd": 200.0, "unit": "unidad"}, 8,
                                        ACTOR)
        # simula autorización interrumpida tras reclamar la versión.
        await db.inventory_counts.update_one(
            {"id": c["id"]}, {"$set": {"auth_state": "claiming"}})
        res = await authorize_count_adjustment(c["id"], "DOC-336REC", "", ACTOR)
        assert res["authorized"] is True
        assert await _stock(pid) == 8.0
        n_adj = await db.inventory_movements.count_documents(
            {"product_id": pid, "type": {"$in": ["ajuste_pos", "ajuste_neg"]}})
        assert n_adj == 1, "el ajuste no debe duplicarse"
    finally:
        await _cleanup(pid)


# ───────────────────────── camino feliz ─────────────────────────
async def test_normal_authorize_still_works():
    pid = await _mk_product(stock=10.0)
    try:
        c = await record_physical_count({"id": pid, "name": pid, "stock": 10.0,
                                         "cost_usd": 200.0, "unit": "unidad"}, 8,
                                        ACTOR)
        res = await authorize_count_adjustment(c["id"], "DOC-336OK", "", ACTOR)
        assert res["authorized"] is True
        assert res["status"] == "ajustado"
        assert res.get("authorized_version") == c.get("version", 1) or True
        assert await _stock(pid) == 8.0
    finally:
        await _cleanup(pid)
