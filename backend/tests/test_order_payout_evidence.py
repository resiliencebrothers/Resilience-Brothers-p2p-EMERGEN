"""iter41: Order payout evidence — staff/admin uploads the proof of the
payment made TO the client when completing an order.

Covers:
- transfer method: requires `payout_proof_image` when marking 'completed'.
- crypto method: requires `payout_tx_hash` OR `payout_proof_image`.
- cash method: exempt — no artefact required.
- accumulate method: exempt — the balance stays in the client's VIP wallet.
- Order document persists `payout_proof_image` / `payout_tx_hash`.
- Marking from another status (e.g. pending → approved) does NOT require evidence.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, make_admin_totp


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


def _seed_order(db, method: str = "transfer") -> str:
    oid = "order_payout_test_" + uuid.uuid4().hex[:8]
    db.orders.insert_one({
        "id": oid,
        "user_id": "user_test_normal",
        "user_email": "normal.test@resilience.com",
        "user_name": "Normal Test",
        "user_role": "normal",
        "from_code": "USDT",
        "to_code": "CUP",
        "amount_from": 100.0,
        "amount_to": 39000.0,
        "rate_applied": 390.0,
        "commission_percent": 0.0,
        "delivery_method": method,
        "delivery_details": "Cuenta BPA 9202 ... 1234",
        "sender_name": "Cliente Test",
        "proof_image": "",
        "payout_proof_image": "",
        "payout_tx_hash": "",
        "status": "approved",
        "admin_note": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return oid


# 1x1 transparent PNG, base64 — used as a real-looking proof_image
_TINY_PNG_B64 = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


class TestOrderPayoutEvidence:
    def test_transfer_completed_requires_payout_proof(self, db):
        oid = _seed_order(db, method="transfer")
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/orders/{oid}/status",
                headers=_h(ADMIN_TOKEN),
                json={"status": "completed", "admin_note": "",
                      "totp_code": make_admin_totp()},
            )
            assert r.status_code == 400
            assert "captura" in r.text.lower()
        finally:
            db.orders.delete_one({"id": oid})

    def test_transfer_completed_with_proof_succeeds(self, db):
        oid = _seed_order(db, method="transfer")
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/orders/{oid}/status",
                headers=_h(ADMIN_TOKEN),
                json={"status": "completed", "admin_note": "",
                      "totp_code": make_admin_totp(),
                      "payout_proof_image": _TINY_PNG_B64},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "completed"
            assert body["payout_proof_image"]  # persisted (either URL or base64)
            # Mongo doc reflects the field
            doc = db.orders.find_one({"id": oid}, {"_id": 0})
            assert doc["payout_proof_image"]
        finally:
            db.orders.delete_one({"id": oid})

    def test_crypto_completed_requires_hash_or_proof(self, db):
        oid = _seed_order(db, method="crypto")
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/orders/{oid}/status",
                headers=_h(ADMIN_TOKEN),
                json={"status": "completed", "totp_code": make_admin_totp()},
            )
            assert r.status_code == 400
            assert "hash" in r.text.lower() or "captura" in r.text.lower()
        finally:
            db.orders.delete_one({"id": oid})

    def test_crypto_completed_with_only_tx_hash_succeeds(self, db):
        oid = _seed_order(db, method="crypto")
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/orders/{oid}/status",
                headers=_h(ADMIN_TOKEN),
                json={"status": "completed", "totp_code": make_admin_totp(),
                      "payout_tx_hash": "0xabcdef0123456789"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["payout_tx_hash"] == "0xabcdef0123456789"
        finally:
            db.orders.delete_one({"id": oid})

    def test_cash_completed_no_payout_evidence_required(self, db):
        oid = _seed_order(db, method="cash")
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/orders/{oid}/status",
                headers=_h(ADMIN_TOKEN),
                json={"status": "completed", "totp_code": make_admin_totp()},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "completed"
        finally:
            db.orders.delete_one({"id": oid})

    def test_accumulate_completed_no_payout_evidence_required(self, db):
        oid = _seed_order(db, method="accumulate")
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/orders/{oid}/status",
                headers=_h(ADMIN_TOKEN),
                json={"status": "completed", "totp_code": make_admin_totp()},
            )
            assert r.status_code == 200, r.text
        finally:
            db.orders.delete_one({"id": oid})

    def test_transfer_approved_does_not_require_proof(self, db):
        """Only transition INTO 'completed' triggers the check; intermediate
        approvals still flow through without artefact."""
        oid = _seed_order(db, method="transfer")
        # Reset back to pending so we can move to approved
        db.orders.update_one({"id": oid}, {"$set": {"status": "pending"}})
        try:
            r = requests.put(
                f"{BASE_URL}/api/admin/orders/{oid}/status",
                headers=_h(ADMIN_TOKEN),
                json={"status": "approved", "totp_code": make_admin_totp()},
            )
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "approved"
        finally:
            db.orders.delete_one({"id": oid})
