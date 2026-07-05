"""iter55.8 — Operator reproduced: when the admin completes an order and the
client opens the "payout proof" image in a new tab, they get 403 "No
autorizado". Root cause: `routes.files._can_access` was checking
`orders.proof_image` (deposit proof) and `withdrawals.payout_proof_image`,
but NOT `orders.payout_proof_image` (the field where staff attach the
transfer/cash receipt when completing a P2P order).

Fix: also allow access when the key matches the user's own order's
`payout_proof_image`.
"""
import os
import uuid
import base64
import requests
from datetime import datetime, timezone

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN


def _mongo():
    from pymongo import MongoClient
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP8//8/AwAI/AL+HHkYhwAAAABJRU5ErkJggg=="
)


class TestPayoutProofAccess:
    def test_owner_can_open_payout_proof(self):
        """Seed an order for VIP user with a payout_proof_image reference,
        then attempt to fetch it as the VIP user themselves."""
        db = _mongo()
        # Upload a fake object first by inserting a matching order that
        # references a hypothetical file. Because `storage.get_object_bytes`
        # will 404 if the object doesn't exist in R2, we mock this at the
        # DB level and confirm access-check passes (403 vs 404).
        oid = str(uuid.uuid4())
        fake_key = f"orders/2026/03/01/{oid}.png"
        db.orders.insert_one({
            "id": oid,
            "user_id": "user_test_vip01",
            "from_code": "USDT", "to_code": "CUP",
            "amount_from": 10.0, "amount_to": 7000.0,
            "rate": 700.0, "real_rate": 700.0,
            "delivery_method": "transfer",
            "status": "completed",
            "payout_proof_image": f"/api/files/{fake_key}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            r = requests.get(
                f"{BASE_URL}/api/files/{fake_key}",
                headers={"Authorization": f"Bearer {VIP_TOKEN}"},
                timeout=15,
            )
            # Access-check must pass → we either get 200 (if the object
            # exists in R2) or 404 (not found in bucket). NEVER 403.
            assert r.status_code != 403, (
                f"iter55.8 regression: client got 403 opening THEIR OWN payout proof. "
                f"body={r.text}"
            )
        finally:
            db.orders.delete_one({"id": oid})

    def test_non_owner_still_blocked(self):
        """A different client must NOT be able to fetch someone else's payout
        proof — the ownership check must still reject them."""
        db = _mongo()
        oid = str(uuid.uuid4())
        fake_key = f"orders/2026/03/01/{oid}.png"
        db.orders.insert_one({
            "id": oid,
            "user_id": "user_test_vip01",  # owned by VIP
            "from_code": "USDT", "to_code": "CUP",
            "amount_from": 10.0, "amount_to": 7000.0,
            "rate": 700.0, "real_rate": 700.0,
            "delivery_method": "transfer",
            "status": "completed",
            "payout_proof_image": f"/api/files/{fake_key}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            r = requests.get(
                f"{BASE_URL}/api/files/{fake_key}",
                headers={"Authorization": f"Bearer {NORMAL_TOKEN}"},
                timeout=15,
            )
            assert r.status_code == 403, r.text
        finally:
            db.orders.delete_one({"id": oid})

    def test_staff_always_bypasses_check(self):
        db = _mongo()
        oid = str(uuid.uuid4())
        fake_key = f"orders/2026/03/01/{oid}.png"
        db.orders.insert_one({
            "id": oid,
            "user_id": "user_test_vip01",
            "from_code": "USDT", "to_code": "CUP",
            "amount_from": 10.0, "amount_to": 7000.0,
            "rate": 700.0, "real_rate": 700.0,
            "delivery_method": "transfer",
            "status": "completed",
            "payout_proof_image": f"/api/files/{fake_key}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            r = requests.get(
                f"{BASE_URL}/api/files/{fake_key}",
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                timeout=15,
            )
            # Admin passes the access check regardless of the key
            assert r.status_code != 403
        finally:
            db.orders.delete_one({"id": oid})
