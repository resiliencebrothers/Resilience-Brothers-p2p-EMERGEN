"""iter391 — Autorización por permiso de los exports de la sección CONTABLE.

Extiende el patrón "sin permiso → 403 / con permiso → 200" (ya aplicado a
Transacciones en test_iter390/test_transactions_registry) a:

- Conciliación por cuenta (dentro de Cuentas de cobro):
    GET /api/admin/payment-accounts/reconciliation-summary(.export.csv)
    → permiso `payment_accounts`.
- Fondos de empresa:
    GET /api/admin/company-funds/export.csv
    GET /api/admin/company-funds/commissions/export.csv
    GET /api/admin/company-funds/closing.pdf
    → permiso `company_funds`.

Modelo (STAFF-01, deny-by-default): admin siempre pasa; un empleado accede
SÓLO si su `allowed_permissions` contiene el código; vacío/ausente no concede
nada. El helper concede el permiso al empleado compartido y RESTAURA su estado
original para no contaminar otros tests.
"""
import os
from contextlib import contextmanager

import requests
from pymongo import MongoClient

from tests.conftest import ADMIN_TOKEN, BASE_URL, EMPLOYEE_TOKEN

API = f"{BASE_URL}/api"
EMP_UID = "user_test_employee01"


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@contextmanager
def _employee_with_permission(code):
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    before = db.users.find_one({"user_id": EMP_UID}, {"_id": 0, "allowed_permissions": 1}) or {}
    had = "allowed_permissions" in before
    db.users.update_one({"user_id": EMP_UID}, {"$set": {"allowed_permissions": [code]}})
    try:
        yield
    finally:
        if had:
            db.users.update_one({"user_id": EMP_UID},
                                {"$set": {"allowed_permissions": before["allowed_permissions"]}})
        else:
            db.users.update_one({"user_id": EMP_UID}, {"$unset": {"allowed_permissions": ""}})


# Cada caso: (ruta, permiso requerido, content-type esperado con permiso)
RECON = "/admin/payment-accounts/reconciliation-summary/export.csv"
FUNDS_CSV = "/admin/company-funds/export.csv"
FUNDS_COMMISSIONS = "/admin/company-funds/commissions/export.csv"
FUNDS_CLOSING = "/admin/company-funds/closing.pdf"


# ---------------------------------------------------------------------------
# Conciliación por cuenta (permiso payment_accounts)
# ---------------------------------------------------------------------------
def test_reconciliation_export_anon_401():
    assert requests.get(f"{API}{RECON}").status_code == 401


def test_reconciliation_export_admin_ok():
    r = requests.get(f"{API}{RECON}", headers=_h(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers.get("Content-Type", "")


def test_reconciliation_export_employee_without_permission_forbidden():
    r = requests.get(f"{API}{RECON}", headers=_h(EMPLOYEE_TOKEN))
    assert r.status_code == 403, r.text


def test_reconciliation_export_employee_with_permission_allowed():
    with _employee_with_permission("payment_accounts"):
        r = requests.get(f"{API}{RECON}", headers=_h(EMPLOYEE_TOKEN))
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers.get("Content-Type", "")


def test_reconciliation_summary_employee_requires_permission():
    # El JSON del panel usa el mismo gate que su export.
    base = "/admin/payment-accounts/reconciliation-summary"
    denied = requests.get(f"{API}{base}", headers=_h(EMPLOYEE_TOKEN))
    assert denied.status_code == 403, denied.text
    with _employee_with_permission("payment_accounts"):
        ok = requests.get(f"{API}{base}", headers=_h(EMPLOYEE_TOKEN))
    assert ok.status_code == 200, ok.text


# ---------------------------------------------------------------------------
# Fondos de empresa (permiso company_funds)
# ---------------------------------------------------------------------------
def test_company_funds_csv_anon_401():
    assert requests.get(f"{API}{FUNDS_CSV}").status_code == 401


def test_company_funds_csv_admin_ok():
    r = requests.get(f"{API}{FUNDS_CSV}", headers=_h(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers.get("Content-Type", "")


def test_company_funds_csv_employee_without_permission_forbidden():
    r = requests.get(f"{API}{FUNDS_CSV}", headers=_h(EMPLOYEE_TOKEN))
    assert r.status_code == 403, r.text


def test_company_funds_csv_employee_with_permission_allowed():
    with _employee_with_permission("company_funds"):
        r = requests.get(f"{API}{FUNDS_CSV}", headers=_h(EMPLOYEE_TOKEN))
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers.get("Content-Type", "")


def test_company_commissions_csv_employee_without_permission_forbidden():
    r = requests.get(f"{API}{FUNDS_COMMISSIONS}", headers=_h(EMPLOYEE_TOKEN))
    assert r.status_code == 403, r.text


def test_company_commissions_csv_employee_with_permission_allowed():
    with _employee_with_permission("company_funds"):
        r = requests.get(f"{API}{FUNDS_COMMISSIONS}", headers=_h(EMPLOYEE_TOKEN))
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers.get("Content-Type", "")


def test_company_closing_pdf_employee_without_permission_forbidden():
    r = requests.get(f"{API}{FUNDS_CLOSING}", headers=_h(EMPLOYEE_TOKEN))
    assert r.status_code == 403, r.text


def test_company_closing_pdf_employee_with_permission_allowed():
    with _employee_with_permission("company_funds"):
        r = requests.get(f"{API}{FUNDS_CLOSING}", headers=_h(EMPLOYEE_TOKEN))
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF-")
