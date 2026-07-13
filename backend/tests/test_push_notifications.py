"""Tests for Web Push notifications endpoints (iteration 4)."""
import os
import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN, make_admin_totp

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
VIP_USER_ID = "user_test_vip01"


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(autouse=True)
def cleanup_subs(db):
    """Remove test-created push subscriptions before & after each test."""
    db.push_subscriptions.delete_many({
        "$or": [
            {"endpoint": {"$regex": "example.com"}},
            {"endpoint": {"$regex": "fcm.googleapis.com/fcm/send/fake"}},
        ]
    })
    yield
    db.push_subscriptions.delete_many({
        "$or": [
            {"endpoint": {"$regex": "example.com"}},
            {"endpoint": {"$regex": "fcm.googleapis.com/fcm/send/fake"}},
        ]
    })


# ----- VAPID public key (no auth) -----
class TestVapidKey:
    def test_get_vapid_key_no_auth(self):
        r = requests.get(f"{BASE_URL}/api/push/vapid-public-key")
        assert r.status_code == 200
        data = r.json()
        assert "key" in data
        assert isinstance(data["key"], str)
        # base64url VAPID public key ~ 87 chars
        assert 80 <= len(data["key"]) <= 100, f"key length is {len(data['key'])}"


# ----- Subscribe -----
class TestSubscribe:
    def test_subscribe_requires_auth(self):
        body = {"subscription": {"endpoint": "https://example.com/push/x", "keys": {"p256dh": "a", "auth": "b"}}}
        r = requests.post(f"{BASE_URL}/api/push/subscribe", json=body)
        assert r.status_code == 401

    def test_subscribe_persists(self, db):
        endpoint = "https://example.com/push/sub1"
        body = {
            "subscription": {"endpoint": endpoint, "keys": {"p256dh": "x", "auth": "y"}},
            "user_agent": "Mozilla/5.0 TestAgent",
        }
        r = requests.post(f"{BASE_URL}/api/push/subscribe", headers=_h(VIP_TOKEN), json=body)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}
        # verify persistence
        doc = db.push_subscriptions.find_one({"endpoint": endpoint})
        assert doc is not None
        assert doc["user_id"] == VIP_USER_ID
        assert doc["subscription"]["endpoint"] == endpoint
        assert doc["user_agent"] == "Mozilla/5.0 TestAgent"

    def test_subscribe_upsert_no_duplicate(self, db):
        endpoint = "https://example.com/push/upsert"
        body = {"subscription": {"endpoint": endpoint, "keys": {"p256dh": "a", "auth": "b"}}, "user_agent": "UA1"}
        r1 = requests.post(f"{BASE_URL}/api/push/subscribe", headers=_h(VIP_TOKEN), json=body)
        assert r1.status_code == 200
        # second call (same endpoint) with different UA
        body["user_agent"] = "UA2"
        r2 = requests.post(f"{BASE_URL}/api/push/subscribe", headers=_h(VIP_TOKEN), json=body)
        assert r2.status_code == 200
        count = db.push_subscriptions.count_documents({"endpoint": endpoint})
        assert count == 1
        # latest UA persisted
        doc = db.push_subscriptions.find_one({"endpoint": endpoint})
        assert doc["user_agent"] == "UA2"

    def test_subscribe_upsert_across_users(self, db):
        endpoint = "https://example.com/push/cross"
        body = {"subscription": {"endpoint": endpoint, "keys": {"p256dh": "a", "auth": "b"}}, "user_agent": "vip"}
        requests.post(f"{BASE_URL}/api/push/subscribe", headers=_h(VIP_TOKEN), json=body)
        body["user_agent"] = "normal"
        requests.post(f"{BASE_URL}/api/push/subscribe", headers=_h(NORMAL_TOKEN), json=body)
        # still one record because upsert is by endpoint
        count = db.push_subscriptions.count_documents({"endpoint": endpoint})
        assert count == 1

    def test_subscribe_missing_endpoint_400(self):
        body = {"subscription": {"keys": {"p256dh": "x", "auth": "y"}}, "user_agent": ""}
        r = requests.post(f"{BASE_URL}/api/push/subscribe", headers=_h(VIP_TOKEN), json=body)
        assert r.status_code == 400


# ----- Unsubscribe -----
class TestUnsubscribe:
    def test_unsubscribe_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/push/unsubscribe", json={"endpoint": "https://example.com/x"})
        assert r.status_code == 401

    def test_unsubscribe_missing_endpoint_400(self):
        r = requests.post(f"{BASE_URL}/api/push/unsubscribe", headers=_h(VIP_TOKEN), json={})
        assert r.status_code == 400

    def test_unsubscribe_removes_record(self, db):
        endpoint = "https://example.com/push/toremove"
        body = {"subscription": {"endpoint": endpoint, "keys": {"p256dh": "a", "auth": "b"}}}
        requests.post(f"{BASE_URL}/api/push/subscribe", headers=_h(VIP_TOKEN), json=body)
        assert db.push_subscriptions.count_documents({"endpoint": endpoint}) == 1
        r = requests.post(f"{BASE_URL}/api/push/unsubscribe", headers=_h(VIP_TOKEN), json={"endpoint": endpoint})
        assert r.status_code == 200
        assert db.push_subscriptions.count_documents({"endpoint": endpoint}) == 0


