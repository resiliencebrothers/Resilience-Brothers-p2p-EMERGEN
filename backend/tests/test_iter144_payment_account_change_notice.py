"""iter144 — Account-change notice for in-flight orders / VIP batch items.

When a payment account is created/updated/deleted, every pending order and
pending VIP batch item of that currency is re-resolved; affected clients get
an in-app notification (+push best-effort):
  - `payment_account_changed`     → details changed OR another tier now applies
  - `payment_account_unavailable` → no account matches their amount anymore
Label-only edits must NOT notify.
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN, make_admin_totp,
)

API = f"{BASE_URL}/api"
FROM_CODE = "ZNT"   # synthetic — never touches operator data
TO_CODE = "CNT"
NOTIF_TYPES = ["payment_account_changed", "payment_account_unavailable"]
NORMAL_UID = "user_test_normal01"
VIP_UID = "user_test_vip01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _acc_payload(**over):
    base = {
        "currency_code": FROM_CODE,
        "label": "Zelle Test 200",
        "account_details": "Resilience Test\nEmail: test200@rb.com",
        "min_amount": 200, "max_amount": None, "is_active": True,
        "totp_code": make_admin_totp(),
    }
    base.update(over)
    base["totp_code"] = make_admin_totp()
    return base


def _notifs(uid):
    return list(_db().notifications.find(
        {"recipient_user_id": uid, "type": {"$in": NOTIF_TYPES}}, {"_id": 0},
    ))


def _clear_notifs():
    _db().notifications.delete_many({"type": {"$in": NOTIF_TYPES}})


@pytest.fixture(scope="module", autouse=True)
def _seed_world():
    db = _db()
    db.currencies.update_one({"code": FROM_CODE}, {"$set": {
        "id": "test_cur_znt", "code": FROM_CODE, "name": "Zelle Notice Test",
        "type": "fiat", "symbol": "$", "is_active": True, "payment_account": "",
    }}, upsert=True)
    db.currencies.update_one({"code": TO_CODE}, {"$set": {
        "id": "test_cur_cnt", "code": TO_CODE, "name": "Peso Notice Transferencia",
        "type": "fiat", "symbol": "₱", "is_active": True, "payment_account": "",
        "delivery_methods": ["transfer"],
    }}, upsert=True)
    db.rates.update_one({"from_code": FROM_CODE, "to_code": TO_CODE}, {"$set": {
        "id": "test_rate_znt_cnt", "from_code": FROM_CODE, "to_code": TO_CODE,
        "rate_normal": 380, "rate_vip": 395, "real_rate": 450, "tiers": [],
    }}, upsert=True)
    db.payment_accounts.delete_many({"currency_code": FROM_CODE})
    db.payment_accounts.insert_many([
        {"id": "payacc_znt_50", "currency_code": FROM_CODE,
         "label": "Zelle Test 50", "account_details": "Yuri Test\ntest50@rb.com",
         "min_amount": 50, "max_amount": None, "is_active": True,
         "created_at": "2026-08-01T00:00:00+00:00", "updated_at": "2026-08-01T00:00:00+00:00"},
        {"id": "payacc_znt_200", "currency_code": FROM_CODE,
         "label": "Zelle Test 200", "account_details": "Resilience Test\nEmail: test200@rb.com",
         "min_amount": 200, "max_amount": None, "is_active": True,
         "created_at": "2026-08-01T00:00:00+00:00", "updated_at": "2026-08-01T00:00:00+00:00"},
    ])
    yield
    db.payment_accounts.delete_many({"currency_code": FROM_CODE})
    db.currencies.delete_many({"code": {"$in": [FROM_CODE, TO_CODE]}})
    db.rates.delete_many({"from_code": FROM_CODE, "to_code": TO_CODE})
    db.orders.delete_many({"from_code": FROM_CODE})
    db.vip_batch_items.delete_many({"from_code": FROM_CODE})
    db.vip_batches.delete_many({"from_code": FROM_CODE})
    _clear_notifs()


@pytest.fixture(scope="module")
def pending_work():
    """One pending order (normal user, 250) + one pending VIP batch item (250)."""
    r = requests.post(f"{API}/orders", json={
        "from_code": FROM_CODE, "to_code": TO_CODE, "amount_from": 250,
        "delivery_method": "transfer",
        "delivery_details": f"NOTICE_{uuid.uuid4().hex[:6]}",
        "sender_name": "Notice Tester", "proof_image": "",
    }, headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["payment_account_id"] == "payacc_znt_200"

    rb = requests.post(f"{API}/vip/batches",
                       json={"from_code": FROM_CODE, "to_code": TO_CODE},
                       headers=_hdr(VIP_TOKEN))
    assert rb.status_code == 200, rb.text
    batch = rb.json()
    ri = requests.post(f"{API}/vip/batches/{batch['id']}/items", json={
        "items": [{"holder_name": "Notice Vip", "amount": 250}],
    }, headers=_hdr(VIP_TOKEN))
    assert ri.status_code == 200, ri.text
    return {"order": order, "batch": batch}


def test_details_change_notifies_both_clients(pending_work):
    _clear_notifs()
    r = requests.put(f"{API}/admin/payment-accounts/payacc_znt_200",
                     json=_acc_payload(account_details="NUEVOS DATOS\nEmail: nuevo@rb.com"),
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    for uid in (NORMAL_UID, VIP_UID):
        notes = _notifs(uid)
        assert len(notes) == 1, f"{uid}: {notes}"
        assert notes[0]["type"] == "payment_account_changed"
        assert "nuevo@rb.com" in notes[0]["message"]
        assert FROM_CODE in notes[0]["message"]


def test_label_only_change_is_silent(pending_work):
    _clear_notifs()
    r = requests.put(f"{API}/admin/payment-accounts/payacc_znt_200",
                     json=_acc_payload(label="Zelle Test 200 renombrada",
                                       account_details="NUEVOS DATOS\nEmail: nuevo@rb.com"),
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert _notifs(NORMAL_UID) == [] and _notifs(VIP_UID) == []


def test_tier_reassignment_notifies(pending_work):
    """Raising the min of the 200-account to 300 pushes the 250 rows onto the
    50-account → both clients must be told the account changed."""
    _clear_notifs()
    r = requests.put(f"{API}/admin/payment-accounts/payacc_znt_200",
                     json=_acc_payload(min_amount=300,
                                       account_details="NUEVOS DATOS\nEmail: nuevo@rb.com"),
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    for uid in (NORMAL_UID, VIP_UID):
        notes = _notifs(uid)
        assert len(notes) == 1, f"{uid}: {notes}"
        assert notes[0]["type"] == "payment_account_changed"
        # single new account → its details are embedded
        assert "test50@rb.com" in notes[0]["message"]
    # restore the tier for the next test
    requests.put(f"{API}/admin/payment-accounts/payacc_znt_200",
                 json=_acc_payload(min_amount=200,
                                   account_details="NUEVOS DATOS\nEmail: nuevo@rb.com"),
                 headers=_hdr(ADMIN_TOKEN))


def test_no_matching_account_notifies_unavailable(pending_work):
    """Capping the 200-account at 240 and the 50-account at 100 leaves the
    250 rows with NO valid account → 'unavailable' notice."""
    _clear_notifs()
    requests.put(f"{API}/admin/payment-accounts/payacc_znt_50",
                 json=_acc_payload(label="Zelle Test 50", min_amount=50,
                                   max_amount=100,
                                   account_details="Yuri Test\ntest50@rb.com"),
                 headers=_hdr(ADMIN_TOKEN))
    _clear_notifs()  # the 50-cap alone doesn't touch the 250 rows; stay clean
    r = requests.put(f"{API}/admin/payment-accounts/payacc_znt_200",
                     json=_acc_payload(min_amount=200, max_amount=240,
                                       account_details="NUEVOS DATOS\nEmail: nuevo@rb.com"),
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    for uid in (NORMAL_UID, VIP_UID):
        notes = _notifs(uid)
        assert len(notes) == 1, f"{uid}: {notes}"
        assert notes[0]["type"] == "payment_account_unavailable"


def test_delete_account_notifies(pending_work):
    """Deleting the (only matching) 200-account: rows fall to no account at all
    while the capped 50-account still exists → unavailable notice again."""
    _clear_notifs()
    r = requests.delete(f"{API}/admin/payment-accounts/payacc_znt_200",
                        headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    for uid in (NORMAL_UID, VIP_UID):
        notes = _notifs(uid)
        assert len(notes) == 1, f"{uid}: {notes}"
        assert notes[0]["type"] == "payment_account_unavailable"
