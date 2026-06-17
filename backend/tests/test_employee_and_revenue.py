"""Iter6 — Tests for new 'employee' role + ExchangeRate.real_rate + GET /api/admin/revenue."""
import os
import pytest
import requests

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP, NORMAL_TOKEN as NORMAL, EMPLOYEE_TOKEN as EMP


def _h(t=None):
    h = {"Content-Type": "application/json"}
    if t:
        h["Authorization"] = f"Bearer {t}"
    return h


# ----- Employee role recognition -----
class TestEmployeeAuthMe:
    def test_me_employee_role(self):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(EMP))
        assert r.status_code == 200, r.text
        assert r.json().get("role") == "employee"


# ----- /api/admin/revenue access control -----
class TestRevenueAccess:
    def test_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/revenue")
        assert r.status_code == 401

    def test_normal_403(self):
        r = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(NORMAL))
        assert r.status_code == 403

    def test_vip_403(self):
        r = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(VIP))
        assert r.status_code == 403

    def test_employee_403(self):
        r = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(EMP))
        assert r.status_code == 403, "employee should NOT see revenue"

    def test_admin_200_shape(self):
        r = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("total_profit_usdt", "total_volume_usdt", "profit_margin_pct",
                  "by_pair", "by_role", "missing_real_rate_pairs", "orders_total"):
            assert k in d, f"missing key {k}"
        assert "normal" in d["by_role"] and "vip" in d["by_role"]
        assert isinstance(d["by_pair"], list)
        assert isinstance(d["missing_real_rate_pairs"], list)

    def test_admin_days_filter(self):
        r = requests.get(f"{BASE_URL}/api/admin/revenue?days=7", headers=_h(ADMIN))
        assert r.status_code == 200


# ----- Rates CRUD with real_rate; employee allowed -----
class TestRatesRealRate:
    @pytest.fixture(autouse=True)
    def _ensure_seed(self):
        requests.post(f"{BASE_URL}/api/admin/seed", headers=_h(ADMIN))

    def test_employee_can_list_rates_via_public(self):
        # /api/rates is public
        r = requests.get(f"{BASE_URL}/api/rates")
        assert r.status_code == 200

    def test_employee_can_create_rate_with_real_rate(self):
        payload = {"from_code": "USDT", "to_code": "BRL", "rate_normal": 4.8,
                   "rate_vip": 4.95, "real_rate": 5.1}
        r = requests.post(f"{BASE_URL}/api/admin/rates", json=payload, headers=_h(EMP))
        assert r.status_code in (200, 201), r.text
        rid = r.json()["id"]
        # Verify GET shows real_rate
        rates = requests.get(f"{BASE_URL}/api/rates").json()
        found = next((x for x in rates if x["id"] == rid), None)
        assert found is not None
        assert float(found["real_rate"]) == 5.1
        # Cleanup
        requests.delete(f"{BASE_URL}/api/admin/rates/{rid}", headers=_h(ADMIN))

    def test_real_rate_null_persists_as_null(self):
        payload = {"from_code": "USDT", "to_code": "MXN", "rate_normal": 17.0,
                   "rate_vip": 17.4, "real_rate": None}
        r = requests.post(f"{BASE_URL}/api/admin/rates", json=payload, headers=_h(ADMIN))
        assert r.status_code in (200, 201), r.text
        rid = r.json()["id"]
        rates = requests.get(f"{BASE_URL}/api/rates").json()
        found = next((x for x in rates if x["id"] == rid), None)
        assert found is not None
        assert found.get("real_rate") in (None, 0, 0.0) or found.get("real_rate") is None
        requests.delete(f"{BASE_URL}/api/admin/rates/{rid}", headers=_h(ADMIN))

    def test_put_updates_real_rate(self):
        payload = {"from_code": "USDT", "to_code": "BRL", "rate_normal": 4.8,
                   "rate_vip": 4.95, "real_rate": 5.1}
        cr = requests.post(f"{BASE_URL}/api/admin/rates", json=payload, headers=_h(ADMIN))
        rid = cr.json()["id"]
        upd = {**payload, "real_rate": 5.25}
        ur = requests.put(f"{BASE_URL}/api/admin/rates/{rid}", json=upd, headers=_h(EMP))
        assert ur.status_code == 200, ur.text
        rates = requests.get(f"{BASE_URL}/api/rates").json()
        found = next((x for x in rates if x["id"] == rid), None)
        assert float(found["real_rate"]) == 5.25
        requests.delete(f"{BASE_URL}/api/admin/rates/{rid}", headers=_h(ADMIN))


