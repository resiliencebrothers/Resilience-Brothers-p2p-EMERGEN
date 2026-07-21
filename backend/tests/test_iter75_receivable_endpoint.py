"""iter75 — Backend tests for `GET /api/currencies/{code}/receivable`.

Verifies:
 1. Returns 404 when the source currency does not exist.
 2. Returns the exact list of `to_code` values that have a rate FROM the
    source currency (strict direct — inverse rates are NOT considered).
 3. Deduplicates and sorts alphabetically.
 4. Empty list is returned (not 404) when the currency exists but has no
    outbound rates.
"""
import os
import uuid
import pytest
import requests
from pymongo import MongoClient

BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BACKEND_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BACKEND_URL = line.split("=", 1)[1].strip()
                break
API = f"{BACKEND_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
if not MONGO_URL or not DB_NAME:
    with open("/app/backend/.env") as f:
        for line in f:
            if line.startswith("MONGO_URL="):
                MONGO_URL = line.split("=", 1)[1].strip()
            if line.startswith("DB_NAME="):
                DB_NAME = line.split("=", 1)[1].strip()


PREFIX = "ITER75TEST"


@pytest.fixture
def db():
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


@pytest.fixture
def sample_pair(db):
    """Insert a source currency plus 3 destinations plus 3 rates FROM the source,
    and a 4th destination that only has an INVERSE rate. Cleaned up afterwards."""
    src_code = f"{PREFIX}SRC"
    dst_a = f"{PREFIX}DA"
    dst_b = f"{PREFIX}DB"
    dst_c = f"{PREFIX}DC"
    dst_inverse = f"{PREFIX}INV"

    def _cur(code, name):
        return {"id": uuid.uuid4().hex, "code": code, "name": name,
                "type": "fiat", "is_active": True}

    db.currencies.insert_many([
        _cur(src_code, "iter75 source"),
        _cur(dst_a, "iter75 dest A"),
        _cur(dst_b, "iter75 dest B"),
        _cur(dst_c, "iter75 dest C"),
        _cur(dst_inverse, "iter75 inverse only"),
    ])
    db.rates.insert_many([
        {"id": uuid.uuid4().hex, "from_code": src_code, "to_code": dst_a,
         "rate_normal": 1.0, "rate_vip": 1.0},
        {"id": uuid.uuid4().hex, "from_code": src_code, "to_code": dst_b,
         "rate_normal": 2.0, "rate_vip": 2.0},
        {"id": uuid.uuid4().hex, "from_code": src_code, "to_code": dst_c,
         "rate_normal": 3.0, "rate_vip": 3.0},
        # duplicate to check dedup (should not happen in practice but be safe)
        {"id": uuid.uuid4().hex, "from_code": src_code, "to_code": dst_a,
         "rate_normal": 1.5, "rate_vip": 1.5},
        # inverse-only pair — must NOT appear in the response
        {"id": uuid.uuid4().hex, "from_code": dst_inverse, "to_code": src_code,
         "rate_normal": 4.0, "rate_vip": 4.0},
    ])

    yield {
        "src": src_code,
        "expected": sorted([dst_a, dst_b, dst_c]),
        "inverse_only": dst_inverse,
    }

    db.rates.delete_many({"$or": [
        {"from_code": {"$regex": f"^{PREFIX}"}},
        {"to_code": {"$regex": f"^{PREFIX}"}},
    ]})
    db.currencies.delete_many({"code": {"$regex": f"^{PREFIX}"}})


def test_returns_404_for_unknown_currency():
    r = requests.get(f"{API}/currencies/{PREFIX}DOES_NOT_EXIST/receivable")
    assert r.status_code == 404


def test_returns_only_direct_rates(sample_pair):
    r = requests.get(f"{API}/currencies/{sample_pair['src']}/receivable")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == sample_pair["src"]
    assert body["receivable"] == sample_pair["expected"]
    assert body["count"] == 3
    # Sanity — the inverse-only destination MUST be absent.
    assert sample_pair["inverse_only"] not in body["receivable"]


def test_receivable_is_sorted_alphabetically(sample_pair):
    r = requests.get(f"{API}/currencies/{sample_pair['src']}/receivable")
    body = r.json()
    assert body["receivable"] == sorted(body["receivable"])


def test_returns_empty_list_when_no_rates(db):
    """Currency exists but has zero outbound rates."""
    code = f"{PREFIX}LONE"
    db.currencies.insert_one({
        "id": uuid.uuid4().hex, "code": code, "name": "iter75 loner",
        "type": "fiat", "is_active": True,
    })
    try:
        r = requests.get(f"{API}/currencies/{code}/receivable")
        assert r.status_code == 200
        body = r.json()
        assert body["receivable"] == []
        assert body["count"] == 0
    finally:
        db.currencies.delete_one({"code": code})


def test_endpoint_is_public_no_auth_required(sample_pair):
    """No cookies, no headers — endpoint must respond 200."""
    r = requests.get(
        f"{API}/currencies/{sample_pair['src']}/receivable",
        cookies={},
    )
    assert r.status_code == 200


def test_code_normalisation_uppercases_input():
    """Lowercase and whitespace-padded input must still resolve."""
    # Use a known existing currency like USDT — safe read-only test.
    for variant in ["usdt", "USDT", " usdt ", "Usdt"]:
        r = requests.get(f"{API}/currencies/{variant.strip()}/receivable")
        assert r.status_code in (200, 404), f"variant {variant!r} → {r.status_code}"
        if r.status_code == 200:
            assert r.json()["code"] == "USDT"
