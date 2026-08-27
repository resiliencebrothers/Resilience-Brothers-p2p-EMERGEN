"""iter194 — Company funds per-account breakdown.

- POST /admin/company-funds/accounts (custom fund accounts)
- GET  /admin/company-funds/accounts/{currency} (breakdown + unassigned)
- POST /admin/company-funds/accounts/transfer (2FA, unassigned ↔ accounts)
- Adjustments accept account_id; company withdrawals accept paid_from_account_id.
- GET  /admin/fund-accounts/options (staff selector).
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, with_totp_admin, make_admin_totp

API = f"{BASE_URL}/api"
CODE = "TFA194"
CODE2 = "TFB194"
S = {}  # shared ids across ordered tests


def _hdr(tok=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def setup_module():
    db = _db()
    for code in (CODE, CODE2):
        db.currencies.update_one(
            {"code": code},
            {"$set": {"code": code, "name": f"Test {code}", "type": "fiat",
                      "is_active": True},
             "$setOnInsert": {"id": uuid.uuid4().hex,
                              "created_at": "2026-07-10T00:00:00+00:00"}},
            upsert=True)


def teardown_module():
    db = _db()
    db.currencies.delete_many({"code": {"$in": [CODE, CODE2]}})
    db.fund_accounts.delete_many({"currency": {"$in": [CODE, CODE2]}})
    db.fund_account_transfers.delete_many({"currency": {"$in": [CODE, CODE2]}})
    db.company_fund_adjustments.delete_many({"currency": {"$in": [CODE, CODE2]}})
    db.company_withdrawals.delete_many({"currency": {"$in": [CODE, CODE2]}})


def _breakdown():
    r = requests.get(f"{API}/admin/company-funds/accounts/{CODE}", headers=_hdr())
    assert r.status_code == 200, r.text
    return r.json()


def _adjust(amount, account_id=None, adj_type="inflow"):
    body = with_totp_admin({
        "adjustment_type": adj_type, "currency": CODE, "amount": amount,
        "method": "transfer", "source_name": "Test 194",
        "source_account": "acct-194", "account_id": account_id,
    })
    return requests.post(f"{API}/admin/company-funds/adjustments",
                         headers=_hdr(), json=body)


def _acc_balance(data, acc_id):
    return next((a["balance"] for a in data["accounts"] if a["id"] == acc_id), None)


def test_create_custom_account():
    r = requests.post(f"{API}/admin/company-funds/accounts", headers=_hdr(),
                      json={"name": "Zelle Rafa Test", "currency": CODE,
                            "method": "bank"})
    assert r.status_code == 200, r.text
    acc = r.json()
    assert acc["id"].startswith("facc_")
    assert acc["currency"] == CODE
    S["acc1"] = acc["id"]
    # duplicate name rejected
    r2 = requests.post(f"{API}/admin/company-funds/accounts", headers=_hdr(),
                       json={"name": "Zelle Rafa Test", "currency": CODE,
                             "method": "bank"})
    assert r2.status_code == 400


def test_adjustment_with_account_reflects_in_breakdown():
    r = _adjust(1000, account_id=S["acc1"])
    assert r.status_code == 200, r.text
    assert r.json()["account_label"] == "Zelle Rafa Test"
    data = _breakdown()
    assert _acc_balance(data, S["acc1"]) == 1000
    assert data["total_balance"] == 1000
    assert data["unassigned"] == 0


def test_transfer_between_accounts():
    r = requests.post(f"{API}/admin/company-funds/accounts", headers=_hdr(),
                      json={"name": "Efectivo Caja Test", "currency": CODE,
                            "method": "cash"})
    assert r.status_code == 200, r.text
    S["acc2"] = r.json()["id"]
    body = {"currency": CODE, "from_account_id": S["acc1"],
            "to_account_id": S["acc2"], "amount": 400,
            "totp_code": make_admin_totp()}
    r = requests.post(f"{API}/admin/company-funds/accounts/transfer",
                      headers=_hdr(), json=body)
    assert r.status_code == 200, r.text
    data = _breakdown()
    assert _acc_balance(data, S["acc1"]) == 600
    assert _acc_balance(data, S["acc2"]) == 400
    assert data["total_balance"] == 1000  # transfers don't change the total
    assert len(data["transfers"]) == 1


def test_transfer_insufficient_balance_rejected():
    body = {"currency": CODE, "from_account_id": S["acc2"],
            "to_account_id": S["acc1"], "amount": 10000,
            "totp_code": make_admin_totp()}
    r = requests.post(f"{API}/admin/company-funds/accounts/transfer",
                      headers=_hdr(), json=body)
    assert r.status_code == 400
    assert "insuficiente" in r.json()["detail"].lower()


def test_transfer_same_origin_destination_rejected():
    body = {"currency": CODE, "from_account_id": S["acc1"],
            "to_account_id": S["acc1"], "amount": 10,
            "totp_code": make_admin_totp()}
    r = requests.post(f"{API}/admin/company-funds/accounts/transfer",
                      headers=_hdr(), json=body)
    assert r.status_code == 400


def test_transfer_from_unassigned_bucket():
    assert _adjust(500).status_code == 200  # no account → unassigned
    data = _breakdown()
    assert data["unassigned"] == 500
    body = {"currency": CODE, "from_account_id": None,
            "to_account_id": S["acc1"], "amount": 200,
            "totp_code": make_admin_totp()}
    r = requests.post(f"{API}/admin/company-funds/accounts/transfer",
                      headers=_hdr(), json=body)
    assert r.status_code == 200, r.text
    data = _breakdown()
    assert data["unassigned"] == 300
    assert _acc_balance(data, S["acc1"]) == 800
    assert data["total_balance"] == 1500


def test_company_withdrawal_paid_from_account():
    body = with_totp_admin({"amount": 100, "currency": CODE,
                            "beneficiary": "Proveedor Test"})
    r = requests.post(f"{API}/admin/company-withdrawals", headers=_hdr(), json=body)
    assert r.status_code == 200, r.text
    cwid = r.json()["id"]
    r = requests.put(f"{API}/admin/company-withdrawals/{cwid}/status",
                     headers=_hdr(),
                     json={"status": "paid", "paid_from_account_id": S["acc1"],
                           "totp_code": make_admin_totp()})
    assert r.status_code == 200, r.text
    assert r.json()["paid_from_account_label"] == "Zelle Rafa Test"
    data = _breakdown()
    assert _acc_balance(data, S["acc1"]) == 700
    assert data["total_balance"] == 1400
    assert data["unassigned"] == 300


def test_fund_account_options_lists_both():
    r = requests.get(f"{API}/admin/fund-accounts/options",
                     params={"currency": CODE}, headers=_hdr())
    assert r.status_code == 200, r.text
    ids = {o["id"] for o in r.json()}
    assert S["acc1"] in ids and S["acc2"] in ids


def test_adjustment_currency_mismatch_rejected():
    body = with_totp_admin({
        "adjustment_type": "inflow", "currency": CODE2, "amount": 50,
        "method": "transfer", "source_name": "Test 194",
        "source_account": "x", "account_id": S["acc1"],
    })
    r = requests.post(f"{API}/admin/company-funds/adjustments",
                      headers=_hdr(), json=body)
    assert r.status_code == 400
    assert CODE in r.json()["detail"]


def test_unknown_account_rejected():
    r = _adjust(10, account_id="facc_nope")
    assert r.status_code == 400
