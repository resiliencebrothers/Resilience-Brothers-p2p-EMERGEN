"""iter55.36l — Multi-month revenue analytics export (CSV + PDF).

Verifies:
  • GET /admin/revenue/analytics/export?format=csv → 200 + CSV bytes with the
    expected header + Spanish accents preserved (BOM).
  • Same with format=pdf → 200 + application/pdf + PDF magic bytes.
  • format=invalid → 400.
  • Non-admin token → 403/401 (auth gate reused from require_admin).
"""
import os
import requests

from tests.conftest import BASE_URL as API_ROOT, ADMIN_TOKEN, NORMAL_TOKEN

API = f"{API_ROOT}/api"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_analytics_csv_export_returns_valid_csv():
    r = requests.get(
        f"{API}/admin/revenue/analytics/export?format=csv&days=30",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv"), r.headers
    body = r.content
    # UTF-8-with-BOM for Excel Spanish-accent support
    assert body.startswith(b"\xef\xbb\xbf"), body[:16]
    text = body.decode("utf-8-sig")
    assert "Reporte de Ingresos" in text
    assert "Aporte por categoría" in text
    # Header row for the monthly table
    assert "Mes,P2P (USDT),Marketplace (USDT)" in text


def test_analytics_pdf_export_returns_pdf_magic_bytes():
    r = requests.get(
        f"{API}/admin/revenue/analytics/export?format=pdf&days=30",
        headers=_hdr(ADMIN_TOKEN),
        timeout=20,
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-"), r.content[:16]
    assert len(r.content) > 5000  # non-trivial size (includes chart)


def test_analytics_export_rejects_unknown_format():
    r = requests.get(
        f"{API}/admin/revenue/analytics/export?format=xml",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r.status_code == 400
    assert "csv" in r.text.lower() or "pdf" in r.text.lower()


def test_analytics_export_rejects_non_admin():
    r = requests.get(
        f"{API}/admin/revenue/analytics/export?format=csv",
        headers=_hdr(NORMAL_TOKEN),
    )
    assert r.status_code in (401, 403), r.text


def test_analytics_export_without_days_uses_all_time():
    """Missing/empty `days` → summary covers all time (period label reflects it)."""
    r = requests.get(
        f"{API}/admin/revenue/analytics/export?format=csv",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert "todo el tiempo" in text
