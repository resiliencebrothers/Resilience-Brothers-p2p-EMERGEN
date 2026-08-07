"""iter150 — QR poster global settings.

Verifies:
1. Public GET returns the empty default when nothing is configured yet.
2. Staff PUT persists the heading + promo and returns the trimmed values.
3. Anonymous PUT is rejected with 401.
4. Normal (non-staff) PUT is rejected with 403.
5. Payload length is enforced (heading ≤60, promo ≤80).
6. Public GET reads whatever the staff PUT saved (cross-session visibility).
"""
import os

import pytest
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def _reset_qr_poster():
    _db().settings.delete_one({"id": "qr_poster"})
    yield
    _db().settings.delete_one({"id": "qr_poster"})


def test_public_get_returns_empty_defaults():
    r = requests.get(f"{API}/qr-poster")
    assert r.status_code == 200
    body = r.json()
    assert body == {"heading": "", "promo": ""}


def test_admin_put_persists_and_public_get_reflects_it():
    r = requests.put(
        f"{API}/qr-poster",
        headers=_hdr(ADMIN_TOKEN),
        json={"heading": "  Escanea aquí  ", "promo": "  10% DE DESCUENTO EN JUNIO  "},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["heading"] == "Escanea aquí"
    assert body["promo"] == "10% DE DESCUENTO EN JUNIO"

    # Anonymous GET picks up the freshly-saved values.
    r2 = requests.get(f"{API}/qr-poster")
    assert r2.status_code == 200
    assert r2.json() == {"heading": "Escanea aquí", "promo": "10% DE DESCUENTO EN JUNIO"}


def test_employee_put_is_allowed():
    r = requests.put(
        f"{API}/qr-poster",
        headers=_hdr(EMPLOYEE_TOKEN),
        json={"heading": "Staff heading", "promo": "Promo staff"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["heading"] == "Staff heading"


def test_anonymous_put_returns_401():
    r = requests.put(
        f"{API}/qr-poster",
        headers={"Content-Type": "application/json"},
        json={"heading": "hack", "promo": "hack promo"},
    )
    assert r.status_code == 401


def test_non_staff_put_returns_403():
    r = requests.put(
        f"{API}/qr-poster",
        headers=_hdr(NORMAL_TOKEN),
        json={"heading": "hack", "promo": "hack promo"},
    )
    assert r.status_code == 403


def test_over_length_heading_rejected():
    r = requests.put(
        f"{API}/qr-poster",
        headers=_hdr(ADMIN_TOKEN),
        json={"heading": "X" * 61, "promo": "ok"},
    )
    assert r.status_code == 422


def test_over_length_promo_rejected():
    r = requests.put(
        f"{API}/qr-poster",
        headers=_hdr(ADMIN_TOKEN),
        json={"heading": "ok", "promo": "Y" * 81},
    )
    assert r.status_code == 422


def test_empty_body_clears_stored_values():
    # First save something
    requests.put(
        f"{API}/qr-poster",
        headers=_hdr(ADMIN_TOKEN),
        json={"heading": "Old title", "promo": "Old promo"},
    )
    # Then blank it
    r = requests.put(
        f"{API}/qr-poster",
        headers=_hdr(ADMIN_TOKEN),
        json={"heading": "", "promo": ""},
    )
    assert r.status_code == 200
    assert r.json() == {"heading": "", "promo": ""}
    assert requests.get(f"{API}/qr-poster").json() == {"heading": "", "promo": ""}
