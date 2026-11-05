"""iter393 — Estadísticas de empresas FASE 2 (análisis y exportación).

Cubre:
  - GET /api/admin/company-stats/trend (día/semana/mes)
  - Comparativa período-sobre-período + concentración en /summary
  - Exportación CSV: /export/companies.csv|products.csv|municipalities.csv
Verifica: autorización (deny-by-default), que el export es SOLO LECTURA,
que incluye corte/filtros/cobertura y el dataset COMPLETO (no sólo la página),
y que la tendencia agrupa correctamente por el bucket pedido.
"""
import csv
import io
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


EXPORTS = ["companies.csv", "products.csv", "municipalities.csv"]


# --- trend ----------------------------------------------------------------
def test_trend_anon_401():
    assert requests.get(f"{API}/admin/company-stats/trend").status_code == 401


def test_trend_buckets_admin_ok():
    for bucket in ("day", "week", "month"):
        r = requests.get(f"{API}/admin/company-stats/trend",
                         headers=_h(ADMIN_TOKEN), params={"bucket": bucket})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["bucket"] == bucket
        assert d["currency"] == "USDT"
        assert isinstance(d["rows"], list)
        for row in d["rows"]:
            assert {"label", "commission_usdt", "reversed_usdt", "orders"} <= set(row)
        # labels ordenados ascendentemente
        labels = [row["label"] for row in d["rows"]]
        assert labels == sorted(labels)


def test_trend_employee_without_permission_forbidden():
    r = requests.get(f"{API}/admin/company-stats/trend", headers=_h(EMPLOYEE_TOKEN))
    assert r.status_code == 403, r.text


def test_trend_sum_matches_summary_net_commission():
    """La suma de la comisión neta de todos los buckets == comisión neta del summary."""
    params = {"since": "2026-01-01", "until": "2026-12-31"}
    tr = requests.get(f"{API}/admin/company-stats/trend",
                      headers=_h(ADMIN_TOKEN), params={**params, "bucket": "month"}).json()
    summ = requests.get(f"{API}/admin/company-stats/summary",
                        headers=_h(ADMIN_TOKEN), params=params).json()
    trend_net = round(sum(r["commission_usdt"] for r in tr["rows"]), 2)
    assert abs(trend_net - summ["economic"]["net_commission_usdt"]) < 1e-2, (trend_net, summ["economic"])


# --- comparativa + concentración -----------------------------------------
def test_summary_comparison_block():
    r = requests.get(f"{API}/admin/company-stats/summary", headers=_h(ADMIN_TOKEN),
                     params={"since": "2026-10-01", "until": "2026-10-31"})
    assert r.status_code == 200, r.text
    d = r.json()
    comp = d.get("comparison")
    assert comp is not None, "con rango de fechas debe haber comparativa"
    assert {"previous_since", "previous_until", "previous_net_commission_usdt",
            "delta_usdt", "delta_pct"} <= set(comp)
    # El período anterior comparable termina el día antes del inicio actual.
    assert comp["previous_until"] == "2026-09-30"


def test_summary_no_comparison_without_dates():
    r = requests.get(f"{API}/admin/company-stats/summary", headers=_h(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert r.json().get("comparison") is None


def test_summary_has_concentration_key():
    r = requests.get(f"{API}/admin/company-stats/summary", headers=_h(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    # La clave existe siempre; es None cuando no hay comisión atribuida a empresas.
    assert "concentration" in r.json()


# --- exportación CSV ------------------------------------------------------
def test_exports_anon_401():
    for path in EXPORTS:
        assert requests.get(f"{API}/admin/company-stats/export/{path}").status_code == 401, path


def test_exports_employee_without_permission_forbidden():
    for path in EXPORTS:
        r = requests.get(f"{API}/admin/company-stats/export/{path}", headers=_h(EMPLOYEE_TOKEN))
        assert r.status_code == 403, f"{path}: {r.text}"


def test_exports_employee_with_permission_allowed():
    with _employee_with_permission("company_funds"):
        for path in EXPORTS:
            r = requests.get(f"{API}/admin/company-stats/export/{path}", headers=_h(EMPLOYEE_TOKEN))
            assert r.status_code == 200, f"{path}: {r.text}"


def test_export_csv_headers_and_metadata():
    r = requests.get(f"{API}/admin/company-stats/export/companies.csv",
                     headers=_h(ADMIN_TOKEN), params={"since": "2026-10-01", "until": "2026-10-31"})
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    assert ".csv" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    flat = "\n".join(",".join(c for c in row) for row in rows)
    # Metadatos obligatorios del plan: hora de generación, zona de negocio,
    # moneda, filtros y cobertura (EST-R04/R10: es hora de generación, no un corte).
    assert "hora de generacion UTC" in flat
    assert "Zona horaria de negocio" in flat
    assert "USDT" in flat
    assert "2026-10-01" in flat and "2026-10-31" in flat
    assert "Cobertura" in flat
    # Incluye fila de totales (dataset completo, no sólo la página).
    assert any(row and row[0] == "TOTAL" for row in rows)


def test_export_products_kind_services():
    r = requests.get(f"{API}/admin/company-stats/export/products.csv",
                     headers=_h(ADMIN_TOKEN), params={"kind": "services"})
    assert r.status_code == 200, r.text
    text = r.content.decode("utf-8-sig")
    assert "Servicios" in text


def test_exports_do_not_mutate_data():
    db = _db()
    before = {
        "redemptions": db.redemptions.count_documents({}),
        "deliveries": db.deliveries.count_documents({}),
        "service_bookings": db.service_bookings.count_documents({}),
    }
    for path in EXPORTS:
        requests.get(f"{API}/admin/company-stats/export/{path}", headers=_h(ADMIN_TOKEN))
    after = {k: db[k].count_documents({}) for k in before}
    assert before == after, (before, after)
