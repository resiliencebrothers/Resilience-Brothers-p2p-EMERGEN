"""iter196 — Manual "Reenviar este email" support tool.

Validates:
  1. New sends persist `html_body` (only for sent/failed, not suppressed).
  2. Old rows without `html_body` return a friendly error and don't crash.
  3. Successful resend triggers a fresh `email_events` row + tags the
     original with `retried_from`.
"""
import os
import time

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}",
            "Content-Type": "application/json"}


def _seed_event(status: str, with_html: bool, kind: str = "withdrawal_paid") -> str:
    """Insert a fake email_events row and return its id."""
    from datetime import datetime, timezone
    ev_id = f"emev_test_{int(time.time() * 1000)}_{status}"
    doc = {
        "id": ev_id,
        "to": "vip.test@resilience.com",
        "subject": f"Test iter196 · {status}",
        "kind": kind,
        "status": status,
        "error": "" if status == "sent" else "seed error",
        "provider_id": "",
        "attempts": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if with_html:
        doc["html_body"] = "<p>Test HTML body iter196</p>"
    _db().email_events.insert_one(doc)
    return ev_id


# ------------------------------------------------------------------
# Listing endpoint surfaces the `can_resend` boolean without leaking html
# ------------------------------------------------------------------

def test_email_events_list_exposes_can_resend_flag():
    ev_with = _seed_event("failed", with_html=True)
    ev_without = _seed_event("failed", with_html=False)

    r = requests.get(f"{API}/admin/users/user_test_vip01/email-events?limit=50",
                     headers=_hdr())
    assert r.status_code == 200, r.text
    events = {e["id"]: e for e in r.json()["events"]}

    assert ev_with in events and events[ev_with]["can_resend"] is True
    assert ev_without in events and events[ev_without]["can_resend"] is False
    # html_body must NOT leak to the client — only the boolean summary.
    assert "html_body" not in events[ev_with]

    _db().email_events.delete_many({"id": {"$in": [ev_with, ev_without]}})


# ------------------------------------------------------------------
# Resend endpoint — happy path
# ------------------------------------------------------------------

def test_resend_replays_html_and_chains_the_new_row():
    ev_id = _seed_event("failed", with_html=True, kind="deposit_confirmed")

    r = requests.post(f"{API}/admin/email-events/{ev_id}/resend",
                      headers=_hdr())
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # A brand-new row must exist for the same recipient + subject, and it
    # should carry the `retried_from` back-reference.
    db = _db()
    ev = db.email_events.find_one({"id": ev_id}, {"_id": 0})
    child = db.email_events.find_one(
        {"to": ev["to"], "subject": ev["subject"], "retried_from": ev_id},
        {"_id": 0},
    )
    assert child, "new email_events row not chained via retried_from"
    assert child["status"] in ("sent", "suppressed", "failed")

    db.email_events.delete_many(
        {"$or": [{"id": ev_id}, {"retried_from": ev_id}]},
    )


# ------------------------------------------------------------------
# Resend endpoint — friendly errors
# ------------------------------------------------------------------

def test_resend_rejects_when_html_missing():
    ev_id = _seed_event("failed", with_html=False)

    r = requests.post(f"{API}/admin/email-events/{ev_id}/resend",
                      headers=_hdr())
    assert r.status_code == 400, r.text
    assert "sin cuerpo HTML" in r.json()["detail"]

    _db().email_events.delete_one({"id": ev_id})


def test_resend_rejects_suppressed_rows():
    ev_id = _seed_event("suppressed", with_html=True)

    r = requests.post(f"{API}/admin/email-events/{ev_id}/resend",
                      headers=_hdr())
    assert r.status_code == 400, r.text
    assert "desactivado" in r.json()["detail"].lower()

    _db().email_events.delete_one({"id": ev_id})


def test_resend_unknown_event_404s():
    r = requests.post(f"{API}/admin/email-events/emev_does_not_exist/resend",
                      headers=_hdr())
    assert r.status_code == 404


# ------------------------------------------------------------------
# End-to-end: real send persists html_body so resend works
# ------------------------------------------------------------------

def test_real_send_persists_html_body_for_later_resend():
    """A fresh notify_withdrawal_paid call should write an email_events
    row that has can_resend=True."""
    from email_service import notify_withdrawal_paid

    w = {"id": "wd_it196reg1", "method": "transfer",
         "amount_usd": 25, "currency": "USD"}
    ok = notify_withdrawal_paid(w, {
        "email": "vip.test@resilience.com",
        "name": "Ledger Test",
        "preferred_language": "es",
    })
    assert ok

    time.sleep(0.4)
    # Look up the freshly written row
    r = requests.get(f"{API}/admin/users/user_test_vip01/email-events?limit=5",
                     headers=_hdr())
    events = r.json()["events"]
    subj_prefix = "Retiro #it196r"
    row = next((e for e in events if e["subject"].startswith(subj_prefix)), None)
    assert row, f"withdrawal_paid ledger row missing; got {[e['subject'] for e in events]}"
    # In this env EMAIL_SEND_ENABLED=true, so status should be `sent` and
    # can_resend should be True.
    assert row["status"] in ("sent", "failed")
    assert row["can_resend"] is True

    _db().email_events.delete_many({"subject": {"$regex": "^Retiro #it196r"}})
