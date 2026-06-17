"""Iter5 tests: admin settings (VIP threshold) + admin alert hooks resilience."""
import os
import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


# ---------- /api/admin/settings ----------
class TestAdminSettings:
    def test_get_settings_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/settings")
        assert r.status_code == 401

    def test_get_settings_normal_403(self):
        r = requests.get(f"{BASE_URL}/api/admin/settings", headers=_h(NORMAL_TOKEN))
        assert r.status_code == 403

    def test_get_settings_admin_default(self):
        r = requests.get(f"{BASE_URL}/api/admin/settings", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        data = r.json()
        assert "vip_threshold_usdt" in data
        assert isinstance(data["vip_threshold_usdt"], (int, float))

    def test_put_settings_normal_403(self):
        r = requests.put(f"{BASE_URL}/api/admin/settings",
                         headers=_h(NORMAL_TOKEN),
                         json={"vip_threshold_usdt": 3000})
        assert r.status_code == 403

    def test_put_settings_admin_persists(self):
        r = requests.put(f"{BASE_URL}/api/admin/settings",
                         headers=_h(ADMIN_TOKEN),
                         json={"vip_threshold_usdt": 3000})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert data.get("vip_threshold_usdt") == 3000
        # Verify via GET
        g = requests.get(f"{BASE_URL}/api/admin/settings", headers=_h(ADMIN_TOKEN))
        assert g.json()["vip_threshold_usdt"] == 3000
        # Restore to 5000
        requests.put(f"{BASE_URL}/api/admin/settings",
                     headers=_h(ADMIN_TOKEN),
                     json={"vip_threshold_usdt": 5000})

    def test_put_settings_invalid_payload_422(self):
        r = requests.put(f"{BASE_URL}/api/admin/settings",
                         headers=_h(ADMIN_TOKEN),
                         json={"vip_threshold_usdt": "not-a-number-abc"})
        # pydantic v2 returns 422
        assert r.status_code == 422


# ---------- Alert hooks should not break endpoints ----------
class TestAlertHooksNonBreaking:
    def test_create_order_still_200(self):
        # Order creation should work even though notify_all_admins is called
        rates = requests.get(f"{BASE_URL}/api/rates").json()
        assert rates, "rates seed missing"
        # pick any active rate
        rate = next((r for r in rates if r["from_code"] == "USD" and r["to_code"] == "CUP"), rates[0])
        payload = {
            "from_code": rate["from_code"], "to_code": rate["to_code"],
            "amount_from": 5, "delivery_method": "transfer",
            "delivery_details": "x", "sender_name": "Tester", "proof_image": "",
        }
        r = requests.post(f"{BASE_URL}/api/orders", headers=_h(NORMAL_TOKEN), json=payload)
        assert r.status_code == 200, r.text

    def test_vip_withdraw_still_200(self, db):
        # ensure VIP has balance
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$set": {"vip_balance_usd": 100.0}})
        r = requests.post(f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP_TOKEN),
                          json={"amount_usd": 5, "method": "transfer", "details": "Bank Y", "beneficiary_name": "Test Holder"})
        assert r.status_code == 200, r.text

    def test_vip_redeem_still_200(self, db):
        prods = requests.get(f"{BASE_URL}/api/products").json()
        if not prods:
            pytest.skip("no products")
        cheap = min(prods, key=lambda p: p["price_usd"])
        # Top up balance
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$set": {"vip_balance_usd": cheap["price_usd"] + 50}})
        r = requests.post(f"{BASE_URL}/api/vip/redeem", headers=_h(VIP_TOKEN),
                          json={"product_id": cheap["id"], "quantity": 1, "delivery_address": "Addr"})
        assert r.status_code == 200, r.text