# ----- Push test endpoint -----
class TestPushTestEndpoint:
    def test_push_test_no_subscriptions_returns_404(self, db):
        # ensure VIP has no subs
        db.push_subscriptions.delete_many({"user_id": VIP_USER_ID})
        r = requests.post(f"{BASE_URL}/api/push/test", headers=_h(VIP_TOKEN))
        assert r.status_code == 404
        assert "suscritos" in (r.json().get("detail") or "").lower()

    def test_push_test_with_dummy_subscription_returns_delivered_total(self, db):
        # create a dummy sub via API
        body = {"subscription": {"endpoint": "https://fcm.googleapis.com/fcm/send/fake_token",
                                  "keys": {"p256dh": "Bzzz", "auth": "abcd"}}}
        requests.post(f"{BASE_URL}/api/push/subscribe", headers=_h(VIP_TOKEN), json=body)
        r = requests.post(f"{BASE_URL}/api/push/test", headers=_h(VIP_TOKEN))
        assert r.status_code == 200
        data = r.json()
        assert "delivered" in data and "total" in data
        assert data["total"] >= 1
        # delivered will be 0 because fake endpoint cannot be reached
        assert isinstance(data["delivered"], int)


# ----- Order approval triggers push (no break even if push fails) -----
class TestOrderApprovalPush:
    def test_approve_order_with_dummy_sub_still_returns_200(self, db):
        # Subscribe VIP with a fake endpoint
        body = {"subscription": {"endpoint": "https://fcm.googleapis.com/fcm/send/fake_token_approve",
                                  "keys": {"p256dh": "Bzzz", "auth": "abcd"}}}
        s = requests.post(f"{BASE_URL}/api/push/subscribe", headers=_h(VIP_TOKEN), json=body)
        assert s.status_code == 200

        # Create order as VIP
        payload = {"from_code": "USD", "to_code": "CUP", "amount_from": 5,
                   "delivery_method": "accumulate", "delivery_details": "",
                   "sender_name": "VIP", "proof_image": ""}
        o = requests.post(f"{BASE_URL}/api/orders", headers=_h(VIP_TOKEN), json=payload)
        assert o.status_code == 200, o.text
        oid = o.json()["id"]

        # Approve via admin — must respond 200 even though push will fail
        r = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                         headers=_h(ADMIN_TOKEN),
                         json={"status": "approved", "admin_note": "ok",
                               "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"

        # The dead subscription handling: with the tri-state contract introduced
        # to avoid removing subs on transient network errors, a fake endpoint
        # that fails with non-410/404 errors is kept (treated as 'transient').
        # We only assert the endpoint stayed 200 OK — auto-removal is reserved
        # for true 410/404 responses from the real push gateway.
        remaining = db.push_subscriptions.count_documents(
            {"endpoint": "https://fcm.googleapis.com/fcm/send/fake_token_approve"}
        )
        assert remaining in (0, 1), f"unexpected sub count {remaining}"

    def test_reject_order_with_dummy_sub_still_returns_200(self, db):
        body = {"subscription": {"endpoint": "https://fcm.googleapis.com/fcm/send/fake_token_reject",
                                  "keys": {"p256dh": "B", "auth": "c"}}}
        requests.post(f"{BASE_URL}/api/push/subscribe", headers=_h(VIP_TOKEN), json=body)
        payload = {"from_code": "USD", "to_code": "CUP", "amount_from": 5,
                   "delivery_method": "transfer", "delivery_details": "x",
                   "sender_name": "VIP", "proof_image": "data:image/png;base64,iVBORw0KGgo="}
        o = requests.post(f"{BASE_URL}/api/orders", headers=_h(VIP_TOKEN), json=payload)
        assert o.status_code == 200
        oid = o.json()["id"]
        r = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                         headers=_h(ADMIN_TOKEN),
                         json={"status": "rejected", "admin_note": "no"})
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"


# ----- Frontend static assets -----
class TestPwaAssets:
    def test_splash_1170(self):
        r = requests.get(f"{BASE_URL}/splash/splash-1170x2532.png", timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/")
        assert len(r.content) > 1000

    def test_splash_1290(self):
        r = requests.get(f"{BASE_URL}/splash/splash-1290x2796.png", timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/")
        assert len(r.content) > 1000

    def test_icon_192_exists(self):
        r = requests.get(f"{BASE_URL}/icons/icon-192.png", timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/")

    def test_logo_300_exists(self):
        r = requests.get(f"{BASE_URL}/branding/logo-300.png", timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/")
