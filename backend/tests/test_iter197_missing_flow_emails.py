"""iter197 — E2E: email coverage for the flows that were missing it.

- classic deposit REJECTED           → kind=deposit_rejected
- VIP capital deposit confirm/reject → kind=capital_deposit_confirmed|rejected
- VIP settlement approve/reject      → kind=settlement_confirmed|rejected
- VIP capital request approve/reject → kind=capital_request_disbursed|rejected
- GET /admin/email-health diagnostic

Each admin action fires `_send`, which persists a row in `email_events`
(status sent/suppressed/failed depending on env). We assert on those rows.
"""
import os
import time
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vip_email() -> str:
    u = _db().users.find_one({"user_id": VIP_ID}, {"_id": 0, "email": 1})
    return u["email"]


def _find_event(kind: str, since_iso: str) -> dict:
    db = _db()
    email = _vip_email().lower()
    for row in db.email_events.find(
        {"kind": kind, "to": email, "created_at": {"$gt": since_iso}},
        {"_id": 0},
    ).sort("created_at", -1).limit(1):
        return row
    return {}


def _wait_event(kind: str, since_iso: str) -> dict:
    for _ in range(20):
        ev = _find_event(kind, since_iso)
        if ev:
            return ev
        time.sleep(0.1)
    return {}


def _mk_deposit():
    dep_id = f"dep_{uuid.uuid4().hex[:12]}"
    _db().deposits.insert_one({
        "id": dep_id, "user_id": VIP_ID, "user_name": "VIP Test",
        "amount": 100, "currency": "USD", "method": "transfer",
        "status": "pending", "created_at": _now_iso(),
        "updated_at": _now_iso(),
    })
    return dep_id


def _mk_capital_deposit():
    dep_id = f"vcd_{uuid.uuid4().hex[:12]}"
    _db().vip_capital_deposits.insert_one({
        "id": dep_id, "vip_user_id": VIP_ID,
        "vip_email": _vip_email(), "vip_name": "VIP Test",
        "amount": 500, "currency": "USDT", "method": "crypto",
        "tx_hash": "", "status": "pending",
        "created_at": _now_iso(), "updated_at": _now_iso(),
    })
    return dep_id


def _mk_settlement():
    sid = f"vset_{uuid.uuid4().hex[:12]}"
    _db().vip_settlements.insert_one({
        "id": sid, "vip_user_id": VIP_ID, "vip_email": _vip_email(),
        "vip_name": "VIP Test", "direction": "payout", "currency": "USDT",
        "amount": 200, "amount_usdt": 200, "settlement_method": "crypto",
        "status": "pending", "created_at": _now_iso(),
        "updated_at": _now_iso(),
    })
    return sid


def _mk_capital_request():
    rid = f"cr_{uuid.uuid4().hex[:12]}"
    _db().capital_requests.insert_one({
        "id": rid, "user_id": VIP_ID, "user_email": _vip_email(),
        "user_name": "VIP Test", "amount": 1000, "currency_code": "USDT",
        "reason": "capital operativo de prueba", "status": "pending",
        "created_at": _now_iso(), "updated_at": _now_iso(),
        "repayment_events": [],
    })
    return rid


def test_deposit_reject_sends_email():
    since = _now_iso()
    dep_id = _mk_deposit()
    r = requests.post(f"{API}/admin/deposits/{dep_id}/reject",
                      json={"admin_note": "comprobante ilegible iter197"},
                      headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    ev = _wait_event("deposit_rejected", since)
    assert ev, "deposit_rejected email_event never landed"
    assert "rechazado" in ev["subject"].lower()
    _db().deposits.delete_one({"id": dep_id})


def test_capital_deposit_confirm_sends_email():
    since = _now_iso()
    dep_id = _mk_capital_deposit()
    r = requests.post(f"{API}/admin/vip-capital-deposits/{dep_id}/confirm",
                      json={}, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    ev = _wait_event("capital_deposit_confirmed", since)
    assert ev, "capital_deposit_confirmed email_event never landed"
    assert "confirmado" in ev["subject"].lower()
    # Undo the USDT credit so the VIP balance stays deterministic.
    delta = _db().vip_capital_deposits.find_one({"id": dep_id})["balance_delta_usdt"]
    _db().users.update_one({"user_id": VIP_ID},
                           {"$inc": {"vip_balances.USDT": -delta}})
    _db().vip_capital_deposits.delete_one({"id": dep_id})


def test_capital_deposit_reject_sends_email():
    since = _now_iso()
    dep_id = _mk_capital_deposit()
    r = requests.post(f"{API}/admin/vip-capital-deposits/{dep_id}/reject",
                      json={"admin_note": "hash duplicado iter197"},
                      headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    ev = _wait_event("capital_deposit_rejected", since)
    assert ev, "capital_deposit_rejected email_event never landed"
    _db().vip_capital_deposits.delete_one({"id": dep_id})


def test_settlement_approve_sends_email():
    since = _now_iso()
    sid = _mk_settlement()
    r = requests.post(f"{API}/admin/vip-settlements/{sid}/approve",
                      json={}, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    ev = _wait_event("settlement_confirmed", since)
    assert ev, "settlement_confirmed email_event never landed"
    # Undo the payout debit.
    _db().users.update_one({"user_id": VIP_ID},
                           {"$inc": {"vip_balances.USDT": 200}})
    _db().vip_settlements.delete_one({"id": sid})


def test_settlement_reject_sends_email():
    since = _now_iso()
    sid = _mk_settlement()
    r = requests.post(f"{API}/admin/vip-settlements/{sid}/reject",
                      json={"admin_note": "monto no coincide iter197"},
                      headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    ev = _wait_event("settlement_rejected", since)
    assert ev, "settlement_rejected email_event never landed"
    _db().vip_settlements.delete_one({"id": sid})


def test_capital_request_approve_sends_email():
    since = _now_iso()
    rid = _mk_capital_request()
    r = requests.post(f"{API}/admin/capital-requests/{rid}/approve",
                      json=with_totp_admin({"admin_notes": "ok iter197",
                                            "discount_pct": 10}),
                      headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    ev = _wait_event("capital_request_disbursed", since)
    assert ev, "capital_request_disbursed email_event never landed"
    assert "aprobada" in ev["subject"].lower()
    # Undo the disbursement credit.
    _db().users.update_one({"user_id": VIP_ID},
                           {"$inc": {"vip_balances.USDT": -1000}})
    _db().capital_requests.delete_one({"id": rid})


def test_capital_request_reject_sends_email():
    since = _now_iso()
    rid = _mk_capital_request()
    r = requests.post(f"{API}/admin/capital-requests/{rid}/reject",
                      json=with_totp_admin({"reject_reason":
                                            "sin historial suficiente iter197"}),
                      headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    ev = _wait_event("capital_request_rejected", since)
    assert ev, "capital_request_rejected email_event never landed"
    _db().capital_requests.delete_one({"id": rid})


def test_email_health_endpoint():
    r = requests.get(f"{API}/admin/email-health", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "send_enabled" in body
    assert "api_key_set" in body
    assert set(body["counts_7d"].keys()) == {"sent", "failed", "suppressed"}


def test_email_health_requires_staff():
    r = requests.get(f"{API}/admin/email-health", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 403, r.text
