"""iter176 — Reporte diario de operaciones (casos >48h sin resolver)."""
import os
import time
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

API = f"{BASE_URL}/api/admin/ops-report"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso_ago(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _cleanup():
    db = _db()
    db.users.delete_many({"user_id": {"$regex": "^user_t176_"}})
    db.appeals.delete_many({"id": {"$regex": "^appeal_t176_"}})
    db.support_tickets.delete_many({"id": {"$regex": "^tkt_t176_"}})
    db.email_events.delete_many({"kind": "daily_ops_report",
                                 "to": {"$regex": "t176"}})


def setup_module():
    _cleanup()
    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    # STALE (>48h) — deben aparecer
    db.users.insert_one({
        "user_id": "user_t176_stale", "name": "Fulano Sospechoso",
        "email": "t176stale@test.com", "phone": "+5355511176",
        "role": "normal", "account_status": "under_review",
        "under_review_since": _iso_ago(72), "created_at": _iso_ago(72),
    })
    db.appeals.insert_one({
        "id": "appeal_t176_stale", "user_id": "user_t176_stale",
        "user_name": "Fulano Sospechoso", "user_email": "t176stale@test.com",
        "message": "No soy estafador, revisen mi caso por favor",
        "status": "pending", "created_at": _iso_ago(60),
    })
    db.support_tickets.insert_one({
        "id": "tkt_t176_stale", "user_id": "user_t176_stale",
        "user_name": "Fulano Sospechoso", "user_email": "t176stale@test.com",
        "category": "general", "subject": "Posible fraude en mi orden",
        "status": "open", "unread_by_staff": True, "messages": [],
        "created_at": _iso_ago(55), "updated_at": _iso_ago(55),
    })
    # FRESCOS (<48h) — NO deben aparecer
    db.users.insert_one({
        "user_id": "user_t176_fresh", "name": "Mengano Reciente",
        "email": "t176fresh@test.com", "role": "normal",
        "account_status": "under_review",
        "under_review_since": _iso_ago(5), "created_at": now,
    })
    db.support_tickets.insert_one({
        "id": "tkt_t176_fresh", "user_id": "user_t176_fresh",
        "user_name": "Mengano Reciente", "user_email": "t176fresh@test.com",
        "category": "general", "subject": "Duda reciente",
        "status": "open", "unread_by_staff": True, "messages": [],
        "created_at": _iso_ago(2), "updated_at": _iso_ago(2),
    })


def teardown_module():
    _cleanup()


class TestPreview:
    def test_preview_includes_only_stale(self):
        r = requests.get(f"{API}/preview", headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["hours"] == 48
        ur_ids = {u["user_id"] for u in d["under_review"]}
        assert "user_t176_stale" in ur_ids
        assert "user_t176_fresh" not in ur_ids
        ap_ids = {a["id"] for a in d["appeals"]}
        assert "appeal_t176_stale" in ap_ids
        tk_ids = {t["id"] for t in d["tickets"]}
        assert "tkt_t176_stale" in tk_ids
        assert "tkt_t176_fresh" not in tk_ids
        assert d["total"] >= 3
        for u in d["under_review"]:
            if u["user_id"] == "user_t176_stale":
                assert u["age_hours"] >= 71

    def test_preview_requires_admin(self):
        assert requests.get(f"{API}/preview").status_code in (401, 403)


class TestRun:
    def test_manual_run_sends_and_audits(self):
        r = requests.post(f"{API}/run", headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total"] >= 3
        assert d["under_review"] >= 1 and d["appeals"] >= 1 and d["tickets"] >= 1
        assert d["recipients"] >= 1
        assert d["sent"] >= 1  # EMAIL_SEND_ENABLED=false → suppressed cuenta como sent
        db = _db()
        ev = db.email_events.find_one({"kind": "daily_ops_report"},
                                      sort=[("_id", -1)])
        assert ev is not None, "no email_event recorded"
        audit = db.audit_log.find_one({"action": "ops_report.manual_run"},
                                      sort=[("_id", -1)])
        assert audit is not None

    def test_opt_out_flag_skips(self):
        db = _db()
        prev = db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
        had_flag = "auto_send_daily_ops_report" in prev
        db.settings.update_one({"id": "global"},
                               {"$set": {"auto_send_daily_ops_report": False}},
                               upsert=True)
        try:
            r = requests.post(f"{API}/run", headers=_h(ADMIN))
            assert r.status_code == 200
            assert r.json().get("skipped") == "opt_out"
        finally:
            if had_flag:
                db.settings.update_one(
                    {"id": "global"},
                    {"$set": {"auto_send_daily_ops_report":
                              prev["auto_send_daily_ops_report"]}})
            else:
                db.settings.update_one(
                    {"id": "global"},
                    {"$unset": {"auto_send_daily_ops_report": ""}})


class TestSchedulerJob:
    def test_job_registered(self):
        import subprocess
        out = subprocess.run(
            ["grep", "-c", "daily_ops_fraud_report", "/app/backend/scheduler.py"],
            capture_output=True, text=True)
        assert int(out.stdout.strip()) >= 2
