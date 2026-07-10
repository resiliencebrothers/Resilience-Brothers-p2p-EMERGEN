"""iter55.19h — TX hash format validation vs declared network.

Covers:
1. Pure predicates: is_tx_hash_valid_for_network + detect_hash_family
2. Cross-family rejection: TRC20 hash on BEP20 withdrawal → 400
3. Well-formed hash matching declared network → accepted
4. Order flow: crypto order with delivery_details declaring TRC20 → wrong hash rejected
5. Regression: non-crypto withdrawals ignore the guard
"""
import os
import uuid
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, with_totp_admin, make_vip_totp

from services.crypto_networks import (
    is_tx_hash_valid_for_network,
    detect_hash_family,
    tx_hash_mismatch_reason,
)


API = f"{BASE_URL}/api"

# Real-shape (non-live) hashes for tests.
TRC20_HASH = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"  # 64 hex, no 0x
BEP20_HASH = "0xa1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"  # 0x + 64
TRC20_ADDR = "TJRabRWQdrJc7iCPFy4gnPCJcXbc17ncCk"
BEP20_ADDR = "0x1234567890abcdef1234567890abcdef12345678"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_paid_ready_withdrawal(network: str, addr: str) -> str:
    """Plant an approved crypto withdrawal ready to be marked paid."""
    wid = uuid.uuid4().hex
    _sync_db().currencies.update_one(
        {"code": "USDTT19H"},
        {"$set": {"code": "USDTT19H", "name": "Tether Test",
                   "type": "crypto", "is_active": True, "delivery_methods": None},
         "$setOnInsert": {"id": uuid.uuid4().hex, "created_at": "2026-07-10T00:00:00+00:00"}},
        upsert=True,
    )
    _sync_db().withdrawals.insert_one({
        "id": wid, "user_id": "user_test_vip01",
        "user_email": "vip.test@resilience.com", "user_name": "VIP Test",
        "amount_usd": 50, "currency": "USDTT19H",
        "method": "crypto", "crypto_network": network,
        "details": addr, "beneficiary_name": "VIP Test",
        "status": "approved", "admin_note": "",
        "payout_proof_image": "", "payout_tx_hash": "",
        "created_at": "2026-07-10T10:00:00+00:00",
    })
    return wid


def _cleanup_withdrawal(wid: str):
    _sync_db().withdrawals.delete_one({"id": wid})
    _sync_db().currencies.delete_one({"code": "USDTT19H"})


# ============================================================
# Pure predicates
# ============================================================

def test_detect_hash_family_matrix():
    assert detect_hash_family(TRC20_HASH) == "tron"
    assert detect_hash_family(BEP20_HASH) == "evm"
    assert detect_hash_family("garbage") == "unknown"
    assert detect_hash_family("") == "unknown"
    # Address-like input must NOT be classified as a hash (different length)
    assert detect_hash_family(TRC20_ADDR) == "unknown"
    assert detect_hash_family(BEP20_ADDR) == "unknown"


def test_is_tx_hash_valid_for_network_matrix():
    assert is_tx_hash_valid_for_network(TRC20_HASH, "TRC20") is True
    assert is_tx_hash_valid_for_network(BEP20_HASH, "BEP20") is True
    # Cross-family
    assert is_tx_hash_valid_for_network(TRC20_HASH, "BEP20") is False
    assert is_tx_hash_valid_for_network(BEP20_HASH, "TRC20") is False
    # Unsupported network
    assert is_tx_hash_valid_for_network(TRC20_HASH, "ERC20") is False
    # Empty
    assert is_tx_hash_valid_for_network("", "TRC20") is False


def test_tx_hash_mismatch_reason_mentions_conflict():
    r = tx_hash_mismatch_reason(TRC20_HASH, "BEP20")
    assert "Tron" in r
    assert "BEP20" in r or "BSC" in r


# ============================================================
# HTTP endpoint enforcement — withdrawals
# ============================================================

