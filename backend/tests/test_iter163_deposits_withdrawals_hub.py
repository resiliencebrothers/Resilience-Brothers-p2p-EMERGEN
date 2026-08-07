"""iter163 — Deposits & Withdrawals unified section.

Client deposits + VIP capital deposits moved from the `orders` permission
gate to `withdrawals`. New hub badge endpoint:
  GET /api/admin/deposits-hub/pending-count
"""
import os
import uuid

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP

EMP_WITHDRAWALS_ID = "user_test_emp163_wd"
EMP_ORDERS_ID = "user_test_emp163_ord"
EMP_WITHDRAWALS_TOKEN = f"test_session_{uuid.uuid4().hex}"
EMP_ORDERS_TOKEN = f"test_session_{uuid.uuid4().hex}"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def setup_module():
    db = _db()
    for uid, tok, perms in (
        (EMP_WITHDRAWALS_ID, EMP_WITHDRAWALS_TOKEN, ["withdrawals"]),
        (EMP_ORDERS_ID, EMP_ORDERS_TOKEN, ["orders"]),
    ):
        db.users.update_one(
            {"user_id": uid},
            {"$set": {"user_id": uid, "email": f"{uid}@test.com",
                      "name": uid, "role": "employee",
                      "allowed_permissions": perms}},
            upsert=True,
        )
        db.user_sessions.update_one(
            {"session_token": tok},
            {"$set": {"session_token": tok, "user_id": uid,
                      "expires_at": "2099-01-01T00:00:00+00:00"}},
            upsert=True,
        )


def teardown_module():
    db = _db()
    db.users.delete_many({"user_id": {"$in": [EMP_WITHDRAWALS_ID, EMP_ORDERS_ID]}})
    db.user_sessions.delete_many({"session_token": {"$in": [EMP_WITHDRAWALS_TOKEN, EMP_ORDERS_TOKEN]}})


class TestDepositsPermissionGate:
    def test_withdrawals_staff_can_list_deposits(self):
        r = requests.get(f"{BASE_URL}/api/admin/deposits", headers=_h(EMP_WITHDRAWALS_TOKEN))
        assert r.status_code == 200, r.text
        assert "items" in r.json()

    def test_orders_staff_forbidden_on_deposits(self):
        r = requests.get(f"{BASE_URL}/api/admin/deposits", headers=_h(EMP_ORDERS_TOKEN))
        assert r.status_code == 403, r.text

    def test_withdrawals_staff_can_list_capital_deposits(self):
        r = requests.get(f"{BASE_URL}/api/admin/vip-capital-deposits", headers=_h(EMP_WITHDRAWALS_TOKEN))
        assert r.status_code == 200, r.text

    def test_orders_staff_forbidden_on_capital_deposits(self):
        r = requests.get(f"{BASE_URL}/api/admin/vip-capital-deposits", headers=_h(EMP_ORDERS_TOKEN))
        assert r.status_code == 403, r.text

    def test_admin_still_allowed(self):
        for path in ("/api/admin/deposits", "/api/admin/vip-capital-deposits"):
            r = requests.get(f"{BASE_URL}{path}", headers=_h(ADMIN))
            assert r.status_code == 200, (path, r.text)


class TestDepositsFilters:
    def _seed(self, dep_id, method, name, email):
        _db().deposits.insert_one({
            "id": dep_id, "user_id": "user_test_vip01",
            "user_email": email, "user_name": name, "user_role": "vip",
            "currency": "USD", "amount": 10.0, "method": method,
            "status": "pending",
            "created_at": "2026-06-01T00:00:00+00:00",
            "updated_at": "2026-06-01T00:00:00+00:00",
        })

    def test_method_and_user_q_filters(self):
        a = f"dep165_{uuid.uuid4().hex[:8]}"
        b = f"dep165_{uuid.uuid4().hex[:8]}"
        self._seed(a, "cash", "Carlos Filtro", "carlos.filtro@test.com")
        self._seed(b, "crypto", "Berta Cadena", "berta.cadena@test.com")
        try:
            r = requests.get(f"{BASE_URL}/api/admin/deposits",
                             params={"method": "cash", "user_q": "filtro"},
                             headers=_h(ADMIN))
            assert r.status_code == 200, r.text
            ids = [i["id"] for i in r.json()["items"]]
            assert a in ids and b not in ids

            r2 = requests.get(f"{BASE_URL}/api/admin/deposits",
                              params={"user_q": "berta.cadena@test.com"},
                              headers=_h(ADMIN))
            ids2 = [i["id"] for i in r2.json()["items"]]
            assert ids2 == [b]

            r3 = requests.get(f"{BASE_URL}/api/admin/deposits",
                              params={"user_q": "zzz_no_match_999"},
                              headers=_h(ADMIN))
            assert r3.json()["items"] == []
        finally:
            _db().deposits.delete_many({"id": {"$in": [a, b]}})


class TestIter166CapitalUnification:
    def test_vip_capital_deposit_creation_gone(self):
        r = requests.post(f"{BASE_URL}/api/vip/capital-deposits", headers=_h(VIP),
                          json={"amount": 100, "currency": "USDT",
                                "deposit_method": "crypto", "tx_hash": "0xabc123456789"})
        assert r.status_code == 410, r.text
        assert "unificaron" in r.json()["detail"]

    def test_capital_requests_moved_to_withdrawals_gate(self):
        r = requests.get(f"{BASE_URL}/api/admin/capital-requests",
                         headers=_h(EMP_WITHDRAWALS_TOKEN))
        assert r.status_code == 200, r.text

        r2 = requests.get(f"{BASE_URL}/api/admin/capital-requests",
                          headers=_h(EMP_ORDERS_TOKEN))
        assert r2.status_code == 403, r2.text

    def test_vip_capital_history_still_readable(self):
        r = requests.get(f"{BASE_URL}/api/vip/capital-deposits", headers=_h(VIP))
        assert r.status_code == 200, r.text


class TestHubPendingCount:
    def test_counts_shape_and_gate(self):
        r = requests.get(f"{BASE_URL}/api/admin/deposits-hub/pending-count",
                         headers=_h(EMP_WITHDRAWALS_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("deposits_pending", "requests_pending", "withdrawals_pending"):
            assert isinstance(body[k], int)

        r2 = requests.get(f"{BASE_URL}/api/admin/deposits-hub/pending-count",
                          headers=_h(EMP_ORDERS_TOKEN))
        assert r2.status_code == 403

        r3 = requests.get(f"{BASE_URL}/api/admin/deposits-hub/pending-count",
                          headers=_h(VIP))
        assert r3.status_code == 403

    def test_pending_count_reflects_seeded_deposit(self):
        db = _db()
        dep_id = f"dep_test163_{uuid.uuid4().hex[:8]}"
        db.deposits.insert_one({
            "id": dep_id, "user_id": "user_test_vip01",
            "user_email": "vip.test@resilience.com", "user_name": "VIP Test",
            "user_role": "vip", "currency": "USD", "amount": 10.0,
            "method": "transfer", "status": "pending",
            "created_at": "2026-06-01T00:00:00+00:00",
            "updated_at": "2026-06-01T00:00:00+00:00",
        })
        try:
            r = requests.get(f"{BASE_URL}/api/admin/deposits-hub/pending-count", headers=_h(ADMIN))
            assert r.status_code == 200
            assert r.json()["deposits_pending"] >= 1
        finally:
            db.deposits.delete_one({"id": dep_id})
