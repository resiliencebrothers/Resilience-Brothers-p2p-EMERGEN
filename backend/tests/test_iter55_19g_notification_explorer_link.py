"""iter55.19g — Order completed notification enriched with explorer link.

When an order is marked completed with method=crypto and a payout_tx_hash is
recorded, the in-app notification carries an `explorer_url` + `crypto_network`
so the frontend can render a "Verificar en Tronscan / BscScan" button.
"""
import os
import uuid
import pytest
from pymongo import MongoClient

from tests.conftest import ADMIN_TOKEN, BASE_URL
import requests


API = f"{BASE_URL}/api"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_completed_order_with_hash(delivery_details: str, tx_hash: str,
                                     to_code: str = "USDT"):
    db = _sync_db()
    oid = uuid.uuid4().hex
    db.orders.insert_one({
        "id": oid,
        "user_id": "user_test_vip01",
        "user_name": "VIP Test",
        "user_email": "vip.test@resilience.com",
        "from_code": "USD",
        "to_code": to_code,
        "amount_from": 100,
        "amount_to": 100,
        "rate_applied": 1.0,
        "commission_percent": 0,
        "delivery_method": "crypto",
        "delivery_details": delivery_details,
        "sender_name": "VIP Test",
        "status": "approved",
        "admin_note": "",
        "proof_image": "",
        "payout_proof_image": "",
        "payout_tx_hash": "",
        "created_at": "2026-07-10T13:00:00+00:00",
    })
    return oid


def _cleanup(oid: str):
    db = _sync_db()
    db.orders.delete_one({"id": oid})
    db.notifications.delete_many({"data.order_id": oid})


def test_completed_crypto_order_notification_carries_explorer_url_trc20():
    oid = _seed_completed_order_with_hash(
        delivery_details="TJRabRWQdrJc7iCPFy4gnPCJcXbc17ncCk",
        tx_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
    )
    # Admin marks the order as completed with a tx_hash
    r = requests.put(
        f"{API}/admin/orders/{oid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json={
            "status": "completed",
            "payout_tx_hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
        },
    )
    assert r.status_code == 200, r.text
    # Fetch the notification that was fanned out to the client
    db = _sync_db()
    notif = db.notifications.find_one({"data.order_id": oid, "type": "order_completed"})
    assert notif is not None, "no in-app notification was created"
    data = notif["data"]
    assert data.get("payout_tx_hash") == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
    assert data.get("crypto_network") == "TRC20"
    assert data.get("explorer_url", "").startswith("https://tronscan.org/#/transaction/")
    _cleanup(oid)


def test_completed_crypto_order_notification_bep20_hint():
    # Delivery details explicitly declare BEP20 → notif should link to BscScan
    oid = _seed_completed_order_with_hash(
        delivery_details="0x1234567890abcdef1234567890abcdef12345678 · red BEP20",
        tx_hash="0xabcdef123456789012345678901234567890abcdef123456789012345678901234",
    )
    r = requests.put(
        f"{API}/admin/orders/{oid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json={
            "status": "completed",
            "payout_tx_hash": "0xabcdef123456789012345678901234567890abcdef123456789012345678901234",
        },
    )
    assert r.status_code == 200, r.text
    db = _sync_db()
    notif = db.notifications.find_one({"data.order_id": oid, "type": "order_completed"})
    assert notif is not None
    assert notif["data"].get("crypto_network") == "BEP20"
    assert notif["data"].get("explorer_url", "").startswith("https://bscscan.com/tx/")
    _cleanup(oid)


def test_completed_crypto_order_without_hash_has_no_explorer_url():
    """Legacy path: if the admin still hasn't pasted a hash (e.g. transfer
    method previously used), the notification must NOT include an explorer_url
    key so the UI hides the button cleanly."""
    # For this we'd need to allow completing without hash; but backend requires
    # at least hash OR proof for crypto. So we seed a proof-only completion.
    oid = _seed_completed_order_with_hash(
        delivery_details="TJRabRWQdrJc7iCPFy4gnPCJcXbc17ncCk",
        tx_hash="",
    )
    r = requests.put(
        f"{API}/admin/orders/{oid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json={
            "status": "completed",
            "payout_proof_image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
        },
    )
    assert r.status_code == 200, r.text
    db = _sync_db()
    notif = db.notifications.find_one({"data.order_id": oid, "type": "order_completed"})
    assert notif is not None
    assert "explorer_url" not in notif["data"]
    _cleanup(oid)
