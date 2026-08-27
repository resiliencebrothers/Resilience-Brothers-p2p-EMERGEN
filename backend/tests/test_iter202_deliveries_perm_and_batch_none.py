"""iter202 — Permiso dedicado 'Mensajería' + modo "sin acceso a lotes".

1. El catálogo de permisos incluye el código `deliveries` (Mensajería).
2. Endpoints admin de mensajería (/admin/deliveries, /admin/couriers) exigen
   el permiso `deliveries` (ya no `withdrawals`).
3. Designar mensajeros (is_courier) exige `deliveries` (antes user_functions).
4. allowed_batch_pairs acepta el sentinel "none": el staff queda SIN acceso
   a ningún lote (lista vacía sigue = acceso total, compat legacy).
"""
import os
import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, VIP_TOKEN,
    with_totp_admin, with_totp_employee,
)

API = f"{BASE_URL}/api"
EMPLOYEE_ID = "user_test_employee01"
VIP_ID = "user_test_vip01"


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _set_employee(perms=None, pairs=None):
    update = {}
    update["allowed_permissions"] = perms if perms is not None else []
    update["allowed_batch_pairs"] = pairs if pairs is not None else []
    _sync_db().users.update_one({"user_id": EMPLOYEE_ID}, {"$set": update})


def _reset_employee():
    _sync_db().users.update_one(
        {"user_id": EMPLOYEE_ID},
        {"$set": {"allowed_permissions": [], "allowed_batch_pairs": []}})


# ---------- 1. Catálogo ----------

def test_catalog_includes_deliveries_permission():
    r = requests.get(f"{API}/admin/permissions/catalog", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    codes = {p["code"] for p in r.json()["items"]}
    assert "deliveries" in codes
    entry = next(p for p in r.json()["items"] if p["code"] == "deliveries")
    assert entry["label"] == "Mensajería"


# ---------- 2. Gate en endpoints de mensajería ----------

def test_deliveries_endpoints_require_deliveries_permission():
    try:
        # Con withdrawals pero SIN deliveries → 403.
        _set_employee(perms=["withdrawals"])
        r = requests.get(f"{API}/admin/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 403, r.text
        assert "Mensajería" in r.json().get("detail", "")
        r = requests.get(f"{API}/admin/couriers", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 403, r.text
        # Con deliveries → 200.
        _set_employee(perms=["deliveries"])
        r = requests.get(f"{API}/admin/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200, r.text
        r = requests.get(f"{API}/admin/couriers", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200, r.text
    finally:
        _reset_employee()


# ---------- 3. Designar mensajeros ----------

def test_designating_courier_requires_deliveries_permission():
    try:
        # users + user_functions ya NO alcanzan para is_courier.
        _set_employee(perms=["users", "user_functions"])
        r = requests.put(f"{API}/admin/users/{VIP_ID}", headers=_hdr(EMPLOYEE_TOKEN),
                         json=with_totp_employee({"is_courier": True}))
        assert r.status_code == 403, r.text
        assert "Mensajería" in r.json().get("detail", "")
        # Admin siempre puede.
        r = requests.put(f"{API}/admin/users/{VIP_ID}", headers=_hdr(ADMIN_TOKEN),
                         json=with_totp_admin({"is_courier": True}))
        assert r.status_code == 200, r.text
        assert r.json()["is_courier"] is True
    finally:
        _reset_employee()
        # iter209b — restaurar el estado base (VIP test ES mensajero desde
        # iter199) para no contaminar otros tests de la suite.
        requests.put(f"{API}/admin/users/{VIP_ID}", headers=_hdr(ADMIN_TOKEN),
                     json=with_totp_admin({"is_courier": True}))


# ---------- 4. Lotes: sentinel "none" ----------

def test_batch_pairs_none_persists_via_api():
    r = requests.put(f"{API}/admin/users/{EMPLOYEE_ID}", headers=_hdr(ADMIN_TOKEN),
                     json=with_totp_admin({"allowed_batch_pairs": ["none"]}))
    assert r.status_code == 200, r.text
    assert r.json()["allowed_batch_pairs"] == ["none"]
    # "none" mezclado con pares → gana "none" (bloqueo total explícito).
    r = requests.put(f"{API}/admin/users/{EMPLOYEE_ID}", headers=_hdr(ADMIN_TOKEN),
                     json=with_totp_admin({"allowed_batch_pairs": ["EUR->USDT", "NONE"]}))
    assert r.status_code == 200, r.text
    assert r.json()["allowed_batch_pairs"] == ["none"]
    _reset_employee()


def test_staff_with_none_sees_no_batch_items_and_cannot_approve():
    db = _sync_db()
    item_id = "itm_test_iter202"
    db.vip_batch_items.insert_one({
        "id": item_id, "batch_id": "bat_test_iter202",
        "vip_user_id": VIP_ID, "holder_name": "Iter202 Holder",
        "amount": 10.0, "currency": "EUR", "direction": "credit",
        "from_code": "EUR", "to_code": "USDT",
        "status": "pending", "created_at": "2026-06-01T00:00:00+00:00",
        "updated_at": "2026-06-01T00:00:00+00:00",
    })
    try:
        _set_employee(perms=[], pairs=["none"])
        # La cola llega vacía para este staff.
        r = requests.get(f"{API}/admin/vip-batches", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200, r.text
        ids = {it["id"] for it in r.json()["items"]}
        assert item_id not in ids
        # Y no puede aprobar (403 del RBAC de pares).
        r = requests.post(f"{API}/admin/vip-batches/items/{item_id}/approve",
                          headers=_hdr(EMPLOYEE_TOKEN), json={})
        assert r.status_code == 403, r.text
        # Lista vacía (legacy) sigue viendo el ítem — compat sin cambios.
        _set_employee(perms=[], pairs=[])
        r = requests.get(f"{API}/admin/vip-batches", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200, r.text
        ids = {it["id"] for it in r.json()["items"]}
        assert item_id in ids
    finally:
        _reset_employee()
        db.vip_batch_items.delete_one({"id": item_id})
        db.vip_batches.delete_many({"id": "bat_test_iter202"})
