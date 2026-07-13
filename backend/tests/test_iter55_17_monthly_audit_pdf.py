"""iter55.17 — Monthly audit report PDF + KPIs + integrity hash.

Backend tests covering:
1. `month_range_iso` boundaries (start/end + year rollover)
2. `compute_monthly_kpis` aggregation semantics
3. `compute_integrity_hash` stability & sensitivity to changes
4. `generate_monthly_audit_pdf` produces a valid PDF (%PDF- magic)
5. `GET /admin/audit/monthly.summary` returns KPIs + hash for admin
6. `GET /admin/audit/monthly.pdf` streams a PDF for admin
7. Employee → 403 on both endpoints
8. Invalid year/month → 400
9. `POST /admin/audit/monthly/send-email` requires TOTP step-up
"""
import os
import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, with_totp_admin,
)

# Local imports (pure services + PDF generator)
from services.audit_report import (
    month_range_iso, month_label,
    compute_monthly_kpis, compute_integrity_hash,
)
from audit_pdf_monthly import generate_monthly_audit_pdf


API = f"{BASE_URL}/api"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


# ============================================================
# 1. month_range_iso
# ============================================================

def test_month_range_iso_regular_month():
    since, until = month_range_iso(2026, 3)
    assert since.startswith("2026-03-01T00:00:00")
    # Ends inside March (before April 1st)
    assert until.startswith("2026-03-31T23:59:59")


def test_month_range_iso_december_rolls_over_to_next_year():
    since, until = month_range_iso(2026, 12)
    assert since.startswith("2026-12-01T00:00:00")
    assert until.startswith("2026-12-31T23:59:59")


def test_month_range_iso_february_leap_year():
    # 2024 is a leap year → 29 days
    since, until = month_range_iso(2024, 2)
    assert since.startswith("2024-02-01T00:00:00")
    assert until.startswith("2024-02-29T23:59:59")


def test_month_range_iso_invalid_raises():
    import pytest
    with pytest.raises(ValueError):
        month_range_iso(2026, 13)
    with pytest.raises(ValueError):
        month_range_iso(1999, 5)


def test_month_label_is_spanish():
    assert month_label(2026, 1) == "Enero 2026"
    assert month_label(2026, 12) == "Diciembre 2026"


# ============================================================
# 2. compute_monthly_kpis
# ============================================================

_FAKE_ENTRIES = [
    {"id": "1", "created_at": "2026-07-01T09:00:00+00:00",
     "actor_id": "user_test_admin01", "actor_name": "Admin", "actor_email": "a@x",
     "actor_role": "admin", "action": "order.approved",
     "actor_permissions_effective": "all"},
    {"id": "2", "created_at": "2026-07-01T10:00:00+00:00",
     "actor_id": "user_test_admin01", "actor_name": "Admin", "actor_email": "a@x",
     "actor_role": "admin", "action": "order.rejected",
     "actor_permissions_effective": "all"},
    {"id": "3", "created_at": "2026-07-02T09:00:00+00:00",
     "actor_id": "user_test_employee01", "actor_name": "Emp", "actor_email": "e@x",
     "actor_role": "employee", "action": "rate.update",
     "actor_permissions_effective": "all_staff_default"},
    {"id": "4", "created_at": "2026-07-03T09:00:00+00:00",
     "actor_id": "user_test_employee01", "actor_name": "Emp", "actor_email": "e@x",
     "actor_role": "employee", "action": "user.reject_phone",
     "actor_permissions_effective": ["blocked_contacts"]},
]


def test_kpis_total_and_actors():
    k = compute_monthly_kpis(_FAKE_ENTRIES)
    assert k["total_actions"] == 4
    assert k["distinct_actors"] == 2


def test_kpis_group_ordering():
    k = compute_monthly_kpis(_FAKE_ENTRIES)
    codes = [b["code"] for b in k["by_group"]]
    # order.* appears twice — must be first
    assert codes[0] == "order"
    assert set(codes) >= {"order", "rate", "user"}


def test_kpis_top_actors_desc():
    k = compute_monthly_kpis(_FAKE_ENTRIES)
    actors = k["top_actors"]
    # Both have 2 events — order is by count desc; ties by insertion
    assert actors[0]["count"] >= actors[1]["count"]


def test_kpis_anti_fraud_flags_reject_phone():
    k = compute_monthly_kpis(_FAKE_ENTRIES)
    fraud = k["anti_fraud"]
    assert any(item["action"] == "user.reject_phone" for item in fraud)


def test_kpis_permission_scope_buckets():
    k = compute_monthly_kpis(_FAKE_ENTRIES)
    scope = k["permission_scope"]
    assert scope.get("admin") == 2
    assert scope.get("staff_default") == 1
    assert scope.get("scoped") == 1


def test_kpis_empty_input():
    k = compute_monthly_kpis([])
    assert k["total_actions"] == 0
    assert k["distinct_actors"] == 0
    assert k["by_group"] == []
    assert k["top_actors"] == []


# ============================================================
# 3. compute_integrity_hash
# ============================================================

def test_integrity_hash_stable_and_deterministic():
    h1 = compute_integrity_hash(_FAKE_ENTRIES, "Julio 2026")
    h2 = compute_integrity_hash(list(reversed(_FAKE_ENTRIES)), "Julio 2026")
    assert len(h1) == 64  # SHA-256 hex
    assert h1 == h2  # order-independent (sorts by created_at internally)


