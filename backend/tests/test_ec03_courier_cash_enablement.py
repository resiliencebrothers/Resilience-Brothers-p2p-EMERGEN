"""EC03-R — registrar efectivo de custodia exige MENSAJERO HABILITADO.

Unifica la política con `_require_courier` (STAFF-04/05-R): la ruta manual
`POST /admin/courier-cash` ya NO acepta a un admin/employee cuyo `is_courier`
sea falso (antes bastaba pertenecer al staff). Si se le retiró la habilitación
de mensajero, no se le puede emitir ni recibir efectivo de custodia aunque
conserve rol de personal. Un cliente normal también se rechaza.
"""
import os
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
EMP = "user_test_employee01"
NORMAL = "user_test_normal01"

_DB_CLIENT = None


def _db():
    global _DB_CLIENT
    if _DB_CLIENT is None:
        _DB_CLIENT = MongoClient(os.environ["MONGO_URL"])
    return _DB_CLIENT[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _post(courier_id):
    return requests.post(
        f"{API}/admin/courier-cash", headers=_hdr(ADMIN_TOKEN),
        json={"kind": "issued", "courier_id": courier_id,
              "account_id": "bogus_account_ec03", "currency": "CUP",
              "amount": 100})


def test_ec03r_staff_without_is_courier_rejected():
    _db().users.update_one({"user_id": EMP},
                           {"$set": {"role": "employee", "account_status": "active",
                                     "is_courier": False}})
    try:
        r = _post(EMP)
        assert r.status_code == 400, r.text
        assert "mensajero habilitado" in r.text.lower(), r.text
    finally:
        _db().users.update_one({"user_id": EMP}, {"$set": {"is_courier": False}})


def test_ec03r_normal_user_rejected():
    _db().users.update_one({"user_id": NORMAL}, {"$set": {"is_courier": False}})
    r = _post(NORMAL)
    assert r.status_code == 400, r.text
    assert "mensajero habilitado" in r.text.lower(), r.text


def test_ec03r_enabled_courier_passes_enablement_gate():
    # is_courier=True supera la compuerta de habilitación; luego falla por la
    # cuenta inexistente, pero NO por "mensajero habilitado".
    _db().users.update_one({"user_id": EMP},
                           {"$set": {"role": "employee", "account_status": "active",
                                     "is_courier": True}})
    try:
        r = _post(EMP)
        assert r.status_code == 400, r.text  # cuenta de caja inexistente
        assert "mensajero habilitado" not in r.text.lower(), r.text
    finally:
        _db().users.update_one({"user_id": EMP}, {"$set": {"is_courier": False}})