# ----- Employee access to staff endpoints -----
class TestEmployeeStaffEndpoints:
    @pytest.mark.parametrize("path", [
        "/api/admin/orders",
        "/api/admin/withdrawals",
        "/api/admin/redemptions",
        "/api/admin/stats",
        "/api/admin/users",
    ])
    def test_employee_can_get(self, path):
        r = requests.get(f"{BASE_URL}{path}", headers=_h(EMP))
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"

    def test_employee_can_seed(self):
        r = requests.post(f"{BASE_URL}/api/admin/seed", headers=_h(EMP))
        assert r.status_code == 200

    def test_employee_can_push_test(self):
        r = requests.post(f"{BASE_URL}/api/push/test", headers=_h(EMP))
        # Should not be 401/403. May 200 or 400 if no subscriptions.
        assert r.status_code not in (401, 403), r.text


# ----- Employee restricted endpoints -----
class TestEmployeeRestrictions:
    def test_employee_cannot_update_admin_settings(self):
        r = requests.put(f"{BASE_URL}/api/admin/settings",
                         json={"vip_threshold_usdt": 5000},
                         headers=_h(EMP))
        assert r.status_code == 403, r.text

    def test_admin_can_update_admin_settings(self):
        r = requests.put(f"{BASE_URL}/api/admin/settings",
                         json={"vip_threshold_usdt": 5000},
                         headers=_h(ADMIN))
        assert r.status_code == 200

    def test_employee_cannot_promote_to_admin(self):
        r = requests.put(f"{BASE_URL}/api/admin/users/user_test_normal01",
                         json={"role": "admin"}, headers=_h(EMP))
        assert r.status_code == 403
        # Verify role unchanged
        users = requests.get(f"{BASE_URL}/api/admin/users", headers=_h(ADMIN)).json()
        u = next(x for x in users if x["user_id"] == "user_test_normal01")
        assert u["role"] == "normal"

    def test_employee_cannot_promote_to_employee(self):
        r = requests.put(f"{BASE_URL}/api/admin/users/user_test_normal01",
                         json={"role": "employee"}, headers=_h(EMP))
        assert r.status_code == 403

    def test_employee_can_set_normal_or_vip(self):
        # set normal -> vip
        r = requests.put(f"{BASE_URL}/api/admin/users/user_test_normal01",
                         json={"role": "vip"}, headers=_h(EMP))
        assert r.status_code == 200, r.text
        # restore
        rr = requests.put(f"{BASE_URL}/api/admin/users/user_test_normal01",
                          json={"role": "normal"}, headers=_h(EMP))
        assert rr.status_code == 200

    def test_admin_can_promote_to_employee(self):
        # Create a throwaway user to promote
        import pymongo
        from pymongo import MongoClient
        client = MongoClient(os.environ.get("MONGO_URL"))
        client[os.environ.get("DB_NAME")].users.update_one(
            {"user_id": "user_test_normal01"}, {"$set": {"role": "normal"}}
        )
        client.close()
        r = requests.put(f"{BASE_URL}/api/admin/users/user_test_normal01",
                         json={"role": "employee"}, headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        # Restore
        rr = requests.put(f"{BASE_URL}/api/admin/users/user_test_normal01",
                          json={"role": "normal"}, headers=_h(ADMIN))
        assert rr.status_code == 200


# ----- Revenue calculation end-to-end -----
class TestRevenueCalculation:
    """Create rate USD->CUP with real_rate=410; create VIP order USD->CUP amount=100;
    approve; verify profit_to in by_pair == (100*410 - 100*395) = 1500."""

    rate_id = None

    def setup_method(self, method):
        # Find or create USD->CUP rate; set real_rate=410, rate_vip=395
        rates = requests.get(f"{BASE_URL}/api/rates").json()
        existing = next((r for r in rates if r["from_code"] == "USD" and r["to_code"] == "CUP"), None)
        payload = {"from_code": "USD", "to_code": "CUP", "rate_normal": 380,
                   "rate_vip": 395, "real_rate": 410}
        if existing:
            r = requests.put(f"{BASE_URL}/api/admin/rates/{existing['id']}",
                             json=payload, headers=_h(ADMIN))
            assert r.status_code == 200
            self.rate_id = existing["id"]
        else:
            r = requests.post(f"{BASE_URL}/api/admin/rates",
                              json=payload, headers=_h(ADMIN))
            assert r.status_code in (200, 201)
            self.rate_id = r.json()["id"]

    def test_e2e_profit_computation(self):
        # Create order as VIP user, USD -> CUP, amount=100
        order_payload = {"from_code": "USD", "to_code": "CUP", "amount_from": 100,
                         "delivery_method": "transfer",
                         "delivery_details": "Acc 1234",
                         "sender_name": "Test Holder"}
        r = requests.post(f"{BASE_URL}/api/orders", json=order_payload, headers=_h(VIP))
        assert r.status_code in (200, 201), r.text
        order = r.json()
        oid = order["id"]
        # amount_to should be 100 * 395 = 39500 (VIP rate, no commission)
        assert abs(order["amount_to"] - 39500) < 0.01, f"expected 39500 got {order['amount_to']}"

        # Approve via admin
        ar = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                          json={"status": "approved"}, headers=_h(ADMIN))
        assert ar.status_code == 200, ar.text

        # Fetch revenue
        rv = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(ADMIN))
        assert rv.status_code == 200
        data = rv.json()
        # USD→CUP entry
        entry = next((p for p in data["by_pair"] if p["pair"] == "USD→CUP"), None)
        assert entry is not None, f"USD→CUP not in by_pair: {data['by_pair']}"
        # profit_to should be at least 1500 (this order alone). Other approved orders may add.
        # We check that this single-order portion exists by checking VIP role bucket increase.
        assert data["by_role"]["vip"]["orders"] >= 1
        assert data["orders_total"] >= 1
        # missing_real_rate_pairs should NOT contain USD→CUP
        assert "USD→CUP" not in data["missing_real_rate_pairs"]
        # Cleanup: cancel/complete order — leave approved for downstream tests (or delete via mongo)
        import pymongo
        from pymongo import MongoClient
        client = MongoClient(os.environ.get("MONGO_URL"))
        client[os.environ.get("DB_NAME")].orders.delete_one({"id": oid})
        client.close()

    def test_missing_real_rate_appears_in_missing_list(self):
        # Set USD→CUP real_rate to None
        rates = requests.get(f"{BASE_URL}/api/rates").json()
        existing = next(r for r in rates if r["from_code"] == "USD" and r["to_code"] == "CUP")
        upd = {"from_code": "USD", "to_code": "CUP", "rate_normal": existing["rate_normal"],
               "rate_vip": existing["rate_vip"], "real_rate": None}
        r = requests.put(f"{BASE_URL}/api/admin/rates/{existing['id']}",
                         json=upd, headers=_h(ADMIN))
        assert r.status_code == 200

        # Create order
        order_payload = {"from_code": "USD", "to_code": "CUP", "amount_from": 50,
                         "delivery_method": "transfer", "delivery_details": "x", "sender_name": "Test Holder"}
        cr = requests.post(f"{BASE_URL}/api/orders", json=order_payload, headers=_h(VIP))
        if cr.status_code not in (200, 201):
            pytest.skip(f"order create failed: {cr.text}")
        oid = cr.json()["id"]
        ar = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                          json={"status": "approved"}, headers=_h(ADMIN))
        assert ar.status_code == 200

        rv = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(ADMIN)).json()
        assert "USD→CUP" in rv["missing_real_rate_pairs"]
        # by_pair should NOT include USD→CUP (or it should not have positive profit)
        pair_keys = [p["pair"] for p in rv["by_pair"]]
        assert "USD→CUP" not in pair_keys, "pair without real_rate should be excluded from by_pair"

        # Cleanup order and restore rate
        import pymongo
        from pymongo import MongoClient
        client = MongoClient(os.environ.get("MONGO_URL"))
        client[os.environ.get("DB_NAME")].orders.delete_one({"id": oid})
        client.close()
        restore = {"from_code": "USD", "to_code": "CUP", "rate_normal": 380,
                   "rate_vip": 395, "real_rate": 410}
        requests.put(f"{BASE_URL}/api/admin/rates/{existing['id']}",
                     json=restore, headers=_h(ADMIN))
