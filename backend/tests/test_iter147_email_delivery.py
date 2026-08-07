"""iter147 — Email delivery ledger + staff resend-verification.

Root-cause support for "el correo de verificación no llega":
1. Every email send attempt is persisted to `email_events`
   (status sent | failed | suppressed, error, attempts).
   In this preview EMAIL_SEND_ENABLED=false → registrations record
   a `suppressed` event with kind=email_verification.
2. GET  /admin/users/{id}/email-events   (staff) — delivery history.
3. POST /admin/users/{id}/resend-verification (staff) — regenerates the
   token and resends; 60s cooldown; 400 when already verified.
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"
EMAIL = f"delivery.test.{uuid.uuid4().hex[:8]}@rbtest.com"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def registered_user():
    r = requests.post(f"{API}/auth/register", json={
        "email": EMAIL, "password": "SuperSecret123!",
        "name": "Delivery Tester", "phone": "+5355512345",
    })
    assert r.status_code == 200, r.text
    user = _db().users.find_one({"email": EMAIL}, {"_id": 0})
    assert user
    yield user
    _db().users.delete_many({"email": EMAIL})
    _db().email_events.delete_many({"to": EMAIL})
    _db().user_sessions.delete_many({"user_id": user["user_id"]})


def test_registration_records_email_event(registered_user):
    events = list(_db().email_events.find({"to": EMAIL}, {"_id": 0}))
    assert len(events) == 1, events
    ev = events[0]
    assert ev["kind"] == "email_verification"
    assert ev["status"] == "suppressed"  # preview: EMAIL_SEND_ENABLED=false
    assert "Verifica" in ev["subject"] or "Verify" in ev["subject"]


def test_admin_email_events_endpoint(registered_user):
    uid = registered_user["user_id"]
    r = requests.get(f"{API}/admin/users/{uid}/email-events", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == EMAIL
    assert body["events"] and body["events"][0]["kind"] == "email_verification"
    # clients can't see the ledger
    r2 = requests.get(f"{API}/admin/users/{uid}/email-events", headers=_hdr(VIP_TOKEN))
    assert r2.status_code == 403
    r3 = requests.get(f"{API}/admin/users/nope_xx/email-events", headers=_hdr(ADMIN_TOKEN))
    assert r3.status_code == 404


def test_admin_resend_verification_flow(registered_user):
    uid = registered_user["user_id"]
    db = _db()
    old_token = db.users.find_one({"user_id": uid})["verification_token"]
    r = requests.post(f"{API}/admin/users/{uid}/resend-verification",
                      headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "sent": True}
    fresh = db.users.find_one({"user_id": uid})
    assert fresh["verification_token"] != old_token  # token rotated
    assert db.email_events.count_documents(
        {"to": EMAIL, "kind": "email_verification"}) == 2
    # cooldown: immediate second resend → 429
    r2 = requests.post(f"{API}/admin/users/{uid}/resend-verification",
                       headers=_hdr(ADMIN_TOKEN))
    assert r2.status_code == 429
    # clients blocked
    r3 = requests.post(f"{API}/admin/users/{uid}/resend-verification",
                       headers=_hdr(VIP_TOKEN))
    assert r3.status_code == 403


def test_resend_rejected_when_already_verified(registered_user):
    uid = registered_user["user_id"]
    db = _db()
    db.users.update_one({"user_id": uid}, {"$set": {"email_verified": True}})
    try:
        r = requests.post(f"{API}/admin/users/{uid}/resend-verification",
                          headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 400
    finally:
        db.users.update_one({"user_id": uid}, {"$set": {"email_verified": False}})
