"""iter392 — Estadísticas de empresas (Fondo de empresa > Ingresos), FASE 1.

Cubre los 4 endpoints de SOLO LECTURA:
  GET /api/admin/company-stats/summary|companies|products|municipalities
Verifica: autorización por permiso (deny-by-default), identidad de conciliación
(empresas + sin atribuir = total elegible), estructura de rankings, y que
consultar NO modifica datos (solo lectura).
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


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@contextmanager
def _employee_with_permission(code):
    db = _db()
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


ENDPOINTS = ["summary", "companies", "products", "municipalities"]


# --- autorización ---------------------------------------------------------
def test_endpoints_anon_401():
    for ep in ENDPOINTS:
        assert requests.get(f"{API}/admin/company-stats/{ep}").status_code == 401, ep


def test_endpoints_admin_ok():
    for ep in ENDPOINTS:
        r = requests.get(f"{API}/admin/company-stats/{ep}", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, f"{ep}: {r.text}"


def test_endpoints_employee_without_permission_forbidden():
    for ep in ENDPOINTS:
        r = requests.get(f"{API}/admin/company-stats/{ep}", headers=_h(EMPLOYEE_TOKEN))
        assert r.status_code == 403, f"{ep}: {r.text}"


def test_endpoints_employee_with_permission_allowed():
    with _employee_with_permission("company_funds"):
        for ep in ENDPOINTS:
            r = requests.get(f"{API}/admin/company-stats/{ep}", headers=_h(EMPLOYEE_TOKEN))
            assert r.status_code == 200, f"{ep}: {r.text}"


# --- estructura y conciliación -------------------------------------------
def test_summary_structure_and_reconciliation():
    r = requests.get(f"{API}/admin/company-stats/summary", headers=_h(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["currency"] == "USDT"
    for grp in ("economic", "operational", "messaging", "reconciliation", "coverage"):
        assert grp in d, grp
    rec = d["reconciliation"]
    # Identidad: empresas + sin atribuir == total elegible (tolerancia flotante)
    assert abs((rec["companies_commission_usdt"] + rec["unattributed_commission_usdt"])
               - rec["total_eligible_commission_usdt"]) < 1e-6
    assert rec["balanced"] is True


def test_companies_reconciliation_identity():
    r = requests.get(f"{API}/admin/company-stats/companies",
                     headers=_h(ADMIN_TOKEN), params={"limit": 500})
    assert r.status_code == 200, r.text
    d = r.json()
    companies_sum = sum(row["commission_usdt"] for row in d["rows"])
    # Nota: rows está limitado; la identidad exacta se valida con totals.
    assert "unattributed" in d and "totals" in d
    total = d["totals"]["commission_usdt"]
    unatt = d["unattributed"]["commission_usdt"]
    # companies_sum (todas las filas, limit=500) + unatt == total
    assert abs((companies_sum + unatt) - total) < 1e-6, (companies_sum, unatt, total)


def test_products_and_services_shape():
    for kind in ("products", "services"):
        r = requests.get(f"{API}/admin/company-stats/products",
                         headers=_h(ADMIN_TOKEN), params={"kind": kind, "limit": 10})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["kind"] == kind
        assert isinstance(d["rows"], list)
        for row in d["rows"]:
            assert {"id", "name", "company", "quantity", "gross_usdt", "orders"} <= set(row)


def test_municipalities_shape():
    r = requests.get(f"{API}/admin/company-stats/municipalities",
                     headers=_h(ADMIN_TOKEN), params={"limit": 50})
    assert r.status_code == 200, r.text
    d = r.json()
    assert isinstance(d["rows"], list)
    assert "total_completed" in d
    for row in d["rows"]:
        assert {"province", "municipality", "completed", "registered"} <= set(row)


def test_invalid_date_returns_400():
    r = requests.get(f"{API}/admin/company-stats/summary",
                     headers=_h(ADMIN_TOKEN), params={"since": "not-a-date"})
    assert r.status_code == 400, r.text


# --- solo lectura ---------------------------------------------------------
def test_stats_do_not_mutate_data():
    db = _db()
    before = {
        "redemptions": db.redemptions.count_documents({}),
        "deliveries": db.deliveries.count_documents({}),
        "company_fund_adjustments": db.company_fund_adjustments.count_documents({}),
        "service_bookings": db.service_bookings.count_documents({}),
    }
    for ep in ENDPOINTS:
        requests.get(f"{API}/admin/company-stats/{ep}",
                     headers=_h(ADMIN_TOKEN), params={"since": "2026-01-01", "until": "2026-12-31"})
    after = {k: db[k].count_documents({}) for k in before}
    assert before == after, (before, after)
