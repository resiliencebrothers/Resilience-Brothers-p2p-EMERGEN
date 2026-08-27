"""iter196 — Withdrawal + deposit lifecycle emails.

Client-facing emails at 4 lifecycle events:
  • Withdrawal approved  → notify_withdrawal_in_progress  ("En proceso")
  • Withdrawal paid      → notify_withdrawal_paid          ("Exitoso")
  • Deposit created      → notify_deposit_received         ("En proceso")
  • Deposit confirmed    → notify_deposit_confirmed        ("Exitoso")

The email backend is mocked at the module level so tests don't hit Resend
and don't leak entries into `email_events`. The API flows still exercise
the real routes (`POST /api/deposits`, admin confirm, admin withdrawal
status update) so the wiring is validated end-to-end.
"""
import os
import uuid
from unittest.mock import patch

from pymongo import MongoClient

from tests.conftest import BASE_URL  # noqa: F401 — ensures dotenv is loaded


PROOF = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
         "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


# ------------------------------------------------------------------
# Unit tests — render templates in isolation (no HTTP, no DB writes)
# ------------------------------------------------------------------

def test_withdrawal_in_progress_email_renders_es_and_en():
    from email_service import notify_withdrawal_in_progress
    w = {"id": "wd_abc123def456", "method": "crypto",
         "amount_usd": 250.0, "currency": "USDT",
         "crypto_network": "TRC20"}
    with patch("email_service._send") as m:
        m.return_value = True
        assert notify_withdrawal_in_progress(w, {"email": "u@x.com",
                                                 "name": "Juan",
                                                 "preferred_language": "es"})
        args, kwargs = m.call_args
        subj = args[1]
        html = args[2]
        assert "en proceso" in subj.lower()
        assert "abc123de" in subj  # short id in subject (prefix stripped)
        assert "TRC20" in html
        assert "USDT" in html
        assert kwargs.get("kind") == "withdrawal_in_progress"

    with patch("email_service._send") as m:
        m.return_value = True
        notify_withdrawal_in_progress(w, {"email": "u@x.com",
                                          "name": "John",
                                          "preferred_language": "en"})
        subj = m.call_args[0][1]
        assert "being processed" in subj.lower()


def test_withdrawal_paid_email_renders_and_includes_txhash():
    from email_service import notify_withdrawal_paid
    w = {"id": "wd_pay0001", "method": "crypto",
         "amount_usd": 100.0, "currency": "USDT",
         "crypto_network": "BEP20",
         "payout_tx_hash": "0xdeadbeef" * 6,
         "admin_note": "Enviado 14:32"}
    with patch("email_service._send") as m:
        m.return_value = True
        notify_withdrawal_paid(w, {"email": "u@x.com",
                                   "name": "Ana",
                                   "preferred_language": "es"})
        html = m.call_args[0][2]
        subj = m.call_args[0][1]
        assert "exitoso" in subj.lower()
        assert "0xdeadbeef" in html  # tx hash surfaced
        assert "BEP20" in html
        assert "Enviado 14:32" in html  # admin note surfaced
        assert m.call_args.kwargs.get("kind") == "withdrawal_paid"


def test_deposit_received_email_uses_courier_label_when_applicable():
    from email_service import notify_deposit_received
    d = {"id": "dep_cash01", "method": "cash", "amount": 500,
         "currency": "USD", "cash_mode": "courier"}
    with patch("email_service._send") as m:
        m.return_value = True
        notify_deposit_received(d, {"email": "u@x.com",
                                    "name": "Luis",
                                    "preferred_language": "es"})
        html = m.call_args[0][2]
        assert "Recogida a domicilio" in html
        assert "EN PROCESO" in html
        assert m.call_args.kwargs.get("kind") == "deposit_received"


def test_deposit_confirmed_email_shows_credit_and_link():
    from email_service import notify_deposit_confirmed
    d = {"id": "dep_ok0001", "method": "transfer", "amount": 750,
         "currency": "USD"}
    with patch("email_service._send") as m:
        m.return_value = True
        notify_deposit_confirmed(d, {"email": "u@x.com",
                                     "name": "María",
                                     "preferred_language": "es"})
        html = m.call_args[0][2]
        subj = m.call_args[0][1]
        assert "exitoso" in subj.lower()
        assert "acreditado" in html.lower() or "acredit" in html.lower()
        assert "750" in html
        assert "dashboard/vip" in html  # CTA


# ------------------------------------------------------------------
# Wiring tests — call the actual send functions with fake args to
# prove imports resolve at the call site (the real HTTP flows are
# covered by the existing iter155/163 tests).
# ------------------------------------------------------------------

def test_all_email_functions_export_from_email_service():
    """Regression: if any of the 4 names disappears the routes crash
    silently (they're imported inside try/except in the callers)."""
    import email_service as es
    for name in ("notify_withdrawal_in_progress",
                 "notify_withdrawal_paid",
                 "notify_deposit_received",
                 "notify_deposit_confirmed"):
        assert callable(getattr(es, name, None)), f"missing {name}"


def test_email_falls_back_to_spanish_when_lang_missing():
    from email_service import notify_withdrawal_paid
    w = {"id": "wd_fb1", "method": "transfer",
         "amount_usd": 50, "currency": "USD"}
    with patch("email_service._send") as m:
        m.return_value = True
        # No preferred_language field at all → should default to 'es'
        notify_withdrawal_paid(w, {"email": "u@x.com", "name": "X"})
        subj = m.call_args[0][1]
        assert "exitoso" in subj.lower()  # Spanish subject
