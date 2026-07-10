"""iter55.19c — Crypto network ↔ address validation for VIP withdrawals.

Replicates BingX-style "No coinciden" behavior: a TRC20 address cannot be
submitted for a BEP20 withdrawal (and vice-versa). BEP20 and ERC20 share the
EVM format so we only distinguish families (tron vs evm) — the operator
picks the exact chain.

Covers pure service predicates + HTTP endpoint enforcement + persistence.
"""
import os
import uuid
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, VIP_TOKEN, make_vip_totp
from services.crypto_networks import (
    SUPPORTED_NETWORKS,
    is_supported_network,
    detect_family,
    is_address_valid_for_network,
    mismatch_reason,
)


API = f"{BASE_URL}/api"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_usdt_currency():
    _sync_db().currencies.update_one(
        {"code": "USDTT19C"},
        {"$set": {
            "code": "USDTT19C",
            "name": "Tether Test iter55.19c",
            "type": "crypto",
            "is_active": True,
            "delivery_methods": None,
        },
         "$setOnInsert": {"id": uuid.uuid4().hex, "created_at": "2026-07-10T00:00:00+00:00"}},
        upsert=True,
    )
    _sync_db().users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {"vip_balances.USDTT19C": 5000}},
    )


def _cleanup():
    _sync_db().currencies.delete_one({"code": "USDTT19C"})
    _sync_db().users.update_one(
        {"user_id": "user_test_vip01"},
        {"$unset": {"vip_balances.USDTT19C": ""}},
    )
    _sync_db().withdrawals.delete_many({"currency": "USDTT19C"})


# Well-known real address formats (public, non-secret) for regex sanity checks.
# TRC20: T + 33 base58 chars (no 0, O, I, l). Real-shape but not a live wallet.
TRC20_ADDR = "TJRabRWQdrJc7iCPFy4gnPCJcXbc17ncCk"
BEP20_ADDR = "0x1234567890abcdef1234567890abcdef12345678"  # 42 chars starting with 0x
BAD_ADDR = "some-random-garbage-9999"


# ============================================================
# Pure predicates
# ============================================================

def test_supported_networks_are_trc20_and_bep20():
    assert SUPPORTED_NETWORKS == ["TRC20", "BEP20"]
    assert is_supported_network("TRC20")
    assert is_supported_network("BEP20")
    assert not is_supported_network("ERC20")
    assert not is_supported_network("SOLANA")
    assert not is_supported_network("")


def test_detect_family_recognizes_tron_and_evm():
    assert detect_family(TRC20_ADDR) == "tron"
    assert detect_family(BEP20_ADDR) == "evm"
    assert detect_family(BAD_ADDR) == "unknown"
    assert detect_family("") == "unknown"
    # Mixed case for hex → still valid
    assert detect_family("0xABCDEF1234567890abcdef1234567890AbCdEf12") == "evm"


def test_is_address_valid_for_network_matrix():
    assert is_address_valid_for_network(TRC20_ADDR, "TRC20") is True
    assert is_address_valid_for_network(BEP20_ADDR, "BEP20") is True
    # Cross-family mismatches
    assert is_address_valid_for_network(TRC20_ADDR, "BEP20") is False
    assert is_address_valid_for_network(BEP20_ADDR, "TRC20") is False
    # Garbage
    assert is_address_valid_for_network(BAD_ADDR, "TRC20") is False
    assert is_address_valid_for_network(BAD_ADDR, "BEP20") is False
    # Unsupported network
    assert is_address_valid_for_network(TRC20_ADDR, "ERC20") is False


def test_mismatch_reason_mentions_the_conflicting_family():
    # TRC20 address declared as BEP20 → should mention Tron
    reason = mismatch_reason(TRC20_ADDR, "BEP20")
    assert "Tron" in reason
    assert "BSC" in reason or "BEP20" in reason
    # EVM address declared as TRC20 → should mention EVM
    reason2 = mismatch_reason(BEP20_ADDR, "TRC20")
    assert "EVM" in reason2 or "BSC/ETH" in reason2


# ============================================================
# HTTP endpoint enforcement
# ============================================================