def test_withdrawal_paid_rejects_bep20_hash_on_trc20_withdrawal():
    wid = _seed_paid_ready_withdrawal("TRC20", TRC20_ADDR)
    r = requests.put(
        f"{API}/admin/withdrawals/{wid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json=with_totp_admin({
            "status": "paid",
            "payout_tx_hash": BEP20_HASH,  # WRONG family
        }),
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("code") == "TX_HASH_NETWORK_MISMATCH"
        assert detail.get("network") == "TRC20"
    _cleanup_withdrawal(wid)


def test_withdrawal_paid_rejects_trc20_hash_on_bep20_withdrawal():
    wid = _seed_paid_ready_withdrawal("BEP20", BEP20_ADDR)
    r = requests.put(
        f"{API}/admin/withdrawals/{wid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json=with_totp_admin({
            "status": "paid",
            "payout_tx_hash": TRC20_HASH,  # WRONG family
        }),
    )
    assert r.status_code == 400, r.text
    _cleanup_withdrawal(wid)


def test_withdrawal_paid_accepts_matching_hash():
    wid = _seed_paid_ready_withdrawal("TRC20", TRC20_ADDR)
    r = requests.put(
        f"{API}/admin/withdrawals/{wid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json=with_totp_admin({
            "status": "paid",
            "payout_tx_hash": TRC20_HASH,
        }),
    )
    assert r.status_code == 200, r.text
    doc = _sync_db().withdrawals.find_one({"id": wid})
    assert doc.get("payout_tx_hash") == TRC20_HASH
    assert doc.get("status") == "paid"
    _cleanup_withdrawal(wid)


def test_withdrawal_hash_guard_skipped_when_no_network():
    """Legacy crypto withdrawals (created before iter55.19c) have no
    crypto_network field. We must NOT block them just because we can't
    figure out the family — the operator can still paste a hash."""
    wid = _seed_paid_ready_withdrawal("", TRC20_ADDR)  # no network
    r = requests.put(
        f"{API}/admin/withdrawals/{wid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json=with_totp_admin({
            "status": "paid",
            "payout_tx_hash": BEP20_HASH,  # normally wrong for TRC address
        }),
    )
    assert r.status_code == 200, r.text
    _cleanup_withdrawal(wid)


# ============================================================
# Order flow — crypto orders infer network from delivery_details
# ============================================================

def _seed_approved_crypto_order(delivery_details: str) -> str:
    oid = uuid.uuid4().hex
    _sync_db().orders.insert_one({
        "id": oid, "user_id": "user_test_vip01",
        "user_name": "VIP Test", "user_email": "vip.test@resilience.com",
        "from_code": "USD", "to_code": "USDT",
        "amount_from": 100, "amount_to": 100, "rate_applied": 1.0,
        "commission_percent": 0,
        "delivery_method": "crypto", "delivery_details": delivery_details,
        "sender_name": "VIP", "status": "approved", "admin_note": "",
        "proof_image": "", "payout_proof_image": "",
        "payout_tx_hash": "", "created_at": "2026-07-10T10:00:00+00:00",
    })
    return oid


def _cleanup_order(oid: str):
    _sync_db().orders.delete_one({"id": oid})
    _sync_db().notifications.delete_many({"data.order_id": oid})


def test_order_completed_rejects_bep20_hash_on_trc20_delivery():
    oid = _seed_approved_crypto_order(f"{TRC20_ADDR} · red TRC20")
    r = requests.put(
        f"{API}/admin/orders/{oid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json={"status": "completed", "payout_tx_hash": BEP20_HASH},
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("code") == "TX_HASH_NETWORK_MISMATCH"
    _cleanup_order(oid)


def test_order_completed_accepts_matching_trc20_hash():
    oid = _seed_approved_crypto_order(f"{TRC20_ADDR} · red TRC20")
    r = requests.put(
        f"{API}/admin/orders/{oid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json={"status": "completed", "payout_tx_hash": TRC20_HASH},
    )
    assert r.status_code == 200, r.text
    _cleanup_order(oid)
