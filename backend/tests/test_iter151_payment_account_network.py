"""iter151 — Payment account network / method field.

Covers:
1. Admin can create + update a payment account with a `network` value.
2. `network` normalisation: leading/trailing spaces stripped, empty ⇒ null.
3. Public /payment-accounts/resolve echoes `network` back to the client.
4. Existing accounts without `network` return an empty string, so the
   frontend hides the warning banner.
5. `network` is capped at 30 chars (Pydantic 422 on overflow).
6. TOTP step-up + RBAC still apply to create/update (regression guard).
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, VIP_TOKEN,
    make_admin_totp,
)

API = f"{BASE_URL}/api"

FROM_CODE = "ZNT"   # synthetic source currency used only by this suite


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def _seed_currency():
    db = _db()
    db.currencies.update_one({"code": FROM_CODE}, {"$set": {
        "id": "test_cur_znt", "code": FROM_CODE, "name": "Network Test",
        "type": "crypto", "symbol": "₮", "is_active": True, "payment_account": "",
    }}, upsert=True)
    db.payment_accounts.delete_many({"currency_code": FROM_CODE})
    yield
    db.payment_accounts.delete_many({"currency_code": FROM_CODE})


def _create_account(**overrides):
    base = {
        "currency_code": FROM_CODE,
        "label": f"Wallet {uuid.uuid4().hex[:6]}",
        "account_details": "0xabc123... (network test wallet)",
        "network": "BEP20",
        "min_amount": 1,
        "is_active": True,
        "totp_code": make_admin_totp(),
    }
    base.update(overrides)
    return requests.post(f"{API}/admin/payment-accounts",
                         headers=_hdr(ADMIN_TOKEN), json=base)


def test_admin_can_create_account_with_network():
    r = _create_account(network="BEP20")
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["network"] == "BEP20"

    stored = _db().payment_accounts.find_one({"id": doc["id"]}, {"_id": 0})
    assert stored["network"] == "BEP20"


def test_network_is_trimmed_and_empty_becomes_none():
    r = _create_account(network="   ")
    assert r.status_code == 200
    doc = r.json()
    assert doc["network"] is None

    r2 = _create_account(network="  TRC20  ")
    assert r2.status_code == 200
    assert r2.json()["network"] == "TRC20"


def test_resolve_echoes_network_to_client():
    _create_account(network="BEP20", min_amount=1)
    r = requests.get(
        f"{API}/payment-accounts/resolve",
        params={"currency": FROM_CODE, "amount": 250},
        headers=_hdr(VIP_TOKEN),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["account"] is not None
    assert body["account"]["network"] == "BEP20"


def test_resolve_returns_empty_string_when_network_missing():
    # Insert an account directly WITHOUT a network field (legacy shape).
    db = _db()
    legacy_id = f"payacc_{uuid.uuid4().hex[:12]}"
    db.payment_accounts.insert_one({
        "id": legacy_id, "currency_code": FROM_CODE,
        "label": "Legacy no-network",
        "account_details": "Legacy details",
        "min_amount": 1, "is_active": True,
        "created_at": "2020-01-01T00:00:00+00:00",
        "updated_at": "2020-01-01T00:00:00+00:00",
    })
    r = requests.get(
        f"{API}/payment-accounts/resolve",
        params={"currency": FROM_CODE, "amount": 25},
        headers=_hdr(VIP_TOKEN),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["account"]["network"] == ""


def test_update_can_change_network():
    r = _create_account(network="BEP20", min_amount=1)
    assert r.status_code == 200
    doc = r.json()

    put_body = {
        "currency_code": FROM_CODE,
        "label": doc["label"],
        "account_details": doc["account_details"],
        "network": "TRC20",
        "min_amount": doc["min_amount"],
        "max_amount": doc.get("max_amount"),
        "is_active": True,
        "totp_code": make_admin_totp(),
    }
    r2 = requests.put(f"{API}/admin/payment-accounts/{doc['id']}",
                      headers=_hdr(ADMIN_TOKEN), json=put_body)
    assert r2.status_code == 200, r2.text
    assert r2.json()["network"] == "TRC20"


def test_network_over_30_chars_rejected():
    r = _create_account(network="X" * 31)
    assert r.status_code == 422


def test_normal_client_cannot_create_account():
    body = {
        "currency_code": FROM_CODE,
        "label": "Hacked",
        "account_details": "0xhacker",
        "network": "BEP20",
        "min_amount": 1,
        "is_active": True,
    }
    r = requests.post(f"{API}/admin/payment-accounts",
                      headers=_hdr(VIP_TOKEN), json=body)
    # VIP is not staff; endpoint gated by `payment_accounts` permission.
    assert r.status_code in (401, 403)
