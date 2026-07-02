"""iter55.6 — Rate change and order status transitions must ALSO create in-app
notifications (not just OS push). This mirrors the operator report where a
client user had push enabled and the campanita badge was green, but the
"Notificaciones" inbox stayed empty ("Todo al día") after a rate change."""
import os
import uuid
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN, make_admin_totp


def _mongo():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _clear_inbox(user_id: str):
    _mongo().notifications.delete_many({"recipient_user_id": user_id})


class TestRateChangeInApp:
    """Rate change must land in every client's inbox, regardless of push status."""

    def test_vip_and_normal_receive_inapp(self):
        db = _mongo()
        _clear_inbox("user_test_vip01")
        _clear_inbox("user_test_normal01")
        # Fetch a rate and bump it
        r = requests.get(f"{BASE_URL}/api/rates", timeout=10)
        rate = r.json()[0]
        new_normal = float(rate["rate_normal"]) + 0.777
        new_vip = float(rate.get("rate_vip") or rate["rate_normal"]) + 0.888
        rr = requests.put(
            f"{BASE_URL}/api/admin/rates/{rate['id']}",
            json={
                "from_code": rate["from_code"],
                "to_code": rate["to_code"],
                "rate_normal": new_normal,
                "rate_vip": new_vip,
                "real_rate": rate.get("real_rate") or rate["rate_normal"],
                "totp_code": make_admin_totp(),
            },
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            timeout=15,
        )
        assert rr.status_code == 200, rr.text

        # VIP inbox
        vip_notif = db.notifications.find_one({
            "recipient_user_id": "user_test_vip01", "type": "rate_change"
        }, sort=[("created_at", -1)])
        assert vip_notif is not None, "VIP client should see the rate change in inbox"
        assert rate["from_code"] in vip_notif["title"]
        assert rate["to_code"] in vip_notif["title"]
        # VIP rate should be reflected in the message
        assert f"{new_vip:g}" in vip_notif["message"]

        # Normal client inbox
        normal_notif = db.notifications.find_one({
            "recipient_user_id": "user_test_normal01", "type": "rate_change"
        }, sort=[("created_at", -1)])
        assert normal_notif is not None
        assert f"{new_normal:g}" in normal_notif["message"]

    def test_admin_does_NOT_get_inbox_entry(self):
        db = _mongo()
        _clear_inbox("user_test_admin01")
        r = requests.get(f"{BASE_URL}/api/rates", timeout=10)
        rate = r.json()[0]
        rr = requests.put(
            f"{BASE_URL}/api/admin/rates/{rate['id']}",
            json={
                "from_code": rate["from_code"],
                "to_code": rate["to_code"],
                "rate_normal": float(rate["rate_normal"]) + 0.999,
                "rate_vip": float(rate.get("rate_vip") or rate["rate_normal"]) + 0.999,
                "real_rate": rate.get("real_rate") or rate["rate_normal"],
                "totp_code": make_admin_totp(),
            },
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            timeout=15,
        )
        assert rr.status_code == 200
        admin_notif = db.notifications.find_one({
            "recipient_user_id": "user_test_admin01", "type": "rate_change"
        })
        assert admin_notif is None, "Admin/staff should NOT receive rate-change inbox entries"

    def test_client_sees_it_via_api(self):
        _clear_inbox("user_test_vip01")
        # Trigger a change
        r = requests.get(f"{BASE_URL}/api/rates", timeout=10)
        rate = r.json()[0]
        requests.put(
            f"{BASE_URL}/api/admin/rates/{rate['id']}",
            json={
                "from_code": rate["from_code"],
                "to_code": rate["to_code"],
                "rate_normal": float(rate["rate_normal"]) + 0.123,
                "rate_vip": float(rate.get("rate_vip") or rate["rate_normal"]) + 0.123,
                "real_rate": rate.get("real_rate") or rate["rate_normal"],
                "totp_code": make_admin_totp(),
            },
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            timeout=15,
        )
        r = requests.get(
            f"{BASE_URL}/api/notifications",
            headers={"Authorization": f"Bearer {VIP_TOKEN}"},
            timeout=10,
        )
        assert r.status_code == 200
        items = r.json()["items"]
        assert any(x.get("type") == "rate_change" for x in items), \
            "Client's /notifications endpoint should include the rate_change entry"


class TestOrderStatusInApp:
    """Order status transitions must also create inbox entries."""

    def _seed_pending_order(self, user_id: str = "user_test_vip01") -> str:
        db = _mongo()
        from datetime import datetime, timezone
        oid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.orders.insert_one({
            "id": oid, "user_id": user_id,
            "user_email": "vip.test@resilience.com",
            "user_name": "Test VIP",
            "user_role": "vip",
            "from_code": "USDT", "to_code": "CUP",
            "amount_from": 10.0, "amount_to": 1500.0,
            "rate": 150.0, "real_rate": 150.0,
            "delivery_method": "transfer", "delivery_details": "test",
            "status": "pending",
            "created_at": now, "updated_at": now,
        })
        return oid

    def test_approved_transition_creates_inapp(self):
        db = _mongo()
        _clear_inbox("user_test_vip01")
        oid = self._seed_pending_order()
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/orders/{oid}/status",
                json={"status": "approved"},
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                timeout=15,
            )
            assert r.status_code == 200, r.text
            notif = db.notifications.find_one({
                "recipient_user_id": "user_test_vip01",
                "type": "order_approved",
                "data.order_id": oid,
            })
            assert notif is not None
            assert oid[:8] in notif["title"]
        finally:
            db.orders.delete_one({"id": oid})

    def test_completed_transition_creates_inapp(self):
        db = _mongo()
        _clear_inbox("user_test_vip01")
        oid = self._seed_pending_order()
        try:
            requests.put(
                f"{BASE_URL}/api/admin/orders/{oid}/status",
                json={"status": "approved"},
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                timeout=15,
            )
            r = requests.put(
                f"{BASE_URL}/api/admin/orders/{oid}/status",
                json={
                    "status": "completed",
                    "payout_proof_image": "data:image/png;base64,iVBORw0KGgo=",
                },
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                timeout=15,
            )
            assert r.status_code == 200, r.text
            notif = db.notifications.find_one({
                "recipient_user_id": "user_test_vip01",
                "type": "order_completed",
                "data.order_id": oid,
            })
            assert notif is not None
            assert "transferimos" in notif["message"].lower() or "1500" in notif["message"]
        finally:
            db.orders.delete_one({"id": oid})
