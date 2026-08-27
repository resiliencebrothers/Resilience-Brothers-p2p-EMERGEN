"""iter189 — Operativa VIP orders queue: free-text search + date range.

GET /admin/vip-batches?q=&date_from=&date_to= must filter by VIP name/email,
holder name, card number and created_at day range (inclusive).
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
TAG = "it189"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed():
    db = _db()
    db.users.update_one(
        {"user_id": f"vip_{TAG}"},
        {"$set": {"user_id": f"vip_{TAG}", "name": "Osvaldo Farres Quintana",
                  "email": f"osvaldo.{TAG}@test.com", "role": "vip"}},
        upsert=True)
    items = [
        {"id": f"vbi_{TAG}_1", "batch_id": f"vb_{TAG}", "vip_user_id": f"vip_{TAG}",
         "holder_name": "Caridad Ferrer Lopez", "card_number": "9224 0699 1234 5678",
         "amount": 100.0, "currency": "CUP", "direction": "credit",
         "from_code": "CUP", "to_code": "USDT", "status": "pending",
         "created_at": "2099-06-01T10:00:00+00:00"},
        {"id": f"vbi_{TAG}_2", "batch_id": f"vb_{TAG}", "vip_user_id": f"vip_{TAG}",
         "holder_name": "Ramona Diaz Sosa", "card_number": "9205 1299 8765 4321",
         "amount": 55.0, "currency": "CUP", "direction": "credit",
         "from_code": "CUP", "to_code": "USDT", "status": "pending",
         "created_at": "2099-06-10T10:00:00+00:00"},
    ]
    db.vip_batch_items.insert_many(items)


def _cleanup():
    db = _db()
    db.vip_batch_items.delete_many({"id": {"$regex": f"^vbi_{TAG}"}})
    db.users.delete_many({"user_id": f"vip_{TAG}"})


def setup_module():
    _cleanup()
    _seed()


def teardown_module():
    _cleanup()


def _list(**params):
    r = requests.get(f"{API}/admin/vip-batches", headers=_hdr(ADMIN_TOKEN),
                     params={"status": "pending", **params})
    assert r.status_code == 200, r.text
    return [i for i in r.json()["items"] if i["id"].startswith(f"vbi_{TAG}")]


def test_search_by_holder_name():
    items = _list(q="caridad ferrer")
    assert len(items) == 1 and items[0]["id"] == f"vbi_{TAG}_1"


def test_search_by_vip_name_and_email():
    assert len(_list(q="Osvaldo Farres")) == 2
    assert len(_list(q=f"osvaldo.{TAG}@test.com")) == 2


def test_search_by_card_number():
    items = _list(q="9205 1299")
    assert len(items) == 1 and items[0]["id"] == f"vbi_{TAG}_2"


def test_search_no_results():
    assert _list(q="zzz-no-existe-xyz") == []


def test_date_range_filters_inclusive():
    only_first = _list(date_from="2099-06-01", date_to="2099-06-01")
    assert [i["id"] for i in only_first] == [f"vbi_{TAG}_1"]
    both = _list(date_from="2099-06-01", date_to="2099-06-10")
    assert len(both) == 2
    only_second = _list(date_from="2099-06-02")
    assert [i["id"] for i in only_second] == [f"vbi_{TAG}_2"]


def test_search_and_date_combined():
    items = _list(q="Ramona", date_from="2099-06-01", date_to="2099-06-30")
    assert len(items) == 1 and items[0]["holder_name"] == "Ramona Diaz Sosa"
    assert _list(q="Ramona", date_to="2099-06-05") == []
