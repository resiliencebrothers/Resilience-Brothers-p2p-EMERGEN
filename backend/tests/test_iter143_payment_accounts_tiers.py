"""iter143 — Tiered payment accounts + amount-tiered exchange rates.

Covers:
1. Pure helpers: pick_account (highest matching min, max cap), min_required.
2. Pure helpers: rate_tiers.pick_tier / effective_rates fallbacks.
3. HTTP: /payment-accounts/resolve picks the right tier / flags below_min.
4. HTTP: admin CRUD with TOTP + RBAC (scoped employee 403, client 403).
5. HTTP: POST /orders blocked below minimum; snapshot + tier rate applied.
6. HTTP: VIP batch items get per-item tier rate + account snapshot;
   below-min item rejected with 422.
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN, EMPLOYEE_TOKEN,
    make_admin_totp,
)
from services.payment_accounts import pick_account, min_required
from services.rate_tiers import pick_tier, effective_rates

API = f"{BASE_URL}/api"

# Synthetic currency codes so we never touch operator data.
FROM_CODE = "ZLT"   # pretend-Zelle test currency
TO_CODE = "CPT"     # pretend-CUP test currency


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def _seed_world():
    db = _db()
    db.currencies.update_one({"code": FROM_CODE}, {"$set": {
        "id": "test_cur_zlt", "code": FROM_CODE, "name": "Zelle Test",
        "type": "fiat", "symbol": "$", "is_active": True, "payment_account": "",
    }}, upsert=True)
    db.currencies.update_one({"code": TO_CODE}, {"$set": {
        "id": "test_cur_cpt", "code": TO_CODE, "name": "Peso Test Transferencia",
        "type": "fiat", "symbol": "₱", "is_active": True, "payment_account": "",
        "delivery_methods": ["transfer"],
    }}, upsert=True)
    # Base rate 380/395 + tiers: >=50 → 400/415, >=200 → 420/440
    db.rates.update_one({"from_code": FROM_CODE, "to_code": TO_CODE}, {"$set": {
        "id": "test_rate_zlt_cpt", "from_code": FROM_CODE, "to_code": TO_CODE,
        "rate_normal": 380, "rate_vip": 395, "real_rate": 450,
        "tiers": [
            {"min_amount": 50, "rate_normal": 400, "rate_vip": 415, "real_rate": 455},
            {"min_amount": 200, "rate_normal": 420, "rate_vip": 440, "real_rate": 460},
        ],
    }}, upsert=True)
    # Two tiered accounts (min 50 / min 200)
    db.payment_accounts.delete_many({"currency_code": FROM_CODE})
    db.payment_accounts.insert_many([
        {"id": "payacc_test_50", "currency_code": FROM_CODE,
         "label": "Zelle Yuri · mín 50",
         "account_details": "Info@serene.test\nYuri Despaigne",
         "min_amount": 50, "max_amount": None, "is_active": True,
         "created_at": "2026-08-01T00:00:00+00:00", "updated_at": "2026-08-01T00:00:00+00:00"},
        {"id": "payacc_test_200", "currency_code": FROM_CODE,
         "label": "Zelle RB · mín 200",
         "account_details": "Resilience Brothers\ndanny@test.com",
         "min_amount": 200, "max_amount": None, "is_active": True,
         "created_at": "2026-08-01T00:00:00+00:00", "updated_at": "2026-08-01T00:00:00+00:00"},
    ])
    yield
    db.payment_accounts.delete_many({"currency_code": FROM_CODE})
    db.currencies.delete_many({"code": {"$in": [FROM_CODE, TO_CODE]}})
    db.rates.delete_many({"from_code": FROM_CODE, "to_code": TO_CODE})
    db.orders.delete_many({"from_code": FROM_CODE})
    db.vip_batches.delete_many({"currency": FROM_CODE})
    db.vip_batch_items.delete_many({"from_code": FROM_CODE})


# ------------------------------------------------------------------
# 1. Pure helpers — payment accounts
# ------------------------------------------------------------------

ACCS = [
    {"id": "a50", "min_amount": 50, "max_amount": None, "is_active": True},
    {"id": "a200", "min_amount": 200, "max_amount": None, "is_active": True},
    {"id": "a500", "min_amount": 500, "max_amount": 1000, "is_active": True},
    {"id": "aoff", "min_amount": 10, "max_amount": None, "is_active": False},
]


def test_pick_account_highest_matching_min():
    assert pick_account(ACCS, 250)["id"] == "a200"
    assert pick_account(ACCS, 80)["id"] == "a50"
    assert pick_account(ACCS, 600)["id"] == "a500"


def test_pick_account_respects_max_cap():
    # 2000 exceeds a500's max → falls back to a200 (no cap)
    assert pick_account(ACCS, 2000)["id"] == "a200"


def test_pick_account_below_all_minimums_and_inactive_ignored():
    assert pick_account(ACCS, 30) is None  # aoff (min 10) is inactive
    assert min_required(ACCS) == 50


# ------------------------------------------------------------------
# 2. Pure helpers — rate tiers
# ------------------------------------------------------------------

RATE_DOC = {
    "rate_normal": 380, "rate_vip": 395, "real_rate": 450,
    "tiers": [
        {"min_amount": 50, "rate_normal": 400, "rate_vip": 415, "real_rate": 455},
        {"min_amount": 200, "rate_normal": 420, "rate_vip": 440},
    ],
}


def test_pick_tier_highest_matching():
    assert pick_tier(RATE_DOC, 250)["min_amount"] == 200
    assert pick_tier(RATE_DOC, 199.99)["min_amount"] == 50
    assert pick_tier(RATE_DOC, 30) is None
    assert pick_tier({"rate_normal": 1}, 500) is None


def test_effective_rates_tier_and_fallbacks():
    eff = effective_rates(RATE_DOC, 250)
    assert eff["rate_normal"] == 420 and eff["rate_vip"] == 440
    # tier 200 has no real_rate → falls back to base 450
    assert eff["real_rate"] == 450
    eff50 = effective_rates(RATE_DOC, 80)
    assert eff50 == {"rate_normal": 400, "rate_vip": 415, "real_rate": 455}
    base = effective_rates(RATE_DOC, 10)
    assert base == {"rate_normal": 380, "rate_vip": 395, "real_rate": 450}


# ------------------------------------------------------------------
# 3. Resolve endpoint
# ------------------------------------------------------------------

def test_resolve_picks_tier_by_amount():
    r = requests.get(f"{API}/payment-accounts/resolve",
                     params={"currency": FROM_CODE, "amount": 250},
                     headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_tiers"] is True
    assert body["account"]["id"] == "payacc_test_200"
    assert "Resilience" in body["account"]["account_details"]

    r2 = requests.get(f"{API}/payment-accounts/resolve",
                      params={"currency": FROM_CODE, "amount": 80},
                      headers=_hdr(NORMAL_TOKEN))
    assert r2.json()["account"]["id"] == "payacc_test_50"


def test_resolve_below_min_and_no_tiers():
    r = requests.get(f"{API}/payment-accounts/resolve",
                     params={"currency": FROM_CODE, "amount": 30},
                     headers=_hdr(NORMAL_TOKEN))
    body = r.json()
    assert body["below_min"] is True and body["account"] is None
    assert body["min_required"] == 50

    r2 = requests.get(f"{API}/payment-accounts/resolve",
                      params={"currency": "NOPE_XX", "amount": 100},
                      headers=_hdr(NORMAL_TOKEN))
    assert r2.json()["has_tiers"] is False

    r3 = requests.get(f"{API}/payment-accounts/resolve",
                      params={"currency": FROM_CODE, "amount": 100})
    assert r3.status_code in (401, 403)


# ------------------------------------------------------------------
# 4. Admin CRUD + RBAC
# ------------------------------------------------------------------

def test_admin_crud_with_totp():
    payload = {
        "currency_code": "eur",  # normalised to EUR
        "label": "IBAN España test",
        "account_details": "BASA TRAVEL\nIBAN: ES65 0081 ...",
        "min_amount": 50, "max_amount": None, "is_active": True,
        "totp_code": make_admin_totp(),
    }
    r = requests.post(f"{API}/admin/payment-accounts", json=payload, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    acc = r.json()
    assert acc["currency_code"] == "EUR"
    acc_id = acc["id"]
    try:
        r2 = requests.put(f"{API}/admin/payment-accounts/{acc_id}",
                          json={**payload, "min_amount": 60, "totp_code": make_admin_totp()},
                          headers=_hdr(ADMIN_TOKEN))
        assert r2.status_code == 200, r2.text
        assert r2.json()["min_amount"] == 60

        r3 = requests.get(f"{API}/admin/payment-accounts",
                          params={"currency": "EUR"}, headers=_hdr(ADMIN_TOKEN))
        assert any(a["id"] == acc_id for a in r3.json())
    finally:
        r4 = requests.delete(f"{API}/admin/payment-accounts/{acc_id}", headers=_hdr(ADMIN_TOKEN))
        assert r4.status_code == 200


def test_create_without_totp_rejected():
    r = requests.post(f"{API}/admin/payment-accounts", json={
        "currency_code": "EUR", "label": "x", "account_details": "y",
        "min_amount": 10,
    }, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code in (400, 401, 403), r.text


def test_max_must_exceed_min():
    r = requests.post(f"{API}/admin/payment-accounts", json={
        "currency_code": "EUR", "label": "x", "account_details": "y",
        "min_amount": 100, "max_amount": 50, "totp_code": make_admin_totp(),
    }, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 400


def test_rbac_scoped_employee_and_client_blocked():
    db = _db()
    db.users.update_one({"user_id": "user_test_employee01"},
                        {"$set": {"allowed_permissions": ["kyc"]}})
    try:
        r = requests.get(f"{API}/admin/payment-accounts", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 403, r.text
    finally:
        db.users.update_one({"user_id": "user_test_employee01"},
                            {"$set": {"allowed_permissions": []}})
    r2 = requests.get(f"{API}/admin/payment-accounts", headers=_hdr(EMPLOYEE_TOKEN))
    assert r2.status_code == 200  # empty perms = full staff access
    r3 = requests.get(f"{API}/admin/payment-accounts", headers=_hdr(VIP_TOKEN))
    assert r3.status_code == 403


# ------------------------------------------------------------------
# 5. Order creation — min enforcement + tier rate + snapshot
# ------------------------------------------------------------------

def _order_payload(amount):
    return {
        "from_code": FROM_CODE, "to_code": TO_CODE, "amount_from": amount,
        "delivery_method": "transfer",
        "delivery_details": f"TEST_iter143_{uuid.uuid4().hex[:6]}",
        "sender_name": "Tier Tester",
        "proof_image": "",
    }


def test_order_below_min_rejected():
    r = requests.post(f"{API}/orders", json=_order_payload(30), headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 400, r.text
    assert "mínimo" in r.text.lower()


def test_order_tier_rate_and_account_snapshot():
    r = requests.post(f"{API}/orders", json=_order_payload(250), headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["rate_applied"] == 420          # normal rate of the >=200 tier
    assert o["amount_to"] == 250 * 420
    assert o["payment_account_id"] == "payacc_test_200"
    assert o["payment_account_label"] == "Zelle RB · mín 200"

    r2 = requests.post(f"{API}/orders", json=_order_payload(80), headers=_hdr(VIP_TOKEN))
    assert r2.status_code == 200, r2.text
    o2 = r2.json()
    assert o2["rate_applied"] == 415         # vip rate of the >=50 tier
    assert o2["payment_account_id"] == "payacc_test_50"


# ------------------------------------------------------------------
# 6. VIP batches — per-item tier rate + account snapshot
# ------------------------------------------------------------------

def test_vip_batch_items_tiered():
    r = requests.post(f"{API}/vip/batches",
                      json={"from_code": FROM_CODE, "to_code": TO_CODE},
                      headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    batch = r.json()
    batch_id = batch["id"]
    try:
        # Detail exposes the tiers for the preview
        rd = requests.get(f"{API}/vip/batches/{batch_id}", headers=_hdr(VIP_TOKEN))
        assert rd.status_code == 200
        tiers = rd.json()["batch"].get("rate_tiers") or []
        assert [t["min_amount"] for t in tiers] == [50, 200]

        ri = requests.post(f"{API}/vip/batches/{batch_id}/items", json={"items": [
            {"holder_name": "Ana 250", "amount": 250},
            {"holder_name": "Luis 80", "amount": 80},
        ]}, headers=_hdr(VIP_TOKEN))
        assert ri.status_code == 200, ri.text
        items = {it["holder_name"]: it for it in ri.json()["items"]}
        assert items["Ana 250"]["rate_applied"] == 440   # vip tier >=200
        assert items["Ana 250"]["payment_account_label"] == "Zelle RB · mín 200"
        assert items["Luis 80"]["rate_applied"] == 415   # vip tier >=50
        assert items["Luis 80"]["payment_account_label"] == "Zelle Yuri · mín 50"

        rbad = requests.post(f"{API}/vip/batches/{batch_id}/items", json={"items": [
            {"holder_name": "Bajo 30", "amount": 30},
        ]}, headers=_hdr(VIP_TOKEN))
        assert rbad.status_code == 422, rbad.text
        assert "mínimo" in rbad.text.lower()
    finally:
        _db().vip_batch_items.delete_many({"batch_id": batch_id})
        _db().vip_batches.delete_many({"id": batch_id})
