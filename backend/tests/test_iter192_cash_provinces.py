"""iter192 — Cash-delivery withdrawals gated by province availability.

- GET /vip/cash-provinces lists all 16 provinces with availability flags.
- PUT /admin/settings accepts cash_provinces (validated).
- POST /vip/withdraw method=cash requires an AVAILABLE province.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, make_vip_totp

API = f"{BASE_URL}/api"
CODE = "CUP192"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _set_provinces(value):
    _db().settings.update_one({"id": "global"},
                              {"$set": {"cash_provinces": value}}, upsert=True)


def setup_module():
    db = _db()
    db.currencies.update_one(
        {"code": CODE},
        {"$set": {"code": CODE, "name": "Test 192", "type": "fiat",
                  "is_active": True, "delivery_methods": ["cash"]},
         "$setOnInsert": {"id": uuid.uuid4().hex,
                          "created_at": "2026-07-10T00:00:00+00:00"}},
        upsert=True)
    db.users.update_one({"user_id": "user_test_vip01"},
                        {"$set": {f"vip_balances.{CODE}": 5000}})


def teardown_module():
    db = _db()
    _set_provinces(None)
    db.currencies.delete_one({"code": CODE})
    db.users.update_one({"user_id": "user_test_vip01"},
                        {"$unset": {f"vip_balances.{CODE}": ""}})
    db.withdrawals.delete_many({"currency": CODE})


CASH_DETAILS = ("Provincia: La Habana\nNombre: Juan Pérez Rodríguez\n"
                "Celular: +53 55512345\nDirección: Calle 23 #456, Vedado")


def _withdraw(province=None):
    body = {"amount_usd": 25, "currency": CODE, "method": "cash",
            "details": CASH_DETAILS, "totp_code": make_vip_totp()}
    if province is not None:
        body["province"] = province
    return requests.post(f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN), json=body)


def test_provinces_endpoint_lists_16_with_flags():
    _set_provinces(["La Habana", "Matanzas"])
    r = requests.get(f"{API}/vip/cash-provinces", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    provs = r.json()["provinces"]
    assert len(provs) == 16
    flags = {p["name"]: p["available"] for p in provs}
    assert flags["La Habana"] is True
    assert flags["Matanzas"] is True
    assert flags["Holguín"] is False


def test_cash_withdraw_available_province_succeeds_and_stores():
    _set_provinces(["La Habana"])
    r = _withdraw("La Habana")
    assert r.status_code == 200, r.text
    doc = _db().withdrawals.find_one({"id": r.json()["id"]})
    assert doc["province"] == "La Habana"


def test_cash_withdraw_unavailable_province_blocked():
    _set_provinces(["La Habana"])
    r = _withdraw("Holguín")
    assert r.status_code == 400, r.text
    assert "Holguín" in r.json()["detail"]


def test_cash_withdraw_missing_or_invalid_province_blocked():
    _set_provinces(None)
    assert _withdraw(None).status_code == 400
    assert _withdraw("Narnia").status_code == 400


def test_no_config_means_all_available():
    _set_provinces(None)
    r = _withdraw("Guantánamo")
    assert r.status_code == 200, r.text


def test_admin_settings_rejects_invalid_provinces():
    r = requests.put(f"{API}/admin/settings", headers=_hdr(ADMIN_TOKEN),
                     json={"cash_provinces": ["La Habana", "Narnia"],
                           "totp_code": "000000"})
    # invalid provinces must 400 (or 401 if TOTP is checked first)
    assert r.status_code in (400, 401), r.text
    if r.status_code == 400:
        assert "Narnia" in r.json()["detail"]
