"""iter184 — Saved crypto addresses CRUD + validation."""
import os
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, VIP_TOKEN

API = f"{BASE_URL}/api"
TRC20_ADDR = "TJRabRWQdrJc7iCPFy4gnPCJcXbc17ncCk"
BEP20_ADDR = "0x1234567890abcdef1234567890abcdef12345678"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _cleanup():
    MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]].crypto_addresses.delete_many(
        {"user_id": "user_test_vip01"})


def test_save_list_delete_address_flow():
    _cleanup()
    try:
        r = requests.post(f"{API}/vip/crypto-addresses", headers=_hdr(VIP_TOKEN),
                          json={"label": "Mi Binance", "address": TRC20_ADDR, "network": "TRC20"})
        assert r.status_code == 200, r.text
        aid = r.json()["id"]
        assert r.json()["label"] == "Mi Binance"

        r = requests.get(f"{API}/vip/crypto-addresses", headers=_hdr(VIP_TOKEN))
        assert r.status_code == 200
        items = r.json()["items"]
        assert any(i["id"] == aid for i in items)

        r = requests.delete(f"{API}/vip/crypto-addresses/{aid}", headers=_hdr(VIP_TOKEN))
        assert r.status_code == 200

        r = requests.delete(f"{API}/vip/crypto-addresses/{aid}", headers=_hdr(VIP_TOKEN))
        assert r.status_code == 404
    finally:
        _cleanup()


def test_save_rejects_network_mismatch():
    _cleanup()
    try:
        r = requests.post(f"{API}/vip/crypto-addresses", headers=_hdr(VIP_TOKEN),
                          json={"label": "Mal", "address": TRC20_ADDR, "network": "BEP20"})
        assert r.status_code == 400, r.text
        r = requests.post(f"{API}/vip/crypto-addresses", headers=_hdr(VIP_TOKEN),
                          json={"label": "Mal", "address": BEP20_ADDR, "network": "SOLANA"})
        assert r.status_code == 400, r.text
    finally:
        _cleanup()


def test_save_rejects_duplicate():
    _cleanup()
    try:
        body = {"label": "Uno", "address": BEP20_ADDR, "network": "BEP20"}
        r = requests.post(f"{API}/vip/crypto-addresses", headers=_hdr(VIP_TOKEN), json=body)
        assert r.status_code == 200, r.text
        r = requests.post(f"{API}/vip/crypto-addresses", headers=_hdr(VIP_TOKEN), json=body)
        assert r.status_code == 409, r.text
    finally:
        _cleanup()


def test_requires_auth():
    r = requests.get(f"{API}/vip/crypto-addresses")
    assert r.status_code in (401, 403)
