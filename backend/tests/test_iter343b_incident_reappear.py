"""iter343 — H07 (ALTA): una diferencia que reaparece NO debe quedar resuelta.

Bug del auditor (Fase 3, services/inventory_incidents.py): el conteo reutiliza
su id al recontar la misma jornada, así que la incidencia de 'diferencia' usa
un dedupe_key fijo. Secuencia 8 → 10 → 7 (stock 10, sin autorizar ajuste):
  - contar 8  → diferencia −2 abierta.
  - contar 10 → se auto-resuelve (cuadra).
  - contar 7  → diferencia −3, PERO `_upsert_incident` veía la incidencia ya
    resuelta y no reabría ni creaba sucesor → quedaba 1 resuelta y 0 abiertas.

Fix (modelo de episodios): al reaparecer la causa se crea un episodio SUCESOR
abierto, enlazado al resuelto (predecessor_id), conservando la evidencia previa.
La secuencia debe terminar con −3 visible como pendiente y las tres
observaciones trazables (ep1: 8→10, ep2: 7).
"""
import uuid

import pytest

from db_client import db
from services.inventory_ipv import record_physical_count
from services.inventory_incidents import incident_summary

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk(stock=10.0, cost=20.0, unit="libra"):
    pid = f"TEST_IPV343B_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 40.0,
        "cost_usd": cost, "stock": stock, "unit": unit, "is_active": True})
    return pid


async def _cleanup(pid):
    await db.products.delete_many({"id": pid})
    await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_lots.delete_many({"product_id": pid})
    await db.inventory_counts.delete_many({"product_id": pid})
    await db.inventory_incidents.delete_many({"product_id": pid})


async def _diff_incidents(pid):
    return await db.inventory_incidents.find(
        {"product_id": pid, "type": "diferencia"}, {"_id": 0}).sort(
        "episode", 1).to_list(50)


async def _prod(pid):
    return await db.products.find_one({"id": pid}, {"_id": 0})


async def test_reappearing_difference_opens_successor_episode():
    pid = await _mk(stock=10.0, cost=20.0)
    try:
        # 8 → diferencia −2 abierta
        await record_physical_count(await _prod(pid), 8.0, ACTOR)
        incs = await _diff_incidents(pid)
        assert len(incs) == 1 and incs[0]["status"] == "pendiente"
        assert incs[0]["episode"] == 1 and incs[0]["amount"] == -40.0

        # 10 → cuadra, se auto-resuelve
        await record_physical_count(await _prod(pid), 10.0, ACTOR)
        incs = await _diff_incidents(pid)
        assert len(incs) == 1 and incs[0]["status"] == "resuelta"
        assert incs[0]["auto_resolved"] is True

        # 7 → reaparece: debe abrir un episodio SUCESOR, no quedar sin abiertas
        await record_physical_count(await _prod(pid), 7.0, ACTOR)
        incs = await _diff_incidents(pid)
        assert len(incs) == 2, "episodio sucesor creado, evidencia previa intacta"
        ep1, ep2 = incs[0], incs[1]
        # evidencia de la resolución anterior conservada
        assert ep1["episode"] == 1 and ep1["status"] == "resuelta"
        # la diferencia −3 queda VISIBLE como pendiente
        assert ep2["episode"] == 2 and ep2["status"] == "pendiente"
        assert ep2["amount"] == -60.0 and "-3" in ep2["detail"]
        # episodios enlazados (trazabilidad / continuidad)
        assert ep2["predecessor_id"] == ep1["id"]

        # exactamente UNA incidencia abierta (no se duplica el faltante)
        abiertas = [i for i in incs if i["status"] != "resuelta"]
        assert len(abiertas) == 1

        # trazabilidad de las TRES observaciones: ep1 registra 8 y su cierre
        # (al contar 10), ep2 registra 7.
        ep1_states = [h["status"] for h in ep1["history"]]
        assert "pendiente" in ep1_states and "resuelta" in ep1_states
        assert any("-2" in h.get("note", "") for h in ep1["history"]) or \
            "-2" in ep1["detail"]
        assert ep2["history"][0]["status"] == "pendiente"
        assert str(ep1["id"]) in ep2["history"][0]["note"]
    finally:
        await _cleanup(pid)


async def test_persistent_difference_not_duplicated():
    """Un faltante PERSISTENTE (recuento tras recuento sin cuadrar) refresca el
    MISMO episodio abierto: no crea episodios nuevos ni duplica el impacto."""
    pid = await _mk(stock=10.0, cost=20.0)
    try:
        await record_physical_count(await _prod(pid), 8.0, ACTOR)   # −2
        await record_physical_count(await _prod(pid), 6.0, ACTOR)   # −4 (persiste)
        incs = await _diff_incidents(pid)
        assert len(incs) == 1, "sin cuadrar entre medias → mismo episodio"
        assert incs[0]["status"] == "pendiente"
        assert incs[0]["amount"] == -80.0, "monto refrescado al último, no sumado"
        # la observación intermedia queda registrada en el historial
        notes = " ".join(h.get("note", "") for h in incs[0]["history"])
        assert "-4" in notes or "-4" in incs[0]["detail"]
    finally:
        await _cleanup(pid)


async def test_resolved_then_resolved_again_no_phantom_open():
    """Si tras el sucesor la causa vuelve a cuadrar, el episodio 2 se resuelve
    y no quedan incidencias abiertas (ni fantasmas)."""
    pid = await _mk(stock=10.0, cost=20.0)
    try:
        await record_physical_count(await _prod(pid), 8.0, ACTOR)    # ep1 −2
        await record_physical_count(await _prod(pid), 10.0, ACTOR)   # ep1 resuelta
        await record_physical_count(await _prod(pid), 7.0, ACTOR)    # ep2 −3
        await record_physical_count(await _prod(pid), 10.0, ACTOR)   # ep2 resuelta
        incs = await _diff_incidents(pid)
        assert len(incs) == 2
        assert all(i["status"] == "resuelta" for i in incs)
        abiertas = [i for i in incs if i["status"] != "resuelta"]
        assert not abiertas
    finally:
        await _cleanup(pid)