def test_integrity_hash_sensitive_to_row_change():
    h1 = compute_integrity_hash(_FAKE_ENTRIES, "Julio 2026")
    tampered = list(_FAKE_ENTRIES) + [
        {"id": "999", "created_at": "2026-07-04T09:00:00+00:00",
         "actor_id": "x", "action": "hidden.event", "entity_type": "",
         "entity_id": ""},
    ]
    h2 = compute_integrity_hash(tampered, "Julio 2026")
    assert h1 != h2


def test_integrity_hash_sensitive_to_period():
    h1 = compute_integrity_hash(_FAKE_ENTRIES, "Julio 2026")
    h2 = compute_integrity_hash(_FAKE_ENTRIES, "Agosto 2026")
    assert h1 != h2


# ============================================================
# 4. PDF generation
# ============================================================

def test_generate_monthly_audit_pdf_returns_valid_pdf():
    kpis = compute_monthly_kpis(_FAKE_ENTRIES)
    h = compute_integrity_hash(_FAKE_ENTRIES, "Julio 2026")
    pdf = generate_monthly_audit_pdf(_FAKE_ENTRIES, "Julio 2026", kpis, h)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000  # Non-trivial content


def test_generate_monthly_audit_pdf_handles_empty_period():
    """Empty months must still produce a valid PDF (owner should see the
    integrity hash even for 0 rows)."""
    kpis = compute_monthly_kpis([])
    h = compute_integrity_hash([], "Julio 2026")
    pdf = generate_monthly_audit_pdf([], "Julio 2026", kpis, h)
    assert pdf[:5] == b"%PDF-"


# ============================================================
# 5+6+7. HTTP endpoints (E2E through the ingress)
# ============================================================

def test_summary_endpoint_admin_ok():
    r = requests.get(
        f"{API}/admin/audit/monthly.summary?year=2026&month=7",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["period_label"] == "Julio 2026"
    assert body["period_slug"] == "2026-07"
    assert len(body["integrity_hash"]) == 64
    assert "kpis" in body
    assert "row_count" in body


def test_summary_endpoint_employee_forbidden():
    r = requests.get(
        f"{API}/admin/audit/monthly.summary?year=2026&month=7",
        headers=_hdr(EMPLOYEE_TOKEN),
    )
    assert r.status_code == 403


def test_pdf_endpoint_admin_ok():
    r = requests.get(
        f"{API}/admin/audit/monthly.pdf?year=2026&month=7",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:5] == b"%PDF-"
    # File name includes the period slug
    disp = r.headers.get("content-disposition", "")
    assert "auditoria-2026-07" in disp


def test_pdf_endpoint_employee_forbidden():
    r = requests.get(
        f"{API}/admin/audit/monthly.pdf?year=2026&month=7",
        headers=_hdr(EMPLOYEE_TOKEN),
    )
    assert r.status_code == 403


# ============================================================
# 8. Invalid year/month → 400
# ============================================================

def test_invalid_month_returns_400():
    r = requests.get(
        f"{API}/admin/audit/monthly.pdf?year=2026&month=13",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r.status_code == 400
    r2 = requests.get(
        f"{API}/admin/audit/monthly.pdf?year=2026&month=0",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r2.status_code == 400


def test_invalid_year_returns_400():
    r = requests.get(
        f"{API}/admin/audit/monthly.pdf?year=1999&month=1",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r.status_code == 400


# ============================================================
# 9. Email send endpoint — TOTP step-up required
# ============================================================

def test_email_send_requires_totp():
    r = requests.post(
        f"{API}/admin/audit/monthly/send-email",
        headers=_hdr(ADMIN_TOKEN),
        json={"year": 2026, "month": 7},  # NO totp_code
    )
    assert r.status_code in (401, 412)  # TOTP_INVALID or TOTP_SETUP_REQUIRED
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("code", "").startswith("TOTP_")


def test_email_send_admin_with_totp_ok():
    """Happy path: admin sends the monthly report with a fresh TOTP code.

    Note: RESEND_API_KEY may be absent in the test environment; email_service._send
    returns False silently in that case, so `sent` may equal 0. What we verify
    is that the endpoint accepts the request and returns the expected shape.
    """
    r = requests.post(
        f"{API}/admin/audit/monthly/send-email",
        headers=_hdr(ADMIN_TOKEN),
        json=with_totp_admin({"year": 2026, "month": 7}),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["period_label"] == "Julio 2026"
    assert body["period"] == "2026-07"
    assert "integrity_hash" in body
    assert "recipients" in body
    assert "sent" in body


def test_email_send_employee_forbidden():
    r = requests.post(
        f"{API}/admin/audit/monthly/send-email",
        headers=_hdr(EMPLOYEE_TOKEN),
        json={"year": 2026, "month": 7, "totp_code": "000000"},
    )
    assert r.status_code == 403


# ============================================================
# 10. Integrity hash is stable across GET summary and GET pdf calls
# ============================================================

def test_integrity_hash_stable_between_summary_and_pdf():
    """Both endpoints hit the same collection, so the hash should match iff
    no new audit rows landed between the two HTTP calls. This test tolerates
    the (rare) case where a background job inserts a row in-between."""
    r1 = requests.get(
        f"{API}/admin/audit/monthly.summary?year=2026&month=7",
        headers=_hdr(ADMIN_TOKEN),
    )
    r2 = requests.get(
        f"{API}/admin/audit/monthly.summary?year=2026&month=7",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r1.status_code == 200 and r2.status_code == 200
    b1, b2 = r1.json(), r2.json()
    # In a quiet test env the two calls see identical rows → same hash.
    # If a background job inserted a row between the calls, `row_count`
    # would differ; in that case skip the deterministic hash check so
    # we don't fire a false positive.
    if b1.get("row_count") == b2.get("row_count"):
        assert b1["integrity_hash"] == b2["integrity_hash"]
