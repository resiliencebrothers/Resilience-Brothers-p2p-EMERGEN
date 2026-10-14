"""M01-B (recorrido LIBRE) — una aceptación de un trabajo LIBRE también recibe
una identidad de ciclo (`assignment_uid`) distinguible, de modo que una
reasignación administrativa ATRASADA no pueda confundir dos ciclos aceptados
sucesivos que —antes del arreglo— compartían la "ausencia de uid".

MEN-14 sólo cubre ciclos que empiezan por `admin_assign`, así que todos sus
ciclos ya tienen uid. Aquí el ciclo nace de la cola «Disponibles» (claim sin
uid), que era precisamente el hueco: libre -> acepta A -> libera -> acepta B ->
libera -> acepta A, con la primera reasignación observando el ciclo inicial.
Debe perder con 409 y conservar la nueva aceptación de A.

Incluye el control positivo de una reasignación vigente y la cobertura de los
registros ACEPTADOS heredados sin uid (migración de sellado).
"""
import os
import uuid as _uuid
import asyncio
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, EMPLOYEE_TOKEN

API = f"{BASE_URL}/api"
A_ID = "user_test_vip01"        # mensajero A
A_TOKEN = VIP_TOKEN
B_ID = "user_test_employee01"   # mensajero B (role employee)
B_TOKEN = EMPLOYEE_TOKEN


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mk_free():
    db = _db()
    db.users.update_one({"user_id": A_ID}, {"$set": {"is_courier": True}})
    did = f"men16_{_uuid.uuid4().hex[:10]}"
    db.deliveries.insert_one({
        "id": did, "status": "available", "kind": "withdrawal",
        "ref_id": _uuid.uuid4().hex, "client_name": "MEN16", "address": "C 1",
        "amount_label": "100 USDT", "km": 2, "fee_usdt": 5,
        "courier_share_usdt": 4, "platform_share_usdt": 1,
        "courier_id": None, "courier_name": None,
        "created_at": _now(), "updated_at": _now(),
    })
    return did


def _claim_free(did, tok):
    """Toma desde «Disponibles»: SIN assignment_uid (trabajo realmente libre)."""
    return requests.post(f"{API}/courier/deliveries/{did}/claim",
                         headers=_hdr(tok), json={}, timeout=15)


def _reassign(did, courier_id=None, expected_uid=None, reason="cambio"):
    body = {"reason": reason}
    if courier_id:
        body["courier_id"] = courier_id
    if expected_uid is not None:
        body["expected_uid"] = expected_uid
    return requests.post(f"{API}/admin/deliveries/{did}/reassign",
                         headers=_hdr(ADMIN_TOKEN), json=body, timeout=15)


def _uid(did):
    return _db().deliveries.find_one({"id": did}, {"_id": 0}).get(
        "assignment_uid")


def _doc(did):
    return _db().deliveries.find_one({"id": did}, {"_id": 0})


def _cleanup(did):
    _db().deliveries.delete_many({"id": did})


# ---------------------------------------------------------------------------

def test_free_accept_stamps_a_distinguishable_cycle_uid():
    """Aceptar un trabajo LIBRE (sin uid) sella una identidad de ciclo nueva."""
    did = _mk_free()
    try:
        assert _uid(did) is None  # recién creada, libre, sin ciclo
        assert _claim_free(did, A_TOKEN).status_code == 200
        d = _doc(did)
        assert d["status"] == "accepted" and d["courier_id"] == A_ID
        assert d.get("assignment_uid")  # AHORA tiene identidad de ciclo
    finally:
        _cleanup(did)


def test_two_successive_free_accepts_have_different_cycle_uids():
    """Dos aceptaciones libres SUCESIVAS no comparten la ausencia de uid: cada
    una recibe un uid propio, por lo que son distinguibles."""
    did = _mk_free()
    try:
        assert _claim_free(did, A_TOKEN).status_code == 200
        f1 = _uid(did)
        # liberar el ciclo vigente y volver a tomarlo libremente
        assert _reassign(did, expected_uid=f1).status_code == 200
        assert _claim_free(did, A_TOKEN).status_code == 200
        f2 = _uid(did)
        assert f1 and f2 and f1 != f2
    finally:
        _cleanup(did)


def test_M01B_stale_reassign_on_free_cycle_loses_with_409():
    """libre -> A acepta (f1) -> libera -> B acepta (f2) -> libera -> A acepta
    (f3). La reasignación ATRASADA que observó f1 pierde con 409 al reanudarse
    y la nueva aceptación de A (f3) queda intacta."""
    did = _mk_free()
    try:
        # A toma el trabajo libre → ciclo f1
        assert _claim_free(did, A_TOKEN).status_code == 200
        f1 = _uid(did)
        assert _doc(did)["status"] == "accepted" and f1

        # libera (ciclo vigente f1) → B lo toma libremente → f2
        assert _reassign(did, expected_uid=f1).status_code == 200
        assert _claim_free(did, B_TOKEN).status_code == 200
        f2 = _uid(did)
        assert f2 and f2 != f1

        # libera (ciclo vigente f2) → A lo vuelve a tomar → f3
        assert _reassign(did, expected_uid=f2).status_code == 200
        assert _claim_free(did, A_TOKEN).status_code == 200
        f3 = _uid(did)
        assert f3 and f3 not in (f1, f2)
        assert _doc(did)["status"] == "accepted"
        assert _doc(did)["courier_id"] == A_ID

        # reanuda la PRIMERA reasignación: observó f1 → debe perder con 409
        r = _reassign(did, B_ID, expected_uid=f1)
        assert r.status_code == 409, r.text
        d = _doc(did)
        assert d["status"] == "accepted"
        assert d["courier_id"] == A_ID
        assert d.get("assignment_uid") == f3  # ciclo nuevo de A intacto
    finally:
        _cleanup(did)


def test_M01B_valid_reassign_on_free_cycle_succeeds():
    """Control positivo: reasignar observando el ciclo LIBRE vigente funciona."""
    did = _mk_free()
    try:
        assert _claim_free(did, A_TOKEN).status_code == 200
        f1 = _uid(did)
        r = _reassign(did, B_ID, expected_uid=f1)
        assert r.status_code == 200, r.text
        d = _doc(did)
        assert d["status"] == "available"
        assert d["assigned_to_courier_id"] == B_ID
        assert d.get("assignment_uid") not in (None, f1)
    finally:
        _cleanup(did)


def test_legacy_accepted_without_uid_is_sealed_by_migration():
    """Un registro ACEPTADO heredado SIN uid queda cubierto por la migración de
    sellado (idempotente): recibe un uid y una segunda ejecución no lo cambia."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from services.db_migrations import (
        migrate_assignment_uid_for_accepted_deliveries)

    db = _db()
    did = f"men16_legacy_{_uuid.uuid4().hex[:8]}"
    db.deliveries.insert_one({
        "id": did, "status": "accepted", "kind": "withdrawal",
        "courier_id": A_ID, "courier_name": "VIP Test",
        "created_at": _now(), "updated_at": _now(),
    })

    async def _run_migration():
        aclient = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            await migrate_assignment_uid_for_accepted_deliveries(
                aclient[os.environ["DB_NAME"]])
        finally:
            aclient.close()

    try:
        assert "assignment_uid" not in _doc(did)
        asyncio.run(_run_migration())
        sealed = _uid(did)
        assert sealed  # ahora distinguible
        asyncio.run(_run_migration())
        assert _uid(did) == sealed  # idempotente
    finally:
        _cleanup(did)
