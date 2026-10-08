"""iter350c — RV-04 / H06: la cabecera del cierre debe CONCORDAR con el snapshot.

Bug del auditor: la PRIMERA actualización de `inventory_closes` escribía la
cabecera (responsable/revisor/folio/nota/resultado) SIN condicionarla a la
versión; la ÚLTIMA solo avanzaba el puntero y la valoración. Un intercalado
(A fija su cabecera y se detiene antes de insertar su acta; B completa la v1;
A reanuda con la v2 y pasa a ser la referenciada) dejaba `inventory_closes`
apuntando a la v2 de A pero conservando responsable/folio de B.

Fix: la cabecera se DERIVA del snapshot seleccionado y se publica JUNTO al
puntero bajo el guard de avance monotónico → firmas, folio, nota, resultado y
valor coinciden SIEMPRE con el `snapshot_id` referenciado.
"""
import asyncio

import pytest

from db_client import db
from services.inventory_ipv import save_close_review

pytestmark = pytest.mark.asyncio

DAY = "2001-03-09"  # fecha aislada sin movimientos reales → acta vacía y rápida
ACTOR_A = {"user_id": "user_iter350c_a", "email": "a350c@resilience.com"}
ACTOR_B = {"user_id": "user_iter350c_b", "email": "b350c@resilience.com"}


async def _cleanup():
    await db.inventory_closes.delete_many({"close_date": DAY})
    await db.inventory_close_snapshots.delete_many({"close_date": DAY})


async def _close_doc():
    return await db.inventory_closes.find_one({"close_date": DAY}, {"_id": 0})


async def _snaps():
    return await db.inventory_close_snapshots.find(
        {"close_date": DAY}, {"_id": 0}).to_list(100)


def _gate_first_snapshot_insert(monkeypatch):
    """Bloquea la PRIMERA inserción de snapshot de DAY hasta soltar la compuerta.
    Reproduce el intercalado: A se detiene ANTES de insertar su acta."""
    cls = type(db.inventory_close_snapshots)
    orig = cls.insert_one
    gate = asyncio.Event()
    state = {"blocked": False}

    async def patched(self, doc, *a, **k):
        if (self.name == "inventory_close_snapshots"
                and isinstance(doc, dict) and doc.get("close_date") == DAY
                and not state["blocked"]):
            state["blocked"] = True
            await gate.wait()
        return await orig(self, doc, *a, **k)

    monkeypatch.setattr(cls, "insert_one", patched)
    return gate, state


async def test_header_matches_pointed_snapshot_after_interleave(monkeypatch):
    await _cleanup()
    try:
        gate, state = _gate_first_snapshot_insert(monkeypatch)
        # A arranca y se detiene en su insert de snapshot (tras fijar su acta).
        task_a = asyncio.create_task(save_close_review(
            DAY, "Prep-A", "Rev-A", "F-A", "motivo A", ACTOR_A))
        for _ in range(500):
            if state["blocked"]:
                break
            await asyncio.sleep(0.01)
        assert state["blocked"], "A no llegó a su inserción de snapshot"
        # B completa ENTERO → crea la v1 y la referencia apunta a ella.
        await save_close_review(DAY, "Prep-B", "Rev-B", "F-B", "motivo B",
                                ACTOR_B)
        # A reanuda → su v1 choca (dup), reintenta v2 y pasa a ser la referenciada.
        gate.set()
        await task_a

        doc = await _close_doc()
        snaps = await _snaps()
        by_id = {s["id"]: s for s in snaps}
        assert doc["snapshot_version"] == 2
        pointed = by_id[doc["snapshot_id"]]
        assert pointed["version"] == 2
        # La cabecera del cierre CONCUERDA con el snapshot apuntado (A), NO con B.
        assert doc["responsable"] == pointed["responsable"] == "Prep-A"
        assert doc["revisado_por"] == pointed["revisado_por"] == "Rev-A"
        assert doc["folio"] == pointed["folio"] == "F-A"
        assert doc["note"] == pointed["note"] == "motivo A"
        assert doc["resultado"] == pointed["resultado"]
        assert doc["closed_by"] == pointed["frozen_by"] == "user_iter350c_a"
        assert doc["value_cup"] == pointed["totals"]["value_cup"]
        assert doc["fx_rate_vip"] == pointed["fx"]["rate_vip"]
        # Ambas actas quedan archivadas como evidencia (nunca se pierde la de B).
        assert sorted(s["version"] for s in snaps) == [1, 2]
        v1 = next(s for s in snaps if s["version"] == 1)
        assert v1["responsable"] == "Prep-B" and v1["folio"] == "F-B"
    finally:
        await _cleanup()


async def test_sequential_header_follows_latest_snapshot():
    """Correcciones secuenciales: la cabecera del cierre sigue SIEMPRE a la
    última versión (la referenciada), no a una intermedia."""
    await _cleanup()
    try:
        await save_close_review(DAY, "R1", "V1", "F1", "n1", ACTOR_A)
        await save_close_review(DAY, "R2", "V2", "F2", "n2", ACTOR_B)
        doc = await _close_doc()
        snaps = await _snaps()
        pointed = next(s for s in snaps if s["id"] == doc["snapshot_id"])
        assert doc["snapshot_version"] == 2 and pointed["version"] == 2
        assert doc["responsable"] == pointed["responsable"] == "R2"
        assert doc["folio"] == pointed["folio"] == "F2"
        assert doc["note"] == pointed["note"] == "n2"
    finally:
        await _cleanup()
