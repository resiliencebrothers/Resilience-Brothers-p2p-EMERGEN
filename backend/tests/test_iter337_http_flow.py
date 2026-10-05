"""iter337 — Smoke HTTP del fix H02 (fracción no truncada) sobre el URL público.

Reproduce el caso del auditor por API real (cookie session_token):
- Inserta producto fraccionario de prueba (10 lb @ 20 CUP/lb) directo en Mongo.
- POST /api/admin/inventory/counts con counted_qty=9.25.
- GET /api/admin/inventory/cutoff-report (JSON) y .csv.
- GET /api/admin/inventory/incidents?type=diferencia.
- Limpia al final.
"""
import os
import csv
import io
import uuid
import asyncio

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
COOKIE = {"session_token": "smoke_fp4_admin"}


@pytest.fixture(scope="module")
def product_id():
    pid = f"TEST_IPV337H_{uuid.uuid4().hex[:8]}"
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]

    async def _setup():
        await db.products.insert_one({
            "id": pid, "name": pid, "category": "test",
            "price_usd": 40.0, "cost_usd": 20.0,
            "stock": 10.0, "unit": "libra", "is_active": True,
        })

    async def _teardown():
        await db.products.delete_many({"id": pid})
        await db.inventory_counts.delete_many({"product_id": pid})
        await db.inventory_incidents.delete_many({"product_id": pid})
        await db.inventory_movements.delete_many({"product_id": pid})
        await db.inventory_lots.delete_many({"product_id": pid})
        await db.stock_ops.delete_many({"product_id": pid})

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_setup())
        yield pid
        loop.run_until_complete(_teardown())
    finally:
        loop.close()
        cli.close()


def test_post_count_fraction(product_id):
    r = requests.post(
        f"{BASE_URL}/api/admin/inventory/counts",
        json={"product_id": product_id, "counted_qty": 9.25},
        cookies=COOKIE, timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["difference"] == -0.75, data
    assert data["difference_value"] == -15.0, data
    assert data["unit"] == "libra"
    assert data["status"] == "faltante"


def test_cutoff_report_contains_fraction(product_id):
    r = requests.get(
        f"{BASE_URL}/api/admin/inventory/cutoff-report",
        cookies=COOKIE, timeout=30,
    )
    assert r.status_code == 200, r.text
    rep = r.json()
    row = next((p for p in rep["products"]
                if p["product_id"] == product_id), None)
    assert row is not None, "producto con conteo debe aparecer en el corte"
    cb = row["count"]
    assert cb is not None
    assert cb["difference"] == -0.75, f"no debe truncarse a 0: {cb}"
    assert cb["difference_value"] == -15.0, cb
    assert cb["unit"] == "libra", cb


def test_cutoff_report_csv_contains_fraction(product_id):
    r = requests.get(
        f"{BASE_URL}/api/admin/inventory/cutoff-report.csv",
        cookies=COOKIE, timeout=30,
    )
    assert r.status_code == 200, r.text
    text = r.text
    reader = csv.reader(io.StringIO(text))
    headers = next(reader)
    # Localiza columnas por nombre (tolerante a cambios de orden)
    def idx(name):
        for i, h in enumerate(headers):
            if h.strip().lower() == name.lower():
                return i
        return -1
    i_pid = idx("Producto ID") if idx("Producto ID") >= 0 else idx("product_id")
    i_diff = idx("Diferencia")
    i_dv = idx("Valor diferencia")
    assert i_diff >= 0 and i_dv >= 0, f"headers: {headers}"
    row = next((r for r in reader
                if (i_pid >= 0 and r[i_pid] == product_id)
                or product_id in r), None)
    assert row is not None, f"fila del producto {product_id} no encontrada en CSV"
    # Comparación tolerante a coma/punto como separador decimal
    diff_val = float(row[i_diff].replace(",", "."))
    dv_val = float(row[i_dv].replace(",", "."))
    assert diff_val == -0.75, (row, headers)
    assert dv_val == -15.0, (row, headers)


def test_incident_pending_not_autoresolved(product_id):
    r = requests.get(
        f"{BASE_URL}/api/admin/inventory/incidents",
        params={"type": "diferencia"},
        cookies=COOKIE, timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    items = data if isinstance(data, list) else data.get("items") or data.get("incidents") or []
    inc = next((i for i in items if i.get("product_id") == product_id), None)
    assert inc is not None, "una diferencia ≠ 0 debe generar incidencia"
    assert inc["status"] == "pendiente", f"NO debe auto-resolverse: {inc}"
    assert inc["amount"] == -15.0, inc
    assert "-0.75" in inc["detail"], inc["detail"]
    assert "lb" in inc["detail"], inc["detail"]
