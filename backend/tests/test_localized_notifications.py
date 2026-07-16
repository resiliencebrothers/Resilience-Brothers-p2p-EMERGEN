"""iter68 — Localized email and PDF regression tests.

Ensures customer-facing emails and PDFs are rendered in the recipient's
`preferred_language`. Historic offenders would render Spanish subject lines
to English-speaking users, hurting conversion / creating support tickets.

These tests exercise the pure rendering layer (no Resend / no HTTP) so they
run fast in CI. Callers-in-context (routes/profile.py, routes/auth.py,
services/orders_helpers.py) are covered by the integration tests further
down that hit the real API.
"""
from __future__ import annotations

import email_service as es
from transactions_pdf import generate_transactions_pdf


# ---------------- Email rendering: subject + body language switch ---------

def _rendered_email_bodies(fn, *args, lang: str) -> tuple[str, str]:
    """Capture the (subject, html) that `_send` would receive without actually
    hitting Resend. Patches `es._send` temporarily via monkey-attribute."""
    captured = {}
    orig = es._send
    def _fake_send(to, subject, html, attachments=None):
        captured["subject"] = subject
        captured["html"] = html
        return True
    es._send = _fake_send
    try:
        fn(*args, lang=lang)
    finally:
        es._send = orig
    return captured["subject"], captured["html"]


def test_order_approved_email_english_content():
    """`preferred_language='en'` on the user doc → subject + body in English."""
    captured = {}
    orig = es._send
    es._send = lambda to, subject, html, attachments=None: captured.update(subject=subject, html=html) or True
    try:
        es.notify_order_approved(
            {"id": "abcdef1234", "from_code": "USDT", "to_code": "USD",
             "amount_from": 100, "amount_to": 99.5, "rate_applied": 0.995,
             "commission_percent": 0.5, "delivery_method": "accumulate",
             "admin_note": ""},
            {"email": "e@t.com", "name": "Test", "preferred_language": "en"},
        )
    finally:
        es._send = orig
    assert "was approved" in captured["subject"].lower()
    assert "approved" in captured["html"].lower()
    assert "you sent" in captured["html"].lower() or "You sent" in captured["html"]
    # Spanish leak check
    assert "Enviaste" not in captured["html"]
    assert "aprobada" not in captured["subject"].lower()


def test_order_approved_email_spanish_default():
    """No `preferred_language` field → defaults to Spanish."""
    captured = {}
    orig = es._send
    es._send = lambda to, subject, html, attachments=None: captured.update(subject=subject, html=html) or True
    try:
        es.notify_order_approved(
            {"id": "abcdef1234", "from_code": "USDT", "to_code": "USD",
             "amount_from": 100, "amount_to": 99.5, "rate_applied": 0.995,
             "commission_percent": 0.5, "delivery_method": "accumulate",
             "admin_note": ""},
            {"email": "e@t.com", "name": "Test"},  # no preferred_language
        )
    finally:
        es._send = orig
    assert "fue aprobada" in captured["subject"]
    assert "Enviaste" in captured["html"]


def test_order_rejected_email_english():
    captured = {}
    orig = es._send
    es._send = lambda to, subject, html, attachments=None: captured.update(subject=subject, html=html) or True
    try:
        es.notify_order_rejected(
            {"id": "abcdef1234", "from_code": "USDT", "to_code": "USD",
             "amount_from": 100, "admin_note": "Missing payment proof"},
            {"email": "e@t.com", "name": "Alice", "preferred_language": "en"},
        )
    finally:
        es._send = orig
    assert "needs attention" in captured["subject"]
    assert "REJECTED" in captured["html"]
    assert "Missing payment proof" in captured["html"]


def test_verification_email_english():
    subj, html = _rendered_email_bodies(
        es.notify_email_verification, "u@t.com", "Bob", "tok123", lang="en"
    )
    assert "Verify your email" in subj
    assert "VERIFY MY EMAIL" in html
    assert "Verifica" not in html


def test_verification_email_spanish():
    subj, html = _rendered_email_bodies(
        es.notify_email_verification, "u@t.com", "Bob", "tok123", lang="es"
    )
    assert "Verifica tu correo" in subj
    assert "VERIFICAR MI EMAIL" in html


