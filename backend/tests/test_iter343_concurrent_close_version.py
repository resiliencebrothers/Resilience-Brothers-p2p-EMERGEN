"""iter343 — H06: dos cierres concurrentes NO pueden compartir versión de acta.

Bug del auditor (Fase 1, services/inventory_ipv.py): la versión del acta se
obtenía leyendo el máximo y sumando uno, sin asignación atómica. Dos guardados
simultáneos leían la misma versión y se insertaban dos actas [1, 1]; además una
operación atrasada podía sustituir en `inventory_closes` la referencia a una
revisión posterior.

Pruebas DETERMINISTAS in-process (no HTTP): una `asyncio.Barrier` fuerza a que
ambos guardados lean la MISMA versión máxima ANTES de que cualquiera inserte
(el intercalado exacto que reproduce el auditor). Con el fix, el índice único
(close_date, version) arbitra y el perdedor REINTENTA → versiones inequívocas
[1, 2] y la referencia apunta siempre a la mayor.
"""
import asyncio
import uuid

import pytest

from db_client import db
from services.inventory_ipv import save_close_review

pytestmark = pytest.mark.asyncio

DAY = "2000-01-15"  # fecha aislada: sin movimientos reales → acta vacía y rápida
ACTOR_A = {"user_id": "user_iter343_a", "email": "a.iter343@resilience.com"}
ACTOR_B = {"user_id": "user_iter343_b", "email": "b.iter343@resilience.com"}


async def _cleanup():
    await db.inventory_closes.delete_many({"close_date": DAY})
    await db.inventory_close_snapshots.delete_many({"close_date": DAY})


async def _snaps():
    return await db.inventory_close_snapshots.find(
        {"close_date": DAY}, {"_id": 0}).to_list(100)


async def _close_doc():
    return await db.inventory_closes.find_one({"close_date": DAY}, {"_id": 0})


def _gate_both_version_reads(monkeypatch):
    """Fuerza a que las DOS primeras lecturas de versión de `DAY` ocurran antes
    de cualquier inserción (ambas ven el mismo máximo). La barrera bloquea a la
    primera corrutina hasta que la segunda llega a su propia lectura."""
    cls = type(db.inventory_close_snapshots)
    orig = cls.find_one
    barrier = asyncio.Barrier(2)
    state = {"gated": 0}

    async def patched(self, filt=None, *a, **k):
        res = await orig(self, filt, *a, **k)
        if (self.name == "inventory_close_snapshots"
                and isinstance(filt, dict) and filt.get("close_date") == DAY
                and state["gated"] < 2):
            state["gated"] += 1
            await barrier.wait()
        return res

    monkeypatch.setattr(cls, "find_one", patched)


async def test_concurrent_saves_get_unique_versions(monkeypatch):
    """Repro del auditor: dos guardados concurrentes leen la misma versión; con
    el fix NO se insertan [1, 1] sino [1, 2] y la referencia apunta a la 2."""
    await _cleanup()
    try:
        _gate_both_version_reads(monkeypatch)
        a, b = await asyncio.gather(
            save_close_review(DAY, "Resp A", "Rev A", "F-A", "motivo A",
                              ACTOR_A),
            save_close_review(DAY, "Resp B", "Rev B", "F-B", "motivo B",
                              ACTOR_B),
        )
        snaps = await _snaps()
        versions = sorted(s["version"] for s in snaps)
        assert versions == [1, 2], f"versiones inequívocas, nunca [1,1]: {versions}"
        assert len({s["id"] for s in snaps}) == 2, "dos actas distintas"
        # motivo y autor conservados en CADA acta (como pide el plan)
        by_resp = {s["responsable"]: s for s in snaps}
        assert set(by_resp) == {"Resp A", "Resp B"}
        assert by_resp["Resp A"]["note"] == "motivo A"
        assert by_resp["Resp A"]["frozen_by"] == "user_iter343_a"
        assert by_resp["Resp B"]["note"] == "motivo B"
        assert by_resp["Resp B"]["frozen_by"] == "user_iter343_b"
        # la referencia de inventory_closes apunta a la versión MAYOR, coherente
        top = max(snaps, key=lambda s: s["version"])
        doc = await _close_doc()
        assert doc["snapshot_version"] == 2
        assert doc["snapshot_id"] == top["id"]
    finally:
        await _cleanup()


async def test_sequential_saves_increment_and_preserve_author():
    """Guardados secuenciales (correcciones) → versiones 1,2,3; cada acta
    conserva su propio motivo/autor y la referencia sigue a la última."""
    await _cleanup()
    try:
        for i, (resp, note, actor) in enumerate([
                ("R1", "n1", ACTOR_A), ("R2", "n2", ACTOR_B),
                ("R3", "n3", ACTOR_A)], start=1):
            await save_close_review(DAY, resp, "Rev", f"F{i}", note, actor)
            doc = await _close_doc()
            assert doc["snapshot_version"] == i
        snaps = await _snaps()
        assert sorted(s["version"] for s in snaps) == [1, 2, 3]
        by_ver = {s["version"]: s for s in snaps}
        assert by_ver[1]["note"] == "n1" and by_ver[1]["responsable"] == "R1"
        assert by_ver[3]["note"] == "n3" and by_ver[3]["responsable"] == "R3"
        doc = await _close_doc()
        assert doc["snapshot_id"] == by_ver[3]["id"]
    finally:
        await _cleanup()


async def test_late_lower_version_does_not_overwrite_reference():
    """Una operación atrasada (versión menor) NO sustituye la referencia a una
    revisión posterior ya registrada: el guard de avance monotónico la ignora."""
    await _cleanup()
    try:
        await save_close_review(DAY, "R1", "Rev", "F1", "n1", ACTOR_A)
        await save_close_review(DAY, "R2", "Rev", "F2", "n2", ACTOR_B)
        doc = await _close_doc()
        assert doc["snapshot_version"] == 2
        ref_id = doc["snapshot_id"]
        # intento atrasado de re-apuntar a la versión 1 (misma consulta guardada
        # de producción): no debe tocar la referencia vigente a la 2.
        res = await db.inventory_closes.update_one(
            {"close_date": DAY,
             "$or": [{"snapshot_version": {"$exists": False}},
                     {"snapshot_version": {"$lt": 1}}]},
            {"$set": {"snapshot_version": 1, "snapshot_id": "acta-vieja"}})
        assert res.modified_count == 0, "el guard ignora la versión menor"
        doc = await _close_doc()
        assert doc["snapshot_version"] == 2 and doc["snapshot_id"] == ref_id
    finally:
        await _cleanup()


async def test_unique_index_present_after_save():
    """Tras un guardado, el índice único (close_date, version) existe → impide
    físicamente actas duplicadas por fecha aunque falle el reintento lógico."""
    await _cleanup()
    try:
        await save_close_review(DAY, "R", "Rev", "F", "n", ACTOR_A)
        info = await db.inventory_close_snapshots.index_information()
        unique_compound = [
            name for name, spec in info.items()
            if spec.get("unique") and spec.get("key") ==
            [("close_date", 1), ("version", 1)]]
        assert unique_compound, f"falta índice único compuesto: {list(info)}"
    finally:
        await _cleanup()
