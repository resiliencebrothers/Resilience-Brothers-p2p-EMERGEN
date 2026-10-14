"""Empresa Fase 1 — rol business, aprobación, tiendas y catálogo.

Cubre:
- Registro `account_type=business` => rol 'empresa' + account_status under_review
  (el rol NUNCA se acepta del cliente).
- `require_company`: /company/* devuelve 403 hasta que el admin aprueba (active).
- Tiendas 1:N aisladas por company_id y excluidas del listado público /stores.
- Catálogo: crear producto queda 'pending', aparece en la cola admin
  (/admin/vendor-products) y lleva owner_id + company_id de la Empresa.
- Publicación/edición VIP DESHABILITADA (403).
"""
import os
import uuid as _uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"

EMP_ID = "user_test_empresa01"
EMP_TOKEN = "test_session_empresa_X"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _seed_empresa(account_status="active"):
    db = _db()
    db.users.update_one(
        {"user_id": EMP_ID},
        {"$set": {
            "user_id": EMP_ID,
            "email": "empresa.test@example.com",
            "name": "Empresa Test",
            "role": "empresa",
            "account_status": account_status,
            "email_verified": True,
            "phone_verified": True,
            "phone": "+5350000123",
        }},
        upsert=True,
    )
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    db.user_sessions.update_one(
        {"session_token": EMP_TOKEN},
        {"$set": {"session_token": EMP_TOKEN, "user_id": EMP_ID, "expires_at": exp}},
        upsert=True,
    )


def _cleanup():
    db = _db()
    db.products.delete_many({"company_id": EMP_ID})
    db.stores.delete_many({"company_id": EMP_ID})
    db.users.delete_many({"email": {"$regex": r"^biz\.", "$options": "i"}})


# ------------------------------------------------------------------
# Registro
# ------------------------------------------------------------------

def test_register_business_sets_empresa_under_review():
    email = f"biz.{_uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(f"{API}/auth/register", json={
        "email": email,
        "password": "TestPass123!",
        "name": "Negocio Uno",
        "phone": "+5350001111",
        "account_type": "business",
    }, timeout=20)
    assert r.status_code in (200, 201), r.text
    db = _db()
    doc = db.users.find_one({"email": email})
    assert doc is not None
    assert doc.get("role") == "empresa"
    assert doc.get("account_status") == "under_review"
    db.users.delete_one({"email": email})


def test_register_rejects_client_supplied_role():
    """El cliente no puede autoasignarse un rol; solo cuenta account_type."""
    email = f"biz.{_uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(f"{API}/auth/register", json={
        "email": email,
        "password": "TestPass123!",
        "name": "Intruso",
        "phone": "+5350002222",
        "role": "admin",            # debe ignorarse
        "account_type": "personal",
    }, timeout=20)
    assert r.status_code in (200, 201), r.text
    db = _db()
    doc = db.users.find_one({"email": email})
    assert doc.get("role") == "normal"
    db.users.delete_one({"email": email})


# ------------------------------------------------------------------
# Gate de aprobación
# ------------------------------------------------------------------

def test_company_me_blocked_until_active():
    _seed_empresa(account_status="under_review")
    r = requests.get(f"{API}/company/me", headers=_hdr(EMP_TOKEN), timeout=15)
    assert r.status_code == 403, r.text

    _seed_empresa(account_status="active")
    r = requests.get(f"{API}/company/me", headers=_hdr(EMP_TOKEN), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["user_id"] == EMP_ID
    _cleanup()


def test_company_routes_reject_non_empresa():
    r = requests.get(f"{API}/company/me", headers=_hdr(NORMAL_TOKEN), timeout=15)
    assert r.status_code == 403, r.text


# ------------------------------------------------------------------
# Tiendas 1:N + aislamiento del listado público
# ------------------------------------------------------------------

def test_store_crud_and_public_isolation():
    _seed_empresa(account_status="active")
    # crear
    r = requests.post(f"{API}/company/stores", headers=_hdr(EMP_TOKEN), json={
        "name": "Sucursal Centro", "address": "Calle 1 #23, La Habana",
        "municipality": "Centro", "province": "La Habana",
    }, timeout=15)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert r.json()["company_id"] == EMP_ID

    # aparece en MIS tiendas
    r = requests.get(f"{API}/company/stores", headers=_hdr(EMP_TOKEN), timeout=15)
    assert sid in [s["id"] for s in r.json()]

    # NO aparece en el listado público de sucursales Resilience
    r = requests.get(f"{API}/stores", headers=_hdr(NORMAL_TOKEN), timeout=15)
    assert sid not in [s["id"] for s in r.json()]

    # NO aparece en la gestión admin de sucursales Resilience
    r = requests.get(f"{API}/admin/stores", headers=_hdr(ADMIN_TOKEN), timeout=15)
    assert sid not in [s["id"] for s in r.json()]

    # editar
    r = requests.put(f"{API}/company/stores/{sid}", headers=_hdr(EMP_TOKEN), json={
        "name": "Sucursal Centro 2", "address": "Calle 1 #23, La Habana",
    }, timeout=15)
    assert r.status_code == 200 and r.json()["name"] == "Sucursal Centro 2"

    # borrar
    r = requests.delete(f"{API}/company/stores/{sid}", headers=_hdr(EMP_TOKEN), timeout=15)
    assert r.status_code == 200
    _cleanup()


# ------------------------------------------------------------------
# Catálogo => cola de aprobación admin
# ------------------------------------------------------------------

def test_product_create_is_pending_and_in_admin_queue():
    _seed_empresa(account_status="active")
    r = requests.post(f"{API}/company/products", headers=_hdr(EMP_TOKEN), json={
        "name": "Café Empresa", "description": "250g", "price_usd": 4.5,
        "stock": 10, "category": "alimentos",
    }, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    pid = body["id"]
    assert body["approval_status"] == "pending"
    assert body["owner_id"] == EMP_ID

    db = _db()
    doc = db.products.find_one({"id": pid})
    assert doc.get("company_id") == EMP_ID

    # cola admin (owner_id presente => entra a vendor-products)
    r = requests.get(f"{API}/admin/vendor-products?status=pending",
                     headers=_hdr(ADMIN_TOKEN), timeout=15)
    assert r.status_code == 200, r.text
    assert pid in [p["id"] for p in r.json()]
    _cleanup()


def test_product_store_ids_must_belong_to_company():
    _seed_empresa(account_status="active")
    r = requests.post(f"{API}/company/products", headers=_hdr(EMP_TOKEN), json={
        "name": "Producto X", "price_usd": 2.0, "stock": 1,
        "available_store_ids": ["store-que-no-existe"],
    }, timeout=15)
    assert r.status_code == 400, r.text
    _cleanup()


# ------------------------------------------------------------------
# Publicación VIP deshabilitada
# ------------------------------------------------------------------

def test_vip_publishing_disabled():
    r = requests.post(f"{API}/vip/my-products", headers=_hdr(VIP_TOKEN), json={
        "name": "Producto VIP", "price_usd": 3.0, "stock": 1,
    }, timeout=15)
    assert r.status_code == 403, r.text

    r = requests.put(f"{API}/vip/my-products/anything", headers=_hdr(VIP_TOKEN), json={
        "name": "Editado",
    }, timeout=15)
    assert r.status_code == 403, r.text
