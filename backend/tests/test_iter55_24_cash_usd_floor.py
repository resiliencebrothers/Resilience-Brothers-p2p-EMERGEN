"""iter55.24 — Cash USD delivery must floor sub-dollar amounts.

Ops in Cuba doesn't stock coins, so any USD cash delivery has to be exact
whole dollars. The client is warned in the UI (see ExchangeView.jsx), but the
backend also enforces the floor so a modified frontend payload cannot smuggle
a fractional USD amount into the order ledger.
"""
import os
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, VIP_TOKEN

API = f"{API_ROOT}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _upsert_currency(code, delivery_methods, ctype="fiat"):
    _db().currencies.update_one(
        {"code": code},
        {"$set": {"code": code, "name": f"Test {code}", "type": ctype,
                  "is_active": True, "delivery_methods": delivery_methods,
                  "updated_at": _iso()},
         "$setOnInsert": {"id": uuid.uuid4().hex, "created_at": _iso()}},
        upsert=True,
    )


def _upsert_rate(from_code, to_code, normal, vip=None):
    _db().rates.update_one(
        {"from_code": from_code, "to_code": to_code},
        {"$set": {
            "from_code": from_code, "to_code": to_code,
            "rate_normal": normal, "rate_vip": vip if vip is not None else normal,
            "updated_at": _iso(),
        },
         "$setOnInsert": {"id": uuid.uuid4().hex}},
        upsert=True,
    )


def _cleanup():
    _db().orders.delete_many({"from_code": {"$regex": "^ZELLE24"}})
    _db().rates.delete_many({"from_code": {"$regex": "^ZELLE24"}})
    _db().currencies.delete_many({"code": {"$regex": "^(ZELLE24|USD_CASH24)"}})


def _enable_usd_cash():
    """The seed `USD` currency only allows transfer by default. Enable cash
    for the duration of the test so the delivery-method guard doesn't reject
    a legitimate cash order to USD."""
    _db().currencies.update_one(
        {"code": "USD"},
        {"$addToSet": {"delivery_methods": "cash"}},
    )


def _disable_usd_cash():
    _db().currencies.update_one(
        {"code": "USD"},
        {"$pull": {"delivery_methods": "cash"}},
    )


def test_pure_helper_matches_screenshot_scenario():
    """The reported bug scenario: send 325 ZELLE @ 0.95 → gross 308.75, expect
    to receive exactly 308 in cash USD."""
    from services.orders_helpers import _cash_no_cents

    # iter55.27 broadened the rule to any fiat + cash. Signature now includes
    # `to_type` so we can gate on currency category (not just USD).
    assert _cash_no_cents("USD", "fiat", "cash") is True
    assert _cash_no_cents("usd", "fiat", "cash") is True  # case doesn't matter for code
    assert _cash_no_cents("USD", "fiat", "transfer") is False
    assert _cash_no_cents("USD", "fiat", "crypto") is False
    # EUR fiat now also floors when cash — this is a positive change from iter55.24.
    assert _cash_no_cents("EUR", "fiat", "cash") is True
    assert _cash_no_cents("", "fiat", "cash") is True  # code is not the gate; type is
    # Non-fiat: False
    assert _cash_no_cents("USDT", "crypto", "cash") is False


def test_backend_floors_cash_usd_amount_end_to_end():
    """POST an order that would produce 308.75 USD cash. Backend must persist
    amount_to = 308.0, not 308.75."""
    _upsert_currency("ZELLE24", ["transfer"])
    _enable_usd_cash()
    try:
        _upsert_rate("ZELLE24", "USD", 0.95)

        r = requests.post(
            f"{API}/orders",
            headers=_hdr(VIP_TOKEN),
            json={
                "from_code": "ZELLE24",
                "to_code": "USD",
                "amount_from": 325,
                "delivery_method": "cash",
                "delivery_details": "Nombre: Test\nCelular: +5355550000\nDirección: X",
                "sender_name": "Test Sender",
                "proof_image": "",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Screenshot: 325 * 0.95 = 308.75 → must floor to 308.
        assert body["amount_to"] == 308.0, f"Expected 308.0, got {body['amount_to']}"
        assert body["from_code"] == "ZELLE24" and body["to_code"] == "USD"
        assert body["delivery_method"] == "cash"
    finally:
        _disable_usd_cash()
        _cleanup()


def test_backend_does_not_floor_transfer_delivery():
    """Regression guard — the floor rule must ONLY apply to cash + USD, never
    to transfer/crypto/accumulate, so wire transfers keep their precision."""
    _upsert_currency("ZELLE24", ["transfer"])
    _upsert_rate("ZELLE24", "USD", 0.95)

    r = requests.post(
        f"{API}/orders",
        headers=_hdr(VIP_TOKEN),
        json={
            "from_code": "ZELLE24",
            "to_code": "USD",
            "amount_from": 325,
            "delivery_method": "transfer",
            "delivery_details": "Bank X — Account 123456",
            "sender_name": "Test Sender",
            "proof_image": "",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Transfer preserves the fractional amount (rounded to 4 decimals as before).
    assert body["amount_to"] == 308.75, f"Expected 308.75, got {body['amount_to']}"

    _cleanup()


def test_backend_does_not_floor_cash_to_non_fiat():
    """iter55.27 broadened the floor to any fiat+cash. Non-fiat destinations
    (e.g. USDT) never floor. CUP now DOES floor per iter55.27 — the residue
    is credited to the client's balance instead of being lost."""
    _upsert_currency("ZELLE24", ["transfer"])
    _upsert_currency("CUP", ["cash", "transfer"])  # ensure CUP allows cash
    _upsert_rate("ZELLE24", "CUP", 100.5)  # 325 * 100.5 = 32662.5

    r = requests.post(
        f"{API}/orders",
        headers=_hdr(VIP_TOKEN),
        json={
            "from_code": "ZELLE24",
            "to_code": "CUP",
            "amount_from": 325,
            "delivery_method": "cash",
            "delivery_details": "Nombre: Test\nCelular: +5355550000\nDirección: X",
            "sender_name": "Test Sender",
            "proof_image": "",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # iter55.27 semantics: CUP is fiat + cash → FLOOR applied. 32662.5 → 32662.
    # (See iter55.27 tests for full residue-credit assertion.)
    assert body["amount_to"] == 32662.0, f"Expected 32662.0 (floor), got {body['amount_to']}"

    _cleanup()


def test_backend_leaves_exact_amounts_unchanged():
    """When the calculation already produces an integer USD amount, cash
    delivery must NOT change it (floor is a no-op on integers)."""
    _upsert_currency("ZELLE24", ["transfer"])
    _enable_usd_cash()
    try:
        _upsert_rate("ZELLE24", "USD", 1.0)  # 342 * 1.0 = 342.0 exact

        r = requests.post(
            f"{API}/orders",
            headers=_hdr(VIP_TOKEN),
            json={
                "from_code": "ZELLE24",
                "to_code": "USD",
                "amount_from": 342,
                "delivery_method": "cash",
                "delivery_details": "Nombre: Test\nCelular: +5355550000\nDirección: X",
                "sender_name": "Test Sender",
                "proof_image": "",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["amount_to"] == 342.0
    finally:
        _disable_usd_cash()
        _cleanup()