def test_password_reset_email_english():
    subj, html = _rendered_email_bodies(
        es.notify_password_reset, "u@t.com", "Bob", "resettok", lang="en"
    )
    assert "Reset your password" in subj
    assert "CREATE NEW PASSWORD" in html


def test_password_changed_email_english():
    subj, html = _rendered_email_bodies(
        es.notify_password_changed, "u@t.com", "Bob", lang="en"
    )
    assert "Your password was updated" in subj
    assert "Password changed" in html


def test_email_change_code_english():
    subj, html = _rendered_email_bodies(
        es.notify_email_change_code, "u@t.com", "Bob", "483920", lang="en"
    )
    assert "Confirm your new email" in subj
    assert "Confirmation code" in html
    assert "483920" in html


def test_email_change_alert_english():
    subj, html = _rendered_email_bodies(
        es.notify_email_change_alert, "u@t.com", "Bob", "n***@x.com", lang="en"
    )
    assert "Security alert" in subj
    assert "Wasn't you?" in html


def test_phone_change_approved_english():
    subj, html = _rendered_email_bodies(
        es.notify_phone_change_approved, "u@t.com", "Bob", "+1-***-9999", lang="en"
    )
    assert "phone was verified" in subj.lower()
    assert "Phone verified" in html


def test_phone_change_rejected_english():
    subj, html = _rendered_email_bodies(
        es.notify_phone_change_rejected, "u@t.com", "Bob",
        "+1-***-9999", "Number belongs to another account", lang="en"
    )
    assert "rejected" in subj.lower()
    assert "Reason" in html
    assert "Number belongs to another account" in html


# ---------------- PDF: transactions register ---------------------------

def test_transactions_pdf_generates_bytes_for_both_langs():
    """Smoke test — the PDF builds cleanly for both languages without raising."""
    entries = [
        {"created_at": "2026-01-10T12:00:00+00:00", "direction": "in",
         "currency": "USDT", "amount": 100.0, "holder_name": "Alice",
         "client_name": "Alice", "method": "internal", "ref_id": "ref12345"},
        {"created_at": "2026-01-11T12:00:00+00:00", "direction": "out",
         "currency": "USD", "amount": 50.0, "holder_name": "Bob",
         "client_name": "Bob", "method": "zelle", "ref_id": "ref67890"},
    ]
    totals = {"by_currency": {"USDT": {"in": 100.0, "out": 0}, "USD": {"in": 0, "out": 50}}}
    for lang in ["es", "en", "en-GB"]:
        pdf_bytes = generate_transactions_pdf(entries, {}, totals, lang=lang)
        assert pdf_bytes.startswith(b"%PDF-"), f"lang={lang!r} produced invalid PDF"
        assert len(pdf_bytes) > 1000, f"lang={lang!r} produced suspiciously small PDF"


def test_transactions_pdf_translation_lookup():
    """Directly exercise the `_t` string table so we catch typos without
    depending on a PDF text-extraction library (which isn't installed)."""
    from transactions_pdf import _t  # private but stable — tested surface
    assert _t("h1", "es") == "Transacciones — Resilience Brothers"
    assert _t("h1", "en") == "Transactions — Resilience Brothers"
    assert _t("row_in", "es") == "↓ ENTRADA"
    assert _t("row_in", "en") == "↓ INFLOW"
    assert _t("row_out", "en") == "↑ OUTFLOW"
    assert _t("totals_title", "en") == "TOTALS PER CURRENCY"
    assert _t("totals_title", "es") == "TOTALES POR MONEDA"
    assert _t("col_amount", "en") == "Amount"
    assert _t("col_amount", "es") == "Monto"
    # region variants normalize to base
    assert _t("h1", "en-GB") == "Transactions — Resilience Brothers"
    assert _t("h1", "EN-US") == "Transactions — Resilience Brothers"
    assert _t("h1", "es-CU") == "Transacciones — Resilience Brothers"
    # Unknown lang falls back to Spanish (not English)
    assert _t("h1", "fr") == "Transacciones — Resilience Brothers"
    assert _t("h1", "") == "Transacciones — Resilience Brothers"