def test_crypto_withdrawal_requires_network():
    _seed_usdt_currency()
    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 50, "currency": "USDTT19C", "method": "crypto",
            "details": TRC20_ADDR, "beneficiary_name": "Test",
            # NO crypto_network on purpose
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "")
    assert "red" in detail.lower() or "TRC20" in detail
    _cleanup()


def test_crypto_withdrawal_rejects_unsupported_network():
    _seed_usdt_currency()
    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 50, "currency": "USDTT19C", "method": "crypto",
            "details": BEP20_ADDR, "beneficiary_name": "Test",
            "crypto_network": "SOLANA",  # not supported
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 400, r.text
    _cleanup()


def test_crypto_withdrawal_rejects_trc20_address_on_bep20():
    _seed_usdt_currency()
    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 50, "currency": "USDTT19C", "method": "crypto",
            "details": TRC20_ADDR, "beneficiary_name": "Test",
            "crypto_network": "BEP20",
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail")
    # Backend returns a structured detail here — code + message
    if isinstance(detail, dict):
        assert detail.get("code") == "CRYPTO_NETWORK_MISMATCH"
        assert detail.get("network") == "BEP20"
    else:
        # Fallback: plain string still mentions the network
        assert "BEP20" in detail
    _cleanup()


def test_crypto_withdrawal_rejects_bep20_address_on_trc20():
    _seed_usdt_currency()
    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 50, "currency": "USDTT19C", "method": "crypto",
            "details": BEP20_ADDR, "beneficiary_name": "Test",
            "crypto_network": "TRC20",
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 400, r.text
    _cleanup()


def test_crypto_withdrawal_accepts_matching_trc20():
    _seed_usdt_currency()
    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 25, "currency": "USDTT19C", "method": "crypto",
            "details": TRC20_ADDR, "beneficiary_name": "Test",
            "crypto_network": "TRC20",
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "crypto"
    assert body["crypto_network"] == "TRC20"
    # Verify the field is persisted in Mongo (audit / admin panel)
    doc = _sync_db().withdrawals.find_one({"id": body["id"]})
    assert doc is not None
    assert doc.get("crypto_network") == "TRC20"
    _cleanup()


def test_crypto_withdrawal_accepts_matching_bep20():
    _seed_usdt_currency()
    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 25, "currency": "USDTT19C", "method": "crypto",
            "details": BEP20_ADDR, "beneficiary_name": "Test",
            "crypto_network": "BEP20",
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["crypto_network"] == "BEP20"
    _cleanup()


# ============================================================
# Regression: transfer/cash flows are unaffected
# ============================================================

def test_transfer_flow_ignores_crypto_network_field():
    """Non-crypto withdrawals should not be validated against the network
    even if the client accidentally sends the field."""
    # Vanilla USD stays transfer-friendly by heuristic; seed a balance.
    _sync_db().users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {"vip_balances.USDXFR19C": 500}},
    )
    _sync_db().currencies.update_one(
        {"code": "USDXFR19C"},
        {"$set": {"code": "USDXFR19C", "name": "USD", "type": "fiat",
                  "is_active": True, "delivery_methods": None},
         "$setOnInsert": {"id": uuid.uuid4().hex, "created_at": "2026-07-10T00:00:00+00:00"}},
        upsert=True,
    )
    r = requests.post(
        f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
        json={
            "amount_usd": 10, "currency": "USDXFR19C", "method": "transfer",
            "details": "Banco Popular · cuenta 12345", "beneficiary_name": "Test",
            # Bogus crypto_network — must be ignored for transfer
            "crypto_network": "BEP20",
            "totp_code": make_vip_totp(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # For non-crypto withdrawals, the stored crypto_network stays empty.
    doc = _sync_db().withdrawals.find_one({"id": body["id"]})
    assert doc is not None
    assert doc.get("crypto_network", "") == ""
    # Cleanup
    _sync_db().withdrawals.delete_many({"id": body["id"]})
    _sync_db().currencies.delete_one({"code": "USDXFR19C"})
    _sync_db().users.update_one(
        {"user_id": "user_test_vip01"},
        {"$unset": {"vip_balances.USDXFR19C": ""}},
    )
