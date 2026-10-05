"""iter338 — HTTP smoke of cutoff-report CSV:
Verifies the new 'Unidad' column position and totals row alignment.
Seeds a 'libra' product with a physical count row (diff -0.75) and asserts
CSV output shows Unidad='lb', Costo ref.=20.0, Valor diferencia=-15.0.

Admin cookie: session_token=smoke_fp4_admin.
"""
import csv
import datetime as _dt
import io
import os
import uuid

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
COOKIES = {"session_token": "smoke_fp4_admin"}


@pytest.fixture
def seeded_lb_product():
    cli = MongoClient(os.environ["MONGO_URL"])
    dbh = cli[os.environ["DB_NAME"]]
    pid = f"TEST_IPV338CSV_{uuid.uuid4().hex[:6]}"
    pname = pid
    today = _dt.datetime.utcnow().strftime("%Y-%m-%d")
    now_iso = _dt.datetime.utcnow().isoformat() + "+00:00"

    dbh.products.insert_one({
        "id": pid, "name": pname, "category": "test", "price_usd": 50.0,
        "cost_usd": 20.0, "stock": 10.0, "unit": "libra", "is_active": True,
    })
    # Movement so product appears in cutoff report + a count row
    dbh.inventory_movements.insert_one({
        "id": str(uuid.uuid4()), "product_id": pid, "product_name": pname,
        "type": "entrada", "quantity": 10.0, "unit": "libra",
        "unit_price": 20.0, "unit_cost": 20.0, "total": 200.0,
        "cost_of_sale": 0.0, "profit": 0.0, "note": "seed",
        "source": "manual", "ref_id": "", "actor_id": "", "actor_email": "",
        "created_at": now_iso, "needs_stock": False, "stock_applied": True,
        "applied_at": now_iso,
    })
    dbh.inventory_counts.insert_one({
        "id": str(uuid.uuid4()), "product_id": pid, "product_name": pname,
        "counted_at": now_iso, "date": today, "count_date": today,
        "counted_qty": 9.25,
        "expected_qty": 10.0, "difference": -0.75, "reference_cost": 20.0,
        "value_difference": -15.0, "unit": "libra",
        "actor_id": "user_test_admin01",
        "actor_email": "admin.test@resilience.com",
    })
    yield pid, pname
    dbh.products.delete_many({"id": pid})
    dbh.inventory_movements.delete_many({"product_id": pid})
    dbh.inventory_counts.delete_many({"product_id": pid})
    dbh.inventory_incidents.delete_many({"product_id": pid})
    dbh.stock_ops.delete_many({"product_id": pid})
    dbh.inventory_lots.delete_many({"product_id": pid})


def test_csv_unidad_column_and_libra_row(seeded_lb_product):
    pid, pname = seeded_lb_product
    r = requests.get(f"{BASE_URL}/api/admin/inventory/cutoff-report.csv",
                     cookies=COOKIES, timeout=30)
    assert r.status_code == 200, r.text[:500]
    text = r.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))

    header_idx = next(i for i, row in enumerate(rows) if "Diferencia" in row)
    header = rows[header_idx]
    assert "Unidad" in header, header
    i_diff = header.index("Diferencia")
    i_unit = header.index("Unidad")
    i_cost = header.index("Costo ref.")
    i_val = header.index("Valor diferencia")
    assert i_unit == i_diff + 1
    assert i_cost == i_unit + 1

    prod_row = next((row for row in rows if row and row[0] == pname), None)
    assert prod_row is not None, f"product {pname} missing from CSV"
    assert prod_row[i_diff] == "-0.75"
    assert prod_row[i_unit] == "lb"
    assert prod_row[i_cost] == "20.0"
    assert prod_row[i_val] == "-15.0"

    totals_row = next(
        (row for row in rows if row and row[0].upper().startswith("TOTAL")),
        None,
    )
    assert totals_row is not None
    assert len(totals_row) == len(header), (
        f"TOTAL has {len(totals_row)} cols, header {len(header)}")


def test_cutoff_report_json_ok():
    r = requests.get(f"{BASE_URL}/api/admin/inventory/cutoff-report",
                     cookies=COOKIES, timeout=30)
    assert r.status_code == 200
    assert "products" in r.json()
