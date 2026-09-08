"""iter252 — Backend: campo `applied_templates` en PUT /admin/users/{id}.

Registro del delta que cada plantilla rápida sumó (added_perms, prev/set
currencies) para que el botón "Quitar lo que sumó" revierta exactamente eso.
"""
import os

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
ADM_H = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
EMP_H = {"Authorization": f"Bearer {EMPLOYEE_TOKEN}"}
TARGET = "user_test_employee01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


class TestAppliedTemplatesField:
    def setup_method(self, _):
        u = _db().users.find_one({"user_id": TARGET},
                                 {"_id": 0, "applied_templates": 1,
                                  "allowed_permissions": 1, "allowed_currencies": 1})
        self._orig = u or {}

    def teardown_method(self, _):
        sets, unsets = {}, {}
        for k in ("applied_templates", "allowed_permissions", "allowed_currencies"):
            if k in self._orig:
                sets[k] = self._orig[k]
            else:
                unsets[k] = ""
        ops = {}
        if sets:
            ops["$set"] = sets
        if unsets:
            ops["$unset"] = unsets
        _db().users.update_one({"user_id": TARGET}, ops)

    def _put(self, body, headers=ADM_H):
        return requests.put(f"{API}/admin/users/{TARGET}",
                            headers=headers, json=with_totp_admin(body), timeout=15)

    def test_persists_sanitized_record_and_roundtrips(self):
        body = {
            "allowed_permissions": ["orders", "quick_view"],
            "applied_templates": {
                "cajero": {
                    "added_perms": ["orders", "quick_view"],
                    "prev_currencies": ["USD"],
                    "set_currencies": [],
                    "currencies_changed": True,
                    "applied_at": "2026-06-01T00:00:00+00:00",
                    "campo_extra_malicioso": "se descarta",
                },
            },
        }
        r = self._put(body)
        assert r.status_code == 200, r.text
        doc = _db().users.find_one({"user_id": TARGET}, {"_id": 0, "applied_templates": 1})
        rec = doc["applied_templates"]["cajero"]
        assert rec["added_perms"] == ["orders", "quick_view"]
        assert rec["prev_currencies"] == ["USD"]
        assert rec["set_currencies"] == []
        assert rec["currencies_changed"] is True
        assert "campo_extra_malicioso" not in rec
        # el GET del admin expone el campo
        g = requests.get(f"{API}/admin/users", headers=ADM_H,
                         params={"q": "employee.test"}, timeout=15)
        assert g.status_code == 200
        row = next(u for u in g.json() if u["user_id"] == TARGET)
        assert "cajero" in (row.get("applied_templates") or {})

    def test_empty_dict_clears_records(self):
        self._put({"applied_templates": {"cajero": {"added_perms": ["orders"]}}})
        r = self._put({"applied_templates": {}})
        assert r.status_code == 200, r.text
        doc = _db().users.find_one({"user_id": TARGET}, {"_id": 0, "applied_templates": 1})
        assert doc.get("applied_templates") == {}

    def test_non_admin_cannot_write_templates(self):
        r = requests.put(f"{API}/admin/users/{TARGET}", headers=EMP_H,
                         json=with_totp_admin(
                             {"applied_templates": {"cajero": {"added_perms": []}}}),
                         timeout=15)
        assert r.status_code == 403, r.text

    def test_oversized_map_rejected(self):
        big = {f"t{i}": {"added_perms": []} for i in range(25)}
        r = self._put({"applied_templates": big})
        assert r.status_code == 422, r.text
