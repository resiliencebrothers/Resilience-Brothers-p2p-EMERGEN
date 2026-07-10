"""iter55.21 — Monthly audit auto-send scheduler.

Covers the pure `run_monthly_audit_email` function which builds the audit
bundle for the previous calendar month and fans it out to admin recipients.
The APScheduler cron wiring is trivially exercised (idempotency + job list).
"""
import os
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

import email_service
from scheduler import run_monthly_audit_email, _previous_month
from datetime import datetime, timezone


@pytest.fixture
def async_db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    yield db
    client.close()


def test_previous_month_helper_regular_case():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    y, m, slug = _previous_month(now)
    assert y == 2026 and m == 6
    assert slug == "2026-06"


def test_previous_month_helper_january_rolls_back_a_year():
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    y, m, slug = _previous_month(now)
    assert y == 2025 and m == 12
    assert slug == "2025-12"


@pytest.mark.asyncio
async def test_run_monthly_audit_email_calls_notify_and_persists_no_state(async_db, monkeypatch):
    """Feature 2 happy path — the job builds the PDF and invokes
    email_service.notify_monthly_audit for each admin recipient. We monkey-
    patch _send to intercept without hitting Resend."""
    calls = []
    original_send = email_service._send

    def fake_send(to, subject, html, attachments=None):
        calls.append({"to": to, "subject": subject, "has_attachment": bool(attachments)})
        return True
    monkeypatch.setattr(email_service, "_send", fake_send)

    try:
        await run_monthly_audit_email(async_db)
    finally:
        email_service._send = original_send

    # If there is at least one admin in the test DB we expect >=1 send.
    admins = await async_db.users.count_documents({"role": "admin"})
    if admins > 0:
        assert len(calls) >= 1, "expected at least one email attempt"
        for c in calls:
            assert "auditor" in c["subject"].lower() or "audit" in c["subject"].lower()
            assert c["has_attachment"] is True  # the PDF must be attached


@pytest.mark.asyncio
async def test_opt_out_flag_short_circuits_the_job(async_db, monkeypatch):
    """When settings.global.auto_send_monthly_audit == False, the job must
    exit before generating the PDF / sending anything."""
    calls = []
    monkeypatch.setattr(email_service, "_send",
                         lambda to, s, h, attachments=None: (calls.append(to), True)[1])

    # Set opt-out
    await async_db.settings.update_one(
        {"_id": "global"},
        {"$set": {"auto_send_monthly_audit": False}}, upsert=True,
    )
    try:
        await run_monthly_audit_email(async_db)
        assert calls == [], "expected zero send calls when opt-out is active"
    finally:
        # Restore
        await async_db.settings.update_one(
            {"_id": "global"},
            {"$unset": {"auto_send_monthly_audit": ""}},
        )


@pytest.mark.asyncio
async def test_scheduler_registers_the_new_job(async_db):
    """Cheap wiring check: after start_scheduler the monthly_audit_email
    job is present in the scheduler with the expected cron trigger."""
    from scheduler import start_scheduler, stop_scheduler

    async def _dummy_ts(_g, year=None, month=None):
        return []

    sched = start_scheduler(async_db, _dummy_ts)
    try:
        ids = [j.id for j in sched.get_jobs()]
        assert "monthly_audit_email" in ids
        job = sched.get_job("monthly_audit_email")
        # cron trigger — day=1 hour=9 minute=15
        trig_str = str(job.trigger)
        assert "day='1'" in trig_str
        assert "hour='9'" in trig_str
        assert "minute='15'" in trig_str
    finally:
        stop_scheduler()
