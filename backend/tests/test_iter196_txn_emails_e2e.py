"""iter196 — E2E integration: withdrawal + deposit emails are actually
triggered by the HTTP routes (not just importable).

Since EMAIL_SEND_ENABLED=false in preview/CI, `_send` short-circuits and
persists a `suppressed` row in `email_events`. We assert on those rows to
confirm each lifecycle event fires the correct `kind`.
"""
import os
import time
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, VIP_TOKEN, with_totp_admin, make_vip_totp,
)

API = f"{BASE_URL}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _find_event(kind: str, since_iso: str, to_email: str) -> dict:
    """Return the newest email_event with the given kind for `to_email`
    created after `since_iso`, or {}."""
    db = _db()
    for row in db.email_events.find(
        {"kind": kind, "to": to_email.lower(),
         "created_at": {"$gt": since_iso}}, {"_id": 0},
    ).sort("created_at", -1).limit(1):
        return row
    return {}


def _vip_email() -> str:
    db = _db()
    u = db.users.find_one({"user_id": "user_test_vip01"}, {"_id": 0, "email": 1})
    assert u and u.get("email"), "VIP test user missing email"
    return u["email"]


def _seed_vip_balance(currency: str = "USD", amount: float = 500.0) -> None:
    _db().users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {f"vip_balances.{currency}": amount}},
    )


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# Deposits
# ------------------------------------------------------------------

def test_deposit_creation_triggers_received_email():
    since = _now_iso()
    email = _vip_email()

    # Ensure the currency is depositable (USD is default in the catalog).
    payload = {
        "currency": "USD",
        "amount": 100,
        "method": "transfer",
        "account_holder": "Cliente VIP",
        "note": "test iter196 deposit",
        "proof_image": (
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAA"
            "AfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        ),
    }
    r = requests.post(f"{API}/deposits", json=payload, headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    dep_id = r.json()["id"]
    # Email is fired inside the route — allow a small window for the
    # try/except block to run.
    for _ in range(10):
        ev = _find_event("deposit_received", since, email)
        if ev:
            break
        time.sleep(0.1)
    assert ev, "deposit_received email_event never landed"
    # Deposits use `dep_<hash>` ids; the short slug strips the prefix.
    assert dep_id.split("_", 1)[1][:8] in ev["subject"], (
        f"short deposit id not in subject: {ev['subject']!r}"
    )
    assert ev["status"] in ("sent", "suppressed")

    # Cleanup: remove the deposit so subsequent runs stay deterministic.
    _db().deposits.delete_one({"id": dep_id})


def test_deposit_confirmation_triggers_confirmed_email():
    since = _now_iso()
    email = _vip_email()

    # Create a deposit first
    r = requests.post(f"{API}/deposits", json={
        "currency": "USD", "amount": 50, "method": "transfer",
        "account_holder": "Cliente VIP", "note": "iter196 confirm test",
        "proof_image": (
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAA"
            "AfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        ),
    }, headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    dep_id = r.json()["id"]

    # Admin confirms
    r2 = requests.post(f"{API}/admin/deposits/{dep_id}/confirm",
                       json=with_totp_admin({}), headers=_hdr(ADMIN_TOKEN))
    assert r2.status_code == 200, r2.text

    for _ in range(10):
        ev = _find_event("deposit_confirmed", since, email)
        if ev:
            break
        time.sleep(0.1)
    assert ev, "deposit_confirmed email_event never landed"
    assert dep_id.split("_", 1)[1][:8] in ev["subject"]

    # Cleanup: remove the deposit + revert balance credit
    _db().deposits.delete_one({"id": dep_id})
    _db().users.update_one({"user_id": "user_test_vip01"},
                           {"$inc": {"vip_balances.USD": -50}})


# ------------------------------------------------------------------
# Withdrawals
# ------------------------------------------------------------------

def test_withdrawal_approved_and_paid_trigger_emails():
    since = _now_iso()
    email = _vip_email()

    _seed_vip_balance("USDT", 500.0)

    # 1) VIP creates a crypto withdrawal — pending (no email at this step).
    payload = {
        "amount_usd": 50,
        "currency": "USDT",
        "method": "crypto",
        "details": "TQrZ9wBEeC7DwqcJHkT3wLoP5vBg7HKxSb",  # sample TRC20 addr
        "crypto_network": "TRC20",
        "beneficiary_name": "",
        "totp_code": make_vip_totp(),
    }
    r = requests.post(f"{API}/vip/withdraw", json=payload, headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    wid = r.json()["id"]

    # 2) Admin flips → approved. Expect withdrawal_in_progress email.
    r2 = requests.put(f"{API}/admin/withdrawals/{wid}/status",
                      json=with_totp_admin({"status": "approved",
                                            "admin_note": "iter196 approved"}),
                      headers=_hdr(ADMIN_TOKEN))
    assert r2.status_code == 200, r2.text

    ev_in_progress = {}
    for _ in range(15):
        ev_in_progress = _find_event("withdrawal_in_progress", since, email)
        if ev_in_progress:
            break
        time.sleep(0.1)
    assert ev_in_progress, "withdrawal_in_progress email_event never landed"
    assert wid[:8] in ev_in_progress["subject"]

    # 3) Admin flips → paid. Expect withdrawal_paid email.
    since_paid = _now_iso()
    r3 = requests.put(f"{API}/admin/withdrawals/{wid}/status",
                      json=with_totp_admin({"status": "paid",
                                            "admin_note": "iter196 paid",
                                            "payout_proof_image":
                                                "data:image/png;base64,iVBORw0KGgo=",
                                            "payout_tx_hash": ""}),
                      headers=_hdr(ADMIN_TOKEN))
    assert r3.status_code == 200, r3.text

    ev_paid = {}
    for _ in range(15):
        ev_paid = _find_event("withdrawal_paid", since_paid, email)
        if ev_paid:
            break
        time.sleep(0.1)
    assert ev_paid, "withdrawal_paid email_event never landed"
    assert wid[:8] in ev_paid["subject"]

    # Cleanup
    _db().withdrawals.delete_one({"id": wid})
