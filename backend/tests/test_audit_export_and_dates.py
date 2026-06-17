"""Iter10 — Audit Log pagination headers, CSV/PDF export, and date filters.

Covers:
- GET /api/admin/audit pagination headers + disjoint pages + consistent X-Total-Count
- GET /api/admin/audit/export.csv: admin-only, UTF-8 BOM, 10-column header
- GET /api/admin/audit/export.pdf: admin-only, %PDF-1.4 + %%EOF, attachment header
- since/until date filters: YYYY-MM-DD expansion, full ISO, invalid → 400, future since → []
- Filters propagate to CSV and PDF exports
"""
import io
import csv
import pytest
import requests

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN, EMPLOYEE_TOKEN as EMP


def _h(t=None):
    h = {"Content-Type": "application/json"}
    if t:
        h["Authorization"] = f"Bearer {t}"
    return h


# -------- AUDIT PAGINATION HEADERS --------
class TestAuditPagination:
    def test_headers_present_and_array_body(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit",
                         headers=_h(ADMIN), params={"limit": 5, "offset": 0})
        assert r.status_code == 200
        assert "X-Total-Count" in r.headers
        assert int(r.headers["X-Offset"]) == 0
        assert int(r.headers["X-Limit"]) == 5
        body = r.json()
        assert isinstance(body, list)
        assert len(body) <= 5

    def test_pages_are_disjoint(self):
        first = requests.get(f"{BASE_URL}/api/admin/audit",
                             headers=_h(ADMIN), params={"limit": 5, "offset": 0})
        total = int(first.headers["X-Total-Count"])
        if total <= 5:
            pytest.skip(f"only {total} audit rows")
        second = requests.get(f"{BASE_URL}/api/admin/audit",
                              headers=_h(ADMIN), params={"limit": 5, "offset": 5})
        assert second.status_code == 200
        # audit_log uses created_at; use id-like keys if present, fallback to (created_at, action, entity_id)
        def k(e):
            return (e.get("created_at"), e.get("action"), e.get("entity_id"),
                    e.get("actor_id"), e.get("summary"))
        s1 = {k(e) for e in first.json()}
        s2 = {k(e) for e in second.json()}
        assert s1.isdisjoint(s2), "audit pagination overlap"
        assert int(second.headers["X-Total-Count"]) == total


# -------- CSV EXPORT --------
class TestAuditCSVExport:
    def test_employee_forbidden(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit/export.csv", headers=_h(EMP))
        assert r.status_code == 403

    def test_unauthenticated_blocked(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit/export.csv")
        # No bearer → require_admin should reject (401 or 403)
        assert r.status_code in (401, 403)

    def test_admin_csv_format(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit/export.csv", headers=_h(ADMIN))
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("Content-Type", "")
        cd = r.headers.get("Content-Disposition", "")
        assert "attachment" in cd and "audit_log_" in cd and ".csv" in cd
        # UTF-8 BOM prefix
        assert r.content.startswith(b"\xef\xbb\xbf"), "missing UTF-8 BOM"
        # Header row has 10 expected columns in order
        text = r.content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        assert header == [
            "created_at", "actor_id", "actor_email", "actor_name", "actor_role",
            "action", "entity_type", "entity_id", "summary", "details",
        ]

    def test_csv_respects_action_filter(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit/export.csv",
                         headers=_h(ADMIN), params={"action": "rate.update"})
        assert r.status_code == 200
        text = r.content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        # Skip header — every data row must have action == rate.update (or be empty)
        for row in rows[1:]:
            assert row[5] == "rate.update"


# -------- PDF EXPORT --------
class TestAuditPDFExport:
    def test_employee_forbidden(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit/export.pdf", headers=_h(EMP))
        assert r.status_code == 403

    def test_admin_pdf_format(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit/export.pdf", headers=_h(ADMIN))
        assert r.status_code == 200
        assert r.headers.get("Content-Type", "").startswith("application/pdf")
        cd = r.headers.get("Content-Disposition", "")
        assert "attachment" in cd and "audit_log_" in cd and ".pdf" in cd
        body = r.content
        assert body.startswith(b"%PDF-1.4"), f"PDF magic missing, got {body[:20]!r}"
        # %%EOF usually near the very end (sometimes followed by trailing newline)
        assert b"%%EOF" in body[-32:], "PDF EOF marker missing at tail"

    def test_pdf_with_filters_does_not_500(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit/export.pdf",
                         headers=_h(ADMIN),
                         params={"action": "rate.update", "since": "2024-01-01"})
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF-1.4")


# -------- DATE FILTERS --------
class TestAuditDateFilters:
    def test_since_date_only_accepted(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit",
                         headers=_h(ADMIN), params={"since": "2024-01-01", "limit": 5})
        assert r.status_code == 200

    def test_until_date_only_accepted(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit",
                         headers=_h(ADMIN), params={"until": "2030-12-31", "limit": 5})
        assert r.status_code == 200

    def test_full_iso_accepted(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit",
                         headers=_h(ADMIN),
                         params={"since": "2024-01-01T00:00:00+00:00", "limit": 5})
        assert r.status_code == 200

    def test_invalid_date_400(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit",
                         headers=_h(ADMIN), params={"since": "not-a-date"})
        assert r.status_code == 400
        data = r.json()
        assert "detail" in data and "inv" in data["detail"].lower()

    def test_future_since_returns_empty(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit",
                         headers=_h(ADMIN), params={"since": "2099-01-01", "limit": 10})
        assert r.status_code == 200
        assert r.json() == []
        assert int(r.headers["X-Total-Count"]) == 0

    def test_date_filter_propagates_to_csv(self):
        # future date → CSV with only header (1 row)
        r = requests.get(f"{BASE_URL}/api/admin/audit/export.csv",
                         headers=_h(ADMIN), params={"since": "2099-01-01"})
        assert r.status_code == 200
        text = r.content.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        assert len(rows) == 1, f"expected only header row, got {len(rows)}"

    def test_date_filter_propagates_to_pdf(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit/export.pdf",
                         headers=_h(ADMIN), params={"since": "2099-01-01"})
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF-1.4")