# ---------- VIP threshold alert flow ----------
class TestVipThresholdAlert:
    def test_threshold_crossing_sets_last_vip_alert_threshold(self, db):
        # Reset VIP state and ensure threshold = 5000
        requests.put(f"{BASE_URL}/api/admin/settings", headers=_h(ADMIN_TOKEN),
                     json={"vip_threshold_usdt": 5000})
        # Seed user state: vip_balances.USD = 4900, last_vip_alert_threshold = 0
        db.users.update_one(
            {"user_id": "user_test_vip01"},
            {"$set": {
                "vip_balances": {"USD": 4900.0},
                "vip_balance_usd": 0.0,
                "last_vip_alert_threshold": 0.0,
            }}
        )
        # Create accumulate USD->USD-like order? Need to use a rate; safest: use USD->CUP and credit CUP
        # But threshold check totals across all balances in USDT, so we can simply credit USD
        # by creating a USDT->USD accumulate order. Let's just bump via update + create a tiny accumulate.
        # Easier: directly add to USD via API order USD->USD if seed; otherwise bump balance to 5100 then trigger an approve.
        # We'll create a minimal accumulate USD->CUP order of 1 USD then approve. CUP credit won't push USDT >5000 alone,
        # so instead we'll pre-set balances to 4900 USD and add 200 USD by direct DB update + approve order to fire the path.
        # The threshold logic ONLY runs inside update_order_status; so we still must have an order approved.
        # Plan: insert balances 4900 USD, create accumulate order USD->CUP for 1 USD,
        # then before approval set balances to {"USD": 5100} so when we approve, total_usdt becomes >=5000.
        rates = requests.get(f"{BASE_URL}/api/rates").json()
        rate = next((r for r in rates if r["from_code"] == "USD" and r["to_code"] == "CUP"), None)
        if not rate:
            pytest.skip("USD->CUP rate not seeded")
        order_payload = {
            "from_code": "USD", "to_code": "CUP", "amount_from": 1,
            "delivery_method": "accumulate", "delivery_details": "",
            "sender_name": "VIP", "proof_image": "",
        }
        r = requests.post(f"{BASE_URL}/api/orders", headers=_h(VIP_TOKEN), json=order_payload)
        assert r.status_code == 200
        oid = r.json()["id"]
        # Bump balance over threshold BEFORE approval
        db.users.update_one(
            {"user_id": "user_test_vip01"},
            {"$set": {"vip_balances": {"USD": 5100.0}, "last_vip_alert_threshold": 0.0}}
        )
        # Approve order → triggers threshold check; total_usdt ≈ 5100 (USD) + small CUP credit
        r2 = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                          headers=_h(ADMIN_TOKEN),
                          json={"status": "approved", "admin_note": "ok"})
        assert r2.status_code == 200
        # Verify last_vip_alert_threshold was updated
        u = db.users.find_one({"user_id": "user_test_vip01"})
        assert u.get("last_vip_alert_threshold", 0) >= 5000

    def test_threshold_does_not_refire_on_small_increment(self, db):
        # last_vip_alert_threshold should now be ~5100+. Create another tiny accumulate order, approve,
        # and verify it does NOT lower last_vip_alert_threshold (no spam path).
        before = db.users.find_one({"user_id": "user_test_vip01"}).get("last_vip_alert_threshold", 0)
        order_payload = {
            "from_code": "USD", "to_code": "CUP", "amount_from": 1,
            "delivery_method": "accumulate", "delivery_details": "",
            "sender_name": "VIP", "proof_image": "",
        }
        r = requests.post(f"{BASE_URL}/api/orders", headers=_h(VIP_TOKEN), json=order_payload)
        oid = r.json()["id"]
        r2 = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                          headers=_h(ADMIN_TOKEN),
                          json={"status": "approved", "admin_note": "ok"})
        assert r2.status_code == 200
        after = db.users.find_one({"user_id": "user_test_vip01"}).get("last_vip_alert_threshold", 0)
        # value should not decrease (only updates if total_usdt > last_alert)
        assert after >= before
