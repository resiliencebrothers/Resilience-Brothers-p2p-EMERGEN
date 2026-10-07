"""iter346 — IPV H13 (MEDIA): completar el alcance de la Fase 3 de incidencias.

Cubre lo que faltaba del plan acordado:
- Nuevos tipos auto-detectados: `costo_pendiente` (existencia sin costo, no
  valorable) y `documento_faltante` (base sin documentar), con auto-resolución.
- Filtros por fecha y por producto en el listado.
- Responsable asignado (admin/staff), DISTINTO del autor del cambio, con traza.
- Resolución manual que EXIGE explicación (≥10) + evidencia acorde al tipo.
"""
import uuid

import pytest
from fastapi import HTTPException

from db_client import db
from services.inventory import today_havana
from services.inventory_ipv import register_audited_opening
from services.inventory_incidents import (
    sync_pending_count_incidents, transition_incident, assign_incident,
    list_assignees, list_incidents)

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "u_admin_h13", "email": "admin.h13@resilience.com"}


async def _inc(product_id, itype):
    return await db.inventory_incidents.find_one(
        {"product_id": product_id, "type": itype}, {"_id": 0},
        sort=[("episode", -1), ("created_at", -1)])


async def _mk_product(name, stock, cost):
    pid = f"TEST_H13_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": name, "category": "Prueba", "is_active": True,
        "stock": float(stock), "cost_usd": float(cost),
        "price_usd": float(cost) * 2 or 10.0, "owner_id": "", "unit": "unidad"})
    return pid


async def _cleanup(pids, extra_users=()):
    for pid in pids:
        await db.products.delete_many({"id": pid})
        await db.inventory_movements.delete_many({"product_id": pid})
        await db.inventory_lots.delete_many({"product_id": pid})
        await db.inventory_incidents.delete_many({"product_id": pid})
    for uid in extra_users:
        await db.users.delete_many({"user_id": uid})


async def test_h13_costo_pendiente_lifecycle():
    # Existencia 5 sin costo (cost_usd=0) → no se puede valorar.
    pid = await _mk_product("H13 Sin Costo", 5, 0)
    try:
        day = today_havana()
        await sync_pending_count_incidents(day)
        inc = await _inc(pid, "costo_pendiente")
        assert inc is not None and inc["status"] == "pendiente"
        # Se asigna costo → en el siguiente sync la incidencia se auto-resuelve.
        await db.products.update_one({"id": pid}, {"$set": {"cost_usd": 12.0}})
        await sync_pending_count_incidents(day)
        inc2 = await _inc(pid, "costo_pendiente")
        assert inc2["status"] == "resuelta" and inc2["auto_resolved"] is True
    finally:
        await _cleanup([pid])


async def test_h13_documento_faltante_lifecycle():
    # Existencia 4 CON costo pero SIN movimiento de origen → base sin documentar.
    pid = await _mk_product("H13 Sin Doc", 4, 10)
    try:
        day = today_havana()
        await sync_pending_count_incidents(day)
        inc = await _inc(pid, "documento_faltante")
        assert inc is not None and inc["status"] == "pendiente"
        # Con costo asignado, NO debe existir incidencia de costo pendiente.
        assert await _inc(pid, "costo_pendiente") is None
        # Registrar la apertura auditada documenta la base → se auto-resuelve.
        await register_audited_opening(pid, None, "", ACTOR)
        await sync_pending_count_incidents(day)
        inc2 = await _inc(pid, "documento_faltante")
        assert inc2["status"] == "resuelta" and inc2["auto_resolved"] is True
    finally:
        await _cleanup([pid])


async def test_h13_resolution_requires_note_and_evidence():
    pid = await _mk_product("H13 Resolver", 3, 0)
    try:
        await sync_pending_count_incidents(today_havana())
        inc = await _inc(pid, "costo_pendiente")
        assert inc is not None
        # Nota vacía → 400.
        with pytest.raises(HTTPException) as e1:
            await transition_incident(inc["id"], "resuelta", "", ACTOR)
        assert e1.value.status_code == 400
        # Nota demasiado corta → 400.
        with pytest.raises(HTTPException):
            await transition_incident(inc["id"], "resuelta", "corto", ACTOR)
        # Nota válida pero SIN evidencia → 400.
        with pytest.raises(HTTPException) as e3:
            await transition_incident(
                inc["id"], "resuelta",
                "Se corrige el costo según factura de compra.", ACTOR)
        assert e3.value.status_code == 400
        # Nota válida + evidencia → OK.
        upd = await transition_incident(
            inc["id"], "resuelta",
            "Se corrige el costo según factura de compra.", ACTOR,
            evidence="FACT-2026-114")
        assert upd["status"] == "resuelta"
        assert upd["resolution_evidence"] == "FACT-2026-114"
        assert any("Evidencia: FACT-2026-114" in (h.get("note") or "")
                   for h in upd["history"])
    finally:
        await _cleanup([pid])


async def test_h13_assign_owner_is_distinct_from_author():
    pid = await _mk_product("H13 Responsable", 2, 0)
    uid = f"u_staff_h13_{uuid.uuid4().hex[:6]}"
    await db.users.insert_one({
        "user_id": uid, "name": "Staff H13", "email": "staff.h13@resilience.com",
        "role": "employee"})
    try:
        await sync_pending_count_incidents(today_havana())
        inc = await _inc(pid, "costo_pendiente")
        assert inc is not None
        # El responsable aparece en la lista de asignables.
        assert any(a["id"] == uid for a in await list_assignees())
        # Asignar un no-staff → 400.
        with pytest.raises(HTTPException):
            await assign_incident(inc["id"], "no_existe_123", ACTOR)
        # Asignar al staff → responsable ≠ autor del cambio (ACTOR).
        out = await assign_incident(inc["id"], uid, ACTOR)
        assert out["assignee_id"] == uid
        assert out["assignee_name"] == "Staff H13"
        assert out["assigned_by"] == ACTOR["user_id"]
        assert out["assignee_id"] != out["assigned_by"]
        assert any("Responsable asignado: Staff H13" in (h.get("note") or "")
                   for h in out["history"])
    finally:
        await _cleanup([pid], extra_users=[uid])


async def test_h13_filters_by_product_and_date():
    sfx = uuid.uuid4().hex[:6]
    pa = await _mk_product(f"H13 Filtro Alfa {sfx}", 1, 0)
    pb = await _mk_product(f"H13 Filtro Beta {sfx}", 1, 0)
    try:
        day = today_havana()
        await sync_pending_count_incidents(day)
        # Filtro por producto (coincidencia parcial sobre el nombre).
        only_alfa = await list_incidents(product_q=f"Filtro Alfa {sfx}")
        assert only_alfa and all("Filtro Alfa" in r["product_name"]
                                 for r in only_alfa)
        assert all(r["product_id"] != pb for r in only_alfa)
        # Filtro por fecha: una ventana futura no devuelve las de hoy.
        future = await list_incidents(product_q=f"Filtro Alfa {sfx}",
                                      date_from="2999-01-01")
        assert future == []
        # La ventana que incluye hoy sí las devuelve.
        today_win = await list_incidents(product_q=f"Filtro Alfa {sfx}",
                                         date_from=day, date_to=day)
        assert len(today_win) >= 1
    finally:
        await _cleanup([pa, pb])
